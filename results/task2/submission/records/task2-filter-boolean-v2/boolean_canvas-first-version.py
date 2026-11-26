"""Course canvas for a filter whose actual SQLite values encode a boolean."""

from contextlib import closing
import re

from experiment import columns_for, ident, read_connection, step_node, validate_graph

STEM = 'DB_DBcontent_equivalence-00143'
EXAMPLES = [STEM + '-pre', STEM + '-post']
TYPES = {
    'boolean_extract': 'extract', 'boolean_lookup': 'lookup',
    'boolean_generate': 'generate', 'execute': 'execute',
}
STEPS = ('extract', 'lookup', 'generate', 'execute')
GRAPH = {
    'nodes': [{'id': name, 'kind': kind} for name, kind in zip(STEPS, TYPES)],
    'links': [{'source': a, 'target': b} for a, b in zip(STEPS, STEPS[1:])],
}
EXTRACT_HINT = (
    'For a single clear equality condition describing an entity status or property, return one '
    'target with table, column, term, operator "=", and truth (JSON true or false). Term must '
    'be the exact unquoted status word or phrase in the question. For a status column with '
    'literal text and for an affirmative boolean flag, represent the positive status with true. '
    'For an explicitly negated affirmative flag use false and keep the status term itself '
    'without negation. When the condition or its column is uncertain, or several conditions '
    'are equally plausible, return zero targets. Do not guess how the value is stored.'
)


def is_boolean(graph):
    return isinstance(graph, dict) and isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') in tuple(TYPES)[:-1]
        for node in graph['nodes'])


def validate_boolean(graph):
    nodes = graph.get('nodes')
    if not isinstance(nodes, list) or len(nodes) != len(TYPES) or any(
        not isinstance(node, dict) or node.get('kind') not in TYPES
        or node.get('hint') or node.get('probe') for node in nodes
    ):
        raise ValueError('布尔编码核验需要四个固定职责的节点。')
    by_kind = {node['kind']: node['id'] for node in nodes}
    if set(by_kind) != set(TYPES):
        raise ValueError('布尔核验节点类型须各出现一次。')
    mapped = {**graph, 'nodes': [{**node, 'kind': TYPES[node['kind']]} for node in nodes]}
    ordered = validate_graph(mapped)
    kinds = [node['kind'] for node in ordered]
    if kinds != list(TYPES.values()) or any(
        node['from'] != ([ordered[i-1]['id']] if i else []) for i, node in enumerate(ordered)
    ):
        raise ValueError('按提取、编码核验、生成和执行的顺序连接。')
    original = {value: key for key, value in TYPES.items()}
    return [{**node, 'kind': original[node['kind']]} for node in ordered]


def flag_matches(column, type_name, term):
    words = re.findall(r'[a-z0-9]+', column.casefold())
    status = re.findall(r'[a-z0-9]+', term.casefold())
    if not words or not status:
        return False
    # Only explicit affirmative names have a safe polarity. Unprefixed bool
    # columns must name the status itself or a status-qualified subject.
    if words[0] in ('is', 'has'):
        words = words[1:]
    elif type_name.casefold() not in ('bool', 'boolean'):
        return False
    if not words or any(word in ('not', 'no', 'non', 'without') for word in words):
        return False
    return words == status or (len(words) == 2 and status == words[:1]
                               and words[1] in ('ship', 'flag', 'status'))


def encoding_pair(observed, truth):
    values = {row[0] for row in observed}
    storage = {row[1] for row in observed}
    if len(storage) != 1 or len(values) != 2:
        return None
    kind = next(iter(storage))
    if kind == 'text':
        by_key = {value.casefold(): value for value in values}
        for false, true in (('f', 't'), ('false', 'true'), ('0', '1')):
            if set(by_key) == {false, true}:
                return by_key[true if truth else false], kind
    if kind == 'integer' and values == {0, 1}:
        return int(truth), kind
    return None


def resolve_encoding(case, extraction):
    targets = extraction.get('targets', [])
    if not isinstance(targets, list) or len(targets) != 1 or not isinstance(targets[0], dict):
        return {'status': 'fallback', 'reason': 'no_unique_target'}
    target = targets[0]
    table, column, raw_term = (target.get(key) for key in ('table', 'column', 'term'))
    truth = target.get('truth')
    if not all(isinstance(s, str) for s in (table, column, raw_term)) or target.get('operator') != '=':
        return {'status': 'fallback', 'reason': 'invalid_target'}
    term = raw_term.strip().strip('\'"“”‘’').strip()
    if not 1 <= len(term) <= 120 or type(truth) is not bool:
        return {'status': 'fallback', 'reason': 'invalid_term_or_truth'}
    occurrences = list(re.finditer(r'(?<!\w)' + re.escape(term) + r'(?!\w)', case.question, re.I))
    negated = [bool(re.search(r'\b(?:not|never|no)\s+(?:(?:been|being|a|an)\s+)?$',
                             case.question[:m.start()], re.I)) for m in occurrences]
    if not negated or any(value != (not truth) for value in negated):
        return {'status': 'fallback', 'reason': 'unverified_term_or_polarity'}
    binding = [(t, c, declared) for t, cols in columns_for(case.database).items()
               if t.casefold() == table.casefold() for c, declared in cols.items()
               if c.casefold() == column.casefold()]
    if len(binding) != 1:
        return {'status': 'fallback', 'reason': 'invalid_schema'}
    table, column, declared = binding[0]
    t, c = ident(table), ident(column)
    details = {'table': table, 'column': column, 'term': term,
               'truth': truth, 'declared_type': declared}
    with closing(read_connection(case.database)) as db:
        if truth and db.execute(
            f"SELECT 1 FROM {t} WHERE typeof({c}) = 'text' AND {c} COLLATE BINARY = ? LIMIT 1",
            (term,),
        ).fetchone():
            return {**details, 'status': 'exact', 'value': term, 'storage': 'text'}
        if not flag_matches(column, declared, term):
            return {**details, 'status': 'fallback', 'reason': 'flag_meaning_unverified'}
        values = db.execute(f'SELECT DISTINCT {c} COLLATE BINARY, typeof({c}) FROM {t} '
                            f'WHERE {c} IS NOT NULL ORDER BY 1, 2 LIMIT 3').fetchall()
    pair = encoding_pair(values, truth)
    observed = [{'value': value, 'storage': storage} for value, storage in values]
    if pair is None:
        return {**details, 'status': 'fallback', 'reason': 'encoding_unverified', 'observed': observed}
    return {**details, 'status': 'boolean', 'value': pair[0], 'storage': pair[1], 'observed': observed}


def boolean_step(node, case, model, upstream, complete):
    kind = node['kind']
    if kind == 'boolean_extract':
        return step_node({**node, 'kind': 'extract', 'hint': EXTRACT_HINT}, case, model, [], complete)
    if kind == 'boolean_lookup':
        return resolve_encoding(case, upstream[0]['output']), None
    if kind == 'boolean_generate':
        evidence = upstream[0]['output']
        previous = []
        if evidence['status'] == 'boolean':
            hint = (f"Verified knowledge: {evidence['table']}.{evidence['column']} stores the "
                    f"matching value for {evidence['term']!r} as {evidence['value']!r} "
                    f"(SQLite storage type {evidence['storage']}). Use that value and type "
                    'for the verified equality condition. Keep the requested output, other filters and aggregation.')
            previous.append({'kind': 'plan', 'output': hint})
        output, call = step_node({**node, 'kind': 'generate'}, case, model, previous, complete)
        return {**output, 'route': evidence['status'], 'stored_value': evidence.get('value')}, call
    return step_node(node, case, model, upstream, complete)
