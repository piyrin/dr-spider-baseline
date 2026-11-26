"""Apply the declared output grain for the two sides of the Top N anchor."""

import re

from experiment import execute_sql, ident
from top_n_canvas import GRAPH as BASE_GRAPH, ORIGINAL, inspect, top_n_step, validate_top_n

MODE = 'winner_name_rank'
GRAPH = {**BASE_GRAPH, 'nodes': [{**node, 'hint': MODE}
                                  if node['kind'] == 'top_n_policy' else dict(node)
                                  for node in BASE_GRAPH['nodes']]}


def is_original_graph(graph):
    return isinstance(graph, dict) and isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') == 'top_n_policy' and node.get('hint') == MODE
        for node in graph['nodes'])


def validate(graph, case=None):
    if not is_original_graph(graph) or (case is not None and case.id not in ORIGINAL):
        raise ValueError('按姓名和排名的预设仅适用于第 7 题原题的两个题面。')
    compatible = {**graph, 'nodes': [{**node, 'hint': ''}
                                    if isinstance(node, dict) and node.get('kind') == 'top_n_policy'
                                    and node.get('hint') == MODE else node for node in graph['nodes']]}
    ordered = validate_top_n(compatible)
    return [{**node, 'hint': MODE} if node['kind'] == 'top_n_policy' else node for node in ordered]


def run_step(node, case, model, upstream, complete):
    kind = node['kind']
    if kind == 'top_n_inspect':
        cue = re.search(r'\b(\d+) youngest winners\b', case.question, re.I)
        if not cue:
            return {'reason': 'limit_or_sort_cue_missing'}, None
        target = {
            'table': 'matches', 'fields': ['winner_name', 'winner_rank'], 'order_column': 'winner_age',
            'direction': 'ASC', 'n': int(cue[1]), 'grain': 'tuple', 'cue': cue[0],
        }
        evidence = inspect(case, {'targets': [target]})
        return {**evidence, 'policy_source': 'canvas_preset', 'agent_intent': upstream[0]['output']}, None
    if kind == 'top_n_policy':
        evidence = upstream[0]['output']
        route = 'fallback' if 'reason' in evidence else 'tuple'
        return {**evidence, 'route': route, 'semantic_ambiguity': True}, None

    result, call = top_n_step(node, case, model, upstream, complete)
    if kind != 'top_n_execute' or result['route'] != 'tuple':
        return result, call
    decision = upstream[0]['output']['decision']
    fields = ', '.join(map(ident, decision['fields']))
    age, table = ident(decision['order_column']), ident(decision['table'])
    sql = (f'SELECT {fields} FROM {table} WHERE {age} IS NOT NULL GROUP BY {fields} '
           f'ORDER BY MIN({age}) ASC, {fields} LIMIT {decision["n"]}')
    expected = execute_sql(case.database, sql)
    if expected['status'] != 'executed':
        raise ValueError('Could not execute the verified Top N policy')
    same_rows = result.get('rows') == expected['rows']
    checked = result if same_rows else expected
    return {**checked, 'route': 'tuple', 'agent_sql': result.get('sql'),
            'policy_check': 'agent_match' if same_rows else 'policy_query_used',
            'policy_sql': sql}, call
