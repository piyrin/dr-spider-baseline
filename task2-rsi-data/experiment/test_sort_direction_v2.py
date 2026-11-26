import json
import unittest

from experiment import Scenario
from sort_direction_canvas import EXAMPLES, GRAPH
from sort_direction_v2 import GRAPH_V2, sort_step_v2, validate_sort_v2


class SortDirectionMeaningTests(unittest.TestCase):
    def judge(self, result):
        case = Scenario.from_id(EXAMPLES[1])
        probe = {'route': 'similar', 'table': 'orchestra', 'column': 'year_of_existence',
                 'direction': 'DESC', 'values': [(14, 'integer', 3)]}
        node = validate_sort_v2(GRAPH_V2)[2]

        def complete(_, request):
            self.assertIn('year_of_existence', request['messages'][1]['content'])
            self.assertIn('column_meaning', request['messages'][0]['content'])
            content = json.dumps({'targets': [result]})
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}

        return sort_step_v2(node, case, 'test', [{'output': probe}], complete)[0]

    def test_judgment_records_field_meaning_and_converts_direction(self):
        result = self.judge({'requested_quantity': 'founding year', 'column_meaning': 'elapsed age in years',
                             'relation': 'reverse', 'reason': 'Later founding means fewer elapsed years.'})
        self.assertEqual(result['direction'], 'ASC')
        self.assertEqual(result['column_meaning'], 'elapsed age in years')

    def test_missing_field_meaning_falls_back(self):
        result = self.judge({'requested_quantity': 'founding year', 'relation': 'reverse', 'reason': 'Shorter is newer.'})
        self.assertEqual(result['route'], 'fallback')

    def test_explicitly_unknown_relation_falls_back(self):
        result = self.judge({'requested_quantity': 'founding year', 'column_meaning': 'ambiguous numeric value',
                             'relation': 'unknown', 'reason': 'Insufficient context.'})
        self.assertEqual(result['route'], 'fallback')

    def test_v2_routes_are_separate(self):
        self.assertEqual(validate_sort_v2(GRAPH_V2)[2]['kind'], 'sort_meaning_v2')
        with self.assertRaises(ValueError):
            validate_sort_v2(GRAPH)
