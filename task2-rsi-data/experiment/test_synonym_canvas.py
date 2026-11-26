import json
from types import SimpleNamespace
import unittest

from experiment import Scenario
from synonym_canvas import EXAMPLES, GRAPH, synonym_step, validate_synonym


class SynonymCanvasTest(unittest.TestCase):
    def run_case(self, side, term, candidate, reason='full name and abbreviation', operator='='):
        sample = Scenario.from_id(EXAMPLES[side])
        case = SimpleNamespace(database=sample.database, question=sample.question.replace(
            'United States' if side else 'USA', term))
        calls = []

        def complete(node, request):
            calls.append((node, request))
            if node == 'extract':
                answer = ('{"targets":[{"table":"airlines","column":"country",'
                          f'"term":"{term}","operator":"{operator}"}}]}}')
            elif node == 'match':
                answer = json.dumps({'value': candidate, 'reason': reason})
            else:
                answer = "SELECT Airline, Abbreviation FROM Airlines WHERE Country='USA'"
            return {'choices': [{'message': {'content': answer}, 'finish_reason': 'stop'}]}

        steps = {}
        for node in validate_synonym(GRAPH):
            if node['kind'] == 'execute':
                break
            output, _ = synonym_step(node, case, 'test', [steps[p] for p in node['from']], complete)
            steps[node['id']] = {**node, 'output': output}
        return steps, calls

    def test_exact_hit_keeps_baseline_prompt_without_matching_agent(self):
        steps, calls = self.run_case(0, 'USA', None)
        self.assertEqual(steps['generate']['output']['route'], 'exact')
        self.assertEqual([node for node, _ in calls], ['extract', 'generate'])
        self.assertNotIn('Verified synonym', calls[-1][1]['messages'][-1]['content'])

    def test_accepts_confirmed_same_column_alias(self):
        steps, calls = self.run_case(1, 'United States', 'USA')
        self.assertEqual(steps['generate']['output']['route'], 'synonym')
        self.assertEqual(steps['verify']['output']['mapping']['stored_value'], 'USA')
        self.assertIn('Verified synonym', calls[-1][1]['messages'][-1]['content'])

    def test_rejects_unknown_value_or_abstention(self):
        for term, value in [('United States', 'US'), ('Canada', None)]:
            with self.subTest(term=term):
                steps, calls = self.run_case(1, term, value)
                self.assertEqual(steps['generate']['output']['route'], 'fallback')
                self.assertNotIn('Verified synonym', calls[-1][1]['messages'][-1]['content'])

    def test_preserves_negation_operator(self):
        steps, _ = self.run_case(1, 'United States', 'USA', operator='!=')
        self.assertEqual(steps['verify']['output']['mapping']['operator'], '!=')

    def test_requires_verification_edge(self):
        with self.assertRaises(ValueError):
            validate_synonym({**GRAPH, 'links': GRAPH['links'][:-2] + GRAPH['links'][-1:]})
