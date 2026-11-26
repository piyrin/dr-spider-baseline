"""Route a related-record count by the question's treatment of missing detail."""

import re

from experiment import columns_for, step_node, validate_graph

STEM = 'SQL_comparison-00133'
EXAMPLES = [STEM + '-pre', STEM + '-post']
KINDS = ('count_intent', 'count_policy', 'count_generate', 'execute')
BASE_KINDS = ('extract', 'lookup', 'generate', 'execute')
STEPS = ('intent', 'policy', 'generate', 'execute')
GRAPH = {
    'nodes': [{'id': node, 'kind': kind} for node, kind in zip(STEPS, KINDS)],
    'links': [{'source': before, 'target': after} for before, after in zip(STEPS, STEPS[1:])],
}
INTENT = (
    'For this node replace the default field-hypothesis task with a scope analysis for one count '
    'of related records per parent entity. Return JSON {"targets":[]} if no single applicable '
    'count or parent/detail key is clear. Otherwise return one target with parent_table, parent_key, '
    'detail_table, detail_key (exact schema identifiers connected by equality), role '
    '("result", "filter", or "both"), operator (comparison to count, or null), threshold '
    '(nonnegative integer or null), policy ("observed", "zero", or "unknown"), '
    'and cue (exact contiguous original question text supporting the choice). '
    'Use observed when counting recorded observations about a parent, no detail makes that '
    'measurement unknown, and the question does not require inclusion of unobserved parents. '
    'Use zero when the question expressly includes zero counts or absence of related events, '
    'or asks to report a count for each parent even without matching records. '
    'Use unknown if coverage, intended population, or the effect of a compound condition is unclear. '
    'An upper bound alone does not decide whether no detail means zero. Do not provide SQL.'
)
ABSENCE_CUE = re.compile(r'\b(?:zero|0|none|never|without)\b|\bno\s+(?!more\b|less\b|fewer\b)', re.I)
POPULATION_CUE = re.compile(r'\b(?:every|each|all|per)\b', re.I)


def is_count(graph):
    return isinstance(graph, dict) and isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') in KINDS[:-1] for node in graph['nodes'])


def validate_count(graph):
    nodes = graph.get('nodes')
    if not isinstance(nodes, list) or len(nodes) != len(KINDS) or any(
        not isinstance(node, dict) or node.get('kind') not in KINDS
        or node.get('hint') or node.get('probe') for node in nodes
    ):
        raise ValueError('统计口径编排需要四个固定职责节点。')
    mapping = dict(zip(KINDS, BASE_KINDS))
    spec = {**graph, 'nodes': [{**node, 'kind': mapping[node['kind']]} for node in nodes]}
    ordered = validate_graph(spec)
    if tuple(node['kind'] for node in ordered) != BASE_KINDS or any(
        node['from'] != ([ordered[i - 1]['id']] if i else []) for i, node in enumerate(ordered)
    ):
        raise ValueError('按题意解析、统计口径、生成 SQL 和执行的顺序连接。')
    return [{**node, 'kind': kind} for node, kind in zip(ordered, KINDS)]


def resolve_scope(case, extracted):
    def fallback(reason):
        return {'route': 'fallback', 'reason': reason}

    targets = extracted.get('targets', [])
    if not isinstance(targets, list) or len(targets) != 1 or not isinstance(targets[0], dict):
        return fallback('no_unique_related_count')
    target = targets[0]
    role, policy, cue = (target.get(key) for key in ('role', 'policy', 'cue'))
    if role not in ('filter', 'result', 'both') or policy not in ('observed', 'zero'):
        return fallback('uncertain_scope')
    if not isinstance(cue, str) or not cue.strip() or cue.strip().casefold() not in case.question.casefold():
        return fallback('unverified_question_cue')
    schema = columns_for(case.database)
    binding = {}
    for side in ('parent', 'detail'):
        table, column = (target.get(f'{side}_{key}') for key in ('table', 'key'))
        if not isinstance(table, str) or not isinstance(column, str):
            return fallback('invalid_schema_binding')
        matches = [(t, c) for t, fields in schema.items() if t.casefold() == table.casefold()
                   for c in fields if c.casefold() == column.casefold()]
        if len(matches) != 1:
            return fallback('invalid_schema_binding')
        binding[f'{side}_table'], binding[f'{side}_key'] = matches[0]
    if binding['parent_table'] == binding['detail_table']:
        return fallback('same_table')
    threshold, operator = target.get('threshold'), target.get('operator')
    if policy == 'observed':
        if role not in ('filter', 'both') or type(threshold) is not int or not (
            (operator == '<' and threshold > 0) or (operator == '<=' and threshold >= 0)
        ):
            return fallback('zero_cannot_change_supported_filter')
    elif not ABSENCE_CUE.search(cue) and not (role == 'result' and POPULATION_CUE.search(cue)):
        return fallback('zero_scope_not_explicit')
    return {'route': policy, 'role': role, 'operator': operator, 'threshold': threshold,
            'cue': cue.strip(), **binding}


def count_step(node, case, model, upstream, complete):
    kind = node['kind']
    if kind == 'count_intent':
        return step_node({**node, 'kind': 'extract', 'hint': INTENT}, case, model, [], complete)
    if kind == 'count_policy':
        return resolve_scope(case, upstream[0]['output']), None
    if kind == 'count_generate':
        evidence = upstream[0]['output']
        route = evidence['route']
        previous = []
        if route in ('observed', 'zero'):
            parent = f"{evidence['parent_table']}.{evidence['parent_key']}"
            detail = f"{evidence['detail_table']}.{evidence['detail_key']}"
            hint = f'Count scope for the relation from {parent} to {detail}. '
            if route == 'observed':
                hint += ('Use parents with matching recorded detail for this count filter. '
                         'Absence of detail is an unknown observation and must not pass as zero. ')
            else:
                hint += ('Keep the requested population of parents, including those with no matching '
                         'detail. Treat that absence as zero where requested. With an outer join count '
                         'a non-null matched detail key, not the placeholder row. ')
            hint += 'Keep the question’s output, comparison and other conditions.'
            previous.append({'kind': 'plan', 'output': hint})
        output, call = step_node({**node, 'kind': 'generate'}, case, model, previous, complete)
        return {**output, 'route': route}, call
    return step_node(node, case, model, upstream, complete)
