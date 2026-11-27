import unittest

from experiment import Scenario, execute_sql, score


class CountScopeSqlTest(unittest.TestCase):
    def test_simple_observed_count_requires_matching_detail(self):
        from count_scope_v3 import verify_sql_scope

        case = Scenario.from_id('SQL_comparison-00133-post')
        decision = {'route': 'observed', 'operator': '<', 'threshold': 2,
                    'parent_table': 'country', 'parent_key': 'Code',
                    'detail_table': 'countrylanguage', 'detail_key': 'CountryCode'}
        sql = ('SELECT c.Name, COUNT(l.Language) FROM country c LEFT JOIN countrylanguage l '
               'ON c.Code=l.CountryCode GROUP BY c.Code HAVING COUNT(l.Language) < 2;')
        result = verify_sql_scope(case, decision, {'sql': sql})
        self.assertEqual(result['check'], 'required_detail')
        self.assertTrue(score(case, execute_sql(case.database, result['sql']))['correct'])
        self.assertEqual(verify_sql_scope(case, decision, {'sql': sql.replace('c.Code=l.CountryCode',
                         'c.Name=l.CountryCode')})['check'], 'unchanged')
        self.assertEqual(verify_sql_scope(case, {'route': 'fallback'}, {'sql': sql})['sql'], sql)

    def test_zero_branch_preserves_global_minimum(self):
        from count_scope_v3 import verify_sql_scope

        case = Scenario.from_id('DB_schema_abbreviation-02606-pre')
        decision = {'route': 'zero', 'operator': '=', 'threshold': 0,
                    'parent_table': 'Highschooler', 'parent_key': 'ID',
                    'detail_table': 'Friend', 'detail_key': 'student_id'}
        sql = ('SELECT MIN(h.grade) FROM "Highschooler" AS h LEFT JOIN "Friend" AS f '
               'ON h."ID" = f."student_id" GROUP BY h."ID" HAVING COUNT(f."friend_id") = 0;')
        result = verify_sql_scope(case, decision, {'sql': sql})
        self.assertEqual(result['check'], 'global_extreme')
        self.assertTrue(score(case, execute_sql(case.database, result['sql']))['correct'])
