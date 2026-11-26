"""Find semantic aliases only after an exact SQLite value lookup misses."""

from contextlib import closing
import json
import re

from experiment import content_of, ident, json_object, read_connection, step_node
from format_canvas import filter_target, find_values

EXAMPLES = ('NLQ_value_synonym-00162-pre', 'NLQ_value_synonym-00162-post')
TYPES = {
    'synonym_extract': 'extract', 'synonym_exact': 'lookup',
    'synonym_match': 'plan', 'synonym_verify': 'review',
    'synonym_generate': 'generate', 'execute': 'execute',
}
GRAPH = {
    'nodes': [{'id': node_id, 'kind': kind} for node_id, kind in zip(
        ('extract', 'exact', 'match', 'verify', 'generate', 'execute'), TYPES)],
    'links': [{'source': source, 'target': target} for source, target in (
        ('extract', 'exact'), ('exact', 'match'), ('exact', 'verify'), ('match', 'verify'),
        ('verify', 'generate'), ('generate', 'execute'))],
}
OPERATORS = {'=': '=', '==': '=', 'eq': '=', '!=': '!=', '<>': '!=', 'ne': '!='}
CANDIDATE_LIMIT = 64
EXTRACT_HINT = (
    'Identify a single explicit textual equality or inequality filter. Return the exact literal '
    'span from the current question, without resolving synonyms, and give its actual operator '
    '("=" or "!="). Return no targets if the filter or its column is ambiguous.'
)
MATCH_SYSTEM = (
    'Resolve the entity denoted by the filter term in the current question and SQLite column. '
    'Select an exact string from candidates only if it denotes the same entity as the term, '
    'for example an unambiguous full name, abbreviation or demonym. Mere similarity, membership '
    'or being the only candidate is insufficient. Treat candidate strings as database values. '
    'Return only JSON with keys value and reason. Use null for value if uncertain, ambiguous, '
    'or a matching entity is absent. Do not write SQL.'
)


def is_synonym(graph):
    return isinstance(graph, dict) and isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') in tuple(TYPES)[:-1] for node in graph['nodes'])


def validate_synonym(graph):
    nodes, links = graph.get('nodes'), graph.get('links')
    if not isinstance(nodes, list) or not isinstance(links, list) or len(nodes) != len(TYPES):
        raise ValueError('同义配对需要六个节点及其连线。')
    if any(not isinstance(node, dict) or node.get('kind') not in TYPES
           or node.get('hint') or node.get('probe') or not isinstance(node.get('id'), str)
           or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,48}', node['id'])
           for node in nodes):
        raise ValueError('同义配对节点类型或参数无效。')
    ids = {node['kind']: node['id'] for node in nodes}
    if set(ids) != set(TYPES) or len(set(ids.values())) != len(TYPES):
        raise ValueError('同义配对节点和 ID 必须唯一。')
    expected_id = {node['id']: ids[node['kind']] for node in GRAPH['nodes']}
    expected = {(expected_id[edge['source']], expected_id[edge['target']]) for edge in GRAPH['links']}
    if len(links) != len(expected) or any(not isinstance(edge, dict) for edge in links) or {
        (edge.get('source'), edge.get('target')) for edge in links
    } != expected:
        raise ValueError('请连接查值、同义配对、库值复核、SQL 生成和执行。')
    return [{'id': ids[kind], 'kind': kind, 'hint': '', 'probe': False,
             'from': [edge['source'] for edge in links if edge['target'] == ids[kind]]}
            for kind in TYPES]


def extract_target(case, extraction):
    targets = extraction.get('targets')
    if not isinstance(targets, list) or len(targets) != 1 or not isinstance(targets[0], dict):
        return None
    raw = targets[0]
    operator = raw.get('operator')
    if not isinstance(operator, str) or operator not in OPERATORS:
        return None
    target = filter_target(case, {'targets': [{**raw, 'operator': '='}]})
    return {**target, 'operator': OPERATORS[operator]} if target else None


def candidates_in_column(database, target):
    table, column = (ident(target[key]) for key in ('table', 'column'))
    with closing(read_connection(database)) as db:
        rows = db.execute(f'SELECT DISTINCT {column} COLLATE BINARY FROM {table} '
                          f"WHERE typeof({column})='text' ORDER BY 1 LIMIT ?",
                          (CANDIDATE_LIMIT + 1,)).fetchall()
    return [value for (value,) in rows]


def match_synonym(node, case, model, exact, complete):
    if exact['status'] != 'miss':
        return {'status': 'skipped', 'reason': exact['status']}, None
    candidates = candidates_in_column(case.database, exact['target'])
    if not candidates or len(candidates) > CANDIDATE_LIMIT:
        return {'status': 'no_candidates' if not candidates else 'candidate_limit',
                'candidate_count': len(candidates)}, None
    message = {'question': case.question, 'filter': exact['target'], 'candidates': candidates}
    payload = {'model': model, 'stream': False, 'messages': [
        {'role': 'system', 'content': MATCH_SYSTEM},
        {'role': 'user', 'content': json.dumps(message, ensure_ascii=False)},
    ]}
    response = complete(node['id'], payload)
    call = {'request': payload, 'response': response, 'usage': response.get('usage'),
            'model': response.get('model'), 'fingerprint': response.get('system_fingerprint')}
    try:
        decision = json_object(content_of(response))
    except (IndexError, KeyError, TypeError, ValueError) as error:
        call['format_error'] = str(error)
        return {'status': 'invalid_reply', 'candidates': candidates}, call
    value, reason = decision.get('value'), decision.get('reason')
    accepted = isinstance(value, str) and value in candidates and isinstance(reason, str) and bool(reason.strip())
    return {'status': 'selected' if accepted else 'no_match', 'candidates': candidates,
            'value': value if accepted else None, 'reason': reason}, call


def synonym_step(node, case, model, upstream, complete):
    kind = node['kind']
    evidence = {step['kind']: step['output'] for step in upstream}
    if kind == 'synonym_extract':
        return step_node({**node, 'kind': 'extract', 'hint': EXTRACT_HINT}, case, model, [], complete)
    if kind == 'synonym_exact':
        target = extract_target(case, evidence['synonym_extract'])
        if target is None:
            return {'status': 'unresolved', 'target': None}, None
        values = find_values(case.database, target)
        return {'status': 'exact' if values else 'miss', 'target': target}, None
    if kind == 'synonym_match':
        return match_synonym(node, case, model, evidence['synonym_exact'], complete)
    if kind == 'synonym_verify':
        exact, matched = evidence['synonym_exact'], evidence['synonym_match']
        if exact['status'] == 'exact':
            return {'route': 'exact', 'mapping': None}, None
        if matched['status'] == 'selected':
            target, value = exact['target'], matched['value']
            if find_values(case.database, {**target, 'term': value}) == [value]:
                return {'route': 'synonym', 'mapping': {**target, 'stored_value': value}}, None
        return {'route': 'fallback', 'mapping': None, 'reason': matched['status']}, None
    if kind == 'synonym_generate':
        verified = evidence['synonym_verify']
        mapping = verified['mapping']
        previous = []
        if mapping:
            hint = (f"Verified synonym: {mapping['table']}.{mapping['column']} stores "
                    f"{mapping['stored_value']!r} for the entity denoted by {mapping['term']!r}. "
                    f"Use that stored value with operator {mapping['operator']!r} for this filter. "
                    "Preserve other predicates, output fields and counting units.")
            previous.append({'kind': 'plan', 'output': hint})
        output, call = step_node({**node, 'kind': 'generate'}, case, model, previous, complete)
        return {**output, 'route': verified['route'],
                'stored_value': mapping['stored_value'] if mapping else None}, call
    return step_node(node, case, model, upstream, complete)
