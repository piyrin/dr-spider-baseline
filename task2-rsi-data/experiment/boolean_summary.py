"""Verify and report the boolean-encoding canvas and paired comparisons."""

from collections import Counter
from pathlib import Path
from statistics import mean

from boolean_canvas import EXAMPLES, GRAPH
from boolean_compare import CONDITIONS, EFFORTS, METHODS, MODEL, OUT
from experiment import ROOT, Scenario, execute_sql, score
from projection_summary import arm_metrics, compare, decimal, outcome
from run_full_evaluation import digest, load, save

VISUAL = ROOT/'runs/task2-filter-boolean-v2'


def verify_calls(record, case, effort=None):
    final = record['steps'][-1]['output']
    fresh = execute_sql(case.database, final['sql']) if final.get('sql') else final
    assert record['score'] == score(case, fresh)
    totals = []
    for node in record['steps']:
        call = node['call']
        if call is None:
            continue
        request, response = call['request'], call['response']
        assert request['model'] == response['model'] == MODEL
        assert request['stream'] is False and case.gold_sql not in request['messages'][-1]['content']
        if effort is not None:
            path = OUT/'requests'/record['method']/effort/case.id/node['id']
            assert load(path/'request.json') == {**request, 'reasoning_effort': effort}
            assert load(path/'response.json') == response
        assert response.get('usage') == call['usage']
        totals.append((call.get('usage') or {}).get('total_tokens'))
    amount = sum(totals) if all(type(n) is int for n in totals) else None
    return len(totals), amount


def verify_visual():
    rows = load(VISUAL/'browser-results.json')
    assert len(rows) == 4
    results = {}
    files = [Path(__file__).parent / name for name in ('boolean_canvas.py', 'serve_canvas.py', 'web/page.tsx')]
    meta = {'code_sha256': {str(p.relative_to(ROOT)): digest(p) for p in files},
            'run_ids': {}, 'model': MODEL}
    for row in rows:
        case = Scenario.from_id(row['sample_id'])
        name = row['condition'], row['side']
        assert name not in results
        raw = load(ROOT/'.local/task2-experiment/runs/canvas'/(row['run_id']+'.json'))
        assert row['course_flow_id'] and row['course_flow']['nodes']
        assert raw['score'] == row['score'] and raw['cost'] == row['cost']
        assert raw['graph'] == row['request']['graph']
        if name[0] == 'canvas':
            assert raw['graph'] == GRAPH and len(raw['steps']) == 4
        assert verify_calls(raw, case) == (row['cost']['model_calls'], row['cost']['total_tokens'])
        results[name] = raw
        meta['run_ids']['/'.join(name)] = row['run_id']
    for side in ('pre', 'post'):
        base, canvas = (results[k, side] for k in ('baseline', 'canvas'))
        generated = canvas['steps'][-2]
        baseline_request = base['steps'][-2]['call']['request']
        request = generated['call']['request']
        if generated['output']['route'] in ('exact', 'fallback'):
            assert request == baseline_request
        else:
            assert request['messages'][-1]['content'].startswith(
                baseline_request['messages'][-1]['content']+'\nQuery plan\nVerified knowledge')
    meta_path = VISUAL/'run-meta.json'
    if meta_path.exists():
        assert load(meta_path)['run_ids'] == meta['run_ids']
    else:
        save(meta_path, meta)
    return results


def read_pair(stem):
    pair = {}
    for method, effort in CONDITIONS:
        for side in ('pre', 'post'):
            identifier = stem + '-' + side
            record = load(OUT/'records'/method/effort/(identifier+'.json'))
            case = Scenario.from_id(identifier)
            calls, total = verify_calls(record, case, effort)
            assert calls == record['model_calls'] and total == record['usage'].get('total_tokens')
            pair[method, effort, side] = record
    for effort in EFFORTS:
        for side in ('pre', 'post'):
            base, canvas = (pair[method, effort, side]['steps'][-2] for method in METHODS)
            if canvas['output']['route'] in ('exact', 'fallback'):
                assert canvas['call']['request'] == base['call']['request']
            else:
                lookup = pair[METHODS[1], effort, side]['steps'][1]['output']
                baseline_request = base['call']['request']
                request = canvas['call']['request']
                assert lookup['status'] == canvas['output']['route'] == 'boolean'
                assert request['messages'][0] == baseline_request['messages'][0]
                original = baseline_request['messages'][-1]['content']
                extended = request['messages'][-1]['content']
                assert extended.startswith(original+'\nQuery plan\nVerified knowledge')
                evidence = extended.removeprefix(original)
                assert repr(lookup['value']) in evidence and lookup['storage'] in evidence
                assert all(set(value) == {'value', 'storage'} for value in lookup['observed'])
    return pair


def metrics(pairs):
    arms, changes = {}, {}
    for method, effort in CONDITIONS:
        arm = method, effort
        records = [pair[*arm, side] for pair in pairs for side in ('pre', 'post')]
        arms[' '.join(arm)] = {**arm_metrics(pairs, arm),
                              'mean_calls': mean(row['model_calls'] for row in records),
                              'routes': dict(Counter(r['steps'][-2]['output'].get('route', 'baseline') for r in records))}
    for effort in EFFORTS:
        changes['编排 '+effort] = compare(pairs, ('baseline', effort), (METHODS[1], effort))
    for method in METHODS:
        changes[method+' none→high'] = compare(pairs, (method, 'none'), (method, 'high'))
    return {'arms': arms, 'changes': changes}


def render_batch(plan, data, result):
    lines = ['### 同类与混合题单复测', '',
             '各条件均固定原题侧、schema、模型、流程实现和执行评分。Thinking 使用 `none/high` 请求档。'
             '该题单原题已暴露，统计用于开发回归。', '',
             '| 题单 | 方法与 Thinking | pre EX | post EX | 双侧通过 | 平均模型调用 | 平均总 token |',
             '|---|---|---:|---:|---:|---:|---:|']
    scope_names = {'target': '同类', 'control': '混合', 'all': '全体'}
    for key, scope in scope_names.items():
        for arm, values in result[key]['arms'].items():
            n = values['n']
            lines.append(f'| {scope} | {arm} | {values["clean"]}/{n} | {values["post"]}/{n} | '
                         f'{values["both"]}/{n} | {values["mean_calls"]:.2f} | '
                         f'{decimal(values["token_means"]["total_tokens"])} |')
    lines += ['', '| 题单 | 对照 | 修复 | post 对转错 | pre 回退 | 双侧净变化 | 总 token 差中位数 |',
              '|---|---|---:|---:|---:|---:|---:|']
    for key, scope in scope_names.items():
        for name, changes in result[key]['changes'].items():
            lines.append(f'| {scope} | {name} | {changes["repair"]} | {changes["post_regression"]} | '
                         f'{changes["all_pre_regressions"]} | {changes["net_cc"]:+d}/{changes["n"]} | '
                         f'{decimal(changes["median_total_token_delta"])} |')
    lines += ['', '修复指基线前对后错而编排后双侧通过。逐题下表的两位依次表示 pre/post，C 通过，W 未通过。', '',
              '| 题单 | 配对 | 基线 none | 编排 none | 基线 high | 编排 high | 编排路由 none / high |',
              '|---|---|---|---|---|---|---|']
    for row in plan['selected']:
        pair = data[row['pair']]
        arms = [(m, e) for e in EFFORTS for m in METHODS]
        routes = ['/'.join(pair[METHODS[1], e, side]['steps'][-2]['output']['route']
                          for side in ('pre', 'post')) for e in EFFORTS]
        cells = [scope_names[row['label']], '`'+row['pair']+'`', *(outcome(pair, arm) for arm in arms),
                 ' / '.join(routes)]
        lines.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join(lines) + '\n'


def main():
    visual = verify_visual()
    anchor = read_pair(EXAMPLES[0].removesuffix('-pre'))
    plan = load(OUT/'plan.json')
    result = {'anchor': metrics([anchor]), 'visual_verified': len(visual)}
    count = len(list((OUT/'records').glob('*/*/*.json')))
    if count == 8 * (len(plan['selected']) + 1):
        data = {row['pair']: read_pair(row['pair']) for row in plan['selected']}
        for key in ('target', 'control', 'all'):
            result[key] = metrics([data[row['pair']] for row in plan['selected']
                                   if row['label'] == key or key == 'all'])
        (OUT/'batch-report.md').write_text(render_batch(plan, data, result), encoding='utf-8')
    result['verified_batch_conditions'] = count if 'all' in result else 8
    save(OUT/'summary.json', result)
    print(result['visual_verified'], 'visual runs and', result['verified_batch_conditions'], 'scored batch conditions verified.')


if __name__ == '__main__':
    main()
