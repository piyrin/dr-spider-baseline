import json
import unittest

from experiment import Scenario, score


class CountScopeTests(unittest.TestCase):
    def test_observed_counts_and_true_zero_use_different_routes(self):
        from count_scope_canvas import resolve_scope

        case = Scenario.from_id('SQL_comparison-00133-post')
        target = {
            'parent_table': 'country', 'parent_key': 'Code',
            'detail_table': 'countrylanguage', 'detail_key': 'CountryCode',
            'role': 'both', 'operator': '<', 'threshold': 2,
            'policy': 'observed', 'cue': 'less than 2 languages',
        }
        self.assertEqual(resolve_scope(case, {'targets': [target]})['route'], 'observed')
        self.assertEqual(resolve_scope(case, {'targets': [{**target, 'threshold': 0}]})['route'], 'fallback')
        self.assertEqual(resolve_scope(case, {'targets': [{**target, 'policy': 'unknown'}]})['route'], 'fallback')
        self.assertEqual(resolve_scope(case, {'targets': [{**target, 'detail_key': 'not_a_column'}]})['route'], 'fallback')
        case = Scenario('zero-control', 'List every country and its language count, including zero.',
                        case.database, '')
        self.assertEqual(resolve_scope(case, {'targets': [{**target, 'policy': 'zero', 'role': 'result',
                                                         'cue': 'including zero'}]})['route'], 'zero')
        case = Scenario('qualified-all', 'List all countries with less than 2 languages.',
                        case.database, '')
        self.assertEqual(resolve_scope(case, {'targets': [{**target, 'policy': 'zero', 'role': 'filter',
                                                         'cue': 'all countries'}]})['route'], 'fallback')

    def test_fallback_uses_the_baseline_generation_prompt(self):
        from count_scope_canvas import count_step, GRAPH, validate_count
        from experiment import GRAPHS, step_node, validate_graph

        case = Scenario.from_id('SQL_comparison-00133-pre')
        requests = []

        def complete(_node, payload):
            requests.append(payload)
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': 'SELECT 1'}}]}

        generator = validate_count(GRAPH)[-2]
        count_step(generator, case, 'test-model', [{'output': {'route': 'fallback'}}], complete)
        step_node(validate_graph(GRAPHS['baseline'])[0], case, 'test-model', [], complete)
        self.assertEqual(requests[0], requests[1])

    def test_observed_route_carries_the_verified_constraint_into_generation(self):
        from count_scope_canvas import count_step, GRAPH, validate_count

        case = Scenario.from_id('SQL_comparison-00133-post')
        extraction = json.dumps({'targets': [{
            'parent_table': 'country', 'parent_key': 'Code',
            'detail_table': 'countrylanguage', 'detail_key': 'CountryCode',
            'role': 'both', 'operator': '<', 'threshold': 2,
            'policy': 'observed', 'cue': 'less than 2 languages',
        }]})
        response_sql = ('SELECT c.Name, COUNT(d.Language) FROM country c '
                        'JOIN countrylanguage d ON d.CountryCode=c.Code '
                        'GROUP BY c.Code HAVING COUNT(d.Language) < 2')
        calls = []

        def complete(node, payload):
            calls.append((node, payload['messages'][1]['content']))
            return {'choices': [{'finish_reason': 'stop', 'message': {
                'content': extraction if node == 'intent' else response_sql,
            }}]}

        steps = {}
        for node in validate_count(GRAPH):
            previous = [steps[parent] for parent in node['from']]
            output, _ = count_step(node, case, 'fixture-model', previous, complete)
            steps[node['id']] = {'kind': node['kind'], 'output': output}
        self.assertEqual([node for node, _ in calls], ['intent', 'generate'])
        self.assertEqual(steps['policy']['output']['route'], 'observed')
        self.assertIn('Absence of detail is an unknown observation', calls[1][1])
        self.assertNotIn(case.gold_sql, calls[1][1])
        self.assertTrue(score(case, steps['execute']['output'])['correct'])


if __name__ == '__main__':
    unittest.main()
