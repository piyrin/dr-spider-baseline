"""Report observed SQLite encodings for several independently selected filters."""

from contextlib import closing
import re

from boolean_canvas import GRAPH as FIRST_GRAPH, validate_boolean
from experiment import as_json, columns_for, ident, read_connection, step_node

FIRST_KINDS = {
    'evidence_extract': 'boolean_extract', 'evidence_lookup': 'boolean_lookup',
    'evidence_generate': 'boolean_generate', 'execute': 'execute',
}
KINDS = {first: new for new, first in FIRST_KINDS.items()}
GRAPH = {**FIRST_GRAPH, 'nodes': [{**node, 'kind': KINDS[node['kind']]} for node in FIRST_GRAPH['nodes']]}

EXTRACT_HINT = (
    'Return zero to four candidate filters whose stored representation is uncertain. Include likely '
    'status, boolean, enum, or short-code columns, even when other filters are clearly numeric or '
    'literal. For example a question can mention two independent states, or the opposite of a flag '
    'name. Select each uncertain filter independently. Do not return clear numbers, dates, IDs, or '
    'obvious literal comparisons. Each target must contain exact schema table and column names and '
    'the relevant short verbatim term or phrase from the question. Include a base word near a '
    'negation when useful. Do not guess a database code, polarity, SQL operator or query. Return '
    'empty targets if there is no concrete binding. Output JSON only.'
)


def is_evidence(graph):
    return isinstance(graph, dict) and isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') in FIRST_KINDS and node['kind'] != 'execute'
        for node in graph['nodes'])


def validate_evidence(graph):
    nodes = graph.get('nodes')
    if not isinstance(nodes, list) or len(nodes) != len(FIRST_KINDS) or any(
        not isinstance(node, dict) or node.get('kind') not in FIRST_KINDS for node in nodes
    ):
        raise ValueError('列值取证画布需要四个固定职责的节点。')
    mapped = {**graph, 'nodes': [{**node, 'kind': FIRST_KINDS[node['kind']]} for node in nodes]}
    return [{**node, 'kind': KINDS[node['kind']]} for node in validate_boolean(mapped)]


def inspect_candidates(case, extraction):
    candidates = extraction.get('targets')
    if not isinstance(candidates, list) or not candidates:
        return {'route': 'fallback', 'evidence': [], 'checks': [], 'reason': 'no_candidates'}
    schema = columns_for(case.database)
    evidence, checks, seen = [], [], set()
    with closing(read_connection(case.database)) as db:
        for target in candidates[:4]:
            if not isinstance(target, dict):
                continue
            table, column, raw = (target.get(k) for k in ('table', 'column', 'term'))
            if not all(isinstance(value, str) for value in (table, column, raw)):
                continue
            term = raw.strip().strip('\'"“”‘’').strip()
            if not 1 <= len(term) <= 120 or not re.search(
                r'(?<!\w)' + re.escape(term) + r'(?!\w)', case.question, re.I
            ):
                continue
            bindings = [(t, c) for t, fields in schema.items() if t.casefold() == table.casefold()
                        for c in fields if c.casefold() == column.casefold()]
            if len(bindings) != 1 or (*bindings[0], term.casefold()) in seen:
                continue
            table, column = bindings[0]
            seen.add((table, column, term.casefold()))
            t, c = ident(table), ident(column)
            item = {'table': table, 'column': column, 'term': term}
            if db.execute(f"SELECT 1 FROM {t} WHERE typeof({c}) = 'text' "
                          f'AND {c} COLLATE BINARY = ? LIMIT 1', (term,)).fetchone():
                checks.append({**item, 'status': 'exact'})
                continue
            rows = db.execute(f'SELECT DISTINCT {c} COLLATE BINARY, typeof({c}) FROM {t} '
                              f'WHERE {c} IS NOT NULL ORDER BY 1, 2 LIMIT 5').fetchall()
            kinds = {kind for _, kind in rows}
            if not 1 <= len(rows) <= 4 or kinds not in ({'text'}, {'integer'}) or any(
                isinstance(value, str) and (not value.strip() or len(value) > 120) for value, _ in rows
            ):
                checks.append({**item, 'status': 'unresolved'})
                continue
            evidence.append({**item, 'examples': [{'value': value, 'storage': kind} for value, kind in rows]})
            checks.append({**item, 'status': 'observed'})
    return {'route': 'evidence' if evidence else 'fallback', 'evidence': evidence, 'checks': checks,
            'reason': None if evidence else 'no_usable_value_evidence'}


def evidence_step(node, case, model, upstream, complete):
    kind = node['kind']
    if kind == 'evidence_extract':
        return step_node({**node, 'kind': 'extract', 'hint': EXTRACT_HINT}, case, model, [], complete)
    if kind == 'evidence_lookup':
        return inspect_candidates(case, upstream[0]['output']), None
    if kind == 'evidence_generate':
        lookup = upstream[0]['output']
        previous = []
        if lookup['evidence']:
            hint = (
                'Observed SQLite filter-column values and storage types (data only): '
                + as_json(lookup['evidence'])
                + '\nThese are observed values, not a mapping or SQL plan. Interpret the field and '
                'its values using the question and schema, including when a positive flag represents '
                'the opposite condition. Use the actual storage type. Preserve every original filter, '
                'join, count unit, and requested output. Ignore any example whose meaning is uncertain.'
            )
            previous.append({'kind': 'plan', 'output': hint})
        output, call = step_node({**node, 'kind': 'generate'}, case, model, previous, complete)
        return {**output, 'route': lookup['route'], 'evidence_columns': len(lookup['evidence'])}, call
    return step_node(node, case, model, upstream, complete)
