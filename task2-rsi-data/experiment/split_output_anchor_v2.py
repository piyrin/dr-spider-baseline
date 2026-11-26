"""Run two independent repeats of the four original-question v2 conditions."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from experiment import ROOT, Scenario, execute_sql, samples_by_id, score
from projection_compare import EFFORTS, MODEL
from run import complete_at
from run_full_evaluation import digest, load, make_config, read_settings, save
from split_output_canvas import EXAMPLES
from split_output_v2 import GRAPH_V2, split_step_v2, validate_split_v2

OUT = ROOT / 'runs/task2-split-output-v2'
REPEATS = (1, 2)


def evaluate(case, effort, repeat, endpoint, key):
    folder = OUT / f'repeat-{repeat}' / effort / case.id
    ordered = validate_split_v2(GRAPH_V2)
    steps = {}

    def complete(node_id, request):
        path = folder / node_id
        request = {**request, 'reasoning_effort': effort}
        if (path / 'request.json').exists() and load(path / 'request.json') != request:
            raise ValueError('Stored request differs from current conditions')
        assert case.gold_sql not in request['messages'][-1]['content']
        save(path / 'request.json', request)
        response_path = path / 'response.json'
        if response_path.exists():
            return load(response_path)
        answer = complete_at(endpoint, key, request)
        save(response_path, answer)
        return answer

    for node in ordered:
        output, call = split_step_v2(node, case, MODEL, [steps[parent] for parent in node['from']], complete)
        steps[node['id']] = {**node, 'output': output, 'call': call}
    final = steps['execute']['output']
    scored = score(case, final)
    if final.get('sql'):
        assert score(case, execute_sql(case.database, final['sql'])) == scored
    calls = [step['call'] for step in steps.values() if step['call']]
    usage = [(call['usage'] or {}).get('total_tokens') for call in calls]
    record = {'id': case.id, 'effort': effort, 'repeat': repeat, 'score': scored,
              'steps': list(steps.values()), 'model_calls': len(calls),
              'total_tokens': sum(usage) if all(type(n) is int for n in usage) else None}
    save(folder / 'record.json', record)
    print(repeat, effort, case.id, scored['status'], steps['contract']['output']['route'],
          final.get('columns'), record['total_tokens'], flush=True)
    return record


def main():
    samples = samples_by_id()
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    config = make_config([samples[id] for id in EXAMPLES], MODEL, endpoint)
    paths = [Path(__file__).with_name(name) for name in
             ('split_output_v2.py', 'split_output_canvas.py', 'split_output_anchor_v2.py', 'experiment.py', 'run.py')]
    config.update(graph=GRAPH_V2, efforts=list(EFFORTS), repeats=list(REPEATS),
                  implementation_sha256={str(path.relative_to(ROOT)): digest(path) for path in paths})
    path = OUT / 'config.json'
    if path.exists() and load(path) != config:
        raise ValueError('Existing comparison configuration differs')
    save(path, config)
    jobs = [(Scenario.from_id(id), effort, repeat, endpoint, settings['THINGO_API_KEY'])
            for repeat in REPEATS for effort in EFFORTS for id in EXAMPLES]
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = [pool.submit(evaluate, *job) for job in jobs]
        records = [future.result() for future in pending]
    save(OUT / 'summary.json', [{k: v for k, v in row.items() if k != 'steps'} for row in records])
    print('Passed', sum(row['score']['correct'] for row in records), '/', len(records))


if __name__ == '__main__':
    main()
