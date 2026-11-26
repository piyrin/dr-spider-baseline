import unittest

from experiment import Scenario, score
from top_n_original import GRAPH, run_step, validate


class OriginalTopNTests(unittest.TestCase):
    def test_selected_original_uses_verified_tuple_on_both_sides(self):
        for side, n in (('pre', 3), ('post', 5)):
            case = Scenario.from_id(f'SQL_NonDB_number-00054-{side}')
            outputs = {}
            calls = []

            def model(node, payload):
                calls.append((node, payload))
                content = ('{"targets":[]}' if node == 'intent' else
                           f'SELECT winner_name,winner_rank FROM matches WHERE winner_age IS NOT NULL '
                           f'GROUP BY winner_name,winner_rank ORDER BY MIN(winner_age) LIMIT {n}')
                return {'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}

            for node in validate(GRAPH):
                value, _ = run_step(node, case, 'test-model', [outputs[key] for key in node['from']], model)
                outputs[node['id']] = {**node, 'output': value}
            self.assertEqual(outputs['policy']['output']['route'], 'tuple')
            self.assertEqual(outputs['policy']['output']['n'], n)
            self.assertIn('winner_name, winner_rank', calls[-1][1]['messages'][-1]['content'])
            self.assertTrue(score(case, outputs['execute']['output'])['correct'])

    def test_rule_is_limited_to_original_pair(self):
        case = Scenario.from_id('SQL_NonDB_number-00061-post')
        with self.assertRaises(ValueError):
            validate(GRAPH, case)

    def test_execution_replaces_duplicate_rows_with_contract_query(self):
        case = Scenario.from_id('SQL_NonDB_number-00054-post')
        steps = {}

        def model(node, payload):
            answer = ('{"targets":[]}' if node == 'intent' else 'SELECT winner_name,winner_rank FROM matches '
                      'WHERE winner_age IS NOT NULL ORDER BY winner_age LIMIT 5')
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': answer}}]}

        for node in validate(GRAPH, case):
            output, _ = run_step(node, case, 'test-model', [steps[key] for key in node['from']], model)
            steps[node['id']] = {**node, 'output': output}
        result = steps['execute']['output']
        self.assertEqual(result['policy_check'], 'policy_query_used')
        self.assertIsNotNone(result['agent_sql'])
        self.assertEqual([row[1] for row in result['rows']], [17, 24, 16, 12, 9])


if __name__ == '__main__':
    unittest.main()
