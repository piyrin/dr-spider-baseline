"""Run matched Thinking comparisons for the sort direction canvas."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path
import re
import sys
import time

from experiment import GRAPHS, ROOT, Scenario, samples_by_id, score, step_node, validate_graph
from projection_compare import EFFORTS, MODEL
from projection_exposure import exposure
from run import complete_at
from run_full_evaluation import digest, gold_rows, load, make_config, result_eq, read_settings, save
from sort_direction_canvas import EXAMPLES, GRAPH, sort_step, validate_sort

OUT = ROOT / 'runs/task2-sort-direction-v1'
SEED = 'sort-direction-v1-20261126'
METHODS = ('baseline', 'canvas_v1')
CONDITIONS = [(method, effort) for method in METHODS for effort in EFFORTS]
ORDER = re.compile(r'\bORDER\s+BY\s+([\w.]+)(?:\s+(ASC|DESC))?(?=\s*(?:LIMIT\b|;|$))', re.I)
EXPLICIT = re.compile(r'\b(?:ascending|descending|old to young|young to old)\b', re.I)
CONTROL_GROUPS = ('DB_schema_synonym', 'DB_schema_abbreviation', 'NLQ_column_carrier',
                  'NLQ_column_synonym', 'SQL_sort_order', 'SQL_NonDB_number')


def order(sql):
    part = ORDER.search(sql)
    return (part[1].rsplit('.', 1)[-1].casefold(), (part[2] or 'ASC').upper()) if part else None


def freeze(samples):
    path = OUT / 'plan.json'
    if path.exists():
        return load(path)
    exposed, _, historical = exposure(samples)
    seen = set(historical)
    candidates = sorted(
        (row for row in samples.values() if row['side'] == 'post'),
        key=lambda row: (row['id'][:-5] in seen, sha256((SEED + row['id']).encode()).digest()))
    seen_originals = {samples[EXAMPLES[0]]['original_id']}
    selected = []

    def add(row, label, reason):
        stem = row['id'][:-5]
        selected.append({'pair': stem, 'label': label, 'original_id': row['original_id'],
                         'db_id': row['db_id'], 'selection': reason, 'previously_seen_pair': stem in seen})
        seen_originals.add(row['original_id'])

    per_db = Counter()
    for row in candidates:
        if (row['group'] != 'DB_DBcontent_equivalence' or row['original_id'] in seen_originals
                or not EXPLICIT.search(row['question']) or per_db[row['db_id']] >= 2):
            continue
        before = samples[row['id'][:-4] + 'pre']
        old, new = order(before['gold_sql']), order(row['gold_sql'])
        if not old or not new or old[0] == new[0] or old[1] == new[1]:
            continue
        left, right = gold_rows(before['database'], before['gold_sql']), gold_rows(row['database'], row['gold_sql'])
        if left and result_eq(left, right, True):
            add(row, 'target', '显式单列排序，替代字段反向，参考执行结果逐序一致')
            per_db[row['db_id']] += 1
        if len(selected) == 8:
            break
    for group in CONTROL_GROUPS:
        add(next(row for row in candidates if row['group'] == group
                 and row['original_id'] not in seen_originals and order(row['gold_sql'])),
            'control', '不同官方扰动下的排序对照')
    for group in ('NLQ_column_attribute', 'SQL_comparison'):
        add(next(row for row in candidates if row['group'] == group
                 and row['original_id'] not in seen_originals
                 and not order(row['gold_sql']) and not EXPLICIT.search(row['question'])),
            'control', '无显式排序的回退对照')
    files = [Path(__file__), Path(__file__).with_name('sort_direction_canvas.py'),
             Path(__file__).with_name('experiment.py'), Path(__file__).with_name('run.py')]
    plan = {'seed': SEED, 'selected': selected, 'anchor': EXAMPLES, 'conditions': CONDITIONS,
            'observed_originals': len(exposed), 'graph': GRAPH,
            'code_sha256': {str(file.relative_to(ROOT)): digest(file) for file in files}}
    save(path, plan)
    return plan


def evaluate(sample_id, method, effort, endpoint, key):
    path = OUT / 'records' / method / effort / (sample_id + '.json')
    if path.is_file():
        return
    case = Scenario.from_id(sample_id)
    nodes, runner = ((validate_graph(GRAPHS['baseline']), step_node) if method == 'baseline'
                     else (validate_sort(GRAPH), sort_step))

    def complete(node_id, payload):
        folder = OUT / 'requests' / method / effort / sample_id / node_id
        request, response = folder / 'request.json', folder / 'response.json'
        payload = {**payload, 'reasoning_effort': effort}
        if request.exists() and load(request) != payload:
            raise ValueError('Cached request differs from the frozen condition')
        save(request, payload)
        if response.exists():
            return load(response)
        for attempt in (1, 2):
            try:
                answer = complete_at(endpoint, key, payload)
            except Exception as error:
                save(folder / f'failure-{attempt}.json', {'error': str(error).replace(key, '[REDACTED]')})
                if attempt == 2:
                    raise
                time.sleep(1)
            else:
                save(response, answer)
                return answer

    steps = {}
    for node in nodes:
        output, call = runner(node, case, MODEL, [steps[parent] for parent in node['from']], complete)
        steps[node['id']] = {**node, 'output': output, 'call': call}
    calls = [node['call'].get('usage') or {} for node in steps.values() if node['call']]
    usage = {}
    for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        observed = [call.get(field) for call in calls]
        if all(type(value) is int for value in observed):
            usage[field] = sum(observed)
    final = list(steps.values())[-1]['output']
    save(path, {'id': case.id, 'method': method, 'effort': effort, 'steps': list(steps.values()),
                'usage': usage, 'model_calls': len(calls), 'score': score(case, final)})


def main(mode):
    samples = samples_by_id()
    plan = freeze(samples)
    print('Frozen', Counter(r['label'] for r in plan['selected']), 'originals exposed:',
          plan['observed_originals'], flush=True)
    if mode == 'prepare':
        for item in plan['selected']:
            print(item['label'], item['pair'], item['db_id'], flush=True)
        return 0
    if mode != 'run':
        raise ValueError('Use prepare or run')
    for name, sha in plan['code_sha256'].items():
        assert digest(ROOT / name) == sha, name
    ids = [*EXAMPLES, *(r['pair'] + '-' + side for r in plan['selected'] for side in ('pre', 'post'))]
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    key = settings['THINGO_API_KEY']
    config = make_config([samples[i] for i in ids], MODEL, endpoint)
    config.update(reasoning_efforts=list(EFFORTS), plan_sha256=digest(OUT / 'plan.json'), graph=GRAPH)
    previous = OUT / 'config.json'
    if previous.exists() and load(previous) != config:
        raise ValueError('Configuration differs from the frozen experiment')
    save(previous, config)
    failures = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = {pool.submit(evaluate, sample, *cond, endpoint, key): (sample, *cond)
                   for sample in ids for cond in CONDITIONS}
        for number, future in enumerate(as_completed(pending), 1):
            try:
                future.result()
            except Exception as error:
                failure = {'case': pending[future], 'error': str(error).replace(key, '[REDACTED]')}
                failures.append(failure)
                print(failure, flush=True)
            if number % 8 == 0 or number == len(pending):
                print(f'{number}/{len(pending)} completed, {len(failures)} runner failures', flush=True)
    save(OUT / 'failures.json', failures)
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
