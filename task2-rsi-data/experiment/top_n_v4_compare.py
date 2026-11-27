"""Run the v4 rule selection on the frozen v3 comparison and matched baseline."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys
import time

from experiment import ROOT, score
from projection_compare import MODEL
from run import complete_at
from run_full_evaluation import digest, load, read_settings, save
from top_n_v3_compare import case_for
from top_n_v4 import GRAPH_V4, run_step, validate_v4

BASE = ROOT / 'runs/task2-top-n-v3'
OUT = ROOT / 'runs/task2-top-n-v4'


def freeze():
    base = load(BASE / 'plan.json')
    directory = Path(__file__).parent
    files = [Path(__file__), *(directory / name for name in
             ('top_n_v4.py', 'top_n_v3.py', 'top_n_v3_cases.py', 'experiment.py', 'run.py'))]
    plan = {'base_plan_sha256': digest(BASE / 'plan.json'), 'groups': base['groups'],
            'efforts': base['efforts'], 'structure': GRAPH_V4,
            'source_sha256': {str(p.relative_to(ROOT)): digest(p) for p in files}}
    path = OUT / 'plan.json'
    if path.exists() and load(path) != plan:
        raise ValueError('Frozen v4 plan differs')
    save(path, plan)
    return plan


def evaluate(sample, effort, endpoint, key):
    folder = OUT / 'records' / effort / sample
    path = folder / 'record.json'
    if path.exists():
        return
    case = case_for(sample)
    steps, sources = {}, {}
    baseline = BASE / 'records/baseline' / effort / sample

    def complete(node, payload):
        request = {**payload, 'reasoning_effort': effort}
        target = folder / node
        req, res, origin = (target / f'{name}.json' for name in ('request', 'response', 'source'))
        if req.exists() and load(req) != request:
            raise ValueError('Saved request differs')
        save(req, request)
        if res.exists():
            sources[node] = load(origin)['source']
            return load(res)
        matched = baseline / node
        if node == 'generate' and (matched / 'request.json').exists() and load(matched / 'request.json') == request:
            answer = load(matched / 'response.json')
            sources[node] = 'paired_baseline'
        else:
            for attempt in (1, 2):
                try:
                    answer = complete_at(endpoint, key, request)
                except Exception as error:
                    save(target / f'error-{attempt}.json', {'error': str(error).replace(key, '[REDACTED]')})
                    if attempt == 2:
                        raise
                    time.sleep(1)
                else:
                    break
            sources[node] = 'live'
        save(origin, {'source': sources[node]})
        save(res, answer)
        return answer

    for node in validate_v4(GRAPH_V4):
        output, call = run_step(node, case, MODEL, [steps[p] for p in node['from']], complete)
        steps[node['id']] = {**node, 'output': output, 'call': call}
    final = steps['execute']['output']
    calls = [node['call'] for node in steps.values() if node['call']]
    tokens = [(call.get('usage') or {}).get('total_tokens') for call in calls]
    save(path, {'id': sample, 'effort': effort, 'steps': list(steps.values()), 'score': score(case, final),
                'route': final['route'], 'rule': final.get('rule'), 'model_calls': len(calls),
                'total_tokens': sum(tokens) if all(type(v) is int for v in tokens) else None,
                'response_sources': sources})


def main(mode):
    plan = freeze()
    if mode == 'prepare':
        print('Frozen', sum(map(len, plan['groups'].values())) // 2, 'pairs')
        return 0
    if mode != 'run':
        raise ValueError('Use prepare or run')
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    key = settings['THINGO_API_KEY']
    save(OUT / 'config.json', {'model': MODEL, 'endpoint': endpoint, 'requested_efforts': plan['efforts'],
                              'baseline_config_sha256': digest(BASE / 'config.json'),
                              'plan_sha256': digest(OUT / 'plan.json')})
    jobs = [(sample, effort) for effort in plan['efforts'] for ids in plan['groups'].values() for sample in ids]
    errors = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = {pool.submit(evaluate, *job, endpoint, key): job for job in jobs}
        for count, future in enumerate(as_completed(pending), 1):
            try:
                future.result()
            except Exception as error:
                detail = {'case': pending[future], 'error': str(error).replace(key, '[REDACTED]')}
                errors.append(detail)
                print(detail, flush=True)
            if count % 8 == 0 or count == len(pending):
                print(f'{count}/{len(pending)} completed, {len(errors)} errors', flush=True)
    save(OUT / 'failures.json', errors)
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))
