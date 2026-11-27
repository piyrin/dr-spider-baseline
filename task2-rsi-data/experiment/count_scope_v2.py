"""Add a documented Dr.Spider default for single related-count upper bounds."""

from contextlib import closing
import re

from count_scope_canvas import ABSENCE_CUE, GRAPH, count_step, resolve_scope, validate_count
from experiment import ident, read_connection


POLICY = 'count_policy_v2'
GRAPH_V2 = {**GRAPH, 'nodes': [{**node, 'kind': POLICY} if node['id'] == 'policy' else node
                               for node in GRAPH['nodes']]}
NUMBERS = {word: value for value, word in enumerate(
    'zero one two three four five six seven eight nine ten'.split())}
NUMBER = r'(\d{1,6}|' + '|'.join(NUMBERS) + ')'
PREFIX_BOUND = re.compile(r'\b(less than|fewer than|under|at most|no more than|no greater than)\s+' + NUMBER + r'\b', re.I)
SUFFIX_BOUND = re.compile(r'\b' + NUMBER + r'\s+or\s+(?:less|fewer)\b', re.I)
COMPOUND = re.compile(r'\b(?:or|either|unless|except|but|also)\b', re.I)
EXPLICIT_SCOPE = re.compile(r'\b(?:do(?:es)?|did)\s+not\b|\beven if\b|\bincluding\b', re.I)


def is_count_v2(graph):
    return isinstance(graph, dict) and isinstance(graph.get('nodes'), list) and any(
        isinstance(node, dict) and node.get('kind') == POLICY for node in graph['nodes'])


def validate_count_v2(graph):
    if not is_count_v2(graph):
        raise ValueError('第 5 题 v2 需要统计口径 v2 节点。')
    old_graph = {**graph, 'nodes': [{**node, 'kind': 'count_policy'} if node.get('kind') == POLICY else node
                                    for node in graph['nodes']]}
    return [{**node, 'kind': POLICY} if node['kind'] == 'count_policy' else node
            for node in validate_count(old_graph)]


def upper_bound(question):
    def number(text):
        return int(text) if text.isdecimal() else NUMBERS[text.casefold()]

    bound = [(('<=' if m[1].casefold() in ('at most', 'no more than', 'no greater than') else '<'),
              number(m[2])) for m in PREFIX_BOUND.finditer(question)]
    bound.extend(('<=', number(m[1])) for m in SUFFIX_BOUND.finditer(question))
    without_bounds = SUFFIX_BOUND.sub('', PREFIX_BOUND.sub('', question))
    if len(bound) == 1 and not any(pattern.search(without_bounds) for pattern in
                                  (ABSENCE_CUE, COMPOUND, EXPLICIT_SCOPE)):
        return bound[0]
    return None


def verified_keys(case, decision):
    parent, parent_key, detail, detail_key = (decision[k] for k in
        ('parent_table', 'parent_key', 'detail_table', 'detail_key'))
    with closing(read_connection(case.database)) as db:
        keys = [row[1] for row in db.execute(f'PRAGMA table_info({ident(parent)})') if row[5]]
        foreign = [row for row in db.execute(f'PRAGMA foreign_key_list({ident(detail)})')
                   if row[3].casefold() == detail_key.casefold()]
    if foreign:
        return keys == [parent_key] and len(foreign) == 1 and (
            foreign[0][2].casefold() == parent.casefold()
            and (foreign[0][4] or parent_key).casefold() == parent_key.casefold())
    return keys == [parent_key]


def resolve_scope_v2(case, extracted):
    v1 = resolve_scope(case, extracted)
    if v1.get('reason') not in ('uncertain_scope', 'zero_scope_not_explicit'):
        return v1
    targets = extracted.get('targets')
    if not isinstance(targets, list) or len(targets) != 1:
        return v1
    target = targets[0]
    bound = upper_bound(case.question)
    if bound is None or bound != (target.get('operator'), target.get('threshold')):
        return v1
    observed = resolve_scope(case, {'targets': [{**target, 'policy': 'observed'}]})
    if observed['route'] != 'observed' or not verified_keys(case, observed):
        return v1
    return {**observed, 'basis': 'benchmark_default'}


def count_step_v2(node, case, model, upstream, complete):
    if node['kind'] == POLICY:
        return resolve_scope_v2(case, upstream[0]['output']), None
    return count_step(node, case, model, upstream, complete)
