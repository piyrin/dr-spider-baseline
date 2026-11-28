export const courseCases: { id: string; title: string; pair: string; presets: string[] }[] = [
  { id: 'case1', title: '输出字段', pair: 'NLQ_column_carrier-00499', presets: ['projection', 'projection_v2'] },
  { id: 'case2', title: '筛选值大小写', pair: 'NLQ_column_value-00205', presets: ['filter_format'] },
  { id: 'case3', title: '同义名称', pair: 'NLQ_value_synonym-00162', presets: ['filter_synonym'] },
  { id: 'case4', title: '布尔编码', pair: 'DB_DBcontent_equivalence-00143', presets: ['filter_boolean', 'filter_boolean_evidence'] },
  { id: 'case5', title: '明细缺失与零值', pair: 'SQL_comparison-00133', presets: ['count_scope', 'count_scope_v2', 'count_scope_v3'] },
  { id: 'case6', title: '姓名分列', pair: 'DB_DBcontent_equivalence-00125', presets: ['split_output', 'split_output_v2', 'split_output_v3'] },
  { id: 'case7', title: 'Top N 去重', pair: 'SQL_NonDB_number-00054', presets: ['top_n', 'top_n_interactive', 'top_n_original', 'top_n_v3', 'top_n_v3_interactive', 'top_n_v4'] },
  { id: 'case8', title: '替代列排序', pair: 'DB_DBcontent_equivalence-00304', presets: ['sort_direction', 'sort_meaning_v2', 'sort_direction_v3'] },
  { id: 'case9', title: '筛选列与关联', pair: 'SQL_DB_text-00048', presets: ['filter_column', 'filter_column_v2'] },
  { id: 'case10', title: '条件与去重计数', pair: 'NLQ_keyword_carrier-00248', presets: ['filter_count'] },
];
