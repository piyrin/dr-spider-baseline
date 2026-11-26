import unittest

from experiment import Scenario
from split_output_canvas import EXAMPLES
from split_output_v2 import explicit_name, split_step_v2


class SplitOutputV2Test(unittest.TestCase):
    def setUp(self):
        self.pre, self.post = map(Scenario.from_id, EXAMPLES)

    def test_explicit_original_recovers_from_empty_extraction(self):
        for case, route, cols in ((self.pre, 'direct', ['Name']),
                                  (self.post, 'components', ['first_name', 'last_name'])):
            with self.subTest(case=case.id):
                result, call = split_step_v2({'kind': 'split_fields_v2'}, case, 'test',
                                             [{'output': {'targets': []}}], None)
                self.assertIsNone(call)
                self.assertEqual((result['route'], result['columns']), (route, cols))

    def test_other_output_requirements_still_fall_through(self):
        for question in ('Return the full name in one column.',
                         'What is the name of the visitor and their membership level?',
                         'What is the first name of the visitor?'):
            case = Scenario('control', question, self.post.database, '')
            self.assertIsNone(explicit_name(case))

    def test_confirmed_output_can_survive_empty_decision(self):
        fields, _ = split_step_v2({'kind': 'split_fields_v2'}, self.post, 'test',
                                  [{'output': {'targets': []}}], None)
        def complete(_, payload):
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"targets":[]}'}}]}
        result, call = split_step_v2({'kind': 'split_decide', 'id': 'decide', 'hint': ''},
                                     self.post, 'test', [{'output': fields}], complete)
        self.assertIsNotNone(call)
        self.assertEqual(result['route'], 'split')
