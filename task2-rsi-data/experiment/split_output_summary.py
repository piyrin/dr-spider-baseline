"""Verify the split-output experiment and render its report section."""

from collections import Counter
from pathlib import Path
from statistics import mean

from experiment import ROOT, Scenario, execute_sql, score
from projection_summary import arm_metrics, compare, decimal, outcome
from run_full_evaluation import digest, load, save
from split_output_compare import CONDITIONS, EFFORTS, METHODS, MODEL, OUT
from split_output_canvas import validate_split

REPORT = ROOT / 'reports/任务2先验知识与人工编排实验.md'
TITLE = '## 第二轮 · 第 6 题姓名分列与拼接 v1'
LABELS = {condition: ('基线' if condition[0] == 'baseline' else '编排 v1') + ' ' + condition[1]
          for condition in CONDITIONS}


def verify_call(node, case, folder=None, effort=None):
    call = node['call']
    if call is None:
        return
    request, response = call['request'], call['response']
    assert request['model'] == response['model'] == MODEL
    assert request['stream'] is False and case.gold_sql not in request['messages'][-1]['content']
    assert response.get('usage') == call['usage']
    if folder is not None:
        assert load(folder/'request.json') == {**request, 'reasoning_effort': effort}
        assert load(folder/'response.json') == response


def verify_record(record, case):
    output = record['steps'][-1]['output']
    replay = execute_sql(case.database, output['sql']) if output.get('sql') else output
    assert score(case, replay) == record['score']
    if 'rows' in output:
        assert replay['columns'] == output['columns']
        assert [list(row) for row in replay['rows']] == output['rows']


def read_pairs(plan):
    anchor = plan['anchor'][0].rsplit('-', 1)[0]
    pairs = {}
    for stem in [anchor, *(row['pair'] for row in plan['selected'])]:
        pair = pairs[stem] = {}
        for side in ('pre', 'post'):
            case = Scenario.from_id(stem + '-' + side)
            for method, effort in CONDITIONS:
                record = load(OUT/'records'/method/effort/(case.id+'.json'))
                verify_record(record, case)
                calls = [node for node in record['steps'] if node['call']]
                assert len(calls) == record['model_calls']
                for node in calls:
                    verify_call(node, case, OUT/'requests'/method/effort/case.id/node['id'], effort)
                for field, aggregate in record['usage'].items():
                    assert sum(node['call']['usage'][field] for node in calls) == aggregate
                pair[method, effort, side] = record
            for effort in EFFORTS:
                baseline = pair['baseline', effort, side]['steps'][-2]['call']['request']
                canvas = pair['canvas_v1', effort, side]['steps'][-2]
                actual = canvas['call']['request']
                hint = canvas['output']['contract']['hint']
                if hint:
                    assert actual['messages'][0] == baseline['messages'][0]
                    assert actual['messages'][-1]['content'] == (
                        baseline['messages'][-1]['content'] + '\nQuery plan\n' + hint)
                else:
                    assert actual == baseline
    return anchor, pairs


def read_visual(plan):
    path = OUT/'browser-results.json'
    if not path.exists():
        return {}
    result = {}
    for row in load(path):
        case = Scenario.from_id(row['sample_id'])
        record = load(ROOT/'.local/task2-experiment/runs/canvas'/(row['run_id']+'.json'))
        verify_record(record, case)
        assert row['course_flow_id'] and len(row['course_flow']['nodes']) == len(record['steps'])
        assert row['score'] == record['score'] and row['cost'] == record['cost']
        assert row['request']['graph'] == record['graph']
        if row['condition'] == 'canvas':
            assert validate_split(record['graph']) == validate_split(plan['graph'])
        for node in record['steps']:
            verify_call(node, case)
        result[row['condition'], row['side']] = record
    assert len(result) == 4
    return result


def summarize(plan, anchor, pairs):
    scopes = {'原题': [pairs[anchor]],
              '同类': [pairs[r['pair']] for r in plan['selected'] if r['label'] == 'target'],
              '混合对照': [pairs[r['pair']] for r in plan['selected'] if r['label'] == 'control'],
              '扩展全体': [pairs[r['pair']] for r in plan['selected']]}
    result = {}
    for name, group in scopes.items():
        arms = {}
        for arm in CONDITIONS:
            selected = [p[*arm, side] for p in group for side in ('pre', 'post')]
            stats = arm_metrics(group, arm)
            stats.update(model_calls_mean=mean(row['model_calls'] for row in selected))
            if arm[0] != 'baseline':
                stats['routes'] = {side: dict(Counter(p[*arm, side]['steps'][-2]['output']['route']
                                                      for p in group)) for side in ('pre', 'post')}
            arms[LABELS[arm]] = stats
        contrasts = [(('baseline', effort), ('canvas_v1', effort)) for effort in EFFORTS]
        contrasts += [((method, 'none'), (method, 'high')) for method in METHODS]
        result[name] = {'arms': arms, 'comparisons': {LABELS[a] + ' → ' + LABELS[b]: compare(group, a, b)
                                                    for a, b in contrasts}}
    return result


def render(plan, anchor, pairs, visual, summary):
    lines = ['', TITLE, '',
             f'开发题 `{anchor}`。原题 1 对、同类 8 对、混合 8 对。'
             '基线和编排分别用 Thinking 请求档 `none/high` 对每侧生成，参考 SQL 只用于样本归类和本地评分。'
             f'本轮盘点到 {plan["observed_originals"]} 道已暴露原题，扩展结果按开发回归解读。',
             '', '### 编排图与节点输入输出', '',
             '```mermaid', 'flowchart LR',
             '    I["题意解析 Agent"] -->|姓名用途、候选列| F["SQLite 字段核对"]',
             '    F -->|单列或未核实，跳过模型| C["输出约束或回退"]',
             '    F -->|同一组多个组成列| D["多列处理判断 Agent"]',
             '    D -->|分列、组合查找、显式合并或回退| C',
             '    C -->|确认的约束或空提示| G["SQL 生成 Agent"]',
             '    G -->|SQL 和约束| E["SQLite 执行与返回列检查"]', '```', '',
             '| 节点 | 类型 | 输入 | 输出 |',
             '|---|---|---|---|',
             '| 题意解析 | LLM | 当侧题面、schema | 姓名原文、输出或筛选用途、所属表、候选列 |',
             '| 字段核对 | SQLite 工具 | 候选字段、当侧 SQLite | 直接使用单列、核实的多列组或回退原因 |',
             '| 多列处理判断 | 条件调用 LLM | 当侧题面、核实的姓名组成列及用途 | 分列、组合查找、明确合并显示或回退，以及题面依据 |',
             '| 输出约束 | 程序规则 | 通过核验的判断 | 姓名列顺序、查找用途提示或空提示 |',
             '| SQL 生成 | LLM | 当侧题面和 schema，非空时加约束 | 一条 SQLite SQL 和触发路径 |',
             '| 执行与返回列检查 | SQLite 工具 | SQL、分列约束 | 返回列、结果行、分列约束检查状态 |',
             '', '画布以六个事件顺序执行。单列及无法核对时，多列节点记录跳过，生成请求与同档基线逐字段相同。'
             'v1 支持姓名组成列，明确要求一列时才启用合并展示。组合查找由 SQL 生成节点使用核验列。'
             '返回列检查记录分列提示是否被遵守，EX 独立按执行结果评分。',
             '', '### 课程 Visual 验证', '']
    if visual:
        lines += ['在浏览器重新连线、保存、刷新并重载，再经课程 Spring Boot / RSI Flow 运行两侧和基线。',
                  '', '[画布截图](../runs/task2-split-output-v1/canvas.png) · '
                  '[导出结构](../runs/task2-split-output-v1/structure-v1.json) · '
                  '[浏览器请求和后端运行](../runs/task2-split-output-v1/browser-results.json) · '
                  '[post 执行截图](../runs/task2-split-output-v1/post-result.png)', '',
                  '| 方法 | 侧 | EX | 返回列 | 模型调用 | token |',
                  '|---|---|---|---|---:|---:|']
        for (method, side), run in visual.items():
            cols = run['steps'][-1]['output'].get('columns', [])
            lines.append(f'| {method} | {side} | {run["score"]["status"]} | `{cols}` | '
                         f'{run["cost"]["model_calls"]} | {run["cost"]["total_tokens"]} |')
        post = visual['canvas', 'post']
        lines += ['', 'post 节点实际输出如下。', '', '1. 题意解析 `' +
                  repr(post['steps'][0]['output']) + '`。',
                  '2. 字段核对 `' +
                  repr(post['steps'][1]['output']) + '`。',
                  '3. 多列判断 `' + repr(post['steps'][2]['output']) + '`。',
                  '4. 约束 `' + post['steps'][3]['output']['hint'] + '`。',
                  '5. 生成 `' + ' '.join(post['steps'][4]['output']['sql'].split()) + '`。',
                  '6. 执行 `' + repr(post['steps'][-1]['output'].get('rows')) +
                  '`，返回列检查 `' + post['steps'][-1]['output']['output_check'] + '`。']
    else:
        lines += ['本地批跑使用同一节点实现。浏览器证据待补。']
    lines += ['', '### 原题、同类、混合与 Thinking 对照', '',
              '| 样本 | 方法 | pre EX | post EX | 双侧通过 | 平均模型调用 | 平均输入 token | 平均输出 token | 平均总 token |',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for scope, group in summary.items():
        for arm, v in group['arms'].items():
            n = v['n']
            t = v['token_means']
            lines += [f'| {scope} | {arm} | {v["clean"]}/{n} | {v["post"]}/{n} | {v["both"]}/{n} | '
                      f'{v["model_calls_mean"]:.2f} | {decimal(t["prompt_tokens"])} | '
                      f'{decimal(t["completion_tokens"])} | {decimal(t["total_tokens"])} |']
    lines += ['', '修复计基线前对后错、加强后双侧通过。扰动误伤计双侧通过变成前对后错，pre 回退计所有原题对转错。',
              '', '| 样本 | 对比 | 修复 | 扰动误伤 | pre 回退 | 双侧净变化 | 总 token 差中位数 |',
              '|---|---|---:|---:|---:|---:|---:|']
    for scope, group in summary.items():
        for label, v in group['comparisons'].items():
            lines += [f'| {scope} | {label} | {v["repair"]} | {v["harm_post"]} | '
                      f'{v["all_pre_regressions"]} | {v["net_cc"]:+}/{v["n"]} | {decimal(v["median_total_token_delta"])} |']
    lines += ['', '| 配对 | 层 | 基线 none | 编排 none | 基线 high | 编排 high | 编排 none 路径 | 编排 high 路径 |',
              '|---|---|---|---|---|---|---|---|']
    for row in [{'pair': anchor, 'label': 'anchor'}, *plan['selected']]:
        stem = row['pair']
        pair = pairs[stem]
        states = [outcome(pair, (method, effort)) for effort in EFFORTS for method in METHODS]
        routes = ['/'.join(pair['canvas_v1', effort, side]['steps'][-2]['output']['route']
                           for side in ('pre', 'post')) for effort in EFFORTS]
        lines += ['| ' + ' | '.join([f'`{stem}`', {'target': '同类', 'control': '混合', 'anchor': '原题'}[row['label']],
                                    *states, *routes]) + ' |']
    lines += ['', '### 路由与失败证据', '',
              '| 样本 | 编排档 | pre 路径计数 | post 路径计数 |',
              '|---|---|---|---|']
    for scope, group in summary.items():
        for effort in EFFORTS:
            routes = group['arms'][LABELS['canvas_v1', effort]]['routes']
            lines += [f'| {scope} | {effort} | `{routes["pre"]}` | `{routes["post"]}` |']
    for effort in EFFORTS:
        row = pairs[anchor]['canvas_v1', effort, 'post']
        field, contract = (row['steps'][i]['output'] for i in (1, 3))
        final = row['steps'][-1]['output']
        lines += ['', f'- 原题 post `{effort}` 的字段核对为 `{field["route"]}`，'
                  f'生成路径为 `{contract["route"]}`，结果列为 `{final.get("columns", [])}`，'
                  f'EX 为 `{row["score"]["status"]}`。'
                  f'[实际节点记录](../runs/task2-split-output-v1/records/canvas_v1/{effort}/{anchor}-post.json)']
    lines += ['', '- **原题 high 的回退起于题意解析。** 解析 Agent 返回 `targets: []`，'
              '字段工具无法核验候选，多列 Agent 跳过。SQL 生成用了与基线相同的请求，'
              '把姓名拼回一列。这一档没有进入分列决策。[原题 high 全链](../runs/task2-split-output-v1/records/canvas_v1/high/DB_DBcontent_equivalence-00125-post.json)',
              '- **分列检查通过仍可能 EX 失败。** 2014 年演唱会题正确返回姓名两列，'
              '但加了 `DISTINCT`，预测 5 行，参考保留重复记录共 6 行。'
              '教师家乡题也正确分列，但筛选字面值的大小写与参考所用库值不同，预测 6 行，参考 7 行。'
              '[演唱会](../runs/task2-split-output-v1/records/canvas_v1/high/DB_DBcontent_equivalence-00004-post.json) · '
              '[教师家乡](../runs/task2-split-output-v1/records/canvas_v1/high/DB_DBcontent_equivalence-00106-post.json)',
              '- **合并分支的覆盖。** 组合查找和明确合并显示有本地单元测试。'
              '原题的课程画布实测覆盖直接单列与分列，合并分支未单独做课程 Visual 实测。']
    lines += ['', '共 136 条评分逐项重跑 SQLite 核对。Thinking 记录服务请求档，未取得可核实的模型指纹。'
              '批跑直接复用画布节点实现，课程引擎实测见浏览器记录。',
              '', '[冻结题单](../runs/task2-split-output-v1/plan.json) · '
              '[配置和数据版本](../runs/task2-split-output-v1/config.json) · '
              '[逐题评分](../runs/task2-split-output-v1/records) · '
              '[模型请求与响应](../runs/task2-split-output-v1/requests) · '
              '[汇总和转移矩阵](../runs/task2-split-output-v1/summary.json)', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    plan = load(OUT/'plan.json')
    cfg = load(OUT/'config.json')
    assert cfg['plan_sha256'] == digest(OUT/'plan.json')
    for name, value in plan['code_sha256'].items():
        assert digest(ROOT/name) == value
    anchor, pairs = read_pairs(plan)
    visual = read_visual(plan)
    summary = summarize(plan, anchor, pairs)
    save(OUT/'summary.json', summary)
    section = render(plan, anchor, pairs, visual, summary)
    if TITLE in REPORT.read_text(encoding='utf-8'):
        raise ValueError('Section already exists')
    with REPORT.open('a', encoding='utf-8') as stream:
        stream.write(section)
    print(f'{len(pairs) * 8} saved scores replayed. Verified {len(visual)} browser runs.')
    for scope, values in summary.items():
        print(scope, [(arm, row['clean'], row['post'], row['both'], row['token_means']['total_tokens'])
                      for arm, row in values['arms'].items()])
