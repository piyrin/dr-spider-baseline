import json
import unittest

from experiment import Scenario, score
from filter_count_canvas import GRAPH, STEM, filter_count_step, validate_filter_count


def intent(tournament):
    return {
        'targets': [
            {'table': 'matches', 'column': 'tourney_name', 'term': tournament, 'kind': 'name'},
            {'table': 'matches', 'column': 'winner_hand', 'term': 'left-handed', 'kind': 'handedness'},
        ],
        'count': {'table': 'matches', 'column': 'winner_id', 'term': 'won', 'unit': 'entity'},
    }


class FilterCountCanvasTest(unittest.TestCase):
    def setUp(self):
        self.case = Scenario.from_id(STEM + '-post')
        self.sql = ("SELECT COUNT(DISTINCT m.winner_id) FROM matches AS m "
                    "WHERE m.tourney_name = 'WTA Championships' AND m.winner_hand = 'L';")

    def execute(self, plan, sql):
        calls = []

        def complete(node, payload):
            calls.append((node, payload))
            content = json.dumps(plan) if node == 'intent' else sql
            return {'model': 'test', 'choices': [{'finish_reason': 'stop',
                                                  'message': {'content': content}}]}

        steps = []
        for node in validate_filter_count(GRAPH):
            output, call = filter_count_step(node, self.case, 'test', steps[-1:], complete)
            steps.append({**node, 'output': output, 'call': call})
        return steps, calls

    def test_both_grounded_filters_and_count_reach_generator(self):
        steps, calls = self.execute(intent('WTA'), self.sql)
        self.assertEqual([node for node, _ in calls], ['intent', 'generate'])
        evidence = steps[1]['output']
        self.assertEqual([f['value'] for f in evidence['filters']], ['WTA Championships', 'L'])
        self.assertEqual(evidence['count']['column'], 'winner_id')
        prompt = calls[1][1]['messages'][-1]['content']
        for fact in ('WTA Championships', 'winner_hand', 'winner_id', 'distinct'):
            self.assertIn(fact, prompt)
        self.assertEqual(steps[-1]['output']['rows'], [(2,)])
        self.assertTrue(score(self.case, steps[-1]['output'])['correct'])

    def test_rejects_counting_match_rows_and_dropping_a_filter(self):
        drafts = [
            self.sql.replace('DISTINCT m.winner_id', '*'),
            self.sql.replace("m.tourney_name = 'WTA Championships' AND ", ''),
        ]
        for sql in drafts:
            with self.subTest(sql=sql):
                steps, _ = self.execute(intent('WTA'), sql)
                answer = steps[-1]['output']
                self.assertEqual(answer['status'], 'contract_mismatch')
                self.assertNotIn('rows', answer)

    def test_malformed_hint_falls_back_to_original_request(self):
        steps, calls = self.execute(intent('Grand Slam'), self.sql)
        self.assertEqual(steps[1]['output']['route'], 'fallback')
        self.assertNotIn('Query plan', calls[1][1]['messages'][-1]['content'])


if __name__ == '__main__':
    unittest.main()
