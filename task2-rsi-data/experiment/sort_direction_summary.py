"""Verify the paired sort experiment and append the results to the task report."""

from collections import Counter
from statistics import mean

from experiment import ROOT, Scenario
from projection_summary import arm_metrics, compare, decimal, outcome
from run_api_sample import load, save
from sort_direction_canvas import EXAMPLES, validate_sort
from sort_direction_compare import CONDITIONS, EFFORTS, OUT
from split_output_summary import verify_call, verify_record

REPORT = ROOT / 'reports/任务2先验知识与人工编排实验.md'
TITLE = '## 第二轮 · 第 8 题替代字段排序方向 v1'
LABELS = {arm: ('基线' if arm[0] == 'baseline' else '编排 v1') + ' ' + arm[1] for arm in CONDITIONS}


def verified_pairs(plan):
    pairs = {}
    for stem in (EXAMPLES[0].removesuffix('-pre'), *(r['pair'] for r in plan['selected'])):
        pair = pairs[stem] = {}
        for side in ('pre', 'post'):
            case = Scenario.from_id(stem + '-' + side)
            for method, effort in CONDITIONS:
                record = load(OUT / 'records' / method / effort / (case.id + '.json'))
                verify_record(record, case)
                for step in record['steps']:
                    verify_call(step, case, OUT / 'requests' / method / effort / case.id / step['id'], effort)
                pair[method, effort, side] = record
            for effort in EFFORTS:
                base = pair['baseline', effort, side]['steps'][-2]['call']['request']
                generation = pair['canvas_v1', effort, side]['steps'][-2]
                actual = generation['call']['request']
                if generation['output']['sort_plan']['route'] == 'fallback':
                    assert actual == base
                else:
                    assert actual['messages'][0] == base['messages'][0]
                    assert actual['messages'][1]['content'].startswith(base['messages'][1]['content'] + '\nQuery plan\n')
    return pairs


def verified_browser(plan):
    browser = load(OUT / 'browser-results.json')
    for row in browser:
        case = Scenario.from_id(row['sample_id'])
        record = load(ROOT / '.local/task2-experiment/runs/canvas' / (row['run_id'] + '.json'))
        verify_record(record, case)
        assert row['course_flow_id'] and row['score'] == record['score'] and row['cost'] == record['cost']
        assert record['graph'] == row['request']['graph']
        if row['condition'] == 'canvas':
            assert validate_sort(record['graph']) == validate_sort(plan['graph'])
        for step in record['steps']:
            verify_call(step, case)
    assert {(row['condition'], row['side']) for row in browser} == {
        (condition, side) for condition in ('canvas', 'baseline') for side in ('pre', 'post')}
    return browser


def render(plan, pairs, browser):
    anchor = EXAMPLES[0].removesuffix('-pre')
    groups = {'原题': [pairs[anchor]],
              '同类': [pairs[r['pair']] for r in plan['selected'] if r['label'] == 'target'],
              '混合': [pairs[r['pair']] for r in plan['selected'] if r['label'] == 'control'],
              '扩展全体': [pairs[r['pair']] for r in plan['selected']]}
    lines = ['', TITLE, '',
             f'原题 `{anchor}`。编排按用户给定的条件分支实现。'
             '题意 Agent 提取当前问题的原始排序方向和候选列，工具核对当前 SQLite 表列。'
             '直接匹配跳过列值取样和方向 Agent。相似列提供最多八个实际值及其存储类型，'
             '方向 Agent 判断同向、反向或无法确定。无法确定时，SQL 生成请求与同档基线相同。',
             '推理阶段只使用当侧题面、库和查列证据。配对参考 SQL 只用于筛选和评分。',
             '', '```mermaid', 'flowchart LR',
             '    A["排序题意 Agent"] --> T["SQLite 字段核对"]',
             '    T -->|直接匹配，保留方向| G["SQL 生成 Agent"]',
             '    T -->|相似列，读取实际值| D["方向判断 Agent"]',
             '    D -->|同向或反向| G', '    T -->|无可信列，基线提示| G',
             '    D -->|无法确定，基线提示| G', '    G --> E["SQLite 执行与 EX"]', '```',
             '', '| 节点 | 类型与作用 | 输入 | 输出 |',
             '|---|---|---|---|',
             '| 排序题意解析 | LLM，识别要排序的量及其题意方向 | 当侧题面和 SQLite schema | '
             '题面原文、候选表列、直接或相似、原始 ASC/DESC。无明确单列排序时返回空候选 |',
             '| SQLite 排序列核验与取样 | 只读工具，核验列存在并在相似分支取样 | '
             '上游候选、当侧 SQLite | 直接核验结果，或候选列、至多八个不同值及存储类型和频数，或回退原因 |',
             '| 替代字段排序判断 | 条件调用 LLM，判定原排序量和实际列的关系 | '
             '当侧题面和 schema、已核对的相似列、原方向、取样结果 | 同向、反向或未知，以及理由。'
             '程序据关系换算实际方向。直接匹配或无候选时跳过模型 |',
             '| 按排序约束生成 SQL | LLM，生成完整查询 | 当侧题面和 schema。'
             '有已选定列和方向时追加查询计划，回退时用基线提示 | 一条 SQL 和所走路径 |',
             '| 执行 SQLite 查询 | 只读工具，运行查询 | 上游生成 SQL 和当侧 SQLite | '
             '返回列、结果行或执行错误。外层评测按参考执行结果判 EX |',
             '', '### 课程 Visual 实测', '',
             '| 方法 | 侧 | EX | 路径或判断 | 调用数 | 总 token |',
             '|---|---|---|---|---:|---:|']
    for row in browser:
        direction = next((step['output'] for step in row['steps'] if step['id'] == 'direction'), {})
        route = direction.get('route', 'baseline')
        note = direction.get('reason') if route == 'fallback' else direction.get('direction')
        lines.append(f'| {row["condition"]} | {row["side"]} | {row["score"]["status"]} | '
                     f'{route}{(" · " + note) if note else ""} | {row["cost"]["model_calls"]} | '
                     f'{row["cost"]["total_tokens"]} |')
    lines += ['', '已在浏览器重连、保存、刷新后重载流程。页面请求包含图与样本 ID，'
              '由 Spring Boot / RSI Flow 逐节点执行。实际列值 13–20 已传入方向 Agent。'
              '课程 Visual 的 post 判断返回 unknown，说明该响应认为小整数和列名不足以确认字段语义及共同参照。'
              '回退按设计发生，SQL 仍用存续年数降序，12 行顺序错误。'
              'pre 命中成立年份直接走降序，方向 Agent 跳过。',
              '', '[画布](../runs/task2-sort-direction-v1/canvas.png) · '
              '[结构 JSON](../runs/task2-sort-direction-v1/structure-v1.json) · '
              '[浏览器与课程引擎记录](../runs/task2-sort-direction-v1/browser-results.json) · '
              '[post 截图](../runs/task2-sort-direction-v1/post-result.png)',
              '', '### 原题、同类、混合与 Thinking 对照', '',
              f'原题 1 对、同类 {len(groups["同类"])} 对、混合 {len(groups["混合"])} 对，112 个配对条件全部有评分。'
              '同类按显式单列排序、参考字段方向反向和两侧参考执行结果逐序相同筛选。'
              f'已有暴露原题 {plan["observed_originals"]} 道，本组归入开发回归。'
              'Thinking 按发送的 none/high 请求档分组。批跑使用和画布同源的节点实现。',
              '', '| 题单 | 方法与档位 | pre EX | post EX | 双侧通过 | 平均调用 | 平均总 token |',
              '|---|---|---:|---:|---:|---:|---:|']
    summary = {}
    for label, group in groups.items():
        stats = summary[label] = {'arms': {}, 'contrasts': {}}
        for arm in CONDITIONS:
            info = arm_metrics(group, arm)
            selected = [pair[*arm, side] for pair in group for side in ('pre', 'post')]
            info['calls_mean'] = mean(item['model_calls'] for item in selected)
            if arm[0] != 'baseline':
                info['routes'] = {
                    side: dict(Counter(pair[*arm, side]['steps'][-2]['output']['sort_plan']['route']
                                       for pair in group)) for side in ('pre', 'post')}
            stats['arms'][LABELS[arm]] = info
            n = info['n']
            lines.append(f'| {label} | {LABELS[arm]} | {info["clean"]}/{n} | {info["post"]}/{n} | '
                         f'{info["both"]}/{n} | {info["calls_mean"]:.2f} | {decimal(info["token_means"]["total_tokens"])} |')
        contrasts = [(('baseline', effort), ('canvas_v1', effort)) for effort in EFFORTS]
        contrasts += [((arm, 'none'), (arm, 'high')) for arm in ('baseline', 'canvas_v1')]
        for before, after in contrasts:
            name = LABELS[before] + ' → ' + LABELS[after]
            stats['contrasts'][name] = compare(group, before, after)
    lines += ['', '| 题单 | 对比 | 修复 | 扰动误伤 | pre 回退 | 双侧通过净变化 | token 差中位数 |',
              '|---|---|---:|---:|---:|---:|---:|']
    for label, item in summary.items():
        for name, info in item['contrasts'].items():
            lines.append(f'| {label} | {name} | {info["repair"]} | {info["harm_post"]} | '
                         f'{info["all_pre_regressions"]} | {info["net_cc"]:+d}/{info["n"]} | '
                         f'{decimal(info["median_total_token_delta"])} |')
    lines += ['', '逐题状态按 pre、post 排列。C 表示通过，W 表示未通过。',
              '', '| 样本 | 分组 | 基线 none | 编排 none | 基线 high | 编排 high |',
              '|---|---|---|---|---|---|']
    arms = [('baseline', 'none'), ('canvas_v1', 'none'), ('baseline', 'high'), ('canvas_v1', 'high')]
    for item in [{'pair': anchor, 'label': 'anchor'}, *plan['selected']]:
        stem = item['pair']
        lines.append('| ' + ' | '.join([f'`{stem}`', item['label'],
                                       *(outcome(pairs[stem], arm) for arm in arms)]) + ' |')
    lines += ['', '[冻结题单](../runs/task2-sort-direction-v1/plan.json) · '
              '[运行配置](../runs/task2-sort-direction-v1/config.json) · '
              '[逐题评分](../runs/task2-sort-direction-v1/records) · '
              '[模型请求与响应](../runs/task2-sort-direction-v1/requests) · '
              '[汇总与转移矩阵](../runs/task2-sort-direction-v1/summary.json)', '']
    return summary, '\n'.join(lines)


def main():
    plan = load(OUT / 'plan.json')
    pairs = verified_pairs(plan)
    browser = verified_browser(plan)
    summary, body = render(plan, pairs, browser)
    save(OUT / 'summary.json', summary)
    if TITLE not in REPORT.read_text(encoding='utf-8'):
        with REPORT.open('a', encoding='utf-8') as report:
            report.write('\n' + body)
    print(f'Verified {len(pairs) * 8} batch and {len(browser)} browser results.')
    for name, item in summary.items():
        print(name, {label: (r['clean'], r['post'], r['both']) for label, r in item['arms'].items()})


if __name__ == '__main__':
    main()
