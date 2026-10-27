"""Mechanical CUDA candidate selection in one original small navigation chunk."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import gzip,json,time
from scar.trace.native_tensor_inputs import _json as strict_json
B=Path(__file__).resolve().parent
inputs=json.loads((B/'INPUTS.json').read_bytes());art=inputs['navigation'];p=Path(art['uri']);before=p.stat();raw=p.read_bytes()
assert len(raw)==art['size_bytes']and sha256(raw).hexdigest()==art['sha256']and before==p.stat()
m=strict_json(raw);chunk=m['tables']['associations']['chunks'][0];relative=Path(chunk['path'])
assert not relative.is_absolute()and '..'not in relative.parts
p=Path(art['uri']).parent/relative;before=p.stat();packed=p.read_bytes()
assert len(packed)==chunk['size_bytes']and sha256(packed).hexdigest()==chunk['sha256']and before==p.stat()
assert chunk['raw_bytes']<=8_000_000
with gzip.GzipFile(fileobj=BytesIO(packed))as f:
 decoded=f.read(chunk['raw_bytes']+1)
assert len(decoded)==chunk['raw_bytes']and sha256(decoded).hexdigest()==chunk['raw_sha256']
rows=[strict_json(line)for line in decoded.splitlines()];assert len(rows)==chunk['rows']
def supported(r):
 e=r['provider_epoch'];d=r['metadata'].get('device')
 return d is not None and d['text'].split(':')[0]=='cuda'and e['status']=='OBSERVED_PROVIDER_EPOCH_REFERENCE'
selected=next((r for r in rows if supported(r)),None)
result={'status':'FOUND'if selected else 'NO_CUDA_IN_SELECTED_CHUNK',
 'selection':'first original order row with typed device cuda and observed exact provider epoch; one chunk only',
 'navigation':art,'source_chunk':chunk,'rows_checked':len(rows),
 'stored_bytes':len(raw)+len(packed),'decoded_bytes':len(raw)+len(decoded),
 'scope':'candidate only; original endpoint/epoch/allocation normal verification follows', 'selected':selected}
(B/'gpu01/SELECTION.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items()if k not in('selected','navigation','source_chunk')},sort_keys=True))
if selected:print(json.dumps({'row':selected['row'],'path':selected['path'],'device':selected['metadata']['device'],'epoch':selected['provider_epoch']},sort_keys=True))
