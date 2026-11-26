import unittest
from dataclasses import replace

from experiment import Scenario, step_node
from projection_canvas import GRAPH, projection_step, validate_projection


class ProjectionCanvasTest(unittest.TestCase):
    def run_projection(self, side, question=None):
        case = Scenario.from_id('NLQ_column_carrier-00499-' + side)
        if question is not None:
            case = replace(case, question=question)
        steps = {}
        payloads = []

        def complete(_, payload):
            payloads.append(payload)
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': 'SELECT name FROM Highschooler'}}]}

        for node in validate_projection(GRAPH):
            upstream = [steps[parent] for parent in node['from']]
            output, _ = projection_step(node, case, 'gpt-6-sol', upstream, complete)
            steps[node['id']] = {**node, 'output': output}
        self.assertEqual(len(payloads), 1)
        return {step['kind']: step for step in steps.values()}, payloads[0], case

    def test_explicit_name_skips_normalization(self):
        steps, payload, _ = self.run_projection('pre')
        self.assertEqual(steps['projection_normalize']['output']['status'], 'skipped')
        self.assertEqual(steps['projection_constraint']['output']['route'], 'direct')
        self.assertIn('Highschooler.name', payload['messages'][-1]['content'])

    def test_who_is_normalized_and_schema_verified(self):
        steps, payload, _ = self.run_projection('post')
        self.assertEqual(steps['projection_constraint']['output']['route'], 'normalized')
        self.assertEqual(steps['projection_recheck']['output']['field'], 'Highschooler.name')
        self.assertIn('Highschooler.name', payload['messages'][-1]['content'])

    def test_unresolved_output_uses_identical_baseline_request(self):
        steps, payload, case = self.run_projection(
            'post', 'What are the names and IDs of all students in grade 10?')
        self.assertEqual(steps['projection_constraint']['output']['route'], 'fallback')
        baseline = {'id': 'generate', 'kind': 'generate', 'hint': '', 'probe': False}
        _, call = step_node(baseline, case, 'gpt-6-sol', [], lambda _, __: {
            'choices': [{'finish_reason': 'stop', 'message': {'content': 'SELECT ID FROM Highschooler'}}]})
        self.assertEqual(payload, call['request'])

    def test_graph_requires_fallback_branches_to_reach_generator(self):
        invalid = {**GRAPH, 'links': GRAPH['links'][:-2] + GRAPH['links'][-1:]}
        with self.assertRaises(ValueError):
            validate_projection(invalid)
