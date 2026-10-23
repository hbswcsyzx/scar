"""Losslessly retain this experiment's generated raw logs, not application data."""
import gzip
from hashlib import sha256
import json
from pathlib import Path


root = Path(__file__).resolve().parent
index = root / 'archive-index.json'
if index.exists():
    raise FileExistsError(index)
paths = sorted((root / 'os').glob('syscalls.*'))
paths += sorted((root / 'trace').glob('*.jsonl'))
paths += sorted((root / 'trace').glob('execution-trace.*.json'))
paths += sorted((root / 'trace').glob('kineto.*.json'))
rows = []
for path in paths:
    if path.is_symlink() or path.suffix == '.gz' or not path.is_file():
        raise ValueError('unexpected generated artifact: ' + str(path))
    target = path.with_name(path.name + '.gz')
    raw_hash, size = sha256(), 0
    with path.open('rb') as source, target.open('xb') as output:
        with gzip.GzipFile(filename='', fileobj=output, mode='wb', mtime=0) as compressed:
            while block := source.read(1048576):
                compressed.write(block)
                raw_hash.update(block)
                size += len(block)
    check, check_size = sha256(), 0
    with gzip.open(target, 'rb') as source:
        while block := source.read(1048576):
            check.update(block)
            check_size += len(block)
    if check.digest() != raw_hash.digest() or check_size != size:
        raise ValueError('roundtrip failed: ' + str(path))
    zipped_hash = sha256()
    with target.open('rb') as source:
        while block := source.read(1048576):
            zipped_hash.update(block)
    rows.append({'logical_path': str(path), 'actual_path': str(target),
                 'raw_sha256': raw_hash.hexdigest(), 'raw_bytes': size,
                 'compressed_bytes': target.stat().st_size, 'gzip_sha256': zipped_hash.hexdigest()})
payload = {'schema': 'scar.lossless-capture-archive', 'schema_version': 1,
           'verified_roundtrip': True, 'files': rows}
with index.open('x') as output:
    json.dump(payload, output, indent=2)
    output.write('\n')
# Only generated duplicates whose compressed bytes were just independently
# roundtrip-checked are removed, after the complete index has been published.
for row in rows:
    Path(row['logical_path']).unlink()
print(json.dumps({'files': len(rows), 'raw_bytes': sum(row['raw_bytes'] for row in rows),
                  'gzip_bytes': sum(row['compressed_bytes'] for row in rows)}))
