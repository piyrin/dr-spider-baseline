"""Freeze case 10 regression pairs and compare the unchanged canvas with baseline."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from itertools import product
from pathlib import Path
import re
import sys

import filter_count_compare as experiment
from experiment import ROOT, Scenario, samples_by_id
from filter_count_canvas import EXAMPLES, GRAPH
from projection_exposure import exposure
from run_full_evaluation import digest, load, make_config, read_settings, save

OUT = ROOT / 'runs/task2-filter-count-regression-v1'
SEED = 'filter-count-regression-v1-20261126'
METHODS = ('baseline', 'canvas_v1')


def freeze(samples):
    file = OUT / 'plan.json'
    if file.exists():
        return load(file)
    seen_originals, _, historical = exposure(samples)
    seen_pairs = set(historical)
    anchor = EXAMPLES[0].rsplit('-', 1)[0]
    ordered = sorted((row for row in samples.values() if row['side'] == 'post'), key=lambda row: (
        row['id'][:-5] in seen_pairs, sha256((SEED + row['id']).encode()).digest()))
    selected = []
    used_pairs = {anchor}
    used_originals = {485, 486}

    def add(row, label, reason):
        pair = row['id'][:-5]
        assert pair not in used_pairs
        used_pairs.add(pair)
        used_originals.add(row['original_id'])
        selected.append({'pair': pair, 'original_id': row['original_id'], 'db_id': row['db_id'],
                         'group': row['group'], 'label': label, 'reason': reason,
                         'previously_seen_pair': pair in seen_pairs})

    count_distinct = re.compile(r'^SELECT\s+COUNT\s*\(\s*DISTINCT\b', re.I)
    for original_id, question_group in ((485, 'NLQ_others'), (486, 'NLQ_keyword_carrier')):
        for group, reason in (
            ('DB_DBcontent_equivalence', '左右手字段改成布尔编码'),
            ('DB_schema_synonym', '赛事、获胜者或左右手字段改名'),
            (question_group, '在仍询问人数的情况下改写题面'),
            ('SQL_DB_text', '替换赛事名称，保持双条件去重计数'),
        ):
            row = next(row for row in ordered if row['original_id'] == original_id
                       and row['group'] == group and row['id'][:-5] not in used_pairs
                       and count_distinct.search(row['gold_sql'])
                       and ('how many' in row['question'].lower() or group != question_group)
                       and not re.search(r'how many times|both of', row['question'], re.I))
            add(row, 'target', reason)

    for original_id, reason in (
        (734, '单条件但统计去重属性类别'),
        (770, '有关联、数值比较和布尔条件的跨表去重计数'),
        (625, '检查其他单表或关联查值方式是否影响基线'),
    ):
        add(next(row for row in ordered if row['original_id'] == original_id), 'mixed', reason)

    selectors = [
        ('DB_DBcontent_equivalence', r'writer_firstname.*AND.*writer_lastname', '双等值条件下统计记录数'),
        ('SQL_comparison', r'\bCOUNT\s*\(', '含数值比较的计数'),
        ('NLQ_keyword_synonym', r'^SELECT\s+COUNT\s*\([^)]*\)\s+FROM\s+\w+\s*$', '无筛选条件计数'),
        ('SQL_sort_order', r'\bORDER BY\b', '排序类问题'),
        ('NLQ_column_carrier', r'^SELECT\s+(?!COUNT\b)', '列输出类问题'),
    ]
    for group, pattern, reason in selectors:
        add(next(row for row in ordered if row['group'] == group and row['original_id'] not in used_originals
                 and re.search(pattern, ' '.join(row['gold_sql'].split()).rstrip(';'), re.I)), 'mixed', reason)
    assert Counter(row['label'] for row in selected) == {'target': 8, 'mixed': 8}
    files = [Path(__file__), Path(experiment.__file__),
             Path(__file__).with_name('filter_count_canvas.py'),
             Path(__file__).with_name('experiment.py'), Path(__file__).with_name('run.py')]
    plan = {'seed': SEED, 'anchor': EXAMPLES, 'selected': selected, 'observed_originals': len(seen_originals),
            'conditions': list(product(METHODS, experiment.EFFORTS)), 'graph': GRAPH,
            'source_sha256': {str(path.relative_to(ROOT)): digest(path) for path in files}}
    save(file, plan)
    return load(file)


def main(mode):
    samples = samples_by_id()
    plan = freeze(samples)
    for row in plan['selected']:
        print(row['label'], row['pair'], row['original_id'], row['db_id'], row['previously_seen_pair'], flush=True)
    if mode == 'prepare':
        return
    if mode != 'run':
        raise ValueError('Use prepare or run')
    for relative, expected in plan['source_sha256'].items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f'Frozen source changed: {relative}')
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    key = settings['THINGO_API_KEY']
    ids = [*EXAMPLES, *(r['pair'] + '-' + side for r in plan['selected'] for side in ('pre', 'post'))]
    config = make_config([samples[case_id] for case_id in ids], experiment.MODEL, endpoint)
    config.update(plan_sha256=digest(OUT / 'plan.json'), reasoning_efforts=list(experiment.EFFORTS))
    file = OUT / 'config.json'
    if file.exists() and load(file) != config:
        raise ValueError('Existing configuration differs from the frozen run')
    save(file, config)

    # Reuse the exact anchor evaluator with an independent result root.
    experiment.OUT = OUT
    failures = []
    jobs = list(product(ids, METHODS, experiment.EFFORTS))
    with ThreadPoolExecutor(max_workers=10) as pool:
        pending = {pool.submit(experiment.evaluate, Scenario.from_id(job[0]), *job[1:], endpoint, key): job
                   for job in jobs}
        for number, task in enumerate(as_completed(pending), 1):
            try:
                task.result()
            except Exception as error:
                failure = {'condition': pending[task], 'error': str(error).replace(key, '[REDACTED]')}
                failures.append(failure)
                print(failure, flush=True)
            if number % 8 == 0:
                print(f'{number}/{len(jobs)} recorded jobs, {len(failures)} transport failures', flush=True)
    save(OUT / 'failures.json', failures)
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
