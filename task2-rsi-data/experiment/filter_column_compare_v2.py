"""Replay each archived baseline draft through the v2 filter-column canvas."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys
from zipfile import ZipFile
import json

from experiment import ROOT, Scenario, samples_by_id, score
from filter_column_v2 import GRAPH_V2, column_step_v2, inspect_draft, validate_column_v2
from projection_compare import EFFORTS, MODEL
from run import complete_at
from run_full_evaluation import digest, load, make_config, read_settings, save

V1 = ROOT / 'runs/task2-filter-column-v1'
SUBMISSION = ROOT / 'results/task2/submission'
V1_METADATA = SUBMISSION / 'records/task2-filter-column-v1'
OUT = ROOT / 'runs/task2-filter-column-v2'


def archive(relative):
    local = V1 / relative
    if local.is_file():
        return load(local)
    with ZipFile(SUBMISSION / '完整批测记录.zip') as source:
        return json.loads(source.read((V1.relative_to(ROOT) / relative).as_posix()))


def evaluate(sample, effort, endpoint, key):
    record = OUT / 'records' / effort / (sample + '.json')
    if record.exists():
        return load(record)
    case = Scenario.from_id(sample)
    baseline = archive(Path('records/baseline') / effort / (sample + '.json'))
    v1 = archive(Path('records/canvas_v1') / effort / (sample + '.json'))
    old = Path('requests/baseline') / effort / sample / 'generate'
    steps = {}

    def complete(node_id, payload):
        payload = {**payload, 'reasoning_effort': effort}
        folder = OUT / 'requests' / effort / sample / node_id
        request, response = folder / 'request.json', folder / 'response.json'
        if request.exists() and load(request) != payload:
            raise ValueError('Cached v2 request differs from the frozen condition')
        save(request, payload)
        if node_id == 'draft':
            if archive(old / 'request.json') != payload:
                raise ValueError('The baseline draft request differs')
            reply = archive(old / 'response.json')
        else:
            reply = load(response) if response.exists() else complete_at(endpoint, key, payload)
        save(response, reply)
        return reply

    for node in validate_column_v2(GRAPH_V2):
        output, call = column_step_v2(node, case, MODEL, [steps[p] for p in node['from']], complete)
        steps[node['id']] = {**node, 'output': output, 'call': call}
    if steps['draft']['output'] != baseline['steps'][-2]['output']:
        raise ValueError('The replayed draft differs from the saved baseline')
    calls = [n['call'].get('usage') or {} for n in steps.values() if n['call']]
    usage = {}
    for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        values = [row.get(field) for row in calls]
        if all(type(v) is int for v in values):
            usage[field] = sum(values)
    result = {'id': sample, 'effort': effort, 'steps': list(steps.values()),
              'baseline': baseline['score'], 'v1': v1['score'],
              'baseline_usage': baseline['usage'], 'v1_usage': v1['usage'],
              'usage': usage, 'model_calls': len(calls),
              'draft_source': (V1.relative_to(ROOT) / old / 'response.json').as_posix(),
              'score': score(case, steps['execute']['output'])}
    save(record, result)
    return result


def main(mode):
    plan_path = V1_METADATA / 'plan.json'
    plan = load(plan_path)
    ids = [*plan['anchor'], *(r['pair'] + '-' + s for r in plan['selected'] for s in ('pre', 'post'))]
    if mode == 'inspect':
        routes = {}
        for effort in EFFORTS:
            for sample in ids:
                baseline = archive(Path('records/baseline') / effort / (sample + '.json'))
                check = inspect_draft(Scenario.from_id(sample), baseline['steps'][-2]['output'].get('sql'))
                routes[effort, sample] = check['route']
                if check['route'] != 'keep':
                    print(effort, sample, check['route'],
                          [(row['source'], row['target'], row['term']) for row in check['options']])
        print({route: list(routes.values()).count(route) for route in ('keep', 'auto', 'review')})
        return 0
    if mode != 'run':
        raise ValueError('Use inspect or run')
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    key = settings['THINGO_API_KEY']
    samples = samples_by_id()
    config = make_config([samples[s] for s in ids], MODEL, endpoint)
    old_config = load(V1_METADATA / 'config.json')
    for field in ('model', 'endpoint', 'data_source', 'database_sha256', 'evaluator_commit', 'system'):
        if config[field] != old_config[field]:
            raise ValueError(f'Comparison differs from v1 in {field}')
    here = Path(__file__).parent
    source = [Path(__file__), here / 'filter_column_v2.py', here / 'format_canvas.py',
              here / 'split_output_v3.py', here / 'iterations/guarded_replay.py',
              here / 'experiment.py', here / 'run.py']
    config.update(graph=GRAPH_V2, source_plan_sha256=digest(plan_path),
                  source_config_sha256=digest(V1_METADATA / 'config.json'),
                  reasoning_efforts=list(EFFORTS),
                  code_sha256={str(p.relative_to(ROOT)): digest(p) for p in source},
                  draft_policy='Reuse the same matched request and response from v1 baseline')
    path = OUT / 'config.json'
    if path.exists() and load(path) != config:
        raise ValueError('Frozen v2 configuration differs')
    save(path, config)
    save(OUT / 'structure-v2.json', GRAPH_V2)
    failures = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {pool.submit(evaluate, sample, effort, endpoint, key): (sample, effort)
                for sample in ids for effort in EFFORTS}
        for future in as_completed(jobs):
            try:
                future.result()
            except Exception as error:
                failure = {'sample': jobs[future], 'error': str(error).replace(key, '[REDACTED]')}
                failures.append(failure)
                print(failure, flush=True)
    save(OUT / 'failures.json', failures)
    print(f'{len(jobs) - len(failures)}/{len(jobs)} v2 scores recorded', flush=True)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))
