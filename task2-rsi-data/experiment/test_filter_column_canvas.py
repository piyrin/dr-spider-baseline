import unittest

from experiment import Scenario
from filter_column_canvas import GRAPH, STEM, probe_columns, validate_columns


class FilterColumnTests(unittest.TestCase):
    def test_original_in_each_side_resolves_the_full_name(self):
        for side, term in [('pre', 'General Motors'), ('post', 'Honda')]:
            with self.subTest(side=side):
                case = Scenario.from_id(f'{STEM}-{side}')
                result = probe_columns(case, {'targets': [{
                    'term': term,
                    'candidates': [
                        {'table': 'car_makers', 'column': 'Maker'},
                        {'table': 'car_makers', 'column': 'FullName'},
                    ],
                }]})
                self.assertEqual(result['chosen']['column'], 'FullName')
                self.assertEqual(result['chosen']['value'], term)
                self.assertEqual(result['matches'][0]['normalized'], ['honda'] if side == 'post' else [])

    def test_requires_multiple_valid_columns_and_verbatim_term(self):
        case = Scenario.from_id(f'{STEM}-post')
        for term, second_column in [('Ford', 'Maker'), ('Honda', 'not_a_column')]:
            result = probe_columns(case, {'targets': [{'term': term, 'candidates': [
                {'table': 'car_makers', 'column': 'FullName'},
                {'table': 'car_makers', 'column': second_column},
            ]}]})
            self.assertEqual(result['route'], 'fallback')

    def test_graph_requires_all_three_links(self):
        self.assertEqual(len(validate_columns(GRAPH)), 4)
        with self.assertRaises(ValueError):
            validate_columns({**GRAPH, 'links': GRAPH['links'][:-1]})
