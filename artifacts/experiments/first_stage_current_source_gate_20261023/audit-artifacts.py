"""Stored-output/shard receipt audit only; no raw/source/IR replay."""
import gzip
import hashlib
import json
from pathlib import Path
import time

BASE=Path(__file__).resolve().parent
START=time.monotonic()

def receipt(path):
    digest,size=hashlib.sha256(),0
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1_048_576),b''):
            digest.update(block);size+=len(block)
    return {'path':str(path.relative_to(BASE)),'stored_sha256':digest.hexdigest(),'stored_bytes':size}

manifest=json.loads((BASE/'result/analysis/manifest.json').read_bytes())
counts={};chunks=0;decoded_bytes=0
for name,table in manifest['tables'].items():
    total=0
    for declaration in table['chunks']:
        path=Path(declaration['path']);stored=receipt(path)
        assert (stored['stored_sha256'],stored['stored_bytes'])==(declaration['sha256'],declaration['bytes'])
        with gzip.open(path,'rb') as stream:payload=stream.read(manifest['max_shard_decoded_bytes']+1)
        assert len(payload)<=manifest['max_shard_decoded_bytes']
        assert hashlib.sha256(payload).hexdigest()==declaration['decoded_sha256']
        assert len(payload)==declaration['decoded_bytes'] and len(payload.splitlines())==declaration['rows']
        total+=declaration['rows'];chunks+=1;decoded_bytes+=len(payload)
    assert total==table['rows'];counts[name]=total
summary=json.loads((BASE/'summary.json').read_bytes())
assert summary['canonical_report_sha256']==manifest['canonical_document_sha256']
assert summary['canonical_report_bytes']==manifest['canonical_document_bytes']
header=manifest['header'];path=Path(header['path']);stored=receipt(path)
assert (stored['stored_sha256'],stored['stored_bytes'])==(header['sha256'],header['bytes'])
with gzip.open(path,'rb') as stream:payload=stream.read(manifest['max_shard_decoded_bytes']+1)
assert hashlib.sha256(payload).hexdigest()==header['decoded_sha256'] and len(payload)==header['decoded_bytes']
result={'status':'PASS','scope':'all output shard bytes/counts and stored carrier receipts only',
    'chunks':chunks,'tables':counts,'decoded_table_bytes':decoded_bytes,'header_decoded_bytes':len(payload),
    'canonical_report_sha256':summary['canonical_report_sha256'],
    'raw_scan_repeated':False,'source_reprepared':False,'code_compiled':False,'scar_imported':False,
    'elapsed_seconds':time.monotonic()-START}
(BASE/'artifact-audit.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
excluded={'artifact-receipts.json','artifact-receipts.json.sha256','artifact-audit.stdout.json','artifact-audit.stderr.txt','artifact-audit.time.txt'}
rows=[receipt(path) for path in sorted(BASE.rglob('*')) if path.is_file() and path.name not in excluded]
(BASE/'artifact-receipts.json').write_text(json.dumps(rows,sort_keys=True,indent=2)+'\n')
print(json.dumps(result,sort_keys=True))
