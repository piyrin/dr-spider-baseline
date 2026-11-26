"""Ground all filters and the counted entity before generating a single-table count."""

import re

import sqlparse

from experiment import as_json, column_values, columns_for, execute_sql, step_node

STEM = 'NLQ_keyword_carrier-00248'
EXAMPLES = [STEM + '-pre', STEM + '-post']
IDS = ('intent', 'verify', 'generate', 'execute')
KINDS = ('filter_count_intent', 'filter_count_verify', 'filter_count_generate', 'filter_count_execute')
GRAPH = {
    'nodes': [{'id': node, 'kind': kind} for node, kind in zip(IDS, KINDS)],
    'links': [{'source': head, 'target': tail} for head, tail in zip(IDS, IDS[1:])],
}
INTENT = (
    'For a question asking for a count of distinct real-world entities from one SQLite table, '
    'extract ALL required conjunctive text equality filters AND the counted entity. '
    'Return JSON {"targets":[{"table":"exact table","column":"exact column",'
    '"term":"verbatim words from the question","kind":"name|handedness"}],'
    '"count":{"table":"exact table","column":"exact entity identifier column",'
    '"term":"verbatim cue about the counted entity","unit":"entity"}}. '
    'Use an entity ID if available. A competition referred to by an acronym and "this tournament" '
    'still constrains the tournament name. For a right- or left-handed condition, use the exact '
    'hand description from the question. Preserve every independent filter and use the table '
    'that stores both the entities and filters. Only handle a single total, positive text '
    'equalities joined by AND, and a single table. If unsupported or uncertain about the column '
    'or whether an entity count is requested, return {"targets":[],"count":null}. Do not write SQL.'
)

IDENTIFIER = r'(?:"(?:[^"]|"")+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_]\w*)'
FIELD = rf'(?:{IDENTIFIER}\s*\.\s*)?{IDENTIFIER}'
LITERAL = r"'(?:[^']|'')*'"
HEAD = re.compile(
    rf'SELECT\s+COUNT\s*\(\s*DISTINCT\s+(?P<count>{FIELD})\s*\)'
    rf'(?:\s+(?:AS\s+)?{IDENTIFIER})?\s+FROM\s+(?P<table>{IDENTIFIER})'
    rf'(?:\s+(?:AS\s+)?(?P<alias>{IDENTIFIER}))?\s+WHERE\s+(?P<where>.+)',
    re.I | re.S,
)
CONDITION = re.compile(
    rf"(?P<open>\(\s*)?(?P<column>{FIELD})\s*=\s*(?P<value>{LITERAL})"
    r"(?(open)\s*\))\s*(?P<and>\bAND\b\s*|$)", re.I,
)
HAND = re.compile(r'(left|right)(?:[\s-]*hand(?:ed)?)?', re.I)


def is_filter_count(graph):
    return isinstance(graph, dict) and isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') in KINDS for node in graph['nodes'])


def validate_filter_count(graph):
    nodes, links = graph.get('nodes'), graph.get('links')
    if not isinstance(nodes, list) or len(nodes) != len(KINDS) or not isinstance(links, list):
        raise ValueError('筛选与计数编排需要四个职责节点。')
    ids = {}
    for node in nodes:
        node_id, kind = node.get('id'), node.get('kind')
        if (not isinstance(node_id, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,48}', node_id)
                or node_id in ids.values() or kind not in KINDS or kind in ids
                or node.get('hint') or node.get('probe')):
            raise ValueError('节点 ID、类型或配置有误。')
        ids[kind] = node_id
    order = [ids[kind] for kind in KINDS]
    if sorted((link.get('source', ''), link.get('target', '')) for link in links) != sorted(zip(order, order[1:])):
        raise ValueError('请依次连接题意解析、筛选核验、SQL 生成和检查执行。')
    return [{'id': node_id, 'kind': kind, 'hint': '', 'probe': False,
             'from': order[max(0, i-1):i]} for i, (node_id, kind) in enumerate(zip(order, KINDS))]


def term_in_question(question, term):
    return isinstance(term, str) and bool(term.strip()) and term.strip().casefold() in question.casefold()


def resolve_value(database, table, column, term, kind):
    values = column_values(database, table, column, 3001)
    if len(values) > 3000:
        return None
    options = [value for value, typ, _ in values if typ == 'text']
    normalized = term.strip().casefold()
    exact = [value for value in options if value.casefold() == normalized]
    if exact:
        return (exact[0], 'exact') if len(exact) == 1 else None
    if kind == 'handedness' and 'hand' in column.casefold() and HAND.fullmatch(normalized):
        if not options or not {value.casefold() for value in options} <= {'l', 'r'}:
            return None
        matches = [value for value in options if value.casefold() == normalized[0]]
        rule = 'handedness_code'
    elif kind == 'name' and re.fullmatch(r'[A-Z]{2,8}', term.strip()):
        token = re.compile(rf'(?<!\w){re.escape(normalized)}(?!\w)', re.I)
        matches = [value for value in options if token.search(value)]
        rule = 'unique_acronym_token'
    else:
        return None
    return (matches[0], rule) if len(matches) == 1 else None


def verify_intent(case, result):
    targets, count = result.get('targets'), result.get('count')
    if not isinstance(count, dict) or count.get('unit') != 'entity' or not term_in_question(case.question, count.get('term')):
        return {'route': 'fallback', 'reason': 'unverified_entity_count'}
    if not isinstance(targets, list) or not 1 <= len(targets) <= 5:
        return {'route': 'fallback', 'reason': 'unverified_filters'}
    tables = {table.casefold(): (table, {col.casefold(): col for col in cols})
              for table, cols in columns_for(case.database).items()}
    table, column = count.get('table'), count.get('column')
    if not isinstance(table, str) or not isinstance(column, str) or table.casefold() not in tables:
        return {'route': 'fallback', 'reason': 'unknown_count_field'}
    actual_table, columns = tables[table.casefold()]
    if column.casefold() not in columns or not re.search(r'(?:_id|_name|Id|Name)$', column, re.I):
        return {'route': 'fallback', 'reason': 'unsupported_count_identifier'}
    filters = []
    for target in targets:
        if not isinstance(target, dict):
            return {'route': 'fallback', 'reason': 'unverified_filter'}
        source, col, kind, term = (target.get(key) for key in ('table', 'column', 'kind', 'term'))
        if (not isinstance(source, str) or source.casefold() != table.casefold()
                or not isinstance(col, str) or col.casefold() not in columns or kind not in ('name', 'handedness')
                or not term_in_question(case.question, term)):
            return {'route': 'fallback', 'reason': 'unverified_filter'}
        col = columns[col.casefold()]
        value = resolve_value(case.database, actual_table, col, term, kind)
        if value is None or any(item['column'] == col for item in filters):
            return {'route': 'fallback', 'reason': 'unresolved_or_duplicate_filter', 'column': col, 'term': term}
        filters.append({'column': col, 'term': term, 'value': value[0], 'evidence': value[1]})
    return {'route': 'grounded', 'table': actual_table, 'filters': filters,
            'count': {'column': columns[column.casefold()], 'unit': 'distinct_entity', 'term': count['term']}}


def plain(identifier):
    return identifier.strip().strip('"`[]').casefold()


def verified_sql(sql, contract):
    clean = sqlparse.format(sql, strip_comments=True).strip().removesuffix(';').strip()
    match = HEAD.fullmatch(clean)
    if match is None or plain(match['table']) != contract['table'].casefold():
        return False
    qualifiers = {plain(match['table']), plain(match['alias'] or '')}

    def resolved(field):
        parts = [plain(value) for value in field.split('.')]
        return parts[-1] if len(parts) == 1 or len(parts) == 2 and parts[0] in qualifiers else None

    if resolved(match['count']) != contract['count']['column'].casefold():
        return False
    expected = {(item['column'].casefold(), item['value']) for item in contract['filters']}
    conditions = []
    remaining = match['where'].strip()
    while remaining:
        found = CONDITION.match(remaining)
        if found is None:
            return False
        conditions.append((resolved(found['column']), found['value'][1:-1].replace("''", "'")))
        remaining = remaining[found.end():]
        if found['and'].strip() and not remaining:
            return False
    return len(conditions) == len(expected) and set(conditions) == expected


def filter_count_step(node, case, model, upstream, complete):
    kind = node['kind']
    previous = upstream[0]['output'] if upstream else None
    if kind == 'filter_count_intent':
        return step_node({**node, 'kind': 'extract', 'hint': INTENT}, case, model, [], complete)
    if kind == 'filter_count_verify':
        return verify_intent(case, previous), None
    if kind == 'filter_count_generate':
        context = []
        if previous['route'] == 'grounded':
            plan = ('Use this verified query plan. Return a direct single-table SELECT with one '
                    'COUNT(DISTINCT entity identifier) and exactly the verified equalities joined by AND. '
                    'Preserve the verified stored text values, using single-quoted SQLite literals. '
                    + as_json(previous))
            context = [{'kind': 'plan', 'output': plan}]
        result, call = step_node({**node, 'kind': 'generate'}, case, model, context, complete)
        return {**result, 'contract': previous}, call
    sql, contract = previous.get('sql'), previous['contract']
    if not sql:
        return {'status': previous.get('status', 'generation_error'), 'reason': previous.get('reason')}, None
    if contract['route'] == 'grounded' and not verified_sql(sql, contract):
        return {'status': 'contract_mismatch', 'sql': sql,
                'reason': 'Expected one distinct entity count and all verified equalities.'}, None
    return {**execute_sql(case.database, sql),
            'contract_check': 'match' if contract['route'] == 'grounded' else 'not_applicable'}, None
