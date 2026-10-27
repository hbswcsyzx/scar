from pathlib import Path
from hashlib import sha256
import json,os,sys,time,resource,traceback
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode,encode
from scar.analysis.native_declaration_interfaces import NativeDeclarationSession,NativeDeclarationBudget,read_native_declaration_fragment
B=Path(__file__).resolve().parent
s=json.loads((B/'SELECTION.json').read_bytes())
p=s['port_index'];index=ProviderArtifact(p['path'],p['sha256'],p['bytes'],'scar.native-boxed-port-index')
p=s['bundle'];bundle=ProviderArtifact(p['path'],p['sha256'],p['bytes'],'scar.partitioned-ir-bundle')
coordinates=ProviderArtifact('/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/native_inputs_full_20261026/native-import/capture-coordinates.json','aa387e36be71941bbcc09bed33d99850655e49713c417c98333a08dafe751017',5607897,'scar.capture-coordinates')
budget=NativeDeclarationBudget(max_input_bytes=256_000_000,max_output_bytes=16_000_000,max_seconds=120,max_fragment_bytes=16_000_000)
audit_counts={'raw_opens':[],'live_source_opens':[],'target_exec':0}
def audit(event,args):
 if event=='open'and args and isinstance(args[0],(str,bytes,os.PathLike)):
  p=os.fsdecode(args[0])
  if '/capture/trace/'in p or '/capture/os/'in p:audit_counts['raw_opens'].append(p);raise AssertionError('raw replay forbidden')
  if p.startswith('/home/zyf/AAA/le-wm/'):audit_counts['live_source_opens'].append(p);raise AssertionError('live target source forbidden')
 if event=='exec'and args and getattr(args[0],'co_filename','').startswith('/home/zyf/AAA/le-wm/'):
  audit_counts['target_exec']+=1;raise AssertionError('target exec forbidden')
sys.addaudithook(audit);start=time.monotonic();r={}
try:
 with NativeDeclarationSession(index,bundle,coordinates,budget=budget)as session:
  cat=session.prepare_catalog(B/'attempt01/catalog',shard_indices=(s['port_shard_number'],),source_ordinals=(s['source_ordinal'],))
  shard=session.publish_shard(s['port_shard_number'],B/'attempt01/shard',source_ordinals=(s['source_ordinal'],))
  producer_measurement=session.meter.finish()
 d=json.loads(Path(shard.uri).read_bytes());fragment=decode(ProviderArtifact,d['fragments'][0])
 view=read_native_declaration_fragment(fragment,budget=budget)
 assert d['canonical_input_ports']==6 and d['conditional_output_ports']==1
 assert d['canonical_operation_occurrences']==1 and d['completion_selected_count']==0
 assert len(view.execution.operations)==1 and not view.execution.transfers
 assert len(view.execution.values)==7 and len(view.execution.denotations)==6
 assert view.occurrences[0].native.instance.value.endswith(':eto:21')
 assert s['metadata']['canonical_status']=='CANONICAL_NATIVE_BOUNDARY_UNAVAILABLE'
 r={'status':'PASS','index':encode(index),'bundle':encode(bundle),'coordinates':encode(coordinates),
  'catalog':encode(cat),'shard':encode(shard),'fragment':encode(fragment),
  'source_ordinal':s['source_ordinal'],'old_canonical_status':s['metadata']['canonical_status'],
  'producer_measurement':producer_measurement,'reader_measurement':view.measurements,
  'scope_denominators':s['denominators'],'counts':{k:d[k]for k in ('declared_operation_rows','selected_operation_rows','processed_operation_rows','canonical_operation_occurrences','canonical_input_ports','conditional_output_ports','completion_selected_count')},
  'validation':{'valid':view.validation.valid,'issues':encode(view.validation.issues),'gaps':encode(view.validation.gaps)},
  'source_binding':encode(view.occurrences[0]),'execution_counts':{'operations':len(view.execution.operations),'values':len(view.execution.values),'uses':len(view.execution.uses),'transfers':len(view.execution.transfers)}}
except BaseException as e:r={'status':'FAILED','type':type(e).__name__,'detail':str(e),'traceback':traceback.format_exc()}
finally:
 r.update(wall_seconds=time.monotonic()-start,max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,audit=audit_counts,
  source_sha256={str(p):sha256(p.read_bytes()).hexdigest()for p in (Path('scar/analysis/native_declaration_interfaces.py'),Path('scar/ir/execution/native_declarations.py'),Path('scar/trace/native_protocol.py'))})
 (B/'attempt01/RESULT.json').write_text(json.dumps(r,sort_keys=True,indent=2)+'\n');print(json.dumps(r,sort_keys=True,indent=2))
 if r['status']!='PASS':sys.exit(1)
