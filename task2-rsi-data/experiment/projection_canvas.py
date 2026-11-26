"""Schema-checked output field routing for the student-list development case."""

import re

from experiment import columns_for, step_node


STEM = 'NLQ_column_carrier-00499'
KINDS = ('projection_match', 'projection_normalize', 'projection_recheck',
         'projection_constraint', 'projection_generate', 'execute')
EDGES = ((0, 1), (1, 2), (0, 3), (2, 3), (3, 4), (4, 5))
IDS = ('match', 'normalize', 'recheck', 'constraint', 'generate', 'execute')
GRAPH = {
    'nodes': [{'id': node_id, 'kind': kind} for node_id, kind in zip(IDS, KINDS)],
    'links': [{'source': IDS[source], 'target': IDS[target]} for source, target in EDGES],
}
EXAMPLES = [STEM + '-pre', STEM + '-post']
EXPLICIT = re.compile(r'(?:what are the|list the|give the) names of (?:all )?'
                      r'(?:high[ -]?schoolers?|students?) (?:currently )?in grade [\w-]+')
IMPLICIT = re.compile(r'who (?:are|were) (?:all |the )?(?:high[ -]?schoolers?|students?) '
                      r'(?:currently )?in grade [\w-]+')


def is_projection(graph):
    return isinstance(graph, dict) and isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') in KINDS[:-1]
        for node in graph['nodes'])


def validate_projection(graph):
    if not isinstance(graph, dict) or not isinstance(graph.get('nodes'), list) or not isinstance(graph.get('links'), list):
        raise ValueError('输出字段流程需要节点和连线。')
    nodes = graph['nodes']
    if len(nodes) != len(KINDS) or any(
        not isinstance(node, dict) or node.get('kind') not in KINDS
        or not isinstance(node.get('id'), str)
        or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,48}', node['id'])
        or node.get('hint', '') or node.get('probe', False)
        for node in nodes
    ):
        raise ValueError('输出字段流程需要六个节点，使用固定规则。')
    by_kind = {node['kind']: node['id'] for node in nodes}
    if len(by_kind) != len(KINDS) or len(set(by_kind.values())) != len(KINDS):
        raise ValueError('输出字段节点类型或 ID 重复。')
    ordered_ids = [by_kind[kind] for kind in KINDS]
    expected = {(ordered_ids[a], ordered_ids[b]) for a, b in EDGES}
    links = graph['links']
    if len(links) != len(expected) or any(
        not isinstance(link, dict) or not isinstance(link.get('source'), str)
        or not isinstance(link.get('target'), str)
        for link in links
    ) or {(link['source'], link['target']) for link in links} != expected:
        raise ValueError('请连接匹配的两条分支、归一后的字段复核及 SQL 执行。')
    return [{'id': node_id, 'kind': kind, 'hint': '', 'probe': False,
             'from': [ordered_ids[a] for a, b in EDGES if b == i]}
            for i, (node_id, kind) in enumerate(zip(ordered_ids, KINDS))]


def verified_name(case):
    schema = columns_for(case.database)
    candidates = [(table, field) for table, columns in schema.items()
                  if table.lower() in {'highschooler', 'student', 'students'}
                  for field in columns if field.lower() == 'name']
    if len(candidates) != 1:
        return None
    return '.'.join(candidates[0])


def projection_step(node, case, model, upstream, complete):
    kind = node['kind']
    if kind == 'projection_match':
        question = case.question.strip().lower().rstrip('?.')
        explicit = EXPLICIT.fullmatch(question) is not None
        field = verified_name(case) if explicit else None
        return {'status': 'verified' if field else 'unresolved', 'field': field,
                'reason': '明确请求姓名，并确认库中字段' if field else '未确认明确的姓名输出'}, None
    if kind == 'projection_normalize':
        if upstream[0]['output']['field']:
            return {'status': 'skipped', 'candidate': None, 'reason': '直接匹配已核验'}, None
        question = case.question.strip().lower().rstrip('?.')
        candidate = 'student.name' if IMPLICIT.fullmatch(question) else None
        return {'status': 'candidate' if candidate else 'unresolved', 'candidate': candidate,
                'reason': '将 who 指代归一为学生姓名' if candidate else '题面不满足姓名推断规则'}, None
    if kind == 'projection_recheck':
        normalized = upstream[0]['output']
        field = verified_name(case) if normalized['candidate'] else None
        status = 'verified' if field else normalized['status'] if normalized['status'] == 'skipped' else 'unresolved'
        return {'status': status, 'field': field,
                'reason': '当前库中存在唯一学生姓名列' if field else '没有需要确认的唯一姓名列'}, None
    if kind == 'projection_constraint':
        direct, checked = [item['output']['field'] for item in upstream]
        field = direct or checked
        route = 'direct' if direct else 'normalized' if checked else 'fallback'
        hint = (f'Return only the requested student name from {field}. Fields used to filter, identify, '
                'or order rows do not belong in the output unless explicitly requested.') if field else ''
        return {'route': route, 'field': field, 'hint': hint}, None
    if kind == 'projection_generate':
        hint = upstream[0]['output']['hint']
        evidence = [{'kind': 'plan', 'output': hint}] if hint else []
        return step_node({**node, 'kind': 'generate'}, case, model, evidence, complete)
    return step_node(node, case, model, upstream, complete)
