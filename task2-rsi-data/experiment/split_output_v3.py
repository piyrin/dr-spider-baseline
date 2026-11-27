"""Check a generated query against runtime evidence, with one proposed revision."""

from dataclasses import dataclass
import json
import re

from experiment import content_of, database_input, execute_sql, json_object, step_node

KINDS = ('sql_review_draft', 'sql_review_audit', 'sql_review_gate', 'sql_review_confirm', 'sql_review_execute')
IDS = ('draft', 'audit', 'gate', 'confirm', 'execute')
GRAPH_V3 = {
    'nodes': [{'id': node, 'kind': kind} for node, kind in zip(IDS, KINDS)],
    'links': [{'source': parent, 'target': child} for parent, child in zip(IDS, IDS[1:])],
}
DIMENSIONS = ('projection', 'filter', 'join', 'grouping', 'distinct', 'order', 'limit', 'syntax')
OUTPUT_POLICY = (
    'Experiment output convention: if a requested person name is represented only by separate '
    'first/middle/last name fields for one entity, return the stored components in order, unless '
    'the question explicitly requests one combined display value. Keep lookup expressions independent '
    'of final projection. If a single stored complete name exists, keep it as one requested field.'
)
AUDIT = (
    'Audit the draft SQLite query against an independent reading of the question and current schema. '
    'Consider selected columns, population, filters, joins, result grain, aggregation, duplicate '
    'handling and order. Preserve the draft if sound, uncertain, or the proposed change depends '
    'on unavailable data or an unspecified sort direction. A clear issue merits at most one '
    'minimal revision. Preserve unrelated clauses. Return a single JSON object. Keep uses '
    '{"action":"keep","reason":"..."}. Revise uses {"action":"revise","dimension":"projection|filter|join|grouping|distinct|order|limit|syntax",'
    '"quote":"exact contiguous words copied from the question","reason":"specific conflict and schema evidence",'
    '"sql":"one complete read-only SQLite SELECT"}. Do not answer the query. ' + OUTPUT_POLICY
)
CONFIRM = (
    'Check the one proposed revision against the question and current schema. Accept only if the '
    'identified conflict has clear support, the proposed SQL resolves it, and unrelated intent '
    'is preserved. Reject when interpretations are ambiguous or the proposal changes unrelated '
    'semantics. Return a single JSON object {"accept":true or false,"reason":"specific review"}. '
    'Do not write any SQL. ' + OUTPUT_POLICY
)


@dataclass(frozen=True)
class ReviewInput:
    question: str
    database: str


def is_review_v3(graph):
    return isinstance(graph, dict) and isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') in KINDS for node in graph['nodes'])


def validate_v3(graph):
    nodes, links = graph.get('nodes'), graph.get('links')
    if not isinstance(nodes, list) or len(nodes) != len(KINDS) or not isinstance(links, list):
        raise ValueError('SQL 审查编排需要五个职责节点。')
    kinds, seen = {}, set()
    for node in nodes:
        node_id, kind = node.get('id'), node.get('kind')
        if (not isinstance(node_id, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,48}', node_id)
                or node_id in seen or kind not in KINDS or kind in kinds or node.get('hint') or node.get('probe')):
            raise ValueError('SQL 审查节点的 ID、类型或配置有误。')
        seen.add(node_id)
        kinds[kind] = node_id
    order = [kinds[kind] for kind in KINDS]
    if sorted((link.get('source', ''), link.get('target', '')) for link in links) != sorted(zip(order, order[1:])):
        raise ValueError('请依次连接初稿、审查、核验、确认和执行。')
    return [{'id': node, 'kind': kind, 'hint': '', 'probe': False,
             'from': order[max(0, i-1):i]} for i, (node, kind) in enumerate(zip(order, KINDS))]


def ask(node, case, model, instruction, evidence, complete):
    schema = database_input(case.database)['schema']
    user = f'Schema\n{schema}\nQuestion\n{case.question}\nSQL review input\n'
    payload = {'model': model, 'stream': False, 'messages': [
        {'role': 'system', 'content': instruction},
        {'role': 'user', 'content': user + json.dumps(evidence, ensure_ascii=False)},
    ]}
    response = complete(node['id'], payload)
    call = {'request': payload, 'response': response, 'usage': response.get('usage'),
            'model': response.get('model'), 'fingerprint': response.get('system_fingerprint')}
    try:
        return json_object(content_of(response)), call
    except (KeyError, TypeError, ValueError, IndexError) as error:
        call['format_error'] = str(error)
        return {}, call


def candidate_gate(case, draft, proposal):
    route = {'draft': draft, 'proposal': proposal}
    if proposal.get('action') != 'revise':
        return {**route, 'gate': 'keep' if proposal.get('action') == 'keep' else 'invalid_review'}
    sql, quote, reason = (proposal.get(field) for field in ('sql', 'quote', 'reason'))
    if (proposal.get('dimension') not in DIMENSIONS or not isinstance(quote, str)
            or len(quote.strip()) < 4 or quote.strip().casefold() not in case.question.casefold()
            or not isinstance(reason, str) or not reason.strip()):
        return {**route, 'gate': 'ungrounded'}
    if (not isinstance(sql, str) or not re.match(r'^\s*(SELECT|WITH)\b', sql, re.I)
            or sql.strip() == (draft.get('sql') or '').strip()):
        return {**route, 'gate': 'invalid_or_unchanged_sql'}
    query_plan = execute_sql(case.database, 'EXPLAIN QUERY PLAN ' + sql.strip())
    if query_plan['status'] != 'executed':
        return {**route, 'gate': 'sqlite_rejected', 'sqlite_reason': query_plan['reason']}
    return {**route, 'gate': 'eligible'}


def review_step(node, case, model, upstream, complete):
    kind = node['kind']
    previous = upstream[0]['output'] if upstream else None
    if kind == 'sql_review_draft':
        return step_node({**node, 'kind': 'generate'}, case, model, [], complete)
    if kind == 'sql_review_audit':
        proposal, call = ask(node, case, model, AUDIT, {'draft_sql': previous.get('sql')}, complete)
        return {'draft': previous, 'proposal': proposal}, call
    if kind == 'sql_review_gate':
        return candidate_gate(case, previous['draft'], previous['proposal']), None
    if kind == 'sql_review_confirm':
        if previous['gate'] != 'eligible':
            return {**previous, 'final': previous['draft'], 'revision': 'skipped'}, None
        verdict, call = ask(node, case, model, CONFIRM,
                            {'draft_sql': previous['draft'].get('sql'), 'proposal': previous['proposal']}, complete)
        accepted = verdict.get('accept') is True and isinstance(verdict.get('reason'), str) and bool(verdict['reason'].strip())
        final = {'sql': previous['proposal']['sql'].strip()} if accepted else previous['draft']
        return {**previous, 'final': final, 'revision': 'accepted' if accepted else 'rejected',
                'verdict': verdict}, call
    if kind == 'sql_review_execute':
        final, call = step_node({**node, 'kind': 'execute'}, case, model,
                                [{'kind': 'generate', 'output': previous['final']}], complete)
        return {**final, 'revision': previous['revision'], 'gate': previous['gate']}, call
    raise ValueError(f'Unknown SQL review node {kind}')
