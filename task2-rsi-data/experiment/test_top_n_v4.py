import json
import unittest

from experiment import Scenario, score
from top_n_v3_cases import fixture_case
from top_n_v4 import GRAPH_V4, run_step, validate_v4


class TopNRuleTests(unittest.TestCase):
    def run_case(self, case, choice):
        steps, calls = {}, []

        def complete(node, payload):
            calls.append(node)
            content = json.dumps({'targets': [choice]}) if node == 'intent' else 'SELECT 1'
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}

        for node in validate_v4(GRAPH_V4):
            output, _ = run_step(node, case, 'test-model', [steps[p] for p in node['from']], complete)
            steps[node['id']] = {**node, 'output': output}
        return steps, calls

    @staticmethod
    def winner_choice(n=5):
        return {'rule': 'event_tuple', 'scope': 'all_rows', 'table': 'matches', 'n': n,
                'display': ['winner_name', 'winner_rank'], 'entity_key': 'winner_id',
                'entity_display': 'winner_name', 'order': 'winner_age', 'direction': 'ASC',
                'grain_evidence': 'across all matches', 'projection_evidence': 'name and rank', 'ties': []}

    def test_event_tuple_supports_both_original_sides_and_uses_question_limit(self):
        for side, n in (('pre', 3), ('post', 5)):
            case = Scenario.from_id(f'SQL_NonDB_number-00054-{side}')
            steps, calls = self.run_case(case, self.winner_choice())
            self.assertEqual(steps['policy']['output']['rule'], 'event_tuple')
            self.assertEqual(steps['policy']['output']['n'], n)
            self.assertTrue(score(case, steps['execute']['output'])['correct'])
            self.assertEqual(calls, ['intent'])

    def test_explicit_entity_scope_disallows_event_default(self):
        anchor = Scenario.from_id('SQL_NonDB_number-00054-post')
        case = Scenario('challenge', 'Find the 5 youngest distinct individual winners across all matches. '
                        'Show name and rank.', anchor.database, anchor.gold_sql)
        steps, calls = self.run_case(case, self.winner_choice())
        self.assertEqual(steps['policy']['output']['route'], 'fallback')
        self.assertEqual(steps['execute']['output']['route'], 'fallback')
        self.assertEqual(calls, ['intent', 'generate'])

    def test_unknown_rule_falls_back_without_clarification(self):
        steps, calls = self.run_case(fixture_case('lap-ambiguity-post'), {'rule': 'unknown'})
        self.assertEqual(steps['execute']['output']['route'], 'fallback')
        self.assertEqual(calls, ['intent', 'generate'])

    def test_plural_display_words_keep_historical_related_question_supported(self):
        case = Scenario.from_id('SQL_NonDB_number-00061-post')
        choice = {**self.winner_choice(), 'projection_evidence': 'names and ranks'}
        steps, calls = self.run_case(case, choice)
        self.assertEqual(calls, ['intent'])
        self.assertTrue(score(case, steps['execute']['output'])['correct'])

    def test_explicit_raw_record_selection_disallows_event_default(self):
        anchor = Scenario.from_id('SQL_NonDB_number-00054-post')
        case = Scenario('raw-check', 'Find the 5 youngest matches across all matches. '
                        'Show name and rank.', anchor.database, anchor.gold_sql)
        steps, calls = self.run_case(case, self.winner_choice())
        self.assertEqual(steps['execute']['output']['route'], 'fallback')
        self.assertEqual(calls, ['intent', 'generate'])

    def test_same_event_rule_works_on_orders_with_different_fields(self):
        original = fixture_case('sale-tuple-post')
        case = Scenario('orders-check', 'Find the top 4 customers across all orders by highest amount. '
                        'Show customer name and category.', original.database, original.gold_sql)
        choice = {'rule': 'event_tuple', 'scope': 'all_rows', 'table': 'orders', 'n': 4,
                  'display': ['customer_name', 'category'], 'entity_key': 'customer_code',
                  'entity_display': 'customer_name', 'order': 'amount', 'direction': 'DESC',
                  'grain_evidence': 'across all orders', 'projection_evidence': 'customer name and category',
                  'ties': []}
        steps, calls = self.run_case(case, choice)
        self.assertEqual(calls, ['intent'])
        self.assertEqual(steps['execute']['output']['rule'], 'event_tuple')
        self.assertTrue(score(case, steps['execute']['output'])['correct'])


if __name__ == '__main__':
    unittest.main()
