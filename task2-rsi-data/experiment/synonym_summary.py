"""Replay the saved SQL and append measurements to the task 2 report."""

from collections import Counter
import re
from statistics import mean

from experiment import Scenario, execute_sql, score
from projection_summary import arm_metrics, compare, outcome
from run_full_evaluation import load, save
from synonym_compare import CONDITIONS, EFFORTS, MODEL, OUT, ROOT

TITLE = '### 第 3 题课程画布实测及开发回归'
REPORT = ROOT / 'reports/任务2先验知识与人工编排实验.md'
LABELS = {'anchor': '原开发题', 'target': '同类', 'control': '混合', 'all': '同类与混合全体'}


def checked_record(sample, method, effort):
    directory = OUT / method / effort / sample.id
    record = load(directory / 'record.json')
    saved = record['steps'][-1]['output']
    replay = execute_sql(sample.database, saved['sql']) if saved.get('sql') else saved
    assert score(sample, replay) == record['score']
    calls = [step for step in record['steps'] if step['call']]
    assert len(calls) == record['model_calls']
    for step in calls:
        call = step['call']
        request = load(directory / step['id'] / 'request.json')
        response = load(directory / step['id'] / 'response.json')
        assert request == {**call['request'], 'reasoning_effort': effort}
        assert request['model'] == response['model'] == MODEL
        assert sample.gold_sql not in request['messages'][-1]['content']
        assert call['response'] == response
    if 'total_tokens' in record['usage']:
        assert sum(step['call']['usage']['total_tokens'] for step in calls) == record['usage']['total_tokens']
    return record


def checked_pair(identifier):
    records = {}
    for side in ('pre', 'post'):
        sample = Scenario.from_id(f'{identifier}-{side}')
        for method, effort in CONDITIONS:
            records[method, effort, side] = checked_record(sample, method, effort)
        for effort in EFFORTS:
            canvas = records['canvas_v2', effort, side]
            if canvas['route'] in ('exact', 'fallback'):
                requests = [load(OUT / method / effort / sample.id / 'generate/request.json')
                            for method in ('baseline', 'canvas_v2')]
                assert requests[0] == requests[1], (sample.id, effort, canvas['route'])
    return records


def checked_browser():
    rows = load(OUT / 'browser-results.json')
    assert len(rows) == 4
    assert {(row['method'], row['side']) for row in rows} == {
        (method, side) for method in ('synonym', 'baseline') for side in ('pre', 'post')}
    for row in rows:
        sample = Scenario.from_id(row['request']['sample_id'])
        recorded = load(ROOT / '.local/task2-experiment/runs/canvas' / (row['run_id'] + '.json'))
        assert row['request']['graph'] == recorded['graph']
        final = recorded['steps'][-1]['output']
        replay = execute_sql(sample.database, final['sql']) if final.get('sql') else final
        assert row['score'] == recorded['score'] == score(sample, replay)
    return rows


def arm_name(arm):
    return ('基线' if arm[0] == 'baseline' else '编排 v1') + ' ' + arm[1]


def measured(pairs):
    result = {'arms': {}, 'contrasts': {}}
    for arm in CONDITIONS:
        metrics = arm_metrics(pairs, arm)
        rows = [pair[*arm, side] for pair in pairs for side in ('pre', 'post')]
        metrics['routes'] = dict(Counter(row['route'] for row in rows))
        metrics['mean_model_calls'] = mean(row['model_calls'] for row in rows)
        tokens = [step['call'].get('usage') or {} for row in rows for step in row['steps'] if step['call']]
        reasoning = [(usage.get('completion_tokens_details') or {}).get('reasoning_tokens') for usage in tokens]
        metrics['reported_reasoning_calls'] = sum(type(value) is int for value in reasoning)
        metrics['positive_reasoning_calls'] = sum(type(value) is int and value > 0 for value in reasoning)
        result['arms'][arm_name(arm)] = metrics
    if len(pairs) > 1:
        contrasts = [(('baseline', effort), ('canvas_v2', effort)) for effort in EFFORTS]
        contrasts += [((method, 'none'), (method, 'high')) for method in ('baseline', 'canvas_v2')]
        for before, after in contrasts:
            result['contrasts'][arm_name(before) + ' → ' + arm_name(after)] = compare(pairs, before, after)
    return result


def status(value):
    return '通过' if value else '未通过'


def render(browser, groups, pairs, results, probe):
    lines = ['', TITLE, '', '浏览器从课程 Visual 提交本轮原题的四个条件。每条返回课程引擎流程 ID，'
             '浏览器提交结构与 Python 执行记录一致。', '',
             '![第 3 题课程 Visual 画布](../runs/task2-filter-synonym-v1/canvas.png)', '',
             '[浏览器请求与结果](../runs/task2-filter-synonym-v1/browser-results.json) · '
             '[pre 路由截图](../runs/task2-filter-synonym-v1/pre-result.png) · '
             '[post 路由截图](../runs/task2-filter-synonym-v1/post-result.png)', '',
             '| 条件 | 题面 | 路由 | EX | 查询行数 | LLM 调用 | 总 token |',
             '|---|---|---|---|---:|---:|---:|']
    for row in browser:
        lines.append(f'| {row["method"]} | {row["side"]} | {row["route"]} | '
                     f'{status(row["score"]["correct"])} | {row["score"]["prediction_rows"]} | '
                     f'{row["cost"]["model_calls"]} | {row["cost"]["total_tokens"]} |')
    lines += ['', '在浏览器默认请求档的 post 运行中，提取正确定位了 `Airlines.Country = United States`，'
              '精确查值未命中，SQLite 给出的同列候选是 `USA`。同义 Agent 在理由中认出了全称和缩写关系，'
              '但误以为候选缺少数据库证据，仍返回空值。复核节点按设计回退，原 SQL 生成返回 0 行。'
              '批测中 none 档的 Agent 也拒绝了该映射，理由混淆了航司和国家字段。high 档选择了 `USA`。',
              '', f'在单独的 `Canada` 负对照中，Agent 看到了唯一候选 `USA`，仍返回无同义匹配。'
              f'基线和编排均返回 {probe["score"]["prediction_rows"]} 行，编排耗用 {probe["model_calls"]} 次 LLM。'
              '这条人工变体用于核验回退，不进入 17 对批测统计。'
              '[逐节点记录](../runs/task2-filter-synonym-v1/canvas_v2/high/canada-negative/record.json)']
    lines += ['', '批测覆盖 1 对原开发题、8 对历史同类错题、8 对沿用第 2 题题单的混合对照。'
              '17 对的原题 ID 互异。每侧在基线与编排分别用 `reasoning_effort=none/high` 请求，'
              '合计 136 条评分。模型均返回 `gpt-6-sol` 标识。Thinking 以请求档位记载。'
              '精确命中和回退分支的 SQL 生成请求已逐字段核对，与同档基线一致。', '',
              '[运行配置](../runs/task2-filter-synonym-v1/config.json) · '
              '[完整统计](../runs/task2-filter-synonym-v1/summary.json) · '
              '[逐节点请求、响应、生成 SQL 及评分](../runs/task2-filter-synonym-v1)', '',
              '| 题单 | 条件 | pre EX | post EX | 双侧通过 | 回退/精确/同义 | 每题 LLM | 每题总 token |',
              '|---|---|---:|---:|---:|---|---:|---:|']
    for scope, result in results.items():
        for arm, metrics in result['arms'].items():
            n = metrics['n']
            routes = '/'.join(str(metrics['routes'].get(route, 0)) for route in ('fallback', 'exact', 'synonym'))
            token = metrics['token_means']['total_tokens']
            token_cell = f'{token:.1f}' if token is not None else '—'
            lines.append(f'| {LABELS[scope]} | {arm} | {metrics["clean"]}/{n} | {metrics["post"]}/{n} | '
                         f'{metrics["both"]}/{n} | {routes if arm.startswith("编排") else "—"} | '
                         f'{metrics["mean_model_calls"]:.2f} | {token_cell} |')
    lines += ['', '修复按基线前对后错且编排后双侧通过计。扰动误伤按双侧通过变前对后错计。'
              'pre 回退包含所有原题对转错。区间来自以原题为单位的配对自举。', '',
              '| 题单 | 比较 | 修复 | 扰动误伤 | pre 回退 | 双侧净变化与 95% 区间 | token 差中位数 |',
              '|---|---|---:|---:|---:|---|---:|']
    for scope, result in results.items():
        for name, metrics in result['contrasts'].items():
            lo, hi = (value * 100 for value in metrics['cc_delta_ci'])
            lines.append(f'| {LABELS[scope]} | {name} | {metrics["repair"]} | {metrics["harm_post"]} | '
                         f'{metrics["all_pre_regressions"]} | {metrics["net_cc"]:+d}/{metrics["n"]} '
                         f'[{lo:+.1f}, {hi:+.1f}] pp | {metrics["median_total_token_delta"]} |')
    lines += ['', '| 配对 | 题单 | 基线 none | 编排 none | 基线 high | 编排 high | 编排 none 路由 | 编排 high 路由 |',
              '|---|---|---|---|---|---|---|---|']
    for scope, identifiers in groups.items():
        for identifier in identifiers:
            pair = pairs[identifier]
            results = [outcome(pair, arm) for arm in (
                ('baseline', 'none'), ('canvas_v2', 'none'), ('baseline', 'high'), ('canvas_v2', 'high'))]
            routes = ['/'.join(pair['canvas_v2', effort, side]['route'] for side in ('pre', 'post'))
                      for effort in EFFORTS]
            lines.append('| ' + ' | '.join([identifier, LABELS[scope], *results, *routes]) + ' |')
    return lines


def main():
    groups = load(OUT / 'plan.json')['groups']
    pairs = {identifier: checked_pair(identifier) for identifiers in groups.values() for identifier in identifiers}
    rows = checked_browser()
    original = Scenario.from_id('NLQ_value_synonym-00162-post')
    control = Scenario('canada-negative', original.question.replace('the United States', 'Canada'),
                       original.database, original.gold_sql.replace('"USA"', '"Canada"'))
    probe = checked_record(control, 'canvas_v2', 'high')
    baseline = checked_record(control, 'baseline', 'high')
    assert probe['route'] == 'fallback' and probe['score'] == baseline['score']
    assert probe['steps'][2]['output']['status'] == 'no_match'
    results = {scope: measured([pairs[identifier] for identifier in identifiers])
               for scope, identifiers in groups.items()}
    results['all'] = measured([pairs[identifier] for scope in ('target', 'control') for identifier in groups[scope]])
    save(OUT / 'summary.json', results)
    report = REPORT.read_text(encoding='utf-8')
    if TITLE not in report:
        title = '## 第二轮 · 第 3 题筛选值同义配对 v1'
        start = report.index(title) + len(title)
        next_section = re.search(r'^## ', report[start:], re.MULTILINE)
        end = start + next_section.start() if next_section else len(report)
        section = '\n'.join(render(rows, groups, pairs, results, probe))
        REPORT.write_text(report[:end].rstrip() + '\n\n' + section.strip() + '\n\n' + report[end:],
                          encoding='utf-8')
    print('Replayed', len(pairs) * 8, 'batch conditions,', len(rows), 'browser results and two controls.')
    for scope, result in results.items():
        print(scope, {arm: (m['clean'], m['post'], m['both'], m['token_means']['total_tokens'])
                      for arm, m in result['arms'].items()})


if __name__ == '__main__':
    main()
