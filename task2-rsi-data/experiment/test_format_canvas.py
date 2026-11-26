import json
import sqlite3
from unittest import TestCase
from unittest.mock import patch

from experiment import Scenario
from format_canvas import EXAMPLES, GRAPH, find_values, format_step, validate_format
from run_full_evaluation import make_payload


class FormatCanvasTest(TestCase):
    def run_graph(self, sample, term, accept=True):
        case = Scenario.from_id(sample)
        steps = {}
        calls = {}

        def complete(node, payload):
            calls[node] = payload
            sql = "SELECT Package_Option FROM TV_Channel WHERE series_name = 'Sky Radio'"
            content = {
                'extract': json.dumps({'targets': [{'table': 'TV_Channel', 'column': 'series_name',
                                                    'term': term, 'operator': '='}]}),
                'normalize': json.dumps({'accept': accept}),
                'generate': sql,
            }[node]
            return {'model': 'test', 'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}

        for node in validate_format(GRAPH):
            output, _ = format_step(node, case, 'test', [steps[i] for i in node['from']], complete)
            steps[node['id']] = {**node, 'output': output}
        return steps, calls

    def test_pre_exact_hit_skips_normalization_agent(self):
        steps, calls = self.run_graph(EXAMPLES[0], 'Sky Radio')
        self.assertEqual(steps['exact']['output']['status'], 'exact')
        self.assertEqual(steps['normalize']['output']['status'], 'skipped')
        self.assertEqual(set(calls), {'extract', 'generate'})
        self.assertEqual(steps['execute']['output']['rows'], [('Sky Famiglia',)])

    def test_post_unique_normalized_candidate_uses_stored_value(self):
        steps, calls = self.run_graph(EXAMPLES[1], 'Sky radio')
        self.assertEqual(steps['exact']['output']['status'], 'miss')
        self.assertEqual(steps['normalize']['output']['status'], 'normalized')
        self.assertIn('Sky Radio', calls['generate']['messages'][-1]['content'])

    def test_no_match_and_ambiguous_matches_have_unaugmented_generation(self):
        for values, status in (([], 'no_match'), (['Sky Radio', 'SKY RADIO'], 'ambiguous')):
            with self.subTest(status=status), patch('format_canvas.find_values', side_effect=[[], values]):
                steps, calls = self.run_graph(EXAMPLES[1], 'Sky radio')
                self.assertEqual(steps['normalize']['output']['status'], status)
                self.assertEqual(set(calls), {'extract', 'generate'})
                case = Scenario.from_id(EXAMPLES[1])
                self.assertEqual(calls['generate'], make_payload(
                    'test', {'database': case.database, 'question': case.question}))

    def test_normalized_lookup_counts_distinct_original_spellings(self):
        db = sqlite3.connect(':memory:')
        db.execute('CREATE TABLE channel (name TEXT COLLATE NOCASE)')
        db.executemany('INSERT INTO channel VALUES (?)', [('Sky Radio',), ('Sky Radio',), ('SKY RADIO',)])
        target = {'table': 'channel', 'column': 'name', 'term': 'sky  radio'}
        with patch('format_canvas.read_connection', return_value=db):
            self.assertCountEqual(find_values('unused', target, normalized=True),
                                  ['Sky Radio', 'SKY RADIO'])

    def test_rejected_candidate_has_unaugmented_generation(self):
        steps, calls = self.run_graph(EXAMPLES[1], 'Sky radio', accept=False)
        self.assertEqual(steps['normalize']['output']['status'], 'agent_rejected')
        self.assertNotIn('Verified knowledge', calls['generate']['messages'][-1]['content'])
