"""Freeze and run the projection test on previously exposed Spider originals."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
from pathlib import Path
import sys
import time

from experiment import (ROOT, GRAPHS, Scenario, columns_for, samples_by_id,
                        score, step_node, validate_graph)
from projection_exposure import OUT
from projection_generalization import GRAPH_V2, find_name, generalized_step, validate_v2
from run_full_evaluation import api_json, digest, load, make_config, read_settings, save


MODEL = 'gpt-6-sol'
SEED = 'projection-v2-20261125'
EFFORTS = ('none', 'high')
METHODS = ('baseline', 'canvas_v2')
CONDITIONS = [(method, effort) for method in METHODS for effort in EFFORTS]
CONTROL_GROUPS = (
    'DB_DBcontent_equivalence', 'DB_schema_abbreviation', 'DB_schema_synonym',
    'NLQ_column_attribute', 'NLQ_column_value', 'NLQ_keyword_synonym',
    'SQL_comparison', 'SQL_sort_order',
)


def sample_order(stem):
    return hashlib.sha256(f'{SEED}/{stem}'.encode()).hexdigest()


def domains(row):
    return find_name(row['question'], columns_for(row['database']))


def freeze():
    file = OUT / 'plan.json'
    if file.exists():
        return load(file)
    index = load(OUT / 'exposed-original-ids.json')
    known_pairs = set(index['observed_pair_ids'])
    samples = samples_by_id()
    posts = [s for s in samples.values() if s['side'] == 'post' and s['id'][:-5] not in known_pairs]
    ordering = sorted(posts, key=lambda row: sample_order(row['id']))
    selected = []
    originals = {871}
    per_database = {}

    def add(row, label):
        case = row['id'][:-5]
        selected.append({'pair': case, 'original_id': row['original_id'],
                         'group': row['group'], 'db_id': row['db_id'], 'label': label})
        originals.add(row['original_id'])

    for post in ordering:
        if len(selected) == 8:
            break
        if post['group'] != 'NLQ_column_carrier' or post['original_id'] in originals:
            continue
        if per_database.get(post['db_id'], 0) == 2:
            continue
        pre = samples[post['id'][:-4]+'pre']
        if domains(pre)[0] != 'direct':
            continue
        post_route, name = domains(post)
        if post_route != 'normalized' or name != domains(pre)[1]:
            continue
        per_database[post['db_id']] = per_database.get(post['db_id'], 0) + 1
        add(post, 'target')
    if len(selected) != 8:
        raise ValueError(f'Only {len(selected)} target pairs met the frozen inclusion rule')
    for group in CONTROL_GROUPS:
        row = next(s for s in ordering if s['group'] == group and s['original_id'] not in originals)
        add(row, 'control')
    plan = {'seed': SEED, 'known_original_count': len(index['originals']),
            'known_pair_count': len(known_pairs), 'selected': selected, 'conditions': CONDITIONS,
            'project_scope': 'fresh variant pairs of previously exposed original IDs',
            'target_rule': 'NLQ_column_carrier, v2 explicit to normalized same unique name field',
            'control_rule': 'one fixed-hash sample per listed distinct non-carrier perturbation group',
            'code_sha256': {str(file.relative_to(ROOT)): digest(file) for file in (
                Path(__file__), Path(__file__).with_name('projection_generalization.py'),
                Path(__file__).with_name('projection_canvas.py'), Path(__file__).with_name('experiment.py'))}}
    save(file, plan)
    return plan


def evaluate(sample, method, effort, config):
    record_file = OUT / 'records' / method / effort / (sample['id'] + '.json')
    if record_file.exists():
        return load(record_file)
    case = Scenario.from_id(sample['id'])
    steps = {}
    started = time.monotonic()
    calls = 0

    def complete(_, payload):
        nonlocal calls
        calls += 1
        base = OUT / 'requests' / method / effort / sample['id']
        request = {**payload, 'reasoning_effort': effort}
        save(base / 'request.json', request)
        response_path = base / 'response.json'
        if response_path.exists():
            response = load(response_path)
        else:
            response = api_json(config['endpoint'], config['key'], request)
            save(response_path, response)
        if response.get('model') != MODEL or not response.get('choices'):
            raise RuntimeError(f'{sample["id"]}: unexpected model response')
        return response

    if method == 'baseline':
        ordered = validate_graph(GRAPHS['baseline'])
        runner = step_node
    else:
        ordered = validate_v2(GRAPH_V2)
        runner = generalized_step
    call = None
    for node in ordered:
        output, event_call = runner(node, case, MODEL, [steps[parent] for parent in node['from']], complete)
        steps[node['id']] = {**node, 'output': output}
        if event_call:
            call = event_call
    assert calls == 1
    final = steps[ordered[-1]['id']]['output']
    record = {'id': sample['id'], 'side': sample['side'], 'original_id': sample['original_id'],
              'method': method, 'effort': effort, 'steps': list(steps.values()),
              'score': score(case, final), 'usage': call['usage'],
              'system_fingerprint': call['fingerprint'],
              'elapsed_seconds': round(time.monotonic() - started, 3)}
    save(record_file, record)
    return record


def main():
    plan = freeze()
    print('Frozen', len(plan['selected']), 'pairs', plan['known_original_count'], 'exposed originals', flush=True)
    for row in plan['selected']:
        print(row['label'], row['pair'], row['db_id'], flush=True)
    if len(sys.argv) == 1 or sys.argv[1] == 'prepare':
        return 0
    for path, fingerprint in plan['code_sha256'].items():
        if digest(ROOT / path) != fingerprint:
            raise ValueError(f'Frozen method differs from {path}')
    samples = samples_by_id()
    selected = [samples[pair['pair']+'-'+side] for pair in plan['selected'] for side in ('pre', 'post')]
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    config = make_config(selected, MODEL, endpoint)
    config.update(reasoning_efforts=EFFORTS, selection_sha256=digest(OUT/'plan.json'),
                  graph=GRAPH_V2, started_at=datetime.now().astimezone().isoformat())
    if not (OUT / 'config.json').exists():
        save(OUT / 'config.json', config)
    live = {'endpoint': endpoint, 'key': settings['THINGO_API_KEY']}
    errors = []
    tasks = [(sample, method, effort) for i, sample in enumerate(selected)
             for method, effort in CONDITIONS[i % 4:] + CONDITIONS[:i % 4]]
    if sys.argv[1] == 'pilot':
        tasks = [task for task in tasks if task[0]['id'] == selected[1]['id'] and task[1] == 'baseline']
    elif sys.argv[1] != 'run':
        raise ValueError('Choose prepare, pilot or run.')
    finished = 0
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(evaluate, sample, method, effort, live): (sample['id'], method, effort)
                   for sample, method, effort in tasks}
        for future in as_completed(futures):
            key = futures[future]
            try:
                record = future.result()
                finished += 1
                if finished % 8 == 0 or len(tasks) < 8:
                    print(f'{finished}/{len(tasks)}', *key, record['score']['status'], flush=True)
            except Exception as error:
                detail = {'condition': key, 'error': str(error).replace(live['key'], '[REDACTED]')}
                errors.append(detail)
                print(detail, flush=True)
    save(OUT / ('failures-' + datetime.now().strftime('%H%M%S') + '.json'), errors)
    print(f'{finished}/{len(tasks)} scored. {len(errors)} failed.', flush=True)
    return int(bool(errors))


if __name__ == '__main__':
    sys.exit(main())
