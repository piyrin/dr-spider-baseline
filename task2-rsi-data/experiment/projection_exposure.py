"""Inventory prior Dr.Spider exposure from local experiment evidence."""

from collections import Counter, defaultdict
from pathlib import Path
import re

from experiment import ROOT, samples_by_id
from run_api_sample import save


SUFFIXES = {'.json', '.csv', '.tsv', '.md', '.ndjson', '.log', '.py'}
SURFACES = (
    'results', 'runs', 'reports', 'outputs', '.local/task2-experiment',
    '.local/thinking-table-review', '.local/drspider-pair-review',
    '.local/failed-query-review', '.local/notes', '.local/learning',
)
OUT = ROOT / 'runs/task2-projection-comparison-v1'
OWN = {'task2-projection-comparison-v1', 'node_modules', '.git', 'npm-cache',
       '.playwright-cli', 'dist', '__pycache__'}
NAME = re.compile(r'\b(?:first |last |full )?names?\b', re.I)
IMPLICIT_ENTITY = re.compile(
    r'^(?:who\s+(?:are|were|is|was)\b|(?:which|what)\s+'
    r'(?:employees?|teachers?|students?|contestants?|countries|nations|singers?|people|persons?|players?|authors?|films?|movies?|airlines?|visitors?|cities|documents?)\b|'
    r'(?:list|show|give|return)\s+(?:(?:me|the|each|all|a list of|the list of)\s+)*'
    r'(?:employees?|teachers?|students?|contestants?|countries|nations|singers?|people|persons?|players?|authors?|films?|movies?|airlines?|visitors?|cities|documents?)\b)', re.I)


def exposure(samples):
    stems = {key.rsplit('-', 1)[0]: sample['original_id'] for key, sample in samples.items()}
    groups = sorted({row['group'] for row in samples.values()}, key=len, reverse=True)
    sample_id = re.compile(r'(?<!\w)((?:' + '|'.join(map(re.escape, groups)) + r')-\d{5})(?!\d)')
    source_ids = defaultdict(set)
    owners = defaultdict(set)
    pairs = set()
    seen = set()
    for surface in SURFACES:
        for path in (ROOT / surface).rglob('*'):
            relative = path.relative_to(ROOT)
            if relative in seen or OWN.intersection(relative.parts) or not path.is_file():
                continue
            seen.add(relative)
            hits = set(sample_id.findall(path.name))
            # The full-dataset manifest and audit come from enumerating downloadable inputs.
            # Model responses, scored files and other substantive artifacts are considered below.
            is_full_input = relative.as_posix() in {
                'runs/sol-drspider-full/samples.json', 'runs/sol-drspider-full/reference_audit.json'}
            if path.suffix.lower() in SUFFIXES and not is_full_input:
                hits.update(sample_id.findall(path.read_text(encoding='utf-8', errors='replace')))
            pairs.update(stem for stem in hits if stem in stems)
            ids = {stems[stem] for stem in hits if stem in stems}
            if not ids:
                continue
            source_ids[surface].update(ids)
            for i in ids:
                owners[i].add(relative.as_posix())
    return dict(owners), {key: len(values) for key, values in source_ids.items()}, sorted(pairs)


def main():
    samples = samples_by_id()
    owners, counts, pairs = exposure(samples)
    save(OUT / 'exposed-original-ids.json', {
        'counts_by_first_surface': counts,
        'observed_pair_ids': pairs,
        'originals': {str(key): sorted(values) for key, values in sorted(owners.items())}})
    remaining = [r for r in samples.values() if r['original_id'] not in owners]
    print('Exposure', len(owners), counts)
    print('Available official', len(remaining)//2, 'pairs', len({r['original_id'] for r in remaining}), 'originals')
    print('Available groups', dict(Counter(r['group'] for r in remaining if r['side']=='post')))
    targets = []
    for post in remaining:
        if post['side'] != 'post':
            continue
        pre = samples[post['id'][:-4]+'pre']
        if NAME.search(pre['question']) and not NAME.search(post['question']) and IMPLICIT_ENTITY.search(post['question']):
            targets.append((post['original_id'],post['id'],pre['question'],post['question']))
    print('Screened target candidates', len(targets), 'pairs',len({row[0] for row in targets}),'originals')
    for row in targets:
        print(*row, sep=' | ')


if __name__ == '__main__':
    main()
