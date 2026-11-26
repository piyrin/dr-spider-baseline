"""Compare the frozen v2 router on all 18 historical projection cue regressions."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime
import re
import sys

import projection_compare as compare
from experiment import ROOT, Scenario, columns_for, samples_by_id
from projection_generalization import GRAPH_V2, find_name
from run_full_evaluation import digest, load, make_config, read_settings, save


OUT = ROOT / 'runs/task2-projection-historical-v2'
SOURCE = ROOT / '.local/task2-experiment/问题子类与开发样本.md'
HISTORY = ROOT / 'results/drspider-17x50/prepass-postfail-review.csv'
PREDICTIONS = HISTORY.with_name('predictions.csv')
EFFORT = 'none'


def history_plan():
    samples = samples_by_id()
    line = next(s for s in SOURCE.read_text(encoding='utf-8').splitlines()
                if s.startswith('- **输出线索由具体变宽**'))
    stems = re.findall(r'`([A-Za-z_]+-\d{5})`', line)
    with HISTORY.open(encoding='utf-8-sig', newline='') as stream:
        review = {row['pair_id']: row for row in csv.DictReader(stream)}
    with PREDICTIONS.open(encoding='utf-8-sig', newline='') as stream:
        reference = {row['id']: row for row in csv.DictReader(stream)}
    assert len(review) == 134 and len(stems) == len(set(stems)) == 18
    pairs, selected = [], []
    for stem in stems:
        assert stem in review and review[stem]['status'] == '纳入修复研究'
        item = {'pair': stem}
        for side, expected in (('pre', 'True'), ('post', 'False')):
            side_id = f'{stem}-{side}'
            sample = samples[side_id]
            assert reference[side_id]['correct'] == expected
            assert int(review[stem]['original_id']) == sample['original_id']
            case = Scenario.from_id(side_id)
            route, field = find_name(case.question, columns_for(case.database))
            item.update(original_id=sample['original_id'], db_id=sample['db_id'])
            item[side] = {'id': side_id, 'route': route, 'field': field}
            selected.append(sample)
        pairs.append(item)
    assert len({row['original_id'] for row in pairs}) == 14
    version = ROOT / '.local/task2-experiment'
    sources = [SOURCE, HISTORY, PREDICTIONS, ROOT / 'scripts/run_full_evaluation.py']
    sources.extend(version/file for file in ('projection_history.py', 'projection_compare.py',
                                              'projection_generalization.py', 'projection_canvas.py',
                                              'experiment.py'))
    return {'selected': pairs, 'selection': 'all 18 of 134 historical reviewed output-cue widening pairs',
            'effort': EFFORT, 'source_sha256': {str(p.relative_to(ROOT)): digest(p) for p in sources}}, selected


def main():
    plan, samples = history_plan()
    if (OUT/'plan.json').exists() and plan != load(OUT/'plan.json'):
        raise ValueError('Frozen history scope or code changed')
    save(OUT/'plan.json', plan)
    print('Frozen 18 historical pairs from 14 originals.', flush=True)
    for row in plan['selected']:
        print(row['pair'], f'{row["pre"]["route"]} / {row["post"]["route"]}', flush=True)
    if len(sys.argv) == 1 or sys.argv[1] == 'prepare':
        return 0
    if sys.argv[1] != 'run':
        raise ValueError('Choose prepare or run.')
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    assert endpoint == 'https://intlapi.thingo.com.cn/v1/chat/completions'
    config = make_config(samples, compare.MODEL, endpoint)
    config.update(reasoning_effort=EFFORT, selection_sha256=digest(OUT/'plan.json'), graph=GRAPH_V2)
    if (OUT/'config.json').exists() and config != load(OUT/'config.json'):
        raise ValueError('Frozen history run configuration changed')
    save(OUT/'config.json', config)
    compare.OUT = OUT
    live = {'endpoint': endpoint, 'key': settings['THINGO_API_KEY']}
    tasks = [(sample, method) for i, sample in enumerate(samples)
             for method in (compare.METHODS if i % 2 == 0 else compare.METHODS[::-1])]
    done, errors = 0, []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(compare.evaluate, s, method, EFFORT, live): (s['id'], method)
                   for s, method in tasks}
        for f in as_completed(futures):
            key = futures[f]
            try:
                r = f.result()
                done += 1
                if done % 6 == 0:
                    print(f'{done}/{len(tasks)}', *key, r['score']['status'], flush=True)
            except Exception as error:
                detail = {'condition': key, 'error': str(error).replace(live['key'], '[REDACTED]')}
                errors.append(detail)
                print(detail, flush=True)
    save(OUT/('failures-' + datetime.now().strftime('%H%M%S') + '.json'), errors)
    print(f'{done}/{len(tasks)} scored. {len(errors)} failed.', flush=True)
    return bool(errors)


if __name__ == '__main__':
    sys.exit(main())
