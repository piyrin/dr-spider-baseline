"""Freeze and run the synonym canvas development comparison."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys

from experiment import GRAPHS, ROOT, Scenario, samples_by_id, score, step_node, validate_graph
from projection_compare import CONDITIONS, EFFORTS, MODEL
from run import complete_at
from run_full_evaluation import digest, load, make_config, read_settings, save
from synonym_canvas import EXAMPLES, GRAPH, synonym_step, validate_synonym

OUT = ROOT / 'runs/task2-filter-synonym-v1'
TARGETS = (
    'NLQ_multitype-00851', 'NLQ_value_synonym-00483', 'NLQ_value_synonym-00029',
    'NLQ_value_synonym-00211', 'NLQ_value_synonym-00215', 'NLQ_value_synonym-00413',
    'NLQ_value_synonym-00146', 'NLQ_multitype-00659',
)


def freeze(samples):
    controls = load(ROOT / 'runs/task2-filter-format-comparison-v1/plan.json')['selected']
    control_pairs = [row['pair'] for row in controls if row['label'] == 'control']
    groups = {'anchor': [EXAMPLES[0][:-4]], 'target': list(TARGETS), 'control': control_pairs}
    original_ids = [samples[pair + '-pre']['original_id'] for pairs in groups.values() for pair in pairs]
    if len(original_ids) != 17 or len(set(original_ids)) != 17:
        raise ValueError('The experiment requires distinct original questions.')
    sources = [Path(__file__).with_name(name) for name in (
        'synonym_compare.py', 'synonym_canvas.py', 'format_canvas.py', 'experiment.py', 'run.py')]
    plan = {'groups': groups, 'conditions': CONDITIONS, 'graph': GRAPH,
            'sources': {str(path.relative_to(ROOT)): digest(path) for path in sources},
            'scope': 'known historical synonym cases and fixed mixed controls from question 2'}
    path = OUT / 'plan.json'
    if path.exists() and load(path) != {**plan, 'conditions': [list(c) for c in CONDITIONS]}:
        raise ValueError('Stored plan differs from the fixed design.')
    save(path, plan)
    return plan


def evaluate(case, method, effort, endpoint, key):
    arm = OUT / method / effort / case.id
    record_path = arm / 'record.json'
    if record_path.exists():
        return load(record_path)
    nodes, run_node = (validate_graph(GRAPHS['baseline']), step_node) if method == 'baseline' else (
        validate_synonym(GRAPH), synonym_step)
    steps = {}

    def complete(node_id, payload):
        request = {**payload, 'reasoning_effort': effort}
        paths = arm / node_id
        request_path, response_path = paths / 'request.json', paths / 'response.json'
        if request_path.exists() and load(request_path) != request:
            raise ValueError('Frozen request differs from the saved request.')
        save(request_path, request)
        if response_path.exists():
            return load(response_path)
        response = complete_at(endpoint, key, request)
        save(response_path, response)
        return response

    for node in nodes:
        output, call = run_node(node, case, MODEL, [steps[p] for p in node['from']], complete)
        steps[node['id']] = {**node, 'output': output, 'call': call}
    calls = [step['call'] for step in steps.values() if step['call']]
    usage = {}
    for name in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        values = [(call.get('usage') or {}).get(name) for call in calls]
        if all(type(value) is int for value in values):
            usage[name] = sum(values)
    record = {'id': case.id, 'method': method, 'effort': effort, 'steps': list(steps.values()),
              'model_calls': len(calls), 'usage': usage, 'score': score(case, steps[nodes[-1]['id']]['output']),
              'route': steps['generate']['output'].get('route', 'baseline')}
    save(record_path, record)
    return record


def main():
    mode = sys.argv[1]
    samples = samples_by_id()
    plan = freeze(samples)
    ids = [pair + '-' + side for pairs in plan['groups'].values() for pair in pairs for side in ('pre', 'post')]
    print('Frozen', len(ids)//2, 'pairs', plan['groups'], flush=True)
    if mode == 'prepare':
        return 0
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    key = settings['THINGO_API_KEY']
    config = make_config([samples[sample] for sample in ids], MODEL, endpoint)
    config.update(reasoning_efforts=EFFORTS, plan_sha256=digest(OUT / 'plan.json'))
    cfg_path = OUT / 'config.json'
    if cfg_path.exists() and load(cfg_path) != {**config, 'reasoning_efforts': list(EFFORTS)}:
        raise ValueError('Run configuration differs.')
    save(cfg_path, config)
    if mode == 'anchor':
        ids = EXAMPLES
    elif mode != 'run':
        raise ValueError('Use prepare, anchor or run.')
    tasks = [(ident, method, effort) for ident in ids for method, effort in CONDITIONS]
    failures = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = {pool.submit(evaluate, Scenario.from_id(ident), method, effort, endpoint, key):
                   (ident, method, effort) for ident, method, effort in tasks}
        for number, future in enumerate(as_completed(pending), 1):
            try:
                result = future.result()
                if number % 8 == 0 or mode == 'anchor':
                    print(f'{number}/{len(tasks)}', *pending[future],
                          result['route'], result['score']['status'], flush=True)
            except Exception as error:
                failures.append({'condition': pending[future], 'error': str(error).replace(key, '[REDACTED]')})
                print(failures[-1], flush=True)
    save(OUT / 'failures.json', failures)
    print(f'{len(tasks)-len(failures)}/{len(tasks)} scored; {len(failures)} unavailable.', flush=True)
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main())
