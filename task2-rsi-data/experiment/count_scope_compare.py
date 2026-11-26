"""Freeze and run the original, count-scope and mixed paired comparisons."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path
import re
import sys
import time

from count_scope_canvas import EXAMPLES, GRAPH, count_step, validate_count
from experiment import GRAPHS, ROOT, Scenario, execute_sql, samples_by_id, score, step_node, validate_graph
from projection_compare import EFFORTS, MODEL
from projection_exposure import exposure
from run import complete_at
from run_full_evaluation import digest, load, make_config, read_settings, save

OUT = ROOT / 'runs/task2-count-scope-v1'
SEED = 'count-scope-v1-20261126'
METHODS = ('baseline', 'canvas_v1')
CONDITIONS = [(method, effort) for method in METHODS for effort in EFFORTS]
COMPARISON = re.compile(r'\bHAVING\s+COUNT\s*\(\s*\*\s*\)\s*<=?\s*[1-9]', re.I)
JOIN = re.compile(r'\bJOIN\s+\w+\s+AS\s+(\w+)\s+ON\s+(\w+\.\w+)\s*=\s*(\w+\.\w+)', re.I)
ZERO_PAIRS = ('DB_schema_abbreviation-02606', 'NLQ_keyword_synonym-00799', 'NLQ_keyword_carrier-00209')
CONTROL_GROUPS = ('DB_DBcontent_equivalence', 'DB_schema_synonym', 'NLQ_column_attribute',
                  'NLQ_column_value', 'SQL_comparison', 'SQL_sort_order')


def extra_if_zero(row):
    sql = row['gold_sql']
    if row['group'] != 'SQL_comparison' or not COMPARISON.search(sql):
        return 0
    if re.match(r'\s*SELECT\s+COUNT\s*\([^)]*\)\s+FROM\b', sql, re.I):
        return 0
    match = JOIN.search(sql)
    if not match or len(re.findall(r'\bJOIN\b', sql, re.I)) != 1 or re.search(
        r'\b(?:WHERE|UNION|LEFT|RIGHT|OR)\b', sql, re.I
    ):
        return 0
    alias = match[1].casefold()
    detail_key = next((key for key in match.groups()[1:] if key.split('.')[0].casefold() == alias), '')
    if not detail_key:
        return 0
    variant = sql[:match.start()] + 'LEFT ' + sql[match.start():]
    variant = re.sub(r'\bCOUNT\s*\(\s*\*\s*\)', f'COUNT({detail_key})', variant, flags=re.I)
    gold, hypothetical = [execute_sql(row['database'], query) for query in (sql, variant)]
    if 'rows' not in gold or 'rows' not in hypothetical:
        return 0
    expected, observed = [Counter(map(tuple, result['rows'])) for result in (gold, hypothetical)]
    return sum((observed - expected).values()) if not (expected - observed) else 0


def freeze(samples):
    path = OUT / 'plan.json'
    if path.is_file():
        return load(path)
    exposed, surfaces, seen = exposure(samples)
    known = set(seen)
    ordering = sorted((s for s in samples.values() if s['side'] == 'post'),
                      key=lambda s: (s['id'][:-5] in known,
                                     sha256(f'{SEED}/{s["id"]}'.encode()).digest()))
    used = {samples[EXAMPLES[0]]['original_id']}
    cases = []
    per_db = Counter()

    def add(row, label, reason):
        stem = row['id'][:-5]
        cases.append({'pair': stem, 'original_id': row['original_id'], 'db_id': row['db_id'],
                      'group': row['group'], 'label': label, 'selection': reason,
                      'previously_run_variant': stem in known})
        used.add(row['original_id'])

    for row in ordering:
        if row['original_id'] in used or per_db[row['db_id']] >= 2:
            continue
        extra = extra_if_zero(row)
        if extra:
            add(row, 'target', {'reference_counterfactual_extra_rows': extra})
            per_db[row['db_id']] += 1
        if len(cases) == 8:
            break
    target_count = len(cases)
    if not target_count:
        raise ValueError('No matched detail-count cases')
    for stem in ZERO_PAIRS:
        row = samples[stem + '-post']
        if row['original_id'] not in used:
            add(row, 'control', 'explicit absence control')
    for group in CONTROL_GROUPS:
        row = next(s for s in ordering if s['group'] == group and s['original_id'] not in used
                   and not extra_if_zero(s))
        add(row, 'control', 'mixed perturbation')
    paths = [Path(__file__).with_name(name) for name in
             ('count_scope_canvas.py', 'count_scope_compare.py', 'experiment.py', 'run.py')]
    plan = {'seed': SEED, 'selected': cases, 'anchor': EXAMPLES,
            'target_count': target_count, 'observed_originals': len(exposed), 'exposure_surfaces': surfaces,
            'conditions': CONDITIONS, 'graph': GRAPH,
            'code_sha256': {str(path.relative_to(ROOT)): digest(path) for path in paths}}
    save(path, plan)
    return plan


def evaluate(case, method, effort, endpoint, key):
    path = OUT / 'records' / method / effort / (case.id + '.json')
    if path.is_file():
        return
    ordered, runner = ((validate_graph(GRAPHS['baseline']), step_node) if method == 'baseline'
                       else (validate_count(GRAPH), count_step))
    steps = {}

    def complete(node_id, payload):
        folder = OUT / 'requests' / method / effort / case.id / node_id
        request, response = folder / 'request.json', folder / 'response.json'
        payload = {**payload, 'reasoning_effort': effort}
        if request.is_file() and load(request) != payload:
            raise ValueError('Request differs from the frozen condition')
        save(request, payload)
        if response.is_file():
            return load(response)
        for attempt in range(2):
            try:
                answer = complete_at(endpoint, key, payload)
            except Exception as error:
                save(folder / f'failure-{attempt + 1}.json', {'error': str(error).replace(key, '[REDACTED]')})
                if attempt:
                    raise
                time.sleep(1)
            else:
                save(response, answer)
                return answer

    for node in ordered:
        result, call = runner(node, case, MODEL, [steps[parent] for parent in node['from']], complete)
        steps[node['id']] = {**node, 'output': result, 'call': call}
    usages = [step['call'].get('usage') or {} for step in steps.values() if step['call']]
    usage = {}
    for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        data = [row.get(field) for row in usages]
        if all(type(value) is int for value in data):
            usage[field] = sum(data)
    save(path, {'id': case.id, 'method': method, 'effort': effort, 'steps': list(steps.values()),
                'usage': usage, 'model_calls': len(usages),
                'score': score(case, list(steps.values())[-1]['output'])})


def main(mode):
    samples = samples_by_id()
    plan = freeze(samples)
    print('Frozen', Counter(row['label'] for row in plan['selected']), 'across',
          plan['observed_originals'], 'exposed originals', flush=True)
    for row in plan['selected']:
        print(row['label'], row['pair'], row['db_id'], row['selection'], flush=True)
    if mode == 'prepare':
        return 0
    if mode not in ('anchor', 'run'):
        raise ValueError('Use prepare, anchor or run')
    for name, sha in plan['code_sha256'].items():
        assert digest(ROOT / name) == sha, name
    ids = [*EXAMPLES, *(row['pair']+'-'+side for row in plan['selected'] for side in ('pre', 'post'))]
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    key = settings['THINGO_API_KEY']
    config = make_config([samples[n] for n in ids], MODEL, endpoint)
    config.update(reasoning_efforts=list(EFFORTS), plan_sha256=digest(OUT/'plan.json'), graph=GRAPH)
    cfg_path = OUT/'config.json'
    if cfg_path.is_file() and load(cfg_path) != config:
        raise ValueError('Experiment configuration differs from the frozen configuration')
    save(cfg_path, config)
    tasks = [(Scenario.from_id(sample), method, effort) for sample in (EXAMPLES if mode == 'anchor' else ids)
             for method, effort in CONDITIONS]
    failures, done = [], 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = {pool.submit(evaluate, *task, endpoint, key): (task[0].id, *task[1:]) for task in tasks}
        for future in as_completed(pending):
            try:
                future.result()
            except Exception as error:
                info = {'condition': pending[future], 'error': str(error).replace(key, '[REDACTED]')}
                failures.append(info)
                print(info, flush=True)
            else:
                done += 1
                if done % 8 == 0:
                    print(f'{done}/{len(tasks)} scored', flush=True)
    save(OUT/f'{mode}-failures.json', failures)
    print(f'{done}/{len(tasks)} scored, {len(failures)} transport/runner failures', flush=True)
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
