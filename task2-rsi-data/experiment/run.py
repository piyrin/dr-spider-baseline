"""Freeze the split, then execute resumable paired experiments with the course API."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import time

from experiment import GRAPHS, HERE, ROOT, Scenario, as_json, database_input, run_graph, samples_by_id, score
from run_api_sample import api_json, git_output, load, read_settings, resolve_model, save
from run_full_evaluation import digest

SEED = '20261122'
DEVELOPMENT = [
    'NLQ_keyword_synonym-00281-pre', 'DB_DBcontent_equivalence-00037-post',
    'DB_schema_synonym-02550-post', 'DB_schema_synonym-00410-post',
    'DB_DBcontent_equivalence-00186-post', 'NLQ_multitype-00051-post',
    'SQL_sort_order-00026-post', 'NLQ_keyword_carrier-00042-post',
]
ARMS = {'pilot': ['baseline', 'value', 'without_values', 'plan', 'review'],
        'ablation': ['baseline', 'value', 'without_values', 'same_evidence']}
RUNS = HERE / 'runs'
MANIFEST = HERE / 'manifest.json'
ROUTES = HERE / 'routes.json'


def sort_key(identifier):
    return hashlib.sha256(f'{SEED}/{identifier}'.encode()).digest()


def prepare():
    all_rows = samples_by_id()
    with (ROOT / 'results/drspider-17x50/predictions.csv').open(encoding='utf-8-sig', newline='') as file:
        old_rows = list(csv.DictReader(file))
    known = {row['id'] for row in old_rows} | set(DEVELOPMENT)
    for directory in ('sol-drspider-full', 'sol-thinking-table-count-20261121'):
        known.update(path.stem for path in (ROOT / 'runs' / directory / 'records').glob('*.json')
                     if path.stem in all_rows)
    for file in (ROOT / 'results/baseline').glob('sol-*.json'):
        known.update(set(re.findall(r'"([A-Za-z][A-Za-z0-9_]+-\d{5}-(?:pre|post))"',
                                    file.read_text(encoding='utf-8-sig'))) & all_rows.keys())
    known_orig = {all_rows[s]['original_id'] for s in known}
    possible = defaultdict(list)
    for row in all_rows.values():
        if row['side'] == 'pre' and row['original_id'] not in known_orig:
            possible[row['group']].append(row)
    main, used = [], set()
    for group in sorted(possible, key=lambda g: (len({r['original_id'] for r in possible[g]}), g)):
        selected = 0
        for row in sorted(possible[group], key=lambda r: sort_key(r['id'])):
            if row['original_id'] in used:
                continue
            used.add(row['original_id'])
            main.extend((row['id'], row['id'].removesuffix('-pre') + '-post'))
            selected += 1
            if selected == 8:
                break
    if len(main) != 260:
        raise RuntimeError(f'Planned 260 main sides but selected {len(main)}')
    used = {all_rows[s]['original_id'] for s in DEVELOPMENT}
    # These concrete cases have been discussed during development and may recur across perturbations.
    used.update({133, 629, 828, 925})
    classified = load(ROOT / '.local/failed-query-review/class-summary-data.json')['records']
    diagnostic = []
    strata = [('bind', 'model', 5), ('projection', 'model', 8), ('value', 'model', 12),
              ('join', 'ambiguous', 5), ('correct', '', 10)]
    for cause, verdict, quota in strata:
        if cause == 'correct':
            eligible = [r['id'] for r in old_rows if r['status'] == 'match']
        else:
            eligible = [r['id'] for r in classified if r['cause'] == cause and r['verdict'] == verdict]
        selected = 0
        for case_id in sorted(eligible, key=sort_key):
            original = all_rows[case_id]['original_id']
            if original in used:
                continue
            used.add(original)
            diagnostic.append({'id': case_id, 'stratum': cause})
            selected += 1
            if selected == quota:
                break
        if selected != quota:
            raise RuntimeError(f'Planned {quota} diagnostic sides for {cause}, selected {selected}')
    save(MANIFEST, {'seed': SEED, 'known_originals': len(known_orig), 'main': main,
                    'pilot': DEVELOPMENT, 'ablation': diagnostic,
                    'source': load(ROOT / 'manifests/data_source.json')})
    with (HERE / 'route-review.tsv').open('w', encoding='utf-8', newline='') as file:
        writer = csv.writer(file, delimiter='\t')
        writer.writerow(['number', 'id', 'question'])
        for i, key in enumerate(main, start=1):
            writer.writerow([i, key, all_rows[key]['question']])
    print(f'Main: {len(main)//2} pairs. Diagnostic: {len(diagnostic)} sides. Development: {len(DEVELOPMENT)} sides.')


def model_client():
    s = read_settings()
    base = s['THINGO_BASE_URL'].rstrip('/')
    key = s['THINGO_API_KEY']
    model = resolve_model('gpt-6-sol', api_json(base + '/models', key))
    return model, base + '/chat/completions', key


def complete_at(endpoint, token, payload):
    for attempt in range(4):
        try:
            response = api_json(endpoint, token, payload)
            if response.get('model') != payload['model'] or not response.get('choices'):
                raise ValueError('The provider returned an unexpected model ID or omitted choices.')
            return response
        except (OSError, RuntimeError) as error:
            if type(error) is RuntimeError and not re.match(r'^HTTP (408|429|5\d\d):', str(error)):
                raise
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))


def run_batch(stage, workers, limit):
    manifest = load(MANIFEST)
    directory = RUNS / stage
    if stage == 'main':
        routes = load(ROUTES)
        if set(routes) != set(manifest['main']) or set(routes.values()) - {'value', 'plan', 'review'}:
            raise ValueError('Main-stage route picks must cover every frozen sample.')
        entries = [(key, ['baseline', routes[key]]) for key in manifest['main']]
    elif stage == 'ablation':
        entries = []
        for row in manifest[stage]:
            names = list(ARMS[stage])
            if row['stratum'] in ('bind', 'projection'):
                names.append('plan')
            if row['stratum'] in ('join', 'correct'):
                names.append('review')
            entries.append((row['id'], names))
    else:
        entries = [(key, ARMS[stage]) for key in manifest[stage]]
    model, endpoint, token = model_client()
    cases = {key: Scenario.from_id(key) for key, names in entries}
    config = {
        'model': model, 'model_digest': None, 'generation_parameters': {'stream': False, 'others': 'provider defaults'},
        'code_commit': git_output('rev-parse', 'HEAD'), 'source_hashes': {
            path.name: digest(path) for path in (HERE / 'experiment.py', HERE / 'run.py', MANIFEST)},
        'sqlite_version': __import__('sqlite3').sqlite_version, 'data_source': manifest['source'],
        'evaluator_commit': 'e97acc546ecbee8fa27fa8dbf025ef61493a876c',
        'database_sha256': {db: database_input(db)['sha256'] for db in sorted({c.database for c in cases.values()})},
        'cases': [[key, names] for key, names in entries], 'graphs': GRAPHS,
    }
    config_path = directory / 'config.json'
    if config_path.exists() and load(config_path) != config:
        raise ValueError(f'Run configuration differs from {config_path}')
    if not config_path.exists():
        save(config_path, config)

    def path_for(key, name):
        return directory / 'records' / f'{key}--{name}.json'

    def run_case(entry):
        key, names = entry
        case = cases[key]
        counts = Counter()
        for name in names:
            output = path_for(key, name)
            if output.exists():
                continue
            hits = []

            def complete(node_id, payload):
                request_hash = hashlib.sha256(as_json(payload).encode('utf-8')).hexdigest()
                path = directory / 'calls' / key / f'{request_hash}.json'
                if path.exists():
                    hits.append(node_id)
                    return load(path)['response']
                started = time.monotonic()
                response = complete_at(endpoint, token, payload)
                save(path, {'request': payload, 'response': response, 'elapsed_s': time.monotonic() - started})
                return response

            try:
                start = time.monotonic()
                result = run_graph(GRAPHS[name], case, model, complete)
                evaluation = score(case, result['final'])
                save(output, {'id': key, 'arm': name, 'database': case.database,
                              'time_utc': datetime.now(timezone.utc).isoformat(),
                              'elapsed_s': time.monotonic() - start, 'cache_hit_nodes': hits,
                              'result': result, 'score': evaluation})
                counts[evaluation['status']] += 1
            except Exception as error:
                save(directory / 'errors' / output.name,
                     {'id': key, 'arm': name, 'error': f'{type(error).__name__}: {str(error)[:1000]}'})
                counts['transport_or_runner_error'] += 1
                break
        return counts

    remaining = [(key, names) for key, names in entries if any(not path_for(key, name).exists() for name in names)]
    if limit is not None:
        remaining = remaining[:limit]
    totals = Counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(run_case, entry) for entry in remaining]
        for i, future in enumerate(as_completed(futures), start=1):
            totals.update(future.result())
            if i % 10 == 0 or i == len(futures):
                print(f'{stage}: {i}/{len(futures)} sides. New records: {dict(totals)}', flush=True)
    completed = sum(path_for(key, name).exists() for key, names in entries for name in names)
    expected = sum(len(names) for key, names in entries)
    print(f'{stage}: {completed}/{expected} arms scored', flush=True)
    if totals['transport_or_runner_error']:
        raise SystemExit(1)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=['prepare', 'pilot', 'main', 'ablation'])
    p.add_argument('--workers', type=int, default=12)
    p.add_argument('--limit', type=int)
    args = p.parse_args()
    if args.stage == 'prepare':
        prepare()
    else:
        run_batch(args.stage, args.workers, args.limit)


if __name__ == '__main__':
    main()
