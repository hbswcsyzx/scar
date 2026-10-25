"""Complete the safe input superset using the original small checkpoint index."""
import gzip
import hashlib
import json
from pathlib import Path

OUT=Path(__file__).resolve().parent
MAIN=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
d=json.loads((OUT/'READ_PLAN.json').read_bytes());items={r['uri']:r for r in d['inputs']}
p=MAIN/'artifacts/experiments/first_stage_full_inventory_restored_20261023/result/manifest.json';m=json.loads(p.read_bytes());r=m['components']['inputs'];q=Path(r['uri']) if r['external'] else p.parent/r['uri']
b=q.read_bytes();v=json.loads(gzip.decompress(b))['value'];idx=v['original_checkpoint_index'];path=Path(idx['path']);raw=path.read_bytes()
if len(raw)>1000000 or len(raw)!=idx['bytes'] or hashlib.sha256(raw).hexdigest()!=idx['sha256']:raise ValueError('original checkpoint index receipt mismatch')
added=[];original_rows=[]
for lineno,line in enumerate(raw.splitlines(),1):
 row=json.loads(line);cp=path.parent/row['file'];s=cp.stat();uri=str(cp)
 if cp.is_symlink():raise ValueError('unsafe original checkpoint')
 original_rows.append(dict(uri=uri,decoded_bytes=row['raw_bytes'],decoded_sha256=row['raw_sha256'],index_line=lineno))
 if uri in items:
  if items[uri]['decoded_bytes']!=row['raw_bytes'] or items[uri]['decoded_sha256']!=row['raw_sha256']:raise ValueError('checkpoint index/source-reference receipt differs')
 else:
  item=dict(uri=uri,stored_bytes=s.st_size,decoded_bytes=row['raw_bytes'],stored_sha256=None,decoded_sha256=row['raw_sha256'],
   role='original checkpoint, safe superset including unsupported outcomes',source_locator={'artifact_uri':str(path),'index_line':lineno},
   stored_sha_verification='deferred: actual receipt-bound normal inventory reader plus full decoded SHA; payload not opened during preparation')
  items[uri]=item;added.append(item)
items[str(path)]=dict(uri=str(path),stored_bytes=len(raw),decoded_bytes=len(raw),stored_sha256=idx['sha256'],decoded_sha256=idx['sha256'],role='original checkpoint index')
upper=sum(r['stored_bytes']+r['decoded_bytes'] for r in items.values());total=upper+d['own_new_outputs_first_read_upper_bytes']+d['metadata_guard_allowance_bytes']
# A single proposed ceiling is obtained by rounding the declared safe upper to
# the next100MB, then retaining an explicit small margin. It is not a retry rule.
ceiling=((total+99999999)//100000000)*100000000
out={**d,'inputs':list(items.values()),'declared_retained_input_upper_bytes':upper,'no_duplicate_read_total_upper_bytes':total,
 'original_checkpoint_index':idx,'original_checkpoint_rows':len(original_rows),'extra_historical_or_unsupported_inputs':len(added),
 'deferred_stored_sha_input_count':len(added),'required_session_cache_payload_bytes_upper':sum(r['decoded_bytes'] for r in items.values())+d['own_new_outputs_first_read_upper_bytes'],
 'proposed_once_ceiling_bytes':ceiling,'ceiling_not_authorized':True,
 'budget_derivation':'Strict unique URI safe superset, includes all original returns as well as all858 active references; source858 decoded capped96MB, own first output reads capped256MB, metadata allowance16MB. No payload opened. Ordinary source inventory supplies exact stored receipts for deferred rows before acceptance.',
 'preparation_payload_reads':0}
(OUT/'READ_PLAN.v2.json').write_text(json.dumps(out,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:out[k] for k in ('declared_retained_input_upper_bytes','no_duplicate_read_total_upper_bytes','original_checkpoint_rows','extra_historical_or_unsupported_inputs','deferred_stored_sha_input_count','required_session_cache_payload_bytes_upper','proposed_once_ceiling_bytes')}))
