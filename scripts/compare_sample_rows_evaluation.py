"""Compare matched Dr.Spider runs with and without three example rows per table."""

import argparse
from collections import Counter, defaultdict
import csv
from pathlib import Path
from statistics import mean, median

from summarize_full_evaluation import collect, load, summarize, write_json


def require_complete(run, samples, records, model):
    if len(records) != len(samples):
        raise ValueError(f'{run}: {len(records)}/{len(samples)} records')
    for record in records.values():
        if record['model'] != model or type(record['correct']) is not bool:
            raise ValueError(f"{run}: unscored case or mismatched API model: {record['id']}")


def compare(samples, baseline, augmented):
    base_groups = summarize(samples, baseline)
    augmented_groups = summarize(samples, augmented)
    by_group = defaultdict(list)
    for sample in samples:
        by_group[sample['group']].append(sample)

    rows = []
    for base, new in zip(base_groups, augmented_groups, strict=True):
        group = base['group']
        subset = samples if group == 'overall' else by_group[group]
        changes = {}
        for side in ('pre', 'post'):
            transitions = Counter(
                (baseline[s['id']]['correct'], augmented[s['id']]['correct'])
                for s in subset if s['side'] == side
            )
            changes[side] = {
                'repaired': transitions[False, True],
                'regressed': transitions[True, False],
                'both_correct': transitions[True, True],
                'both_incorrect': transitions[False, False],
                'delta_pp': 100 * (new[f'{side}_ex'] - base[f'{side}_ex']),
            }
        for metrics in (base, new):
            denominator = metrics['pre_correct']
            metrics['relative_robustness'] = metrics['both_pass'] / denominator if denominator else None
        rows.append({'group': group, 'baseline': base, 'select3': new, 'changes': changes})
    return rows


def usage_summary(records):
    counts = [r['usage']['prompt_tokens'] for r in records.values()
              if r.get('usage') and r['usage'].get('prompt_tokens') is not None]
    return {'input_token_records': len(counts), 'input_tokens_total': sum(counts),
            'input_tokens_median': median(counts) if counts else None,
            'input_tokens_mean': mean(counts) if counts else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('select3', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()

    samples, baseline = collect(args.baseline)
    augmented_samples, augmented = collect(args.select3)
    if samples != augmented_samples:
        parser.error('Frozen sample manifests differ')
    configs = [load(run / 'config.json') for run in (args.baseline, args.select3)]
    baseline_config, augmented_config = configs
    if baseline_config.get('sample_rows', 0) != 0 or augmented_config.get('sample_rows') != 3:
        parser.error('Expected the schema-only run followed by the Select 3 run')
    for key in ('model', 'model_digest', 'endpoint', 'data_source', 'database_sha256',
                'sampling', 'parameters', 'metric', 'evaluator_commit', 'system',
                'sqlite_version', 'python_version', 'dependencies'):
        if baseline_config[key] != augmented_config[key]:
            parser.error(f'Incomparable run settings: {key}')
    for run, records, config in zip((args.baseline, args.select3), (baseline, augmented),
                                    configs, strict=True):
        require_complete(run, samples, records, config['model'])

    groups = compare(samples, baseline, augmented)
    macro_robustness = {}
    for name in ('baseline', 'select3'):
        subgroup_rates = [group[name]['relative_robustness'] for group in groups[1:]]
        defined_rates = [rate for rate in subgroup_rates if rate is not None]
        macro_robustness[name] = {'value': mean(defined_rates) if defined_rates else None,
                                  'defined_groups': len(defined_rates)}
    pre_failed_post = [
        s['id'] for s in samples if s['side'] == 'post' and not baseline[s['id']]['correct']
        and baseline[s['id'].removesuffix('-post') + '-pre']['correct']
    ]

    args.destination.mkdir(parents=True, exist_ok=True)
    meta_keys = ('data_source', 'model', 'model_digest', 'parameters', 'sampling',
                 'evaluator_commit', 'metric', 'sqlite_version', 'python_version')
    metadata = {
        **{key: augmented_config[key] for key in meta_keys},
        'runs': {'baseline': args.baseline.name, 'select3': args.select3.name},
        'code_commits': {'baseline': baseline_config['code_commit'],
                         'select3': augmented_config['code_commit']},
        'sample_rows': augmented_config['sample_rows'],
        'schema_sample_method': augmented_config['schema_sample_method'],
        'prompt_context_sha256': augmented_config['prompt_context_sha256'],
        'source_sha256': augmented_config['source_sha256'],
        'question_sides': len(samples),
        'unique_original_questions': len({s['original_id'] for s in samples}),
        'database_files': len(augmented_config['database_sha256']),
        'groups': groups,
        'relative_robustness_macro': macro_robustness,
        'historical_pre_pass_post_fail': {
            'total_pairs': len(pre_failed_post),
            'post_repaired': sum(augmented[case]['correct'] for case in pre_failed_post),
            'both_pass_with_sample_rows': sum(
                augmented[case]['correct'] and augmented[case.removesuffix('-post') + '-pre']['correct']
                for case in pre_failed_post
            ),
        },
        'input_usage': {'baseline': usage_summary(baseline), 'select3': usage_summary(augmented)},
        'statuses': {name: dict(Counter(r['status'] for r in records.values()))
                     for name, records in [('baseline', baseline), ('select3', augmented)]},
        'fingerprints': {
            name: dict(Counter(r['system_fingerprint'] or 'unavailable' for r in records.values()))
            for name, records in [('baseline', baseline), ('select3', augmented)]
        },
    }
    write_json(args.destination / 'comparison.json', metadata)
    id_fields = ('id', 'group', 'side', 'original_id', 'db_id', 'question', 'gold_sql')
    comparison_fields = ('correct', 'status', 'prediction_sql', 'prompt_tokens')
    with (args.destination / 'paired_predictions.csv').open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.DictWriter(file, fieldnames=[
            *id_fields,
            *(f'{name}_{field}' for name in ('baseline', 'select3') for field in comparison_fields),
        ])
        writer.writeheader()
        for sample in samples:
            case = {key: sample[key] for key in id_fields}
            for name, records in [('baseline', baseline), ('select3', augmented)]:
                record = records[sample['id']]
                for field in comparison_fields[:-1]:
                    case[f'{name}_{field}'] = record[field]
                case[f'{name}_prompt_tokens'] = (record.get('usage') or {}).get('prompt_tokens')
            writer.writerow(case)
    print(f'Compared {len(samples)} matched question sides across {len(groups) - 1} groups')


if __name__ == '__main__':
    main()
