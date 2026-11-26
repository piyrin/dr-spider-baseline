"""Verify a filter literal across plausible SQLite columns before SQL generation."""

import json
import re

from experiment import columns_for, step_node, validate_graph
from format_canvas import find_values

STEM = 'SQL_DB_text-00048'
EXAMPLES = [STEM + '-pre', STEM + '-post']
KINDS = {
    'column_intent': 'extract',
    'column_probe': 'lookup',
    'column_generate': 'generate',
    'column_execute': 'execute',
}
IDS = ('intent', 'verify', 'generate', 'execute')
GRAPH = {
    'nodes': [{'id': node, 'kind': kind} for node, kind in zip(IDS, KINDS)],
    'links': [{'source': a, 'target': b} for a, b in zip(IDS, IDS[1:])],
}
INTENT = (
    'Identify the requested output, all explicit filters and their logical connective. '
    'For this node propose up to four distinct plausible text columns for one explicitly named '
    'entity or other textual equality filter. Only include columns whose meanings could '
    'reasonably encode that term, such as a full name and short code; omit unrelated columns. '
    'Use exact schema identifiers and a case-sensitive verbatim contiguous term from the question. '
    'Return only JSON {"output":"requested result","conditions":["verbatim filter cues"],'
    '"connective":"AND|OR|single",'
    '"targets":[{"term":"verbatim literal","candidates":[{"table":"schema table","column":"schema column"}]}]}. '
    'Return empty targets unless one explicit filter has at least two plausible columns. Never write SQL.'
)


def is_columns(graph):
    nodes = graph.get('nodes') if isinstance(graph, dict) else None
    return isinstance(nodes, list) and any(
        isinstance(node, dict) and node.get('kind') in KINDS for node in nodes)


def validate_columns(graph):
    nodes, links = graph.get('nodes'), graph.get('links')
    if not isinstance(nodes, list) or len(nodes) != len(KINDS) or not isinstance(links, list):
        raise ValueError('筛选列核验需要四个职责节点。')
    by_kind = {}
    for node in nodes:
        if (not isinstance(node, dict) or node.get('kind') not in KINDS
                or node.get('kind') in by_kind or node.get('hint') or node.get('probe')):
            raise ValueError('筛选列核验节点类型或配置错误。')
        by_kind[node['kind']] = node.get('id')
    ids = [by_kind[kind] for kind in KINDS]
    expected = list(zip(ids, ids[1:]))
    if len(links) != len(expected) or any(
        not any(isinstance(link, dict) and (link.get('source'), link.get('target')) == edge
                for link in links) for edge in expected
    ):
        raise ValueError('请依次连接题意、查值、生成和执行。')
    mapped = {**graph, 'nodes': [{**node, 'kind': KINDS[node['kind']]} for node in nodes]}
    kinds_by_id = dict(zip(ids, KINDS))
    return [{**node, 'kind': kinds_by_id[node['id']]} for node in validate_graph(mapped)]


def probe_columns(case, extraction):
    targets = extraction.get('targets', [])
    if not isinstance(targets, list) or len(targets) != 1 or not isinstance(targets[0], dict):
        return {'route': 'fallback', 'reason': 'no_single_text_filter', 'matches': []}
    term, candidates = (targets[0].get(key) for key in ('term', 'candidates'))
    if (not isinstance(term, str) or not 0 < len(term.strip()) <= 200
            or not re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', case.question)
            or not isinstance(candidates, list) or not 2 <= len(candidates) <= 4):
        return {'route': 'fallback', 'reason': 'unverified_filter_or_candidates', 'matches': []}
    schema = columns_for(case.database)
    fields = {(table.casefold(), column.casefold()): (table, column)
              for table, columns in schema.items() for column in columns}
    resolved = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        table, column = (candidate.get(key) for key in ('table', 'column'))
        if isinstance(table, str) and isinstance(column, str):
            field = fields.get((table.casefold(), column.casefold()))
            if field:
                resolved[field] = {'table': field[0], 'column': field[1], 'term': term}
    if len(resolved) < 2:
        return {'route': 'fallback', 'reason': 'too_few_valid_columns', 'matches': []}
    matches = [{**target, 'exact': find_values(case.database, target),
                'normalized': find_values(case.database, target, normalized=True)}
               for target in resolved.values()]
    exact = [{**item, 'value': value} for item in matches for value in item['exact']]
    if len(exact) == 1:
        return {'route': 'unique_exact', 'term': term, 'chosen': exact[0], 'matches': matches}
    if any(item['normalized'] for item in matches):
        return {'route': 'candidates', 'term': term, 'chosen': None, 'matches': matches}
    return {'route': 'fallback', 'reason': 'no_stored_match', 'matches': matches}


def column_step(node, case, model, upstream, complete):
    kind = node['kind']
    mapped = {**node, 'kind': KINDS[kind]}
    if kind == 'column_intent':
        return step_node({**mapped, 'hint': INTENT}, case, model, [], complete)
    if kind == 'column_probe':
        return probe_columns(case, upstream[0]['output']), None
    if kind == 'column_execute':
        return step_node(mapped, case, model, upstream, complete)
    checked = upstream[0]['output']
    plans = []
    if checked['route'] != 'fallback':
        evidence = [{key: item[key] for key in ('table', 'column', 'exact', 'normalized')}
                    for item in checked['matches']]
        hint = ('Verified SQLite evidence for the question term ' + repr(checked['term']) + ': '
                + json.dumps(evidence, ensure_ascii=False)
                + '. Choose the column whose meaning matches the question. Prefer an exact match '
                'over a format-only match when it fits the requested attribute. Preserve all other '
                'predicates, their AND/OR relationships and the requested output and deduplication. '
                'Use the original question to decide which rows each branch can draw from.')
        plans.append({'kind': 'plan', 'output': hint})
    output, call = step_node(mapped, case, model, plans, complete)
    return {**output, 'column_route': checked['route']}, call
