"""Check provider accounting for prompt placement on the same questions."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean

from variants import CHECKS, HERE
from experiment import Scenario
from run import complete_at, model_client
from run_api_sample import load, save
from run_full_evaluation import make_payload


COMPACT = ('Return only requested fields. Set the row grain before joining. '
           'Count qualifying rows at that grain, including zero matches only when requested. '
           'Rank by the requested measure and direction.')


def payload_for(mode, case, model):
    payload = make_payload(model, {'database': case.database, 'question': case.question})
    if mode == 'U':
        payload['messages'][1]['content'] += '\n\nChecks before writing SQL: ' + ' '.join(
            CHECKS[k] for k in ('joined_population', 'group_scope', 'ranked_scope', 'projection'))
    elif mode == 'C':
        payload['messages'][1]['content'] += '\n\n' + COMPACT
    elif mode == 'T':
        payload['messages'][0]['content'] += ' ' + COMPACT
    elif mode != 'baseline':
        raise ValueError(mode)
    return payload


def main():
    directory = HERE/'cost-probe'
    model, endpoint, token = model_client()
    items = load(HERE/'confirm/manifest.json')[:12]

    def run(item, mode):
        case = Scenario.from_id(item['id'])
        payload = payload_for(mode, case, model)
        p = directory/'calls'/f'{case.id}--{mode}.json'
        if p.exists():
            row = load(p)
            assert row['request']==payload
            return mode, row['response']['usage']
        response = complete_at(endpoint, token, payload)
        save(p, {'request': payload, 'response': response})
        return mode, response['usage']

    readings = {}
    with ThreadPoolExecutor(max_workers=9) as pool:
        jobs = [pool.submit(run, row, mode) for row in items for mode in ('U','C','T')]
        for job in as_completed(jobs):
            mode, usage = job.result()
            readings.setdefault(mode, []).append(usage)
    result = {k: {metric: mean(row[metric] for row in values)
                  for metric in ('prompt_tokens','completion_tokens','total_tokens')} | {'n':len(values)}
              for k, values in readings.items()}
    save(directory/'summary.json', result)
    print(result)


if __name__ == '__main__':
    main()
