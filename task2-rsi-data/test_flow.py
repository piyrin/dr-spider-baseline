import sqlite3
import unittest

from flow import CASES, execute_query, run_agent_step, run_flow


class FlowTest(unittest.TestCase):
    def test_course_sql_stage_requires_both_table_agent_outputs(self):
        def complete(system, content):
            self.fail('An incomplete handoff should not call the model')

        with self.assertRaises(ValueError):
            run_agent_step('multi-agent', 'sql', CASES['multi-agent']['question'], complete,
                           [{'agent': 'singer', 'output': '保留所有歌手'}])

    def test_single_table_counts_french_singers(self):
        def complete(system, content):
            self.assertIn('CREATE TABLE "singer"', content)
            self.assertNotIn('singer_in_concert', content)
            return 'SELECT COUNT(*) FROM singer WHERE Country = \'France\';', {}

        result = run_flow('single-table', CASES['single-table']['question'], complete)
        self.assertEqual(result['rows'], [[4]])
        self.assertTrue(result['matches_reference'])
        self.assertEqual(len(result['steps']), 1)

    def test_multiple_agents_feed_the_sql_agent(self):
        def complete(system, content):
            if 'singer →' in content:
                self.assertIn('保留全部歌手', content)
                self.assertIn('用 Singer_ID 关联', content)
                return CASES['multi-agent']['reference_sql'], {}
            if 'CREATE TABLE "singer_in_concert"' in content:
                return '用 Singer_ID 关联', {}
            return '保留全部歌手', {}

        result = run_flow('multi-agent', CASES['multi-agent']['question'], complete)
        self.assertEqual([step['agent'] for step in result['steps']],
                         ['singer', 'singer_in_concert', 'sql'])
        self.assertIn(['Joe Sharp', 0], result['rows'])
        self.assertTrue(result['matches_reference'])

    def test_single_table_cannot_read_the_other_table(self):
        with self.assertRaises(sqlite3.DatabaseError):
            execute_query('SELECT COUNT(*) FROM singer_in_concert', ('singer',))

    def test_multi_agent_checks_extra_output_columns(self):
        def complete(system, content):
            if 'singer →' in content:
                self.assertIn('Do not include internal IDs unless asked', system)
                extra_id = CASES['multi-agent']['reference_sql'].replace('SELECT s.Name', 'SELECT s.Singer_ID, s.Name')
                return extra_id, {}
            return 'Singer_ID is the key.', {}

        result = run_flow('multi-agent', CASES['multi-agent']['question'], complete)
        self.assertFalse(result['matches_reference'])
        self.assertIsNone(result['error'])

    def test_sqlite_rejects_non_query(self):
        with self.assertRaises(ValueError):
            execute_query('ATTACH DATABASE \'another.sqlite\' AS other', ('singer',))


if __name__ == '__main__':
    unittest.main()
