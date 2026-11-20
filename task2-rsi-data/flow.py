"""Table-scoped agents and SQLite verification for the RSI Data demo."""

from collections import Counter
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import time


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / 'data/Spider-dev/databases/concert_singer/concert_singer.sqlite'
CASES = {
    'single-table': {
        'question': '有多少位歌手来自法国？',
        'tables': ('singer',),
        'reference_sql': "SELECT COUNT(*) FROM singer WHERE Country = 'France'",
    },
    'multi-agent': {
        'question': '统计每位歌手参加的演唱会数量，包含 0 场。',
        'tables': ('singer', 'singer_in_concert'),
        'reference_sql': ('SELECT s.Name, COUNT(sc.concert_ID) AS concert_count '
                          'FROM singer AS s LEFT JOIN singer_in_concert AS sc '
                          'ON s.Singer_ID = sc.Singer_ID GROUP BY s.Singer_ID, s.Name'),
    },
}
FUNCTIONS = frozenset('abs avg coalesce count date group_concat ifnull instr length '
                      'lower max min nullif replace round strftime substr sum total trim upper'.split())


def connection():
    return sqlite3.connect(DATABASE.resolve().as_uri() + '?mode=ro', uri=True)


def schema_for(table):
    with closing(connection()) as db:
        row = db.execute('SELECT sql FROM sqlite_schema WHERE type = ? AND name = ?',
                         ('table', table)).fetchone()
    if row is None:
        raise ValueError(f'数据库缺少表 {table}')
    return row[0]


def execute_query(sql, tables):
    if not re.match(r'\s*(SELECT|WITH)\b', sql, flags=re.IGNORECASE):
        raise ValueError('Agent 必须返回一条 SQLite SELECT 查询')

    def authorize(action, name, argument, database, _):
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ and database == 'main' and name.lower() in tables:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and (argument or '').lower() in FUNCTIONS:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    deadline = time.monotonic() + 5
    with closing(connection()) as db:
        db.execute('PRAGMA query_only=ON')
        db.set_authorizer(authorize)
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        cursor = db.execute(sql)
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchmany(1001)
    if len(rows) > 1000:
        raise ValueError('查询返回超过 1000 行')
    return columns, [list(row) for row in rows]


def agent_order(flow_id):
    tables = CASES[flow_id]['tables']
    return tables if flow_id == 'single-table' else (*tables, 'sql')


def run_agent_step(flow_id, agent, question, complete, previous=()):
    tables = CASES[flow_id]['tables']
    if agent not in agent_order(flow_id):
        raise ValueError('Agent 未绑定到当前流程')

    sql_instruction = ('Generate exactly one read-only SQLite SELECT query. Use only the '
                       'provided tables and columns. Return SQL only. If counting rows '
                       'of an optional relationship, count the joined column, not COUNT(*).')
    if agent == 'sql':
        if tuple(step['agent'] for step in previous) != tables:
            raise ValueError('SQL Agent 需要两张表各自的分析结果')
        instruction = (sql_instruction + ' Use the two table agents’ findings to plan the join. '
                       'Return only the requested measures and the human-readable label for each row. '
                       'Do not include internal IDs unless asked.')
        schemas = [schema_for(table) for table in tables]
        notes = [f'{step["agent"]} → {step["output"]}' for step in previous]
        context = '\n\n'.join([*schemas, *notes, f'问题\n{question}'])
    else:
        instruction = sql_instruction if flow_id == 'single-table' else (
            'You are responsible for the single table provided. In Chinese, briefly explain '
            'relevant fields, row grain and keys for the question. Mention which rows from this '
            'table must be kept when appropriate. Return a short note for the downstream SQL agent.')
        context = f'{schema_for(agent)}\n\n问题\n{question}'
    output, model = complete(instruction, context)
    return {'agent': agent, 'system': instruction, 'input': context, 'output': output, 'model': model}


def evaluate_steps(flow_id, question, steps):
    case = CASES[flow_id]
    tables = case['tables']
    if tuple(step['agent'] for step in steps) != agent_order(flow_id):
        raise ValueError('流程的 Agent 输出不完整')
    raw_sql = steps[-1]['output']
    fenced = re.fullmatch(r'```(?:sql|sqlite)?\s*(.*?)\s*```', raw_sql.strip(), re.I | re.S)
    sql = (fenced[1] if fenced else raw_sql).strip()
    result = {'flowId': flow_id, 'question': question, 'database': 'concert_singer',
              'tables': list(tables), 'steps': steps, 'sql': sql, 'columns': [], 'rows': [],
              'matches_reference': None, 'error': None}
    try:
        result['columns'], result['rows'] = execute_query(sql, tables)
        if question == case['question']:
            _, reference = execute_query(case['reference_sql'], tables)
            result['matches_reference'] = (Counter(map(tuple, result['rows']))
                                           == Counter(map(tuple, reference)))
    except (sqlite3.DatabaseError, ValueError) as error:
        result['error'] = str(error)
    return result


def run_flow(flow_id, question, complete):
    steps = []
    for agent in agent_order(flow_id):
        steps.append(run_agent_step(flow_id, agent, question, complete, steps))
    return evaluate_steps(flow_id, question, steps)
