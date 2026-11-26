"""Verify case 10 regression records and render the report tables."""

from collections import Counter
from itertools import product
from statistics import mean
from pathlib import Path
import sys

from experiment import ROOT, Scenario, execute_sql, score
from filter_count_canvas import verified_sql
from filter_count_compare import EFFORTS
from filter_count_regression import METHODS, OUT
from run_full_evaluation import digest, load, save

STATES = {
    (True, True): 'CC', (True, False): 'CW',
    (False, True): 'WC', (False, False): 'WW',
}


def verify(plan):
    config = load(OUT / 'config.json')
    assert config['plan_sha256'] == digest(OUT / 'plan.json')
    for filename, expected in plan['source_sha256'].items():
        assert digest(ROOT / filename) == expected
    assert not load(OUT / 'failures.json')
    pairs = [plan['anchor'][0].rsplit('-', 1)[0], *(r['pair'] for r in plan['selected'])]
    records = {}
    for pair, side, method, effort in product(pairs, ('pre', 'post'), METHODS, EFFORTS):
        case_id = pair + '-' + side
        folder = OUT / 'records' / method / effort / case_id
        row = load(folder / 'record.json')
        case = Scenario.from_id(case_id)
        assert (case_id, method, effort) == (row['id'], row['method'], row['effort'])
        final = row['steps'][-1]['output']
        if final['status'] == 'executed':
            replay = execute_sql(case.database, final['sql'])
            assert replay['status'] == 'executed'
            assert [list(values) for values in replay['rows']] == final['rows']
            assert score(case, replay) == row['score']
        else:
            assert score(case, final) == row['score']
            if final['status'] == 'contract_mismatch':
                contract = row['steps'][1]['output']
                assert not verified_sql(final['sql'], contract)
        for node in row['steps']:
            if not node['call']:
                continue
            payload = load(folder / node['id'] / 'request.json')
            response = load(folder / node['id'] / 'response.json')
            assert payload['reasoning_effort'] == effort
            assert response['model'] == payload['model']
            assert payload['messages'] == node['call']['request']['messages']
            assert case.gold_sql not in payload['messages'][1]['content']
        records[pair, side, method, effort] = row
    return records


def counts(pairs, effort, records):
    transitions = Counter()
    per_side = {side: Counter() for side in ('pre', 'post')}
    costs = {}
    for method in METHODS:
        ways = [records[pair, side, method, effort] for pair, side in product(pairs, ('pre','post'))]
        tokens = [row['total_tokens'] for row in ways if type(row['total_tokens']) is int]
        paired_calls = [row['model_calls'] for row in ways]
        costs[method] = {'n': len(ways), 'n_tokens': len(tokens),
                         'mean_tokens': mean(tokens) if tokens else None,
                         'mean_calls': mean(paired_calls)}
    for pair in pairs:
        original, canvas = (tuple(records[pair, side, method, effort]['score']['correct']
                                  for side in ('pre', 'post')) for method in METHODS)
        transitions[STATES[original] + '→' + STATES[canvas]] += 1
        for side, a, b in zip(('pre', 'post'), original, canvas):
            per_side[side][f'{int(a)}→{int(b)}'] += 1
    return {'pairs': len(pairs), 'transitions': dict(transitions),
            'by_side': {side: dict(counter) for side, counter in per_side.items()}, 'costs': costs}


def main(mode):
    manifest = load(OUT / 'plan.json')
    records = verify(manifest)
    groups = {'原题': [manifest['anchor'][0][:-4]],
              '同类': [r['pair'] for r in manifest['selected'] if r['label'] == 'target'],
              '混合': [r['pair'] for r in manifest['selected'] if r['label'] == 'mixed']}
    groups['全体'] = sum(groups.values(), [])
    stats = {group: {effort: counts(pairs, effort, records) for effort in EFFORTS}
             for group, pairs in groups.items()}
    changes = []
    routes = Counter()
    for group, pairs in list(groups.items())[:3]:
        for pair, side, effort in product(pairs, ('pre', 'post'), EFFORTS):
            baseline, canvas = (records[pair, side, method, effort] for method in METHODS)
            predicate = canvas['steps'][1]['output']
            inputs = [next(step['call']['request'] for step in row['steps']
                           if step['id'] == 'generate') for row in (baseline, canvas)]
            same_generation_prompt = inputs[0] == inputs[1]
            if predicate['route'] == 'fallback':
                assert same_generation_prompt
            routes[(group, effort, predicate['route'], predicate.get('reason', ''))] += 1
            if baseline['score']['correct'] != canvas['score']['correct'] or canvas['score']['status'] == 'contract_mismatch':
                changes.append({'group': group, 'pair': pair, 'side': side, 'effort': effort,
                                'baseline': baseline['score'], 'canvas': canvas['score'],
                                'evidence': predicate,
                                'same_generation_prompt': same_generation_prompt,
                                'baseline_output': baseline['steps'][-1]['output'],
                                'canvas_output': canvas['steps'][-1]['output']})
    save(OUT / 'summary.json', {'verified': len(records), 'by_group': stats, 'changes': changes,
                              'routes': [{'group': a, 'effort': b, 'route': c, 'reason': d, 'n': n}
                                         for (a,b,c,d), n in sorted(routes.items())]})
    if mode == 'verify':
        print(f'{len(records)} conditions rechecked and saved.')
        return
    print('| 范围 | Thinking | pre EX | post EX | 双侧都通过 | post 错转对 / 对转错 | 双侧净变化 |')
    print('|---|---|---:|---:|---:|---:|---:|')
    for name, group in stats.items():
        for effort, values in group.items():
            n = values['pairs']
            pair_states = values['transitions']
            a = sum(count for key, count in pair_states.items() if key.startswith('CC→'))
            b = sum(count for key, count in pair_states.items() if key.endswith('→CC'))
            rendered = []
            for side in ('pre','post'):
                s = values['by_side'][side]
                x = s.get('1→1', 0) + s.get('1→0', 0)
                y = s.get('1→1', 0) + s.get('0→1', 0)
                rendered.append(f'{x}/{n} → {y}/{n}')
            print(f'| {name} | {effort} | {rendered[0]} | {rendered[1]} | {a}/{n} → {b}/{n} | '
                  f'{s.get("0→1", 0)} / {s.get("1→0", 0)} | {b-a:+d} |')
    print()
    print('| 范围 | Thinking | 均值总 token（基线 → 编排） | 有 token 记录（基线 / 编排） |')
    print('|---|---|---:|---:|')
    for name, group in stats.items():
        for effort, values in group.items():
            a,b = (values['costs'][method] for method in METHODS)
            x,y=(f'{r["mean_tokens"]:,.1f}' if r['mean_tokens'] is not None else '缺失' for r in (a,b))
            print(f'| {name} | {effort} | {x} → {y} | {a["n_tokens"]}/{a["n"]} · {b["n_tokens"]}/{b["n"]} |')


if __name__ == '__main__':
    main(sys.argv[1])
