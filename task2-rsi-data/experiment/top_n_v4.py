"""Select a supported, testable Top N rule or fall back to the baseline."""

import re

from experiment import columns_for, execute_sql, ident, step_node
from top_n_canvas import normalized, validate_top_n
from top_n_v3 import (GRAPH_V3, RANKING, WORDS, fallback, inspect_plan, numerals,
                      quoted, run_step as run_v3)

KINDS = {node['kind']: node['kind'].replace('_v3', '_v4') for node in GRAPH_V3['nodes']}
GRAPH_V4 = {**GRAPH_V3, 'nodes': [{**node, 'kind': KINDS[node['kind']]} for node in GRAPH_V3['nodes']]}
EVENT_SCOPE = re.compile(
    r'\b(?:across|over|among|from|in) all (?:\w+ ){0,2}'
    r'(?:matches|games|races|laps|events|runs|attempts|orders|transactions|observations|records)\b')
EXPLICIT_UNIT = re.compile(r'\b(?:distinct|different|unique|individual|each|per|one row for)\b')
NUM = r'([0-9]+|' + '|'.join(WORDS) + r')'
RAW_UNIT = re.compile(r'\b' + NUM + r' (?:\w+ ){0,2}'
                      r'(?:matches|games|races|laps|events|runs|attempts|orders|transactions|observations|records)\b')
NAMED_LIMIT = re.compile(
    r'\b(?:top|bottom|first|last) ' + NUM + r'\b|\b' + NUM +
    r' (?:youngest|oldest|fastest|slowest|earliest|latest|highest|lowest|largest|smallest|best|worst|longest|shortest)\b')
INTENT = (
    'Select one of five bounded Top N rules. Return '
    '{"targets":[{"rule":"entity|tuple|rows|event_tuple|unknown","scope":"all_rows|unsupported",'
    '"table":"exact table","display":["final output column"],"key":["grouping column"],'
    '"order":"exact ranking column","direction":"ASC|DESC","n":5,'
    '"grain_evidence":"verbatim wording","projection_evidence":"verbatim wording",'
    '"ties":[{"column":"exact column","direction":"ASC|DESC","cue":"verbatim wording"}],'
    '"entity_key":"exact ID for event_tuple","entity_display":"exact label for event_tuple"}]}. '
    'First honor an explicitly requested grain: entity for one per different person or item, '
    'tuple for distinct combinations, rows for requested individual records. '
    'Keep keys internal unless the question asks to display them. Use event_tuple for a ranking '
    'explicitly across all events, matches, runs or transactions when the two requested outputs '
    'are an entity label and an attribute that may change at each event, there is a stable entity ID, '
    'and the question does not explicitly demand different entities or raw event rows. '
    'For event_tuple quote the full scope phrase, identify the ID and label, and use the display '
    'pair as key. This is a default for event-scoped questions and must yield to explicit grain. '
    'Use unknown when no rule fits. A smallest or largest observed value within a unit is supported. '
    'Filtered, joined or complex aggregated questions are unsupported and must keep all constraints '
    'on fallback. Copy the actual requested limit. Do not output SQL.'
)


def is_v4(graph):
    return isinstance(graph, dict) and isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') in KINDS.values() for node in graph['nodes'])


def validate_v4(graph):
    old_by_new = {new: old.removesuffix('_v3') for old, new in KINDS.items()}
    if (not is_v4(graph) or any(not isinstance(node, dict) or node.get('kind') not in old_by_new
                                or node.get('hint') for node in graph['nodes'])):
        raise ValueError('Top N v4 需要使用同版本的自动规则节点。')
    old_nodes = [{**node, 'kind': old_by_new[node['kind']]} for node in graph['nodes']]
    return [{**node, 'kind': node['kind'] + '_v4'}
            for node in validate_top_n({**graph, 'nodes': old_nodes})]


def limit_for(question):
    matches = (a or b for a, b in NAMED_LIMIT.findall(normalized(question)))
    values = {int(value) if value.isdecimal() else WORDS[value] for value in matches}
    return next(iter(values)) if len(values) == 1 else None


def event_plan(case, item):
    question = normalized(case.question)
    cue = item.get('grain_evidence')
    projection = item.get('projection_evidence')
    if (not quoted(case.question, cue) or not EVENT_SCOPE.search(normalized(cue))
            or EXPLICIT_UNIT.search(question) or RAW_UNIT.search(question) or not quoted(case.question, projection)
            or not re.search(r'\b(?:names?|labels?|titles?)\b', normalized(projection))
            or item.get('scope') != 'all_rows' or item.get('ties')
            or re.search(r'\b(?:where|whose|having|provided that)\b', question)):
        return fallback('event_scope_or_projection_unverified')
    n, direction = item.get('n'), item.get('direction')
    if type(n) is not int or n not in numerals(case.question) or not 1 <= n <= 500 or direction not in ('ASC', 'DESC'):
        return fallback('unverified_limit_or_direction')
    schema = columns_for(case.database)
    table = next((a for a in schema if a.casefold() == str(item.get('table')).casefold()), None)
    fields = {a.casefold(): a for a in schema.get(table, {})}
    values = item.get('display')
    if not isinstance(values, list) or len(values) != 2:
        return fallback('event_display_requires_two_columns')
    display = [fields.get(str(a).casefold()) for a in values]
    entity_id, label, ranking = (fields.get(str(item.get(a)).casefold())
                                 for a in ('entity_key', 'entity_display', 'order'))
    if (not all([*display, entity_id, label, ranking]) or len(set(display)) != 2
            or label not in display or entity_id in display or ranking in display or ranking == entity_id):
        return fallback('event_columns_unverified')
    other = next(a for a in display if a != label)
    pk, title, attr, source = map(ident, (entity_id, label, other, table))
    checks = (
        f'EXISTS(SELECT 1 FROM {source} WHERE {pk} IS NULL OR {title} IS NULL)',
        f'EXISTS(SELECT 1 FROM {source} GROUP BY {pk} HAVING COUNT(DISTINCT {title}) > 1)',
        f'EXISTS(SELECT 1 FROM {source} GROUP BY {title} HAVING COUNT(DISTINCT {pk}) > 1)',
        f'EXISTS(SELECT 1 FROM {source} GROUP BY {pk} HAVING COUNT(DISTINCT {attr}) > 1)',
        f'EXISTS(SELECT 1 FROM {source} GROUP BY {pk}, {title}, {attr} HAVING COUNT(*) > 1)',
    )
    result = execute_sql(case.database, 'SELECT ' + ', '.join(checks))
    if result.get('rows') != [(0, 0, 0, 1, 1)]:
        return fallback('event_identity_or_repetition_unverified')
    return {'route': 'tuple', 'table': table, 'display': display, 'keys': display,
            'order': [(ranking, direction)], 'n': n, 'grain_evidence': cue,
            'projection_evidence': projection, 'identity_key': entity_id, 'variable_attribute': other}


def choose_plan(case, output):
    candidates = output.get('targets', [])
    if len(candidates) != 1 or not isinstance(candidates[0], dict):
        return fallback(output.get('reason', 'no_single_supported_plan'))
    item = dict(candidates[0])
    rule = item.get('rule')
    original = item.get('n')
    recognized = limit_for(case.question)
    if recognized is not None:
        item['n'] = recognized
    if rule in ('entity', 'tuple', 'rows'):
        verified = inspect_plan(case, {'targets': [{**item, 'unit': rule}]})
    elif rule == 'event_tuple':
        verified = event_plan(case, item)
    else:
        verified = fallback('no_rule_selected')
    return {**verified, 'selected_rule': rule, 'agent_limit': original, 'verified_limit': item.get('n')}


def run_step(node, case, model, upstream, complete):
    kind = node['kind']
    previous = upstream[0]['output'] if upstream else None
    if kind == 'top_n_intent_v4':
        if not RANKING.search(case.question) or not numerals(case.question):
            return {'reason': 'no_top_n_cue'}, None
        return step_node({**node, 'kind': 'extract', 'hint': INTENT}, case, model, [], complete)
    if kind == 'top_n_inspect_v4':
        return choose_plan(case, previous), None
    result, call = run_v3({**node, 'kind': kind.replace('_v4', '_v3')}, case, model, upstream, complete)
    if kind in ('top_n_policy_v4', 'top_n_execute_v4'):
        result['rule'] = previous.get('selected_rule', previous.get('rule'))
    return result, call
