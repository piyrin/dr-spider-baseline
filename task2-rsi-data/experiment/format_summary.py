"""Verify raw model calls and summarize the frozen filter-format study."""

from collections import Counter
from statistics import mean

from experiment import Scenario, execute_sql, score
from format_compare import CONDITIONS, EFFORTS, EXAMPLES, METHODS, MODEL, OUT
from projection_summary import arm_metrics, compare, outcome
from run_full_evaluation import load, save


TITLE = '## 第二轮 · 第 2 题 Thinking、同类与混合对照'
LABELS = {'baseline': '基线', METHODS[1]: '编排 v1'}


def arm_label(condition):
    return LABELS[condition[0]] + ' ' + condition[1]


def read_case(sample, method, effort):
    root = OUT/'requests'/method/effort/sample.id
    record = load(OUT/'records'/method/effort/(sample.id+'.json'))
    final = record['steps'][-1]['output']
    evaluated = execute_sql(sample.database, final['sql']) if final.get('sql') else final
    assert record['score'] == score(sample, evaluated)
    calls = []
    for step in record['steps']:
        call = step['call']
        if call is None:
            continue
        folder = root/step['id']
        request, response = (load(folder/key) for key in ('request.json', 'response.json'))
        assert request == {**call['request'], 'reasoning_effort': effort}
        assert request['model'] == response['model'] == MODEL
        assert request['stream'] is False and sample.gold_sql not in request['messages'][-1]['content']
        assert response == call['response'] and response['usage'] == call['usage']
        calls.append(call['usage'])
    assert len(calls) == record['model_calls']
    assert sum(c['total_tokens'] for c in calls) == record['usage']['total_tokens']
    generated = record['steps'][-2]
    record['route'] = generated['output'].get('route', 'baseline')
    record['stored_value'] = generated['output'].get('stored_value')
    record['generation_request'] = load(root/'generate/request.json')
    return record


def comparison_metrics(pairs):
    result = {'arms': {}, 'contrasts': {}}
    for arm in CONDITIONS:
        records = [pair[*arm, side] for pair in pairs for side in ('pre', 'post')]
        metrics = arm_metrics(pairs, arm)
        metrics['routes'] = dict(Counter(r['route'] for r in records))
        metrics['mean_model_calls'] = mean(r['model_calls'] for r in records)
        metrics['api_calls'] = sum(r['model_calls'] for r in records)
        reasoning = [(s['call']['usage'].get('completion_tokens_details') or {}).get('reasoning_tokens')
                     for r in records for s in r['steps'] if s['call']]
        metrics['positive_reasoning_token_reports'] = sum(type(n) is int and n > 0 for n in reasoning)
        metrics['reasoning_token_coverage'] = sum(type(n) is int for n in reasoning)
        result['arms'][arm_label(arm)] = metrics
    comparisons = [(('baseline', effort), (METHODS[1], effort)) for effort in EFFORTS]
    comparisons += [((method, 'none'), (method, 'high')) for method in METHODS]
    for before, after in comparisons:
        result['contrasts'][arm_label(before)+' → '+arm_label(after)] = compare(pairs, before, after)
    return result


def render(plan, data, result):
    lines = ['', TITLE, '',
             '固定第 2 题原画布和 `gpt-6-sol`，在原题及 16 对未见官方变体上跑基线和编排，'
             '交叉比较 `reasoning_effort=none/high`。复用课程画布的节点实现批跑。'
             '所有生成请求仅使用当侧题面、schema 和节点取得的证据。', '',
             '同类层依据题面格式差和只读 SQLite 唯一匹配选取 8 对，实际选中的 8 对均为大小写变化。'
             '参考 SQL 仅供筛选和本地评分。'
             '混合层从八种 DB、NLQ、SQL 扰动各取一对。16 对原题 ID 互异，但原题已在项目中暴露，结论限于开发回归。'
             'Thinking 按请求档记录，模型系统指纹及全量推理 token 不可验证。'
             '原始运行目录沿用条件名 `canvas_v2`，本节实际执行的结构为第 2 题 v1。', '',
             '[冻结题单](../runs/task2-filter-format-comparison-v1/plan.json) · '
             '[版本与配置](../runs/task2-filter-format-comparison-v1/config.json) · '
             '[逐条件记录](../runs/task2-filter-format-comparison-v1/records) · '
             '[逐节点请求与响应](../runs/task2-filter-format-comparison-v1/requests) · '
             '[完整指标与转移矩阵](../runs/task2-filter-format-comparison-v1/summary.json)', '',
             '### 原开发题 Thinking 对照', '',
             '| 方法 | 请求档 | pre EX | post EX | pre 总 token | post 总 token |',
             '|---|---|---|---|---:|---:|']
    for method, effort in CONDITIONS:
        pre, post = (data['anchor'][method, effort, side] for side in ('pre', 'post'))
        cells = [LABELS[method], effort]
        cells += ['通过' if r['score']['correct'] else '未通过' for r in (pre, post)]
        cells += [str(r['usage']['total_tokens']) for r in (pre, post)]
        lines.append('| ' + ' | '.join(cells) + ' |')
    lines += ['', '### 同类、混合与全体结果', '',
              '| 题单 | 方法与请求档 | pre EX | post EX | 双侧通过 | pre 通过后 post 失败率 | 平均模型调用数 | 平均总 token |',
              '|---|---|---:|---:|---:|---:|---:|---:|']
    scopes = {'target': '同类', 'control': '混合', 'all': '全体'}
    for key, label in scopes.items():
        for arm, m in result[key]['arms'].items():
            n = m['n']
            asr = f'{m["cw"]}/{m["clean"]}' if m['clean'] else '—'
            lines.append(f'| {label} | {arm} | {m["clean"]}/{n} | {m["post"]}/{n} | {m["both"]}/{n} | '
                         f'{asr} | {m["mean_model_calls"]:.2f} | {m["token_means"]["total_tokens"]:.1f} |')
    lines += ['', '修复为前对后错转为双侧通过。扰动误伤为双侧通过转为前对后错。'
              '原题回退包含所有 pre 对转错。', '',
              '| 题单 | 比较 | 修复 | 扰动误伤 | 原题回退 | 双侧净变化 | 每题 TOKEN 差中位数 |',
              '|---|---|---:|---:|---:|---:|---:|']
    for key, name in scopes.items():
        for comparison, m in result[key]['contrasts'].items():
            lo, hi = m['cc_delta_ci']
            lines.append(f'| {name} | {comparison} | {m["repair"]} | {m["harm_post"]} | '
                         f'{m["all_pre_regressions"]} | {m["net_cc"]:+d}/{m["n"]} '
                         f'（95% [{100*lo:+.1f}, {100*hi:+.1f}] pp） | {m["median_total_token_delta"]:.1f} |')
    lines += ['', 'C 为通过，W 为未通过。字母按 pre、post 排列。路由按 pre/post 排列。', '',
              '| 题单 | 官方配对 ID | 基线 none | 编排 none | 基线 high | 编排 high | 编排 none 路由 | 编排 high 路由 |',
              '|---|---|---|---|---|---|---|---|']
    display = [('baseline','none'), (METHODS[1],'none'), ('baseline','high'), (METHODS[1],'high')]
    for row in plan['selected']:
        pair = data[row['pair']]
        cells = [scopes[row['label']], '`'+row['pair']+'`', *(outcome(pair, arm) for arm in display)]
        cells += ['/'.join(pair[METHODS[1], effort, s]['route'] for s in ('pre','post')) for effort in EFFORTS]
        lines.append('| ' + ' | '.join(cells) + ' |')
    for effort in EFFORTS:
        routes = result['all']['arms']['编排 v1 '+effort]['routes']
        lines += ['', f'- 全体 `{effort}` 的 32 个编排题面分支计数，' +
                  '、'.join(f'{k} {v}' for k, v in sorted(routes.items())) + '。']
    return '\n'.join(lines) + '\n'


def main():
    plan = load(OUT/'plan.json')
    sets = [('anchor', EXAMPLES)] + [(row['pair'], [row['pair']+'-'+s for s in ('pre', 'post')])
                                      for row in plan['selected']]
    data = {}
    for name, ids in sets:
        pair = {(m, e, case.id.rsplit('-', 1)[1]): read_case(case, m, e)
                for case in map(Scenario.from_id, ids) for m, e in CONDITIONS}
        for effort in EFFORTS:
            for side in ('pre','post'):
                baseline, canvas = (pair[m, effort, side] for m in METHODS)
                if canvas['route'] == 'fallback':
                    assert canvas['generation_request'] == baseline['generation_request']
        data[name] = pair
    result = {key: comparison_metrics([data[row['pair']] for row in plan['selected']
                                      if row['label'] == key or key == 'all'])
              for key in ('target','control','all')}
    result['anchor'] = comparison_metrics([data['anchor']])
    result['verified_conditions'] = 8 * len(sets)
    result['verified_model_calls'] = sum(r['model_calls'] for pair in data.values() for r in pair.values())
    save(OUT/'summary.json',result)
    (OUT/'report-section.md').write_text(render(plan, data, result),encoding='utf-8')
    print(result['verified_conditions'], 'conditions;', result['verified_model_calls'], 'model calls verified.')


if __name__ == '__main__':
    main()
