"""Verify count-scope requests and render complete-case results."""

from collections import Counter
from statistics import mean

from count_scope_compare import CONDITIONS, EFFORTS, EXAMPLES, GRAPH, METHODS, MODEL, OUT
from experiment import HERE, Scenario, execute_sql, score
from projection_summary import arm_metrics, compare, decimal, outcome
from run_full_evaluation import load, save


def read_pair(stem):
    pair = {}
    for method, effort in CONDITIONS:
        for side in ('pre', 'post'):
            case = Scenario.from_id(stem+'-'+side)
            path = OUT/'records'/method/effort/(case.id+'.json')
            if not path.is_file():
                return None
            row = load(path)
            final = row['steps'][-1]['output']
            replay = execute_sql(case.database, final['sql']) if final.get('sql') else final
            assert score(case, replay) == row['score']
            calls = [node for node in row['steps'] if node['call']]
            assert len(calls) == row['model_calls']
            totals = []
            for node in calls:
                prefix = OUT/'requests'/method/effort/case.id/node['id']
                request, response = (load(prefix/name) for name in ('request.json', 'response.json'))
                call = node['call']
                assert request == {**call['request'], 'reasoning_effort': effort}
                assert request['model'] == response['model'] == MODEL
                assert case.gold_sql not in request['messages'][1]['content']
                assert call['response'] == response and call['usage'] == response.get('usage')
                totals.append((call['usage'] or {}).get('total_tokens'))
            if all(type(token) is int for token in totals):
                assert sum(totals) == row['usage']['total_tokens']
            pair[method, effort, side] = row
    for effort in EFFORTS:
        for side in ('pre', 'post'):
            plain, changed = (pair[m, effort, side]['steps'][-2] for m in METHODS)
            prior = changed['call']['request']
            original = plain['call']['request']
            if changed['output']['route'] == 'fallback':
                assert prior == original
            else:
                assert prior['messages'][0] == original['messages'][0]
                assert prior['messages'][1]['content'].startswith(
                    original['messages'][1]['content']+'\nQuery plan\nCount scope')
    return pair


def verify_visual():
    path = OUT/'visual-results.json'
    if not path.is_file():
        return []
    outcomes = []
    for row in load(path):
        case = Scenario.from_id(row['sample_id'])
        trace = load(HERE/'runs/canvas'/(row['run_id']+'.json'))
        assert row['course_flow_id'] and row['request']['graph'] == trace['graph']
        if row['method'] == 'canvas':
            assert trace['graph']['links'] == GRAPH['links']
            assert [(n['id'], n['kind']) for n in trace['graph']['nodes']] == [
                (n['id'], n['kind']) for n in GRAPH['nodes']]
        final = trace['steps'][-1]['output']
        replay = execute_sql(case.database, final['sql']) if final.get('sql') else final
        assert row['score'] == trace['score'] == score(case, replay)
        assert row['cost'] == trace['cost']
        calls = [node['call'] for node in trace['steps'] if node['call']]
        assert len(calls) == trace['cost']['model_calls']
        assert all(call['request']['model'] == call['response']['model'] == MODEL for call in calls)
        outcomes.append({'method': row['method'], 'side': row['side'], 'sample_id': case.id,
                         'run_id': row['run_id'], 'course_flow_id': row['course_flow_id'],
                         'decision': next((n['output'] for n in trace['steps']
                                           if n['kind'] == 'count_policy'), {}),
                         'score': row['score'], 'cost': row['cost'], 'sql': final.get('sql')})
    assert len({(row['method'], row['side']) for row in outcomes}) == len(outcomes)
    return outcomes


def main():
    plan = load(OUT/'plan.json')
    anchor = EXAMPLES[0].removesuffix('-pre')
    selected = [{'pair': anchor, 'label': 'anchor'}, *plan['selected']]
    data = {row['pair']: read_pair(row['pair']) for row in selected}
    visual = verify_visual()
    lines = ['### 原题、同类与混合回归结果', '',
             '以下成绩按全部八个条件完整的配对统计。C/W 分别表示执行评分通过和失败。', '',
             '| 范围 | 方法 | Thinking | pre EX | post EX | 双侧通过 | 平均调用 | 平均输入 token | 平均输出 token | 平均总 token |',
             '|---|---|---|---:|---:|---:|---:|---:|---:|---:|']
    scopes = {'anchor': '原题', 'target': '同类', 'control': '混合', 'all': '同类与混合合计'}
    summary = {}
    for key, label in scopes.items():
        expected = [row['pair'] for row in selected if row['label'] == key
                    or key == 'all' and row['label'] != 'anchor']
        pairs = [data[stem] for stem in expected if data[stem]]
        group = {'expected': len(expected), 'complete': len(pairs), 'arms': {}, 'changes': {}}
        summary[key] = group
        for method, effort in CONDITIONS:
            if not pairs:
                continue
            arm = method, effort
            stats = arm_metrics(pairs, arm)
            records = [pair[*arm, side] for pair in pairs for side in ('pre', 'post')]
            stats['mean_calls'] = mean(row['model_calls'] for row in records)
            stats['routes'] = dict(Counter(row['steps'][-2]['output'].get('route', 'baseline') for row in records))
            group['arms'][' '.join(arm)] = stats
            n, tokens = stats['n'], stats['token_means']
            lines.append(f'| {label} | {method} | {effort} | {stats["clean"]}/{n} | {stats["post"]}/{n} | '
                         f'{stats["both"]}/{n} | {stats["mean_calls"]:.2f} | '
                         + ' | '.join(decimal(tokens[k]) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')) + ' |')
        if pairs:
            for effort in EFFORTS:
                group['changes']['编排 '+effort] = compare(pairs, ('baseline', effort), ('canvas_v1', effort))
            for method in METHODS:
                group['changes'][method+' none→high'] = compare(pairs, (method, 'none'), (method, 'high'))
    lines += ['', '| 范围 | 对照 | 完整/计划配对 | 修复 | post 回退 | pre 回退 | 双侧净变化 | 总 token 差中位数 |',
              '|---|---|---:|---:|---:|---:|---:|---:|']
    for key, group in summary.items():
        for name, delta in group['changes'].items():
            lines.append(f'| {scopes[key]} | {name} | {group["complete"]}/{group["expected"]} | {delta["repair"]} | '
                         f'{delta["post_regression"]} | {delta["all_pre_regressions"]} | '
                         f'{delta["net_cc"]:+d} | {decimal(delta["median_total_token_delta"])} |')
    lines += ['', '修复指基线前对后错、编排后双侧通过。路由按 pre/post 列出。', '',
              '| 配对 | 范围 | 基线 none | 编排 none | 基线 high | 编排 high | 编排路由 none；high |',
              '|---|---|---|---|---|---|---|']
    for row in selected:
        stem, label = row['pair'], row['label']
        pair = data[stem]
        if not pair:
            lines.append(f'| `{stem}` | {scopes[label]} | 未完整 | — | — | — | — |')
            continue
        cells = [outcome(pair, (method, effort)) for effort in EFFORTS for method in METHODS]
        routes = ['/'.join(pair['canvas_v1', effort, side]['steps'][-2]['output']['route']
                           for side in ('pre', 'post')) for effort in EFFORTS]
        lines.append(' | '.join(['| `'+stem+'`', scopes[label], *cells, '；'.join(routes)])+' |')
    summary['visual'] = visual
    save(OUT/'summary.json', summary)
    (OUT/'batch-report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(sum(pair is not None for pair in data.values()), '/', len(data), 'complete pairs re-scored')


if __name__ == '__main__':
    main()
