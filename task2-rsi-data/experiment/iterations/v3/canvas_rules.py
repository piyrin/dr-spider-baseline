"""Composable SQLite checks that never make a model request."""

from hashlib import sha256
import json
import time

from experiment import execute_sql, field_probes, graph, step_node, validate_graph
from iterations.guarded_replay import replacements

RULES = {'literal': 'text_equivalent', 'year': 'four_digit_year'}
GRAPHS_V3 = {
    'literal_check': graph(('generate', 'execute_first', 'literal', 'execute'),
                           [('generate', 'execute_first'), ('execute_first', 'literal'), ('literal', 'execute')]),
    'year_check': graph(('generate', 'execute_first', 'year', 'execute'),
                        [('generate', 'execute_first'), ('execute_first', 'year'), ('year', 'execute')]),
    'guarded_local': graph(('generate', 'execute_first', 'literal', 'execute_value', 'year', 'execute'),
                           [('generate', 'execute_first'), ('execute_first', 'literal'),
                            ('literal', 'execute_value'), ('execute_value', 'year'), ('year', 'execute')]),
}


def validate_canvas(spec):
    if not isinstance(spec, dict) or not isinstance(spec.get('nodes'), list):
        return validate_graph(spec)
    kinds = {node['id']: node['kind'] for node in spec['nodes']
             if isinstance(node, dict) and node.get('kind') in RULES and isinstance(node.get('id'), str)}
    ordinary = [{**node, 'kind': 'review'} if isinstance(node, dict) and node.get('id') in kinds else node
                for node in spec['nodes']]
    return [{**node, 'kind': kinds.get(node['id'], node['kind'])}
            for node in validate_graph({**spec, 'nodes': ordinary})]


def canvas_digest(ordered):
    return sha256(json.dumps(ordered, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def check_literal(case, before, expected_rule):
    if before['status'] != 'executed' or not before.get('sql'):
        return before, None
    sql = before['sql']
    candidates = replacements(case, sql, allow_edge_padding=False)
    if len(candidates) != 1 or candidates[0][3] != expected_rule:
        return before, None
    start, end, value, rule, field = candidates[0]
    revised = execute_sql(case.database, sql[:start] + value + sql[end:])
    if (revised['status'] != 'executed' or revised['columns'] != before['columns']
            or revised['rows'] == before['rows']):
        return before, None
    return revised, {'rule': rule, 'field': field, 'before': sql[start:end], 'after': value}


def canvas_step(node, case, model, upstream, complete):
    kind = node['kind']
    if kind in RULES:
        final, patch = check_literal(case, upstream[0]['output'], RULES[kind])
        return {'checked': final, 'patch': patch}, None
    if kind == 'execute' and len(upstream) == 1 and upstream[0]['kind'] in RULES:
        output = upstream[0]['output']['checked']
        if node['probe'] and output.get('sql'):
            output = {**output, 'field_probes': field_probes(case, output['sql'])}
        return output, None
    return step_node(node, case, model, upstream, complete)


def run_canvas(spec, case, model, complete):
    ordered = validate_canvas(spec)
    steps = {}
    for node in ordered:
        started = time.monotonic()
        output, call = canvas_step(node, case, model, [steps[key] for key in node['from']], complete)
        steps[node['id']] = {**node, 'output': output, 'call': call, 'elapsed_s': time.monotonic() - started}
    return {'graph_sha256': canvas_digest(ordered), 'steps': list(steps.values()),
            'final': next(reversed(steps.values()))['output']}
