import unittest

from experiment import Scenario


class CountScopeV2Test(unittest.TestCase):
    def test_count_upper_bound_can_use_benchmark_scope_without_llm_policy(self):
        from count_scope_v2 import resolve_scope_v2

        case = Scenario.from_id('SQL_comparison-00100-pre')
        target = {'parent_table': 'Courses', 'parent_key': 'course_id',
                  'detail_table': 'Sections', 'detail_key': 'course_id', 'role': 'filter',
                  'operator': '<=', 'threshold': 2, 'policy': 'unknown',
                  'cue': 'courses having at most 2 sections'}
        decision = resolve_scope_v2(case, {'targets': [target]})
        self.assertEqual((decision['route'], decision['basis']), ('observed', 'benchmark_default'))
        for question, changed in (
            ('Which courses have at most 2 sections, including courses with none?', {}),
            ('Which courses have at most 2 sections or are compulsory?', {}),
            (case.question, {'threshold': 3}),
            (case.question, {'parent_key': 'course_name'}),
        ):
            with self.subTest(question=question, change=changed):
                altered = Scenario(case.id, question, case.database, case.gold_sql)
                candidate = {**target, 'cue': 'at most 2 sections', **changed}
                self.assertEqual(resolve_scope_v2(altered, {'targets': [candidate]})['route'], 'fallback')

    def test_explicit_zero_uses_existing_branch(self):
        from count_scope_v2 import resolve_scope_v2

        case = Scenario.from_id('DB_schema_abbreviation-02606-post')
        target = {'parent_table': 'Highschooler', 'parent_key': 'ID',
                  'detail_table': 'Friend', 'detail_key': 'stu_id', 'role': 'filter',
                  'operator': '=', 'threshold': 0, 'policy': 'zero', 'cue': 'no friends'}
        self.assertEqual(resolve_scope_v2(case, {'targets': [target]})['route'], 'zero')
