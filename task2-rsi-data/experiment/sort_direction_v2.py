"""Require a field-meaning explanation before resolving substitute sort direction."""

from experiment import step_node
from sort_direction_canvas import GRAPH, fallback, single_target, sort_step, validate_sort

MEANING_KIND = 'sort_meaning_v2'
GRAPH_V2 = {**GRAPH, 'nodes': [
    {**node, 'kind': MEANING_KIND} if node['kind'] == 'sort_direction' else dict(node)
    for node in GRAPH['nodes']
]}
MEANING_DECISION = (
    'Resolve the sort direction of one verified candidate, in this order. '
    'First state requested_quantity: what the question means to compare. '
    'Then state column_meaning: translate the exact identifier into plain language and describe '
    'the quantity, unit, and entity suggested by the schema and corroborated by the SQLite samples. '
    'Distinguish a calendar event year, elapsed years since the event, and an unrelated quantity. '
    'For a column that denotes elapsed years and has duration-like values, with the same event and '
    'entity as the question, a shared snapshot is a reasonable interpretation unless the schema '
    'or data indicates differing reference times. The exact reference year is unnecessary for ranking. '
    'Then decide relation: same if ordering by the candidate preserves ordering of the requested '
    'quantity, reverse if it inverts it, or unknown if the meaning, event, or relationship is ambiguous. '
    'For example, later opening year means fewer years since opening at a common snapshot; '
    'the relation between opening year and elapsed years since opening is reverse. '
    'Read the sort cue in the question before reasoning. Report only the relationship between the '
    'two quantities, independently of the requested ASC or DESC. '
    'Return JSON {"targets":[{"requested_quantity":"plain description","column_meaning":"plain '
    'description of stored value","relation":"same|reverse|unknown","reason":"tie the interpretation '
    'to the field and sample evidence"}]}. Use unknown if no grounded interpretation is possible. '
    'Do not output SQL.'
)


def is_sort_v2(graph):
    return isinstance(graph, dict) and isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') == MEANING_KIND for node in graph['nodes'])


def validate_sort_v2(graph):
    if not is_sort_v2(graph) or any(
        isinstance(node, dict) and node.get('kind') == 'sort_direction' for node in graph['nodes']
    ):
        raise ValueError('v2 需要使用字段含义与排序判断节点。')
    v1_nodes = [{**node, 'kind': 'sort_direction'}
                if isinstance(node, dict) and node.get('kind') == MEANING_KIND else node
                for node in graph['nodes']]
    nodes = validate_sort({**graph, 'nodes': v1_nodes})
    return [{**node, 'kind': MEANING_KIND} if node['kind'] == 'sort_direction' else node for node in nodes]


def sort_step_v2(node, case, model, upstream, complete):
    if node['kind'] != MEANING_KIND:
        return sort_step(node, case, model, upstream, complete)
    previous = upstream[0]['output']
    if previous['route'] != 'similar':
        return {**previous, 'agent_skipped': True}, None
    judgment, call = step_node({**node, 'kind': 'extract', 'hint': MEANING_DECISION}, case, model,
                               [{'kind': 'lookup', 'output': previous}], complete)
    decision = single_target(judgment)
    relation = decision.get('relation')
    semantic_fields = ('requested_quantity', 'column_meaning', 'reason')
    if relation not in ('same', 'reverse') or any(
        not isinstance(decision.get(field), str) or not decision[field].strip()
        for field in semantic_fields
    ):
        return {**fallback('field_meaning_or_direction_uncertain'), 'candidate': previous,
                'judgment': decision}, call
    direction = previous['direction']
    if relation == 'reverse':
        direction = 'ASC' if direction == 'DESC' else 'DESC'
    return {**previous, 'original_direction': previous['direction'], 'direction': direction,
            'relation': relation, **{field: decision[field] for field in semantic_fields}}, call
