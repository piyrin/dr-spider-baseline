"""Replay the ten development pairs with and without hand-checked knowledge."""

from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_full_evaluation import (api_json, digest, gold_rows, iter_samples, load,
                                 make_config, make_payload, read_database,
                                 read_settings, save, score)

RUN = ROOT / 'runs/task2-prior-round1'
REPORT = ROOT / 'reports/任务2先验知识与人工编排实验.md'
MODEL = 'gpt-6-sol'
CASES = [
    ('NLQ_column_carrier-00499', '输出线索变宽',
     '筛选对了四名十年级学生，但给姓名附加了 ID 和年级。',
     'Highschooler.name stores the student name requested by the question. Grade is a filter.',
     'Highschooler.name is the human-readable identity for a who question about students. ID is a technical identifier and grade is a filter.'),
    ('NLQ_column_value-00205', '大小写不一致',
     '预测按 Sky radio 精确匹配，查不到套餐。',
     "TV_Channel.series_name stores the exact value 'Sky Radio' for the series named in the question.",
     "In TV_Channel.series_name, the stored value corresponding to the question's 'Sky radio' is 'Sky Radio'."),
    ('NLQ_value_synonym-00162', '同一对象换名称',
     '用 United States 精确匹配 Country，查不到航司。',
     "Airlines.Country stores 'USA' for the country named USA in the question.",
     "In Airlines.Country, the United States is stored as 'USA'."),
    ('DB_DBcontent_equivalence-00143', '布尔字段编码错误',
     '预测用数字 1 匹配文本布尔字段，计数为 0。',
     "In ship.disposition_of_ship, the captured disposition is stored as the text 'Captured'.",
     "ship.is_captured is a text flag. 'T' means captured and 'F' means not captured."),
    ('SQL_comparison-00133', '缺失明细被当作零',
     '预测将没有语言明细的六个地区计为零种语言。',
     'countrylanguage stores observed languages by CountryCode. A country with no corresponding language rows has no recorded language count for this comparison.',
     'countrylanguage stores observed languages by CountryCode. A country with no corresponding language rows has no recorded language count for this comparison. Missing observations do not meet a below-threshold test.'),
    ('DB_DBcontent_equivalence-00125', '分列字段被拼接',
     '访客正确，预测拼成一列，参考按姓名组成字段分为两列。',
     'The visitor full name is stored as the single field visitor.Name.',
     'The output convention for a visitor name in this schema is two separate fields: visitor.first_name followed by visitor.last_name. Preserve both components as separate output columns.'),
    ('SQL_NonDB_number-00054', 'Top N 重复行占名额',
     '重复的姓名与排名组合占了最后一个位置，漏掉另一个排名。',
     'matches has repeated match records. For this output, the ranking unit is a distinct (winner_name, winner_rank) combination, ordered by the youngest age observed for that combination. Distinct ranks of the same winner remain separate.',
     'matches has repeated match records. For this output, the ranking unit is a distinct (winner_name, winner_rank) combination, ordered by the youngest age observed for that combination. Distinct ranks of the same winner remain separate.'),
    ('DB_DBcontent_equivalence-00304', '替代字段排序方向相反',
     '使用了存续年数，但沿用了成立年份的降序，导致主排序方向相反。',
     'orchestra.Year_of_Founded is the founding calendar year. A larger value means more recently founded.',
     'orchestra.year_of_existence is elapsed age at a common reference time. A smaller age means a later founding year, so age and calendar founding year have opposite order.'),
    ('SQL_DB_text-00048', '筛选值配错属性',
     '用 Honda 匹配厂商短码列 Maker，漏掉 honda 车型。',
     "car_makers.FullName stores 'General Motors' and car_makers.Maker stores its short code 'gm'. The question names the full manufacturer name.",
     "car_makers.FullName stores 'Honda' and car_makers.Maker stores its short code 'honda'. The question names the full manufacturer name."),
    ('NLQ_keyword_carrier-00248', '改写后漏筛选条件',
     '只保留左撇子条件，混入其他赛事的获胜者。',
     "The specified tournament is stored as 'WTA Championships' in matches.tourney_name. The winner being left-handed is encoded as 'L' in matches.winner_hand. Both constraints apply.",
     "The WTA tournament referred to in the question matches the unique WTA tournament name 'WTA Championships' in matches.tourney_name. The winner being left-handed is encoded as 'L' in matches.winner_hand. Both constraints apply."),
]


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def row_preview(rows, limit=6):
    if rows is None:
        return '执行结果缺失'
    return f'{len(rows)} 行，预览 `{rows[:limit]!r}`' if rows else '0 行'


def prepare(samples, config):
    manifest = RUN / 'config.json'
    if manifest.exists() and load(manifest) != config:
        raise ValueError('Existing experiment configuration differs')
    save(manifest, config)
    if REPORT.exists():
        return
    path = ROOT / 'results/drspider-17x50/predictions.csv'
    with path.open(encoding='utf-8-sig', newline='') as stream:
        history = {row['id']: row for row in csv.DictReader(stream)}
    lines = [
        '# Dr.Spider 先验知识与人工编排实验', '',
        '## 本轮实验设计', '',
        '10 道历史前对后错的开发原题各取一个配对。第 8 题采用替代字段排序反向，原并列案例留作评分边界。',
        '先逐题完成 20 次 post 基线和先验请求，再单独复测 40 次，覆盖 10 对题的 pre/post × 两组。两批独立保留。',
        '两组共用原基线 SQL 生成提示和单库 EX。加强组仅在问题与 schema 后追加当前侧的手工先验。模型及评分配置一致。',
        '第 6 题的分列提示属于输出约定。整轮衡量人工选定证据对已知开发题的作用。', '',
        f'- 模型 `{MODEL}`，非流式，其余生成参数沿用服务端默认。模型指纹按响应保存。',
        f'- 代码基点 `{config["code_commit"]}`，实际脚本和数据哈希见[运行配置](../runs/task2-prior-round1/config.json)。',
        f'- 数据版本 `{config["data_source"]["commit"]}`，评测版本 `{config["evaluator_commit"]}`，SQLite `{config["sqlite_version"]}`。',
        '- 失败的生成 SQL 和执行错误计错。接口异常保留失败状态，完整对照使用共同可评分样本。', '',
        '## 问题清单与预期结果', '',
    ]
    for number, (key, label, diagnosis, _pre, _post) in enumerate(CASES, 1):
        post_id = key + '-post'
        rows = [samples[key + '-' + side] for side in ('pre', 'post')]
        assert rows[0]['original_id'] == rows[1]['original_id']
        assert history[key + '-pre']['correct'] == 'True'
        assert history[post_id]['correct'] == 'False'
        lines += [f'### {number}. {label}', '',
                  f'配对 `{key}`，Spider 原题 ID `{rows[0]["original_id"]}`。', '']
        for sample in rows:
            expected = gold_rows(sample['database'], sample['gold_sql'])
            lines += [f'- {sample["side"]} 输入（`{sample["db_id"]}`）{sample["question"]}',
                      f'  - 预期输出为下列参考 SQL 的实际结果。{row_preview(expected)}',
                      '  - 参考 SQL `' + ' '.join(sample['gold_sql'].split()) + '`']
        lines += [f'- 历史 post 失败原因。{diagnosis}',
                  '- 历史预测 SQL `' + ' '.join(history[post_id]['prediction_sql'].split()) + '`', '']
    REPORT.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def run_condition(phase, sample, condition, prior, endpoint, key):
    name = f'{sample["id"]}--{condition}'
    folder = RUN / phase / name
    record_path = folder / 'record.json'
    if record_path.exists():
        return load(record_path)
    payload = make_payload(MODEL, sample)
    if prior:
        payload['messages'][-1]['content'] += '\n\nVerified knowledge\n' + prior
    save(folder / 'request.json', payload)
    response_path = folder / 'response.json'
    try:
        if response_path.exists():
            response = load(response_path)
        else:
            started = time.monotonic()
            response = api_json(endpoint, key, payload)
            save(response_path, response)
            save(folder / 'timing.json', {'elapsed_seconds': round(time.monotonic() - started, 3)})
    except Exception as error:
        save(folder / 'transport-error.json', {'time': now(), 'error': str(error).replace(key, '[REDACTED]')})
        raise RuntimeError(f'{name}: {str(error).replace(key, "[REDACTED]")}') from None
    if response.get('model') != MODEL or not response.get('choices'):
        raise RuntimeError(f'{name}: unexpected model API response')
    result = score(sample, response)
    result.update(condition=condition, prior=prior, recorded_at=now(),
                  gold_rows=gold_rows(sample['database'], sample['gold_sql']))
    result['prediction_rows'] = (
        read_database(ROOT / sample['database'], result['prediction_sql'])
        if result.get('prediction_row_count') is not None else None)
    save(record_path, result)
    return result


def status(result):
    return {True: '通过', False: '未通过', None: '缺失'}[result['correct']]


def comparison(before, after):
    if None in (before['correct'], after['correct']):
        return '缺失'
    return {('未通过', '通过'): '修复', ('通过', '未通过'): '回退'}.get(
        (status(before), status(after)), '维持' + status(before))


def append_results(phase, sides, results):
    title = '## 第一轮 A · 逐题 post 验证' if phase == 'post' else '## 第一轮 B · 独立请求配对复测'
    if title in REPORT.read_text(encoding='utf-8'):
        return
    lines = [title, '', f'记录时间 `{now()}`，共有 {len(results)} 条评分记录。', '']
    for side in sides:
        grouped = [(results[key, side, 'baseline'], results[key, side, 'prior']) for key, *_ in CASES]
        complete = [(a, b) for a, b in grouped if None not in (a['correct'], b['correct'])]
        baseline_pass = sum(a['correct'] for a, _ in complete)
        prior_pass = sum(b['correct'] for _, b in complete)
        repaired = sum(comparison(a, b) == '修复' for a, b in complete)
        harmed = sum(comparison(a, b) == '回退' for a, b in complete)
        lines += [f'- {side} EX 由 **{baseline_pass}/{len(complete)}** 变为 **{prior_pass}/{len(complete)}**，'
                  f'错转对 {repaired} 题，对转错 {harmed} 题。']
    if len(sides) == 2:
        blocks = [tuple(results[key, side, c]['correct'] for c in ('baseline', 'prior') for side in sides)
                  for key, *_ in CASES]
        complete = [row for row in blocks if None not in row]
        prepost_repairs = sum(row == (True, False, True, True) for row in complete)
        lines += [f'- 双侧都通过 {sum(a and b for a,b,_,_ in complete)}/{len(complete)} → '
                  f'{sum(c and d for _,_,c,d in complete)}/{len(complete)}，'
                  f'前对后错且加强后双侧都通过 {prepost_repairs} 对。']
    for condition in ('baseline', 'prior'):
        values = [(r.get('usage') or {}).get('total_tokens')
                  for r in results.values() if r['condition'] == condition]
        available = [v for v in values if isinstance(v, int)]
        if available:
            lines += [f'- {condition} 平均总 token {sum(available)/len(available):.1f}，'
                      f'覆盖 {len(available)}/{len(values)} 次。']
    lines += ['', '| 题号 | 样本 | ' + ('pre 基线 → 先验 | pre 变化 | ' if len(sides) == 2 else '') +
              'post 基线 → 先验 | post 变化 |',
              '|---:|---|' + ('---|---|' if len(sides) == 2 else '') + '---|---|']
    for number, (key, *_details) in enumerate(CASES, 1):
        cells = [str(number), f'`{key}`']
        for side in sides:
            a, b = (results[key, side, c] for c in ('baseline', 'prior'))
            cells += [f'{status(a)} → {status(b)}', comparison(a, b)]
        lines += ['| ' + ' | '.join(cells) + ' |']
    for number, (key, label, *_details) in enumerate(CASES, 1):
        lines += ['', f'### {number}. {label}', '']
        for side in sides:
            outcome = [results[key, side, c] for c in ('baseline', 'prior')]
            lines += [f'**{side} 先验**', '', '> ' + outcome[1]['prior'], '',
                      f'预期结果。{row_preview(outcome[0]["gold_rows"])}', '']
            for result in outcome:
                condition = result['condition']
                raw_path = f'../runs/task2-prior-round1/{phase}/{result["id"]}--{condition}'
                usage = result.get('usage') or {}
                label = '基线' if condition == 'baseline' else '先验'
                lines += [f'- {label} · {status(result)}。{row_preview(result["prediction_rows"])}。'
                          f'token 输入 {usage.get("prompt_tokens", "未提供")}、'
                          f'输出 {usage.get("completion_tokens", "未提供")}、'
                          f'总计 {usage.get("total_tokens", "未提供")}。'
                          f'[请求]({raw_path}/request.json) · [响应]({raw_path}/response.json) · [评分]({raw_path}/record.json)',
                          '  - SQL `' + ' '.join((result['prediction_sql'] or '(无)').split()) + '`']
                if result.get('error'):
                    lines += [f'  - 执行或评分状态 `{result["status"]}`。{result["error"]}']
            lines += ['']
    with REPORT.open('a', encoding='utf-8') as stream:
        stream.write('\n' + '\n'.join(lines) + '\n')


def main():
    phase = sys.argv[1]
    if phase not in ('prepare', 'post', 'paired'):
        raise ValueError('Use prepare, post or paired')
    identifiers = {key + '-' + side for key, *_ in CASES for side in ('pre', 'post')}
    samples = {s['id']: s for s in iter_samples() if s['id'] in identifiers}
    assert len(samples) == 20 and len({s['original_id'] for s in samples.values()}) == 10
    settings = read_settings()
    endpoint = settings.get('THINGO_BASE_URL', 'https://intlapi.thingo.com.cn/v1').rstrip('/') + '/chat/completions'
    config = make_config(list(samples.values()), MODEL, endpoint)
    config.update(cases=[list(case) for case in CASES], runner_sha256=digest(Path(__file__)),
                  stages={'post': ['post'], 'paired': ['pre', 'post']})
    prepare(samples, config)
    if phase == 'prepare':
        return
    api_key = settings.get('THINGO_API_KEY', '').strip()
    if not api_key:
        raise ValueError('THINGO_API_KEY is unavailable')
    if phase == 'paired' and len(list((RUN / 'post').glob('*/record.json'))) != 20:
        raise ValueError('Complete the post validation phase first')
    sides = ('post',) if phase == 'post' else ('pre', 'post')
    results = {}
    with ThreadPoolExecutor(max_workers=2 if phase == 'post' else 4) as executor:
        for number, (key, _label, _diagnosis, pre_prior, post_prior) in enumerate(CASES, 1):
            priors = {'pre': pre_prior, 'post': post_prior}
            pending = {
                (key, side, condition): executor.submit(
                    run_condition, phase, samples[key + '-' + side], condition,
                    priors[side] if condition == 'prior' else '', endpoint, api_key)
                for side in sides for condition in ('baseline', 'prior')
            }
            for index, future in pending.items():
                results[index] = future.result()
            states = ', '.join(f'{side} {status(results[key, side, "baseline"])} → '
                               f'{status(results[key, side, "prior"])}' for side in sides)
            print(f'{phase} {number}/10 {key}: {states}', flush=True)
    append_results(phase, sides, results)


if __name__ == '__main__':
    main()
