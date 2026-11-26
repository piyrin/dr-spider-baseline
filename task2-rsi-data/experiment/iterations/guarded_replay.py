"""Post-hoc offline check of two literal-only rules on saved baseline SQL."""

from collections import Counter
import csv
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlparse
from sqlparse.sql import Identifier, Where

from experiment import (HERE, ROOT, Scenario, column_values, columns_for, execute_sql,
                        score)
from run_api_sample import load, save


IDENT = r'(?:"(?:[^"]|"")+"|`[^`]+`|\[[^\]]+\]|[a-zA-Z_]\w*)'
PREDICATE = re.compile(rf"\s*(?:(?P<alias>{IDENT})\s*\.\s*)?"
                       rf"(?P<column>{IDENT})\s*(?P<op><=|>=|=|<|>)\s*"
                       r"(?P<literal>'(?:[^']|'')*'|[0-9]+)\s*;?\s*", re.I)
YEAR = re.compile(r'(?<!\d)[12]\d{3}(?!\d)')


def normalize(value):
    return re.sub(r'\s+', '', value.casefold())


def unquote(value):
    return value.strip('"`[]').replace('""', '"').casefold()


def context(sql, schema):
    statements = sqlparse.parse(sql)
    if len(statements) != 1 or statements[0].token_first().normalized != 'SELECT':
        return None
    statement = statements[0]
    offset, where, tables, want_table = 0, None, {}, False
    names = {k.casefold(): k for k in schema}
    for token in statement.tokens:
        if isinstance(token, Where):
            where = token, offset
        if not token.is_whitespace:
            if want_table:
                if not isinstance(token, Identifier) or token.get_parent_name() is not None:
                    return None
                raw_name = token.get_real_name()
                if not raw_name or raw_name.casefold() not in names:
                    return None
                alias = (token.get_alias() or raw_name).casefold()
                tables[alias] = names[raw_name.casefold()]
            want_table = token.normalized == 'FROM' or token.normalized.endswith(' JOIN') or token.normalized == 'JOIN'
        offset += len(token.value)
    return (where, tables) if where and tables else None


def direct_conditions(where, offset):
    body = str(where)
    start = len(where.tokens[0].value)
    cursor = start
    spans = []
    for token in where.tokens[1:]:
        if token.normalized == 'OR':
            return []
        if token.normalized == 'AND':
            spans.append((start, cursor))
            start = cursor + len(token.value)
        cursor += len(token.value)
    spans.append((start, len(body)))
    return [(match, offset + a) for a, b in spans if (match := PREDICATE.fullmatch(body[a:b]))]


def replacements(case, sql, allow_edge_padding):
    schema = columns_for(case.database)
    parsed = context(sql, schema)
    if not parsed:
        return []
    (where, offset), tables = parsed
    output = []
    for match, begin in direct_conditions(where, offset):
        alias, col, op, literal = match.group('alias', 'column', 'op', 'literal')
        pool = [tables[unquote(alias)]] if alias and unquote(alias) in tables else [] if alias else list(tables.values())
        found = [(table, column) for table in pool for column in schema[table]
                 if column.casefold() == unquote(col)]
        if len(found) != 1:
            continue
        table, column = found[0]
        values = column_values(case.database, table, column, 3001)
        if len(values) > 3000:
            continue
        observed = [(value, kind) for value, kind, _ in values if value is not None]
        replacement, rule = None, None
        if op == '=' and literal.startswith("'"):
            old = literal[1:-1].replace("''", "'")
            if len(normalize(old)) < 3 or not re.search(rf'(?<!\w){re.escape(old.strip())}(?!\w)', case.question, re.I):
                continue
            text = {value for value, kind in observed if kind == 'text'}
            if old in text:
                continue
            candidates = [value for value in text if normalize(value) == normalize(old)]
            if len(candidates) == 1:
                value = candidates[0]
                padded = value != value.strip() or old != old.strip()
                if not padded or allow_edge_padding:
                    replacement = "'" + value.replace("'", "''") + "'"
                    rule = 'outer_space' if padded else 'text_equivalent'
        elif unquote(col) == 'year' and len(literal) == 2:
            years = set(YEAR.findall(case.question))
            if (len(years) == 1 and observed
                    and all(kind in {'integer', 'real'} and 1000 <= value < 3000 for value, kind in observed)):
                year = next(iter(years))
                if year.endswith(literal):
                    replacement, rule = year, 'four_digit_year'
        if replacement:
            a, b = match.span('literal')
            output.append((begin + a, begin + b, replacement, rule, f'{table}.{column}'))
    return output


def replay(case, before, correct, allow_edge_padding):
    sql = before.get('sql')
    if before['status'] != 'executed' or not sql:
        return None
    fixes = replacements(case, sql, allow_edge_padding)
    if len(fixes) != 1:
        return None
    a, b, replacement, rule, field = fixes[0]
    result = execute_sql(case.database, sql[:a] + replacement + sql[b:])
    if (result['status'] != 'executed' or result['columns'] != before['columns']
            or [list(row) for row in result['rows']] == before['rows']):
        return None
    return {'id': case.id, 'rule': rule, 'field': field, 'original_value': sql[a:b],
            'patched_value': replacement, 'before': correct,
            'after': score(case, result)['correct'], 'original_sql': sql,
            'patched_sql': result['sql']}


def main():
    result = {}
    for stage in ('main', 'ablation'):
        records = [load(path) for path in sorted((HERE / 'runs' / stage / 'records').glob('*--baseline.json'))]
        for allow in (False, True):
            changes = [row for r in records if (row := replay(Scenario.from_id(r['id']), r['result']['final'],
                                                               r['score']['correct'], allow)) is not None]
            fixed = sum(not r['before'] and r['after'] for r in changes)
            broken = sum(r['before'] and not r['after'] for r in changes)
            base = sum(r['score']['correct'] for r in records)
            key = stage + ('_including_padding' if allow else '_strict')
            result[key] = {'n': len(records), 'before': base, 'after': base + fixed - broken,
                           'fixed': fixed, 'broken': broken, 'changes': changes}
            print(key, len(records), base, base + fixed - broken, fixed, broken,
                  dict(Counter(row['rule'] for row in changes)))
            for row in changes:
                print(' ', row['id'], row['rule'], row['original_value'], row['patched_value'], row['before'], row['after'])
    with (ROOT / 'results/drspider-17x50/predictions.csv').open(encoding='utf-8-sig', newline='') as source:
        historical = list(csv.DictReader(source))
    base = sum(r['status'] == 'match' for r in historical)
    changes = []
    for row in historical:
        if row['status'] not in {'match', 'mismatch'} or not row['prediction_sql']:
            continue
        case = Scenario.from_id(row['id'])
        sql = row['prediction_sql']
        if len(replacements(case, sql, allow_edge_padding=False)) != 1:
            continue
        before = execute_sql(case.database, sql)
        if before['status'] != 'executed':
            continue
        assert score(case, before)['correct'] == (row['status'] == 'match'), case.id
        before['rows'] = [list(r) for r in before['rows']]
        change = replay(case, before, row['status'] == 'match', allow_edge_padding=False)
        if change:
            changes.append(change)
    fixed = sum(not r['before'] and r['after'] for r in changes)
    broken = sum(r['before'] and not r['after'] for r in changes)
    result['historical_850_pairs_strict'] = {'n': len(historical), 'before': base,
                                            'after': base + fixed - broken, 'fixed': fixed,
                                            'broken': broken, 'changes': changes}
    print('historical_850_pairs_strict', len(historical), base, base + fixed - broken, fixed, broken,
          dict(Counter(row['rule'] for row in changes)))
    file = Path(__file__).with_name('guarded-replay-results.json')
    save(file, {'design': 'post-hoc on saved baseline SQL, zero new model calls', 'results': result})


if __name__ == '__main__':
    main()
