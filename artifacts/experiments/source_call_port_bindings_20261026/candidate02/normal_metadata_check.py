"""Normal partition origin only; no CompositionIndex/CodeWitness/graph/raw read."""
from pathlib import Path
import hashlib,json,time
from config import HERE,REMAINDER,OLD
from scar.analysis.inventory_partitions import InventoryPartitions
start=time.monotonic()
closure=json.loads((HERE/'NEEDED_INPUT_CLOSURE.json').read_text())
if closure['missing_count']:raise ValueError('normal metadata closure incomplete')
root=InventoryPartitions(REMAINDER/'result/publication/manifest.json')
origin=root.code_source_origin()
previous=json.loads((OLD/'result/source/report.json').read_text())
if origin['inventory']!=previous['inventory']:raise ValueError('normal original compiler inventory differs from retained proof')
read_paths=closure['inventory_ancestors']+[origin['call_sources']['artifact']['uri']]
rows=[]
for path in read_paths:
 p=Path(path);raw=p.read_bytes();rows.append({'path':path,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
result={'status':'PASS_NORMAL_INVENTORY_ORIGIN_METADATA_ONLY','normal_reader':'InventoryPartitions.code_source_origin','inventory_ancestors':len(closure['inventory_ancestors']),'origin':origin,'actual_receipts':rows,'elapsed_s':time.monotonic()-start,'CodeWitness_constructed':False,'consumer_started':False,'CompositionIndex_constructed':False,'raw_or_graph_read':False,'retained858_binding_used_as_live_owner':False,'full_gate_pass_claimed':False}
with (HERE/'NORMAL_METADATA_CHECK.json').open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
print(json.dumps({'status':result['status'],'ancestors':result['inventory_ancestors'],'elapsed_s':result['elapsed_s']}))
