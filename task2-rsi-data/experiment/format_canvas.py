"""Canvas for evidence-gated normalization of a filter literal."""

from contextlib import closing
import json
import re

from experiment import columns_for, content_of, ident, json_object, read_connection, step_node, validate_graph


STEM = 'NLQ_column_value-00205'
EXAMPLES = [STEM + '-pre', STEM + '-post']
TYPES = {
    'format_extract': 'extract',
    'format_exact': 'lookup',
    'format_normalize': 'plan',
    'format_generate': 'generate',
    'execute': 'execute',
}
KINDS = tuple(TYPES)[:-1]
GRAPH = {
    'nodes': [{'id': node_id, 'kind': kind} for node_id, kind in zip(
        ('extract', 'exact', 'normalize', 'generate', 'execute'), TYPES)],
    'links': [{'source': a, 'target': b} for a, b in (
        ('extract', 'exact'), ('exact', 'normalize'), ('exact', 'generate'),
        ('normalize', 'generate'), ('generate', 'execute'))],
}

EXTRACT_HINT = ('Identify one explicit textual equality filter. Use the exact term as written in '
                'the question, including case and whitespace, with operator "=". Return zero targets '
                'if there is no such unique filter. The requested output field is not a filter.')
NORMALIZE_SYSTEM = ('Check whether the unique SQLite value is a formatting variant of the quoted '
                    'filter term in the current question. Compare case and whitespace only. '
                    'Reject if the term, column or comparison is unsupported. Return only JSON '
                    'with one boolean key accept. Do not invent or change a value.')


def is_format(graph):
    return isinstance(graph, dict) and isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') in KINDS for node in graph['nodes'])


def validate_format(graph):
    if not isinstance(graph.get('nodes'), list) or not isinstance(graph.get('links'), list):
        raise ValueError('需要筛选值流程的节点和连线。')
    nodes = graph['nodes']
    if len(nodes) != len(TYPES) or any(
        not isinstance(node, dict) or node.get('kind') not in TYPES
        or node.get('hint') or node.get('probe') or not isinstance(node.get('id'), str)
        for node in nodes
    ):
        raise ValueError('筛选值流程需要五个固定职责的节点。')
    by_kind = {node['kind']: node['id'] for node in nodes}
    if set(by_kind) != set(TYPES) or len(set(by_kind.values())) != len(TYPES):
        raise ValueError('筛选值节点的类型和 ID 必须唯一。')
    expected_ids = {node['id']: by_kind[node['kind']] for node in GRAPH['nodes']}
    expected = {(expected_ids[edge['source']], expected_ids[edge['target']]) for edge in GRAPH['links']}
    mapped = {**graph, 'nodes': [{**node, 'kind': TYPES[node['kind']]} for node in nodes]}
    ordered = validate_graph(mapped)
    if {(edge['source'], edge['target']) for edge in graph['links']} != expected:
        raise ValueError('请连接精确匹配分支、归一化分支和 SQL 执行。')
    kinds_by_id = {node['id']: node['kind'] for node in nodes}
    return [{**node, 'kind': kinds_by_id[node['id']]} for node in ordered]


def format_key(value):
    return ' '.join(value.casefold().split()) if isinstance(value, str) else None


def filter_target(case, extraction):
    targets = extraction.get('targets', [])
    if len(targets) != 1 or not isinstance(targets[0], dict):
        return None
    target = targets[0]
    term, table, column = (target.get(key) for key in ('term', 'table', 'column'))
    if (not all(isinstance(value, str) for value in (term, table, column))
            or not format_key(term) or len(term) > 200
            or not re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', case.question)
            or target.get('operator') not in ('=', '==', 'eq')):
        return None
    schema = columns_for(case.database)
    resolved = [(t, c) for t, fields in schema.items() if t.casefold() == table.casefold()
                for c in fields if c.casefold() == column.casefold()]
    if len(resolved) != 1:
        return None
    return {'table': resolved[0][0], 'column': resolved[0][1], 'term': term}


def find_values(database, target, normalized=False):
    table, column = (ident(target[key]) for key in ('table', 'column'))
    expression = f'format_key({column})' if normalized else column
    term = format_key(target['term']) if normalized else target['term']
    with closing(read_connection(database)) as db:
        if normalized:
            db.create_function('format_key', 1, format_key, deterministic=True)
        rows = db.execute(f'SELECT DISTINCT {column} COLLATE BINARY FROM {table} '
                          f"WHERE typeof({column}) = 'text' AND {expression} COLLATE BINARY = ? LIMIT 2",
                          (term,)).fetchall()
    return [value for (value,) in rows]


def review_candidate(node, case, model, target, candidate, complete):
    user = json.dumps({'question': case.question, 'filter': target, 'stored_value': candidate}, ensure_ascii=False)
    payload = {'model': model, 'stream': False, 'messages': [
        {'role': 'system', 'content': NORMALIZE_SYSTEM}, {'role': 'user', 'content': user}]}
    response = complete(node['id'], payload)
    call = {'request': payload, 'response': response, 'usage': response.get('usage'),
            'model': response.get('model'), 'fingerprint': response.get('system_fingerprint')}
    try:
        accepted = json_object(content_of(response)).get('accept') is True
    except (IndexError, KeyError, TypeError, ValueError) as error:
        call['format_error'] = str(error)
        accepted = False
    return accepted, call


def format_step(node, case, model, upstream, complete):
    kind = node['kind']
    evidence = {step['kind']: step['output'] for step in upstream}
    if kind == 'format_extract':
        return step_node({**node, 'kind': 'extract', 'hint': EXTRACT_HINT}, case, model, [], complete)
    if kind == 'format_exact':
        target = filter_target(case, evidence['format_extract'])
        if target is None:
            return {'status': 'unresolved', 'target': None, 'value': None}, None
        values = find_values(case.database, target)
        return {'status': 'exact' if values else 'miss', 'target': target,
                'value': values[0] if values else None}, None
    if kind == 'format_normalize':
        exact = evidence['format_exact']
        if exact['status'] != 'miss':
            return {'status': 'skipped', 'reason': exact['status'], 'value': None}, None
        target = exact['target']
        values = find_values(case.database, target, normalized=True)
        if len(values) != 1:
            return {'status': 'ambiguous' if values else 'no_match', 'candidates': values, 'value': None}, None
        accepted, call = review_candidate(node, case, model, target, values[0], complete)
        return {'status': 'normalized' if accepted else 'agent_rejected', 'candidates': values,
                'value': values[0] if accepted else None}, call
    if kind == 'format_generate':
        exact, normalized = (evidence[key] for key in ('format_exact', 'format_normalize'))
        if exact['status'] == 'exact':
            route, value = 'exact', exact['value']
        elif normalized['status'] == 'normalized':
            route, value = 'normalized', normalized['value']
        else:
            route, value = 'fallback', None
        previous = []
        if value is not None:
            target = exact['target']
            hint = (f"Verified knowledge: in {target['table']}.{target['column']}, the exact stored "
                    f"text corresponding to {target['term']!r} is {value!r}. "
                    'Use the stored text for that equality filter.')
            previous.append({'kind': 'plan', 'output': hint})
        output, call = step_node({**node, 'kind': 'generate'}, case, model, previous, complete)
        return {**output, 'route': route, 'stored_value': value}, call
    return step_node(node, case, model, upstream, complete)
