"""Run one real Dr.Spider question through an OpenAI-compatible API."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from baseline import SYSTEM, load, read_database, save


def read_settings():
    """Read simple KEY=value settings, with process environment taking priority."""
    settings = {}
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, separator, value = line.partition('=')
            if not separator:
                raise ValueError('Expected KEY=value in .env')
            settings[key.strip()] = value.strip().strip('\"\'')
    for key in ['THINGO_API_KEY', 'THINGO_BASE_URL', 'THINGO_MODEL']:
        if key in os.environ:
            settings[key] = os.environ[key]
    return settings


def api_json(url, api_key, payload=None):
    headers = {'Authorization': 'Bearer ' + api_key,
               'Content-Type': 'application/json'}
    body = None if payload is None else json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=180) as reply:
            return json.load(reply)
    except urllib.error.HTTPError as error:
        detail = error.read().decode('utf-8', errors='replace')
        # Some gateways echo request details in errors. Redact credentials.
        detail = detail.replace(api_key, '[REDACTED]')
        raise RuntimeError(f'HTTP {error.code}: {detail[:2000]}') from None


def resolve_model(requested, models):
    identifiers = [item['id'] for item in models['data']]
    if requested in identifiers:
        return requested
    # Accept punctuation and the ChatGPT display-name prefix, without
    # selecting a different model family, version, or capability tier.
    def normalized(name):
        return re.sub(r'[^a-z0-9]', '', name.lower()).replace('chatgpt', 'gpt')

    matches = [name for name in identifiers
               if normalized(name) == normalized(requested)]
    if len(matches) == 1:
        return matches[0]
    raise ValueError('Cannot uniquely match model ' + requested
                     + '. Run --list-models and set THINGO_MODEL to an exact ID.')


def make_sample(group, index, side):
    rows = load(ROOT / 'data' / group / f'questions_{side}_perturbation.json')
    if index < 0 or index >= len(rows):
        raise ValueError('Sample index is outside this subset')
    item = rows[index]
    database_root = ROOT / 'data/Spider-dev/databases'
    if group.startswith('DB_') and side == 'post':
        database_root = ROOT / 'data' / group / 'database_post_perturbation'
    database = database_root / item['db_id'] / (item['db_id'] + '.sqlite')
    if not database.is_file():
        raise FileNotFoundError(database)
    schema_rows = read_database(database,
        "SELECT sql FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")
    return {
        'id': f'{group}-{index:05d}-{side}',
        'group': group, 'index': index, 'side': side,
        'original_id': item['q_id_spider_dev'], 'db_id': item['db_id'],
        'database': str(database.relative_to(ROOT)),
        'database_sha256': hashlib.sha256(database.read_bytes()).hexdigest(),
        'question': item['question'], 'gold_sql': item['query'],
        'schema': '\n'.join(row[0] for row in schema_rows if row[0]),
    }

def git_output(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=ROOT,
                                   text=True, encoding='utf-8').strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='api-one')
    parser.add_argument('--model', help='Exact model ID from --list-models')
    parser.add_argument('--list-models', action='store_true')
    parser.add_argument('--prepare', action='store_true',
                        help='Check the one question and gold SQL locally')
    parser.add_argument('--group', default='NLQ_keyword_synonym', choices=[
        'DB_schema_synonym', 'DB_schema_abbreviation',
        'NLQ_keyword_synonym', 'NLQ_column_synonym', 'SQL_sort_order',
    ])
    parser.add_argument('--index', type=int, default=0)
    parser.add_argument('--side', choices=['pre', 'post'], default='pre')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run):
        raise ValueError('Run name must use letters, digits, _ or -')
    settings = read_settings()
    base_url = settings.get('THINGO_BASE_URL',
                            'https://intlapi.thingo.com.cn/v1').rstrip('/')
    if not args.prepare:
        api_key = settings.get('THINGO_API_KEY', '').strip()
        if not api_key:
            raise ValueError('Fill THINGO_API_KEY in .env first.')
        models = api_json(base_url + '/models', api_key)
        if args.list_models:
            for model in models['data']:
                print(model['id'])
            return
        model = resolve_model(args.model or settings.get('THINGO_MODEL',
                                                       'gpt6sol'), models)

    sample = make_sample(args.group, args.index, args.side)
    database = ROOT / sample['database']
    gold_rows = read_database(database, sample['gold_sql'])
    print('Sample:', sample['id'])
    print('Question:', sample['question'])
    if args.prepare:
        print('Gold SQL:', sample['gold_sql'])
        print('Gold rows:', gold_rows)
        print('Prepared 1 sample; gold SQL executed successfully.')
        return

    sys.path.insert(0, str(ROOT / '.cache/evaluator'))
    from exec_eval import result_eq

    folder = ROOT / 'runs' / args.run
    # Each run is a distinct attempt, including failed attempts.
    folder.mkdir(parents=True, exist_ok=False)
    payload = {
        'model': model, 'stream': False,
        'messages': [
            {'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': 'Schema\n' + sample['schema']
             + '\nQuestion\n' + sample['question']},
        ],
    }
    config = {
        'endpoint': base_url + '/chat/completions', 'requested_model': model,
        'parameters': {'stream': False,
                       'other_generation_parameters': 'provider defaults'},
        'planned_predictions': 1, 'sample_selection': 'first pre sample in subset',
        'metric': 'single-database EX', 'system': SYSTEM,
        'evaluator_commit': 'e97acc546ecbee8fa27fa8dbf025ef61493a876c',
        'data_source': load(ROOT / 'manifests/data_source.json'),
        'code_commit': git_output('rev-parse', 'HEAD'),
        'git_status': git_output('status', '--porcelain'),
        'source_sha256': {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [Path(__file__), ROOT / 'src/baseline.py']
        },
        'started_at': datetime.now(timezone.utc).isoformat(),
        'python_version': sys.version,
    }
    save(folder / 'sample.json', sample)
    save(folder / 'config.json', config)
    save(folder / 'models.json', models)
    save(folder / 'request.json', payload)
    (folder / 'environment.txt').write_text(subprocess.check_output(
        [sys.executable, '-m', 'pip', 'freeze'], text=True, encoding='utf-8'),
        encoding='utf-8')
    record = {'id': sample['id'], 'pred_sql': None, 'correct': False,
              'error': None, 'stage': 'generation', 'gold_rows': gold_rows}
    started = time.monotonic()
    print('Model:', model)
    print('Sending one generation request...', flush=True)
    try:
        response = api_json(config['endpoint'], api_key, payload)
        save(folder / 'response.json', response)
        save(folder / 'model_identity.json', {
            'requested_model': model, 'returned_model': response.get('model'),
            'system_fingerprint': response.get('system_fingerprint'),
            'digest': None, 'digest_note': 'Remote API does not expose a verified digest',
        })
        choice = response['choices'][0]
        record['finish_reason'] = choice.get('finish_reason')
        if choice.get('finish_reason') != 'stop':
            raise ValueError('Generation did not finish normally; inspect response.json')
        prediction = choice['message']['content']
        if not isinstance(prediction, str) or not prediction.strip():
            raise ValueError('Expected nonempty text content; inspect response.json')
        prediction = prediction.strip()
        fenced = re.fullmatch(r'```(?:sql|sqlite)?\s*(.*?)```', prediction,
                              flags=re.I | re.S)
        if fenced:
            prediction = fenced.group(1).strip()
        record['pred_sql'] = prediction
        if not re.match(r'^(SELECT|WITH)\b', prediction, flags=re.I):
            raise ValueError('Expected one SELECT query')
        record['stage'] = 'execution'
        predicted_rows = read_database(database, prediction)
        record['prediction_rows'] = predicted_rows
        record['stage'] = 'comparison'
        record['correct'] = result_eq(gold_rows, predicted_rows,
                                     'order by' in sample['gold_sql'].lower())
        record['stage'] = 'done'
    except Exception as error:
        record['error'] = (f'{type(error).__name__}: {error}').replace(api_key, '[REDACTED]')
    record['elapsed_seconds'] = time.monotonic() - started
    save(folder / 'record.json', record)
    save(folder / 'summary.json', {
        'planned': 1, 'attempted': 1, 'scored': int(record['stage'] == 'done'),
        'correct': int(record['correct']), 'failures': int(record['error'] is not None),
        'metric': 'single-database EX',
        'ex': float(record['correct']) if record['stage'] in ['done', 'generation', 'execution'] else None,
    })
    print('Predicted SQL:', record['pred_sql'])
    print('Gold SQL:', sample['gold_sql'])
    print('Predicted rows:', record.get('prediction_rows'))
    print('Gold rows:', gold_rows)
    print('Correct:', record['correct'])
    print('Error:', record['error'])
    print('Saved:', folder)
    if record['error']:
        return 1
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        print(f'{type(error).__name__}: {error}', file=sys.stderr)
        sys.exit(1)
