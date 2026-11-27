import json
import unittest

from experiment import Scenario, score
from top_n_canvas import original_or_control
from top_n_v3 import GRAPH_V3, validate_v3, run_step
from top_n_v3_cases import fixture_case


class TopNPlanTests(unittest.TestCase):
    def test_published_v1_and_v3_have_distinct_node_types(self):
        self.assertEqual([node['id'] for node in validate_v3(GRAPH_V3)],
                         ['intent', 'inspect', 'policy', 'generate', 'execute'])

    def test_explicit_result_unit_compiles_without_a_second_model_call(self):
        case = original_or_control('top-n-pair-post')
        intent = '{"targets":[{"unit":"tuple","table":"matches","display":["winner_name","winner_rank"],' \
                 '"key":["winner_name","winner_rank"],"order":"winner_age","direction":"ASC","n":5,' \
                 '"grain_evidence":"distinct name-and-rank combinations","projection_evidence":' \
                 '"Output winner name and rank","scope":"all_rows","ties":[]}]}'
        steps, calls = self.run_case(case, intent)
        self.assertEqual(calls, ['intent'])
        self.assertEqual(steps['execute']['output']['route'], 'tuple')
        self.assertTrue(score(case, steps['execute']['output'])['correct'])

    def test_original_uses_ambiguity_route(self):
        case = Scenario.from_id('SQL_NonDB_number-00054-post')
        steps, calls = self.run_case(case, '{"targets":[{"unit":"ambiguous","grain_evidence":"5 youngest winners"}]}')
        self.assertEqual(calls, ['intent', 'generate'])
        self.assertEqual(steps['policy']['output']['reason'], 'ambiguous_unit')

    def test_unrelated_question_skips_intent(self):
        original = Scenario.from_id('SQL_NonDB_number-00054-pre')
        case = Scenario('control', 'List the winners.', original.database, original.gold_sql)
        steps, calls = self.run_case(case, None)
        self.assertEqual(calls, ['generate'])
        self.assertEqual(steps['policy']['output']['reason'], 'no_top_n_cue')

    def test_entity_plan_uses_hidden_id_and_preserves_two_people_with_same_name(self):
        case = fixture_case('lap-entity-post')
        intent = self.lap_plan('entity', 'different drivers', 3, 'Show only the driver name and track', ['driver_number'])
        steps, calls = self.run_case(case, intent)
        result = steps['execute']['output']
        self.assertEqual(calls, ['intent'])
        self.assertEqual(result['columns'], ['driver_name', 'track'])
        self.assertEqual(result['rows'], [('Aya', 'North'), ('Bo', 'West'), ('Aya', 'East')])

    def test_raw_record_plan_preserves_repeated_display_rows(self):
        case = fixture_case('lap-rows-post')
        intent = self.lap_plan('rows', 'fastest lap records', 4,
                               'Return the driver name and track', [])
        steps, calls = self.run_case(case, intent)
        result = steps['execute']['output']
        self.assertEqual(calls, ['intent'])
        self.assertEqual(result['rows'][:2], [('Aya', 'North'), ('Aya', 'North')])
        self.assertTrue(score(case, result)['correct'])

    def test_undetermined_cutoff_tie_uses_fallback(self):
        base = fixture_case('lap-rows-pre')
        case = Scenario('tie', base.question.replace('2 fastest', '1 fastest'), base.database, base.gold_sql)
        intent = self.lap_plan('rows', 'fastest lap records', 1,
                               'Return the driver name and track', [])
        steps, calls = self.run_case(case, intent)
        self.assertEqual(steps['policy']['output']['reason'], 'uncertain_cutoff_tie')
        self.assertEqual(calls, ['intent', 'generate'])

    def lap_plan(self, unit, cue, n, projection, keys):
        return json.dumps({'targets': [{'unit': unit, 'table': 'laps', 'display': ['driver_name', 'track'],
                                       'key': keys, 'order': 'elapsed_ms', 'direction': 'ASC', 'n': n,
                                       'grain_evidence': cue, 'projection_evidence': projection,
                                       'scope': 'all_rows', 'ties': []}]})

    def run_case(self, case, intent):
        steps, calls = {}, []

        def complete(node, payload):
            calls.append(node)
            content = intent if node == 'intent' else 'SELECT winner_name,winner_rank FROM matches LIMIT 1'
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}

        for node in validate_v3(GRAPH_V3):
            output, _ = run_step(node, case, 'test', [steps[k] for k in node['from']], complete)
            steps[node['id']] = {**node, 'output': output}
        return steps, calls


if __name__ == '__main__':
    unittest.main()
