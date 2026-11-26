"""Verify the v2 comparison and record it without replacing the v1 report."""

from collections import Counter
from experiment import ROOT, Scenario
from projection_summary import arm_metrics, compare, decimal
from run_api_sample import load, save
from run_full_evaluation import digest
from sort_direction_compare_v2 import EFFORTS, OUT, V1
from sort_direction_summary import REPORT, verified_pairs
from sort_direction_v2 import validate_sort_v2
from split_output_summary import verify_call, verify_record

TITLE = '## 第二轮 · 第 8 题字段含义与排序方向 v2'


def read_v2(pairs):
    totals = Counter()
    for stem, pair in pairs.items():
        for side in ('pre', 'post'):
            case = Scenario.from_id(stem + '-' + side)
            for effort in EFFORTS:
                record = load(OUT / 'records' / effort / (case.id + '.json'))
                verify_record(record, case)
                folder = OUT / 'requests' / effort / case.id
                sources = record['response_sources']
                for node in record['steps']:
                    call = node['call']
                    if call is None:
                        continue
                    call_path = folder / node['id']
                    verify_call(node, case, call_path, effort)
                    source = sources[node['id']]
                    if source == 'v2':
                        totals['new'] += 1
                    else:
                        old = ROOT / source
                        assert load(old) == load(call_path / 'response.json')
                        assert load(old.with_name('request.json')) == load(call_path / 'request.json')
                        totals['reused'] += 1
                previous = pair['canvas_v1', effort, side]
                assert record['steps'][0]['output'] == previous['steps'][0]['output']
                assert record['steps'][1]['output'] == previous['steps'][1]['output']
                pair['canvas_v2', effort, side] = record
    return totals


def read_browser():
    results = load(OUT / 'browser-results.json')
    assert len(results) == 2 and {item['side'] for item in results} == {'pre', 'post'}
    for row in results:
        case = Scenario.from_id(row['sample_id'])
        raw = load(ROOT / '.local/task2-experiment/runs/canvas' / (row['run_id'] + '.json'))
        verify_record(raw, case)
        assert row['course_flow_id'] and row['score'] == raw['score'] and row['cost'] == raw['cost']
        assert row['request']['graph'] == raw['graph']
        validate_sort_v2(raw['graph'])
        for step in raw['steps']:
            verify_call(step, case)
    return results


def render(plan, pairs, calls, browser):
    stem = plan['anchor'][0].removesuffix('-pre')
    groups = {'原题': [pairs[stem]],
              '同类': [pairs[r['pair']] for r in plan['selected'] if r['label'] == 'target'],
              '混合': [pairs[r['pair']] for r in plan['selected'] if r['label'] == 'control'],
              '扩展全体': [pairs[r['pair']] for r in plan['selected']]}
    lines = ['', TITLE, '',
             '依据用户方案，方向 Agent 先解释题目要比较的量和候选列的实际含义，再给出排序关系。'
             '它需要区分日历年、经过年数和无关量。实际值用来印证列义，两侧各自读取当前库。'
             '列义或关系不明时回退。v2 沿用 v1 的意图解析、查列、SQL 生成与执行节点。',
             '', '```mermaid', 'flowchart LR',
             '    I["题意解析 Agent"] --> T["SQLite 排序列核验"]',
             '    T -->|相似列和实际值| M["字段含义与方向 Agent"]',
             '    M -->|列义、同向或反向| G["SQL 生成 Agent"]',
             '    T -->|直接匹配或无法核验| G',
             '    M -->|未知，基线提示| G',
             '    G --> E["SQLite 执行"]', '```',
             '', '| 节点 | 类型与作用 | 输入 | 输出 |', '|---|---|---|---|',
             '| 题意解析 | LLM，辨认排序要求 | 当侧题面、schema | 原始方向、候选表列和匹配类型 |',
             '| 排序列核验 | SQLite 工具，核对字段与取样 | 候选、当前库 | 直接匹配结果，或相似列与实际值、类型、频数 |',
             '| 字段含义与方向判断 | 条件 LLM，理解列义并比较两个量 | 问题、schema 与核实的列证据 | '
             '题意量、列义、同向/反向/未知和依据。程序按关系换算方向或回退 |',
             '| SQL 生成 | LLM，生成查询 | 题面、schema、核实后的排序约束或空提示 | SQL 和路径 |',
             '| 执行 | SQLite 工具，运行只读查询 | SQL 和当前库 | 结果行与列，或执行错误 |',
             '', '### 课程 Visual 原题实测', '',
             '| 题侧 | 方向路径 | 列义或回退原因 | 生成 SQL | EX | 调用数 | 总 token |',
             '|---|---|---|---|---|---:|---:|']
    for row in browser:
        direction = row['steps'][2]['output']
        sql = ' '.join((row['steps'][3]['output'].get('sql') or '无').split())
        meaning = direction.get('column_meaning') or direction.get('reason') or '直接使用核验列'
        lines.append(f'| {row["side"]} | {direction["route"]} {direction.get("direction", "")} | '
                     f'{meaning.replace("|", "/")} | `{sql.replace("|", "&#124;")}` | {row["score"]["status"]} | '
                     f'{row["cost"]["model_calls"]} | {row["cost"]["total_tokens"]} |')
    lines += ['', '[画布](../runs/task2-sort-direction-v2/canvas.png) · '
              '[结构 JSON](../runs/task2-sort-direction-v2/structure-v2.json) · '
              '[浏览器和课程引擎记录](../runs/task2-sort-direction-v2/browser-results.json)',
              '', '### 同一题单和 Thinking 档位对照', '',
              '冻结题单包含原题 1 对、同类 5 对、混合 8 对。v2 有 56 条评分，基线与 v1 沿用上一轮记录。'
              f'v2 逻辑调用中，{calls["reused"]} 次复用逐字段相同的 v1 请求的响应，'
              f'{calls["new"]} 次为变更请求的新响应。'
              '表内 token 包含复用响应的使用量，用于比较完整流程成本。',
              '', '| 题单 | 档位 | 基线双侧 | v1 双侧 | v2 双侧 | v2 pre EX | v2 post EX | '
              'v1 → v2 pre 对转错 | v1 → v2 post 对转错 | v1 → v2 平均总 token |',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    summary = {}
    for label, group in groups.items():
        summary[label] = {}
        for effort in EFFORTS:
            arms = {name: arm_metrics(group, (name, effort))
                    for name in ('baseline', 'canvas_v1', 'canvas_v2')}
            change = compare(group, ('canvas_v1', effort), ('canvas_v2', effort))
            summary[label][effort] = {'arms': arms, 'v1_to_v2': change}
            n = len(group)
            new = arms['canvas_v2']
            states = ' | '.join(f'{v["both"]}/{n}' for v in arms.values())
            tokens = [decimal(arms[k]['token_means']['total_tokens']) for k in ('canvas_v1', 'canvas_v2')]
            lines.append(f'| {label} | {effort} | {states} | {new["clean"]}/{n} | {new["post"]}/{n} | '
                         f'{change["all_pre_regressions"]} | {change["post_regression"]} | {" → ".join(tokens)} |')
    lines += ['', '[沿用的冻结题单](../runs/task2-sort-direction-v1/plan.json) · '
              '[v2 实验配置](../runs/task2-sort-direction-v2/config.json) · '
              '[逐题证据](../runs/task2-sort-direction-v2/records) · [评分汇总](../runs/task2-sort-direction-v2/summary.json)',
              '']
    return summary, '\n'.join(lines)


def main():
    plan_path = V1 / 'plan.json'
    config = load(OUT / 'config.json')
    assert config['source_plan_sha256'] == digest(plan_path)
    assert config['source_config_sha256'] == digest(V1 / 'config.json')
    plan = load(plan_path)
    pairs = verified_pairs(plan)
    calls = read_v2(pairs)
    browser = read_browser()
    summary, section = render(plan, pairs, calls, browser)
    save(OUT / 'summary.json', {'calls': dict(calls), 'groups': summary, 'browser': browser})
    if TITLE not in REPORT.read_text(encoding='utf8'):
        with REPORT.open('a', encoding='utf8') as report:
            report.write('\n' + section)
    print('Verified', len(pairs) * 4, 'v2 conditions and', len(browser), 'browser runs;', calls)
    for group, values in summary.items():
        print(group, {effort: [v['both'] for v in row['arms'].values()] for effort, row in values.items()})


if __name__ == '__main__':
    main()
