"""Compare the verified Top N planner against matched baseline responses."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys
import time

from experiment import GRAPHS, ROOT, samples_by_id, score, step_node, validate_graph
from projection_compare import EFFORTS, MODEL
from run import complete_at
from run_full_evaluation import digest, load, make_config, read_settings, save
from top_n_canvas import ORIGINAL, original_or_control
from top_n_v3 import GRAPH_V3, INTERACTIVE_V3, run_step, validate_v3
from top_n_v3_cases import FIXTURES, FIXTURE_IDS, fixture_case

OUT = ROOT / 'runs/task2-top-n-v3'
HISTORY = ROOT / 'results/task2/submission/records/task2-top-n-v1'
if not (HISTORY / 'plan.json').is_file():
    HISTORY = ROOT / 'runs/task2-top-n-v1'


def case_for(sample_id):
    return fixture_case(sample_id) if sample_id in FIXTURE_IDS else original_or_control(sample_id)


def freeze():
    historical = load(HISTORY / 'plan.json')['groups']
    groups = {**historical, **{name: [f'{name}-{side}' for side in ('pre', 'post')] for name in FIXTURES}}
    paths = [Path(__file__), *(Path(__file__).with_name(name) for name in
              ('top_n_v3.py', 'top_n_v3_cases.py', 'experiment.py', 'run.py'))]
    cases = {sample: vars(case_for(sample)) for ids in groups.values() for sample in ids}
    plan = {'groups': groups, 'inputs': cases, 'efforts': list(EFFORTS),
            'fixtures': {name: data[1] for name, data in FIXTURES.items()},
            'graph': GRAPH_V3, 'interactive_graph': INTERACTIVE_V3,
            'fixture_db_sha256': {case['database']: digest(ROOT / case['database'])
                                  for id, case in cases.items() if id in FIXTURE_IDS},
            'source_sha256': {p.name: digest(p) for p in paths}}
    path = OUT / 'plan.json'
    if path.exists() and load(path) != plan:
        raise ValueError('Frozen task 7 v3 plan differs')
    save(path, plan)
    return plan


def evaluate(sample, effort, method, endpoint, key):
    folder = OUT / 'records' / method / effort / sample
    path = folder / 'record.json'
    if path.exists():
        return load(path)
    case = case_for(sample)
    steps, sources = {}, {}
    if method == 'baseline':
        nodes, runner = validate_graph(GRAPHS['baseline']), step_node
    else:
        nodes, runner = validate_v3(INTERACTIVE_V3 if method == 'interactive' else GRAPH_V3), run_step

    def complete(node, payload):
        request = {**payload, 'reasoning_effort': effort}
        target = folder / node
        request_file, response_file = (target / f'{name}.json' for name in ('request', 'response'))
        if request_file.exists() and load(request_file) != request:
            raise ValueError('Saved request differs')
        save(request_file, request)
        sources[node] = 'live'
        source_file = target / 'source.json'
        if response_file.exists():
            if source_file.exists():
                sources[node] = load(source_file)['source']
            return load(response_file)
        if node == 'generate':
            current = OUT / 'records' / 'baseline' / effort / sample / 'generate'
            old = HISTORY / 'requests' / 'baseline' / effort / sample / 'generate'
            choices = [(current, 'paired_baseline')] if method != 'baseline' else [(old, 'v1_baseline')]
            for candidate, label in choices:
                request_path, response_path = (candidate / f'{name}.json' for name in ('request', 'response'))
                if request_path.exists() and response_path.exists() and load(request_path) == request:
                    answer = load(response_path)
                    sources[node] = label
                    save(source_file, {'source': label})
                    save(response_file, answer)
                    return answer
        for attempt in (1, 2):
            try:
                answer = complete_at(endpoint, key, request)
            except Exception as error:
                save(target / f'error-{attempt}.json', {'error': str(error).replace(key, '[REDACTED]')})
                if attempt == 2:
                    raise
                time.sleep(1)
            else:
                save(source_file, {'source': 'live'})
                save(response_file, answer)
                return answer

    for node in nodes:
        output, call = runner(node, case, MODEL, [steps[i] for i in node['from']], complete)
        steps[node['id']] = {**node, 'output': output, 'call': call}
    final = steps['execute']['output']
    calls = [s['call'] for s in steps.values() if s['call']]
    observed = [(call.get('usage') or {}).get('total_tokens') for call in calls]
    record = {'id': sample, 'effort': effort, 'method': method, 'steps': list(steps.values()),
              'route': final.get('route'), 'score': score(case, final), 'model_calls': len(calls),
              'total_tokens': sum(observed) if all(type(v) is int for v in observed) else None,
              'response_sources': sources}
    save(path, record)
    return record


def main(mode):
    plan = freeze()
    if mode == 'prepare':
        print({name: len(ids) for name, ids in plan['groups'].items()})
        return 0
    if mode != 'run':
        raise ValueError('Use prepare or run')
    ids = [sample for items in plan['groups'].values() for sample in items]
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    key = settings['THINGO_API_KEY']
    samples = samples_by_id()
    config = make_config([samples[i] for i in ids if i in samples], MODEL, endpoint)
    config.update(frozen_sha256=digest(OUT / 'plan.json'), requested_efforts=list(EFFORTS))
    path = OUT / 'config.json'
    if path.exists() and load(path) != config:
        raise ValueError('Frozen run configuration differs')
    save(path, config)
    errors = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for methods in (['baseline'], ['v3', 'interactive']):
            jobs = [(sample, effort, method) for method in methods for effort in EFFORTS for sample in
                    (ids if method != 'interactive' else [*ORIGINAL, 'lap-ambiguity-pre', 'lap-ambiguity-post'])]
            queued = {pool.submit(evaluate, *job, endpoint, key): job for job in jobs}
            for count, task in enumerate(as_completed(queued), 1):
                try:
                    task.result()
                except Exception as error:
                    detail = {'case': queued[task], 'error': str(error).replace(key, '[REDACTED]')}
                    errors.append(detail)
                    print(detail, flush=True)
                if count % 8 == 0 or count == len(jobs):
                    print(f'{methods} {count}/{len(jobs)} completed, {len(errors)} errors', flush=True)
            if errors:
                break
    save(OUT / 'failures.json', errors)
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))
