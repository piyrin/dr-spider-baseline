"""Verify two unambiguous SQL forms after count-scope generation."""

import re

from count_scope_v2 import GRAPH_V2, count_step_v2, validate_count_v2

CHECK = 'count_sql_check'
GRAPH_V3 = {
    'nodes': [*GRAPH_V2['nodes'][:-1], {'id': 'check', 'kind': CHECK}, GRAPH_V2['nodes'][-1]],
    'links': [*GRAPH_V2['links'][:-1], {'source': 'policy', 'target': 'check'},
              {'source': 'generate', 'target': 'check'}, {'source': 'check', 'target': 'execute'}],
}
IDENTIFIER = r'(?:"[A-Za-z_]\w*"|[A-Za-z_]\w*)'
COLUMN = IDENTIFIER + r'\s*\.\s*' + IDENTIFIER
COUNT = r'COUNT\s*\(\s*(?:DISTINCT\s+)?(?P<count_column>' + COLUMN + r'|\*)\s*\)'
QUERY = re.compile(
    r'\s*SELECT\s+(?P<projection>.+?)\s+FROM\s+'
    rf'(?P<parent>{IDENTIFIER})\s+(?:AS\s+)?(?P<parent_alias>{IDENTIFIER})\s+'
    r'(?P<join>LEFT\s+(?:OUTER\s+)?JOIN)\s+'
    rf'(?P<detail>{IDENTIFIER})\s+(?:AS\s+)?(?P<detail_alias>{IDENTIFIER})\s+'
    rf'ON\s+(?P<first>{COLUMN})\s*=\s*(?P<second>{COLUMN})\s+'
    rf'GROUP\s+BY\s+(?P<group>{COLUMN}(?:\s*,\s*{COLUMN})*)\s+'
    rf'HAVING\s+{COUNT}\s*(?P<operator><=|<|=)\s*(?P<threshold>\d+)\s*;?\s*',
    re.I | re.S)
EXTREME = re.compile(rf'\s*(MIN|MAX)\s*\(\s*({COLUMN})\s*\)\s*', re.I)
EXTREME_WORDS = {'MIN': re.compile(r'\b(?:minimum|lowest)\b', re.I),
                 'MAX': re.compile(r'\b(?:maximum|highest)\b', re.I)}


def is_count_v3(graph):
    return isinstance(graph, dict) and isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') == CHECK for node in graph['nodes'])


def validate_count_v3(graph):
    if (not is_count_v3(graph) or len(graph['nodes']) != 5
            or not all(isinstance(node, dict) for node in graph['nodes'])
            or not isinstance(graph.get('links'), list)
            or not all(isinstance(link, dict) for link in graph['links'])):
        raise ValueError('第 5 题 v3 需要五个固定职责节点。')
    checks = [node for node in graph['nodes'] if node.get('kind') == CHECK]
    if len(checks) != 1:
        raise ValueError('SQL 核验节点须出现一次。')
    check = checks[0]
    check_id = check.get('id')
    if (not isinstance(check_id, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,48}', check_id)
            or any(node.get('id') == check_id for node in graph['nodes'] if node is not check)
            or check.get('hint') or check.get('probe')):
        raise ValueError('SQL 核验节点配置无效。')
    nodes = [node for node in graph['nodes'] if node is not check]
    by_kind = {node.get('kind'): node.get('id') for node in nodes}
    policy, generate, execute = (by_kind.get(kind) for kind in ('count_policy_v2', 'count_generate', 'execute'))
    touching = [(link.get('source'), link.get('target')) for link in graph['links']
                if check_id in (link.get('source'), link.get('target'))]
    if len(touching) != 3 or set(touching) != {(policy, check_id), (generate, check_id), (check_id, execute)}:
        raise ValueError('SQL 核验接收口径与生成 SQL，再输出到 SQLite。')
    links = [link for link in graph['links'] if check_id not in (link.get('source'), link.get('target'))]
    ordered = validate_count_v2({'nodes': nodes, 'links': [*links, {'source': generate, 'target': execute}]})
    return [*ordered[:-1], {**check, 'from': [policy, generate]},
            {**ordered[-1], 'from': [check_id]}]


def normalized(value):
    return re.sub(r'["\s]', '', value).casefold()


def verify_sql_scope(case, decision, draft):
    original = {**draft, 'check': 'unchanged'}
    sql = draft.get('sql')
    route = decision['route']
    if not isinstance(sql, str) or route not in ('observed', 'zero'):
        return original
    match = QUERY.fullmatch(sql)
    if not match or re.search(r'\b(?:SELECT|UNION|FROM)\b', match['projection'], re.I):
        return original
    parent_alias, detail_alias = map(normalized, (match['parent_alias'], match['detail_alias']))
    parent_key = parent_alias+'.'+decision['parent_key'].casefold()
    group = [normalized(column) for column in match['group'].split(',')]
    keys = {parent_key, detail_alias+'.'+decision['detail_key'].casefold()}
    if (normalized(match['parent']) != decision['parent_table'].casefold()
            or normalized(match['detail']) != decision['detail_table'].casefold()
            or {normalized(match[k]) for k in ('first', 'second')} != keys
            or parent_key not in group or any(not column.startswith(parent_alias+'.') for column in group)
            or (match['operator'], int(match['threshold'])) != (decision['operator'], decision['threshold'])):
        return original
    if route == 'observed':
        left, right = match.span('join')
        return {**draft, 'sql': sql[:left]+'JOIN'+sql[right:], 'check': 'required_detail'}
    extreme = EXTREME.fullmatch(match['projection'])
    count_column = normalized(match['count_column'])
    if (not extreme or decision['operator'] != '=' or decision['threshold'] != 0
            or not count_column.startswith(detail_alias+'.')
            or not normalized(extreme[2]).startswith(parent_alias+'.')
            or not EXTREME_WORDS[extreme[1].upper()].search(case.question)
            or re.search(r'\b(?:each|every|per|respectively)\b', case.question, re.I)):
        return original
    aggregate = extreme[1].upper()
    index = match.end('projection')
    grouped = (sql[:index]+' AS group_value'+sql[index:]).strip().rstrip(';')
    return {**draft, 'sql': f'SELECT {aggregate}(group_value) FROM ({grouped})',
            'check': 'global_extreme'}


def count_step_v3(node, case, model, upstream, complete):
    if node['kind'] == CHECK:
        return verify_sql_scope(case, upstream[0]['output'], upstream[1]['output']), None
    return count_step_v2(node, case, model, upstream, complete)
