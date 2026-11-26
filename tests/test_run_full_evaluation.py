import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_full_evaluation import iter_samples, score, make_payload, select_pairs
from summarize_full_evaluation import review_plan, summarize, verify_annotations


class FullEvaluationTests(unittest.TestCase):
    def test_inventory_and_pairing(self):
        samples = list(iter_samples())
        self.assertEqual(len(samples), 30538)
        self.assertEqual(len({s['id'] for s in samples}), len(samples))
        self.assertEqual(len({s['group'] for s in samples}), 17)
        for pre, post in zip(samples[::2], samples[1::2]):
            self.assertEqual((pre['group'], pre['index'], pre['original_id']),
                             (post['group'], post['index'], post['original_id']))
            self.assertEqual((pre['side'], post['side']), ('pre', 'post'))
            if pre['group'].startswith('DB_'):
                self.assertNotEqual(pre['database'], post['database'])
            else:
                self.assertEqual(pre['database'], post['database'])

    def test_scoring_preserves_stage(self):
        sample = next(iter_samples())
        response = {'model': 'gpt-6-sol', 'choices': [{
            'finish_reason': 'stop', 'message': {'content': sample['gold_sql']},
        }]}
        self.assertEqual(score(sample, response)['status'], 'match')
        response['choices'][0]['message']['content'] = 'SELECT no_such_column'
        self.assertEqual(score(sample, response)['status'], 'prediction_execution')
        response['choices'][0]['message']['content'] = None
        self.assertEqual(score(sample, response)['status'], 'prediction_generation')
        bad_gold = {**sample, 'gold_sql': 'SELECT no_such_column'}
        self.assertEqual(score(bad_gold, response)['status'], 'gold_execution')

    def test_stratified_sampling_keeps_both_sides(self):
        samples = list(iter_samples())
        selection = select_pairs(samples, 50, 20261121)
        self.assertEqual(selection, select_pairs(samples, 50, 20261121))
        counts = Counter((s['group'], s['side']) for s in selection)
        self.assertEqual(len(counts), 34)
        self.assertEqual(set(counts.values()), {50})
        self.assertEqual(set(Counter((s['group'], s['index']) for s in selection).values()), {2})

    def test_prompt_does_not_include_reference(self):
        sample = next(iter_samples())
        payload = make_payload('gpt-6-sol', {**sample, 'gold_sql': 'UNIQUE_REFERENCE'})
        self.assertNotIn('UNIQUE_REFERENCE', str(payload))
        self.assertIn(sample['question'], payload['messages'][1]['content'])

    def test_sample_rows_follow_each_tables_ddl(self):
        sample = next(item for item in iter_samples()
                      if item['id'] == 'DB_DBcontent_equivalence-00037-post')
        ordinary = make_payload('gpt-6-sol', sample)
        augmented = make_payload('gpt-6-sol', sample, sample_rows=3)
        baseline = ordinary['messages'][1]['content']
        prompt = augmented['messages'][1]['content']
        self.assertEqual(augmented['messages'][0], ordinary['messages'][0])
        self.assertNotIn('sample rows from', baseline)
        self.assertEqual(prompt.count('sample rows from'), baseline.count('CREATE TABLE'))
        student = prompt.split('sample rows from "Student":')[1].split('*/', 1)[0]
        self.assertIn('SELECT * FROM "Student" LIMIT 3;', student)
        self.assertEqual(sum(line.startswith('[') for line in student.strip().splitlines()), 4)
        self.assertEqual(prompt.split('\nQuestion\n')[1], sample['question'])

    def test_missing_and_paired_outcomes_have_distinct_denominators(self):
        samples = list(iter_samples())[:6]
        records = {s['id']: {'id': s['id'], 'correct': status}
                   for s, status in zip(samples, [True, False, False, True, True])}
        total, group = summarize(samples, records)
        self.assertEqual((total['pre_scored'], total['post_scored']), (3, 2))
        self.assertEqual((group['pre_only'], group['post_only'], group['pair_unscored']), (1, 1, 1))
        self.assertEqual(total['paired_delta_pp'], 0)
        cases = review_plan(samples, records)
        self.assertEqual({case['id'] for case in cases}, {samples[1]['id'], samples[2]['id']})
        with self.assertRaisesRegex(ValueError, 'Annotation coverage'):
            verify_annotations(cases, [])


if __name__ == '__main__':
    unittest.main()
