"""Small-metadata/stat preparation only; never open graph/composition/context payloads."""
import gzip
import hashlib
import json
from pathlib import Path

OUT=Path(__file__).resolve().parent
ISO=OUT.parents[2]
MAIN=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
reads=[]
def sha(b):return hashlib.sha256(b).hexdigest()
def small(path, *, compressed=False):
 p=Path(path).resolve();s=p.stat()
 if s.st_size>1000000:raise ValueError('metadata physical ceiling')
 b=p.read_bytes();d=gzip.decompress(b) if compressed else b
 if len(d)>2000000:raise ValueError('metadata decoded ceiling')
 reads.append(dict(uri=str(p),stored_bytes=len(b),stored_sha256=sha(b),decoded_bytes=len(d),decoded_sha256=sha(d)))
 return json.loads(d)
def stat_only(path, expected):
 p=Path(path).resolve();s=p.stat()
 if p.is_symlink() or s.st_size!=expected:raise ValueError('retained payload size changed')
 return dict(uri=str(p),bytes=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns,inode=s.st_ino,device=s.st_dev,verification='STAT_ONLY_PAYLOAD_NOT_OPENED')
def dump(name,d):(OUT/name).write_text(json.dumps(d,sort_keys=True,ensure_ascii=False,indent=2)+'\n')

subjects=[];texts={}
windows=[ISO/'artifacts/experiments/string_hold_source_repair_20261025/candidate02',ISO/'artifacts/experiments/generator_expression_p0_20261025/candidate03']
for window in windows:
 launch=small(window/'attempt01/launch-result.json');summary=small(window/'attempt01/result.json');selection=small(window/'selection.json')
 if launch['exit_code']!=0:raise ValueError('selection requires an actual exit0 gate')
 by_key={r['body_key']:r for r in selection['selected']}
 for path in sorted((window/'attempt01').glob('body-*-result.json')):
  result=small(path)
  if result['status']!='RECOVERED_WITH_OPEN' or result['artifact'] is None:raise ValueError('unaccepted retained body outcome')
  original=by_key[result['body_key']];work=original['work_input'];artifact=result['artifact']
  item=dict(body_key=result['body_key'],definition=work['definition'],source=work['source'],snapshot=work['snapshot'],context=work['context'],
   original_sequence=original['original_sequence'],original_work_key=original['original_work_key'],original_body_locator=original['body_locator'],
   file_index=original['file_index'],captured_code=work['captured'],code_source_origin=work['code_source_origin'],
   capabilities=original.get('requested_capabilities',work['capabilities']),source_program=dict(schema='scar.source-program',schema_version=5,
     receipt=artifact,stat=stat_only(artifact['path'],artifact['bytes']),receipt_basis='actual exit0 producer/ordinary-reader result; graph not reopened in preparation'),
   actual_gate=dict(launch=str(window/'attempt01/launch-result.json'),result=str(path),checks=result['checks']),
   static_graph_operations=result['operations_emitted'],retained_parent_call_weight=original['current_calls'],
   requested_transition='ADD_GRAPH_PENDING_EXACT_BASE858_CAS',runtime_bound=False,whole_model_complete=False)
  subjects.append(item)
  file=selection['files'][str(original['file_index'])];p=Path(file['utf8_path']);b=p.read_bytes()
  if len(b)>2000000 or 'sha256:'+sha(b)!=work['snapshot']['fingerprint']:raise ValueError('exact archived source text changed')
  texts[str(p)]=dict(uri=str(p),bytes=len(b),sha256=sha(b),logical_source=work['snapshot']['path'])
if len(subjects)!=3 or len({r['body_key'] for r in subjects})!=3 or sorted(r['static_graph_operations'] for r in subjects)!=[131,148,312]:raise ValueError('three successful qualified artifacts differ')
if sum(r['bytes'] for r in texts.values())>2000000:raise ValueError('source-text preparation budget')

base_dir=MAIN/'artifacts/experiments/source_frontend_remainder_composition_resume02_20261025'
base_result=small(base_dir/'result.json');base_manifest_path=Path(base_result['manifest']['path']);base_manifest=small(base_manifest_path)
if base_manifest['counts']['graph_bodies']!=858 or base_manifest['counts']['source_files']!=151:raise ValueError('exact858 parent counts differ')
stat_only(base_result['composition']['path'],base_result['composition']['bytes'])
lineage=[];old_programs={}
for rel in ['source_frontend_remainder_publication_20261025/result/publication/manifest.json','source_call_kwargs_publication_20261025/result/publication/manifest.json','first_stage_source_body_revision_20261023/result/publication/manifest.json','first_stage_source_publication_current_20261023/result/publication/manifest.json']:
 p=MAIN/'artifacts/experiments'/rel;m=small(p);ref=m['components']['publication'];q=Path(ref['uri']) if ref['external'] else p.parent/ref['uri'];v=small(q,compressed=True)['value']
 if reads[-1]['stored_sha256']!=ref['physical_sha256'] or reads[-1]['decoded_sha256']!=ref['decoded_sha256']:raise ValueError('publication metadata receipt mismatch')
 lineage.append(dict(snapshot_active_bodies=m['counts']['graph_bodies'],manifest_uri=str(p),publication_uri=str(q),publication_schema=v['schema_version'],base_composition=v['base_composition']))
 if v['schema_version']==2:
  for expectation in v['expectations']['expectations']:
   r=expectation['replacement'];old_programs[r['uri']]={k:r[k] for k in ('uri','physical_bytes','physical_sha256','decoded_bytes','decoded_sha256')}
# Exact full references remain the existing collections, never an invented 858-row replacement.
def loc(ref,pointer):
 uri=Path(ref['uri']) if ref['external'] else base_manifest_path.parent/ref['uri']
 return dict(artifact={**ref,'uri':str(uri)},pointer=pointer)
base=dict(composition=base_result['composition'],inventory=base_result['manifest'],manifest_counts=base_manifest['counts'],
 complete_body_definition_denominator=2217,active_graph_count=858,source_files=151,
 body_collection=dict(artifact_uri=base_result['composition']['path'],pointer='#/files/*/bodies',declared_count=2217,not_enumerated_in_preparation=True),
 active_interface_reference_collection=loc(base_manifest['components']['interfaces'],'#/value/bodies'),
 source_file_inventory_collection=dict(artifact_uri=str(base_manifest_path),pointer='#/files',declared_count=151),
 base_858_replay_performed=False,old_acceptance_result=str(base_dir/'result.json'),target_new_active_graphs_if_all_three_ADD=861,
 complete_runtime_snapshot_bodies_unchanged=843)
ancestor_unique=sum(r['base_composition']['raw_bytes']+r['base_composition']['decoded_bytes'] for r in lineage)
old_unique=sum(r['physical_bytes']+r['decoded_bytes'] for r in old_programs.values())
composition_ordinary=base_result['composition']['bytes']+sum(2*r['base_composition']['raw_bytes']+r['base_composition']['decoded_bytes'] for r in lineage)+sum(r['base_composition']['raw_bytes']+r['base_composition']['decoded_bytes'] for r in lineage[:-1])
new_unique=sum(r['source_program']['receipt']['bytes']+r['source_program']['receipt']['decoded_bytes'] for r in subjects)
unique_before_new=base_result['composition']['bytes']+ancestor_unique+old_unique
io=dict(schema='scar.source-add-input-lower-bound',schema_version=1,budget_bytes=512000000,status='PROVED_OVER_BUDGET_WITHOUT_PAYLOAD_SCAN',
 composition_only_existing_constructor_lower_bound_bytes=composition_ordinary,
 ideal_single_read_ancestor_root_bytes=ancestor_unique,ideal_single_read_old_program_bytes=old_unique,old_program_count=len(old_programs),
 current858_stored_bytes=base_result['composition']['bytes'],current858_decoded_bytes=None,
 ideal_single_read_lower_bound_before_new_three_bytes=unique_before_new,new_three_program_bytes=new_unique,
 ideal_single_read_lower_bound_with_new_three_bytes=unique_before_new+new_unique,
 lower_bound_omits=['source858 decoded bytes','source contexts','source/file/checkpoint/components metadata','all other dependency reads','output writes/roundtrips'],
 exact_total_upper_bound_bytes=None,upper_bound_not_established_reason='Already a lower bound exceeds512MB; do not read big payloads to refine an impossible budget.',
 mathematical_scope='stored+decoded bytes, same logical URI counted once only in ideal dedup floor; no same-SHA cross-URI identity merging',
 lineage=lineage,required_old_source_program_receipts=list(old_programs.values()),
 source_lines=[dict(path='scar/analysis/program_composition.py',lines=[56,677,681,685,687,728]),dict(path='scar/analysis/source_program_publication.py',lines=[119,132,187,208])])
reader_paths=['scar/analysis/program_composition.py','scar/analysis/source_program_publication.py','scar/analysis/inventory_partitions.py','scar/analysis/program_lowering.py','scar/analysis/function_interfaces.py','scar/analysis/source_generator_validation.py','scar/analysis/source_string_validation.py','scar/ir/program/codec.py','scar/ir/program/source_language.py']
code=[]
for rel in reader_paths:
 p=MAIN/rel;b=p.read_bytes();code.append(dict(uri=str(p),bytes=len(b),sha256=sha(b)))
catalog=dict(schema='scar.three-qualified-source-program-add-inputs',schema_version=1,status='PREPARED_METADATA_ONLY_BLOCKED_BY_IO_BUDGET',base=base,subjects=subjects,
 exact_source_files=len({r['snapshot']['path'] for r in subjects}),retained_parent_call_weight=sum(r['retained_parent_call_weight'] for r in subjects),
 source_text_receipts=list(texts.values()),source_text_bytes_read=sum(r['bytes'] for r in texts.values()),current_reader_sources=code,
 old_producer_sources_preserved=True,main_reader_replay_in_this_preparation=False,new_source_program_wire_fields=False,
 multi_region_scope='GEN graph contains root+B+2D+U, same CP2 source-program5 reference. Publisher _program_counts handles regions; root-only validate_body_interface filters environment by interface.region; actual new batch admission not yet run.',
 new_publication_performed=False,new_runtime_binding=False,real_body_lowerings=0,target_executions=0,graph_payload_reads=0,composition_stream_reads=0,source_context_stream_reads=0)
dump('catalog.json',catalog);dump('io_lower_bound.json',io);dump('SOURCE_RECEIPTS.json',dict(schema='scar.small-preparation-source-receipts',schema_version=1,metadata_reads=reads,source_text_receipts=list(texts.values()),reader_source_receipts=code,graph_or_big_root_or_context_reads=0))
print(json.dumps(dict(subjects=len(subjects),source_files=catalog['exact_source_files'],parent_call_weight=catalog['retained_parent_call_weight'],source_text_bytes=catalog['source_text_bytes_read'],existing_constructor_composition_lower_bound=composition_ordinary,ideal_dedup_lower_bound=unique_before_new+new_unique,status=catalog['status'])))
