"""Audit historical reruns and append their results to the task 2 report."""

from collections import Counter
from statistics import mean, median
import sys

from experiment import ROOT, Scenario, execute_sql, result_eq, score
from projection_history import EFFORT, OUT
from run_full_evaluation import digest, load, save


METHODS = ('baseline', 'canvas_v2')
SIDES = ('pre', 'post')
TITLE = '### 134 对历史失败中的同类回归'
REPORT = ROOT / 'reports/任务2先验知识与人工编排实验.md'


def projection_only(case, actual, gold):
    columns = [column.lower() for column in actual.get('columns', [])]
    wanted = [column.lower() for column in gold['columns']]
    if len(columns) <= len(wanted) or any(columns.count(column) != 1 for column in wanted):
        return False
    positions = [columns.index(column) for column in wanted]
    projected = [tuple(row[i] for i in positions) for row in actual['rows']]
    return result_eq(gold['rows'], projected, 'order by' in case.gold_sql.lower())


def verify(plan):
    records = {}
    for pair in plan['selected']:
        stem = pair['pair']
        collected = {}
        for side in SIDES:
            sample = Scenario.from_id(f'{stem}-{side}')
            gold = execute_sql(sample.database, sample.gold_sql)
            requests = {}
            for method in METHODS:
                folder = OUT / 'requests' / method / EFFORT / sample.id
                path = OUT / 'records' / method / EFFORT / (sample.id + '.json')
                raw, request, record = (load(p) for p in (folder/'response.json', folder/'request.json', path))
                assert request['reasoning_effort'] == EFFORT and raw['model'] == request['model'] == 'gpt-6-sol'
                assert sample.gold_sql not in request['messages'][1]['content']
                result = record['steps'][-1]['output']
                fresh = execute_sql(sample.database, result['sql']) if result.get('sql') else result
                assert score(sample, fresh) == record['score']
                if method == 'canvas_v2':
                    route = next(s['output'] for s in record['steps'] if s['kind'] == 'projection_constraint')
                    assert (route['route'], route['field']) == (pair[side]['route'], pair[side]['field'])
                requests[method] = request
                collected[method, side] = {
                    'correct': record['score']['correct'],
                    'total_tokens': (record.get('usage') or {}).get('total_tokens'),
                    'projection_only': not record['score']['correct'] and projection_only(sample, fresh, gold),
                    'columns': fresh.get('columns'),
                }
            left, right = (requests[m] for m in METHODS)
            if pair[side]['route'] == 'fallback':
                assert left == right
            else:
                plan_text = next(s['output']['hint'] for s in record['steps'] if s['kind'] == 'projection_constraint')
                assert plan_text
                assert right['messages'][1]['content'] == left['messages'][1]['content'] + '\nQuery plan\n' + plan_text
                assert right['messages'][0] == left['messages'][0]
        records[stem] = collected
    return records


def state(records, method):
    return ''.join('C' if records[method, side]['correct'] else 'W' for side in SIDES)


def summarize(pairs, records):
    runs = [records[pair['pair']] for pair in pairs]
    transitions = Counter((state(r, METHODS[0]), state(r, METHODS[1])) for r in runs)
    deltas, averages = [], {}
    for method in METHODS:
        quantities = [r[method, side]['total_tokens'] for r in runs for side in SIDES
                      if type(r[method, side]['total_tokens']) is int]
        averages[method] = {'mean': mean(quantities) if quantities else None, 'count': len(quantities)}
    for r in runs:
        for side in SIDES:
            a, b = (r[method, side]['total_tokens'] for method in METHODS)
            if type(a) is int and type(b) is int:
                deltas.append(b-a)
    counts = {
        'n': len(pairs), 'originals': len({pair['original_id'] for pair in pairs}),
        'pre': [sum(r[m,'pre']['correct'] for r in runs) for m in METHODS],
        'post': [sum(r[m,'post']['correct'] for r in runs) for m in METHODS],
        'both': [sum(state(r,m)=='CC' for r in runs) for m in METHODS],
        'post_fixed': sum(n for (a,b),n in transitions.items() if a[1]=='W' and b[1]=='C'),
        'post_harmed': sum(n for (a,b),n in transitions.items() if a[1]=='C' and b[1]=='W'),
        'pre_harmed': sum(n for (a,b),n in transitions.items() if a[0]=='C' and b[0]=='W'),
        'cw_fixed': transitions['CW','CC'],
        'cw_denominator': sum(n for (a,_),n in transitions.items() if a=='CW'),
        'transitions': {a+'→'+b:n for (a,b),n in transitions.items()},
        'baseline_projection_only_post_pairs': [p['pair'] for p in pairs
                                                 if records[p['pair']]['baseline','post']['projection_only']],
        'token_mean': averages, 'token_difference_median': median(deltas) if deltas else None,
        'token_difference_coverage': len(deltas),
    }
    return counts


def render(plan, records, results):
    lines = ['', TITLE, '',
             '取 134 对前对后错复核表中属于「输出线索由具体变宽」的全部 18 对，共 14 道原题。'
             '同一原题有不同扰动变体，按配对计数。题单来自历史错误，采用同轮基线估计可重复的修复。',
             '使用上轮冻结的 v2 和同一 SQLite 执行评分，固定 `gpt-6-sol` 及 `reasoning_effort=none`。'
             '每侧分别运行基线和 v2，共 72 个条件。全量重新执行评分。', '',
             '| post 路由 | 配对 | pre EX 基线 → v2 | post EX 基线 → v2 | 双侧通过 | post 错转对 / 对转错 | pre 回退 |',
             '|---|---:|---:|---:|---:|---|---:|']
    for label, metrics in results.items():
        n = metrics['n']
        rates = [f'{metrics[k][0]}/{n} → {metrics[k][1]}/{n}' for k in ('pre','post','both')]
        lines.append(f'| {label} | {n} | ' + ' | '.join(rates) +
                     f' | {metrics["post_fixed"]} / {metrics["post_harmed"]} | {metrics["pre_harmed"]} |')
    overall = results['全体']
    a, b = (overall['token_mean'][method]['mean'] for method in METHODS)
    lines += ['', f'同轮四格中，前对后错变为双侧通过 **{overall["cw_fixed"]}/{overall["cw_denominator"]}**。'
              f'每个条件各调用模型一次，平均总 token {a:.1f} → {b:.1f}，'
              f'各题面 token 差值中位数 {overall["token_difference_median"]:+.1f}。',
              'post 回退组的两方法请求逐字段一致。这里的分数变化是相同提示的重跑波动。'
              '该组部分题的 pre 仍会触发约束，pre 和双侧指标另列。', '',
              '| 配对编号 | 原题 ID | v2 pre / post 路由 | 基线 | 编排 v2 | 新基线 post 仅输出列多选 |',
              '|---|---:|---|---|---|---|']
    for pair in plan['selected']:
        r = records[pair['pair']]
        output_issue = '是' if r['baseline','post']['projection_only'] else '—'
        lines.append(f'| `{pair["pair"]}` | {pair["original_id"]} | {pair["pre"]["route"]} / {pair["post"]["route"]} | '
                     f'{state(r,"baseline")} | {state(r,"canvas_v2")} | {output_issue} |')
    lines += ['', 'C 为通过，W 为未通过，依次表示 pre 和 post。'
              '最后一列用执行结果核对，保留已有行和顺序，只取参考对应列即可通过的基线错题才算。', '',
              '[题单和来源](../runs/task2-projection-historical-v2/plan.json) · '
              '[运行版本](../runs/task2-projection-historical-v2/config.json) · '
              '[汇总](../runs/task2-projection-historical-v2/summary.json) · '
              '[逐笔评分](../runs/task2-projection-historical-v2/records) · '
              '[请求与响应](../runs/task2-projection-historical-v2/requests)', '']
    return '\n'.join(lines)


def main():
    plan = load(OUT/'plan.json')
    assert load(OUT/'config.json')['selection_sha256'] == digest(OUT/'plan.json')
    assert all(digest(ROOT/path) == value for path,value in plan['source_sha256'].items())
    data = verify(plan)
    pairs = plan['selected']
    groups = {'全体': pairs, '生成前加字段约束': [p for p in pairs if p['post']['route'] != 'fallback'],
              '回退': [p for p in pairs if p['post']['route'] == 'fallback']}
    results = {name: summarize(group, data) for name, group in groups.items()}
    save(OUT/'summary.json', results)
    text = render(plan, data, results)
    if '--write' in sys.argv and TITLE not in REPORT.read_text(encoding='utf-8'):
        with REPORT.open('a', encoding='utf-8') as stream:
            stream.write(text)
    print(text)


if __name__ == '__main__':
    main()
