"""Check a generated text filter and revise at most one column reference."""

from contextlib import closing
import re

from sqlparse.sql import Comparison

from experiment import columns_for, execute_sql, ident, read_connection, step_node
from format_canvas import find_values
from iterations.guarded_replay import PREDICATE, context, unquote
from split_output_v3 import ask

KINDS = ('column_draft_v2', 'column_inspect_v2', 'column_revise_v2', 'column_execute_v2')
IDS = ('draft', 'inspect', 'revise', 'execute')
GRAPH_V2 = {
    'nodes': [{'id': id_, 'kind': kind} for id_, kind in zip(IDS, KINDS)],
    'links': [{'source': a, 'target': b} for a, b in zip(IDS, IDS[1:])],
}
NAME_CUE = re.compile(r'\b(?:car maker|manufacturer|maker|full name|named|called)\s*["\']?\s*$', re.I)
REVIEW = (
    'Decide whether a single proposed replacement column expresses the text attribute requested '
    'in the question more precisely than the current column. The literal stays the same, and the '
    'candidate’s exact SQLite hit alone is insufficient. Preserve the current attribute if '
    'the question explicitly requests it, or if the mapping or evidence is ambiguous. Return '
    'only JSON {"choice":null,"quote":"","reason":"..."} to keep, or choose one zero-based index '
    'and quote the contiguous question phrase naming the attribute and value. Never return SQL.'
)


def is_column_v2(graph):
    nodes = graph.get('nodes') if isinstance(graph, dict) else None
    return isinstance(nodes, list) and any(
        isinstance(node, dict) and node.get('kind') in KINDS for node in nodes)


def validate_column_v2(graph):
    nodes, links = graph.get('nodes'), graph.get('links')
    if not isinstance(nodes, list) or len(nodes) != len(KINDS) or not isinstance(links, list):
        raise ValueError('筛选列修订需要四个职责节点。')
    by_kind = {}
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError('筛选列修订节点格式错误。')
        kind, id_ = node.get('kind'), node.get('id')
        if (kind not in KINDS or kind in by_kind or not isinstance(id_, str)
                or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,48}', id_)
                or id_ in by_kind.values() or node.get('hint') or node.get('probe')):
            raise ValueError('筛选列修订节点类型、ID 或配置有误。')
        by_kind[kind] = id_
    ids = [by_kind[kind] for kind in KINDS]
    expected = list(zip(ids, ids[1:]))
    if len(links) != len(expected) or any(
        not any(isinstance(l, dict) and (l.get('source'), l.get('target')) == edge
                for l in links) for edge in expected
    ):
        raise ValueError('请依次连接初稿、核验、修订和执行。')
    return [{'id': id_, 'kind': kind, 'hint': '', 'probe': False, 'from': ids[max(0, i-1):i]}
            for i, (id_, kind) in enumerate(zip(ids, KINDS))]


def where_comparisons(where, offset):
    if any(token.normalized in ('NOT', 'XOR') for token in where.tokens):
        return
    for token in where.tokens:
        if isinstance(token, Comparison) and (match := PREDICATE.fullmatch(str(token))):
            yield match, offset
        offset += len(token.value)


def column_options(case, sql, match, offset, schema, tables):
    alias, col, op, literal = match.group('alias', 'column', 'op', 'literal')
    if not alias or unquote(alias) not in tables or op != '=' or not literal.startswith("'"):
        return []
    term = literal[1:-1].replace("''", "'")
    cue = re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', case.question)
    if len(term.strip()) < 3 or not cue:
        return []
    table = tables[unquote(alias)]
    fields = schema[table]
    col = next((name for name in fields if name.casefold() == unquote(col)), None)
    if col is None:
        return []
    ref_table, ref_column = ident(table), ident(col)
    with closing(read_connection(case.database)) as db:
        if db.execute(f'SELECT 1 FROM {ref_table} WHERE {ref_column} = ? LIMIT 1', (term,)).fetchone():
            return []
    start, end = match.span('column')
    old_token = match['column']
    candidates = []
    source = {'table': table, 'column': col, 'term': term}
    normalized = find_values(case.database, source, normalized=True)
    for name, dtype in fields.items():
        if name == col or not any(t in dtype.upper() for t in ('CHAR', 'TEXT', 'CLOB')):
            continue
        target = {**source, 'column': name}
        if not find_values(case.database, target):
            continue
        replacement = ident(name) if old_token[0] in '"`[' or not re.fullmatch(r'[A-Za-z_]\w*', name) else name
        patched = sql[:offset + start] + replacement + sql[offset + end:]
        name_role = re.sub(r'[^a-z]', '', name.casefold()) == 'fullname'
        linked = False
        if len(normalized) == 1 and name_role and NAME_CUE.search(case.question[:cue.start()]):
            with closing(read_connection(case.database)) as db:
                linked = bool(db.execute(
                    f'SELECT 1 FROM {ref_table} WHERE {ref_column} COLLATE BINARY = ? '
                    f'AND {ident(name)} COLLATE BINARY = ? LIMIT 1', (normalized[0], term)).fetchone())
        candidates.append({'table': table, 'source': col, 'target': name, 'term': term,
                           'source_normalized': normalized, 'same_row_full_name': linked,
                           'sql': patched})
    return candidates


def inspect_draft(case, sql):
    if not sql:
        return {'route': 'keep', 'reason': 'no_draft', 'options': []}
    schema = columns_for(case.database)
    parsed = context(sql, schema)
    if not parsed or execute_sql(case.database, 'EXPLAIN QUERY PLAN ' + sql)['status'] != 'executed':
        return {'route': 'keep', 'reason': 'unsupported_or_invalid_draft', 'options': []}
    (where, offset), tables = parsed
    if any(token.normalized.split()[0] in {'UNION', 'INTERSECT', 'EXCEPT'}
           for token in where.parent.tokens if token.normalized.strip()):
        return {'route': 'keep', 'reason': 'compound_select', 'options': []}
    options = [candidate for match, begin in where_comparisons(where, offset)
               for candidate in column_options(case, sql, match, begin, schema, tables)]
    if not options:
        return {'route': 'keep', 'reason': 'no_verified_column_conflict', 'options': []}
    if len(options) == 1 and options[0]['same_row_full_name']:
        return {'route': 'auto', 'reason': 'same_row_verified_full_name', 'options': options}
    if len(options) > 4:
        return {'route': 'keep', 'reason': 'too_many_candidates', 'options': options}
    return {'route': 'review', 'reason': 'column_meaning_needs_confirmation', 'options': options}


def column_step_v2(node, case, model, upstream, complete):
    kind = node['kind']
    if kind == 'column_draft_v2':
        return step_node({**node, 'kind': 'generate'}, case, model, [], complete)
    previous = upstream[0]['output']
    if kind == 'column_inspect_v2':
        return {'draft': previous, **inspect_draft(case, previous.get('sql'))}, None
    if kind == 'column_execute_v2':
        output, _ = step_node({**node, 'kind': 'execute'}, case, model,
                              [{'kind': 'generate', 'output': previous['final']}], complete)
        return {**output, 'revision': previous['revision']}, None
    draft, options, route = (previous[name] for name in ('draft', 'options', 'route'))
    result = {'final': draft, 'revision': 'kept', 'route': route}
    chosen, call = (0 if route == 'auto' else None), None
    if route == 'review':
        evidence = [{k: v for k, v in option.items() if k != 'sql'} for option in options]
        verdict, call = ask(node, case, model, REVIEW, {'draft_sql': draft['sql'], 'options': evidence}, complete)
        result['review'] = verdict
        choice, quote, reason = (verdict.get(key) for key in ('choice', 'quote', 'reason'))
        if (type(choice) is int and 0 <= choice < len(options)
                and isinstance(quote, str) and quote and quote in case.question
                and options[choice]['term'] in quote and isinstance(reason, str) and reason.strip()):
            chosen = choice
    if chosen is not None:
        patched = options[chosen]['sql']
        prepared = execute_sql(case.database, 'EXPLAIN QUERY PLAN ' + patched)
        if prepared['status'] == 'executed':
            result.update(final={'sql': patched}, revision='patched', chosen=chosen)
        else:
            result['sqlite_reason'] = prepared.get('reason')
    return result, call
