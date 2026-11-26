"""Expose one-call user-message candidates as manually composable canvas nodes."""

from deployment import generate_scoped
from iterations.v3.canvas_rules import GRAPHS_V3, canvas_step, validate_canvas

MODES = {'scope_compact': 'C', 'scope_full': 'U'}


def preset(kind):
    previous = GRAPHS_V3['guarded_local']
    return {**previous, 'nodes': [{**node, 'kind': kind} if node['kind'] == 'generate' else node
                                  for node in previous['nodes']]}


SCOPED_GRAPHS = {mode: preset(kind) for kind, mode in MODES.items()}


def validate_scoped(spec):
    if not isinstance(spec, dict) or not isinstance(spec.get('nodes'), list):
        return validate_canvas(spec)
    kinds = {node['id']: node['kind'] for node in spec['nodes'] if isinstance(node, dict)
             and isinstance(node.get('kind'), str) and node['kind'] in MODES and isinstance(node.get('id'), str)}
    nodes = [{**node, 'kind':'generate'} if isinstance(node, dict) and node.get('id') in kinds else node
             for node in spec['nodes']]
    result = validate_canvas({**spec, 'nodes':nodes})
    for node in result:
        if node['id'] in kinds:
            if node['from'] or node['hint'] or node['probe']:
                raise ValueError('语义 SQL 节点只接受题面、数据库结构和固定提示，不接受输入连线或自定义参数。')
            node['kind'] = kinds[node['id']]
    return result


def scoped_step(node, case, model, upstream, complete):
    kind = node['kind']
    if kind not in MODES:
        return canvas_step(node, case, model, upstream, complete)
    call = None

    def invoke(payload):
        nonlocal call
        response = complete(node['id'], payload)
        call = {'request':payload, 'response':response, 'usage':response.get('usage'),
                'model':response.get('model'), 'fingerprint':response.get('system_fingerprint')}
        return response

    output = generate_scoped(MODES[kind], case, model, invoke)
    return output, call
