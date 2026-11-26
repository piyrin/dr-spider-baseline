"""Freeze and run the original, boolean-encoding and mixed comparison."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path
import re
import sys

from boolean_canvas import EXAMPLES, GRAPH, boolean_step, flag_matches, validate_boolean
from experiment import ROOT, GRAPHS, Scenario, columns_for, samples_by_id, score, step_node, validate_graph
from projection_compare import CONTROL_GROUPS, EFFORTS, MODEL
from projection_exposure import exposure
from run import complete_at
from run_full_evaluation import digest, load, make_config, read_settings, save

OUT = ROOT / 'runs/task2-filter-boolean-comparison-v2'
SEED = 'filter-boolean-v1-20261126'
METHODS = ('baseline', 'canvas_v2')
CONDITIONS = [(method, effort) for method in METHODS for effort in EFFORTS]
FLAG = re.compile(r"""\b((?:is_|has_)\w+|\w+_ship)\b"?\s*=\s*["']([TF])["']""", re.I)


def target_evidence(post):
    if post['group'] != 'DB_DBcontent_equivalence':
        return None
    predicates = FLAG.findall(post['gold_sql'])
    if not predicates:
        return None
    database = columns_for(post['database'])
    terms = re.findall(r'[A-Za-z0-9]+', post['question'])
    terms += [f'{a} {b}' for a, b in zip(terms, terms[1:])]
    explicit = sorted({column for column, _ in predicates if any(
        flag_matches(column, declared, term)
        for fields in database.values() for name, declared in fields.items()
        if column.casefold() == name.casefold() for term in terms
    )})
    return {'flag_predicates': predicates, 'named_status_in_question': explicit}


def freeze(samples):
    path = OUT / 'plan.json'
    if path.exists():
        return load(path)
    originals, surfaces, seen = exposure(samples)
    seen = set(seen)
    ordering = sorted((s for s in samples.values() if s['side'] == 'post' and s['id'][:-5] not in seen),
                      key=lambda s: sha256(f'{SEED}/{s["id"]}'.encode()).digest())
    target = [(row, info) for row in ordering if (info := target_evidence(row)) is not None]
    target.sort(key=lambda item: (not item[1]['named_status_in_question'], len(item[1]['flag_predicates'])))
    used, selected, per_db = {samples[EXAMPLES[0]]['original_id']}, [], Counter()

    def add(row, label, evidence=None):
        selected.append({'pair': row['id'][:-5], 'original_id': row['original_id'],
                         'pre_db_id': samples[row['id'][:-4]+'pre']['db_id'], 'db_id': row['db_id'],
                         'group': row['group'], 'label': label, 'selection_evidence': evidence})
        used.add(row['original_id'])

    for row, info in target:
        source_db = samples[row['id'][:-4]+'pre']['db_id']
        if row['original_id'] in used or per_db[source_db] >= 3:
            continue
        add(row, 'target', info)
        per_db[source_db] += 1
        if len(selected) == 8:
            break
    if len(selected) < 8:
        raise ValueError(f'Only {len(selected)} unseen target pairs under the database cap')
    for group in CONTROL_GROUPS:
        add(next(row for row in ordering if row['group'] == group and row['original_id'] not in used
                 and target_evidence(row) is None), 'control')
    paths = [Path(__file__).with_name(file) for file in (
        'boolean_compare.py', 'boolean_canvas.py', 'experiment.py', 'run.py', 'projection_exposure.py')]
    plan = {'seed': SEED, 'observed_originals': len(originals), 'excluded_pairs': len(seen),
            'exposure_surfaces': surfaces, 'selected': selected, 'anchor': EXAMPLES,
            'conditions': CONDITIONS, 'graph': GRAPH,
            'code_sha256': {str(p.relative_to(ROOT)): digest(p) for p in paths}}
    save(path, plan)
    return plan


def evaluate(sample, method, effort, endpoint, key):
    case = Scenario.from_id(sample['id'])
    path = OUT/'records'/method/effort/(case.id + '.json')
    if path.exists():
        return load(path)
    nodes, runner = ((validate_graph(GRAPHS['baseline']), step_node) if method == 'baseline'
                     else (validate_boolean(GRAPH), boolean_step))
    steps = {}

    def complete(node_id, payload):
        directory = OUT/'requests'/method/effort/case.id/node_id
        request, response = directory/'request.json', directory/'response.json'
        payload = {**payload, 'reasoning_effort': effort}
        if request.exists() and load(request) != payload:
            raise ValueError(f'Request differs from frozen condition: {case.id}, {node_id}')
        save(request, payload)
        if response.exists():
            return load(response)
        answer = complete_at(endpoint, key, payload)
        save(response, answer)
        return answer

    for node in nodes:
        output, call = runner(node, case, MODEL, [steps[parent] for parent in node['from']], complete)
        steps[node['id']] = {**node, 'output': output, 'call': call}
    usages = [s['call'].get('usage') or {} for s in steps.values() if s['call']]
    usage = {}
    for metric in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        counts = [u.get(metric) for u in usages]
        if all(type(n) is int for n in counts):
            usage[metric] = sum(counts)
    record = {'id': case.id, 'side': sample['side'], 'original_id': sample['original_id'],
              'method': method, 'effort': effort, 'steps': list(steps.values()), 'usage': usage,
              'model_calls': len(usages), 'score': score(case, steps['execute']['output'])}
    save(path, record)
    return record


def main(mode):
    samples = samples_by_id()
    plan = freeze(samples)
    print(f"Frozen {len(plan['selected'])} pairs across {plan['observed_originals']} exposed originals.", flush=True)
    if mode == 'prepare':
        for row in plan['selected']:
            print(row['label'], row['pair'], row['pre_db_id'], row['db_id'], row['selection_evidence'])
        return 0
    if mode not in ('anchor', 'run'):
        raise ValueError('Use prepare, anchor or run')
    for name, expected in plan['code_sha256'].items():
        if digest(ROOT / name) != expected:
            raise ValueError(f'Frozen code differs: {name}')
    ids = [*EXAMPLES, *(row['pair'] + '-' + side for row in plan['selected'] for side in ('pre', 'post'))]
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    key = settings['THINGO_API_KEY']
    config = make_config([samples[k] for k in ids], MODEL, endpoint)
    config.update(reasoning_efforts=list(EFFORTS), selection_sha256=digest(OUT/'plan.json'), graph=GRAPH)
    config_path = OUT/'config.json'
    if config_path.exists() and load(config_path) != config:
        raise ValueError('Experiment configuration differs')
    save(config_path, config)
    if mode == 'anchor':
        ids = list(EXAMPLES)
    tasks = [(samples[sample_id], method, effort) for i, sample_id in enumerate(ids)
             for method, effort in CONDITIONS[i % 4:] + CONDITIONS[:i % 4]]
    failures, done = [], 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = {pool.submit(evaluate, row, method, effort, endpoint, key): (row['id'], method, effort)
                   for row, method, effort in tasks}
        for future in as_completed(pending):
            try:
                future.result()
            except Exception as error:
                context = pending[future]
                failures.append({'condition': context, 'error': str(error).replace(key, '[REDACTED]')})
                print('Failed', failures[-1], flush=True)
            else:
                done += 1
                if done % 8 == 0:
                    print(f'{done}/{len(tasks)} scored', flush=True)
    save(OUT/('anchor-failures.json' if mode == 'anchor' else 'failures.json'), failures)
    print(f'{done}/{len(tasks)} scored, {len(failures)} failures', flush=True)
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
