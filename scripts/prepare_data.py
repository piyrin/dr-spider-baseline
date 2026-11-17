"""Download, verify and extract the pinned official Dr.Spider data archive."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import tempfile
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def main():
    destination = ROOT / 'data'
    if destination.exists():
        if not (destination / 'Spider-dev/questions.json').is_file():
            raise ValueError('Existing data directory is incomplete; inspect its contents')
        print('Using existing data:', destination)
        return
    provenance = json.loads((ROOT / 'manifests/data_source.json').read_text(encoding='utf-8'))
    cache = ROOT / '.cache'
    cache.mkdir(parents=True, exist_ok=True)
    archive_path = cache / 'data.tar.gz'
    if not archive_path.exists():
        temporary = cache / 'data.tar.gz.part'
        with urllib.request.urlopen(provenance['url'], timeout=120) as response:
            with temporary.open('wb') as output:
                for block in iter(lambda: response.read(1024 * 1024), b''):
                    output.write(block)
        if temporary.stat().st_size != provenance['bytes'] or digest(temporary) != provenance['sha256']:
            raise ValueError('Downloaded archive failed size or SHA-256 validation')
        temporary.replace(archive_path)
    if archive_path.stat().st_size != provenance['bytes'] or digest(archive_path) != provenance['sha256']:
        raise ValueError('Cached archive failed size or SHA-256 validation')
    with tempfile.TemporaryDirectory(prefix='extract-', dir=cache) as temporary_directory:
        extraction_root = Path(temporary_directory) / 'data'
        extraction_root.mkdir()
        with tarfile.open(archive_path, 'r:gz') as archive:
            for member in archive.getmembers():
                member_path = PurePosixPath(member.name)
                if member_path.is_absolute() or '..' in member_path.parts or '\\' in member.name:
                    raise ValueError(f'Unsafe archive path: {member.name}')
                resolved = (extraction_root / member.name).resolve()
                if not resolved.is_relative_to(extraction_root.resolve()):
                    raise ValueError(f'Archive path escapes destination: {member.name}')
                if not (member.isdir() or member.isfile()):
                    raise ValueError(f'Unsupported archive entry: {member.name}')
            archive.extractall(extraction_root, filter='data')
        if not (extraction_root / 'Spider-dev/questions.json').is_file():
            raise ValueError('Archive does not contain expected Dr.Spider files')
        extraction_root.rename(destination)
    print('Verified data ready:', destination)


if __name__ == '__main__':
    main()
