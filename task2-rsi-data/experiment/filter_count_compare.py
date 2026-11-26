"""Run the four-node canvas and baseline on matched case-10 inputs."""

from concurrent.futures import ThreadPoolExecutor
from itertools import product
from pathlib import Path
import sys

from experiment import GRAPHS, ROOT, Scenario, samples_by_id, score, step_node, validate_graph
from filter_count_canvas import EXAMPLES, GRAPH, filter_count_step, validate_filter_count
from run import complete_at
from run_full_evaluation import digest, load, make_config, read_settings, save

OUT = ROOT / 'runs/task2-filter-count-v1'
MODEL = 'gpt-6-sol'
EFFORTS = ('none', 'high')


def evaluate(case, method, effort, endpoint, key):
    folder = OUT / 'records' / method / effort / case.id
    record = folder / 'record.json'
    if record.exists():
        return load(record)
    nodes, runner = ((validate_graph(GRAPHS['baseline']), step_node) if method == 'baseline'
                     else (validate_filter_count(GRAPH), filter_count_step))

    def complete(node_id, payload):
        request, response = folder / node_id / 'request.json', folder / node_id / 'response.json'
        body = {**payload, 'reasoning_effort': effort}
        if request.exists() and load(request) != body:
            raise ValueError('Cached request differs from the declared condition')
        save(request, body)
        if response.exists():
            return load(response)
        answer = complete_at(endpoint, key, body)
        save(response, answer)
        return answer

    steps = {}
    for node in nodes:
        output, call = runner(node, case, MODEL, [steps[parent] for parent in node['from']], complete)
        steps[node['id']] = {**node, 'output': output, 'call': call}
    usage = [step['call'].get('usage') or {} for step in steps.values() if step['call'] is not None]
    totals = [item.get('total_tokens') for item in usage]
    final = steps[nodes[-1]['id']]['output']
    result = {'id': case.id, 'method': method, 'effort': effort, 'steps': list(steps.values()),
              'score': score(case, final), 'model_calls': len(usage),
              'total_tokens': sum(totals) if all(type(item) is int for item in totals) else None}
    save(record, result)
    return result


def main():
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    samples = samples_by_id()
    config = make_config([samples[id] for id in EXAMPLES], MODEL, endpoint)
    config.update(canvas_graph=GRAPH, reasoning_efforts=list(EFFORTS),
                  local_sources={file.name: digest(file) for file in (
                      Path(__file__), Path(__file__).with_name('filter_count_canvas.py'),
                      Path(__file__).with_name('experiment.py'), Path(__file__).with_name('run.py'))})
    config_path = OUT / 'config.json'
    if config_path.exists() and load(config_path) != config:
        raise ValueError('Configuration differs from the frozen test')
    save(config_path, config)
    jobs = list(product(EXAMPLES, ('baseline', 'canvas_v1'), EFFORTS))
    key = settings['THINGO_API_KEY']
    failures = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = [(job, pool.submit(evaluate, Scenario.from_id(job[0]), *job[1:], endpoint, key))
                 for job in jobs]
        for job, task in tasks:
            try:
                result = task.result()
            except Exception as error:
                failures.append({'condition': job, 'error': str(error).replace(key, '[REDACTED]')})
                print(failures[-1], flush=True)
            else:
                print(job, result['score']['status'], result['model_calls'], result['total_tokens'], flush=True)
    save(OUT / 'failures.json', failures)
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main())
