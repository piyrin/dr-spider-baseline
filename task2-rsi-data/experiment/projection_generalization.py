"""Widen the name router while preserving a strict fallback."""

import re

from experiment import columns_for
from projection_canvas import GRAPH, projection_step, validate_projection


ENTITIES = (
    (('high school student', 'high schooler', 'highschooler', 'student'),
     ('highschooler', 'student', 'students'), ('name', 'studentname')),
    (('teacher',), ('teacher', 'teachers'), ('name', 'teachername')),
    (('employee',), ('employee', 'employees'), ('name', 'employeename')),
    (('contestant',), ('contestant', 'contestants'), ('name', 'contestantname')),
    (('singer',), ('singer', 'singers'), ('name', 'singername')),
    (('country', 'countries', 'nation'), ('country', 'countries'), ('name', 'countryname')),
    (('person', 'people'), ('person', 'people'), ('name', 'personname')),
)
ALIASES = {alias: (tables, names) for labels, tables, names in ENTITIES
           for label in labels for alias in (label, label + 's')}
LABELS = '|'.join(map(re.escape, sorted(ALIASES, key=lambda name: (-len(name), name))))
EXPLICIT = re.compile(r'^(?:(?:what (?:is|are)|list|show|find|give|return|provide) (?:me )?)?'
                      r'(?:the |all |distinct |different )*names? (?:of|for) (?:the |all |each |every )*'
                      r'(?P<entity>' + LABELS + r')\b')
IMPLICIT = re.compile(r'^(?:who (?:are|were|is|was)|which|what|list|show|give|return) '
                      r'(?:(?:me|the|all|a list of|the list of) )*(?P<entity>' + LABELS + r')\b')
EXTRA = re.compile(r'\b(?:and|also|include|including|along with|together with)\b|[;?]')
FIRST_KIND = 'projection_match_v2'
GRAPH_V2 = {**GRAPH, 'nodes': [{**GRAPH['nodes'][0], 'kind': FIRST_KIND}, *GRAPH['nodes'][1:]]}


def question_text(question):
    return ' '.join(question.lower().split()).rstrip('?. ')


def entity_candidate(question, pattern):
    text = question_text(question)
    match = pattern.match(text)
    if not match or EXTRA.search(text) or text[match.end():].startswith(("'", '’')):
        return None
    return match['entity']


def lookup_name(entity, schema):
    if entity is None:
        return None
    tables, names = ALIASES[entity]
    candidates = [(table, field) for table, columns in schema.items()
                  if table.lower() in tables for field in columns
                  if field.lower().replace('_', '') in names]
    return '.'.join(candidates[0]) if len(candidates) == 1 else None


def find_name(question, schema):
    for route, pattern in (('direct', EXPLICIT), ('normalized', IMPLICIT)):
        field = lookup_name(entity_candidate(question, pattern), schema)
        if field:
            return route, field
    return 'fallback', None


def validate_v2(graph):
    if not isinstance(graph, dict) or not isinstance(graph.get('nodes'), list):
        raise ValueError('V2 需要节点列表。')
    matches = [node for node in graph['nodes'] if isinstance(node, dict) and node.get('kind') == FIRST_KIND]
    if len(matches) != 1:
        raise ValueError('V2 需要唯一的名称匹配节点。')
    node_id = matches[0].get('id')
    nodes = [{**node, 'kind': 'projection_match'} if node is matches[0] else node for node in graph['nodes']]
    return [{**node, 'kind': FIRST_KIND} if node['id'] == node_id else node
            for node in validate_projection({**graph, 'nodes': nodes})]


def generalized_step(node, case, model, upstream, complete):
    kind = node['kind']
    if kind == FIRST_KIND:
        entity = entity_candidate(case.question, EXPLICIT)
        field = lookup_name(entity, columns_for(case.database)) if entity else None
        return {'status': 'verified' if field else 'unresolved', 'field': field, 'entity': entity}, None
    if kind == 'projection_normalize':
        if upstream[0]['output']['field']:
            return {'status': 'skipped', 'candidate': None}, None
        candidate = entity_candidate(case.question, IMPLICIT)
        return {'status': 'candidate' if candidate else 'unresolved', 'candidate': candidate}, None
    if kind == 'projection_recheck':
        normalized = upstream[0]['output']
        entity = normalized['candidate']
        field = lookup_name(entity, columns_for(case.database)) if entity else None
        status = normalized['status'] if normalized['status'] == 'skipped' else 'verified' if field else 'unresolved'
        return {'status': status, 'field': field, 'entity': entity}, None
    if kind == 'projection_constraint':
        result, call = projection_step(node, case, model, upstream, complete)
        if result['hint']:
            result['hint'] = result['hint'].replace('student name', 'entity name')
        return result, call
    return projection_step(node, case, model, upstream, complete)
