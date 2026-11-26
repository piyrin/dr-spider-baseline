"""Run Top N with an explicit, verified result unit or take an ambiguity branch."""

import re

from experiment import Scenario, columns_for, execute_sql, ident, step_node

STEM = 'SQL_NonDB_number-00054'
ORIGINAL = [f'{STEM}-{side}' for side in ('pre', 'post')]
RELATED = ['SQL_NonDB_number-00061-pre', 'SQL_NonDB_number-00061-post']
CONTROLS = [f'top-n-{grain}-{side}' for grain in ('pair', 'person') for side in ('pre', 'post')]
EXAMPLES = [*ORIGINAL, *RELATED, *CONTROLS]
IDS = ('intent', 'inspect', 'policy', 'generate', 'execute')
KINDS = ('top_n_intent', 'top_n_inspect', 'top_n_policy', 'top_n_generate', 'top_n_execute')
GRAPH = {
    'nodes': [{'id': node_id, 'kind': kind} for node_id, kind in zip(IDS, KINDS)],
    'links': [{'source': a, 'target': b} for a, b in zip(IDS, IDS[1:])],
}
INTERACTIVE_GRAPH = {**GRAPH, 'nodes': [{**node, 'hint': 'interactive'}
                                      if node['kind'] == 'top_n_policy' else dict(node)
                                      for node in GRAPH['nodes']]}
CLARIFICATION = ('前 N 项是指 N 位不同的选手，还是 N 个不同的姓名和排名组合？')
INTENT = (
    'Extract one simple row-based top-N request with one sort column and one table. '
    'Return JSON {"targets":[{"table":"actual table","fields":["actual output columns in question order"],'
    '"order_column":"actual column","direction":"ASC|DESC","n":5,'
    '"grain":"tuple|person|rows|ambiguous","person_key":"actual stable entity identifier, if relevant",'
    '"cue":"exact contiguous quote showing explicit grain, or an ambiguous top-N phrase"}]}. '
    'Use tuple only if the question explicitly asks for distinct combinations or pairs. Use person only '
    'for an explicit request for distinct people, different players or one entry per person. Use rows for '
    'an explicit request for individual records. If each result could be a person or a combination of '
    'output attributes, use ambiguous. A plural noun such as winners and requested display attributes '
    'alone do not specify a deduplication key. Return {"targets":[]} for unrelated, aggregated, or '
    'unsupported sorts. Do not write SQL.'
)
WORDS = ('one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten')


def original_or_control(sample_id):
    if sample_id not in CONTROLS:
        return Scenario.from_id(sample_id)
    grain, side = sample_id.split('-')[-2:]
    base = Scenario.from_id(f'{STEM}-{side}')
    n = 3 if side == 'pre' else 5
    if grain == 'pair':
        question = (f'Across all matches, return the {n} distinct name-and-rank combinations of winners '
                    'with the lowest age recorded for each combination. Output winner name and rank.')
        reference = ('SELECT winner_name, winner_rank FROM (SELECT winner_name, winner_rank, '
                     'winner_age, row_number() OVER (PARTITION BY winner_name, winner_rank '
                     'ORDER BY winner_age) AS rn FROM matches WHERE winner_age IS NOT NULL) '
                     f'WHERE rn = 1 ORDER BY winner_age, winner_name, winner_rank LIMIT {n}')
    else:
        question = (f'Find the {n} youngest distinct individual players to win a match. Return one row per '
                    'player ID, with the name and rank from their youngest recorded win. If a player '
                    'has multiple wins at that age, use the earliest tournament date and lowest match number.')
        reference = ('SELECT m.winner_name, m.winner_rank FROM matches AS m '
                     'WHERE m.winner_age IS NOT NULL AND m.rowid = (SELECT a.rowid FROM matches AS a '
                     'WHERE a.winner_id=m.winner_id AND a.winner_age IS NOT NULL '
                     'ORDER BY a.winner_age, a.tourney_date, a.match_num, a.rowid LIMIT 1) '
                     f'ORDER BY m.winner_age, m.winner_id LIMIT {n}')
    return Scenario(sample_id, question, base.database, reference)


def is_top_n(graph):
    return isinstance(graph, dict) and isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') in KINDS for node in graph['nodes'])


def validate_top_n(graph):
    nodes, links = graph.get('nodes'), graph.get('links')
    if not isinstance(nodes, list) or len(nodes) != len(KINDS) or not isinstance(links, list):
        raise ValueError('Top N 编排需要五个节点。')
    by_kind, seen = {}, set()
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError('Top N 节点格式有误。')
        node_id, kind, hint = node.get('id'), node.get('kind'), node.get('hint') or ''
        if (not isinstance(node_id, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,48}', node_id)
                or node_id in seen or kind not in KINDS or kind in by_kind
                or hint not in (('', 'interactive') if kind == 'top_n_policy' else ('',))
                or node.get('probe')):
            raise ValueError('Top N 节点重复或配置有误。')
        seen.add(node_id)
        by_kind[kind] = (node_id, hint)
    order = [by_kind[kind][0] for kind in KINDS]
    expected = list(zip(order, order[1:]))
    actual = [(link.get('source'), link.get('target')) for link in links if isinstance(link, dict)]
    if len(links) != len(expected) or len(actual) != len(links) or any(link not in actual for link in expected):
        raise ValueError('请依次连接题意、库验证、分支、生成和执行。')
    return [{'id': order[i], 'kind': kind, 'hint': by_kind[kind][1], 'probe': False,
             'from': order[max(0, i - 1):i]} for i, kind in enumerate(KINDS)]


def normalized(text):
    return ' '.join(re.findall(r'\w+', text.casefold()))


def inspect(case, intent):
    targets = intent.get('targets', [])
    if len(targets) != 1 or not isinstance(targets[0], dict):
        return {'reason': 'no_single_top_n_candidate'}
    candidate = targets[0]
    n, cue = candidate.get('n'), candidate.get('cue')
    fields, direction = candidate.get('fields'), candidate.get('direction')
    if (type(n) is not int or not 1 <= n <= 500 or direction not in ('ASC', 'DESC')
            or not isinstance(cue, str) or not normalized(cue)
            or f' {normalized(cue)} ' not in f' {normalized(case.question)} '
            or not isinstance(fields, list) or not 1 <= len(fields) <= 6):
        return {'reason': 'unverified_top_n_intent'}
    words = set(normalized(case.question).split())
    if str(n) not in words and (n > len(WORDS) or WORDS[n - 1] not in words):
        return {'reason': 'unverified_limit'}
    schema = columns_for(case.database)
    table = next((t for t in schema if t.casefold() == str(candidate.get('table')).casefold()), None)
    columns = {c.casefold(): c for c in schema.get(table, {})}
    fields = [columns.get(str(field).casefold()) for field in fields]
    ordering = columns.get(str(candidate.get('order_column')).casefold())
    person = columns.get(str(candidate.get('person_key')).casefold())
    if not all(fields) or not ordering or len(set(fields)) != len(fields):
        return {'reason': 'unverified_columns'}
    keys = ', '.join(map(ident, fields))
    order_sql = ident(ordering)
    duplicate = execute_sql(case.database, f'SELECT COUNT(*), COUNT(DISTINCT {order_sql}) FROM {ident(table)} '
                            f'WHERE {order_sql} IS NOT NULL GROUP BY {keys} '
                            f'HAVING COUNT(*) > 1 ORDER BY COUNT(DISTINCT {order_sql}) DESC LIMIT 1')
    if duplicate['status'] != 'executed':
        return {'reason': 'duplicate_probe_failed'}
    probe = duplicate['rows'][0] if duplicate['rows'] else (0, 0)
    return {'table': table, 'fields': fields, 'order_column': ordering, 'person_key': person,
            'n': n, 'direction': direction, 'grain': candidate.get('grain'), 'cue': cue,
            'duplicate_group': bool(probe[0]), 'example_group_rows': probe[0],
            'example_group_order_values': probe[1]}


def choose(evidence, interactive):
    if 'reason' in evidence:
        return {**evidence, 'route': 'fallback', 'semantic_ambiguity': False}
    cue = normalized(evidence['cue'])
    grain = evidence['grain']
    explicit_tuple = re.search(r'\b(?:distinct|unique|different)\b.*\b(?:combinations|pairs|tuples)\b', cue)
    explicit_person = re.search(r'\b(?:distinct|different|unique)\b.*\b(?:players|people|persons|winners)\b'
                                r'|\bone (?:row|entry) per (?:player|person)\b', cue)
    explicit_rows = re.search(r'\b(?:rows|records)\b', cue)
    if grain == 'tuple' and explicit_tuple and len(evidence['fields']) >= 2:
        return {**evidence, 'route': 'tuple'}
    if grain == 'person' and explicit_person and evidence['person_key']:
        return {**evidence, 'route': 'person'}
    if grain == 'rows' and explicit_rows:
        return {**evidence, 'route': 'fallback', 'reason': 'explicit_row_grain', 'semantic_ambiguity': False}
    reason = (CLARIFICATION if {'winner_name', 'winner_rank'} == set(evidence['fields'])
              else '前 N 项中，每一项应代表一个不同实体，还是一个不同的输出字段组合？')
    return {**evidence, 'route': 'clarification' if interactive else 'fallback',
            'reason': reason, 'semantic_ambiguity': True}


def top_n_step(node, case, model, upstream, complete):
    kind = node['kind']
    previous = upstream[0]['output'] if upstream else None
    if kind == 'top_n_intent':
        return step_node({**node, 'kind': 'extract', 'hint': INTENT}, case, model, [], complete)
    if kind == 'top_n_inspect':
        return inspect(case, previous), None
    if kind == 'top_n_policy':
        return choose(previous, node['hint'] == 'interactive'), None
    if kind == 'top_n_generate':
        if previous['route'] == 'clarification':
            return {'status': 'clarification', 'reason': previous['reason'], 'decision': previous}, None
        evidence = []
        if previous['route'] in ('tuple', 'person'):
            fields = ', '.join(previous['fields'])
            ordering = previous['order_column']
            direction = previous['direction']
            extreme = 'minimum' if direction == 'ASC' else 'maximum'
            unit = (f'Group by the distinct output combination ({fields}) and order groups by their '
                    f'{extreme} non-null {ordering}.' if previous['route'] == 'tuple' else
                    f'Retain one actual row per {previous["person_key"]}, selecting the row with '
                    f'{extreme} non-null {ordering}. Apply tie rules requested in the question.')
            plan = (f'For {previous["table"]}, {unit} Preserve other requested constraints, '
                    f'return only {fields} and apply LIMIT {previous["n"]} after grouping or selecting one row per entity.')
            evidence.append({'kind': 'plan', 'output': plan})
        output, call = step_node({**node, 'kind': 'generate'}, case, model, evidence, complete)
        return {**output, 'decision': previous}, call
    result, call = step_node({**node, 'kind': 'execute'}, case, model, upstream, complete)
    decision = previous['decision']
    if result['status'] == 'executed' and decision['route'] in ('tuple', 'person'):
        rows = result['rows']
        result['contract_check'] = {
            'column_count_matches': len(result['columns']) == len(decision['fields']),
            'at_most_n': len(rows) <= decision['n'],
            'unique_output_tuples': len(set(rows)) == len(rows) if decision['route'] == 'tuple' else None,
        }
    return {**result, 'route': decision['route']}, call
