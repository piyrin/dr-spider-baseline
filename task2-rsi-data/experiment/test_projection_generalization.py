import unittest

from projection_generalization import find_name


class ProjectionGeneralizationTest(unittest.TestCase):
    schema = {'Highschooler': {'name': 'TEXT', 'grade': 'INT', 'ID': 'INT'},
              'Teacher': {'Name': 'TEXT', 'Age': 'INT'}, 'Country': {'Name': 'TEXT'}}

    def test_current_schema_disambiguates_entity_and_normalized_output(self):
        self.assertEqual(find_name('Who are all high school students in grade ten?', self.schema),
                         ('normalized', 'Highschooler.name'))
        self.assertEqual(find_name('List the names of teachers in ascending order of age.', self.schema),
                         ('direct', 'Teacher.Name'))
        self.assertEqual(find_name('What countries have the largest population?', self.schema),
                         ('normalized', 'Country.Name'))
        self.assertEqual(find_name("Which teachers have the name 'Jo'?", self.schema),
                         ('normalized', 'Teacher.Name'))

    def test_returns_no_field_for_additional_outputs_or_ambiguous_schema(self):
        for question in ('List names and IDs of students.', 'Which teachers and what are their ages?',
                         'Which teachers? Give their age.', 'Which students have friends and are liked?',
                         'How many teachers live here?', "Which teacher's age is 21?"):
            self.assertEqual(find_name(question, self.schema), ('fallback', None), question)
        self.assertEqual(find_name('Which students are in grade ten?',
                                   self.schema | {'Student': {'name': 'TEXT'}}), ('fallback', None))
