import json
import unittest

from experiment import Scenario, score
from sort_direction_canvas import EXAMPLES
from sort_direction_v3 import GRAPH_V3, sort_step_v3, validate_sort_v3


class SortDirectionV3Tests(unittest.TestCase):
    def run_canvas(self, side, decision):
        case = Scenario.from_id(EXAMPLES[side])
        requests = {}
        steps = {}
        column = 'Year_of_Founded' if side == 0 else 'year_of_existence'

        def complete(node, payload):
            requests[node] = payload['messages'][-1]['content']
            if node == 'intent':
                content = json.dumps({'targets': [{
                    'match': 'direct' if side == 0 else 'similar',
                    'table': 'orchestra', 'column': column,
                    'cue': 'descending order of years in which they were founded',
                    'requested_quantity': 'founding year',
                    'direction': 'ASC'
                }]})
            elif node == 'direction':
                content = json.dumps({'targets': [decision]})
            else:
                direction = 'DESC' if side == 0 else 'ASC'
                content = f'SELECT Record_Company FROM orchestra ORDER BY {column} {direction}'
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}

        for node in validate_sort_v3(GRAPH_V3):
            output, _ = sort_step_v3(node, case, 'test', [steps[parent] for parent in node['from']], complete)
            steps[node['id']] = {**node, 'output': output}
        return case, requests, {key: step['output'] for key, step in steps.items()}

    def test_raw_intent_does_not_forward_model_generated_direction(self):
        _, requests, out = self.run_canvas(1, {
            'direction': 'ASC', 'relation': 'reverse', 'column_meaning': 'elapsed years',
            'reason': 'A later founding year implies a shorter elapsed duration.'})
        self.assertNotIn('direction', out['intent']['targets'][0])
        self.assertNotIn('direction', out['probe'])
        self.assertNotIn('"direction":', requests['direction'])
        self.assertIn('descending order of years', requests['direction'])
        self.assertIn('ASC', requests['generate'])
        self.assertEqual(out['direction']['direction'], 'ASC')

    def test_direct_match_uses_verbatim_direction_without_an_extra_call(self):
        case, requests, out = self.run_canvas(0, None)
        self.assertEqual(out['direction']['direction'], 'DESC')
        self.assertNotIn('direction', requests)
        self.assertTrue(score(case, out['execute'])['correct'])

    def test_inconsistent_direction_falls_back_without_rewriting(self):
        _, requests, out = self.run_canvas(1, {
            'direction': 'DESC', 'relation': 'reverse', 'column_meaning': 'elapsed years',
            'reason': 'A duration reverses the ordering.'})
        self.assertEqual(out['direction']['route'], 'fallback')
        self.assertNotIn('Query plan', requests['generate'])

    def test_unknown_field_meaning_preserves_fallback(self):
        _, requests, out = self.run_canvas(1, {
            'direction': 'unknown', 'relation': 'unknown', 'column_meaning': 'unknown',
            'reason': 'Candidate meaning is ambiguous.'})
        self.assertEqual(out['direction']['route'], 'fallback')
        self.assertNotIn('Query plan', requests['generate'])
