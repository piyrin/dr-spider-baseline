"""Frozen, synthetic cross-schema controls for the Top N experiment."""

from functools import lru_cache
import sqlite3
from threading import Lock

from experiment import ROOT, Scenario

DATABASES = {
    'laps': (
        'CREATE TABLE laps(lap_id INTEGER PRIMARY KEY, driver_number INTEGER, driver_name TEXT,'
        ' track TEXT, elapsed_ms INTEGER)',
        [(1, 10, 'Aya', 'North', 70), (2, 10, 'Aya', 'North', 70),
         (3, 10, 'Aya', 'South', 72), (4, 10, 'Aya', 'South', 83),
         (5, 20, 'Bo', 'West', 74), (6, 40, 'Aya', 'East', 76), (7, 30, 'Chen', 'East', 81),
         (8, 99, 'Unknown', 'West', None)],
    ),
    'sales': (
        'CREATE TABLE orders(order_id INTEGER PRIMARY KEY, customer_code TEXT, customer_name TEXT,'
        ' category TEXT, amount INTEGER)',
        [(1, 'C1', 'Ira', 'garden', 100), (2, 'C1', 'Ira', 'garden', 100),
         (3, 'C1', 'Ira', 'book', 95), (4, 'C2', 'Lee', 'garden', 93),
         (5, 'C3', 'Nia', 'book', 90), (6, 'C4', 'Om', 'book', 87),
         (7, 'C5', 'Ren', 'art', None)],
    ),
}
FIXTURES = {
    'lap-entity': ('laps', 'entity', (2, 3),
                   'Find the {n} fastest different drivers, one entry per driver number, using each '
                   'driver’s fastest recorded lap. Show only the driver name and track of that lap.',
                   [('Aya', 'North'), ('Bo', 'West'), ('Aya', 'East')]),
    'lap-tuple': ('laps', 'tuple', (2, 4),
                  'Which {n} distinct driver-name and track combinations have the lowest recorded lap time '
                  'within each combination? Display driver name and track.',
                  [('Aya', 'North'), ('Aya', 'South'), ('Bo', 'West'), ('Aya', 'East')]),
    'lap-rows': ('laps', 'rows', (2, 4),
                 'Find the {n} fastest lap records across all runs. Return the driver name and track for each record.',
                 [('Aya', 'North'), ('Aya', 'North'), ('Aya', 'South'), ('Bo', 'West')]),
    'sale-entity': ('sales', 'entity', (2, 3),
                    'Find the top {n} distinct customers ranked by their largest order amount. Use one '
                    'row per customer code. Return only customer name and the category of the largest order.',
                    [('Ira', 'garden'), ('Lee', 'garden'), ('Nia', 'book')]),
    'sale-tuple': ('sales', 'tuple', (2, 4),
                   'Rank distinct pairs of customer name and category by the maximum order amount for '
                   'each pair. Show the top {n} pairs, with customer name and category.',
                   [('Ira', 'garden'), ('Ira', 'book'), ('Lee', 'garden'), ('Nia', 'book')]),
    'lap-ambiguity': ('laps', 'ambiguous', (2, 4),
                      'Show the driver name and track for the {n} fastest drivers across the recorded laps.',
                      [('Aya', 'North'), ('Bo', 'West'), ('Aya', 'East'), ('Chen', 'East')]),
}
FIXTURE_IDS = [f'{stem}-{side}' for stem in FIXTURES for side in ('pre', 'post')]
_lock = Lock()


@lru_cache(maxsize=None)
def fixture_database(name):
    path = ROOT / 'runs/task2-top-n-v3/fixtures' / f'{name}.sqlite'
    ddl, rows = DATABASES[name]
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with sqlite3.connect(path) as connection:
                connection.execute(ddl)
                table = ddl.split('(')[0].split()[-1]
                connection.executemany(f'INSERT INTO {table} VALUES (?,?,?,?,?)', rows)
    return str(path.relative_to(ROOT))


def fixture_case(sample_id):
    name, side = sample_id.rsplit('-', 1)
    database, _unit, ns, question, reference = FIXTURES[name]
    n = ns[('pre', 'post').index(side)]
    # The expected result is hand-listed explicitly, independently of SQL compilation.
    values = ','.join(f"({i},'{col1}','{col2}')" for i, (col1, col2) in enumerate(reference[:n]))
    query = f'WITH expected(pos, first, second) AS (VALUES {values}) SELECT first, second FROM expected ORDER BY pos'
    return Scenario(sample_id, question.format(n=n), fixture_database(database), query)
