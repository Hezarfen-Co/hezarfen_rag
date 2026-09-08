"""Verify that every backed-up data/model file matches its committed LFS hash.
Run after `git lfs pull`: python verify_backup.py
"""
import hashlib
import pathlib
import subprocess
import sys

root = pathlib.Path(__file__).resolve().parent
result = subprocess.run(
    ['git', 'lfs', 'ls-files', '--long', '--null'], cwd=root,
    check=True, stdout=subprocess.PIPE,
)
failed = []
count = 0
for entry in result.stdout.decode('utf-8').split('\0'):
    if not entry:
        continue
    digest, marker, name = entry.split(' ', 2)
    path = root / name
    if not path.is_file():
        failed.append(name + ': missing')
        continue
    actual = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            actual.update(chunk)
    if actual.hexdigest() != digest:
        failed.append(name + ': hash mismatch (run git lfs pull)')
    count += 1
if count == 0:
    failed.append('No LFS files found')
print(f'Checked {count} files; {len(failed)} errors.')
for error in failed:
    print(error)
sys.exit(bool(failed))
