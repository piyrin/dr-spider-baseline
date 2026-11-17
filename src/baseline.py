import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import random
import re
import sqlite3
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
GROUPS = [
    'DB_schema_synonym', 'DB_schema_abbreviation',
    'NLQ_keyword_synonym', 'NLQ_column_synonym', 'SQL_sort_order',
]
SYSTEM = ('Generate one SQLite SELECT query for the question and schema. '
          'Include required values. Return only the SQL query.')


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    default=repr), encoding='utf-8')
    temporary.replace(path)


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def read_database(path, sql):
    started = time.monotonic()
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.set_progress_handler(lambda: int(time.monotonic() - started > 10), 1000)
        return db.execute(sql).fetchall()


def make_samples():
    samples = []
    for group in GROUPS:
        before = load(DATA / group / 'questions_pre_perturbation.json')
        after = load(DATA / group / 'questions_post_perturbation.json')
        indexes = sorted(random.Random(42).sample(range(len(before)), 5))
        for index in indexes:
            assert before[index]['q_id_spider_dev'] == after[index]['q_id_spider_dev']
            for side, rows in [('pre', before), ('post', after)]:
                item = rows[index]
                database_root = DATA / 'Spider-dev/databases'
                if group.startswith('DB_') and side == 'post':
                    database_root = DATA / group / 'database_post_perturbation'
                path = database_root / item['db_id'] / (item['db_id'] + '.sqlite')
                if not path.is_file():
                    raise FileNotFoundError(path)
                schema_rows = read_database(path,
                    "SELECT sql FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name")
                schema = '\n'.join(row[0] for row in schema_rows if row[0])
                samples.append({
                    'id': f'{group}-{index:05d}-{side}',
                    'group': group, 'index': index, 'side': side,
                    'original_id': item['q_id_spider_dev'],
                    'db_id': item['db_id'], 'database': str(path.relative_to(ROOT)),
                    'database_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                    'question': item['question'], 'gold_sql': item['query'],
                    'schema': schema,
                })
    return samples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--model', default='qwen3.5:9b')
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run):
        raise ValueError('Run name must use letters, digits, _ or -')
    if args.limit is not None and args.limit < 1:
        raise ValueError('Limit must be positive')
    folder = ROOT / 'runs' / args.run
    config = {
        'model': args.model, 'endpoint': 'http://127.0.0.1:11434/api/chat',
        'temperature': 0, 'num_ctx': 8192, 'num_predict': 512,
        'think': False, 'system': SYSTEM, 'sample_seed': 42,
        'pairs_per_group': 5, 'metric': 'single-database EX',
        'evaluator_commit': 'e97acc546ecbee8fa27fa8dbf025ef61493a876c',
    }
    samples = make_samples()
    for name, value in [('config.json', config), ('samples.json', samples)]:
        path = folder / name
        if path.exists() and load(path) != value:
            raise ValueError(f'Changed configuration or data; choose a new run name: {path}')
        save(path, value)
    # Validate gold SQL independently before any model request.
    for sample in samples:
        read_database(ROOT / sample['database'], sample['gold_sql'])
    print('Prepared', len(samples), 'samples', flush=True)
    if args.prepare:
        return

    sys.path.insert(0, str(ROOT / '.cache/evaluator'))
    from exec_eval import result_eq

    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=10) as reply:
        installed = json.load(reply)['models']
    identity = next(model for model in installed if model['name'] == args.model)
    identity_path = folder / 'model_identity.json'
    if identity_path.exists() and load(identity_path)['digest'] != identity['digest']:
        raise ValueError('Model digest changed; choose a new run name')
    save(identity_path, identity)

    selected = samples if args.limit is None else samples[:args.limit]
    for sample in selected:
        record_path = folder / 'records' / (sample['id'] + '.json')
        if record_path.exists():
            continue
        messages = [
            {'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': 'Schema\n' + sample['schema']
             + '\nQuestion\n' + sample['question']},
        ]
        payload = {
            'model': args.model, 'messages': messages,
            'stream': False, 'think': config['think'],
            'options': {key: config[key] for key in
                        ['temperature', 'num_ctx', 'num_predict']},
        }
        save(folder / 'requests' / (sample['id'] + '.json'), payload)
        gold_rows = read_database(ROOT / sample['database'], sample['gold_sql'])
        record = {'id': sample['id'], 'group': sample['group'],
                  'side': sample['side'], 'pred_sql': None,
                  'correct': False, 'error': None}
        stage = 'generation'
        try:
            response_path = folder / 'responses' / (sample['id'] + '.json')
            if response_path.exists():
                response = load(response_path)
            else:
                request = urllib.request.Request(config['endpoint'],
                    data=json.dumps(payload).encode('utf-8'),
                    headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(request, timeout=180) as reply:
                    response = json.load(reply)
                save(response_path, response)
            if response.get('done_reason') != 'stop':
                raise ValueError('Generation did not finish normally')
            prediction = response['message']['content'].strip()
            fenced = re.fullmatch(r'```(?:sql|sqlite)?\s*(.*?)```', prediction,
                                  flags=re.I | re.S)
            if fenced:
                prediction = fenced.group(1).strip()
            record['pred_sql'] = prediction
            if not re.match(r'^(SELECT|WITH)\b', prediction, flags=re.I):
                raise ValueError('Expected one SELECT query')
            stage = 'execution'
            predicted_rows = read_database(ROOT / sample['database'], prediction)
            order_matters = 'order by' in sample['gold_sql'].lower()
            stage = 'comparison'
            record['correct'] = result_eq(gold_rows, predicted_rows, order_matters)
            record['gold_preview'] = repr(gold_rows[:5])
            record['prediction_preview'] = repr(predicted_rows[:5])
        except Exception as error:
            if stage == 'comparison':
                raise RuntimeError('Evaluator failed; inspect before scoring') from error
            record['error'] = f'{stage}: {type(error).__name__}: {error}'
        save(record_path, record)
        print(sample['id'], record['correct'], record['error'], flush=True)

    records = [load(path) for path in sorted((folder / 'records').glob('*.json'))]
    groups = []
    for group in GROUPS:
        row = {'group': group, 'pairs': 5}
        for side in ['pre', 'post']:
            subset = [r for r in records if r['group'] == group and r['side'] == side]
            correct = sum(r['correct'] for r in subset)
            row[side + '_completed'] = len(subset)
            row[side + '_correct'] = correct
            row[side + '_ex'] = correct / 5 if len(subset) == 5 else None
        row['delta_pp'] = None
        if row['pre_ex'] is not None and row['post_ex'] is not None:
            row['delta_pp'] = 100 * (row['post_ex'] - row['pre_ex'])
        groups.append(row)
    save(folder / 'summary.json', {'planned': 50, 'completed': len(records),
         'complete': len(records) == 50, 'groups': groups})
    print('Completed', len(records), '/ 50', flush=True)


if __name__ == '__main__':
    main()
