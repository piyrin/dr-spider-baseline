"""Recover an explicit name request against the current schema."""

import re

from experiment import columns_for
from split_output_canvas import DISPLAY_EXPLICIT, GRAPH, decide, split_step, validate_split, verify_fields

FIELD_KIND = 'split_fields_v2'
EXPLICIT_NAME = re.compile(
    r'^what\s+is\s+the\s+name\s+of\s+the\s+(?P<table>[a-z][a-z0-9_]*)'
    r'(?=\s+(?:who|that|which|with)\b|\s*\?\s*$)', re.I,
)
GRAPH_V2 = {**GRAPH, 'nodes': [
    {**node, 'kind': FIELD_KIND} if node['kind'] == 'split_fields' else node
    for node in GRAPH['nodes']
]}


def validate_split_v2(graph):
    nodes = graph['nodes']
    if sum(node.get('kind') == FIELD_KIND for node in nodes) != 1:
        raise ValueError('v2 需要一个可恢复明确姓名请求的字段核对节点。')
    compatible = {**graph, 'nodes': [{**node, 'kind': 'split_fields'} if node.get('kind') == FIELD_KIND else node
                                     for node in nodes]}
    return [{**node, 'kind': FIELD_KIND} if node['kind'] == 'split_fields' else node
            for node in validate_split(compatible)]


def explicit_name(case):
    match = EXPLICIT_NAME.match(case.question.strip())
    if (match is None or DISPLAY_EXPLICIT.search(case.question)
            or re.search(r'\band\s+(?:return|show|list|give|provide)\b', case.question, re.I)):
        return None
    table = match['table'].casefold()
    for actual, fields in columns_for(case.database).items():
        if actual.casefold() == table:
            break
    else:
        return None

    names = {re.sub(r'[^a-z]', '', field.casefold()): field for field in fields}
    direct = [names[name] for name in ('name', 'fullname') if name in names]
    components = [names[name] for name in ('firstname', 'middlename', 'lastname') if name in names]
    split_available = 'firstname' in names and 'lastname' in names
    if len(direct) == 1 and not components:
        columns = direct
    elif not direct and split_available:
        columns = components
    else:
        return None

    verified = verify_fields(case, {'targets': [{
        'kind': 'name', 'table': actual, 'fields': columns,
        'role': 'output', 'cue': match.group(), 'sole_output': True,
    }]})
    return {**verified, 'binding_source': 'explicit_question_schema'} if verified['route'] != 'fallback' else None


def split_step_v2(node, case, model, upstream, complete):
    if node['kind'] == FIELD_KIND:
        recovered = explicit_name(case)
        if recovered is not None:
            return recovered, None
        return split_step({**node, 'kind': 'split_fields'}, case, model, upstream, complete)

    output, call = split_step(node, case, model, upstream, complete)
    if node['kind'] == 'split_decide' and output['route'] == 'fallback':
        verified = upstream[0]['output']
        if verified.get('binding_source') == 'explicit_question_schema':
            action = {'mode': 'split', 'cue': verified['cue']}
            output = {**decide(case, verified, action), 'decision_source': 'explicit_output_policy',
                      'agent_decision': output.get('agent_decision', {})}
    if node['kind'] == 'split_contract' and output.get('binding_source') == 'explicit_question_schema' and output['route'] == 'split':
        output['hint'] += (' Each requested name component must be its own final SELECT column '
                           'in the specified order. Preserve the question’s other conditions.')
    return output, call
