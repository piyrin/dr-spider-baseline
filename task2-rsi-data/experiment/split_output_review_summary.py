"""Recheck v3 requests and SQLite scores, then write the version comparison."""

from collections import Counter
import json
from statistics import mean

from experiment import ROOT, Scenario, database_input, execute_sql, score
from projection_summary import arm_metrics, compare, decimal, outcome
from run_full_evaluation import digest, load, save
from split_output_review_compare import EFFORTS, EXAMPLES, OUT
from split_output_v3 import validate_v3

REPORT = ROOT / 'reports/任务2先验知识与人工编排实验.md'
SECTION = '##### v3 实测结果'
ARCHIVE = ROOT / 'results/task2/submission/records/task2-split-output-v3'
CONDITIONS = [(method, effort) for effort in EFFORTS for method in ('draft', 'final')]


def check(record, case, effort=None, folder=None):
    steps = {row['id']: row for row in record['steps']}
    initial, final = steps['draft']['output'], steps['execute']['output']
    proposal = steps['audit']['output']['proposal']
    prefix = f'Schema\n{database_input(case.database)["schema"]}\nQuestion\n{case.question}'
    expected = {'draft': prefix,
                'audit': {'draft_sql': initial.get('sql')},
                'confirm': {'draft_sql': initial.get('sql'), 'proposal': proposal}}
    for node, content in expected.items():
        call = steps[node]['call']
        if call is None:
            assert node == 'confirm' and steps['gate']['output']['gate'] != 'eligible'
            continue
        actual = call['request']['messages'][-1]['content']
        if node == 'draft':
            assert actual == content
        else:
            assert actual.startswith(prefix + '\nSQL review input\n')
            assert json.loads(actual.removeprefix(prefix + '\nSQL review input\n')) == content
        assert call['request']['model'] == call['response']['model'] and call['request']['stream'] is False
        if folder is not None:
            assert load(folder/node/'request.json') == {**call['request'], 'reasoning_effort': effort}
            assert load(folder/node/'response.json') == call['response']
    if final['revision'] == 'accepted':
        assert final['sql'] == proposal['sql'].strip()
    else:
        assert final.get('sql') == initial.get('sql')
    for key, output in [('draft_score', initial), ('score', final)]:
        actual = execute_sql(case.database, output['sql']) if output.get('sql') else {
            'status': output.get('status', 'generation_error'), 'reason': output.get('reason')}
        assert record[key] == score(case, actual)


def read_case(batch, effort, sample):
    folder = OUT/batch/effort/sample
    record = load(folder/'record.json')
    check(record, Scenario.from_id(sample), effort, folder)
    return record


def condition(record, method):
    calls = [step['call'] for step in record['steps'] if step['call']]
    if method == 'draft':
        calls = calls[:1]
    vals = [call.get('usage') or {} for call in calls]
    metrics = {}
    for name in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        field = [row.get(name) for row in vals]
        if all(type(value) is int for value in field):
            metrics[name] = sum(field)
    return {'score': record['draft_score' if method == 'draft' else 'score'],
            'calls': len(calls), 'usage': metrics}


def label(method, effort):
    return ('初稿' if method == 'draft' else 'v3 最终') + ' ' + effort


def summarize(config, records):
    pairs = {}
    for selection in config['selected']:
        stem = selection['pair']
        pairs[stem] = {(method, effort, side): condition(records[effort, stem+'-'+side], method)
                       for method, effort in CONDITIONS for side in ('pre', 'post')}
    result = {}
    for name, key in [('同类', 'target'), ('混合', 'control'), ('扩展合计', None)]:
        group = [pairs[r['pair']] for r in config['selected'] if key is None or r['label'] == key]
        arms = {}
        for arm in CONDITIONS:
            stats = arm_metrics(group, arm)
            stats['call_mean'] = mean(p[*arm, side]['calls'] for p in group for side in ('pre', 'post'))
            arms[label(*arm)] = stats
        comparisons = {e: compare(group, ('draft', e), ('final', e)) for e in EFFORTS}
        result[name] = {'arms': arms, 'comparisons': comparisons}
    return pairs, result


def render(config, original, records, browser, pairs, results):
    ref = '../results/task2/submission/records/task2-split-output-v3'
    lines = ['', SECTION, '', '初稿和最终 SQL 在流程结束后分别用 SQLite 重放。原题 8 次运行产生 16 条评分，'
             '扩展 64 次运行产生 128 条评分。', '',
             '| 原题侧 | Thinking 档 | 初稿 EX | 最终 EX | 平均总 token 初稿 → 最终 |',
             '|---|---|---:|---:|---:|']
    for sample in EXAMPLES:
        for effort in EFFORTS:
            rows = [r for r in original if r['effort'] == effort and r['id'] == sample]
            sides = [sum(r[field]['correct'] for r in rows) for field in ('draft_score', 'score')]
            totals = [[condition(r, m)['usage'].get('total_tokens') for r in rows] for m in ('draft', 'final')]
            usages = [decimal(mean(v for v in values if v is not None))
                      if any(v is not None for v in values) else '—' for values in totals]
            lines += [f'| {sample.rsplit("-", 1)[-1]} | {effort} | {sides[0]}/2 | {sides[1]}/2 | '
                      f'{usages[0]} → {usages[1]} |']
    if browser:
        lines += ['', '课程 Visual 的同一画布重新连线、保存、刷新并重载，再由 Spring Boot / RSI Flow 调用。',
                  '', '| 页面题面 | 初稿 EX | 最终 EX | 修订状态 | 模型调用 |',
                  '|---|---|---|---|---:|']
        for row in browser:
            lines += [f'| {row["side"]} | {row["draft_score"]["status"]} | {row["score"]["status"]} | '
                      f'{row["steps"][-1]["output"]["revision"]} | {row["cost"]["model_calls"]} |']
        lines += ['', f'[画布](../results/task2/submission/canvas/06-v3.png) · '
                  f'[导出结构]({ref}/structure-v3.json) · [浏览器记录]({ref}/browser-results.json)']
    else:
        lines += ['', '本轮批测调用画布节点实现。课程 Visual 动态运行待核验。']
    lines += ['', '| 题单 | 方法 | pre EX | post EX | 双侧通过 | 平均调用 | 平均输入 / 输出 / 总 token |',
              '|---|---|---:|---:|---:|---:|---:|']
    for scope, result in results.items():
        for name, row in result['arms'].items():
            n = row['n']
            usage = ' / '.join(decimal(row['token_means'][k])
                               for k in ('prompt_tokens', 'completion_tokens', 'total_tokens'))
            lines += [f'| {scope} | {name} | {row["clean"]}/{n} | {row["post"]}/{n} | {row["both"]}/{n} | '
                      f'{row["call_mean"]:.2f} | {usage} |']
    lines += ['', '| 题单 | Thinking 档 | 修复 | 扰动误伤 | pre 回退 | 双侧净变化 | 总 token 差中位数 |',
              '|---|---|---:|---:|---:|---:|---:|']
    for scope, result in results.items():
        for effort, row in result['comparisons'].items():
            lines += [f'| {scope} | {effort} | {row["repair"]} | {row["harm_post"]} | '
                      f'{row["all_pre_regressions"]} | {row["net_cc"]:+}/{row["n"]} | '
                      f'{decimal(row["median_total_token_delta"])} |']
    lines += ['', '| 扩展配对 | 题单 | 初稿 none | 最终 none | 初稿 high | 最终 high |',
              '|---|---|---|---|---|---|']
    for picked in config['selected']:
        stem = picked['pair']
        row = ['`'+stem+'`', '同类' if picked['label']=='target' else '混合',
               *(outcome(pairs[stem], arm) for arm in CONDITIONS)]
        lines += ['| ' + ' | '.join(row) + ' |']
    states = Counter((r['steps'][-1]['output']['gate'], r['steps'][-1]['output']['revision'])
                     for r in records.values())
    lines += ['', f'扩展修订分支计数为 `{dict(states)}`。两个 Thinking 值为服务请求档。',
              f'[配置]({ref}/config.json) · [本轮汇总]({ref}/summary.json) · '
              f'[逐条件决定]({ref}/conditions.json)', '', '']
    return '\n'.join(lines)


def main():
    config = load(OUT/'config.json')
    assert all(digest(ROOT/p) == value for p, value in config['implementation_sha256'].items())
    assert load(OUT/'original-failures.json') == [] and load(OUT/'extended-failures.json') == []
    original = [read_case(batch, effort, sample) for batch in ('original-1', 'original-2')
                for effort in EFFORTS for sample in EXAMPLES]
    records = {(effort, row['pair']+'-'+side): read_case('extended', effort, row['pair']+'-'+side)
               for row in config['selected'] for effort in EFFORTS for side in ('pre', 'post')}
    browser_path = OUT/'browser-results.json'
    browser = load(browser_path) if browser_path.exists() else []
    for row in browser:
        assert validate_v3(row['request']['graph']) == validate_v3(config['graph'])
        assert row['course_flow_id'] and len(row['course_flow']['nodes']) == 5
        raw_path = ROOT/'task2-rsi-data/experiment/runs/canvas'/(row['run_id']+'.json')
        check(load(raw_path), Scenario.from_id(row['sample_id']))
    pairs, results = summarize(config, records)
    save(ARCHIVE/'config.json', config)
    save(ARCHIVE/'summary.json', results)
    save(ARCHIVE/'conditions.json', [
        {**{k: row[k] for k in ('id', 'batch', 'effort', 'draft_score', 'score')},
         'draft': row['steps'][0]['output'], 'audit': row['steps'][1]['output']['proposal'],
         'confirmation': row['steps'][3]['output'].get('verdict'), 'final': row['steps'][-1]['output']}
        for row in [*original, *records.values()]])
    if browser:
        save(ARCHIVE/'browser-results.json', browser)
        save(ARCHIVE/'structure-v3.json', load(OUT/'structure-v3.json'))
        (ROOT/'results/task2/submission/canvas/06-v3.png').write_bytes((OUT/'canvas.png').read_bytes())
    text = REPORT.read_text(encoding='utf-8')
    next_case = '### 第 7 题 · Top N 重复行占名额'
    assert SECTION not in text and text.count(next_case) == 1
    text = text.replace(next_case, render(config, original, records, browser, pairs, results) + next_case, 1)
    REPORT.write_text(text, encoding='utf-8')
    for name, result in results.items():
        print(name, [(k, v['both'], v['token_means']['total_tokens']) for k,v in result['arms'].items()])
    print('Verified 8 original runs and 64 extension runs, 2 scores each, and', len(browser), 'course runs.')


if __name__ == '__main__':
    main()
