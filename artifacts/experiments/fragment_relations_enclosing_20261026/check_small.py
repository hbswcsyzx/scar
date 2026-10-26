from pathlib import Path
from dataclasses import replace
import ast,gzip,hashlib,json,sqlite3,time
from scar.ir.execution.fragment_relations import *
from scar.ir.execution.fragment_relations_codec import dumps,loads,to_dict,from_dict
from scar.ir.record_codec import decode
from scar.ir.v2 import OperationInstance
from scar.analysis.fragment_relations import _check_eto_chain,_parent_fields
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
BASE=ROOT/'artifacts/experiments/fragment_relations_implementation_20261026/candidate02/attempt01/result'
start=time.monotonic();checks=[]
def check(name,value):
 if not value:raise AssertionError(name)
 checks.append(name)
def reject(name,call):
 try:call()
 except (ValueError,TypeError):checks.append(name);return
 raise AssertionError('accepted '+name)
for name in ('scar/ir/execution/fragment_relations.py','scar/ir/execution/fragment_relations_codec.py','scar/store/fragment_relations.py','scar/analysis/fragment_relations.py'):
 ast.parse((ROOT/name).read_text(),filename=name)
m=json.loads((BASE/'manifest.json').read_text());d=m['work'][0];stored=(BASE/d['uri']).read_bytes();raw=gzip.decompress(stored)
check('old_actual_chunk_stored_sha',hashlib.sha256(stored).hexdigest()==d['stored_sha256'])
check('old_actual_chunk_decoded_sha',hashlib.sha256(raw).hexdigest()==d['decoded_sha256'])
line=raw.splitlines(keepends=True)[0];row=loads(line.decode())
check('actual_v1_default_bytes_unchanged',dumps(row).encode()==line)
check('actual_v1_id_unchanged',row.id==json.loads(line)['relation_id'])
check('v1_old_fourteen_types',len(RECORD_TYPES)==14)
for line2 in raw.splitlines(keepends=True):
 candidate=from_dict(json.loads(line2))
 if not any(h.native is not None for h in candidate.hosts):row=candidate;break
else:raise AssertionError('no original missing work in first actual chunk')
db=sqlite3.connect('file:'+str(BASE/'locator.sqlite')+'?mode=ro&immutable=1',uri=True);db.execute('PRAGMA query_only=ON')
eeg=m['catalog']['original_eeg_manifest'];ep=Path(eeg['uri']);eraw=ep.read_bytes();check('original_eeg_root_sha',hashlib.sha256(eraw).hexdigest()==eeg['sha256']);em=json.loads(eraw)
def reference(key):
 ordinal=db.execute('SELECT ordinal FROM nodes WHERE id=?',(key,)).fetchone()[0]
 ds=em['graphs']['evidence']['tables']['instances']['chunks']
 n,desc=next((n,x) for n,x in enumerate(ds) if x['first_ordinal']<=ordinal<=x['last_ordinal'])
 loc=FragmentLocator(ProviderArtifact(str(ep.parent/desc['uri']),desc['physical_sha256'],desc['physical_bytes'],'scar.original-eeg-instances.jsonl'),desc['decoded_sha256'],desc['decoded_bytes'],Encoding.GZIP_JSONL,ordinal-desc['first_ordinal']+1,'#/record',ProviderFactReference(decode(ProviderArtifact,eeg),'#/graphs/evidence/tables/instances/chunks/'+str(n)))
 return EvidenceInstanceRef(loc,OperationInstanceID(key.removeprefix('opinst:')))
host=next(h.host for h in row.hosts if h.kind is HostRelationKind.PROVIDER_SCOPE_CONTEXT)
parents=[];current=host.instance.wire
while True:
 current=db.execute('SELECT parent FROM nodes WHERE id=?',(current,)).fetchone()[0];assert current
 parents.append(reference(current));native=db.execute('SELECT ref FROM native WHERE instance=? ORDER BY sequence',(current,)).fetchall()
 if native:break
ref=decode(QualifiedOccurrenceRef,json.loads(native[0][0]));enclosing=EnclosingNativeRelation(row.projection.scope,host,tuple(parents),ref)
v2=replace(row,enclosing_native=(enclosing,))
check('v2_actual_qualified_endpoints_roundtrip',loads(dumps(v2,schema_version=2))==v2)
check('v2_enclosing_aggregate_same_work_id',v2.id==row.id)
check('standalone_enclosing_v2_roundtrip',loads(dumps(enclosing,schema_version=2))==enclosing)
reject('default_v1_rejects_nonempty_enclosing',lambda:dumps(v2))
reject('v1_rejects_new_fifteenth_type',lambda:dumps(enclosing))
wire=to_dict(row);wire['record']['enclosing_native']=[]
reject('v1_closed_field_set',lambda:from_dict(wire))
reject('host_native_cannot_be_replaced_by_ancestor',lambda:replace(next(h for h in row.hosts if h.host==host),native=ref))
reject('parent_path_rejects_cycle',lambda:replace(enclosing,parents=(host,)+enclosing.parents))
# Two already-retained ORIGINAL EEG records; no further EEG chunk or target read.
rows=json.loads((ROOT/'artifacts/analysis/fragment_relation_gaps_20261026/PARENT_SAMPLE_ROWS.json').read_text())
a,b=(decode(OperationInstance,rows[str(n)]['record']) for n in (17303,17304))
rnative=db.execute('SELECT ref FROM native WHERE instance=?',(b.id.wire,)).fetchone()[0]
r=EnclosingNativeRelation(row.projection.scope,reference(a.id.wire),(reference(b.id.wire),),decode(QualifiedOccurrenceRef,json.loads(rnative)))
coordinate=Path(m['catalog']['coordinates']['uri']);cr=coordinate.read_bytes();check('coordinate_sha',hashlib.sha256(cr).hexdigest()==m['catalog']['coordinates']['sha256'])
c=json.loads(cr);_check_eto_chain(r,(a,b),a.process_id,c);checks.append('actual_two_record_parent_fields_pass')
_check_eto_chain(r,(_parent_fields(r.host,a),_parent_fields(r.parents[0],b)),a.process_id,c);checks.append('owned_typed_field_projection_same_chain')
bad=replace(a,metadata={**a.metadata,'ctrl_deps':a.metadata['ctrl_deps']+1})
reject('wrong_ctrl_deps_rejected',lambda:_check_eto_chain(r,(bad,b),a.process_id,c))
bad=replace(b,metadata={**b.metadata,'eto_tid':2})
reject('cross_collector_thread_rejected',lambda:_check_eto_chain(r,(a,bad),a.process_id,c))
result={'status':'PASSED_TYPED_CODEC_AND_ORIGINAL_FIELD_CHECKS_ONLY','checks':checks,'elapsed_s':time.monotonic()-start,'old_work':row.id,'new_enclosing':enclosing.id,'small_actual_chunk':d,'sqlite':'readonly immutable selected locator declarations; old native model not requalified','source_runtime_whole_model_established':False,'producer_or_target_executed':False,'production_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('scar/ir/execution/fragment_relations.py','scar/ir/execution/fragment_relations_codec.py','scar/store/fragment_relations.py','scar/analysis/fragment_relations.py')},'input':{'stored_work_chunk_bytes':len(stored),'decoded_work_chunk_bytes':len(raw),'eeg_manifest_bytes':len(eraw),'coordinates_bytes':len(cr),'sqlite_selected_page_reads_not_independently_metered':True}}
(OUT/'SMALL_CHECK.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
