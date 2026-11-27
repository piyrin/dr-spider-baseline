"""Re-score the frozen count-scope comparisons and write inspection evidence."""

from collections import Counter
from pathlib import Path
from statistics import mean

from count_scope_compare import OUT as V1
from experiment import HERE, ROOT, Scenario, execute_sql, score
from projection_compare import EFFORTS, MODEL
from projection_summary import arm_metrics, compare, outcome
from run_full_evaluation import digest, load, save


VERSIONS = ('baseline', 'canvas_v1', 'canvas_v2', 'canvas_v3')
EVIDENCE = ROOT/'results/task2/submission/records/task2-count-scope-revisions'


def verify_score(case, record):
    final = record['steps'][-1]['output']
    replay = execute_sql(case.database, final['sql']) if final.get('sql') else final
    assert record['score'] == score(case, replay), record['id']


def verify_revision(case, record, directory, effort, version):
    calls = [step for step in record['steps'] if step['call']]
    assert len(calls) == record['model_calls'] == 2
    for node in calls:
        folder = directory/'requests'/effort/case.id/node['id']
        request, response = (load(folder/name) for name in ('request.json', 'response.json'))
        call = node['call']
        assert request == {**call['request'], 'reasoning_effort': effort}
        assert case.gold_sql not in request['messages'][1]['content']
        assert request['model'] == response['model'] == MODEL
        assert response == call['response'] and response.get('usage') == call['usage']
        source = record['response_sources'][node['id']]
        if source != version:
            previous = ROOT/source
            assert load(previous) == response and load(previous.with_name('request.json')) == request
    for metric in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        values = [(step['call'].get('usage') or {}).get(metric) for step in calls]
        if all(type(value) is int for value in values):
            assert record['usage'][metric] == sum(values)


def read_pair(stem):
    result = {}
    for side in ('pre', 'post'):
        case = Scenario.from_id(stem+'-'+side)
        for effort in EFFORTS:
            for method in VERSIONS:
                if method in VERSIONS[:2]:
                    record = load(V1/'records'/method/effort/(case.id+'.json'))
                else:
                    version = method.removeprefix('canvas_')
                    directory = ROOT/f'runs/task2-count-scope-{version}'
                    record = load(directory/'records'/effort/(case.id+'.json'))
                    verify_revision(case, record, directory, effort, version)
                verify_score(case, record)
                result[method, effort, side] = record
    return result


def metrics(pairs):
    arms, changes = {}, {}
    for effort in EFFORTS:
        for method in VERSIONS:
            condition = method, effort
            run = [pair[*condition, side] for pair in pairs for side in ('pre', 'post')]
            arms[' '.join(condition)] = {**arm_metrics(pairs, condition),
                'mean_calls': mean(row['model_calls'] for row in run)}
        for before, after in zip(VERSIONS, VERSIONS[1:]):
            changes[f'{before} to {after} {effort}'] = compare(pairs, (before, effort), (after, effort))
    return {'arms': arms, 'changes': changes}


def verify_visual(version):
    folder = ROOT/f'runs/task2-count-scope-{version}'
    result = []
    for browser in load(folder/'visual-results.json'):
        case = Scenario.from_id(browser['sample_id'])
        trace = load(HERE/'runs/canvas'/(browser['run_id']+'.json'))
        assert browser['course_flow_id'] and browser['score'] == trace['score']
        assert browser['request']['graph'] == trace['graph'] and browser['cost'] == trace['cost']
        verify_score(case, {'id': case.id, **trace})
        raw = {k: trace[k] for k in ('sample_id', 'run_id', 'graph', 'graph_sha256', 'score', 'cost')}
        raw['course_flow_id'] = browser['course_flow_id']
        raw['side'] = browser['side']
        raw['steps'] = [{k: v for k, v in step.items() if k != 'call'} for step in trace['steps']]
        result.append(raw)
    assert {item['side'] for item in result} == {'pre', 'post'} and len(result) == 2
    return result


def main():
    plan = load(V1/'plan.json')
    anchor = plan['anchor'][0].removesuffix('-pre')
    selection = [{'pair': anchor, 'label': 'anchor'}, *plan['selected']]
    cases = {item['pair']: read_pair(item['pair']) for item in selection}
    stats = {group: metrics([cases[row['pair']] for row in selection if row['label'] == group
                            or group == 'all' and row['label'] != 'anchor'])
             for group in ('anchor', 'target', 'control', 'all')}
    rows = []
    indicators, reused = Counter(), Counter()
    for item in selection:
        row = dict(item)
        pair = cases[item['pair']]
        row['outcomes'] = {' '.join((version, effort)): outcome(pair, (version, effort))
                           for version in VERSIONS for effort in EFFORTS}
        row['revisions'] = {}
        for version in ('v2', 'v3'):
            for effort in EFFORTS:
                for side in ('pre', 'post'):
                    rec = pair['canvas_'+version, effort, side]
                    decision = rec['steps'][1]['output']
                    check = rec['steps'][-2]['output'].get('check')
                    if decision.get('basis') == 'benchmark_default':
                        indicators[f'{version} {effort} {item["label"]} default'] += 1
                    if check and check != 'unchanged':
                        indicators[f'{version} {check}'] += 1
                    reused[version] += sum(src != version for src in rec['response_sources'].values())
                    row['revisions'][f'{version} {effort} {side}'] = {
                        'decision': decision, 'check': check, 'score': rec['score'],
                        'sql': rec['steps'][-1]['output'].get('sql'), 'usage': rec['usage'],
                        'response_sources': rec['response_sources']}
        rows.append(row)
    visual = {version: verify_visual(version) for version in ('v2', 'v3')}
    save(EVIDENCE/'comparison.json', {'source_plan_sha256': digest(V1/'plan.json'), 'metrics': stats,
                                    'samples': rows, 'triggers': dict(indicators),
                                    'cached_model_responses': dict(reused), 'visual': visual})
    for version in ('v2', 'v3'):
        config = load(ROOT/f'runs/task2-count-scope-{version}/config.json')
        save(EVIDENCE/f'config-{version}.json', config)
    print(f'{len(cases)} pairs, {len(cases)*16} scored conditions, 4 Visual runs. Cached node responses {dict(reused)}.')


if __name__ == '__main__':
    main()
