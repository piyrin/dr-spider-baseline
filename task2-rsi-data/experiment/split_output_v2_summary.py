"""Verify v2 original and extension results before appending the report."""

from collections import Counter
from statistics import mean

from experiment import ROOT, Scenario
from projection_summary import arm_metrics, compare, decimal, outcome
from run_full_evaluation import digest, load, save
from split_output_anchor_v2 import EFFORTS, EXAMPLES, OUT, REPEATS
from split_output_summary import verify_call, verify_record
from split_output_v2 import validate_split_v2

REPORT = ROOT / 'reports/任务2先验知识与人工编排实验.md'
TITLE = '#### v2 原题、课程画布与扩展实测'
CONDITIONS = [(method, effort) for effort in EFFORTS for method in ('baseline', 'v2')]


def checked(folder):
    record = load(folder / 'record.json')
    case = Scenario.from_id(record['id'])
    verify_record(record, case)
    calls = [step for step in record['steps'] if step['call']]
    for step in calls:
        verify_call(step, case, folder / step['id'], record['effort'])
    assert record['model_calls'] == len(calls)
    usages = [step['call']['usage'] or {} for step in calls]
    record['usage'] = {}
    for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        available = [usage.get(key) for usage in usages]
        if all(type(v) is int for v in available):
            record['usage'][key] = sum(available)
    assert record['usage'].get('total_tokens') == record['total_tokens']
    return record


def read_original():
    results = {}
    for effort in EFFORTS:
        for sample in EXAMPLES:
            reports = [checked(OUT / f'repeat-{r}' / effort / sample) for r in REPEATS]
            side = sample.rsplit('-', 1)[1]
            expected = ['Name'] if side == 'pre' else ['first_name', 'last_name']
            for result in reports:
                assert result['score']['correct'] and result['steps'][-1]['output']['columns'] == expected
                assert result['steps'][1]['output']['binding_source'] == 'explicit_question_schema'
            results[effort, side] = reports
    return results


def read_browser(config):
    path = OUT / 'browser-results.json'
    if not path.exists():
        return []
    results = load(path)
    assert len(results) == 2 and {r['side'] for r in results} == {'pre', 'post'}
    for result in results:
        assert validate_split_v2(result['request']['graph']) == validate_split_v2(config['graph'])
        assert len(result['course_flow']['nodes']) == 6 and result['course_flow_id']
        record = load(ROOT / '.local/task2-experiment/runs/canvas' / (result['run_id'] + '.json'))
        case = Scenario.from_id(result['sample_id'])
        verify_record(record, case)
        assert result['score']['correct'] and record['score'] == result['score'] and record['cost'] == result['cost']
        for step in record['steps']:
            verify_call(step, case)
    return results


def read_pairs(config):
    pairs = {}
    for selection in config['selected']:
        pair = pairs[selection['pair']] = {}
        for side in ('pre', 'post'):
            name = selection['pair'] + '-' + side
            for effort in EFFORTS:
                base = checked(OUT / 'extended-baseline' / effort / name)
                v2 = checked(OUT / 'repeat-extended' / effort / name)
                gen = v2['steps'][-2]
                hint = gen['output']['contract']['hint']
                request = base['steps'][-2]['call']['request']
                assert request['messages'][0] == gen['call']['request']['messages'][0]
                expected = request['messages'][-1]['content']
                if hint:
                    expected += '\nQuery plan\n' + hint
                assert expected == gen['call']['request']['messages'][-1]['content']
                pair['baseline', effort, side] = base
                pair['v2', effort, side] = v2
    return pairs


def label(method, effort):
    return ('重跑基线' if method == 'baseline' else '编排 v2') + ' ' + effort


def report(original, browser, config, pairs):
    lines = ['', TITLE, '', '原题两侧、两个 Thinking 请求档均在线重复两次。下表的 EX 和返回列均由 SQLite 重放核对。',
             '', '| Thinking 档 | 题面 | EX | 返回列 | 两次平均总 token |',
             '|---|---|---:|---|---:|']
    for (effort, side), rows in original.items():
        columns = ', '.join(rows[0]['steps'][-1]['output']['columns'])
        tokens = mean(row['total_tokens'] for row in rows)
        lines += [f'| {effort} | {side} | 2/2 | `{columns}` | {tokens:.1f} |']
    lines += ['', 'v1 原题 `high` 档 post 漏掉候选并返回一列。v2 在该档的两次请求均核验姓名组成列，分列输出后通过。',
              '原题历次模型请求和 SQL 留在两次运行目录。[第一轮请求与评分](../runs/task2-split-output-v2/repeat-1) · '
              '[第二轮请求与评分](../runs/task2-split-output-v2/repeat-2) · [原题配置](../runs/task2-split-output-v2/config.json)', '']
    post_runs = [row for effort in EFFORTS for row in original[effort, 'post']]
    rule_count = sum(row['steps'][2]['output'].get('decision_source') == 'explicit_output_policy'
                     for row in post_runs)
    lines += [f'原题 post 中，{rule_count}/{len(post_runs)} 次多列 Agent 的输出未满足单一动作契约，'
              '由明确姓名分列规则接手。响应包括筛选和关联信息，部分还输出了多个 JSON 对象。'
              '这些运行确实使用了规则回退，并继续得到了正确的两列。', '']
    if browser:
        costs = '，'.join(f'{row["side"]} {row["cost"]["total_tokens"]} token' for row in browser)
        lines += [f'课程 Visual 实测重新连线、保存、刷新再重载预设。后端两个题面均通过，{costs}。',
                  '[画布](../runs/task2-split-output-v2/canvas.png) · '
                  '[导出结构](../runs/task2-split-output-v2/structure-v2.json) · '
                  '[页面与课程后端记录](../runs/task2-split-output-v2/browser-results.json)', '']
    else:
        lines += ['课程 Visual 回放状态待补。', '']
    lines += ['原题通过后，再用 v1 已冻结的 8 对同类和 8 对混合题做扩展复测。匹配基线为本轮重新请求。'
              '这 16 对属于已有开发题回归。', '',
              '| 题单 | 条件 | pre EX | post EX | 双侧通过 | 平均调用 | 平均输入 / 输出 / 总 token |',
              '|---|---|---:|---:|---:|---:|---:|']
    results = {}
    for name, scope in (('同类', 'target'), ('混合', 'control'), ('扩展合计', None)):
        subset = [pairs[r['pair']] for r in config['selected'] if scope is None or r['label'] == scope]
        arms, comparisons = {}, {}
        for arm in CONDITIONS:
            row = arm_metrics(subset, arm)
            row['calls_mean'] = mean(p[*arm, side]['model_calls'] for p in subset for side in ('pre', 'post'))
            if arm[0] == 'v2':
                row['route_counts'] = dict(Counter(p[*arm, side]['steps'][-2]['output']['route']
                                                  for p in subset for side in ('pre', 'post')))
            arms[label(*arm)] = row
            n = row['n']
            tokens = ' / '.join(decimal(row['token_means'][name])
                                for name in ('prompt_tokens', 'completion_tokens', 'total_tokens'))
            lines += [f'| {name} | {label(*arm)} | {row["clean"]}/{n} | {row["post"]}/{n} | '
                      f'{row["both"]}/{n} | {row["calls_mean"]:.2f} | {tokens} |']
        contrasts = [(('baseline', effort), ('v2', effort)) for effort in EFFORTS]
        contrasts += [((method, 'none'), (method, 'high')) for method in ('baseline', 'v2')]
        for left, right in contrasts:
            comparisons[label(*left) + ' → ' + label(*right)] = compare(subset, left, right)
        results[name] = {'arms': arms, 'comparisons': comparisons}

    lines += ['', '| 题单 | 比较 | 修复 | 扰动误伤 | pre 回退 | 双侧通过净变化 | token 差中位数 |',
              '|---|---|---:|---:|---:|---:|---:|']
    for name, result in results.items():
        for contrast, row in result['comparisons'].items():
            lines += [f'| {name} | {contrast} | {row["repair"]} | {row["harm_post"]} | '
                      f'{row["all_pre_regressions"]} | {row["net_cc"]:+}/{row["n"]} | '
                      f'{decimal(row["median_total_token_delta"])} |']
    lines += ['', '修复指基线前对后错变为双侧通过。扰动误伤指原本双侧通过变为仅前侧通过，pre 回退计所有原题侧对转错。',
              '', '| 配对 | 题单 | 基线 none | v2 none | 基线 high | v2 high | v2 两档 pre/post 路径 |',
              '|---|---|---|---|---|---|---|']
    for row in config['selected']:
        pair = pairs[row['pair']]
        states = [outcome(pair, arm) for arm in CONDITIONS]
        routes = ['/'.join(pair['v2', effort, side]['steps'][-2]['output']['route']
                           for side in ('pre', 'post')) for effort in EFFORTS]
        lines += ['| ' + ' | '.join([f'`{row["pair"]}`', '同类' if row['label'] == 'target' else '混合',
                                    *states, ' · '.join(routes)]) + ' |']
    routed = sum(pair['v2', effort, side]['steps'][1]['output'].get('binding_source') == 'explicit_question_schema'
                 for pair in pairs.values() for effort in EFFORTS for side in ('pre', 'post'))
    lines += ['', f'扩展题的 64 个 v2 条件有 {routed} 次触发新增的明确姓名绑定。'
              '这组扩展结果用于检查整套编排的开发回归。新增绑定的直接证据来自原题。',
              '', '8 条原题评分和 128 条扩展评分已复核请求、响应和 SQLite 结果。Thinking 以服务请求档记录。',
              '[扩展题单、代码与数据配置](../runs/task2-split-output-v2/extended-config.json) · '
              '[重跑基线证据](../runs/task2-split-output-v2/extended-baseline) · '
              '[v2 扩展证据](../runs/task2-split-output-v2/repeat-extended) · '
              '[分层汇总与转移矩阵](../runs/task2-split-output-v2/extended-summary.json)', '']
    return '\n'.join(lines), results


if __name__ == '__main__':
    config = load(OUT / 'extended-config.json')
    assert config['anchor_config_sha256'] == digest(OUT / 'config.json')
    assert load(OUT / 'extended-failures.json') == []
    original, browser, pairs = read_original(), read_browser(config), read_pairs(config)
    section, summary = report(original, browser, config, pairs)
    save(OUT / 'extended-summary.json', summary)
    if TITLE in REPORT.read_text(encoding='utf-8'):
        raise ValueError('Report section already exists')
    with REPORT.open('a', encoding='utf-8') as stream:
        stream.write(section)
    print(f'Verified 8 original scores, {len(pairs) * 8} extension scores and {len(browser)} course runs')
    for scope, data in summary.items():
        print(scope, [(name, row['clean'], row['post'], row['both'], row['token_means']['total_tokens'])
                      for name, row in data['arms'].items()])
