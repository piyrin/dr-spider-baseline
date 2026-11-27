import unittest

from experiment import Scenario
from split_output_canvas import EXAMPLES
from split_output_v3 import GRAPH_V3, ReviewInput, review_step, validate_v3


class SqlReviewV3Test(unittest.TestCase):
    def run_graph(self, review, confirmation=None):
        case = Scenario.from_id(EXAMPLES[1])
        inputs = ReviewInput(case.question, case.database)
        self.assertFalse(hasattr(inputs, 'gold_sql'))
        requests = {}
        draft = 'SELECT first_name FROM visitor'
        responses = {'draft': draft, 'audit': review, 'confirm': confirmation}
        steps = {}

        def complete(node_id, payload):
            requests[node_id] = payload
            self.assertNotIn(case.gold_sql, payload['messages'][-1]['content'])
            return {'choices': [{'finish_reason': 'stop',
                                 'message': {'content': responses[node_id]}}]}

        for node in validate_v3(GRAPH_V3):
            output, call = review_step(node, inputs, 'test', [steps[k] for k in node['from']], complete)
            steps[node['id']] = {**node, 'output': output, 'call': call}
        return steps, requests

    def test_accepts_one_confirmed_read_only_revision(self):
        proposal = '{"action":"revise","dimension":"projection","quote":"name of the visitor","reason":"missing last name","sql":"SELECT first_name, last_name FROM visitor"}'
        steps, requests = self.run_graph(proposal, '{"accept":true,"reason":"localized output change"}')
        self.assertEqual(list(requests), ['draft', 'audit', 'confirm'])
        self.assertEqual(steps['execute']['output']['columns'], ['first_name', 'last_name'])
        self.assertEqual(steps['execute']['output']['revision'], 'accepted')

    def test_keeps_draft_on_false_evidence_and_invalid_sql(self):
        proposals = (
            '{"action":"revise","dimension":"projection","quote":"missing evidence","reason":"change","sql":"SELECT first_name, last_name FROM visitor"}',
            '{"action":"revise","dimension":"projection","quote":"name of the visitor","reason":"change","sql":"SELECT absent_column FROM visitor"}',
        )
        for proposal in proposals:
            with self.subTest(proposal=proposal):
                steps, requests = self.run_graph(proposal)
                self.assertNotIn('confirm', requests)
                self.assertEqual(steps['execute']['output']['columns'], ['first_name'])

    def test_preserves_draft_when_confirmation_rejects(self):
        proposal = '{"action":"revise","dimension":"projection","quote":"name of the visitor","reason":"missing component","sql":"SELECT first_name, last_name FROM visitor"}'
        steps, requests = self.run_graph(proposal, '{"accept":false,"reason":"unsupported assumption"}')
        self.assertIn('confirm', requests)
        self.assertEqual(steps['execute']['output']['revision'], 'rejected')
        self.assertEqual(steps['execute']['output']['columns'], ['first_name'])
