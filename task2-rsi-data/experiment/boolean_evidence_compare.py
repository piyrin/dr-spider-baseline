"""Run the second structure against the first structure's frozen case list."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys

from boolean_canvas import EXAMPLES
from boolean_compare import EFFORTS, MODEL, OUT as FIRST
from boolean_evidence_canvas import GRAPH, evidence_step, validate_evidence
from experiment import ROOT, Scenario, samples_by_id, score
from run import complete_at
from run_full_evaluation import digest, load, make_config, read_settings, save

OUT = ROOT/'runs/task2-filter-boolean-evidence-v2'
METHOD = 'evidence_v2'


def run_side(sample, effort, endpoint, key):
    case = Scenario.from_id(sample['id'])
    record_path = OUT/'records'/METHOD/effort/(case.id+'.json')
    if record_path.exists():
        return
    steps = {}

    def complete(node_id, payload):
        folder = OUT/'requests'/METHOD/effort/case.id/node_id
        request, response = folder/'request.json', folder/'response.json'
        payload = {**payload, 'reasoning_effort': effort}
        if request.exists() and load(request) != payload:
            raise ValueError(f'Existing request differs: {case.id}/{node_id}')
        save(request, payload)
        if response.exists():
            return load(response)
        result = complete_at(endpoint, key, payload)
        save(response, result)
        return result

    for node in validate_evidence(GRAPH):
        upstream = [steps[parent] for parent in node['from']]
        output, call = evidence_step(node, case, MODEL, upstream, complete)
        steps[node['id']] = {**node, 'output': output, 'call': call}
    calls = [s['call'] for s in steps.values() if s['call']]
    usage = {}
    for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        amounts = [(call.get('usage') or {}).get(field) for call in calls]
        if all(type(v) is int for v in amounts):
            usage[field] = sum(amounts)
    save(record_path, {'id': case.id, 'side': sample['side'], 'original_id': sample['original_id'],
                       'method': METHOD, 'effort': effort, 'steps': list(steps.values()),
                       'usage': usage, 'model_calls': len(calls),
                       'score': score(case, steps['execute']['output'])})


def main(mode):
    first_plan = load(FIRST/'plan.json')
    assert len(first_plan['selected']) == 16
    first_files = [FIRST/'plan.json', FIRST/'config.json', FIRST/'summary.json']
    files = [Path(__file__).with_name(name) for name in (
        'boolean_evidence_canvas.py', 'boolean_canvas.py', 'experiment.py', 'run.py', 'boolean_evidence_compare.py')]
    plan = {'selected': first_plan['selected'], 'anchor': EXAMPLES, 'graph': GRAPH,
            'first_version_records': (FIRST/'records').relative_to(ROOT).as_posix(),
            'first_reference_sha256': {p.relative_to(ROOT).as_posix(): digest(p) for p in first_files},
            'code_sha256': {p.relative_to(ROOT).as_posix(): digest(p) for p in files}}
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/')+'/chat/completions'
    key = settings['THINGO_API_KEY']
    ids = [*EXAMPLES, *(row['pair']+'-'+side for row in plan['selected'] for side in ('pre', 'post'))]
    samples = samples_by_id()
    config = make_config([samples[k] for k in ids], MODEL, endpoint)
    config.update(graph=GRAPH, reasoning_efforts=list(EFFORTS), method=METHOD)
    for name, data in (('plan.json', plan), ('config.json', config)):
        path = OUT/name
        if path.exists() and load(path) != data:
            raise ValueError(f'Frozen experiment differs: {name}')
        if not path.exists():
            save(path, data)
    if mode not in ('anchor', 'run'):
        raise ValueError('Use anchor or run')
    if mode == 'anchor':
        ids = list(EXAMPLES)
    tasks = [(samples[k], effort) for k in ids for effort in EFFORTS]
    done, failures = 0, []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(run_side, s, e, endpoint, key): (s['id'], e) for s,e in tasks}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as error:
                failures.append({'condition': futures[future], 'error': str(error).replace(key, '[REDACTED]')})
                print('Failed', failures[-1], flush=True)
            else:
                done += 1
                if done % 4 == 0:
                    print(f'{done}/{len(tasks)} second-version conditions scored', flush=True)
    save(OUT/('failures.json' if mode=='run' else 'anchor-failures.json'), failures)
    print(f'{done}/{len(tasks)} scored; {len(failures)} failures', flush=True)
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
