"""Compare baseline and filter-column orchestration across frozen Dr.Spider pairs."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import re
import sys
import time

from experiment import GRAPHS, ROOT, Scenario, columns_for, samples_by_id, score, step_node, validate_graph
from filter_column_canvas import EXAMPLES, GRAPH, column_step, validate_columns
from format_canvas import find_values
from projection_compare import EFFORTS, MODEL
from run import complete_at
from run_full_evaluation import digest, load, make_config, read_settings, save

OUT = ROOT / 'runs/task2-filter-column-v1'
SEED = 'filter-column-v1-20261126'
CONDITIONS = [(method, effort) for method in ('baseline', 'canvas_v1') for effort in EFFORTS]
TEXT_EQ = re.compile(r"""(?<![<>!])=\s*(['"])([^'"]{3,60})\1""")
FIELD = re.compile(r'name|title|code|abbrev|maker|model|country|address', re.I)
TARGET_GROUPS = {'SQL_DB_text', 'NLQ_column_value', 'NLQ_value_synonym', 'DB_schema_synonym'}
CONTROL_GROUPS = ('DB_DBcontent_equivalence', 'DB_schema_abbreviation', 'NLQ_column_carrier',
                  'NLQ_column_attribute', 'SQL_comparison', 'SQL_sort_order',
                  'SQL_NonDB_number', 'NLQ_keyword_carrier')


@lru_cache(maxsize=4096)
def ambiguity(database, term):
    for table, fields in columns_for(database).items():
        columns = [col for col, dtype in fields.items()
                   if FIELD.search(col) and any(t in dtype.upper() for t in ('CHAR', 'TEXT', 'CLOB'))]
        if len(columns) < 2:
            continue
        matches = []
        for column in columns:
            target = {'table': table, 'column': column, 'term': term}
            if find_values(database, target, normalized=True):
                matches.append(column)
        if len(matches) >= 2:
            return {'term': term, 'table': table, 'matched_columns': matches}
    return None


def freeze(samples):
    path = OUT / 'plan.json'
    if path.exists():
        return load(path)
    candidates = sorted((r for r in samples.values() if r['side'] == 'post'),
                        key=lambda r: sha256((SEED + r['id']).encode()).digest())
    originals = {samples[EXAMPLES[0]]['original_id']}
    per_db = Counter()
    selected = []

    def add(row, label, evidence):
        selected.append({'pair': row['id'][:-5], 'label': label, 'original_id': row['original_id'],
                         'db_id': row['db_id'], 'selection': evidence})
        originals.add(row['original_id'])

    for row in candidates:
        if (row['group'] not in TARGET_GROUPS or row['original_id'] in originals
                or per_db[row['db_id']] >= 2):
            continue
        for _, term in TEXT_EQ.findall(row['gold_sql']):
            if term.casefold() not in row['question'].casefold():
                continue
            evidence = ambiguity(row['database'], term)
            if evidence:
                add(row, 'target', evidence)
                per_db[row['db_id']] += 1
                break
        if per_db.total() == 8:
            break
    for group in CONTROL_GROUPS:
        row = next(r for r in candidates if r['group'] == group
                   and r['original_id'] not in originals
                   and (not TEXT_EQ.search(r['gold_sql']) or not any(
                       ambiguity(r['database'], term) for _, term in TEXT_EQ.findall(r['gold_sql']))))
        add(row, 'control', '不同官方扰动，post 无按本规则检出的跨列文本值冲突')
    current = Path(__file__).parent
    files = ['filter_column_compare.py', 'filter_column_canvas.py', 'format_canvas.py', 'experiment.py', 'run.py']
    plan = {'seed': SEED, 'selected': selected, 'anchor': EXAMPLES, 'conditions': CONDITIONS,
            'observed_originals': '项目已核实 Spider-dev 1034 道原题均暴露',
            'graph': GRAPH,
            'code_sha256': {str((current / file).relative_to(ROOT)): digest(current / file) for file in files}}
    save(path, plan)
    save(OUT / 'structure-v1.json', GRAPH)
    return plan


def evaluate(sample_id, method, effort, endpoint, key):
    path = OUT / 'records' / method / effort / (sample_id + '.json')
    if path.is_file():
        return
    case = Scenario.from_id(sample_id)
    nodes, runner = ((validate_graph(GRAPHS['baseline']), step_node) if method == 'baseline'
                     else (validate_columns(GRAPH), column_step))

    def complete(node_id, payload):
        folder = OUT / 'requests' / method / effort / sample_id / node_id
        request, response = folder / 'request.json', folder / 'response.json'
        payload = {**payload, 'reasoning_effort': effort}
        if request.exists() and load(request) != payload:
            raise ValueError('Cached request differs from the frozen condition')
        save(request, payload)
        if response.exists():
            return load(response)
        for attempt in (1, 2):
            try:
                answer = complete_at(endpoint, key, payload)
            except Exception as error:
                save(folder / f'failure-{attempt}.json', {'error': str(error).replace(key, '[REDACTED]')})
                if attempt == 2:
                    raise
                time.sleep(1)
            else:
                save(response, answer)
                return answer

    steps = {}
    for node in nodes:
        output, call = runner(node, case, MODEL, [steps[parent] for parent in node['from']], complete)
        steps[node['id']] = {**node, 'output': output, 'call': call}
    calls = [node['call'].get('usage') or {} for node in steps.values() if node['call']]
    usage = {}
    for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        observed = [call.get(field) for call in calls]
        if all(type(value) is int for value in observed):
            usage[field] = sum(observed)
    final = list(steps.values())[-1]['output']
    save(path, {'id': case.id, 'method': method, 'effort': effort, 'steps': list(steps.values()),
                'usage': usage, 'model_calls': len(calls), 'score': score(case, final)})


def main(mode):
    samples = samples_by_id()
    plan = freeze(samples)
    print('Frozen', Counter(r['label'] for r in plan['selected']), 'originals exposed:',
          plan['observed_originals'], flush=True)
    if mode == 'prepare':
        for item in plan['selected']:
            print(item['label'], item['pair'], item['db_id'], flush=True)
        return 0
    if mode != 'run':
        raise ValueError('Use prepare or run')
    for name, sha in plan['code_sha256'].items():
        assert digest(ROOT / name) == sha, name
    ids = [*EXAMPLES, *(r['pair'] + '-' + side for r in plan['selected'] for side in ('pre', 'post'))]
    settings = read_settings()
    endpoint = settings['THINGO_BASE_URL'].rstrip('/') + '/chat/completions'
    key = settings['THINGO_API_KEY']
    config = make_config([samples[i] for i in ids], MODEL, endpoint)
    config.update(reasoning_efforts=list(EFFORTS), plan_sha256=digest(OUT / 'plan.json'), graph=GRAPH)
    previous = OUT / 'config.json'
    if previous.exists() and load(previous) != config:
        raise ValueError('Configuration differs from the frozen experiment')
    save(previous, config)
    failures = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = {pool.submit(evaluate, sample, *cond, endpoint, key): (sample, *cond)
                   for sample in ids for cond in CONDITIONS}
        for number, future in enumerate(as_completed(pending), 1):
            try:
                future.result()
            except Exception as error:
                failure = {'case': pending[future], 'error': str(error).replace(key, '[REDACTED]')}
                failures.append(failure)
                print(failure, flush=True)
            if number % 8 == 0 or number == len(pending):
                print(f'{number}/{len(pending)} completed, {len(failures)} runner failures', flush=True)
    save(OUT / 'failures.json', failures)
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
