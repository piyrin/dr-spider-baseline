"""Resolve a requested sort column using the current schema and candidate values."""

import re
import sqlite3

from experiment import column_values, columns_for, step_node

STEM = 'DB_DBcontent_equivalence-00304'
EXAMPLES = [STEM + '-pre', STEM + '-post']
KINDS = ('sort_intent', 'sort_probe', 'sort_direction', 'sort_generate', 'sort_execute')
IDS = ('intent', 'probe', 'direction', 'generate', 'execute')
GRAPH = {
    'nodes': [{'id': node, 'kind': kind} for node, kind in zip(IDS, KINDS)],
    'links': [{'source': parent, 'target': child} for parent, child in zip(IDS, IDS[1:])],
}
INTENT = (
    'Identify one clearly requested sort key in the question. Quote its exact contiguous question cue '
    'and state its requested direction in terms of the original concept, before adapting to storage. '
    'Use match direct for a schema column that directly represents the same quantity, even if its name '
    'is a synonym. Use match similar when only a plausible substitute with a different representation '
    'exists. Prefer a unique direct column. Return JSON {"targets":[{"match":"direct|similar",'
    '"table":"exact identifier","column":"exact identifier","direction":"ASC|DESC","cue":"verbatim text"}]}. '
    'If the sort is implicit, uses an aggregation, has multiple keys, has no clear direction, or no '
    'single credible column can be identified, return {"targets":[]}. Do not write SQL.'
)
DECISION = (
    'Decide whether the ordering by the requested quantity is preserved or reversed when using the '
    'one candidate field in the supplied evidence. Interpret the question, schema and actual sampled '
    'values together. Use direct temporal relationships only when well supported: an elapsed duration '
    'since an event is inverse to the event date when expressed at a shared reference time. Values '
    'alone cannot establish a relationship; do not infer from a suggestive name or values alone. '
    'Return JSON {"targets":[{"relation":"same|reverse|unknown","reason":"short reason grounded in '
    'the question and the evidence"}]}. Choose unknown if the relationship, units, reference time '
    'or direction is unclear. Do not propose other columns or write SQL.'
)


def is_sort(graph):
    return isinstance(graph, dict) and isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') in KINDS for node in graph['nodes'])


def validate_sort(graph):
    nodes, links = graph.get('nodes'), graph.get('links')
    if not isinstance(nodes, list) or len(nodes) != len(KINDS) or not isinstance(links, list):
        raise ValueError('排序编排需要五个职责节点。')
    kinds, seen = {}, set()
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError('排序节点格式错误。')
        node_id, kind = node.get('id'), node.get('kind')
        if (not isinstance(node_id, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,48}', node_id)
                or node_id in seen or kind not in KINDS or kind in kinds
                or node.get('hint') or node.get('probe')):
            raise ValueError('排序节点 ID、类型或配置有误。')
        seen.add(node_id)
        kinds[kind] = node_id
    order = [kinds[kind] for kind in KINDS]
    edges = [(link.get('source'), link.get('target')) for link in links if isinstance(link, dict)]
    if len(links) != len(order) - 1 or len(edges) != len(links) or any(
        edge not in edges for edge in zip(order, order[1:])
    ):
        raise ValueError('请依次连接题意、查列、方向判断、生成和执行。')
    return [{'id': node_id, 'kind': kind, 'hint': '', 'probe': False, 'from': order[max(0, i-1):i]}
            for i, (node_id, kind) in enumerate(zip(order, KINDS))]


def fallback(reason):
    return {'route': 'fallback', 'reason': reason}


def single_target(output):
    targets = output.get('targets', [])
    return targets[0] if len(targets) == 1 and isinstance(targets[0], dict) else {}


def probe(case, intent):
    match, cue, direction = (intent.get(n) for n in ('match', 'cue', 'direction'))
    table, column = (intent.get(n) for n in ('table', 'column'))
    if (match not in ('direct', 'similar') or direction not in ('ASC', 'DESC')
            or not isinstance(cue, str) or not cue.strip() or cue.strip().casefold() not in case.question.casefold()
            or not isinstance(table, str) or not isinstance(column, str)):
        return fallback('unverified_sort_intent')
    tables = columns_for(case.database)
    actual_table = next((name for name in tables if name.casefold() == table.casefold()), None)
    actual_column = next((name for name in tables.get(actual_table, {})
                          if name.casefold() == column.casefold()), None)
    if actual_column is None:
        return fallback('column_not_in_current_schema')
    evidence = {'route': match, 'table': actual_table, 'column': actual_column, 'cue': cue,
                'direction': direction, 'declared_type': tables[actual_table][actual_column]}
    if match == 'direct':
        return evidence
    try:
        values = column_values(case.database, actual_table, actual_column, 8)
    except sqlite3.Error:
        return fallback('column_probe_failed')
    evidence['values'] = [(value[:120] if isinstance(value, str) else value, storage, count)
                          for value, storage, count in values if storage in ('integer', 'real', 'text')]
    return evidence if evidence['values'] else fallback('no_usable_column_values')


def sort_step(node, case, model, upstream, complete):
    kind = node['kind']
    previous = upstream[0]['output'] if upstream else None
    if kind == 'sort_intent':
        return step_node({**node, 'kind': 'extract', 'hint': INTENT}, case, model, [], complete)
    if kind == 'sort_probe':
        return probe(case, single_target(previous)), None
    if kind == 'sort_direction':
        if previous['route'] != 'similar':
            return {**previous, 'agent_skipped': True}, None
        judgment, call = step_node({**node, 'kind': 'extract', 'hint': DECISION}, case, model,
                                   [{'kind': 'lookup', 'output': previous}], complete)
        decision = single_target(judgment)
        relation, reason = decision.get('relation'), decision.get('reason')
        if relation not in ('same', 'reverse') or not isinstance(reason, str) or not reason.strip():
            return {**fallback('direction_uncertain'), 'candidate': previous, 'judgment': decision}, call
        direction = previous['direction']
        if relation == 'reverse':
            direction = 'ASC' if direction == 'DESC' else 'DESC'
        return {**previous, 'original_direction': previous['direction'], 'direction': direction,
                'relation': relation, 'reason': reason}, call
    if kind == 'sort_generate':
        evidence = []
        if previous['route'] != 'fallback':
            instruction = (f'For the requested sorting use {previous["table"]}.{previous["column"]} '
                           f'in {previous["direction"]} order. Preserve all requested outputs and filters.')
            evidence.append({'kind': 'plan', 'output': instruction})
        output, call = step_node({**node, 'kind': 'generate'}, case, model, evidence, complete)
        return {**output, 'sort_plan': previous}, call
    return step_node({**node, 'kind': 'execute'}, case, model, upstream, complete)
