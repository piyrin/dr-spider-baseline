"""Verify v3 against v1 and v2, then publish its traceable report section."""

from collections import Counter
from shutil import copy2, copytree

from experiment import ROOT, Scenario
from projection_summary import arm_metrics, compare, decimal, outcome
from run_api_sample import load, save
from run_full_evaluation import digest
from sort_direction_compare_v3 import EFFORTS, OUT, V1, V2
from sort_direction_summary import REPORT, verified_pairs
from sort_direction_summary_v2 import read_v2
from sort_direction_v3 import validate_sort_v3
from split_output_summary import verify_call, verify_record

DEST = ROOT / 'results/task2/submission'
TITLE = '#### 原文提取与最终方向 v3'
VERSIONS = ['baseline', 'canvas_v1', 'canvas_v2', 'canvas_v3']


def verified_v3(pairs):
    counts = Counter()
    for stem, pair in pairs.items():
        for side in ('pre', 'post'):
            case = Scenario.from_id(stem + '-' + side)
            for effort in EFFORTS:
                record = load(OUT / 'records' / effort / (case.id + '.json'))
                verify_record(record, case)
                assert record['method'] == 'canvas_v3' and record['effort'] == effort
                assert all('direction' not in item for item in record['steps'][0]['output']['targets'])
                assert 'direction' not in record['steps'][1]['output']
                folder = OUT / 'requests' / effort / case.id
                for step in record['steps']:
                    call = step['call']
                    if call is None:
                        continue
                    destination = folder / step['id']
                    verify_call(step, case, destination, effort)
                    source = record['response_sources'][step['id']]
                    if source == 'v3':
                        counts['new'] += 1
                    else:
                        origin = ROOT / source
                        assert load(origin) == load(destination / 'response.json')
                        assert load(origin.with_name('request.json')) == load(destination / 'request.json')
                        counts['reused'] += 1
                generation = record['steps'][-2]
                if generation['output']['sort_plan']['route'] == 'fallback':
                    assert generation['call']['request'] == pair['baseline', effort, side]['steps'][-2]['call']['request']
                pair['canvas_v3', effort, side] = record
    return counts


def verified_visual():
    browser = load(OUT / 'browser-results.json')
    assert len(browser) == 2 and {row['side'] for row in browser} == {'pre', 'post'}
    for row in browser:
        case = Scenario.from_id(row['sample_id'])
        raw_path = ROOT / 'task2-rsi-data/experiment/runs/canvas' / (row['run_id'] + '.json')
        raw = load(raw_path)
        verify_record(raw, case)
        assert row['course_flow_id'] and row['score'] == raw['score'] and row['cost'] == raw['cost']
        assert row['request']['graph'] == raw['graph']
        validate_sort_v3(raw['graph'])
        for step in raw['steps']:
            verify_call(step, case)
    return browser


def render(plan, pairs, browser, calls):
    anchor = plan['anchor'][0].removesuffix('-pre')
    groups = {'原题': [pairs[anchor]],
              '同类': [pairs[row['pair']] for row in plan['selected'] if row['label'] == 'target'],
              '混合': [pairs[row['pair']] for row in plan['selected'] if row['label'] == 'control'],
              '扩展全体': [pairs[row['pair']] for row in plan['selected']]}
    lines = [TITLE, '', '![第 8 题课程 Visual 画布（v3）](../results/task2/submission/canvas/08-v3.png)', '',
             '题意节点交付排序原文和候选字段。方向节点结合已核验的列义与样例，输出候选列的最终方向。'
             '直接列且题面方向明确时，方向节点从原文读取方向，跳过第二次模型调用。'
             '相似列由模型给出最终方向，程序只校验该方向和关系是否一致，冲突或未知时回退。',
             '', '```mermaid', 'flowchart LR',
             '    I["原文提取 Agent"] --> T["SQLite 核对与取样"]',
             '    T -->|已核对候选| D["最终方向节点"]',
             '    D -->|直接方向或模型决定| G["SQL 生成 Agent"]',
             '    D -->|证据不足，基线提示| G',
             '    G --> E["SQLite 执行"]', '```',
             '', '| 节点 | 类型与作用 | 输入 | 输出 |', '|---|---|---|---|',
             '| 原文提取 | LLM，挑选题面的排序要求 | 题面、schema | 原文、题意量、候选表列、匹配方式 |',
             '| 字段核对 | SQLite 工具，验证候选并对相似列取样 | 候选、当侧数据库 | 字段名、类型、原文与实际值，或回退原因 |',
             '| 最终方向 | 直接分支用程序，其余候选交给条件 LLM | 核验结果、题面原文、列义证据 | 最终 ASC/DESC、含义、来源或回退原因 |',
             '| SQL 生成 | LLM，组装完整查询 | 题面、schema、最终排序要求或基线提示 | SQL 与触发路径 |',
             '| 执行 | SQLite 工具，执行只读查询 | SQL、当侧数据库 | 结果行列或错误，外层按参考结果评分 |',
             '', '##### 课程 Visual 原题复测', '',
             '| 输入侧 | 路径 | 最终 SQL | EX | 调用数 | 总 token |',
             '|---|---|---|---|---:|---:|']
    for row in browser:
        order, generated = (row['steps'][i]['output'] for i in (2, 3))
        sql = ' '.join((generated.get('sql') or '无').split()).replace('|', '&#124;')
        lines.append(f'| {row["side"]} | {order["route"]} {order.get("direction", "")} | `{sql}` | '
                     f'{row["score"]["status"]} | {row["cost"]["model_calls"]} | {row["cost"]["total_tokens"]} |')
    prefix = '../results/task2/submission/records/task2-sort-direction-v3'
    lines += ['', f'[课程运行与节点结果]({prefix}/browser-results.json) · [结构 JSON]({prefix}/structure-v3.json)',
              '', '##### 与前两版的同题单对照', '',
              '原题 1 对、同类 5 对、混合 8 对，v3 共 56 个评分条件。两档分别为 none 与 high。'
              f'逻辑节点调用中 {calls["new"]} 次取得新响应，{calls["reused"]} 次沿用逐字段相同的 v2 响应。'
              '基线和前两版沿用同一题单结果。表内总 token 含复用节点的完整成本。',
              '', '| 题单 | Thinking | 基线双侧 | v1 双侧 | v2 双侧 | v3 双侧 | v3 pre EX | v3 post EX | '
              'v2 → v3 pre / post 对转错 | v2 → v3 平均总 token |',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    summary = {}
    for label, group in groups.items():
        summary[label] = {}
        for effort in EFFORTS:
            stats = {version: arm_metrics(group, (version, effort)) for version in VERSIONS}
            change = compare(group, ('canvas_v2', effort), ('canvas_v3', effort))
            summary[label][effort] = {'arms': stats, 'v2_to_v3': change}
            n = len(group)
            cells = ' | '.join(f'{row["both"]}/{n}' for row in stats.values())
            before, now = stats['canvas_v2'], stats['canvas_v3']
            tokens = ' → '.join(decimal(row['token_means']['total_tokens']) for row in (before, now))
            lines.append(f'| {label} | {effort} | {cells} | {now["clean"]}/{n} | {now["post"]}/{n} | '
                         f'{change["all_pre_regressions"]} / {change["post_regression"]} | {tokens} |')
    lines += ['', '逐对状态按 pre、post 排列。C 表示通过，W 表示未通过。', '',
              '| 样本 | 题单 | v1 none | v2 none | v3 none | v1 high | v2 high | v3 high |',
              '|---|---|---|---|---|---|---|---|']
    for row in [{'pair': anchor, 'label': 'anchor'}, *plan['selected']]:
        stem = row['pair']
        cases = [outcome(pairs[stem], (version, effort))
                 for effort in EFFORTS for version in VERSIONS[1:]]
        lines.append('| ' + ' | '.join([f'`{stem}`', row['label'], *cases]) + ' |')
    lines += ['', f'[冻结题单]({prefix}/plan.json) · [运行配置]({prefix}/config.json) · '
              f'[逐题记录]({prefix}/records/) · [评分汇总]({prefix}/summary.json)', '',
              '##### 三版分别改了什么', '',
              '| 版本 | 相对上一版的改动 | 解决的具体问题 |',
              '|---|---|---|',
              '| v1 | 新增题意解析、查列、方向关系判断，程序根据同向或反向换算 ASC/DESC | '
              '有直接列时保留方向。只给相似列和样例时，可在证据不足时回退 |',
              '| v2 | 方向 Agent 先解释题意量和列义，再输出同向、反向或未知。程序仍负责换算 | '
              '让判断考虑候选列实际存储的量，修复乐团原题 |',
              '| v3 | 题意 Agent 只传排序原文与候选列。相似列的最终方向由方向 Agent 给出，程序只做一致性校验。'
              '直接列引用已明确的题面方向 | 将换算集中在一个节点，消除上游提前换算、下游再次翻转的路径 |', '']
    return summary, '\n'.join(lines)


def main():
    config = load(OUT / 'config.json')
    plan_path = V1 / 'plan.json'
    assert config['source_plan_sha256'] == digest(plan_path)
    assert config['v2_config_sha256'] == digest(V2 / 'config.json')
    assert load(OUT / 'failures.json') == []
    plan = load(plan_path)
    pairs = verified_pairs(plan)
    read_v2(pairs)
    calls = verified_v3(pairs)
    browser = verified_visual()
    summary, section = render(plan, pairs, browser, calls)
    save(OUT / 'summary.json', {'calls': dict(calls), 'groups': summary, 'browser': browser})
    dest = DEST / 'records/task2-sort-direction-v3'
    copytree(OUT / 'records', dest / 'records', dirs_exist_ok=True)
    for name in ('config.json', 'summary.json', 'structure-v3.json', 'browser-results.json'):
        copy2(OUT / name, dest / name)
    copy2(plan_path, dest / 'plan.json')
    copy2(OUT / 'canvas.png', DEST / 'canvas/08-v3.png')
    for row in browser:
        filename = row['run_id'] + '.json'
        copy2(ROOT / 'task2-rsi-data/experiment/runs/canvas' / filename,
              DEST / 'records/course-node-traces' / filename)
    report = REPORT.read_text(encoding='utf8')
    next_title = '### 第 9 题 · 筛选值绑定到错误列'
    if TITLE not in report:
        assert report.count(next_title) == 1
        REPORT.write_text(report.replace(next_title, section + '\n' + next_title), encoding='utf8')
    print(f'Verified {len(pairs)*4} v3 scores and {len(browser)} course runs. {dict(calls)}')
    for label, values in summary.items():
        print(label, {effort: [item['both'] for item in stats['arms'].values()]
                      for effort, stats in values.items()})


if __name__ == '__main__':
    main()
