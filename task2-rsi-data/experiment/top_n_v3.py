"""Separate the rank unit from the output columns and compile verified plans."""

import re

from experiment import columns_for, execute_sql, ident, step_node
from top_n_canvas import GRAPH, normalized, validate_top_n

KINDS = {node['kind']: node['kind'] + '_v3' for node in GRAPH['nodes']}
GRAPH_V3 = {**GRAPH, 'nodes': [{**node, 'kind': KINDS[node['kind']]} for node in GRAPH['nodes']]}
INTERACTIVE_V3 = {**GRAPH_V3, 'nodes': [{**node, 'hint': 'interactive'}
                                       if node['id'] == 'policy' else node for node in GRAPH_V3['nodes']]}
WORDS = {name: i for i, name in enumerate(
    'one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty'.split(), 1)}
RANKING = re.compile(
    r'\b(?:top|bottom|fewest|most|least|first|last|highest|lowest|largest|smallest|'
    r'youngest|oldest|earliest|latest|fastest|slowest|best|worst|longest|shortest|order|ordered)\b', re.I)
UNITS = {
    'rows': re.compile(r'\b(?:rows?|records?|runs?|attempts?|measurements?|events?|matches|transactions?)\b'),
    'entity': re.compile(r'\b(?:different|distinct|individual|unique|per|each|one (?:row|record) for)\b'),
    'tuple': re.compile(r'\b(?:combinations?|pairs?|tuples?)\b'),
}
INTENT = (
    'Analyze one top-N query over a single table. Return {"targets":[{"scope":"all_rows|unsupported",'
    '"unit":"rows|entity|tuple|ambiguous","table":"schema table","display":["display column"],'
    '"key":["key column"],"order":"raw ranking column","direction":"ASC|DESC","n":5,'
    '"grain_evidence":"verbatim result-unit wording","projection_evidence":"verbatim display wording",'
    '"ties":[{"column":"tie field","direction":"ASC|DESC","cue":"verbatim tie wording"}]}]}. '
    'Display contains only requested final output fields. Keep a grouping ID internal when the question '
    'says one row per ID but asks to display only names or attributes. Entity means explicitly different '
    'people or one row per entity identified by a stable key. Tuple means explicitly distinct combinations '
    'or pairs, using the tuple fields as keys. Rows means explicit raw records, such as individual runs or '
    'matches. Unqualified winners with displayed names and ranks can mean entities or tuples: mark '
    'ambiguous. An extremum within each result unit (e.g. lowest observed age in each pair) is supported. '
    'Entity returns the complete record with the extreme value; tuple orders groups by that extreme. '
    'Additional filters, joins, arbitrary aggregates, multi-table scopes, and incompatible rules are '
    'unsupported; do not drop those constraints. Use ties only for explicitly requested secondary ordering. '
    'Return {"targets":[]} for unrelated questions. Provide a plan without writing SQL.'
)


def is_v3(graph):
    return isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') in KINDS.values() for node in graph['nodes'])


def validate_v3(graph):
    original = {new: old for old, new in KINDS.items()}
    if not is_v3(graph) or any(node.get('kind') not in original for node in graph['nodes']):
        raise ValueError('请使用同一版本的 Top N 节点。')
    translated = [{**node, 'kind': original[node['kind']]} for node in graph['nodes']]
    return [{**node, 'kind': KINDS[node['kind']]} for node in validate_top_n({**graph, 'nodes': translated})]


def numerals(question):
    return {int(word) if word.isdecimal() else WORDS[word] for word in normalized(question).split()
            if word.isdecimal() or word in WORDS}


def quoted(question, cue):
    return isinstance(cue, str) and bool(normalized(cue)) and (
        f' {normalized(cue)} ' in f' {normalized(question)} ')


def fallback(reason):
    return {'route': 'fallback', 'reason': reason}


def inspect_plan(case, hypothesis):
    if 'reason' in hypothesis:
        return fallback(hypothesis['reason'])
    targets = hypothesis['targets']
    if len(targets) != 1 or not isinstance(targets[0], dict):
        return fallback('no_single_supported_plan')
    plan = targets[0]
    question = case.question
    unit, cue = plan.get('unit'), plan.get('grain_evidence')
    if unit == 'ambiguous' and quoted(question, cue):
        return {'route': 'ambiguity', 'reason': 'ambiguous_unit', 'cue': cue}
    if (unit not in UNITS or not quoted(question, cue) or not UNITS[unit].search(normalized(cue))
            or plan.get('scope') != 'all_rows' or re.search(r'\b(?:where|whose|having|provided that)\b', question, re.I)
            or not quoted(question, plan.get('projection_evidence'))):
        return fallback('unit_projection_or_scope_unverified')
    n, direction = plan.get('n'), plan.get('direction')
    if type(n) is not int or not 1 <= n <= 500 or n not in numerals(question) or direction not in ('ASC', 'DESC'):
        return fallback('unverified_limit_or_direction')
    schema = columns_for(case.database)
    table = next((name for name in schema if name.casefold() == str(plan.get('table')).casefold()), None)
    names = {name.casefold(): name for name in schema.get(table, {})}
    display, keys, ties = plan.get('display'), plan.get('key', []), plan.get('ties', [])
    if any(not isinstance(items, list) for items in (display, keys, ties)):
        return fallback('invalid_plan_shape')
    display = [names.get(str(field).casefold()) for field in display]
    keys = [names.get(str(field).casefold()) for field in keys]
    ranking = names.get(str(plan.get('order')).casefold())
    if (not display or len(set(display)) != len(display) or not ranking or not all(display + keys)
            or (unit == 'entity' and not keys)
            or (unit == 'tuple' and (len(keys) < 2 or set(keys) != set(display)))):
        return fallback('unverified_schema_or_grain')
    if unit == 'entity':
        projection = set(normalized(plan['projection_evidence']).split())
        for key in set(display) & set(keys):
            tail = normalized(key.replace('_', ' ')).split()[-1]
            if tail in {'id', 'key', 'code', 'identifier'} and not projection & {tail, tail + 's'}:
                return fallback('entity_key_not_requested_for_display')
    order = [(ranking, direction)]
    for item in ties:
        if not isinstance(item, dict):
            return fallback('unverified_tie_order')
        field = names.get(str(item.get('column')).casefold())
        ordering = item.get('direction')
        if (not field or field in {name for name, _ in order} or ordering not in ('ASC', 'DESC')
                or not quoted(question, item.get('cue')) or (unit == 'tuple' and field not in keys)):
            return fallback('unverified_tie_order')
        order.append((field, ordering))
    return {'route': unit, 'table': table, 'display': display, 'keys': keys,
            'order': order, 'n': n, 'grain_evidence': cue,
            'projection_evidence': plan['projection_evidence']}


def order_sql(order):
    return ', '.join(f'{ident(column)} {direction}' for column, direction in order)


def compile_plan(plan):
    cols = ', '.join(map(ident, plan['display']))
    keys = ', '.join(map(ident, plan['keys']))
    order = plan['order']
    rank, direction = order[0]
    table = f'{ident(plan["table"])} WHERE {ident(rank)} IS NOT NULL'
    prefix, representative_check = '', None
    source = table
    if plan['route'] == 'tuple':
        aggregate = 'MIN' if direction == 'ASC' else 'MAX'
        source = f'(SELECT {keys}, {aggregate}({ident(rank)}) AS "__top_n_value" FROM {table} GROUP BY {keys})'
        order = [('__top_n_value', direction), *order[1:]]
    if plan['route'] == 'entity':
        relevant = dict.fromkeys([*plan['display'], *plan['keys'], *(field for field, _ in order)])
        fields = ', '.join(map(ident, relevant))
        prefix = (f'WITH candidates AS (SELECT DISTINCT {fields} FROM {table}), '
                  f'ranked AS (SELECT {fields}, RANK() OVER (PARTITION BY {keys} ORDER BY {order_sql(order)}) '
                  f'AS "__top_n_position" FROM candidates) ')
        source = 'ranked WHERE "__top_n_position"=1'
        representative_check = f'{prefix}SELECT 1 FROM {source} GROUP BY {keys} HAVING COUNT(*) > 1 LIMIT 1'
    ordered = f'FROM {source} ORDER BY {order_sql(order)}'
    signature = ', '.join(ident(column) for column, _ in order)
    n = plan['n']
    return (f'{prefix}SELECT {cols} {ordered} LIMIT {n}',
            f'{prefix}SELECT {signature} {ordered} LIMIT {n + 1}', representative_check)


def policy(case, plan, interactive):
    if plan['route'] == 'fallback':
        return plan
    if plan['route'] == 'ambiguity':
        return {**plan, 'route': 'clarification' if interactive else 'fallback',
                'question': '前 N 项以不同实体、不同字段组合，还是原始记录为单位？'}
    sql, boundary, representative = compile_plan(plan)
    if representative:
        matches = execute_sql(case.database, representative)
        if matches['status'] != 'executed' or matches['rows']:
            return fallback('uncertain_representative_tie')
    observed = execute_sql(case.database, boundary)
    if observed['status'] != 'executed':
        return fallback('ranking_probe_failed')
    rows = observed['rows']
    if len(rows) > plan['n'] and rows[-2] == rows[-1]:
        return fallback('uncertain_cutoff_tie')
    return {**plan, 'sql': sql, 'cutoff_checked': True}


def run_step(node, case, model, upstream, complete):
    kind = node['kind']
    previous = upstream[0]['output'] if upstream else None
    if kind == 'top_n_intent_v3':
        if not RANKING.search(case.question) or not numerals(case.question):
            return {'reason': 'no_top_n_cue'}, None
        return step_node({**node, 'kind': 'extract', 'hint': INTENT}, case, model, [], complete)
    if kind == 'top_n_inspect_v3':
        return inspect_plan(case, previous), None
    if kind == 'top_n_policy_v3':
        return policy(case, previous, node['hint'] == 'interactive'), None
    if kind == 'top_n_generate_v3':
        if previous['route'] == 'clarification':
            return {**previous, 'status': 'clarification', 'reason': previous['question']}, None
        if previous.get('sql'):
            return previous, None
        output, call = step_node({**node, 'kind': 'generate'}, case, model, [], complete)
        return {**previous, **output}, call
    result, call = step_node({**node, 'kind': 'execute'}, case, model, upstream, complete)
    return {**result, 'route': previous['route'], 'decision_reason': previous.get('reason')}, call
