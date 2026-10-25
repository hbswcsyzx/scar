"""Metadata/AST preparation only. Never load contexts, marshal or composition JSON."""
import ast
import gzip
import hashlib
import io
import json
from pathlib import Path
import struct
import sys

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[3]
MAIN = Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
EX = MAIN / 'artifacts/experiments'
INPUTS = {}
LIMIT = 64_000_000

def sha(data): return hashlib.sha256(data).hexdigest()
def raw(value): return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def read(path, *, limit=LIMIT, decoded_bytes=None, decoded_sha256=None, read_json=False):
    path=Path(path).resolve()
    if path.is_symlink() or not path.is_file() or path.stat().st_size>limit: raise ValueError('input path/size: '+str(path))
    data=path.read_bytes();s=path.stat()
    row={'path':str(path),'stored_bytes':len(data),'stored_sha256':sha(data),'size':s.st_size,
         'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns,'inode':s.st_ino,'device':s.st_dev,
         'decoded_bytes':decoded_bytes,'decoded_sha256':decoded_sha256}
    if path.suffix=='.gz':
        row['gzip_isize_unverified']=struct.unpack('<I',data[-4:])[0]
        if decoded_bytes is not None and row['gzip_isize_unverified']!=decoded_bytes: raise ValueError('gzip declaration/ISIZE mismatch')
    INPUTS[str(path)]=row
    if not read_json:return data
    if path.suffix=='.gz':
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:decoded=stream.read(limit+1)
    else:decoded=data
    if len(decoded)>limit:raise ValueError('small metadata decoded size')
    if decoded_bytes is not None and len(decoded)!=decoded_bytes:raise ValueError('decoded bytes')
    if decoded_sha256 is not None and sha(decoded)!=decoded_sha256:raise ValueError('decoded hash')
    row['decoded_bytes']=len(decoded);row['decoded_sha256']=sha(decoded)
    return json.loads(decoded)
def reference(root,ref, *, decode=True):
    path=Path(ref['uri']) if ref['external'] else Path(root)/ref['uri']
    data=read(path,decoded_bytes=ref['decoded_bytes'],decoded_sha256=ref['decoded_sha256'],read_json=decode)
    row=INPUTS[str(path.resolve())]
    if row['stored_bytes']!=ref['physical_bytes'] or row['stored_sha256']!=ref['physical_sha256']:raise ValueError('original ref receipt differs')
    return data,path.resolve()
def component(root,manifest,name):
    doc,path=reference(root,manifest['components'][name]);return doc['value'],path

def main():
    implementation=BASE/'implementation-candidate02.json'
    impl=json.loads(implementation.read_bytes())
    for row in impl['changed_sources']:
        data=Path(row['path']).read_bytes()
        if len(data)!=row['bytes'] or sha(data)!=row['sha256']:raise ValueError('frozen production source changed')
    diagnosis=EX/'first_stage_source_frontend_automatic_20261023/exact-ast-frontiers.json'
    diag=read(diagnosis,read_json=True)
    report_path=EX/'first_stage_source_revision_current_20261025/result/connections/source/report.json'
    report=read(report_path,read_json=True)
    if report.get('schema')!='scar.source-invocations' or report.get('schema_version')!=3:raise ValueError('current report schema')
    inv_path=Path(report['inventory']['path']);inv=read(inv_path,read_json=True)
    row=INPUTS[str(inv_path.resolve())]
    if report['inventory']!={'path':str(inv_path.resolve()),'raw_sha256':row['stored_sha256'],'raw_bytes':row['stored_bytes'],'decoded_bytes':row['decoded_bytes']}:raise ValueError('current report/inventory snapshot mismatch')
    cb=report['coordinate_binding'];coords=read(cb['uri'],read_json=True);cr=INPUTS[str(Path(cb['uri']).resolve())]
    if (cr['stored_bytes'],cr['stored_sha256'])!=(cb['size_bytes'],cb['sha256']) or coords['run']!=report['run']:raise ValueError('coordinates/current Run mismatch')
    current_pub,_=component(inv_path.parent,inv,'publication')
    comp_ref=current_pub['base_composition'];comp=Path(comp_ref['path'])
    if comp!=EX/'first_stage_source_publication_current_20261023/result/composition/index.json.gz':raise ValueError('unexpected original compiler composition root')
    read(comp,decoded_bytes=comp_ref['decoded_bytes'],decoded_sha256=current_pub['base_composition_canonical_sha256'])
    if (INPUTS[str(comp)]['stored_bytes'],INPUTS[str(comp)]['stored_sha256'])!=(comp_ref['raw_bytes'],comp_ref['raw_sha256']):raise ValueError('composition frozen receipt')
    # CompositionIndex3 checks this exact existing publication parent at EOF.
    old_manifest,old_path=reference(inv_path.parent,inv['parent_inventory'])
    old_pub,_=component(old_path.parent,old_manifest,'publication')
    if old_pub['code_source_origin']!=current_pub['code_source_origin']:raise ValueError('compiler origin membership changed')
    parent=old_pub['base_composition'];parent_path=Path(parent['path'])
    read(parent_path,decoded_bytes=parent['decoded_bytes'],decoded_sha256=old_pub['base_composition_canonical_sha256'])
    if (INPUTS[str(parent_path)]['stored_bytes'],INPUTS[str(parent_path)]['stored_sha256'])!=(parent['raw_bytes'],parent['raw_sha256']):raise ValueError('parent composition receipt')
    origin=current_pub['code_source_origin'];origin_path=Path(origin['inventory']['path']);origin_doc=read(origin_path,read_json=True)
    orow=INPUTS[str(origin_path)]
    if (orow['stored_sha256'],orow['stored_bytes'],orow['decoded_bytes'])!=(origin['inventory']['raw_sha256'],origin['inventory']['raw_bytes'],origin['inventory']['decoded_bytes']):raise ValueError('original compiler inventory receipt')
    # Same immutable call_sources is retained through publication membership.
    call_sources,_=component(origin_path.parent,origin_doc,'call_sources')
    for manifest,manifest_path in ((inv,inv_path),(old_manifest,old_path)):
        ref=manifest['components']['call_sources'];path=Path(ref['uri']) if ref['external'] else manifest_path.parent/ref['uri']
        if str(path.resolve())!=origin['call_sources']['artifact']['uri'] or {k:ref[k] for k in ('physical_bytes','physical_sha256','decoded_bytes','decoded_sha256','representation')}!={k:origin['call_sources']['artifact'][k] for k in ('physical_bytes','physical_sha256','decoded_bytes','decoded_sha256','representation')}:raise ValueError('call source origin locator differs')
    layers=EX/'first_stage_source_context_20261022/result/source-layers';layer_index=read(layers/'index.json',read_json=True)
    store=EX/'first_stage_partitioned_operand_routes_20261023/result/code-witnesses';store_doc=read(store/'manifest.json',read_json=True)
    if store_doc['runtime']['version'][:3]!=[3,14,7]:raise ValueError('original compiler runtime differs')
    selected,files,texts=[],{},{}
    for ordinal,item in enumerate(diag['rows']):
        if not any(shape['ast_kind']=='Call' for shape in item['exact_ast_shapes']):continue
        sr=item['archived_source_receipt'];text_raw=read(sr['path'])
        if len(text_raw)!=sr['bytes'] or sha(text_raw)!=sr['sha256']:raise ValueError('archived exact UTF8 differs')
        text=text_raw.decode('utf8');tree=ast.parse(text,filename=item['definition_source']['path'])
        q=item['last_frontier']['source'];span=(q['start_line'],q['end_line'],q['start_column'],q['end_column'])
        matches=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and (n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)==span]
        if len(matches)!=1:raise ValueError('original Call source span not unique')
        node=matches[0]
        if not any(k.arg is None for k in node.keywords) or any(isinstance(a,ast.Starred) for a in node.args):continue
        original=item['body_locator']['artifact']
        candidates=[(i,ref) for i,ref in enumerate(inv['files']) if ref['external'] and all(ref[k]==original[k] for k in ('uri','physical_bytes','physical_sha256','decoded_bytes','decoded_sha256','representation'))]
        if len(candidates)!=1:raise ValueError('current inventory has no unique unchanged source file member')
        fi,ref=candidates[0]
        if fi not in files:
            file_doc,file_path=reference(inv_path.parent,ref);file=file_doc['file'];files[fi]=file
            context=[r for r in layer_index['files'] if r['status']=='STORED' and r['snapshot']==file['snapshot'] and r['context']==file['context']]
            if len(context)!=1:raise ValueError('exact original source context is not unique')
            ctx=context[0];ctx_path=layers/ctx['archive']
            read(ctx_path,decoded_bytes=ctx['canonical_bytes'],decoded_sha256=ctx['canonical_sha256'])
            if INPUTS[str(ctx_path)]['stored_bytes']!=ctx['compressed_bytes']:raise ValueError('context stored bytes')
            texts[fi]={'snapshot':file['snapshot'],'context':file['context'],'context_path':str(ctx_path),'file_ref':ref,
                       'utf8_path':sr['path'],'source_path':file['snapshot']['path']}
        file=files[fi]
        definitions=[d for d in file['definitions'] if d['source']==item['definition_source']]
        if len(definitions)!=1:raise ValueError('selected definition source is not unique in current file')
        definition=definitions[0]
        bodies=[(bi,b) for bi,b in enumerate(file['bodies']) if b['definition']==definition['id']]
        if len(bodies)!=1 or bodies[0][1]['status']!='UNSUPPORTED':raise ValueError('selected current body is not a necessary failed item')
        links=[(li,l) for li,l in enumerate(call_sources['model']['code_links']) if l['status']=='VERIFIED' and l['definition']==definition['id'] and l['source']==definition['source'] and l['snapshot']==file['snapshot']]
        if len(links)!=1:raise ValueError('exact captured code/source link is not unique')
        li,link=links[0];captures=[c['code'] for c in call_sources['model']['codes'] if c['code']['key']==link['code']]
        if not captures or any(c!=captures[0] for c in captures):raise ValueError('complete captured descriptor differs')
        modules=[r for r in store_doc['modules'].values() if r['snapshot']==file['snapshot'] and r['compile_key']['optimize'] in link['optimize_levels']]
        if len(modules)!=1:raise ValueError('bounded readonly module selection not unique')
        module=modules[0];module_path=store/module['artifact']['path'];mb=read(module_path)
        if len(mb)!=module['artifact']['bytes'] or sha(mb)!=module['artifact']['sha256']:raise ValueError('owned marshal receipt differs')
        sources=[r for r in store_doc['sources'].values() if r['snapshot']==file['snapshot']]
        if len(sources)!=1 or str(store/sources[0]['artifact']['path'])!=sr['path']:raise ValueError('owned UTF8 namespace differs')
        selected.append({'diagnosis_pointer':'#/rows/'+str(ordinal),'original_sequence':item['sequence'],'original_body_key':item['body_key'],'original_calls':item['current_calls'],'file_index':fi,'body_index':bodies[0][0], 'definition':definition,'snapshot':file['snapshot'],'context':file['context'],'frontier':item['last_frontier'],'captured':captures[0], 'code_link_index':li,'code_source_link':link,'current_body_locator':{'artifact':ref,'pointer':'#/file/bodies/'+str(bodies[0][0])},'ast_keyword_order':['DOUBLE_STARRED' if k.arg is None else 'NAMED' for k in node.keywords],'ast_positional_count':len(node.args)})
    if len(selected)!=4 or len(files)!=2 or sum(r['original_calls'] for r in selected)!=5:raise ValueError('original AST predicate denominator changed')
    if any(r['decoded_bytes'] is not None and r['decoded_bytes']>(96_000_000 if r['path'] in (str(comp),str(parent_path)) else LIMIT) for r in INPUTS.values()):raise ValueError('independent input root/context cap')
    selection={'schema':'scar.kwargs-body-gate-selection','schema_version':1,'status':'PREPARED_NO_BODY_LOWERING','predicate':'exact original Call; at least one keyword.arg=None; no Starred positional; unique unchanged current source/body/context membership','current_report':str(report_path),'current_inventory':str(inv_path),'run':report['run'],'compiler_origin_composition':str(comp),'source_layers':str(layers),'store':str(store),'files':texts,'selected':selected,'code_payloads_loaded':0,'source_context_payloads_loaded':0,'composition_decoded':False}
    with (BASE/'selection.json').open('xb') as f:f.write(raw(selection))
    sources=[]
    for path in sorted((ROOT/'scar').rglob('*.py')):
        b=path.read_bytes();sources.append({'path':str(path),'bytes':len(b),'sha256':sha(b)})
    fixed=[]
    for path in (BASE/'prepare_gate.py',BASE/'run_gate.py',BASE/'gate_guards.py',BASE/'selection.json',implementation,Path(sys.executable).resolve(),Path('/usr/bin/time')):
        b=path.read_bytes();fixed.append({'path':str(path),'bytes':len(b),'sha256':sha(b)})
    freeze={'schema':'scar.kwargs-body-gate-freeze','schema_version':1,'status':'FROZEN_NOT_EXECUTED','production_sources':impl['changed_sources'],'candidate_scar_sources':sources,'small_frozen_files':fixed,'inputs':sorted(INPUTS.values(),key=lambda r:r['path']), 'limits':{'bodies':4,'source_files':2,'operations_per_body':4000,'total_operations':16000,'body_seconds':180,'worker_seconds':600,'outer_seconds':660,'heartbeat_seconds':20,'total_input_bytes':256_000_000,'total_output_bytes':256_000_000,'record_context_bytes':64_000_000,'composition_root_bytes':96_000_000},'actual_input_accounting':'every retained artifact physical read plus every retained gzip decoded read, including repeated reads; source/runner guard hashing separately reported','input_sha_review':'preparation freezes physical SHA/stat; context/composition decoded declarations remain unreviewed until worker EOF','attempt':str(BASE/'attempt02'),'allowed_composition_roots':[str(comp),str(parent_path)],'target_namespace_roots':sorted({r['context']['namespace_root'] for r in selected}),'parent_archive_commit_from_root':'e5e1013b','candidate':'candidate02','body_time_scope':'180s includes evidence/context/lower/independent checks','call_selection':'exact original OPAQUE + ast_type Call + Call atom/output and separate Opcode.CALL','capabilities':['PYTHON_FIXED_LOCAL_UNPACK_V1','PYTHON_SLICE_KEYS_314_V1','PYTHON_LEXICAL_LOCALS_314_V1','PYTHON_CALL_KWARGS_314_V1']}
    with (BASE/'freeze.json').open('xb') as f:f.write(raw(freeze))
    print(json.dumps({'status':'FROZEN_NOT_RUN','selection':str(BASE/'selection.json'),'freeze':str(BASE/'freeze.json'),'freeze_sha256':sha((BASE/'freeze.json').read_bytes()),'selected':len(selected),'source_files':len(files),'inputs':len(INPUTS),'candidate_sources':len(sources)},sort_keys=True))

if __name__=='__main__':main()
