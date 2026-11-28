"""Re-execute the archived twenty course queries and verify the published evidence."""

import csv
from pathlib import Path
import sys

from run_full_evaluation import ROOT, digest, gold_rows, load, result_eq

sys.path.insert(0, str(ROOT / 'task2-rsi-data/experiment'))
from experiment import execute_sql


def main():
    submission = ROOT / 'results/task2/submission/acceptance'
    index = load(submission / 'verification.json')
    baseline_path = ROOT / 'results/drspider-17x50/predictions.csv'
    with baseline_path.open(encoding='utf-8-sig', newline='') as stream:
        baseline = {row['id']: row['status'] for row in csv.DictReader(stream)}

    for number, entry in enumerate(index['cases'], start=1):
        name = f'case{number}'
        result = load(submission / f'results/result{number}.json')
        frontend = submission / f'frontend/{name}.json'
        backend = submission / f'backend/{name}.json'
        view, flow = load(frontend), load(backend)
        if not (entry['case'] == result['case'] == view['id'] == name
                and digest(frontend) == result['frontend']['sha256']
                and digest(backend) == result['backend']['sha256']
                and flow['id'] == result['backend']['flow_id']):
            raise ValueError(f'{name}: case files do not match the archived result')
        summary = []
        for side, historical_status in (('pre', 'match'), ('post', 'mismatch')):
            record = result['runs'][side]
            sample = record['sample_id']
            database = ROOT / Path(record['database'])
            if not database.is_file():
                raise FileNotFoundError(f'{database}: run scripts/prepare_data.py first')
            if not (sample == view['samples'][side]['id'] and baseline[sample] == historical_status
                    and digest(database) == record['database_sha256']
                    and record['run_id'] == entry[side]['run_id']
                    and record['course_flow_id'] == flow['id']
                    and record['http_status'] == 200 and record['score']['correct']):
                raise ValueError(f'{name} {side}: sample, database or execution receipt differs')
            reference = record['reference']
            ordered = 'order by' in reference['sql'].lower()
            expected = gold_rows(database, reference['sql'])
            actual = execute_sql(database, record['executed']['sql'])
            if not (actual['status'] == 'executed'
                    and result_eq(expected, actual['rows'], ordered)
                    and result_eq([tuple(row) for row in record['executed']['rows']], actual['rows'], ordered)
                    and len(expected) == record['score']['reference_rows']
                    and len(actual['rows']) == record['score']['prediction_rows']):
                raise ValueError(f'{name} {side}: SQLite replay differs from the archived score')
            summary.append(f'{side}=pass ({len(actual["rows"])} rows)')
        print(f'{name}: {", ".join(summary)}')
    if len(index['cases']) != 10:
        raise ValueError('Expected ten course cases')
    print('Archived SQL verified: pre 10/10, post 10/10, both 10/10.')


if __name__ == '__main__':
    main()
