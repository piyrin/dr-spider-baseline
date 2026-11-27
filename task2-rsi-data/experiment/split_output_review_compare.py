"""Compare each saved initial draft with its reviewed final query."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from experiment import ROOT, Scenario, execute_sql, samples_by_id, score
from projection_compare import EFFORTS, MODEL
from run import complete_at
from run_full_evaluation import digest, load, make_config, read_settings, save
from split_output_canvas import EXAMPLES
from split_output_v3 import GRAPH_V3, ReviewInput, review_step, validate_v3

OUT = ROOT / 'runs/task2-split-output-v3'
PLAN = ROOT / 'runs/task2-split-output-v1/plan.json'


def run_case(case, effort, batch, endpoint, key):
    folder = OUT / batch / effort / case.id
    path = folder / 'record.json'
    if path.exists():
        return load(path)

    def complete(node, payload):
        request = {**payload, 'reasoning_effort': effort}
        req, res = (folder / node / f'{name}.json' for name in ('request', 'response'))
        if req.exists() and load(req) != request:
            raise ValueError('Saved request differs from frozen settings')
        save(req, request)
        if res.exists():
            return load(res)
        response = complete_at(endpoint, key, request)
        save(res, response)
        return response

    steps = {}
    runtime_case = ReviewInput(case.question, case.database)
    for node in validate_v3(GRAPH_V3):
        output, call = review_step(node, runtime_case, MODEL, [steps[k] for k in node['from']], complete)
        steps[node['id']] = {**node, 'output': output, 'call': call}
    draft = steps['draft']['output']
    if draft.get('sql'):
        initial = execute_sql(case.database, draft['sql'])
    else:
        initial = {'status': draft.get('status', 'generation_error'), 'reason': draft.get('reason')}
    final = steps['execute']['output']
    record = {'id': case.id, 'effort': effort, 'batch': batch, 'steps': list(steps.values()),
              'initial': initial, 'draft_score': score(case, initial), 'score': score(case, final)}
    save(path, record)
    return record


def run_batches(batches, endpoint, key):
    failures = []
    jobs = [(Scenario.from_id(sample), effort, name, endpoint, key)
            for name, ids in batches for sample in ids for effort in EFFORTS]
    with ThreadPoolExecutor(max_workers=8) as pool:
        queued = {pool.submit(run_case, *job): (job[0].id, job[1], job[2]) for job in jobs}
        for index, future in enumerate(as_completed(queued), 1):
            try:
                record = future.result()
            except Exception as error:
                failure = {'case': queued[future], 'error': str(error).replace(key, '[REDACTED]')}
                failures.append(failure)
                print(failure, flush=True)
            else:
                if record['batch'] != 'extended':
                    print(record['batch'], record['effort'], record['id'],
                          record['draft_score']['status'], record['score']['status'],
                          record['steps'][-1]['output']['revision'], flush=True)
            if index % 8 == 0:
                print(f'{index}/{len(jobs)} finished, {len(failures)} errors', flush=True)
    return failures


def main():
    samples = samples_by_id()
    selected = load(PLAN)['selected']
    assert len(selected) == 16 and len({r['original_id'] for r in selected}) == 16
    extended = [row['pair'] + '-' + side for row in selected for side in ('pre', 'post')]
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    key = settings['THINGO_API_KEY']
    config = make_config([samples[s] for s in [*EXAMPLES, *extended]], MODEL, endpoint)
    files = [Path(__file__).with_name(name) for name in
             ('split_output_v3.py', 'split_output_review_compare.py', 'experiment.py', 'run.py')]
    config.update(graph=GRAPH_V3, efforts=list(EFFORTS), anchor=EXAMPLES, selected=selected,
                  v1_plan_sha256=digest(PLAN), comparison='same generated SQL evaluated before and after review',
                  implementation_sha256={str(p.relative_to(ROOT)): digest(p) for p in files})
    dest = OUT / 'config.json'
    if dest.exists() and load(dest) != config:
        raise ValueError('Stored configuration differs from this run')
    save(dest, config)
    anchor_errors = run_batches([('original-1', EXAMPLES), ('original-2', EXAMPLES)], endpoint, key)
    save(OUT / 'original-failures.json', anchor_errors)
    if anchor_errors:
        raise SystemExit(1)
    extended_errors = run_batches([('extended', extended)], endpoint, key)
    save(OUT / 'extended-failures.json', extended_errors)
    raise SystemExit(bool(extended_errors))


if __name__ == '__main__':
    main()
