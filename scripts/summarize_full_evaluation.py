"""Export paired EX statistics and a reproducible semantic-review sample."""

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path


REVIEW_SEED = 20261121
REVIEW_PER_STRATUM = 2
VERDICTS = {'model_error', 'valid_alternative', 'reference_issue', 'ambiguous', 'unresolved'}
MODEL_TYPES = {'return_fields', 'filter_condition', 'candidate_scope', 'aggregation_grain',
               'ranking_limit', 'set_semantics', 'generation_format', 'sql_execution'}


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def collect(run):
    samples = load(run / 'samples.json')
    samples_by_id = {sample['id']: sample for sample in samples}
    if len(samples) != len(samples_by_id):
        raise ValueError('Duplicate sample IDs')
    records = {}
    for file in (run / 'records').glob('*.json'):
        record = load(file)
        if record['id'] != file.stem or file.stem not in samples_by_id:
            raise ValueError(f'Unexpected record: {file.name}')
        records[record['id']] = record
    return samples, records


def summarize(samples, records):
    by_group = defaultdict(dict)
    for sample in samples:
        pair = by_group[sample['group']].setdefault(sample['index'], {})
        pair[sample['side']] = records.get(sample['id'], {'correct': None, 'status': 'missing'})
    rows = []
    for group, pairs in [('overall', [p for g in by_group.values() for p in g.values()]),
                         *((g, list(p.values())) for g, p in by_group.items())]:
        counts = Counter()
        for pair in pairs:
            pre = pair['pre']['correct']
            post = pair['post']['correct']
            if pre is not None and post is not None:
                counts['both_pass' if pre and post else 'pre_only' if pre else
                       'post_only' if post else 'both_fail'] += 1
            else:
                counts['pair_unscored'] += 1
        row = {'group': group, 'pairs': len(pairs)}
        for side in ('pre', 'post'):
            scores = [p[side]['correct'] for p in pairs if p[side]['correct'] is not None]
            row[f'{side}_scored'] = len(scores)
            row[f'{side}_correct'] = sum(scores)
            row[f'{side}_ex'] = sum(scores) / len(scores) if scores else None
        row.update({key: counts[key] for key in ('both_pass', 'pre_only', 'post_only',
                                                  'both_fail', 'pair_unscored')})
        denominator = len(pairs) - counts['pair_unscored']
        row['paired_delta_pp'] = (100 * (counts['post_only'] - counts['pre_only']) / denominator
                                  if denominator else None)
        rows.append(row)
    return rows


def review_plan(samples, records):
    strata = defaultdict(list)
    for sample in samples:
        record = records.get(sample['id'])
        if record and record['correct'] is False:
            strata[sample['group'], sample['side']].append(sample)
    plan = []
    for candidates in strata.values():
        chosen = sorted(candidates, key=lambda s: hashlib.sha256(
            f"{REVIEW_SEED}:{s['id']}".encode()).digest())[:REVIEW_PER_STRATUM]
        plan.extend({**sample, **records[sample['id']], 'stratum_failed': len(candidates)}
                    for sample in chosen)
    return plan


def verify_annotations(plan, annotations):
    plan_by_id = {sample['id']: sample for sample in plan}
    expected = set(plan_by_id)
    ids = [item['id'] for item in annotations]
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError(f'Annotation coverage differs. Missing: {expected - set(ids)}. '
                         f'Unexpected: {set(ids) - expected}.')
    for item in annotations:
        tag = item.get('model_type')
        if (item['verdict'] not in VERDICTS or not item['evidence'].strip()
                or (item['verdict'] == 'model_error' and tag not in MODEL_TYPES)
                or (item['verdict'] != 'model_error' and tag is not None)):
            raise ValueError(f"Invalid annotation: {item['id']}")
        case = plan_by_id[item['id']]
        for field in ('question', 'gold_sql', 'prediction_sql', 'status'):
            if field in item and item[field] != case[field]:
                raise ValueError(f"The reviewed {field} changed: {item['id']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--annotations', type=Path)
    parser.add_argument('--partial', action='store_true')
    args = parser.parse_args()
    samples, records = collect(args.run)
    if not args.partial and len(records) != len(samples):
        parser.error(f'{len(records)} of {len(samples)} records are available')
    config = load(args.run / 'config.json')
    if any(record['model'] != config['model'] for record in records.values()):
        parser.error('Returned model mismatch')
    groups = summarize(samples, records)
    plan = review_plan(samples, records)
    annotations = load(args.annotations) if args.annotations else None
    if annotations is not None:
        verify_annotations(plan, annotations)
    args.destination.mkdir(parents=True, exist_ok=True)
    sessions = [load(path) for path in sorted((args.run / 'sessions').glob('*.json'))]
    metadata = {
        'total_cases': len(samples), 'recorded_cases': len(records),
        'original_question_ids': len({s['original_id'] for s in samples}),
        'sqlite_files': len({s['database'] for s in samples}),
        'model': config['model'], 'model_digest': config['model_digest'],
        'sampling': config.get('sampling'), 'parameters': config['parameters'],
        'data_source': config['data_source'], 'code_commit': config['code_commit'],
        'evaluator_commit': config['evaluator_commit'], 'sqlite_version': config['sqlite_version'],
        'python_version': config['python_version'], 'dependencies': config['dependencies'],
        'source_sha256': config['source_sha256'], 'database_sha256': config['database_sha256'],
        'statuses': dict(Counter(record['status'] for record in records.values())),
        'fingerprints': dict(Counter(record['system_fingerprint'] or 'unavailable'
                                     for record in records.values())),
        'sessions': [{key: session[key] for key in ('started_at', 'finished_at', 'workers',
                                                   'previous_records', 'status_counts')}
                     | {'request_failures': len(session['api_failures'])} for session in sessions],
        'reference_empty_by_side': dict(Counter(sample['side'] for sample in samples
            if records.get(sample['id'], {}).get('gold_row_count') == 0)),
        'review_seed': REVIEW_SEED, 'review_cap_per_subset_side': REVIEW_PER_STRATUM,
        'review_cases': len(plan), 'review_original_ids': len({case['original_id'] for case in plan}),
        'groups': groups,
    }
    if annotations is not None:
        metadata['verdicts'] = dict(Counter(item['verdict'] for item in annotations))
        metadata['model_error_types'] = dict(Counter(item['model_type'] for item in annotations
                                                      if item['verdict'] == 'model_error'))
        annotations_by_id = {item['id']: item for item in annotations}
        plan = [sample | annotations_by_id[sample['id']] for sample in plan]
    write_json(args.destination / 'summary.json', metadata)
    write_json(args.destination / 'review_cases.json', plan)
    fields = ['id', 'group', 'index', 'side', 'original_id', 'db_id', 'database', 'question',
              'gold_sql', 'prediction_sql', 'status', 'correct', 'error', 'gold_row_count',
              'prediction_row_count']
    with (args.destination / 'predictions.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(sample | records.get(sample['id'], {'status': 'missing'}) for sample in samples)
    print(f'{len(records)}/{len(samples)} records, {len(plan)} selected for semantic review')


if __name__ == '__main__':
    main()
