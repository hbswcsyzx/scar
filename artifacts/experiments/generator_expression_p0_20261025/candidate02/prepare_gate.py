"""Small retained metadata only. Never read composition/context streams or lower."""
import ast
import gzip
import hashlib
import json
from pathlib import Path
import runpy
import sys

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[3]
MAIN=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
OLD=MAIN/'artifacts/experiments/source_frontend_remainder_attempt02_20261025'
TEMPLATE=ROOT/'artifacts/experiments/string_hold_source_repair_20261025/candidate02'

def raw(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,indent=2)+'\n').encode()
def sha(v):return hashlib.sha256(v).hexdigest()
def source(path):
 p=Path(path).resolve();data=p.read_bytes();return dict(path=str(p),bytes=len(data),sha256=sha(data))
def pin(path, *, stored_bytes=None,stored_sha=None,decoded_bytes=None,decoded_sha=None):
 p=Path(path).resolve();s=p.stat()
 if p.is_symlink() or stored_bytes is not None and s.st_size!=stored_bytes:raise ValueError('retained physical input declaration differs')
 if stored_sha is None:
  if s.st_size>1_000_000:raise ValueError('preparation may hash small metadata only')
  stored_sha=sha(p.read_bytes())
 return dict(path=str(p),stored_bytes=s.st_size,stored_sha256=stored_sha,decoded_bytes=s.st_size if decoded_bytes is None else decoded_bytes,
  decoded_sha256=stored_sha if decoded_sha is None else decoded_sha,size=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns,inode=s.st_ino,device=s.st_dev)
def artifact(base,row):
 p=Path(row['uri']) if row['external'] else base/row['uri']
 return pin(p,stored_bytes=row['physical_bytes'],stored_sha=row['physical_sha256'],decoded_bytes=row['decoded_bytes'],decoded_sha=row['decoded_sha256'])
def reference(row):return dict(path=row['path'],bytes=row['stored_bytes'],sha256=row['stored_sha256'])
def metadata(path):
 p=pin(path);return json.loads(Path(p['path']).read_bytes()),p

def main():
 template=json.loads((TEMPLATE/'freeze.json').read_bytes());oldselection=json.loads((TEMPLATE/'selection.json').read_bytes())
 design_path=ROOT/'artifacts/analysis/generator_expression_design_20261025/SOURCE_RECEIPTS.json'
 design,dp=metadata(design_path);case=max(design['subjects'],key=lambda r:r['parent_calls_in_existing_catalog'])
 prior,pr=metadata(case['result']['path']);ready,rr=metadata(Path(pr['path']).with_name('ready.json'))
 if prior['status']!='UNSUPPORTED' or prior['body_key']!=case['body_key'] or prior['work_input']!=ready['work_input']:raise ValueError('original qualified subject changed')
 work=prior['work_input']
 report,rp=metadata(oldselection['current_report']);manifest,mp=metadata(report['inventory']['path'])
 if report['inventory']['raw_sha256']!=mp['stored_sha256'] or report['inventory']['raw_bytes']!=mp['stored_bytes']:raise ValueError('exact retained report/inventory mismatch')
 matches=[i for i,row in enumerate(manifest['files']) if str(Path(row['uri']) if row['external'] else Path(mp['path']).parent/row['uri'])==prior['body_locator']['artifact']['uri']]
 if len(matches)!=1:raise ValueError('old qualified subject has no unique retained current file')
 fi=matches[0]
 groups_pin=next(r for r in template['inputs'] if r['path'].endswith('/plan/groups.json.gz'))
 b=Path(groups_pin['path']).read_bytes()
 if sha(b)!=groups_pin['stored_sha256']:raise ValueError('retained group catalog physical SHA differs')
 data=gzip.decompress(b)
 if len(data)!=groups_pin['decoded_bytes'] or len(data)>1_000_000 or sha(data)!=groups_pin['decoded_sha256']:raise ValueError('retained group catalog decoded receipt differs')
 groups=[r for r in json.loads(data)['rows'] if r['body_key']==prior['body_key'] and r['captured']==work['captured']]
 if sum(r['current_calls'] for r in groups)!=case['parent_calls_in_existing_catalog']:raise ValueError('old qualified call denominator differs')
 text=Path(case['source_utf8']['path']).read_bytes()
 if len(text)!=case['source_utf8']['bytes'] or sha(text)!=case['source_utf8']['sha256']:raise ValueError('exact retained UTF8 differs')
 tree=ast.parse(text.decode(),filename=work['snapshot']['path']);ref=case['generator_atom']['reference']
 nodes=[n for n in ast.walk(tree) if isinstance(n,ast.GeneratorExp) and (n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)==(ref['start_line'],ref['end_line'],ref['start_column'],ref['end_column'])]
 if len(nodes)!=1:raise ValueError('qualified GeneratorExp AST differs')
 parents=[p for p in ast.walk(tree) if nodes[0] in tuple(ast.iter_child_nodes(p))]
 if len(parents)!=1 or not isinstance(parents[0],ast.Assign) or len(parents[0].targets)!=1 or not isinstance(parents[0].targets[0],(ast.Tuple,ast.List)):raise ValueError('fixed-unpack AST predicate differs')
 inputs={}
 # Keep the previously approved small ancestry closure. Unused old context/
 # witness/file records are excluded; the original root pin is reused by stat.
 omitted=('source-layers/archives/','code-witnesses/10c','code-witnesses/340','code-witnesses/7dc','code-witnesses/c86','/sources/00124.','/sources/00133.','worker/attempt-00015/','worker/attempt-00061/')
 for row in template['inputs']:
  if any(v in row['path'] for v in omitted):continue
  p=Path(row['path']);s=p.stat()
  if (s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_ino,s.st_dev)!=(row['size'],row['mtime_ns'],row['ctime_ns'],row['inode'],row['device']):raise ValueError('prior retained metadata/root pin changed')
  inputs[row['path']]=row
 for row in (pr,rr,dp,rp,mp):inputs[row['path']]=row
 for key in ('source_archive','source_utf8','module'):
  r=case[key];row=pin(r['path'],stored_bytes=r['bytes'],stored_sha=r['sha256'],decoded_bytes=r.get('decoded_bytes'),decoded_sha=r.get('decoded_sha256'));inputs[row['path']]=row
 for path in (Path(report['inventory']['path']),MAIN/'artifacts/experiments/first_stage_full_inventory_restored_20261023/result/manifest.json'):
  doc=json.loads(path.read_bytes());row=artifact(path.parent,doc['files'][fi]);inputs[row['path']]=row
 selected=dict(original_sequence=prior['sequence'],original_work_key=prior['work_key'],body_key=prior['body_key'],body_locator=prior['body_locator'],file_index=fi,
  work_input=work,old_code_witness=prior['code_witness'],prior_result=reference(pr),prior_ready=reference(rr),current_calls=sum(r['current_calls'] for r in groups),
  original_groups=groups,trigger_sources=[ref],requested_capabilities=[*work['capabilities'],'PYTHON_GENEXPR_314_V1'])
 parent=dict(oldselection['parent_scope']);parent.update(retry_calls=selected['current_calls'],selection_rule='one original qualified UNSUPPORTED fixed-unpack GeneratorExp; no successful-body replay; no name rule')
 selection=dict(schema='scar.genexpr-qualified-retained-inputs',schema_version=1,status='PREPARED_NOT_RUN',selected=[selected],
  files={str(fi):dict(source_path=work['snapshot']['path'],snapshot=work['snapshot'],context=work['context'],context_path=case['source_archive']['path'],utf8_path=case['source_utf8']['path'])},
  current_report=oldselection['current_report'],run=report['run'],compiler_origin_composition=oldselection['compiler_origin_composition'],store=oldselection['store'],
  qualification_metadata=[reference(pr),reference(rr),reference(dp)],parent_scope=parent,one_original_composition_only=True,
  unchanged_other_generator_subjects=[dict(body_key=r['body_key'],original_sequence=r['original_sequence'],parent_calls=r['parent_calls_in_existing_catalog'],status='NOT_ATTEMPTED_THIS_WINDOW_UNSUPPORTED_RETAINED') for r in design['subjects'] if r['body_key']!=case['body_key']])
 (BASE/'selection.json').write_bytes(raw(selection))
 api=runpy.run_path(str(BASE/'run_gate.py'),run_name='prepare_imports');runtime=api['preload_readers']()
 runtimes=[source(p) for p in sorted(set(runtime.values())) if Path(p).is_file()]
 fixed=[source(p) for p in [BASE/'prepare_gate.py',BASE/'run_gate.py',BASE/'gate_guards.py',BASE/'selection.json',BASE.parent/'APPLICATION_RECEIPT.v2.json',BASE.parent/'check12.json',Path(sys.executable).resolve(),Path('/usr/bin/time')]]
 fixed=list({r['path']:r for r in fixed+runtimes}.values());candidates=[source(p) for p in sorted((ROOT/'scar').rglob('*.py'))]
 application=json.loads((BASE.parent/'APPLICATION_RECEIPT.v2.json').read_bytes());production=[{**source(ROOT/r['path']),'relative_path':r['path']} for r in application['production_files']]
 limits={**template['limits'],'bodies':1,'source_files':1,'total_operations':4000}
 freeze={**{k:v for k,v in template.items() if k not in ('parent_archive_commit_from_root','call_selection')},'schema':'scar.genexpr-body-gate-freeze','call_selection':'original qualified OPAQUE GeneratorExp, unique childCode, fixed-unpack assignment; no business or callee-name rule','candidate':'generator_expression_p0_candidate02','status':'FROZEN_NOT_RUN','production_sources':production,
  'candidate_scar_sources':candidates,'small_frozen_files':fixed,'runtime_modules':runtimes,'inputs':sorted(inputs.values(),key=lambda r:r['path']),
  'attempt':str(BASE/'attempt01'),'active_subjects':1,'actual_source_files':1,'full_parent_subjects':65,'parent_scope':parent,
  'internal_check_inputs':[dict(path=str(BASE/'freeze.json'),role='ROOT_APPROVED_FREEZE_SHA256',max_bytes=1000000)],
  'limits':limits,'capabilities':selected['requested_capabilities'],'allowed_composition_roots':[selection['compiler_origin_composition']],
  'reuse_policy':'one original compiler-origin composition, exact one source context and readonly witness; never re-lower accepted body',
  'remaining_selection_rule':parent['selection_rule'],'changed_sources':[r['path'] for r in production]}
 if "if attempt!=BASE/'attempt01':" not in (BASE/'run_gate.py').read_text() or 'attempt04' in (BASE/'run_gate.py').read_text():raise ValueError('fresh attempt path mismatch')
 (BASE/'freeze.json').write_bytes(raw(freeze))
 receipt=dict(status='FROZEN_NOT_RUN',freeze_sha256=sha((BASE/'freeze.json').read_bytes()),attempt=freeze['attempt'],source_files_frozen=len(candidates),runtime_files=len(runtimes),input_stat_pins=len(inputs),
  guard_bytes=sum(r['bytes'] for r in fixed+candidates),production_sources=production,original_sequence=selected['original_sequence'],qualified_body_key=selected['body_key'],parent_body_calls=selected['current_calls'],
  other_generator_parent_calls=4,body_lowerings=0,target_executions=0,target_compilations=0,code_payloads_loaded=0,composition_stream_reads=0,source_context_stream_reads=0,
  readonly_small_group_catalog_decoded_bytes=len(data),limits=limits,whole_program_established=False)
 (BASE/'PREPARATION_RECEIPT.json').write_bytes(raw(receipt));print(json.dumps(receipt,sort_keys=True))

if __name__=='__main__':main()
