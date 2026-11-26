import json
import unittest

from experiment import Scenario
from split_output_canvas import EXAMPLES, GRAPH, check_output, decide, split_step, verify_fields, validate_split


class SplitOutputTest(unittest.TestCase):
    def setUp(self):
        self.pre, self.post = map(Scenario.from_id, EXAMPLES)

    def target(self, *fields, role='output', cue='name'):
        return {'targets': [{'table': 'visitor', 'fields': list(fields), 'kind': 'name',
                             'role': role, 'cue': cue, 'sole_output': True}]}

    def test_same_question_routes_by_current_schema(self):
        self.assertEqual(verify_fields(self.pre, self.target('Name'))['route'], 'direct')
        verified = verify_fields(self.post, self.target('last_name', 'first_name'))
        self.assertEqual(verified['columns'], ['first_name', 'last_name'])
        self.assertEqual(decide(self.post, verified, {'mode': 'split', 'cue': 'name'})['route'], 'split')
        self.assertEqual(verify_fields(self.pre, self.target('first_name', 'last_name'))['route'], 'fallback')

    def test_schema_and_cue_guard(self):
        self.assertEqual(verify_fields(self.post, self.target('first_name', 'ID'))['route'], 'fallback')
        self.assertEqual(verify_fields(self.post, self.target('first_name', 'last_name', cue='fabricated'))['route'],
                         'fallback')
        verified = verify_fields(self.post, self.target('first_name', 'last_name'))
        self.assertEqual(decide(self.post, verified, {'mode': 'display', 'cue': 'name'})['route'], 'fallback')
        self.assertEqual(decide(self.post, verified, {'mode': 'lookup', 'cue': 'name'})['route'], 'fallback')

    def test_filter_only_and_explicit_display(self):
        lookup = Scenario(self.post.id, 'Find a visitor with full name Fernando Gago.', self.post.database, '')
        verified = verify_fields(lookup, self.target('first_name', 'last_name', role='filter', cue='full name'))
        self.assertEqual(decide(lookup, verified, {'mode': 'lookup', 'cue': 'full name'})['route'], 'lookup')
        display = Scenario(self.post.id, 'Return the full name in one column.', self.post.database, '')
        verified = verify_fields(display, self.target('first_name', 'last_name', cue='full name'))
        self.assertEqual(decide(display, verified, {'mode': 'display', 'cue': 'in one column'})['route'], 'display')

    def test_shape_and_graph(self):
        self.assertEqual(len(validate_split(GRAPH)), 6)
        contract = {'route': 'split', 'columns': ['first_name', 'last_name'], 'sole_output': True}
        self.assertEqual(check_output(contract, {'columns': ['first_name', 'last_name']}), 'match')
        self.assertEqual(check_output(contract, {'columns': ['name']}), 'mismatch')
        self.assertEqual(check_output({'route': 'fallback'}, {'columns': ['name']}), 'not_applicable')

    def test_lookup_combines_for_filter_and_keeps_output_separate(self):
        question = 'Return the name of the visitor with full name Fernando Gago.'
        case = Scenario(self.post.id, question, self.post.database, '')
        prompts = {}

        def complete(node_id, payload):
            prompts[node_id] = payload['messages'][-1]['content']
            responses = {
                'intent': json.dumps(self.target('first_name', 'last_name', role='both', cue='full name')),
                'decide': json.dumps({'targets': [{'mode': 'lookup', 'cue': 'full name Fernando Gago'}]}),
                'generate': ("SELECT first_name, last_name FROM visitor "
                             "WHERE first_name || ' ' || last_name = 'Fernando Gago'"),
            }
            return {'choices': [{'message': {'content': responses[node_id]}, 'finish_reason': 'stop'}]}

        steps = {}
        for node in validate_split(GRAPH):
            output, _ = split_step(node, case, 'test-model', [steps[k] for k in node['from']], complete)
            steps[node['id']] = {**node, 'output': output}
        self.assertIn('For matching the name supplied', prompts['generate'])
        self.assertIn('separate in the final projection', prompts['generate'])
        result = steps['execute']['output']
        self.assertEqual(result['rows'], [('Fernando', 'Gago')])
        self.assertEqual(result['output_check'], 'match')
