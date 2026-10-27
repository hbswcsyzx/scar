"""One hypothetical arithmetic counterexample, not an observed allocation."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json,time
from scar.analysis.native_input_storage_bridge import _unique_region
from scar.ir.record_codec import decode
from scar.ir.v2.values import StorageAllocation
B=Path(__file__).resolve().parent
q=json.loads((B/'QUERY.json').read_bytes())
a={'metadata':q['observed_metadata'],'metadata_source':q['metadata_source'],
 'provider_epoch':q['provider_epoch'],'native_input':q['native_input'],'canonical_parent':q['canonical_parent']}
allocation=decode(StorageAllocation,q['allocation']);hypothetical=replace(allocation,nbytes=8)
start=time.monotonic();result=_unique_region(a,hypothetical)
assert result['status']=='OPEN'and result['region']is None
assert result['reason']=='BOUNDING_SPAN_DOES_NOT_EXHAUST_ALLOCATION'
assert result['constraints']['offset_elements_minimum']==0
assert result['constraints']['offset_elements_maximum']==1
result={'status':'PASS','scope':'one hypothetical extent8B counterexample; no retained source/record modified or qualified',
 'normal_reference':{'uri':str(B/'QUERY.json'),'sha256':sha256((B/'QUERY.json').read_bytes()).hexdigest()},
 'result':result,'seconds':time.monotonic()-start}
(B/'NONUNIQUE.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps({'status':result['status'],'scope':result['scope'],'seconds':result['seconds']}))
