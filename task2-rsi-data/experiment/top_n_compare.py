"""Freeze and run the Top N development and explicit-interpretation controls."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys
import time

from experiment import GRAPHS, ROOT, samples_by_id, score, step_node, validate_graph
from projection_compare import EFFORTS, MODEL
from run import complete_at
from run_full_evaluation import digest, load, make_config, read_settings, save
from top_n_canvas import (CONTROLS, GRAPH, INTERACTIVE_GRAPH, ORIGINAL, RELATED,
                          original_or_control, top_n_step, validate_top_n)

OUT = ROOT / 'runs/task2-top-n-v1'
METHODS = ('baseline', 'canvas', 'interactive')


def freeze():
    previous = load(ROOT / 'runs/task2-sort-direction-v1/plan.json')
    mixed = [item['pair'] + '-' + side for item in previous['selected']
             if item['label'] == 'control' for side in ('pre', 'post')]
    groups = {'anchor': ORIGINAL, 'related': RELATED, 'explicit_tuple': CONTROLS[:2],
              'explicit_person': CONTROLS[2:], 'mixed': mixed}
    controls = {sample: vars(original_or_control(sample)) for sample in CONTROLS}
    current = Path(__file__).parent
    files = ['top_n_compare.py', 'top_n_canvas.py', 'experiment.py', 'run.py']
    plan = {'groups': groups, 'controls': controls, 'graph': GRAPH, 'interactive_graph': INTERACTIVE_GRAPH,
            'efforts': list(EFFORTS), 'methods': METHODS,
            'code_sha256': {str((current / file).relative_to(ROOT)): digest(current / file) for file in files}}
    path = OUT / 'plan.json'
    if path.exists() and load(path) != {**plan, 'methods': list(METHODS)}:
        raise ValueError('Frozen Top N plan differs')
    save(path, plan)
    save(OUT / 'structure.json', {'batch': GRAPH, 'interactive': INTERACTIVE_GRAPH})
    return plan


def evaluate(sample_id, method, effort, endpoint, token):
    path = OUT / 'records' / method / effort / (sample_id + '.json')
    if path.exists():
        return
    case = original_or_control(sample_id)
    if method == 'baseline':
        nodes, runner = validate_graph(GRAPHS['baseline']), step_node
    else:
        nodes, runner = validate_top_n(INTERACTIVE_GRAPH if method == 'interactive' else GRAPH), top_n_step

    def complete(node_id, payload):
        payload = {**payload, 'reasoning_effort': effort}
        folder = OUT / 'requests' / method / effort / sample_id / node_id
        request, response = folder / 'request.json', folder / 'response.json'
        if request.exists() and load(request) != payload:
            raise ValueError('Cached request differs from the frozen condition')
        save(request, payload)
        if response.exists():
            return load(response)
        for attempt in (1, 2):
            try:
                answer = complete_at(endpoint, token, payload)
            except Exception as error:
                save(folder / f'failure-{attempt}.json', {'error': str(error).replace(token, '[REDACTED]')})
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
    calls = [node['call'] for node in steps.values() if node['call'] is not None]
    usage = {}
    for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        values = [(call.get('usage') or {}).get(field) for call in calls]
        if all(type(value) is int for value in values):
            usage[field] = sum(values)
    final = list(steps.values())[-1]['output']
    save(path, {'id': sample_id, 'method': method, 'effort': effort, 'steps': list(steps.values()),
                'route': final.get('route'), 'usage': usage, 'model_calls': len(calls),
                'score': score(case, final)})


def main(mode):
    plan = freeze()
    ids = [sample for group in plan['groups'].values() for sample in group]
    if mode == 'prepare':
        print({name: len(group) for name, group in plan['groups'].items()})
        return 0
    if mode != 'run':
        raise ValueError('Use prepare or run')
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    token = settings['THINGO_API_KEY']
    samples = samples_by_id()
    config = make_config([samples[item] for item in ids if item in samples], MODEL, endpoint)
    config.update(plan_sha256=digest(OUT / 'plan.json'), requested_efforts=list(EFFORTS),
                  control_questions=len(CONTROLS))
    path = OUT / 'config.json'
    if path.exists() and load(path) != config:
        raise ValueError('Frozen Top N configuration differs')
    save(path, config)
    conditions = [(sample, method, effort) for sample in ids for method in METHODS[:2] for effort in EFFORTS]
    conditions += [(sample, 'interactive', effort) for sample in ORIGINAL for effort in EFFORTS]
    failures = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = {pool.submit(evaluate, *condition, endpoint, token): condition for condition in conditions}
        for index, future in enumerate(as_completed(pending), 1):
            try:
                future.result()
            except Exception as error:
                failure = {'condition': pending[future], 'error': str(error).replace(token, '[REDACTED]')}
                failures.append(failure)
                print(failure, flush=True)
            if index % 8 == 0 or index == len(pending):
                print(f'{index}/{len(pending)} processed, {len(failures)} failures', flush=True)
    save(OUT / 'failures.json', failures)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))
