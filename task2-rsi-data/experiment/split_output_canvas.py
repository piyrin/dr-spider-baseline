"""Ground a requested person name and decide how to use its stored components."""

import re

from experiment import columns_for, execute_sql, step_node

STEM = 'DB_DBcontent_equivalence-00125'
EXAMPLES = [STEM + '-pre', STEM + '-post']
KINDS = ('split_intent', 'split_fields', 'split_decide', 'split_contract', 'split_generate', 'split_execute')
IDS = ('intent', 'fields', 'decide', 'contract', 'generate', 'execute')
GRAPH = {
    'nodes': [{'id': node, 'kind': kind} for node, kind in zip(IDS, KINDS)],
    'links': [{'source': parent, 'target': child} for parent, child in zip(IDS, IDS[1:])],
}
INTENT = (
    'For this node identify a person name in the question. A word like name can name a song or '
    'place; only select person names. Return JSON {"targets":[]} if no single person name concept '
    'is clear. Otherwise return exactly one target with kind "name", table (exact identifier), '
    'fields (exact identifiers, all stored name components needed for the concept, in display order), '
    'role ("output", "filter", or "both"), cue (verbatim contiguous text naming the concept), '
    'and sole_output (true only when that name is the only requested output item). '
    'A person name may be used for lookup, output, or both. Do not include columns merely used for '
    'other filters, joins or sorting. If only one name component was requested, list just that '
    'component. If the person name has first and last components, list both; include the middle '
    'component if it is part of the requested name. Do not output SQL.'
)
DECISION = (
    'Choose how to use this one verified group of stored person-name components. '
    'Return JSON {"targets":[{"mode":"split|lookup|display|fallback","cue":"verbatim question '
    'fragment"}]}. split means separate stored fields for an output name in the absence of an '
    'explicit request to combine it. lookup means combine components only to match a name supplied '
    'as a filter; if the name is also requested as output leave the components separate. display '
    'requires explicit wording to concatenate or display one output column. A generic name or full '
    'name request uses the experiment default of preserved components. Use fallback for unclear '
    'field use. Do not supply SQL or other columns.'
)
NAME_PART = re.compile(r'(?:first|last|middle|given|family|sur)(?:name)$|(?:^|_)(?:fname|lname|mname|surname)$',
                       re.I)
DISPLAY_EXPLICIT = re.compile(
    r'\b(?:single|one)\s+(?:output\s+)?(?:column|field|string)\b|\b(?:concatenate|combine|join|merge)\b',
    re.I)


def is_split(graph):
    return isinstance(graph, dict) and isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') in KINDS for node in graph['nodes'])


def validate_split(graph):
    nodes, links = graph.get('nodes'), graph.get('links')
    if not isinstance(nodes, list) or len(nodes) != len(KINDS) or not isinstance(links, list):
        raise ValueError('姓名输出编排需要六个职责节点。')
    kinds, seen = {}, set()
    for node in nodes:
        node_id, kind = node.get('id'), node.get('kind')
        if (not isinstance(node_id, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,48}', node_id)
                or node_id in seen or kind not in KINDS or kind in kinds
                or node.get('hint') or node.get('probe')):
            raise ValueError('节点 ID、类型或配置有误。')
        seen.add(node_id)
        kinds[kind] = node_id
    order = [kinds[kind] for kind in KINDS]
    if sorted((link.get('source', ''), link.get('target', '')) for link in links) != sorted(zip(order, order[1:])):
        raise ValueError('请依次连接题意、字段核对、多列判断、输出约束、生成和执行。')
    return [{'id': node_id, 'kind': kind, 'hint': '', 'probe': False,
             'from': order[max(0, i-1):i]} for i, (node_id, kind) in enumerate(zip(order, KINDS))]


def fallback(reason):
    return {'route': 'fallback', 'reason': reason}


def verified_cue(case, cue):
    return isinstance(cue, str) and bool(cue.strip()) and cue.strip().casefold() in case.question.casefold()


def component_order(column):
    name = re.sub(r'[^a-z]', '', column.casefold())
    if name.endswith(('firstname', 'givenname', 'fname')):
        return 0
    return 1 if name.endswith(('middlename', 'mname')) else 2


def verify_fields(case, result):
    targets = result.get('targets')
    if not isinstance(targets, list) or len(targets) != 1 or not isinstance(targets[0], dict):
        return fallback('no_unique_person_name')
    target = targets[0]
    table, requested = target.get('table'), target.get('fields')
    cue, role = target.get('cue'), target.get('role')
    if (target.get('kind') != 'name' or role not in ('output', 'filter', 'both')
            or not verified_cue(case, cue) or not isinstance(table, str)
            or not isinstance(requested, list) or not 1 <= len(requested) <= 3
            or not all(isinstance(v, str) for v in requested)):
        return fallback('unverified_intent')
    for actual_table, fields in columns_for(case.database).items():
        if actual_table.casefold() == table.casefold():
            break
    else:
        return fallback('unknown_table')
    folded = {column.casefold(): column for column in fields}
    if len(set(map(str.casefold, requested))) != len(requested) or any(
        column.casefold() not in folded for column in requested
    ):
        return fallback('unknown_or_duplicate_field')
    columns = [folded[column.casefold()] for column in requested]
    info = {'table': actual_table, 'columns': columns, 'role': role, 'cue': cue,
            'sole_output': target.get('sole_output') is True}
    if len(columns) == 1:
        return {'route': 'direct', **info}
    normalized = [c.casefold().replace('_', '') for c in columns]
    parts = {component_order(column) for column in columns}
    if parts != ({0, 2} if len(columns) == 2 else {0, 1, 2}) or not all(
        NAME_PART.search(name) for name in normalized
    ):
        return fallback('unsupported_or_ambiguous_components')
    return {'route': 'components', **info, 'columns': sorted(columns, key=component_order)}


def decide(case, verified, action):
    mode, cue = action.get('mode'), action.get('cue')
    if not verified_cue(case, cue) or mode not in ('split', 'lookup', 'display'):
        return fallback('undecided_or_unverified')
    role = verified['role']
    if ((mode == 'lookup' and role not in ('filter', 'both'))
            or (mode != 'lookup' and role not in ('output', 'both'))
            or (mode == 'display' and not DISPLAY_EXPLICIT.search(cue))
            or (mode == 'split' and DISPLAY_EXPLICIT.search(case.question))):
        return fallback('operation_conflicts_with_question')
    return {**verified, 'route': mode, 'decision_cue': cue}


def check_output(contract, result):
    route = contract['route']
    if route != 'split' and not (route == 'lookup' and contract['role'] == 'both'):
        return 'not_applicable'
    if 'columns' not in result:
        return 'unavailable'
    actual = [col.casefold() for col in result['columns']]
    expected = [col.casefold() for col in contract['columns']]
    if contract['sole_output']:
        return 'match' if actual == expected else 'mismatch'
    index = 0
    for col in actual:
        if index < len(expected) and col == expected[index]:
            index += 1
    return 'match' if index == len(expected) else 'mismatch'


def split_step(node, case, model, upstream, complete):
    kind = node['kind']
    previous = upstream[0]['output'] if upstream else None
    if kind == 'split_intent':
        return step_node({**node, 'kind': 'extract', 'hint': INTENT}, case, model, [], complete)
    if kind == 'split_fields':
        return verify_fields(case, previous), None
    if kind == 'split_decide':
        if previous['route'] != 'components':
            return {**previous, 'decision_skipped': True}, None
        context = {'targets': [previous]}
        output, call = step_node({**node, 'kind': 'extract', 'hint': DECISION}, case,
                                 model, [{'kind': 'extract', 'output': context}], complete)
        choices = output['targets']
        action = choices[0] if len(choices) == 1 and isinstance(choices[0], dict) else {}
        return {**decide(case, previous, action), 'agent_decision': action}, call
    if kind == 'split_contract':
        evidence = {k: v for k, v in previous.items() if k != 'agent_decision'}
        if evidence['route'] in ('fallback', 'direct'):
            return {**evidence, 'hint': ''}, None
        fields = ', '.join(f'{evidence["table"]}.{column}' for column in evidence['columns'])
        route = evidence['route']
        if route == 'split':
            hint = f'Return this requested person name as separate stored columns in this order: {fields}.'
        elif route == 'display':
            hint = f'The question explicitly asks for one display value. Combine these components: {fields}.'
        else:
            hint = f'For matching the name supplied in the question, use these stored components: {fields}.'
            if evidence['role'] == 'both':
                hint += ' Keep the same components separate in the final projection.'
        return {**evidence, 'hint': hint + ' Preserve all other requested outputs and filters.'}, None
    if kind == 'split_generate':
        context = [{'kind': 'plan', 'output': previous['hint']}] if previous['hint'] else []
        result, call = step_node({**node, 'kind': 'generate'}, case, model, context, complete)
        return {**result, 'route': previous['route'], 'contract': previous}, call
    result = execute_sql(case.database, previous['sql']) if previous.get('sql') else {
        'status': previous.get('status', 'generation_error'), 'reason': previous.get('reason')}
    return {**result, 'output_check': check_output(previous['contract'], result)}, None
