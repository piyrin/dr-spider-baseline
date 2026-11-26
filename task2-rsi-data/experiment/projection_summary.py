"""Verify and summarize frozen projection/Thinking comparisons."""

from collections import Counter
from pathlib import Path
import random
from statistics import mean, median
import sys

from experiment import ROOT, Scenario, execute_sql, score
from projection_compare import CONDITIONS, EFFORTS, METHODS, MODEL, OUT
from run_api_sample import load, save
from run_full_evaluation import digest


SCOPES = {'target': '同类', 'control': '混合对照', 'all': '全体'}
ARMS = {(method, effort): ('基线' if method == 'baseline' else '编排 v2') + ' ' + effort
        for method, effort in CONDITIONS}
STATES = ('CC', 'CW', 'WC', 'WW')
REPORT = ROOT / 'reports/任务2先验知识与人工编排实验.md'
TITLE = '### 16 对同类与混合复测结果'


def load_verified(plan):
    data = {}
    payloads = {}
    for row in plan['selected']:
        pair_id = row['pair']
        data[pair_id] = {}
        for side in ('pre', 'post'):
            sample = Scenario.from_id(f'{pair_id}-{side}')
            for method, effort in CONDITIONS:
                folder = OUT / 'requests' / method / effort / sample.id
                scored = OUT / 'records' / method / effort / f'{sample.id}.json'
                if not scored.is_file():
                    raise FileNotFoundError(scored.relative_to(ROOT))
                record, request, reply = (load(path) for path in
                                          (scored, folder/'request.json', folder/'response.json'))
                assert request['reasoning_effort'] == effort and request['model'] == reply['model'] == MODEL
                assert request['stream'] is False and sample.gold_sql not in request['messages'][1]['content']
                payloads[pair_id, side, method, effort] = {k: v for k, v in request.items() if k != 'reasoning_effort'}
                final = record['steps'][-1]['output']
                fresh = execute_sql(sample.database, final['sql']) if final.get('sql') else final
                assert record['score'] == score(sample, fresh)
                data[pair_id][method, effort, side] = record
            for method in METHODS:
                assert payloads[pair_id, side, method, 'none'] == payloads[pair_id, side, method, 'high']
            for effort in EFFORTS:
                base = payloads[pair_id, side, 'baseline', effort]
                enhanced = payloads[pair_id, side, 'canvas_v2', effort]
                if row['label'] == 'control':
                    assert base == enhanced
                else:
                    assert base['messages'][0] == enhanced['messages'][0]
                    assert enhanced['messages'][1]['content'].startswith(base['messages'][1]['content'] + '\nQuery plan\n')
    return data


def outcome(pair, condition):
    return ''.join('C' if pair[*condition, side]['score']['correct'] else 'W'
                   for side in ('pre', 'post'))


def arm_metrics(pairs, condition):
    states = Counter(outcome(pair, condition) for pair in pairs)
    usage = [pair[*condition, side].get('usage') or {}
             for pair in pairs for side in ('pre', 'post')]
    tokens = {name: [u[name] for u in usage if type(u.get(name)) is int]
              for name in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    reasoning = [(u.get('completion_tokens_details') or {}).get('reasoning_tokens') for u in usage]
    return {'n': len(pairs), 'states': dict(states), 'clean': states['CC'] + states['CW'],
            'post': states['CC'] + states['WC'], 'both': states['CC'], 'cw': states['CW'],
            'token_means': {k: mean(v) if v else None for k, v in tokens.items()},
            'token_coverage': len(tokens['total_tokens']),
            'positive_reasoning_token_reports': sum(type(n) is int and n > 0 for n in reasoning),
            'reasoning_token_coverage': sum(type(n) is int for n in reasoning)}


def compare(pairs, before, after):
    transitions = Counter((outcome(pair, before), outcome(pair, after)) for pair in pairs)
    deltas = [int(outcome(p, after) == 'CC') - int(outcome(p, before) == 'CC') for p in pairs]
    rng = random.Random(20261125)
    boot = sorted(mean(rng.choices(deltas, k=len(deltas))) for _ in range(10000))
    side_differences = []
    for pair in pairs:
        for side in ('pre', 'post'):
            left, right = ((pair[*arm, side].get('usage') or {}).get('total_tokens') for arm in (before, after))
            if type(left) is int and type(right) is int:
                side_differences.append(right - left)
    return {'n': len(pairs), 'repair': transitions['CW','CC'], 'harm_post': transitions['CC','CW'],
            'harm_pre': sum(transitions['CC',state] for state in ('WC','WW')),
            'all_pre_regressions': sum(n for (left,right),n in transitions.items()
                                       if left[0] == 'C' and right[0] == 'W'),
            'post_repair': sum(n for (left,right),n in transitions.items() if left[1] == 'W' and right[1] == 'C'),
            'post_regression': sum(n for (left,right),n in transitions.items() if left[1] == 'C' and right[1] == 'W'),
            'net_cc': sum(deltas), 'cc_delta_ci': [boot[249], boot[9749]],
            'transitions': {a: {b: transitions[a,b] for b in STATES} for a in STATES},
            'median_total_token_delta': median(side_differences) if side_differences else None,
            'token_delta_coverage': len(side_differences)}


def summary(plan, data):
    comparisons = [(('baseline', effort), ('canvas_v2', effort)) for effort in EFFORTS]
    comparisons.extend(((method, 'none'), (method, 'high')) for method in METHODS)
    result = {}
    for key in SCOPES:
        group = [data[row['pair']] for row in plan['selected'] if row['label'] == key or key == 'all']
        result[key] = {
            'arms': {ARMS[c]: arm_metrics(group, c) for c in CONDITIONS},
            'contrasts': {ARMS[a]+' → '+ARMS[b]: compare(group, a, b) for a, b in comparisons},
        }
    return result


def decimal(value):
    return f'{value:.1f}' if value is not None else '—'


def render(plan, data, results):
    lines = ['', TITLE, '',
             '冻结题单的 128 个条件全部评分，并重新执行 SQL 核对。只使用各侧公开题面、对应 schema 和该侧规则产生的字段提示。'
             '这里复用课程画布的节点实现批跑。浏览器到课程引擎的实测见上文。',
             '同类层有意覆盖 v2 能触发的名称指代，混合对照层的编排全走回退。'
             '同一请求档下，混合层的两方法请求逐字段相同，其成绩差异记录为重跑波动。',
             '所有比较均以已见原题的新官方变体为范围。', '',
             '| 题单 | 方法与请求档 | pre EX | post EX | 双侧通过 | 本组 pre 通过后 post 失败率 | 平均总 token |',
             '|---|---|---:|---:|---:|---:|---:|']
    for scope, label in SCOPES.items():
        for arm, values in results[scope]['arms'].items():
            n = values['n']
            asr = f'{values["cw"]}/{values["clean"]}' if values['clean'] else '—'
            lines.append(f'| {label} | {arm} | {values["clean"]}/{n} | {values["post"]}/{n} | '
                         f'{values["both"]}/{n} | {asr} | {decimal(values["token_means"]["total_tokens"])} |')
    lines += ['', '修复指前对后错变为双侧通过。扰动误伤指双侧通过变为前对后错。'
              '原题回退计所有 pre 对转错。双侧净变化的区间按原题配对自举。',
              '', '| 题单 | 比较 | 修复 | 扰动误伤 | 原题回退 | 双侧通过净变化 | 总 token 差中位数 |',
              '|---|---|---:|---:|---:|---:|---:|']
    for scope, label in SCOPES.items():
        for name, result in results[scope]['contrasts'].items():
            n = result['n']
            delta = result['net_cc']
            lo, hi = result['cc_delta_ci']
            lines.append(f'| {label} | {name} | {result["repair"]} | {result["harm_post"]} | '
                         f'{result["all_pre_regressions"]} | {delta:+d}/{n} '
                         f'（{100*delta/n:+.1f} pp，95% [{100*lo:+.1f}, {100*hi:+.1f}]） | '
                         f'{decimal(result["median_total_token_delta"])} |')
    lines += ['', '全体的 token 为接口报告值。推理 token 字段有缺失，Thinking 分组按实际请求档。',
              '', '| 方法与请求档 | 平均输入 token | 平均输出 token | 平均总 token | 报告非零推理 token |',
              '|---|---:|---:|---:|---:|']
    for arm, values in results['all']['arms'].items():
        t=values['token_means']
        lines.append(f'| {arm} | {decimal(t["prompt_tokens"])} | {decimal(t["completion_tokens"])} | '
                     f'{decimal(t["total_tokens"])} | {values["positive_reasoning_token_reports"]}/'
                     f'{values["reasoning_token_coverage"]} 条有字段 |')
    lines += ['', '逐对状态按 pre、post 排列。C 为通过，W 为未通过。',
              '', '| 分组 | 样本 | 基线 none | 编排 none | 基线 high | 编排 high |',
              '|---|---|---|---|---|---|']
    display = [('baseline','none'),('canvas_v2','none'),('baseline','high'),('canvas_v2','high')]
    for row in plan['selected']:
        cells = [SCOPES[row['label']], '`' + row['pair'] + '`']
        cells.extend(outcome(data[row['pair']], condition) for condition in display)
        lines.append('| ' + ' | '.join(cells) + ' |')
    lines += ['', '[汇总与四格转移矩阵](../runs/task2-projection-comparison-v1/summary.json) · '
              '[模型、样本与评测版本](../runs/task2-projection-comparison-v1/config.json) · '
              '[逐侧记录](../runs/task2-projection-comparison-v1/records) · '
              '[请求与响应](../runs/task2-projection-comparison-v1/requests)', '']
    return '\n'.join(lines)


def main():
    plan = load(OUT/'plan.json')
    assert load(OUT/'config.json')['selection_sha256'] == digest(OUT/'plan.json')
    data = load_verified(plan)
    results = summary(plan, data)
    report = render(plan, data, results)
    save(OUT/'summary.json', results)
    if '--write' in sys.argv and TITLE not in REPORT.read_text(encoding='utf-8'):
        with REPORT.open('a', encoding='utf-8') as stream:
            stream.write(report)
    print(report)


if __name__ == '__main__':
    main()
