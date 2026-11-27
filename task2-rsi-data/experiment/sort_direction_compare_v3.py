"""Replay the frozen sort comparison with v3 single-owner direction decisions."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from experiment import ROOT, Scenario, samples_by_id, score
from projection_compare import EFFORTS, MODEL
from run import complete_at
from run_full_evaluation import digest, load, make_config, read_settings, save
from sort_direction_compare import OUT as V1
from sort_direction_compare_v2 import OUT as V2
from sort_direction_v3 import GRAPH_V3, sort_step_v3, validate_sort_v3

OUT = ROOT / 'runs/task2-sort-direction-v3'


def evaluate(sample, effort, endpoint, key):
    record = OUT / 'records' / effort / (sample + '.json')
    if record.exists():
        return
    case = Scenario.from_id(sample)
    origins, steps = {}, {}

    def complete(node_id, payload):
        payload = {**payload, 'reasoning_effort': effort}
        folder = OUT / 'requests' / effort / sample / node_id
        old = V2 / 'requests' / effort / sample / node_id
        request, response = folder / 'request.json', folder / 'response.json'
        if request.exists() and load(request) != payload:
            raise ValueError('Cached v3 request differs from the frozen condition')
        save(request, payload)
        reuse = (old / 'request.json').is_file() and load(old / 'request.json') == payload
        if reuse:
            answer = load(old / 'response.json')
            origins[node_id] = str((old / 'response.json').relative_to(ROOT))
        else:
            answer = load(response) if response.exists() else complete_at(endpoint, key, payload)
            origins[node_id] = 'v3'
        save(response, answer)
        return answer

    for node in validate_sort_v3(GRAPH_V3):
        output, call = sort_step_v3(node, case, MODEL, [steps[parent] for parent in node['from']], complete)
        steps[node['id']] = {**node, 'output': output, 'call': call}
    calls = [node['call'].get('usage') or {} for node in steps.values() if node['call']]
    usage = {}
    for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        counts = [call.get(field) for call in calls]
        if all(type(value) is int for value in counts):
            usage[field] = sum(counts)
    result = list(steps.values())[-1]['output']
    save(record, {'id': sample, 'effort': effort, 'method': 'canvas_v3', 'steps': list(steps.values()),
                  'usage': usage, 'model_calls': len(calls), 'response_sources': origins,
                  'score': score(case, result)})


def main():
    source_plan = V1 / 'plan.json'
    plan = load(source_plan)
    ids = [*plan['anchor'], *(r['pair'] + '-' + side for r in plan['selected'] for side in ('pre', 'post'))]
    samples = samples_by_id()
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    key = settings['THINGO_API_KEY']
    config = make_config([samples[i] for i in ids], MODEL, endpoint)
    v1_config = load(V1 / 'config.json')
    for field in ('endpoint', 'model', 'data_source', 'database_sha256', 'evaluator_commit', 'system'):
        if config[field] != v1_config[field]:
            raise ValueError(f'Comparison differs from v1 in {field}')
    config.update(graph=GRAPH_V3, source_plan_sha256=digest(source_plan),
                  source_config_sha256=digest(V1 / 'config.json'), v2_config_sha256=digest(V2 / 'config.json'),
                  reasoning_efforts=list(EFFORTS),
                  code_sha256={str(file.relative_to(ROOT)): digest(file) for file in
                               (Path(__file__), Path(__file__).with_name('sort_direction_v3.py'))},
                  cache_policy='Reuse v2 response exactly when full node request matches')
    output = OUT / 'config.json'
    if output.exists() and load(output) != config:
        raise ValueError('v3 configuration differs from the frozen experiment')
    save(output, config)
    failures = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        pending = {pool.submit(evaluate, sample, effort, endpoint, key): (sample, effort)
                   for sample in ids for effort in EFFORTS}
        for number, future in enumerate(as_completed(pending), 1):
            try:
                future.result()
            except Exception as error:
                failure = {'sample': pending[future], 'error': str(error).replace(key, '[REDACTED]')}
                failures.append(failure)
                print(failure, flush=True)
            if number % 8 == 0 or number == len(pending):
                print(f'{number}/{len(pending)} complete, {len(failures)} failed', flush=True)
    save(OUT / 'failures.json', failures)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
