"""Evaluate a count-scope revision on the frozen v1 pairs."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys

from count_scope_compare import OUT as V1
from experiment import ROOT, Scenario, samples_by_id, score
from projection_compare import EFFORTS, MODEL
from run import complete_at
from run_full_evaluation import digest, load, make_config, read_settings, save


def revision(version):
    if version == 'v2':
        from count_scope_v2 import GRAPH_V2, count_step_v2, validate_count_v2
        return GRAPH_V2, count_step_v2, validate_count_v2
    if version == 'v3':
        from count_scope_v3 import GRAPH_V3, count_step_v3, validate_count_v3
        return GRAPH_V3, count_step_v3, validate_count_v3
    raise ValueError('Use v2 or v3')


def evaluate(sample, effort, version, endpoint, key, output, graph, runner, validate):
    path = output/'records'/effort/(sample+'.json')
    if path.is_file():
        return
    case = Scenario.from_id(sample)
    old = V1/'requests'/'canvas_v1'/effort/sample
    if version == 'v3':
        old = ROOT/'runs/task2-count-scope-v2/requests'/effort/sample
    sources, steps = {}, {}

    def complete(node_id, payload):
        payload = {**payload, 'reasoning_effort': effort}
        folder = output/'requests'/effort/sample/node_id
        request, response = folder/'request.json', folder/'response.json'
        previous_request, previous_response = old/node_id/'request.json', old/node_id/'response.json'
        if request.exists() and load(request) != payload:
            raise ValueError('Saved request differs from the frozen condition')
        save(request, payload)
        if previous_response.is_file() and load(previous_request) == payload:
            answer = load(previous_response)
            sources[node_id] = str(previous_response.relative_to(ROOT))
        else:
            answer = load(response) if response.exists() else complete_at(endpoint, key, payload)
            sources[node_id] = version
        if answer.get('model') != MODEL or not answer.get('choices'):
            raise ValueError('Unexpected model response')
        save(response, answer)
        return answer

    for node in validate(graph):
        result, call = runner(node, case, MODEL, [steps[parent] for parent in node['from']], complete)
        steps[node['id']] = {**node, 'output': result, 'call': call}
    usages = [node['call'].get('usage') or {} for node in steps.values() if node['call']]
    usage = {}
    for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        values = [u.get(field) for u in usages]
        if usages and all(type(value) is int for value in values):
            usage[field] = sum(values)
    final = list(steps.values())[-1]['output']
    save(path, {'id': sample, 'method': 'canvas_'+version, 'effort': effort,
                'steps': list(steps.values()), 'usage': usage, 'model_calls': len(usages),
                'response_sources': sources, 'score': score(case, final)})


def main(version):
    graph, runner, validate = revision(version)
    output = ROOT/f'runs/task2-count-scope-{version}'
    plan_path = V1/'plan.json'
    plan = load(plan_path)
    ids = [*plan['anchor'], *(row['pair']+'-'+side for row in plan['selected'] for side in ('pre', 'post'))]
    samples = samples_by_id()
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/')+'/chat/completions'
    key = settings['THINGO_API_KEY']
    config = make_config([samples[k] for k in ids], MODEL, endpoint)
    old_config = load(V1/'config.json')
    for field in ('endpoint', 'model', 'data_source', 'database_sha256', 'evaluator_commit', 'system'):
        if config[field] != old_config[field]:
            raise ValueError(f'Comparison differs from v1 in {field}')
    files = ('count_scope_canvas.py', 'count_scope_v2.py', 'experiment.py', 'run.py')
    if version == 'v3':
        files += ('count_scope_v3.py',)
    config.update(graph=graph, source_plan_sha256=digest(plan_path), reasoning_efforts=list(EFFORTS),
                  code_sha256={str(file.relative_to(ROOT)): digest(file) for file in
                               [Path(__file__), *(Path(__file__).with_name(name) for name in files)]},
                  cache_policy='Reuse the immediately preceding version only when the full node request matches')
    config_path = output/'config.json'
    if config_path.is_file() and load(config_path) != config:
        raise ValueError('Saved configuration differs from the frozen comparison')
    save(config_path, config)
    failures = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        pending = {pool.submit(evaluate, sample, effort, version, endpoint, key, output, graph, runner, validate):
                   (sample, effort) for sample in ids for effort in EFFORTS}
        for number, job in enumerate(as_completed(pending), 1):
            try:
                job.result()
            except Exception as error:
                failure = {'condition': pending[job], 'error': str(error).replace(key, '[REDACTED]')}
                failures.append(failure)
                print(failure, flush=True)
            if number % 8 == 0 or number == len(pending):
                print(f'{number}/{len(pending)} conditions, {len(failures)} failures', flush=True)
    save(output/'failures.json', failures)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))
