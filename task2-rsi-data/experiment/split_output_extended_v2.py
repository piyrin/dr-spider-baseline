"""Run a new matched baseline and v2 on the frozen 16 extension pairs."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from experiment import GRAPHS, Scenario, samples_by_id, score, step_node, validate_graph
from projection_compare import EFFORTS, MODEL
from run import complete_at
from run_full_evaluation import digest, load, make_config, read_settings, save
from split_output_anchor_v2 import OUT, evaluate
from split_output_compare import OUT as V1_OUT
from split_output_v2 import GRAPH_V2


def baseline(case, effort, endpoint, key):
    folder = OUT / 'extended-baseline' / effort / case.id
    record_path = folder / 'record.json'
    if record_path.exists():
        return load(record_path)

    def complete(node_id, request):
        path = folder / node_id
        request = {**request, 'reasoning_effort': effort}
        assert case.gold_sql not in request['messages'][-1]['content']
        if (path / 'request.json').exists() and load(path / 'request.json') != request:
            raise ValueError('Cached request differs from the current baseline')
        save(path / 'request.json', request)
        response_path = path / 'response.json'
        if response_path.exists():
            return load(response_path)
        result = complete_at(endpoint, key, request)
        save(response_path, result)
        return result

    steps = {}
    for node in validate_graph(GRAPHS['baseline']):
        output, call = step_node(node, case, MODEL, [steps[parent] for parent in node['from']], complete)
        steps[node['id']] = {**node, 'output': output, 'call': call}
    usage = steps['generate']['call']['usage'] or {}
    result = {'id': case.id, 'effort': effort, 'score': score(case, steps['execute']['output']),
              'model_calls': 1, 'total_tokens': usage.get('total_tokens'), 'steps': list(steps.values())}
    save(record_path, result)
    return result


def main():
    original = load(OUT / 'summary.json')
    if len(original) != 8 or any(not row['score']['correct'] for row in original):
        raise ValueError('Complete the original pre/post repair checks before running extensions')
    anchor_config = load(OUT / 'config.json')
    for path, expected in anchor_config['implementation_sha256'].items():
        if digest(OUT.parents[1] / path) != expected:
            raise ValueError(f'Implementation changed after the original-question run: {path}')
    plan_file = V1_OUT / 'plan.json'
    chosen = load(plan_file)['selected']
    assert len(chosen) == 16 and len({row['original_id'] for row in chosen}) == 16
    cases = [Scenario.from_id(row['pair'] + '-' + side) for row in chosen for side in ('pre', 'post')]
    samples = samples_by_id()
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    key = settings['THINGO_API_KEY']
    config = make_config([samples[case.id] for case in cases], MODEL, endpoint)
    config.update(graph=GRAPH_V2, efforts=list(EFFORTS), selected=chosen, v1_plan_sha256=digest(plan_file),
                  anchor_config_sha256=digest(OUT / 'config.json'), runner_sha256=digest(Path(__file__)))
    config_path = OUT / 'extended-config.json'
    if config_path.exists() and load(config_path) != config:
        raise ValueError('Stored configuration differs from the extension run')
    save(config_path, config)

    failures = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = {}
        for case in cases:
            for effort in EFFORTS:
                pending[pool.submit(baseline, case, effort, endpoint, key)] = (case.id, effort, 'baseline')
                pending[pool.submit(evaluate, case, effort, 'extended', endpoint, key)] = (case.id, effort, 'v2')
        for index, task in enumerate(as_completed(pending), 1):
            try:
                task.result()
            except Exception as error:
                failure = {'condition': pending[task], 'error': str(error).replace(key, '[REDACTED]')}
                failures.append(failure)
                print(failure, flush=True)
            if index % 8 == 0:
                print(f'{index}/{len(pending)} condition jobs complete, {len(failures)} failures', flush=True)
    save(OUT / 'extended-failures.json', failures)
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
