"""Pass an unmodified sort cue to one final direction decision."""

import re
import sqlite3

from experiment import column_values, columns_for, step_node
from sort_direction_canvas import GRAPH, fallback, single_target, sort_step, validate_sort

REPLACEMENTS = {
    'sort_intent': 'sort_select_v3',
    'sort_probe': 'sort_verify_v3',
    'sort_direction': 'sort_finalize_v3',
}
GRAPH_V3 = {**GRAPH, 'nodes': [
    {**node, 'kind': REPLACEMENTS.get(node['kind'], node['kind'])} for node in GRAPH['nodes']
]}
SELECT = (
    'Identify one clearly requested sort and select one candidate field from the supplied schema. '
    'Quote the exact contiguous sort wording including its direction cue, and name the quantity '
    'being ordered in the question. Keep the quote verbatim. Direct means the field stores the '
    'same quantity; similar means a plausible substitute represents it differently. Prefer a '
    'unique direct candidate. Return {"targets":[{"cue":"verbatim quote","requested_quantity":'
    '"quantity in the question","table":"exact identifier","column":"exact identifier",'
    '"match":"direct|similar"}]}. Return {"targets":[]} for an ambiguous field or sort, '
    'a sort over an aggregate, or multiple sorting keys. Do not convert the direction, add a '
    'direction field, or generate SQL. This step only selects information for the next node.'
)
FINALIZE = (
    'Choose the final direction of the verified stored column. Start with the verbatim sort '
    'wording, then explain the candidate column meaning based on its identifier, schema, and '
    'observed values. Distinguish the requested concept from how the database represents it. '
    'For example, a store opened in a later calendar year has fewer elapsed years since opening '
    'at a shared snapshot. Thus descending opening year requires ascending elapsed years. '
    'When a field clearly stores elapsed duration for the same entity and event, and values '
    'support that meaning, a common snapshot is a reasonable default for a single table unless '
    'there are signs of different observation dates. A concrete reference year is unnecessary '
    'to decide relative ordering. Return {"targets":[{"column_meaning":"what the field measures",'
    '"relation":"same|reverse|unknown","direction":"ASC|DESC|unknown","reason":"evidence"}]}. '
    'direction is the final SQL direction for the candidate column, after applying the relationship '
    'once. Use unknown if field meaning, compatibility, or question direction remains ambiguous. '
    'Do not select another field or output SQL.'
)
DIRECTION_WORDS = {
    'ASC': re.compile(r'\b(?:ascending|(?:low|lowest|smallest) to (?:high|highest|largest)|'
                      r'young(?:est)? to old(?:est)?|earli(?:er|est) to lat(?:er|est))\b', re.I),
    'DESC': re.compile(r'\b(?:descending|(?:high|highest|largest) to (?:low|lowest|smallest)|'
                       r'old(?:est)? to young(?:est)?|lat(?:er|est) to earli(?:er|est))\b', re.I),
}


def is_sort_v3(graph):
    return isinstance(graph, dict) and isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') in REPLACEMENTS.values() for node in graph['nodes'])


def validate_sort_v3(graph):
    if not is_sort_v3(graph):
        raise ValueError('需要 v3 的题意、查列和最终方向节点。')
    original = {new: old for old, new in REPLACEMENTS.items()}
    nodes = graph['nodes']
    if any(isinstance(node, dict) and node.get('kind') in REPLACEMENTS for node in nodes):
        raise ValueError('请使用同一版本的排序节点。')
    translated = [
        {**node, 'kind': original[node['kind']]}
        if isinstance(node, dict) and node.get('kind') in original else node
        for node in nodes
    ]
    return [{**node, 'kind': REPLACEMENTS.get(node['kind'], node['kind'])}
            for node in validate_sort({**graph, 'nodes': translated})]


def verify_candidate(case, item):
    match, cue, quantity = (item.get(field) for field in ('match', 'cue', 'requested_quantity'))
    table, column = item.get('table'), item.get('column')
    if (match not in ('direct', 'similar')
            or any(not isinstance(value, str) or not value.strip() for value in (cue, quantity, table, column))
            or cue.strip().casefold() not in case.question.casefold()):
        return fallback('unverified_sort_selection')
    tables = columns_for(case.database)
    actual_table = next((name for name in tables if name.casefold() == table.casefold()), None)
    fields = tables.get(actual_table, {})
    actual_column = next((name for name in fields if name.casefold() == column.casefold()), None)
    if actual_column is None:
        return fallback('column_not_in_current_schema')
    evidence = {'route': match, 'cue': cue, 'requested_quantity': quantity, 'table': actual_table,
                'column': actual_column, 'declared_type': fields[actual_column]}
    if match == 'direct':
        return evidence
    try:
        values = column_values(case.database, actual_table, actual_column, 8)
    except sqlite3.Error:
        return fallback('column_probe_failed')
    evidence['values'] = [(value[:120] if isinstance(value, str) else value, storage, count)
                          for value, storage, count in values if storage in ('integer', 'real', 'text')]
    return evidence if evidence['values'] else fallback('no_usable_column_values')


def sort_step_v3(node, case, model, upstream, complete):
    kind = node['kind']
    if kind == 'sort_select_v3':
        output, call = step_node({**node, 'kind': 'extract', 'hint': SELECT}, case, model, [], complete)
        fields = ('match', 'cue', 'requested_quantity', 'table', 'column')
        return {'targets': [{k: item[k] for k in fields if k in item}
                            for item in output['targets'] if isinstance(item, dict)]}, call
    if kind not in ('sort_verify_v3', 'sort_finalize_v3'):
        return sort_step(node, case, model, upstream, complete)
    previous = upstream[0]['output']
    if kind == 'sort_verify_v3':
        return verify_candidate(case, single_target(previous)), None
    if previous['route'] == 'fallback':
        return {**previous, 'agent_skipped': True}, None
    directions = [direction for direction, words in DIRECTION_WORDS.items() if words.search(previous['cue'])]
    literal = directions[0] if len(directions) == 1 else None
    if previous['route'] == 'direct' and literal:
        return {**previous, 'direction': literal, 'agent_skipped': True}, None
    output, call = step_node({**node, 'kind': 'extract', 'hint': FINALIZE}, case, model,
                             [{'kind': 'lookup', 'output': previous}], complete)
    choice = single_target(output)
    direction, relation = choice.get('direction'), choice.get('relation')
    description = (choice.get('column_meaning'), choice.get('reason'))
    if (direction not in DIRECTION_WORDS or relation not in ('same', 'reverse')
            or any(not isinstance(value, str) or not value.strip() for value in description)
            or (previous['route'] == 'direct' and relation != 'same')
            or (literal and (direction == literal) != (relation == 'same'))):
        return {**fallback('final_direction_uncertain_or_inconsistent'),
                'candidate': previous, 'judgment': choice}, call
    return {**previous, 'direction': direction, 'relation': relation,
            'column_meaning': description[0], 'reason': description[1]}, call
