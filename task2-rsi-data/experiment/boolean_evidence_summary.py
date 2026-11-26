"""Verify the second-version responses and compare the frozen pairs."""

from collections import Counter
from statistics import mean

from boolean_evidence_compare import EFFORTS, EXAMPLES, FIRST, GRAPH, METHOD, MODEL, OUT
from experiment import Scenario, execute_sql, score
from projection_summary import arm_metrics, compare, outcome
from run_full_evaluation import digest, load, save

ARMS = ('baseline', 'canvas_v2', METHOD)


def verify_record(case, effort):
    record = load(OUT/'records'/METHOD/effort/(case.id+'.json'))
    assert record['id'] == case.id and record['effort'] == effort
    final = record['steps'][-1]['output']
    executed = execute_sql(case.database, final['sql']) if final.get('sql') else final
    assert record['score'] == score(case, executed)
    calls = [step for step in record['steps'] if step['call'] is not None]
    assert [step['id'] for step in calls] == ['extract', 'generate']
    for step in calls:
        call = step['call']
        path = OUT/'requests'/METHOD/effort/case.id/step['id']
        request, response = (load(path/key) for key in ('request.json', 'response.json'))
        assert request == {**call['request'], 'reasoning_effort': effort}
        assert request['model'] == response['model'] == MODEL and request['stream'] is False
        assert case.gold_sql not in request['messages'][-1]['content']
        assert response == call['response'] and response.get('usage') == call['usage']
    assert len(calls) == record['model_calls']
    assert sum(step['call']['usage']['total_tokens'] for step in calls) == record['usage']['total_tokens']
    base = load(FIRST/'records/baseline'/effort/(case.id+'.json'))
    original = base['steps'][-2]['call']['request']
    generated = calls[-1]['call']['request']
    lookup = record['steps'][1]['output']
    if lookup['route'] == 'fallback':
        assert original == generated and not lookup['evidence']
    else:
        assert lookup['evidence'] and generated['messages'][0] == original['messages'][0]
        prefix = original['messages'][-1]['content']
        assert generated['messages'][-1]['content'].startswith(
            prefix+'\nQuery plan\nObserved SQLite filter-column values and storage types')
        assert all(set(x) == {'value', 'storage'} for col in lookup['evidence'] for x in col['examples'])
    return record


def summarize_group(pairs):
    result = {'arms': {}, 'contrasts': {}}
    for effort in EFFORTS:
        for method in ARMS:
            rows = [pair[method, effort, side] for pair in pairs for side in ('pre', 'post')]
            metrics = arm_metrics(pairs, (method, effort))
            metrics['mean_model_calls'] = mean(row['model_calls'] for row in rows)
            for side in ('pre', 'post'):
                metrics['routes_'+side] = dict(Counter(
                    pair[method, effort, side]['steps'][-2]['output'].get('route', 'baseline') for pair in pairs))
            result['arms'][method+' '+effort] = metrics
        for before in ARMS[:2]:
            result['contrasts'][before+' → '+METHOD+' '+effort] = compare(
                pairs, (before, effort), (METHOD, effort))
    return result


def main():
    from experiment import ROOT
    plan = load(OUT/'plan.json')
    assert plan['graph'] == GRAPH and plan['selected'] == load(FIRST/'plan.json')['selected']
    assert all(digest(ROOT/path) == sha for path,sha in plan['code_sha256'].items())
    assert all(digest(ROOT/path) == sha for path,sha in plan['first_reference_sha256'].items())
    assert load(OUT/'failures.json') == []
    target_names = [row['pair'] for row in plan['selected'] if row['label'] == 'target']
    control_names = [row['pair'] for row in plan['selected'] if row['label'] == 'control']
    anchor = EXAMPLES[0].removesuffix('-pre')
    data = {}
    for stem in [anchor, *target_names, *control_names]:
        pair = {}
        for side in ('pre', 'post'):
            case = Scenario.from_id(stem+'-'+side)
            for effort in EFFORTS:
                for arm in ARMS[:2]:
                    pair[arm, effort, side] = load(FIRST/'records'/arm/effort/(case.id+'.json'))
                pair[METHOD, effort, side] = verify_record(case, effort)
        data[stem] = pair
    result = {name: summarize_group([data[stem] for stem in stems])
              for name, stems in [('anchor',[anchor]), ('target',target_names), ('control',control_names),
                                  ('all',target_names+control_names)]}
    result['pair_outcomes'] = {stem: {method+' '+effort: outcome(pair, (method, effort))
                                     for method in ARMS for effort in EFFORTS} for stem,pair in data.items()}
    result['verified_second_version_conditions'] = len(data)*4
    result['verified_second_version_model_responses'] = len(data)*8
    save(OUT/'summary.json', result)
    print(result['verified_second_version_conditions'],'second-version conditions and',
          result['verified_second_version_model_responses'],'model responses verified.')


if __name__ == '__main__':
    main()
