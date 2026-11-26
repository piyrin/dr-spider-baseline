import unittest

from boolean_canvas import EXAMPLES
from boolean_evidence_canvas import GRAPH, evidence_step, inspect_candidates, validate_evidence
from experiment import GRAPHS, Scenario, step_node, validate_graph


class BooleanEvidenceTests(unittest.TestCase):
    def test_mixed_candidates_keep_the_uncertain_boolean_column(self):
        case = Scenario.from_id('DB_DBcontent_equivalence-00038-post')
        output = inspect_candidates(case, {'targets': [
            {'table': 'Pets', 'column': 'is_dog', 'term': 'dog'},
            {'table': 'Student', 'column': 'Sex', 'term': 'F'},
        ]})
        self.assertEqual(output['route'], 'evidence')
        self.assertEqual([e['column'] for e in output['evidence']], ['is_dog'])
        self.assertEqual({item['value'] for item in output['evidence'][0]['examples']}, {'T', 'F'})

    def test_opposite_meaning_is_passed_as_observed_values_without_a_mapping(self):
        case = Scenario.from_id('DB_DBcontent_equivalence-00140-post')
        output = inspect_candidates(case, {'targets': [
            {'table': 'players', 'column': 'is_right_handed', 'term': 'left handed'},
        ]})
        self.assertEqual(output['route'], 'evidence')
        self.assertEqual(output['evidence'][0]['column'], 'is_right_handed')
        self.assertEqual({item['value'] for item in output['evidence'][0]['examples']}, {'T', 'F'})
        self.assertNotIn('matched_value', output['evidence'][0])

    def test_clear_literal_or_empty_evidence_reuses_baseline_prompt(self):
        case = Scenario.from_id(EXAMPLES[0])
        found = inspect_candidates(case, {'targets': [
            {'table': 'ship', 'column': 'disposition_of_ship', 'term': 'Captured'}]})
        self.assertEqual(found['route'], 'fallback')
        self.assertFalse(found['evidence'])
        self.assertEqual(inspect_candidates(case, {'targets': []})['route'], 'fallback')
        requests = []

        def complete(_, request):
            requests.append(request)
            return {'model': 'fixture', 'choices': [
                {'finish_reason': 'stop', 'message': {'content': 'SELECT 1'}}]}

        generate = validate_evidence(GRAPH)[2]
        evidence_step(generate, case, 'fixture', [{'output': found}], complete)
        step_node(validate_graph(GRAPHS['baseline'])[0], case, 'fixture', [], complete)
        self.assertEqual(requests[0], requests[1])


if __name__ == '__main__':
    unittest.main()
