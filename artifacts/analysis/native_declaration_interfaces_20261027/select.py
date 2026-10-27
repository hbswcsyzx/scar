"""Select one schema-backed original operator outside marker canonical coverage."""
from pathlib import Path
from hashlib import sha256
from io import BytesIO
import gzip,json
from scar.ir.record_codec import decode,encode
from scar.ir.v2.evidence import OperationInstance
from scar.ir.v2.semantic import OperationDefinition
from scar.store.bundle_partitions import BundlePartitions
from scar.trace.native_port_sidecar import read_native_port_index,_read_shard
B=Path(__file__).resolve().parent
P=Path('/home/zyf/AAA/scar-worktrees/frame-entry-routing/artifacts/analysis/native_port_sidecar_full_20261026/publication/index.json')
I=Path('/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/native_inputs_full_20261026/attempt05/native-input-connections/input-metadata/manifest.json')
M=Path('/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/native_inputs_full_20261026/native-import/native/bundle-partitions/manifest.json')
def read(p,sha,n):
 a=p.stat();r=p.read_bytes();assert len(r)==n and __import__('hashlib').sha256(r).hexdigest()==sha and a==p.stat();return r
m=json.loads(read(I,'7b6be9bd049ad7a6e59bf4f3c1342b085c96d996c77ca02a2017ce82190fc9e3',115602));ref=m['tables']['rows']['chunks'][0]
raw=read(I.parent/ref['path'],ref['sha256'],ref['size_bytes'])
with gzip.GzipFile(fileobj=BytesIO(raw))as f:d=f.read(ref['raw_bytes']+1)
assert len(d)==ref['raw_bytes']and sha256(d).hexdigest()==ref['raw_sha256']
rows=[json.loads(x)for x in d.splitlines()];assert len(rows)==ref['rows']
selected=next(r for r in rows if r['canonical_status']=='CANONICAL_NATIVE_BOUNDARY_UNAVAILABLE'and r.get('schema_text_present')is True and r.get('metadata'))
ordinal=int(selected['original_node']['locator'].split('/')[-1])
idx=read_native_port_index(P,expected_sha256='54f9dfbcc8a4e3cfc720c2dfb0c377d61707cde3f70c1360f1f68fd54cbf17b2')
part=BundlePartitions(M);assert part.manifest_receipt['physical_sha256']==idx.evidence_manifest_sha256=='3a2a80d64ff7e67d72545aefe0154b0f48fa18a855847005675221c86954c29b'
shardno=next(i for i,r in enumerate(idx.shards)if r.first_source_ordinal<=ordinal<r.stop_source_ordinal)
portshard=_read_shard(P.parent,idx.shards[shardno]);portrow=next(r for r in portshard.rows if r.source_ordinal==ordinal)
e=part.selected_records('evidence','instances',(ordinal,))[0];inst=decode(OperationInstance,e['record']);assert inst.id==portrow.instance and inst.definition==portrow.definition
# Only the first already-published semantic chunk, never a whole catalog/raw scan.
chunk=part.manifest['graphs']['semantic']['tables']['definitions']['chunks'][0]
defrow=next((r for r in part.selected_records('semantic','definitions',tuple(range(chunk['first_ordinal'],chunk['last_ordinal']+1)))if r['record']['id']['wire']==portrow.definition.wire),None)
assert defrow is not None,'selected original definition is outside first local chunk'
definition=decode(OperationDefinition,defrow['record'])
result={'selection':'first original metadata row with missing canonical boundary, actual schema, nonempty metadata; restricted first chunk',
 'metadata_index':{'path':str(I),'sha256':'7b6be9bd049ad7a6e59bf4f3c1342b085c96d996c77ca02a2017ce82190fc9e3','bytes':115602},'metadata_chunk':ref,'metadata':selected,
 'port_index':{'path':str(P),'sha256':'54f9dfbcc8a4e3cfc720c2dfb0c377d61707cde3f70c1360f1f68fd54cbf17b2','bytes':P.stat().st_size},
 'bundle':{'path':str(M),'sha256':idx.evidence_manifest_sha256,'bytes':M.stat().st_size},
 'source_ordinal':ordinal,'port_shard_number':shardno,'port_row':encode(portrow),'original_instance':e,'original_definition':defrow,
 'denominators':{'source_nodes':idx.source_nodes,'operator_rows':idx.operation_rows,'input_ports':idx.input_ports,'output_ports':idx.output_ports,'classification_counts':idx.classification_counts,'metadata_tensor_paths':420444,'metadata_old_associated':65130,'metadata_old_canonical_boundary_unavailable':355314}}
(B/'SELECTION.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print(json.dumps({'source_ordinal':ordinal,'node_id':inst.metadata['node_id'],'label':definition.label,'schema':definition.metadata.get('native_schema_contract',{}),'ports':len(portrow.ports),'definition_ordinal':defrow['ordinal'],'metadata_row':selected['index'],'instance_id':inst.id.wire},sort_keys=True)[:3500])
