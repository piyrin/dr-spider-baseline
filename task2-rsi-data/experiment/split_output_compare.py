"""Freeze and score the person-name canvas with matched Thinking conditions."""

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
from run_full_evaluation import digest, load, make_config, read_settings, save
from split_output_canvas import EXAMPLES, GRAPH, split_step, validate_split

OUT = ROOT / 'runs/task2-split-output-v1'
SEED = 'split-output-v1-20261126'
METHODS = ('baseline', 'canvas_v1')
CONDITIONS = [(method, effort) for method in METHODS for effort in EFFORTS]
CONTROL_GROUPS = ('DB_schema_synonym', 'NLQ_column_attribute', 'NLQ_column_value',
                  'NLQ_keyword_synonym', 'SQL_comparison', 'SQL_sort_order')


def freeze(samples):
    path = OUT / 'plan.json'
    if path.exists():
        return load(path)
    exposed, _, historical = exposure(samples)
    seen = set(historical)
    ordered = sorted((row for row in samples.values() if row['side'] == 'post'),
                     key=lambda r: (r['id'][:-5] in seen, sha256((SEED + r['id']).encode()).digest()))
    used = {samples[EXAMPLES[0]]['original_id']}
    selected = []

    def add(row, label, reason):
        pair = row['id'][:-5]
        used.add(row['original_id'])
        selected.append({'pair': pair, 'label': label, 'original_id': row['original_id'],
                         'db_id': row['db_id'], 'selection': reason, 'previously_seen_pair': pair in seen})

    def name_parts(sql):
        projection = re.split(r'\bFROM\b', sql, maxsplit=1, flags=re.I)[0]
        return re.search(r'\b\w*first_name\b', projection, re.I) and re.search(
            r'\b\w*last_name\b', projection, re.I)

    per_db = Counter()
    for row in ordered:
        if (row['original_id'] not in used and row['group'] == 'DB_DBcontent_equivalence'
                and per_db[row['db_id']] < 2 and name_parts(row['gold_sql'])
                and not name_parts(samples[row['id'][:-4] + 'pre']['gold_sql'])):
            add(row, 'target', '当前侧参考输出含分开的名字和姓氏，原侧未分成这两列')
            per_db[row['db_id']] += 1
            if len(selected) == 8:
                break
    for stem, reason in [('DB_DBcontent_equivalence-00176', '日期字段拆分，检验姓名专用规则的边界'),
                         ('NLQ_column_attribute-00065', '姓名原有三个组成列，题面从显式列变为 full name')]:
        add(samples[stem + '-post'], 'control', reason)
    for group in CONTROL_GROUPS:
        add(next(row for row in ordered if row['group'] == group and row['original_id'] not in used
                 and not name_parts(row['gold_sql'])), 'control', '其他官方扰动，用于检查误伤')
    assert len(selected) == 16 and len(used) == 17
    files = [Path(__file__), Path(__file__).with_name('split_output_canvas.py'),
             Path(__file__).with_name('experiment.py'), Path(__file__).with_name('run.py')]
    plan = {'seed': SEED, 'selected': selected, 'anchor': EXAMPLES, 'conditions': CONDITIONS,
            'observed_originals': len(exposed), 'graph': GRAPH,
            'code_sha256': {str(f.relative_to(ROOT)): digest(f) for f in files}}
    save(path, plan)
    return plan


def evaluate(case, method, effort, endpoint, key):
    path = OUT / 'records' / method / effort / (case.id + '.json')
    if path.is_file():
        return
    nodes, runner = ((validate_graph(GRAPHS['baseline']), step_node) if method == 'baseline'
                     else (validate_split(GRAPH), split_step))

    def complete(node_id, payload):
        folder = OUT / 'requests' / method / effort / case.id / node_id
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
        if all(type(v) is int for v in observed):
            usage[field] = sum(observed)
    final = list(steps.values())[-1]['output']
    save(path, {'id': case.id, 'method': method, 'effort': effort, 'steps': list(steps.values()),
                'usage': usage, 'model_calls': len(calls), 'score': score(case, final)})


def main(mode):
    samples = samples_by_id()
    plan = freeze(samples)
    print('Frozen', Counter(r['label'] for r in plan['selected']),
          'originals exposed:', plan['observed_originals'], flush=True)
    for row in plan['selected']:
        print(row['label'], row['pair'], row['db_id'], flush=True)
    if mode == 'prepare':
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
    jobs = [(Scenario.from_id(i), *cond) for i in ids for cond in CONDITIONS]
    failures = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = {pool.submit(evaluate, *j, endpoint, key): (j[0].id, *j[1:]) for j in jobs}
        for number, future in enumerate(as_completed(pending), 1):
            try:
                future.result()
            except Exception as error:
                failure = {'case': pending[future], 'error': str(error).replace(key, '[REDACTED]')}
                failures.append(failure)
                print(failure, flush=True)
            if number % 8 == 0:
                print(f'{number}/{len(jobs)} completed, {len(failures)} runner failures', flush=True)
    save(OUT / 'failures.json', failures)
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
