"""Select one retained relation row and pin its already-declared inputs only."""
from pathlib import Path
import hashlib,json
from dataclasses import fields
from scar.ir.execution.fragment_relations import RuntimeScope,WorkTicketRef,stable_key
from scar.ir.record_codec import decode,encode
from scar.store.fragment_relations import RelationPartitions,RelationBudgets,Meter
BASE=Path(__file__).resolve().parent;ROOT=BASE.parents[3];OLD=BASE.parent/'candidate02'
def raw(v):return (json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode()
def rec(p):
 p=Path(p);v=p.read_bytes();return {'path':str(p),'bytes':len(v),'sha256':hashlib.sha256(v).hexdigest()}
def stat(p):
 p=Path(p);s=p.stat();return {'path':str(p),'bytes':s.st_size,'device':s.st_dev,'inode':s.st_ino,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}
def main():
 if (BASE/'freeze.json').exists():raise FileExistsError('freeze already exists')
 p=OLD/'attempt01/result/manifest.json';manifest=json.loads(p.read_bytes());mr=rec(p)
 selected=manifest['report']['first_static_body_work'];assert selected is not None
 budget=RelationBudgets(max_input_bytes=320_000_000,max_core_input_bytes=256_000_000,max_code_source_bytes=64_000_000,max_output_bytes=16_000_000,max_seconds=180)
 reader=RelationPartitions(p,expected_sha256=mr['sha256'],budgets=budget);meter=Meter(budget);cache={}
 identity='work_relation:'+stable_key((decode(RuntimeScope,selected['scope']),decode(WorkTicketRef,selected['work'])))
 document=reader._lookup('work',identity,meter,cache)
 assert document['relation_id']==identity
 row=document['record'];body=next(r['body'] for r in row['static_bindings'] if r['body'] and r['body']['graph']['decoded_bytes']<=budget.max_metadata_bytes)
 selection={'manifest':mr,'selected_work':selected,'static_reference':body,'old_failure':str(OLD/'attempt01/failure.json'),'old_freeze':str(OLD/'freeze.json'),'original_window_exit_code':1}
 (BASE/'selection.json').write_bytes(raw(selection))
 paths=set()
 def collect(value):
  if isinstance(value,dict):
   if {'uri','sha256','size_bytes','schema'}<=value.keys():paths.add(value['uri'])
   for v in value.values():collect(v)
  elif isinstance(value,list):
   for v in value:collect(v)
 collect(manifest['catalog']);collect(row);paths.add(str(p));paths.add(selection['old_failure']);paths.add(selection['old_freeze'])
 # Native shared static graph and actual current bindings are read by normal validation.
 native=json.loads(Path(manifest['catalog']['native_batch_report']['uri']).read_bytes());paths.add(native['shared_program']['uri'])
 source=json.loads(Path(manifest['catalog']['source_report']['uri']).read_bytes());paths.add(str(Path(manifest['catalog']['source_report']['uri']).parent/source['bindings']['path']))
 # Retention index/chunks are small output projections. Freeze all descriptors;
 # ordinary lookup reads only selected ones, not this entire family.
 for family in ('work','work_index','source','source_index'):
  paths.update(str(p.parent/d['uri']) for d in manifest[family])
 existing=[];unopened_refs=[]
 original_inputs={r['path']:r for r in json.loads((OLD/'freeze.json').read_bytes())['inputs']}
 for path in sorted(paths):
  q=Path(path)
  # Logical invocation facts use decoded identities and are never opened.
  if path in original_inputs or q.is_relative_to(p.parent) or path in (selection['old_failure'],selection['old_freeze']):
   if not q.exists():raise FileNotFoundError(path)
   existing.append(stat(q))
  else:unopened_refs.append(path)
 old_sources=json.loads((OLD/'PREPARATION_RECEIPT.json').read_bytes())['production_sources']
 sources=[]
 for r in old_sources:
  actual=rec(r['path']);assert actual['sha256']==r['sha256'];sources.append(actual)
 for name in ('scar/ir/program/codec.py','scar/ir/execution/codec.py','scar/ir/record_codec.py'):
  sources.append(rec(ROOT/name))
 freeze={'schema':'scar.fragment-relations-normal-reader-postflight','schema_version':1,'sources':sources,'tools':[rec(BASE/'run_postflight.py'),rec(BASE/'prepare_postflight.py'),rec(BASE/'selection.json')],'inputs':existing,'limits':{f.name:getattr(budget,f.name) for f in fields(budget)},'qualification':'CURRENT_SELECTED_NORMAL_READER_AND_INDEPENDENT_STATIC_CORE_MEMBERSHIP; ORIGINAL_EXIT1_REMAINS','public_static_member_helper_passed':False}
 (BASE/'freeze.json').write_bytes(raw(freeze));receipt={'status':'FROZEN_NOT_RUN','freeze':rec(BASE/'freeze.json'),'selected_relation_id':identity,'input_stat_count':len(existing),'original_five_sources_unchanged':True,'preparation_relation_chunk_metadata_io':meter.receipt(),'large_eeg_program_or_work_input_bodies_read_during_preparation':False,'unopened_original_fact_uris':unopened_refs,'budgets':freeze['limits'],'runtime_source_closure_requalification':'NOT_PERFORMED; ONLY_EXPLICIT_SOURCES_PINNED'}
 (BASE/'PREPARATION_RECEIPT.json').write_bytes(raw(receipt));print(json.dumps({'freeze':receipt['freeze'],'selected_relation_id':identity,'input_stats':len(existing),'metadata_preparation_input':meter.receipt()['actual_input_bytes']}))
if __name__=='__main__':main()
