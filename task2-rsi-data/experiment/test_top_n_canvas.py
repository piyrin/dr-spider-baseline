import unittest

from experiment import Scenario
from top_n_canvas import (GRAPH, INTERACTIVE_GRAPH, original_or_control,
                          top_n_step, validate_top_n)


class TopNCanvasTests(unittest.TestCase):
    def run_canvas(self, case, graph, intent):
        calls, steps = [], {}

        def complete(node_id, payload):
            calls.append((node_id, payload))
            content = intent if node_id == 'intent' else (
                'SELECT winner_name, winner_rank FROM matches WHERE winner_age IS NOT NULL '
                'GROUP BY winner_name, winner_rank ORDER BY MIN(winner_age) LIMIT 5')
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}

        for node in validate_top_n(graph):
            output, _ = top_n_step(node, case, 'test-model', [steps[p] for p in node['from']], complete)
            steps[node['id']] = {**node, 'output': output}
        return steps, calls

    def test_original_unclear_uses_baseline_prompt_in_batch_and_asks_in_interactive(self):
        case = Scenario.from_id('SQL_NonDB_number-00054-post')
        intent = ('{"targets":[{"table":"matches","fields":["winner_name","winner_rank"],'
                  '"order_column":"winner_age","direction":"ASC","n":5,"grain":"ambiguous",'
                  '"person_key":"winner_id","cue":"5 youngest winners"}]}')
        batch, calls = self.run_canvas(case, GRAPH, intent)
        self.assertEqual(batch['policy']['output']['route'], 'fallback')
        self.assertNotIn('Query plan', calls[-1][1]['messages'][-1]['content'])
        session, calls = self.run_canvas(case, INTERACTIVE_GRAPH, intent)
        self.assertEqual(session['execute']['output']['status'], 'clarification')
        self.assertEqual([node for node, _ in calls], ['intent'])

    def test_explicit_pair_plan_applies_grouping_before_limit(self):
        case = original_or_control('top-n-pair-post')
        intent = ('{"targets":[{"table":"matches","fields":["winner_name","winner_rank"],'
                  '"order_column":"winner_age","direction":"ASC","n":5,"grain":"tuple",'
                  '"cue":"distinct name-and-rank combinations"}]}')
        steps, calls = self.run_canvas(case, GRAPH, intent)
        self.assertEqual(steps['policy']['output']['route'], 'tuple')
        self.assertIn('winner_name, winner_rank', calls[-1][1]['messages'][-1]['content'])
        self.assertEqual(steps['execute']['output']['rows'][-1], ('Madison Keys', 9))

    def test_llm_assertion_without_verbatim_grain_does_not_add_constraint(self):
        case = Scenario.from_id('SQL_NonDB_number-00054-post')
        intent = ('{"targets":[{"table":"matches","fields":["winner_name","winner_rank"],'
                  '"order_column":"winner_age","direction":"ASC","n":5,"grain":"person",'
                  '"person_key":"winner_id","cue":"5 youngest winners"}]}')
        steps, _ = self.run_canvas(case, GRAPH, intent)
        self.assertEqual(steps['policy']['output']['route'], 'fallback')
        self.assertTrue(steps['policy']['output']['semantic_ambiguity'])

    def test_rejects_bypassing_policy(self):
        graph = {**GRAPH, 'links': [{**link} for link in GRAPH['links']]}
        graph['links'][1]['target'] = 'generate'
        with self.assertRaises(ValueError):
            validate_top_n(graph)


if __name__ == '__main__':
    unittest.main()
