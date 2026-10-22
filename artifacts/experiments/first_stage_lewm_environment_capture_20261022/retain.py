"""Losslessly retain this attempt's generated transcripts, verifying before unlink."""
import gzip, hashlib, json
from pathlib import Path

root=Path(__file__).resolve().parent
rows=[]
paths=sorted((root/'os').glob('syscalls.*'))+sorted((root/'trace').glob('*.jsonl'))+sorted((root/'trace').glob('execution-trace.*.json'))+sorted((root/'trace').glob('kineto.*.json'))
for path in paths:
    if path.suffix=='.gz':
        continue
    target=path.with_name(path.name+'.gz')
    digest=hashlib.sha256();size=0;lines=0
    with path.open('rb') as stream,gzip.open(target,'xb',compresslevel=6) as destination:
        for block in iter(lambda:stream.read(1048576),b''):
            digest.update(block);size+=len(block);lines+=block.count(b'\n');destination.write(block)
    check=hashlib.sha256();n=0
    with gzip.open(target,'rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):
            check.update(block);n+=len(block)
    if n!=size or check.digest()!=digest.digest():
        raise ValueError('retained bytes differ: '+str(path))
    rows.append({'path':str(path.relative_to(root)),'retained':str(target.relative_to(root)), 'raw_sha256':digest.hexdigest(),'raw_bytes':size,'raw_lines':lines,'compressed_bytes':target.stat().st_size})
    path.unlink()
(root/'retention.json').write_text(json.dumps({'schema':'scar.lossless-capture-retention','schema_version':1,'files':rows,'raw_bytes':sum(r['raw_bytes'] for r in rows),'compressed_bytes':sum(r['compressed_bytes'] for r in rows),'all_decoded_hashes_checked':True},indent=2)+'\n')
print(json.dumps({'files':len(rows),'raw_bytes':sum(r['raw_bytes'] for r in rows),'compressed_bytes':sum(r['compressed_bytes'] for r in rows)}))
