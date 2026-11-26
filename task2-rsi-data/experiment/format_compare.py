"""Frozen development regression and Thinking comparison for the format canvas."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path
import re
import sys

from experiment import ROOT, GRAPHS, Scenario, columns_for, samples_by_id, score, step_node, validate_graph
from format_canvas import EXAMPLES, GRAPH, find_values, format_key, format_step, validate_format
from projection_compare import CONDITIONS, CONTROL_GROUPS, EFFORTS, METHODS, MODEL
from projection_exposure import exposure
from run import complete_at
from run_full_evaluation import digest, load, make_config, read_settings, save


OUT = ROOT / 'runs/task2-filter-format-comparison-v1'
SEED = 'filter-format-v1-20261125'
LITERAL = re.compile(r"""\b([A-Za-z_]\w*)\s*=\s*(?:"([^"]+)"|'([^']+)')""")


def evidence(pre, post):
    if not post['group'].startswith('NLQ_') or pre['gold_sql'] != post['gold_sql']:
        return None
    clauses = LITERAL.findall(post['gold_sql'])
    if len(clauses) != 1:
        return None
    column, quoted, single = clauses[0]
    original = quoted or single
    if len(original) < 3 or original not in pre['question'] or original in post['question']:
        return None
    pattern = r'(?<!\w)' + r'\s+'.join(map(re.escape, original.split())) + r'(?!\w)'
    found = {m[0] for m in re.finditer(pattern, post['question'], re.I)
             if format_key(m[0]) == format_key(original)}
    if len(found) != 1:
        return None
    altered = next(iter(found))
    bindings = [{'table': t, 'column': c, 'term': altered}
                for t, fields in columns_for(post['database']).items()
                for c in fields if c.casefold() == column.casefold()]
    verified = [b for b in bindings if not find_values(post['database'], b)
                and find_values(post['database'], b, normalized=True) == [original]]
    if len(verified) != 1:
        return None
    return {**verified[0], 'stored_value': original}


def freeze():
    path = OUT / 'plan.json'
    if path.exists():
        return load(path)
    samples = samples_by_id()
    originals, surfaces, known = exposure(samples)
    previous = load(ROOT/'runs/task2-projection-comparison-v1/plan.json')['selected']
    seen = set(known) | {row['pair'] for row in previous}
    anchor_original = samples[EXAMPLES[0]]['original_id']
    ordering = sorted((s for s in samples.values() if s['side'] == 'post' and s['id'][:-5] not in seen),
                      key=lambda s: sha256(f'{SEED}/{s["id"]}'.encode()).digest())
    selected, used_originals, per_db = [], {anchor_original}, Counter()
    used_values = {('tvshow', 'series_name', 'Sky Radio')}

    def add(post, label, details=None):
        selected.append({'pair': post['id'][:-5], 'original_id': post['original_id'], 'db_id': post['db_id'],
                         'group': post['group'], 'label': label, 'selection_evidence': details})
        used_originals.add(post['original_id'])

    for post in ordering:
        if post['original_id'] in used_originals or per_db[post['db_id']] >= 2:
            continue
        match = evidence(samples[post['id'][:-5]+'-pre'], post)
        if match is None:
            continue
        signature = (post['db_id'], match['column'].casefold(), match['stored_value'])
        if signature in used_values:
            continue
        add(post, 'target', match)
        used_values.add(signature)
        per_db[post['db_id']] += 1
        if len(selected) == 8:
            break
    if len(selected) != 8:
        raise ValueError(f'Only {len(selected)} target pairs satisfied the inclusion rule')
    for group in CONTROL_GROUPS:
        row = next(s for s in ordering if s['group'] == group and s['original_id'] not in used_originals
                   and evidence(samples[s['id'][:-5]+'-pre'], s) is None)
        add(row, 'control')
    files = (Path(__file__).resolve(), *(Path(__file__).resolve().with_name(p)
              for p in ('format_canvas.py', 'experiment.py', 'run.py', 'projection_exposure.py')))
    plan = {'seed': SEED, 'observed_originals': len(originals), 'excluded_pairs': len(seen),
            'exposure_surfaces': surfaces, 'selected': selected, 'anchor': list(EXAMPLES),
            'conditions': CONDITIONS, 'graph': GRAPH,
            'code_sha256': {str(p.relative_to(ROOT)): digest(p) for p in files}}
    save(path, plan)
    return plan


def evaluate(sample, method, effort, endpoint, token):
    folder = OUT / 'records' / method / effort
    record_path = folder / (sample['id'] + '.json')
    if record_path.exists():
        return load(record_path)
    case = Scenario.from_id(sample['id'])
    nodes, runner = (validate_graph(GRAPHS['baseline']), step_node) if method == 'baseline' else (
        validate_format(GRAPH), format_step)
    steps = {}

    def complete(node_id, payload):
        node = OUT / 'requests' / method / effort / sample['id'] / node_id
        request = {**payload, 'reasoning_effort': effort}
        request_path, response_path = node/'request.json', node/'response.json'
        if request_path.exists() and load(request_path) != request:
            raise ValueError('Frozen request differs from stored request')
        save(request_path, request)
        if response_path.exists():
            return load(response_path)
        response = complete_at(endpoint, token, request)
        save(response_path, response)
        return response

    for node in nodes:
        output, call = runner(node, case, MODEL, [steps[p] for p in node['from']], complete)
        steps[node['id']] = {**node, 'output': output, 'call': call}
    calls = [step['call'] for step in steps.values() if step['call']]
    usage = {}
    for name in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        amounts = [(call.get('usage') or {}).get(name) for call in calls]
        if all(type(n) is int for n in amounts):
            usage[name] = sum(amounts)
    record = {'id': sample['id'], 'side': sample['side'], 'original_id': sample['original_id'],
              'method': method, 'effort': effort, 'steps': list(steps.values()), 'model_calls': len(calls),
              'usage': usage, 'score': score(case, steps[nodes[-1]['id']]['output'])}
    save(record_path, record)
    return record


def main():
    mode = sys.argv[1]
    plan = freeze()
    print('Frozen', len(plan['selected']), 'pairs;', plan['observed_originals'], 'observed originals', flush=True)
    if mode == 'prepare':
        for item in plan['selected']:
            print(item['label'], item['pair'], item['db_id'], item['selection_evidence'], flush=True)
        return 0
    if mode not in ('anchor', 'run'):
        raise ValueError('Use prepare, anchor or run')
    for path, fingerprint in plan['code_sha256'].items():
        if digest(ROOT / path) != fingerprint:
            raise ValueError(f'Frozen code differs: {path}')
    ids = [*EXAMPLES, *(f'{p["pair"]}-{side}' for p in plan['selected'] for side in ('pre', 'post'))]
    samples = samples_by_id()
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    key = settings['THINGO_API_KEY']
    cfg = make_config([samples[i] for i in ids], MODEL, endpoint)
    cfg.update(reasoning_efforts=EFFORTS, selection_sha256=digest(OUT/'plan.json'), graph=GRAPH)
    config_path = OUT/'config.json'
    if config_path.exists() and load(config_path) != cfg:
        raise ValueError('Run configuration differs')
    save(config_path, cfg)
    if mode == 'anchor':
        ids = list(EXAMPLES)
    tasks = [(samples[sample_id], method, effort) for i, sample_id in enumerate(ids)
             for method, effort in CONDITIONS[i % 4:] + CONDITIONS[:i % 4]]
    failures = []
    done = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(evaluate, sample, method, effort, endpoint, key): (sample['id'], method, effort)
                   for sample, method, effort in tasks}
        for future in as_completed(futures):
            context = futures[future]
            try:
                record = future.result()
                done += 1
                if done % 8 == 0:
                    print(f'{done}/{len(tasks)} scored', *context, record['score']['status'], flush=True)
            except Exception as error:
                failed = {'condition': context, 'error': str(error).replace(key, '[REDACTED]')}
                failures.append(failed)
                print('Failed', failed, flush=True)
    save(OUT/'failures.json', failures)
    print(f'{done}/{len(tasks)} scored; {len(failures)} transport or runner failures', flush=True)
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main())
