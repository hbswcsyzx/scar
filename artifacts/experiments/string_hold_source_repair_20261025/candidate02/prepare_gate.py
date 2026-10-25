"""Prepare exactly two retained FAILED subjects, never plan/lower a batch."""
import ast
import difflib
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
TEMPLATE=ROOT/'artifacts/experiments/source_joinedstr_target_20261025/candidate03'

def raw(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def sha(b):return hashlib.sha256(b).hexdigest()
def ref(row):return {'path':row['path'],'bytes':row['stored_bytes'],'sha256':row['stored_sha256']}
def source(path):
    b=Path(path).read_bytes();return {'path':str(path),'bytes':len(b),'sha256':sha(b)}
def pin(path,*,stored_sha=None,stored_bytes=None,decoded_bytes=None,decoded_sha=None):
    path=Path(path).resolve();s=path.stat()
    if path.is_symlink() or (stored_bytes is not None and s.st_size!=stored_bytes):raise ValueError('physical input declaration differs')
    if stored_sha is None:
        if s.st_size>4_000_000:raise ValueError('preparation may hash only small inputs')
        stored_sha=sha(path.read_bytes())
    return {'path':str(path),'stored_bytes':s.st_size,'stored_sha256':stored_sha,
        'decoded_bytes':s.st_size if decoded_bytes is None else decoded_bytes,
        'decoded_sha256':stored_sha if decoded_sha is None else decoded_sha,
        'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns,'inode':s.st_ino,'device':s.st_dev}
def meta(path):
    row=pin(path);return json.loads(Path(row['path']).read_bytes()),row
def artifact(root,row):
    path=Path(row['uri']);path=path if row['external'] else root/path
    return pin(path,stored_sha=row['physical_sha256'],stored_bytes=row['physical_bytes'],
               decoded_bytes=row['decoded_bytes'],decoded_sha=row['decoded_sha256'])

def main():
    template,_=meta(TEMPLATE/'freeze.json');parent,pp=meta(OLD/'result.json');oldfreeze,of=meta(OLD/'freeze.json')
    if parent['counts']['FAILED']!=2 or parent['eligibility_count']!=65:raise ValueError('prior actual denominator/status changed')
    report,rp=meta(oldfreeze['current_report']);current,cp=meta(report['inventory']['path'])
    if report['inventory']['raw_sha256']!=cp['stored_sha256'] or report['inventory']['raw_bytes']!=cp['stored_bytes']:
        raise ValueError('report/inventory receipt mismatch')
    _,coord=meta(report['coordinate_binding']['uri'])
    origin_path=MAIN/'artifacts/experiments/first_stage_full_inventory_restored_20261023/result/manifest.json'
    origin,op=meta(origin_path)
    layers_path=MAIN/'artifacts/experiments/first_stage_source_context_20261022/result/source-layers/index.json'
    layers,lp=meta(layers_path)
    store_path=MAIN/'artifacts/experiments/first_stage_partitioned_operand_routes_20261023/result/code-witnesses/manifest.json'
    store,sp=meta(store_path)
    plan_dir=MAIN/'artifacts/experiments/first_stage_source_frontend_automatic_20261023/plan'
    plan,pm=meta(plan_dir/'manifest.json');gp=artifact(plan_dir,plan['tables']['groups'])
    compressed=Path(gp['path']).read_bytes()
    if sha(compressed)!=gp['stored_sha256']:raise ValueError('old group catalog physical receipt differs')
    with gzip.open(gp['path'],'rb') as stream:decoded=stream.read(1_000_001)
    if len(decoded)!=gp['decoded_bytes'] or sha(decoded)!=gp['decoded_sha256']:raise ValueError('old group catalog decoded receipt differs')
    groups=json.loads(decoded)['rows']
    inputs={r['path']:r for r in (pp,of,rp,cp,coord,op,lp,sp,pm,gp)};qualification=[ref(pp),ref(of)]
    for manifest,path in ((origin,origin_path),(current,Path(report['inventory']['path']))):
        for name in ('header','call_sources','publication'):
            if name in manifest['components']:
                row=artifact(path.parent,manifest['components'][name]);inputs[row['path']]=row
    # The successful original840 constructor needs no composition parent.
    # Only current843.code_source_origin() follows these small inventory manifests.
    parent_ref=current['parent_inventory']
    parent_row=artifact(Path(report['inventory']['path']).parent,parent_ref)
    parent_manifest=json.loads(Path(parent_row['path']).read_bytes());inputs[parent_row['path']]=parent_row
    for name in ('header','publication'):
        row=artifact(Path(parent_row['path']).parent,parent_manifest['components'][name]);inputs[row['path']]=row
    from scar.analysis.inventory_partitions import InventoryPartitions
    current_origin=InventoryPartitions(report['inventory']['path'],max_shard_bytes=64_000_000).code_source_origin()
    baseline_origin=InventoryPartitions(origin_path,max_shard_bytes=64_000_000).code_source_origin()
    if current_origin!=baseline_origin:raise ValueError('actual current843 and original840 compiler origin differs')
    original=[r for r in template['inputs'] if 'first_stage_partitioned_composition_bindings_20261023/composition/index.json.gz' in r['path']]
    if len(original)!=1:raise ValueError('exact original-only composition root pin missing')
    root_pin=original[0];s=Path(root_pin['path']).stat()
    if (s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_ino,s.st_dev)!=(root_pin['size'],root_pin['mtime_ns'],root_pin['ctime_ns'],root_pin['inode'],root_pin['device']):
        raise ValueError('original root retained identity changed')
    inputs[root_pin['path']]=root_pin
    selected=[];files={};context_physical_hash_bytes=0
    for ordinal in (15,61):
        failed,fp=meta(OLD/f'worker/attempt-{ordinal:05d}/result.json');ready,ap=meta(OLD/f'worker/attempt-{ordinal:05d}/ready.json')
        if failed['status']!='FAILED' or failed['error']['detail']!='string source validation: string primitive does not own its ordered input hold suffix':
            raise ValueError('selected previous outcome is not the exact verifier failure')
        work=failed['work_input']
        if ready['work_key']!=failed['work_key'] or ready['work_input']!=work:raise ValueError('prior ready/failed identity mismatch')
        matches=[i for i,row in enumerate(origin['files']) if artifact_path(origin_path.parent,row)==failed['body_locator']['artifact']['uri']]
        if len(matches)!=1:raise ValueError('failed locator has no unique original file membership')
        fi=matches[0];row=artifact(origin_path.parent,origin['files'][fi]);inputs[row['path']]=row
        row=artifact(Path(report['inventory']['path']).parent,current['files'][fi]);inputs[row['path']]=row
        layer=[r for r in layers['files'] if r['snapshot']==work['snapshot'] and r['context']==work['context']]
        if len(layer)!=1:raise ValueError('failed subject source context declaration missing')
        layer=layer[0];archive=pin(layers_path.parent/layer['archive'],stored_bytes=layer['compressed_bytes'],
            decoded_bytes=layer['canonical_bytes'],decoded_sha=layer['canonical_sha256'])
        context_physical_hash_bytes+=archive['stored_bytes'];inputs[archive['path']]=archive
        snapshots=[r for r in store['sources'].values() if r['snapshot']==work['snapshot']]
        if len(snapshots)!=1:raise ValueError('readonly source snapshot missing')
        text_info=snapshots[0]['artifact'];text_path=store_path.parent/text_info['path'];text_row=pin(text_path,
            stored_sha=text_info['sha256'],stored_bytes=text_info['bytes']);inputs[text_row['path']]=text_row
        text=text_path.read_bytes()
        if sha(text)!=text_info['sha256']:raise ValueError('retained source text receipt differs')
        tree=ast.parse(text.decode('utf8'),filename=work['snapshot']['path']);triggers=[]
        for node in ast.walk(tree):
            if (isinstance(node,ast.JoinedStr) and work['source']['start_line']<=node.lineno<=node.end_lineno<=work['source']['end_line']
                    and any(isinstance(v,ast.FormattedValue) and isinstance(v.value,ast.Call) for v in node.values)):
                triggers.append({'path':work['snapshot']['path'],'fingerprint':work['snapshot']['fingerprint'],
                    'start_line':node.lineno,'end_line':node.end_lineno,'start_column':node.col_offset,'end_column':node.end_col_offset})
        if not triggers:raise ValueError('prior body has no call-valued interpolation trigger')
        module=failed['code_witness']['witness']['module_artifact'];mr=pin(store_path.parent/module['path'],stored_sha=module['sha256'],stored_bytes=module['bytes']);inputs[mr['path']]=mr
        counts=[g for g in groups if g['body_key']==failed['body_key'] and g['captured']==work['captured']]
        if not counts:raise ValueError('failed subject missing original current groups')
        item={'original_sequence':failed['sequence'],'original_work_key':failed['work_key'],'body_key':failed['body_key'],
            'body_locator':failed['body_locator'],'file_index':fi,'work_input':work,'old_code_witness':failed['code_witness'],
            'prior_result':ref(fp),'prior_ready':ref(ap),'current_calls':sum(g['current_calls'] for g in counts),
            'original_groups':counts,'trigger_sources':triggers}
        selected.append(item);inputs[fp['path']]=fp;inputs[ap['path']]=ap;qualification.extend((ref(fp),ref(ap)))
        files[str(fi)]={'source_path':work['snapshot']['path'],'snapshot':work['snapshot'],'context':work['context'],
            'context_path':archive['path'],'utf8_path':str(text_path)}
    if any(i['work_input']['code_source_origin']!=baseline_origin for i in selected):raise ValueError('prior two FAILED compiler-origin proof differs')
    selection={'schema':'scar.string-hold-failed-retry-inputs','schema_version':1,'status':'PREPARED_NOT_RUN',
        'selected':selected,'files':files,'current_report':str(Path(rp['path'])),'run':report['run'],
        'compiler_origin_composition':root_pin['path'],'store':str(store_path.parent),'qualification_metadata':qualification,
        'parent_scope':{'result':ref(pp),'original_eligibility_count':parent['eligibility_count'],
            'original_counts':parent['counts'],'original_static_bodies':parent['original_static_bodies'],
            'original_current_groups':parent['original_current_groups'],'original_current_calls':parent['original_current_calls'],
            'original_eligibility_calls':parent['eligibility_calls'],'retry_calls':sum(i['current_calls'] for i in selected),
            'selection_rule':'exact retained FAILED verifier outcomes only; no replanning, no successful-body replay'},
        'one_original_composition_only':True,'previous_actual_failures_preserved':True}
    (BASE/'selection.json').write_bytes(raw(selection))
    current_source=source(ROOT/'scar/analysis/source_string_validation.py');current_source['relative_path']='scar/analysis/source_string_validation.py'
    oldhashes={p['sha256'] for item in selected for p in item['work_input']['producer'] if p['path'].endswith('/source_string_validation.py')}
    if oldhashes!={'917e69c4e2907b4118eae66ed66da291b7b65396384377c64298a5f6be790a65'}:raise ValueError('prior verifier version differs')
    current_source['previous_sha256']=next(iter(oldhashes));(BASE/'changed-source.json').write_bytes(raw(current_source))
    olddiff=(TEMPLATE/'changes.diff').read_text();section=olddiff.split('+++ candidate/scar/analysis/source_string_validation.py\n',1)[1].split('\n--- ',1)[0]
    baseline=''.join(line[1:] for line in section.splitlines(True) if line.startswith('+') and not line.startswith('+++'))+'\n'
    if sha(baseline.encode())!=next(iter(oldhashes)):raise ValueError('retained exact verifier baseline reconstruction differs')
    patch=''.join(difflib.unified_diff(baseline.splitlines(True),(ROOT/current_source['relative_path']).read_text().splitlines(True),fromfile='old/'+current_source['relative_path'],tofile='new/'+current_source['relative_path']))
    (BASE/'PATCH.diff').write_text(patch)
    api=runpy.run_path(str(BASE/'run_gate.py'),run_name='prepare_imports');runtime=api['preload_readers']()
    runtime_rows=[source(p) for p in sorted(set(runtime.values())) if Path(p).is_file()]
    fixed=[source(p) for p in (BASE/'prepare_gate.py',BASE/'run_gate.py',BASE/'gate_guards.py',BASE/'selection.json',BASE/'changed-source.json',BASE/'PATCH.diff',Path(sys.executable).resolve(),Path('/usr/bin/time'))]
    fixed=list({r['path']:r for r in fixed+runtime_rows}.values());candidates=[source(p) for p in sorted((ROOT/'scar').rglob('*.py'))]
    if "if attempt!=BASE/'attempt01':" not in (BASE/'run_gate.py').read_text() or 'attempt04' in (BASE/'run_gate.py').read_text():raise ValueError('runner fixed attempt path mismatch')
    freeze={**template,'candidate':'string_hold_failed_retry_candidate02','status':'FROZEN_NOT_RUN','production_sources':[current_source],
        'candidate_scar_sources':candidates,'small_frozen_files':fixed,'runtime_modules':runtime_rows,'inputs':sorted(inputs.values(),key=lambda r:r['path']),
        'allowed_composition_roots':[root_pin['path']],'attempt':str(BASE/'attempt01'),'active_subjects':2,'actual_source_files':2,
        'internal_check_inputs':[{'path':str(BASE/'freeze.json'),'role':'ROOT_APPROVED_FREEZE_SHA256','max_bytes':1000000}],
        'limits':{**template['limits'],'bodies':2,'source_files':2,'total_operations':8000},
        'reuse_policy':'read exact failed/ready metadata; one real original composition and two contexts; no batch planner or successful graphs',
        'parent_scope':selection['parent_scope']}
    (BASE/'freeze.json').write_bytes(raw(freeze))
    receipt={'status':'FROZEN_NOT_RUN','freeze_sha256':sha((BASE/'freeze.json').read_bytes()),'production_sources':[current_source],
        'exact_failed_sequences':[i['original_sequence'] for i in selected],'retry_calls':[i['current_calls'] for i in selected],
        'original_composition_roots':1,'source_contexts':2,'prior_65_replanned':False,'successful_graphs_read':0,
        'context_compressed_bytes_hashed_in_prepare':context_physical_hash_bytes,'composition_stream_reads_in_prepare':0,
        'body_lowerings':0,'code_payloads_loaded':0,'input_stat_pins':len(inputs),'source_files_frozen':len(candidates),
        'runtime_files':len(runtime_rows),'tool_guard_bytes':sum(r['bytes'] for r in fixed+candidates),'limits':freeze['limits'],
        'original840_root_unchanged':root_pin['path'],'current843_origin_equals_original840_and_both_failed':True,
        'only_small_inventory_ancestry_added':ref(parent_row)}
    (BASE/'PREPARATION_RECEIPT.json').write_bytes(raw(receipt));print(json.dumps(receipt,sort_keys=True))

def artifact_path(root,row):return str(Path(row['uri']) if row['external'] else root/row['uri'])

if __name__=='__main__':main()
