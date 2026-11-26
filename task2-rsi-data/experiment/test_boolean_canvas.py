import unittest

from boolean_canvas import EXAMPLES, GRAPH, boolean_step, encoding_pair, resolve_encoding, validate_boolean
from experiment import GRAPHS, Scenario, score, step_node, validate_graph


class BooleanCanvasTests(unittest.TestCase):
    def setUp(self):
        self.pre, self.post = map(Scenario.from_id, EXAMPLES)

    def target(self, column, term='Captured', truth=True):
        return {'targets': [{'table': 'ship', 'column': column, 'term': term,
                             'operator': '=', 'truth': truth}]}

    def test_explicit_text_value_wins(self):
        result = resolve_encoding(self.pre, self.target('disposition_of_ship'))
        self.assertEqual((result['status'], result['value'], result['storage']), ('exact', 'Captured', 'text'))

    def test_actual_boolean_type_wins_and_counts_stay_out(self):
        result = resolve_encoding(self.post, self.target('is_captured'))
        self.assertEqual((result['status'], result['value'], result['storage']), ('boolean', 'T', 'text'))
        self.assertEqual(result['observed'], [{'value': 'F', 'storage': 'text'}, {'value': 'T', 'storage': 'text'}])
        self.assertNotIn('count', str(result['observed']))

    def test_evidence_cannot_change_polarity_or_accept_unknown_field(self):
        for extraction in (self.target('is_captured', truth=False),
                           self.target('is_captured', 'unknown'),
                           self.target('ship_type')):
            with self.subTest(extraction=extraction):
                self.assertEqual(resolve_encoding(self.post, extraction)['status'], 'fallback')

    def test_graph_uses_two_calls_and_transfers_only_verified_encoding(self):
        nodes = validate_boolean(GRAPH)
        steps, calls = {}, []

        def complete(node, payload):
            calls.append((node, payload))
            if node == 'extract':
                content = '{"targets":[{"table":"ship","column":"is_captured","term":"Captured","operator":"=","truth":true}]}'
            else:
                self.assertIn("is_captured", payload['messages'][-1]['content'])
                self.assertIn("'T'", payload['messages'][-1]['content'])
                self.assertNotIn('Observed database values', payload['messages'][-1]['content'])
                content = "SELECT COUNT(*) FROM ship WHERE is_captured = 'T'"
            return {'model': 'fixture', 'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}

        for node in nodes:
            parents = [steps[p] for p in node['from']]
            output, call = boolean_step(node, self.post, 'fixture', parents, complete)
            steps[node['id']] = {**node, 'output': output, 'call': call}
        self.assertEqual([name for name, _ in calls], ['extract', 'generate'])
        self.assertTrue(score(self.post, steps['execute']['output'])['correct'])

    def test_exact_and_fallback_use_unmodified_baseline_generation(self):
        inputs = []
        def capture(_node, payload):
            inputs.append(payload)
            return {'model': 'fixture', 'choices': [
                {'finish_reason': 'stop', 'message': {'content': 'SELECT 1'}}]}

        base = validate_graph(GRAPHS['baseline'])[0]
        generate = validate_boolean(GRAPH)[2]
        step_node(base, self.pre, 'fixture', [], capture)
        exact = resolve_encoding(self.pre, self.target('disposition_of_ship'))
        for evidence in (exact, {'status': 'fallback', 'reason': 'unknown_encoding'}):
            boolean_step(generate, self.pre, 'fixture', [{'output': evidence}], capture)
        self.assertEqual(inputs, [inputs[0]] * 3)

    def test_encoding_requires_a_known_pair_and_one_storage_type(self):
        for values in ([('A', 'text'), ('B', 'text')], [('T', 'text')],
                       [(0, 'integer'), ('1', 'text')]):
            self.assertIsNone(encoding_pair(values, True))


if __name__ == '__main__':
    unittest.main()
