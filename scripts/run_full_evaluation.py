"""Audit and run every pre/post case in the pinned Dr.Spider release."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import closing
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
from importlib.metadata import version
from itertools import zip_longest
import json
import random
import re
import sqlite3
import sys

from run_api_sample import ROOT, SYSTEM, api_json, git_output, load, read_database
from run_api_sample import read_settings, resolve_model, save

sys.path.insert(0, str(ROOT / '.cache/evaluator'))
from exec_eval import result_eq

DATA = ROOT / 'data'
INVENTORY = ROOT / 'manifests/data_inventory.json'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def iter_samples():
    for subset in load(INVENTORY)['subsets']:
        group = subset['subset']
        folder = DATA / group
        before = load(folder / 'questions_pre_perturbation.json')
        after = load(folder / 'questions_post_perturbation.json')
        if len(before) != subset['pairs'] or len(after) != len(before):
            raise ValueError(f'Pair count differs from the inventory in {group}')
        for index, (pre, post) in enumerate(zip(before, after)):
            if pre['q_id_spider_dev'] != post['q_id_spider_dev']:
                raise ValueError(f'Original question IDs differ in {group} at {index}')
            for side, item in [('pre', pre), ('post', post)]:
                db_root = DATA / 'Spider-dev/databases'
                if group.startswith('DB_') and side == 'post':
                    db_root = folder / 'database_post_perturbation'
                db_id = item['db_id']
                yield {
                    'id': f'{group}-{index:05d}-{side}',
                    'group': group, 'index': index, 'side': side,
                    'original_id': item['q_id_spider_dev'], 'db_id': db_id,
                    'database': str((db_root / db_id / f'{db_id}.sqlite').relative_to(ROOT)),
                    'question': item['question'], 'gold_sql': item['query'],
                }


def select_pairs(samples, pairs_per_group, seed):
    grouped_indexes = defaultdict(list)
    for sample in samples:
        if sample['side'] == 'pre':
            grouped_indexes[sample['group']].append(sample['index'])
    rng = random.Random(seed)
    selected = {group: set(rng.sample(indexes, pairs_per_group))
                for group, indexes in grouped_indexes.items()}
    return [s for s in samples if s['index'] in selected[s['group']]]


@lru_cache(maxsize=None)
def database_input(relative_path):
    path = ROOT / relative_path
    rows = read_database(path, "SELECT sql FROM sqlite_master WHERE type='table' "
                         "AND name NOT LIKE 'sqlite_%' ORDER BY name")
    return {'sha256': digest(path), 'schema': '\n'.join(row[0] for row in rows if row[0])}


@lru_cache(maxsize=1024)
def gold_rows(database, query):
    return read_database(ROOT / database, query)


@lru_cache(maxsize=None)
def schema_with_sample_rows(relative_path, sample_rows):
    uri = (ROOT / relative_path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        tables = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        blocks = []
        for name, ddl in tables:
            if not ddl:
                continue
            identifier = '"' + name.replace('"', '""') + '"'
            query = f'SELECT * FROM {identifier} LIMIT {sample_rows}'
            cursor = connection.execute(query)
            overhead = (f'{sample_rows} sample rows from {identifier}:\n{query};'
                        .replace('*/', '* /'))
            values = [[column[0] for column in cursor.description], *cursor.fetchall()]
            lines = [
                json.dumps(value, ensure_ascii=False, default=str).replace('*/', '*\\u002f')
                for value in values
            ]
            blocks.append('\n'.join([ddl, '/*', overhead, *lines, '*/']))
        return '\n'.join(blocks)


def make_payload(model, sample, sample_rows=0):
    path = sample['database']
    schema = (schema_with_sample_rows(path, sample_rows) if sample_rows
              else database_input(path)['schema'])
    return {'model': model, 'stream': False, 'messages': [
        {'role': 'system', 'content': SYSTEM},
        {'role': 'user', 'content': f"Schema\n{schema}\nQuestion\n{sample['question']}"},
    ]}


def prediction_sql(response):
    choice = response['choices'][0]
    if choice.get('finish_reason') != 'stop':
        raise ValueError(f"Unexpected finish reason {choice.get('finish_reason')!r}")
    prediction = choice['message']['content']
    if not isinstance(prediction, str) or not prediction.strip():
        raise ValueError('Expected nonempty text content')
    prediction = prediction.strip()
    fenced = re.fullmatch(r'```(?:sql|sqlite)?\s*(.*?)```', prediction, flags=re.I | re.S)
    if fenced:
        prediction = fenced.group(1).strip()
    if not re.match(r'^(SELECT|WITH)\b', prediction, flags=re.I):
        raise ValueError('Expected one SELECT query')
    return prediction


def score(sample, response):
    result = {'id': sample['id'], 'model': response.get('model'),
              'system_fingerprint': response.get('system_fingerprint'),
              'usage': response.get('usage'), 'prediction_sql': None,
              'correct': None, 'error': None}
    status = 'gold_execution'
    try:
        reference = gold_rows(sample['database'], sample['gold_sql'])
        result['gold_row_count'] = len(reference)
        status = 'prediction_generation'
        result['prediction_sql'] = prediction_sql(response)
        status = 'prediction_execution'
        predicted = read_database(ROOT / sample['database'], result['prediction_sql'])
        result['prediction_row_count'] = len(predicted)
        status = 'comparison_failure'
        comparison = result_eq(reference, predicted, 'order by' in sample['gold_sql'].lower())
        result.update(status='match' if comparison else 'mismatch', correct=bool(comparison))
    except Exception as error:
        result.update(status=status, error=f'{type(error).__name__}: {error}')
        if status in {'prediction_generation', 'prediction_execution'}:
            result['correct'] = False
    return result


def audit(samples):
    groups = defaultdict(Counter)
    failures = []
    unique_reference_queries = set()
    databases = set()
    original_ids = set()
    for sample in samples:
        counts = groups[sample['group']]
        side = sample['side']
        counts[f'{side}_cases'] += 1
        databases.add(sample['database'])
        original_ids.add(sample['original_id'])
        database_input(sample['database'])
        key = (sample['database'], sample['gold_sql'])
        unique_reference_queries.add(key)
        try:
            rows = gold_rows(*key)
            counts[f'{side}_empty_gold'] += not rows
            counts[f'{side}_gold_executable'] += 1
        except sqlite3.Error as error:
            counts[f'{side}_gold_execution_failure'] += 1
            failures.append({'id': sample['id'], 'db_id': sample['db_id'],
                             'gold_sql': sample['gold_sql'], 'error': str(error)})
    return {'question_sides': len(samples), 'original_ids': len(original_ids),
            'database_files': len(databases), 'unique_reference_queries': len(unique_reference_queries),
            'subsets': dict(groups), 'reference_execution_failures': failures}


def make_config(samples, model, endpoint):
    subset_files = {DATA / s['group'] / f"questions_{s['side']}_perturbation.json" for s in samples}
    source_files = {INVENTORY, ROOT / 'src/baseline.py', ROOT / 'scripts/run_api_sample.py',
                    ROOT / 'scripts/run_full_evaluation.py', ROOT / '.cache/evaluator/exec_eval.py'}
    return {
        'data_source': load(ROOT / 'manifests/data_source.json'),
        'source_sha256': {str(path.relative_to(ROOT)): digest(path)
                          for path in sorted(subset_files | source_files)},
        'database_sha256': {path: database_input(path)['sha256']
                            for path in sorted({s['database'] for s in samples})},
        'endpoint': endpoint, 'model': model, 'model_digest': None,
        'parameters': {'stream': False, 'other_generation_parameters': 'provider defaults'},
        'system': SYSTEM, 'metric': 'single-database EX', 'code_commit': git_output('rev-parse', 'HEAD'),
        'evaluator_commit': 'e97acc546ecbee8fa27fa8dbf025ef61493a876c',
        'python_version': sys.version, 'sqlite_version': sqlite3.sqlite_version,
        'dependencies': {name: version(name) for name in ['sqlparse', 'tqdm']},
        'question_sides': len(samples),
    }


def run_sample(output, endpoint, api_key, model, sample, sample_rows=0):
    name = sample['id'] + '.json'
    result_path = output / 'records' / name
    response_path = output / 'responses' / name
    if response_path.is_file():
        response = load(response_path)
    else:
        response = api_json(endpoint, api_key, make_payload(model, sample, sample_rows))
        save(response_path, response)
    if response.get('model') != model:
        raise RuntimeError(f"Expected {model}, received {response.get('model')!r}")
    if not response.get('choices'):
        raise RuntimeError('API returned no choices; inspect the recorded response')
    result = score(sample, response)
    save(result_path, result)
    return result['status']


def execute(output, samples, config, api_key, workers, limit):
    done = {path.stem for path in (output / 'records').glob('*.json')}
    groups = defaultdict(list)
    for sample in samples:
        groups[sample['group']].append(sample)
    remaining = [sample for row in zip_longest(*groups.values()) for sample in row
                 if sample is not None and sample['id'] not in done]
    if limit is not None:
        remaining = remaining[:limit]
    queue = iter(remaining)
    statuses = Counter()
    failures = []
    started = datetime.now(timezone.utc).isoformat()
    print(f'{len(done)}/{len(samples)} already scored, scheduling {len(remaining)}', flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {}

        def enqueue():
            sample = next(queue, None)
            if sample is not None:
                future = pool.submit(run_sample, output, config['endpoint'], api_key,
                                     config['model'], sample, config.get('sample_rows', 0))
                pending[future] = sample['id']

        for _ in range(workers):
            enqueue()
        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                sample_id = pending.pop(future)
                try:
                    statuses[future.result()] += 1
                except Exception as error:
                    detail = f'{type(error).__name__}: {error}'.replace(api_key, '[REDACTED]')
                    failures.append({'id': sample_id, 'error': detail})
                    print(f'{sample_id}: {detail}', file=sys.stderr, flush=True)
            count = sum(statuses.values())
            if (len(done) + count) // 100 > (len(done) + count - len(completed)) // 100:
                print(f'{len(done) + count}/{len(samples)} scored, current session {dict(statuses)}', flush=True)
            if not failures:
                for _ in completed:
                    enqueue()
    finished = datetime.now(timezone.utc)
    save(output / 'sessions' / f'{finished:%Y%m%dT%H%M%S%f}.json', {
        'started_at': started, 'finished_at': finished.isoformat(), 'workers': workers,
        'previous_records': len(done), 'status_counts': dict(statuses), 'api_failures': failures,
    })
    print(f'{len(done) + sum(statuses.values())}/{len(samples)} records saved', flush=True)
    return int(bool(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='sol-drspider-full')
    parser.add_argument('--model', default='gpt-6-sol')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--limit', type=int, help='Maximum new cases in this session')
    parser.add_argument('--pairs-per-group', type=int, help='Sample this many pairs per subset')
    parser.add_argument('--seed', type=int, default=20261121)
    parser.add_argument('--sample-rows', type=int, choices=(3,), default=0,
                        help='Show up to three actual rows after each table definition')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--audit', action='store_true', help='Run the reference queries locally')
    mode.add_argument('--execute', action='store_true', help='Generate and score the predictions')
    args = parser.parse_args()
    if args.audit and args.sample_rows:
        parser.error('--sample-rows applies only to --execute')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run) or not 1 <= args.workers <= 64:
        parser.error('Use a simple --run name and 1 to 64 workers')
    if args.limit is not None and args.limit < 1:
        parser.error('--limit must be positive')

    samples = list(iter_samples())
    if args.pairs_per_group is not None:
        minimum = min(item['pairs'] for item in load(INVENTORY)['subsets'])
        if not 1 <= args.pairs_per_group <= minimum:
            parser.error(f'--pairs-per-group must be between 1 and {minimum}')
        samples = select_pairs(samples, args.pairs_per_group, args.seed)
    output = ROOT / 'runs' / args.run
    output.mkdir(parents=True, exist_ok=True)
    if args.audit:
        result = audit(samples)
        save(output / 'reference_audit.json', result)
        print(f"Audited {len(samples)} cases. Reference execution failures: "
              f"{len(result['reference_execution_failures'])}. Output: {output}")
        return 0

    settings = read_settings()
    api_key = settings.get('THINGO_API_KEY', '').strip()
    if not api_key:
        parser.error('Set THINGO_API_KEY before running generation')
    base = settings.get('THINGO_BASE_URL', 'https://intlapi.thingo.com.cn/v1').rstrip('/')
    endpoint = base + '/chat/completions'
    with closing(sqlite3.connect(output / 'runner.lock.sqlite', timeout=0)) as lock:
        lock.execute('BEGIN EXCLUSIVE')
        model = resolve_model(args.model, api_json(base + '/models', api_key))
        config = make_config(samples, model, endpoint)
        if args.sample_rows:
            config['sample_rows'] = args.sample_rows
            config['schema_sample_method'] = 'SQLite SELECT * LIMIT 3 without ORDER BY'
            config['prompt_context_sha256'] = {
                path: hashlib.sha256(schema_with_sample_rows(path, args.sample_rows)
                                     .encode('utf-8')).hexdigest()
                for path in config['database_sha256']
            }
        config['sampling'] = {'pairs_per_group': args.pairs_per_group,
                              'seed': args.seed if args.pairs_per_group is not None else None}
        config_path = output / 'config.json'
        if config_path.is_file() and load(config_path) != config:
            parser.error('Existing run configuration differs. Use a new --run name.')
        if not config_path.is_file():
            save(config_path, config)
            save(output / 'samples.json', samples)
        elif not (output / 'samples.json').is_file():
            save(output / 'samples.json', samples)
        return execute(output, samples, config, api_key, args.workers, args.limit)


if __name__ == '__main__':
    sys.exit(main())
