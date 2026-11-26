"""Executable graph nodes shared by RSI Data and the paired experiment."""

from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts'))
from run_full_evaluation import (SYSTEM, database_input, gold_rows, iter_samples,
                                 prediction_sql, result_eq)

KINDS = ('extract', 'lookup', 'plan', 'generate', 'execute', 'review')


def graph(nodes, links, probes=()):
    return {'nodes': [{'id': node, 'kind': node.split('_')[0],
                       **({'probe': True} if node in probes else {})} for node in nodes],
            'links': [{'source': a, 'target': b} for a, b in links]}


GRAPHS = {
    'baseline': graph(('generate', 'execute'), [('generate', 'execute')]),
    'value': graph(('extract', 'lookup', 'generate', 'execute'),
                   [('extract', 'lookup'), ('extract', 'generate'),
                    ('lookup', 'generate'), ('generate', 'execute')]),
    'without_values': graph(('extract', 'generate', 'execute'),
                            [('extract', 'generate'), ('generate', 'execute')]),
    'same_evidence': graph(('extract', 'lookup', 'generate', 'execute'),
                           [('extract', 'lookup'), ('lookup', 'generate'), ('generate', 'execute')]),
    'plan': graph(('extract', 'plan', 'generate', 'execute'),
                  [('extract', 'plan'), ('extract', 'generate'),
                   ('plan', 'generate'), ('generate', 'execute')]),
    'review': graph(('generate', 'execute_first', 'review', 'execute'),
                    [('generate', 'execute_first'), ('execute_first', 'review'),
                     ('review', 'execute')], probes=('execute_first',)),
}


@lru_cache(maxsize=1)
def samples_by_id():
    return {row['id']: row for row in iter_samples()}


@dataclass(frozen=True)
class Scenario:
    id: str
    question: str
    database: str
    gold_sql: str

    @classmethod
    def from_id(cls, sample_id):
        row = samples_by_id()[sample_id]
        return cls(*(row[name] for name in ('id', 'question', 'database', 'gold_sql')))


def validate_graph(spec):
    if (not isinstance(spec, dict) or not isinstance(spec.get('nodes'), list)
            or not isinstance(spec.get('links'), list)):
        raise ValueError('图需要节点和连线。')
    if not 2 <= len(spec['nodes']) <= 10 or len(spec['links']) > 24:
        raise ValueError('每张图需要 2 至 10 个节点，最多 24 条连线。')
    nodes = {}
    for node in spec['nodes']:
        node_id, kind = node.get('id'), node.get('kind')
        if (not isinstance(node_id, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,48}', node_id)
                or kind not in KINDS or node_id in nodes):
            raise ValueError('节点 ID、类型或重复节点有误。')
        hint = node.get('hint', '')
        if not isinstance(hint, str) or len(hint) > 500 or type(node.get('probe', False)) is not bool:
            raise ValueError('节点提示不能超过 500 字，探查参数必须为布尔值。')
        nodes[node_id] = {'id': node_id, 'kind': kind, 'hint': hint, 'probe': node.get('probe', False)}
    sources = defaultdict(list)
    targets = defaultdict(list)
    for link in spec['links']:
        a, b = link.get('source'), link.get('target')
        if a not in nodes or b not in nodes or a == b or a in sources[b]:
            raise ValueError('连线有未知端点、自环或重复。')
        sources[b].append(a)
        targets[a].append(b)
    required = {'lookup': {'extract'}, 'review': {'execute'}, 'execute': {'generate', 'review'}}
    accepted = {'extract': set(), 'lookup': {'extract'}, 'plan': {'extract', 'lookup'},
                'generate': {'extract', 'lookup', 'plan'}, 'execute': {'generate', 'review'},
                'review': {'execute'}}
    ends = [node_id for node_id in nodes if not targets[node_id]]
    if len(ends) != 1 or nodes[ends[0]]['kind'] != 'execute':
        raise ValueError('图只允许一个终点，终点必须为执行节点。')
    for node_id, node in nodes.items():
        kind = node['kind']
        inputs = [nodes[parent]['kind'] for parent in sources[node_id]]
        if (set(inputs) - accepted[kind] or len(inputs) != len(set(inputs))
                or kind in required and (len(inputs) != 1 or inputs[0] not in required[kind])):
            raise ValueError(f'{node_id} 的输入类型或数量有误。')
    ordered = []
    pending = dict(nodes)
    while pending:
        ready = [node_id for node_id in pending if all(parent in ordered for parent in sources[node_id])]
        if not ready:
            raise ValueError('流程包含循环连线。')
        for node_id in ready:
            ordered.append(node_id)
            del pending[node_id]
    return [{**nodes[node_id], 'from': sources[node_id]} for node_id in ordered]


def canonical(spec):
    return hashlib.sha256(json.dumps(validate_graph(spec), sort_keys=True,
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def ident(value):
    return '"' + value.replace('"', '""') + '"'


def read_connection(database):
    connection = sqlite3.connect((ROOT / database).resolve().as_uri() + '?mode=ro', uri=True)
    connection.execute('PRAGMA query_only=ON')
    started = time.monotonic()
    connection.set_progress_handler(lambda: int(time.monotonic() - started > 8), 1000)
    return connection


@lru_cache(maxsize=256)
def columns_for(database):
    with closing(read_connection(database)) as db:
        names = db.execute("SELECT name FROM sqlite_schema WHERE type='table' "
                           "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        return {row[0]: {column[1]: column[2] for column in
                         db.execute(f'PRAGMA table_info({ident(row[0])})')} for row in names}


def execute_sql(database, sql):
    allowed = {t.lower() for t in columns_for(database)}

    def authorize(action, arg1, arg2, db, view):
        if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE}:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ and arg1 and arg1.lower() in allowed and db in ('main', None):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and (arg2 or '').lower() not in {'load_extension', 'readfile', 'writefile'}:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    try:
        with closing(read_connection(database)) as connection:
            connection.set_authorizer(authorize)
            cursor = connection.execute(sql)
            rows = cursor.fetchmany(50001)
            if len(rows) > 50000:
                raise ValueError('Query returned more than 50,000 rows')
            return {'status': 'executed', 'sql': sql, 'rows': rows,
                    'columns': [col[0] for col in cursor.description]}
    except (sqlite3.Error, ValueError) as error:
        return {'status': 'execution_error', 'sql': sql, 'reason': str(error)}


@lru_cache(maxsize=512)
def column_values(database, table, column, limit):
    t, c = ident(table), ident(column)
    with closing(read_connection(database)) as db:
        return db.execute(f'SELECT {c}, typeof({c}), COUNT(*) FROM {t} '
                          f'GROUP BY {c}, typeof({c}) ORDER BY 3 DESC, 2, 1 LIMIT ?', (limit,)).fetchall()


def as_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=repr)


def normalize(value):
    return re.sub(r'[^\w]+|_', '', str(value).casefold())


def lookup_values(case, extraction):
    by_table = columns_for(case.database)
    found = []
    for target in extraction.get('targets', [])[:5]:
        if not isinstance(target, dict):
            continue
        raw_table, raw_col = target.get('table'), target.get('column')
        if not isinstance(raw_table, str) or not isinstance(raw_col, str):
            continue
        table = next((name for name in by_table if name.casefold() == raw_table.casefold()), None)
        if table is None:
            continue
        column = next((name for name in by_table[table] if name.casefold() == raw_col.casefold()), None)
        if column is None:
            continue
        raw_term = str(target.get('term', ''))[:150]
        term = normalize(raw_term)
        values = column_values(case.database, table, column, 3001)
        from difflib import SequenceMatcher

        def match(row):
            norm = normalize(row[0]) if row[0] is not None else ''
            if not term or not norm:
                return 0.0
            if term == norm:
                return 1.0
            return SequenceMatcher(None, term, norm, autojunk=False).ratio()

        ranked = sorted(values, key=match, reverse=True)
        corpus = [(v, typ, n, match((v, typ, n))) for v, typ, n in ranked[:6]]
        found.append({'table': table, 'column': column, 'term': raw_term,
                      'operator': str(target.get('operator', ''))[:12],
                      'declared_type': by_table[table][column],
                      'enumeration_complete': len(values) <= 3000,
                      'values': [{'value': v[:160] if isinstance(v, str) else v, 'type': typ,
                                  'count': n, 'similarity': round(sim, 3)} for v, typ, n, sim in corpus]})
    return found


def field_probes(case, sql):
    related = []
    words = {token.casefold() for token in re.findall(r'\w+', sql or '')}
    by_table = columns_for(case.database)
    for table, columns in by_table.items():
        if table.casefold() not in words:
            continue
        for column, decl in columns.items():
            if column.casefold() in words:
                related.append({'table': table, 'column': column, 'declared': decl,
                                'examples_value_type_count': column_values(case.database, table, column, 5)})
            if len(related) == 6:
                return related
    return related


EXTRACT = ('Map requested SQL output fields and filter literals to plausible SQLite schema identifiers. '
           'Return a compact JSON object with keys output (array), joins (array), and targets '
           '(up to five objects with table, column, term from question, operator). '
           'List plausible alternatives for uncertain encodings. Include filters with names, codes, or dates. '
           'Use exact schema identifiers. Supply no SQL.')
PLAN = ('Write a concise plan for the requested SQLite query: exact output fields, row grain, '
        'candidate population, join paths and keys, group/distinct, comparison and order. '
        'Keep only constraints supported by the question and schema. Supply no SQL.')
REVIEW = ('Audit this draft SQLite SQL against the question and database evidence. '
          'Check the requested columns, literal and encoding, population, grouping, and order. '
          'An empty result alone is insufficient evidence of an error. Preserve a valid query. '
          'Change only clearly localized errors. If a missing input or two defensible interpretations '
          'would materially change the answer, ask one focused question. Return only JSON with '
          'action (keep, revise, or clarify), reason, and sql (required only for revise).')


def content_of(response):
    choice = response['choices'][0]
    text = choice['message']['content']
    if choice.get('finish_reason') != 'stop' or not isinstance(text, str) or not text.strip():
        raise ValueError('Incomplete or empty model response')
    return text.strip()


def json_object(text):
    match = re.fullmatch(r'```(?:json)?\s*(.*?)```', text, re.S | re.I)
    data = json.loads(match[1] if match else text)
    if not isinstance(data, dict):
        raise ValueError('Expected a JSON object')
    return data


def step_node(node, case, model, upstream, complete):
    kind = node['kind']
    evidence = {step['kind']: step['output'] for step in upstream}
    if kind == 'lookup':
        return lookup_values(case, evidence['extract']), None
    if kind == 'execute':
        draft = next(iter(evidence.values()))
        if draft.get('sql'):
            result = execute_sql(case.database, draft['sql'])
            if node['probe']:
                result['field_probes'] = field_probes(case, draft['sql'])
            return result, None
        return {'status': draft.get('status', 'generation_error'),
                'reason': draft.get('reason', 'No SQL was generated')}, None

    schema = database_input(case.database)['schema']
    user = f'Schema\n{schema}\nQuestion\n{case.question}'
    if 'extract' in evidence:
        user += '\nField hypotheses\n' + as_json(evidence['extract'])
    if 'lookup' in evidence:
        user += '\nObserved database values (candidate evidence)\n' + as_json(evidence['lookup'])
    if 'plan' in evidence:
        user += '\nQuery plan\n' + evidence['plan']
    if 'execute' in evidence:
        observed = evidence['execute']
        compressed = {k: v for k, v in observed.items() if k != 'rows'}
        if 'rows' in observed:
            compressed.update(row_count=len(observed['rows']), row_examples=observed['rows'][:5])
        user += '\nDraft and execution evidence\n' + as_json(compressed)
    system = {'extract': EXTRACT, 'plan': PLAN, 'generate': SYSTEM, 'review': REVIEW}[kind]
    if node['hint']:
        system += '\nNode configuration: ' + node['hint']
    payload = {'model': model, 'stream': False, 'messages': [
        {'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
    response = complete(node['id'], payload)
    record = {'request': payload, 'response': response, 'usage': response.get('usage'),
              'model': response.get('model'), 'fingerprint': response.get('system_fingerprint')}
    try:
        if kind == 'generate':
            result = {'sql': prediction_sql(response)}
        elif kind == 'plan':
            result = content_of(response)[:4500]
        elif kind == 'extract':
            result = json_object(content_of(response))
            if not isinstance(result.get('targets'), list):
                raise ValueError('Expected a list of targets')
        else:
            result = json_object(content_of(response))
            action = result.get('action')
            if action == 'keep':
                result = {'sql': evidence['execute'].get('sql'), 'reason': result.get('reason')}
            elif action == 'clarify':
                result = {'status': 'clarification', 'reason': result.get('reason')}
            elif action == 'revise':
                revised = result.get('sql')
                if not isinstance(revised, str) or not re.match(r'^\s*(SELECT|WITH)\b', revised, re.I):
                    raise ValueError('Revision must be one SQLite SELECT')
                result = {'sql': revised, 'reason': result.get('reason')}
            else:
                raise ValueError('Unexpected review action')
    except (IndexError, KeyError, TypeError, ValueError) as error:
        record['format_error'] = str(error)
        fallback = {'extract': {'targets': []}, 'plan': '',
                    'generate': {'status': 'generation_error', 'reason': str(error)},
                    'review': {'sql': evidence.get('execute', {}).get('sql'), 'reason': str(error)}}
        result = fallback[kind]
    return result, record


def run_graph(spec, case, model, complete):
    steps = {}
    for node in validate_graph(spec):
        now = time.monotonic()
        output, call = step_node(node, case, model, [steps[k] for k in node['from']], complete)
        steps[node['id']] = {**node, 'output': output, 'call': call,
                             'elapsed_s': round(time.monotonic() - now, 4)}
    final = next(reversed(steps.values()))['output']
    return {'graph_sha256': canonical(spec), 'steps': list(steps.values()), 'final': final}


def score(case, final):
    reference = gold_rows(case.database, case.gold_sql)
    actual = final.get('rows', [])
    if final['status'] == 'executed':
        correct = bool(result_eq(reference, actual, 'order by' in case.gold_sql.lower()))
        status = 'match' if correct else 'mismatch'
    else:
        correct, status = False, final['status']
    return {'correct': correct, 'status': status, 'reference_rows': len(reference),
            'prediction_rows': len(actual) if final['status'] == 'executed' else None}
