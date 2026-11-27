import unittest
from dataclasses import replace

from experiment import Scenario, execute_sql, score
from filter_column_v2 import GRAPH_V2, column_step_v2, inspect_draft, validate_column_v2


class FilterColumnDraftTests(unittest.TestCase):
    def test_post_patches_only_the_honda_filter(self):
        case = Scenario.from_id('SQL_DB_text-00048-post')
        sql = ("SELECT DISTINCT ml.Model FROM model_list AS ml JOIN car_makers AS cm ON cm.Id=ml.Maker "
               "JOIN car_names cn ON cn.Model=ml.Model JOIN cars_data cd ON cd.Id=cn.MakeId "
               "WHERE cm.\"Maker\" = 'Honda' OR cd.Weight > 3500")
        result = inspect_draft(case, sql)
        self.assertEqual(result['route'], 'auto')
        self.assertEqual(result['options'][0]['sql'], sql.replace('cm."Maker"', 'cm."FullName"'))
        self.assertTrue(score(case, execute_sql(case.database, result['options'][0]['sql']))['correct'])

    def test_pre_keeps_the_existing_exact_match(self):
        case = Scenario.from_id('SQL_DB_text-00048-pre')
        sql = "SELECT m.FullName FROM car_makers m WHERE m.FullName = 'General Motors'"
        self.assertEqual(inspect_draft(case, sql)['route'], 'keep')

    def test_join_predicate_and_unqualified_comparisons_are_unchanged(self):
        case = Scenario.from_id('SQL_DB_text-00048-post')
        for sql in ("SELECT cm.FullName FROM car_makers cm WHERE Maker = 'Honda'",
                    "SELECT cm.FullName FROM car_makers cm JOIN model_list ml ON cm.Maker = 'Honda'",
                    "SELECT cm.FullName FROM car_makers cm UNION ALL "
                    "SELECT cm.FullName FROM car_makers cm WHERE cm.Maker = 'Honda'"):
            self.assertEqual(inspect_draft(case, sql)['route'], 'keep')

    def test_validates_the_four_node_canvas(self):
        self.assertEqual([n['id'] for n in validate_column_v2(GRAPH_V2)],
                         ['draft', 'inspect', 'revise', 'execute'])

    def test_only_the_ambiguous_path_asks_a_reviewer_and_verifies_its_quote(self):
        case = replace(Scenario.from_id('SQL_DB_text-00048-post'),
                       question='Which records are associated with Honda?')
        sql = "SELECT cm.FullName FROM car_makers cm WHERE cm.Maker = 'Honda'"
        check = inspect_draft(case, sql)
        self.assertEqual(check['route'], 'review')
        revise = validate_column_v2(GRAPH_V2)[2]

        def complete(_node, _payload):
            return {'choices': [{'finish_reason': 'stop', 'message': {'content':
                    '{"choice":0,"quote":"invented Honda cue","reason":"claimed exact evidence"}'}}]}

        evidence = [{'output': {'draft': {'sql': sql}, **check}}]
        result, call = column_step_v2(revise, case, 'test', evidence, complete)
        self.assertIsNotNone(call)
        self.assertEqual(result['final']['sql'], sql)

        def confirm(_node, _payload):
            return {'choices': [{'finish_reason': 'stop', 'message': {'content':
                    '{"choice":0,"quote":"associated with Honda","reason":"official name is supported"}'}}]}

        result, _ = column_step_v2(revise, case, 'test', evidence, confirm)
        self.assertEqual(result['final']['sql'], sql.replace('cm.Maker', 'cm.FullName'))
