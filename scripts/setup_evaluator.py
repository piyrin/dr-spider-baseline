"""Download the two upstream modules used by the execution comparator."""

import json
from pathlib import Path
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
COMMIT = 'e97acc546ecbee8fa27fa8dbf025ef61493a876c'
DESTINATION = ROOT / '.cache/evaluator'


def main():
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for name in ['exec_eval.py', 'parse.py']:
        url = f'https://raw.githubusercontent.com/taoyds/test-suite-sql-eval/{COMMIT}/{name}'
        with urllib.request.urlopen(url, timeout=60) as response:
            source = response.read()
        compile(source, name, 'exec')
        temporary = DESTINATION / (name + '.tmp')
        temporary.write_bytes(source)
        temporary.replace(DESTINATION / name)
    (DESTINATION / 'source.json').write_text(
        json.dumps({'repository': 'https://github.com/taoyds/test-suite-sql-eval',
                    'commit': COMMIT}, indent=2) + '\n', encoding='utf-8')
    print('Evaluator modules ready:', DESTINATION)


if __name__ == '__main__':
    main()
