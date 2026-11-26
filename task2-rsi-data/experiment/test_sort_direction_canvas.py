import json
import unittest

from experiment import Scenario, score
from sort_direction_canvas import EXAMPLES, GRAPH, sort_step, validate_sort


class SortDirectionTests(unittest.TestCase):
    def run_canvas(self, side, match, column, decision=None):
        case = Scenario.from_id(EXAMPLES[side])
        requests = {}
        outputs = {}

        def complete(node, payload):
            requests[node] = payload['messages'][-1]['content']
            if node == 'intent':
                content = json.dumps({'targets': [{
                    'match': match, 'table': 'orchestra', 'column': column, 'direction': 'DESC',
                    'cue': 'descending order of years in which they were founded'}]})
            elif node == 'direction':
                content = json.dumps({'targets': [decision]})
            else:
                order = 'Year_of_Founded DESC' if side == 0 else 'year_of_existence ASC'
                content = f'SELECT Record_Company FROM orchestra ORDER BY {order}'
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}

        for node in validate_sort(GRAPH):
            output, _ = sort_step(node, case, 'test', [outputs[parent] for parent in node['from']], complete)
            outputs[node['id']] = {**node, 'output': output}
        return case, requests, {key: value['output'] for key, value in outputs.items()}

    def test_direct_column_keeps_direction_and_skips_second_agent(self):
        case, requests, out = self.run_canvas(0, 'direct', 'Year_of_Founded')
        self.assertNotIn('direction', requests)
        self.assertNotIn('values', out['probe'])
        self.assertEqual(out['direction']['direction'], 'DESC')
        self.assertTrue(score(case, out['execute'])['correct'])

    def test_similar_column_supplies_actual_values_before_direction_choice(self):
        case, requests, out = self.run_canvas(1, 'similar', 'year_of_existence', {
            'relation': 'reverse', 'reason': 'A duration and its start year move in opposite directions at a fixed reference time.'})
        self.assertTrue(out['probe']['values'])
        self.assertIn('year_of_existence', requests['direction'])
        self.assertIn(str(out['probe']['values'][0][0]), requests['direction'])
        self.assertEqual(out['direction']['direction'], 'ASC')
        self.assertIn('ASC', requests['generate'])
        self.assertTrue(score(case, out['execute'])['correct'])

    def test_uncertain_judgment_uses_original_sql_prompt(self):
        _, requests, out = self.run_canvas(1, 'similar', 'year_of_existence', {
            'relation': 'unknown', 'reason': 'No reliable transformation.'})
        self.assertEqual(out['direction']['route'], 'fallback')
        self.assertNotIn('Query plan', requests['generate'])

    def test_nonexistent_column_skips_judgment_and_uses_original_prompt(self):
        _, requests, out = self.run_canvas(1, 'similar', 'not_a_column')
        self.assertNotIn('direction', requests)
        self.assertEqual(out['direction']['route'], 'fallback')
        self.assertNotIn('Query plan', requests['generate'])


if __name__ == '__main__':
    unittest.main()
