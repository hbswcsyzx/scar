"""ONE retained raw projection gate; offline with possible parallel server load."""
from collections import Counter
import hashlib
import gzip
import json
from pathlib import Path
import resource
import subprocess
import sys
import time


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
EXP=ROOT/'artifacts/experiments'


def digest(path):
    raw=path.read_bytes()
    return {'path':str(path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def canonical(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()


def write(name,value):
    with (HERE/name).open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True,ensure_ascii=False);stream.write('\n')


def progress(value):
    print(json.dumps(value,sort_keys=True),flush=True)


def write_proofs(name, values):
    raw_bytes=0
    with (HERE/name).open('xb') as output:
        with gzip.GzipFile(fileobj=output,mode='wb',filename='',mtime=0,compresslevel=1) as stream:
            for ordinal,value in enumerate(values):
                raw=canonical({'ordinal':ordinal,'proof':value})
                raw_bytes+=len(raw)
                assert len(raw)<=32768 and raw_bytes<=128000000
                stream.write(raw)
    return {'receipt':digest(HERE/name),'records':len(values),'decoded_bytes':raw_bytes}


def imported_sources():
    return [{'module':name,**digest(Path(module.__file__).resolve())} for name,module in sorted(sys.modules.items())
        if name.startswith('scar') and getattr(module,'__file__',None) and module.__file__.endswith('.py')]


def main():
    started=time.monotonic()
    freeze=json.loads((HERE.parent/'static-freeze.json').read_text())
    frozen=[row for row in freeze['files'] if row['path'].endswith('.py')]
    for row in frozen:assert digest(ROOT/row['path'])['sha256']==row['sha256'],row['path']
    capture=EXP/'first_stage_lewm_physical_20261023'
    old=EXP/'first_stage_os_interface_work_20261023'
    projection=EXP/'first_stage_fd_table_projection_20261023'
    selected_gate=EXP/'first_stage_os_source_lookup_20261023/gate-attempt01'
    r2_manifest=EXP/'first_stage_os_resource_refinement_20261023/gate-attempt01/result/manifest.json'
    input_paths={'base':old/'result/interfaces/manifest.json','archive':capture/'archive-index.json',
        'coordinates':old/'result/capture-coordinates.json','selected':selected_gate/'result/manifest.json',
        'context_evidence':selected_gate/'automatic-witness/context-evidence.json',
        'projection_files':projection/'file-receipts.json','context_events':projection/'context-events.json',
        'r1_summary':old/'result/summary.json','r1_audit':old/'audit-attempt03-summary.json',
        'projection_summary':projection/'summary.json','r2':r2_manifest}
    producer={'schema':'scar.os-fd-source-projection-gate-producer','schema_version':1,
        'revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'script':digest(Path(__file__)),'source_freeze':digest(HERE.parent/'static-freeze.json'),
        'frozen_sources':frozen,'inputs':{name:digest(path) for name,path in input_paths.items()},
        'scope':'ONE offline provider projection and existing-handle refinement; parallel load possible, not benchmark',
        'target_runs':0,'compile_runs':0,'new_work_records':0}
    write('producer.json',producer)
    with (HERE/'frozen-implementation.py').open('xb') as stream:stream.write((ROOT/'scar/trace/os_fd_source_projection.py').read_bytes())
    from scar.ir.execution.resources import HandleBinding,ProviderHandle,InstanceTarget
    from scar.ir.execution.common import Unresolved
    from scar.ir.record_codec import decode,encode
    from scar.trace.os_resource_refinement import OSResourceBase
    from scar.trace.os_fd_table_contexts import FDTableContextInputs,OSFDTableContexts
    from scar.trace.os_fd_source_projection import FDSourceInputs,OSFDSourceProjection,build_os_fd_source_projection
    imports=imported_sources();write('actual-imports-before.json',imports)
    base=OSResourceBase(input_paths['base'],cached_chunks=2)
    contexts=FDTableContextInputs(capture,input_paths['archive'],input_paths['coordinates'],input_paths['r1_summary'],
        input_paths['r1_audit'],input_paths['projection_summary'],input_paths['projection_files'],input_paths['context_events'],input_paths['context_evidence'])
    progress({'phase':'EXISTING_SELECTED_PUBLIC_READ_BEGIN'})
    selected=OSFDTableContexts.read(base,r2_manifest,contexts,input_paths['selected'])
    frozen_accesses=canonical(selected.r2.document['provider_accesses'])
    inputs=FDSourceInputs(capture,input_paths['selected'],input_paths['archive'],input_paths['coordinates'],
        input_paths['projection_files'],input_paths['context_events'],input_paths['context_evidence'])
    progress({'phase':'NEW_RAW_PROJECTION_BEGIN'})
    result=build_os_fd_source_projection(base,selected,inputs,HERE/'result',progress=progress)
    progress({'phase':'PROJECTION_PUBLISHED','receipt':result['manifest_receipt']})
    view=OSFDSourceProjection.read(base,selected,inputs,HERE/'result/manifest.json')
    counts=view.manifest['counts']
    assert counts['base_handles']==base.manifest['tables']['handles']['records']
    assert counts['requested_legacy_handles']==counts['base_handles']-len(selected.handles)
    assert counts['unrefined_legacy_handles']==counts['frontier_records']==0
    assert counts['requested_legacy_handles']==counts['projected_fd_ports']
    ports={};contracts=Counter();chunk_samples={};port_receipts=[]
    for envelope in view.iter_records('fd_ports'):
        ordinal,row=envelope['ordinal'],envelope['record']
        selector=view.selector('fd_ports',ordinal,'/record/fd')
        whole=decode(type(selector),envelope['selector'])
        assert whole.chunk==selector.chunk and whole.ordinal==selector.ordinal and whole.line==selector.line
        assert type(row['fd']) is int and row['fd']>=0 and row['run']==encode(base.run.id)
        assert row['new_ir_resource_created'] is False and row['original_target_preserved'] is True
        assert ordinal not in ports
        ports[ordinal]={'fd':row['fd'],'reference':row['handle_reference'],'target':row['target'],'selector':encode(selector)}
        contracts[row['extraction_contract']]+=1
        chunk_samples.setdefault(selector.chunk.locator,(selector,row['fd']))
        port_receipts.append({'ordinal':ordinal,'selector':encode(selector),'fd':row['fd'],
            'original_handle':row['handle_reference'],'raw_source':row['raw_source'],
            'provider_row_sha256':envelope['row_sha256'],'verification':'ALL_ROWS_PUBLIC_CHUNK_ITERATOR_AND_EXACT_FD_SELECTOR'})
    assert len(ports)==counts['projected_fd_ports']
    # Every selector was qualified in the public per-chunk stream above; exercise
    # actual point dispatch once per chunk, not an O(n^2) per-row readline loop.
    for selector,fd in chunk_samples.values():assert view.combined_resolve(selector)['value']==fd
    birth_facts=list(view.iter_records('birth_facts'));frontiers=list(view.iter_records('frontiers'))
    assert len(birth_facts)==counts['missing_birth_requests']==counts['projected_birth_facts']
    assert not frontiers
    for envelope in birth_facts:
        row=envelope['record'];assert row['run']==encode(base.run.id) and type(row['flags']) is str
        assert row['child_thread']['source']==row['source']
    progress({'phase':'PUBLIC_PROVIDER_ALL_ROWS_PASS','fd_ports':len(ports),'birth_facts':len(birth_facts),'chunks':len(chunk_samples)})
    field_counts=Counter();original_targets=set();new_targets=set();lifetimes=set();field_proofs=[];observed_none=0
    originals=base.reader.iter_records('handles')
    for original,new in zip(originals,view.iter_handle_records(),strict=True):
        ordinal,oldwire=original['ordinal'],original['record'];wire=new['record']
        assert ordinal==new['ordinal'] and oldwire['id']==wire['id']
        assert {k:v for k,v in oldwire.items() if k!='handle'}=={k:v for k,v in wire.items() if k!='handle'}
        typed=decode(HandleBinding,wire);assert type(typed.handle) is ProviderHandle
        assert encode(typed)==wire
        identity=typed.id
        original_targets.add(oldwire['target']['instance']['wire']);new_targets.add(wire['target']['instance']['wire'])
        assert typed.handle.lifetime not in lifetimes;lifetimes.add(typed.handle.lifetime)
        observed_none+=typed.start.process is None
        if identity in selected.handles:
            assert wire==encode(selected.handles[identity]) and type(typed.handle.container) is InstanceTarget
            field_counts['retained_existing_provider']+=1
        else:
            assert type(typed.handle.container) is Unresolved
            info=ports[view.index[ordinal]]
            assert wire['handle']['selector']==info['selector'] and wire['target']==info['target']
            assert info['reference']['canonical_record_sha256']==hashlib.sha256(canonical(oldwire)).hexdigest()
            assert info['reference']['selector']==encode(base.selector('handles',ordinal))
            field_counts['fd_value_refined_container_unresolved']+=1
        field_proofs.append({'ordinal':ordinal,'id':wire['id'],
            'original_canonical_record_sha256':hashlib.sha256(canonical(oldwire)).hexdigest(),
            'refined_canonical_record_sha256':hashlib.sha256(canonical(wire)).hexdigest(),
            'nonendpoint_fields_equal':True,'selection':new['selection']})
        if len(field_proofs)%2000==0:progress({'phase':'ALL_HANDLE_CORE_CODEC_AND_FIELDS','handles':len(field_proofs)})
    assert len(field_proofs)==counts['base_handles'] and original_targets==new_targets
    assert len(new_targets)==base.manifest['tables']['resources']['records']
    assert field_counts['retained_existing_provider']==len(selected.handles)
    assert field_counts['fd_value_refined_container_unresolved']==counts['projected_fd_ports']
    assert counts['projected_fd_ports']-contracts['OPEN_RETURN']==contracts['DUP_RETURN_EXISTING_TARGET']
    assert view.manifest['validation']['new_resources_or_work']==0
    works=[]
    for entry in selected.r2.document['base_references']['submissions']:
        ordinal=entry['selector']['ordinal'];old=selected.record('submissions',ordinal);actual=view.record('submissions',ordinal)
        assert actual==old;works.append({'ordinal':ordinal,'record_sha256':hashlib.sha256(canonical(actual['record'])).hexdigest()})
    assert canonical(selected.r2.document['provider_accesses'])==frozen_accesses
    assert len(selected.r2.accesses)==len(selected.r2.document['provider_accesses'])
    # A small actual query per stream endpoint proves the public sparse route.
    for ordinal in (min(view.index),max(view.index)):
        one=view.record('handles',ordinal);assert one['record']['handle']['selector']==ports[view.index[ordinal]]['selector']
    for row in frozen:assert digest(ROOT/row['path'])['sha256']==row['sha256']
    after=imported_sources();write('actual-imports-after.json',after)
    by_name={row['module']:row for row in after};drift=[row for row in imports if row!=by_name[row['module']]]
    for name,receipt in producer['inputs'].items():assert digest(Path(receipt['path']))==receipt,name
    proof_storage={'ports':write_proofs('all-port-selector-proofs.jsonl.gz',port_receipts),
        'handles':write_proofs('all-handle-field-proofs.jsonl.gz',field_proofs)}
    write('birth-facts.json',birth_facts);write('frontiers.json',{'provider':frontiers,'actor':view.manifest['actor_frontiers']})
    write('work-receipts.json',works)
    report={'schema':'scar.os-fd-source-projection-gate-report','schema_version':1,'status':'PASS_EXISTING_HANDLE_FD_SOURCE_SCOPE',
        'counts':counts,'all_handles_typed_codec':len(field_proofs),'all_selectors_batch_exact_checked':len(ports),
        'point_resolver_samples_per_chunk':len(chunk_samples),'extraction_contracts':dict(contracts),
        'field_results':dict(field_counts),'creator_or_unknown_process_none_preserved':observed_none,
        'unique_original_targets':len(original_targets),'unique_refined_targets':len(new_targets),
        'selected_work_records_unchanged':len(works),'provider_accesses_unchanged':len(selected.r2.accesses),
        'manifest':result['manifest_receipt'],'raw_input_scope':view.manifest['raw_files'],
        'proof_storage':proof_storage,
        'source_file_drift_after_import':drift,'actual_scar_imports':len(after),'critical_sources_sha':'PASS',
        'producer_selected_extraction':'ALL_PROJECTED_ROWS_CHECKED_DURING_SINGLE_RAW_PASS',
        'reader_validation':'ALL_PROVIDER_CHUNKS_AND_ROWS + ALL_HANDLE_PUBLIC_CODEC_AND_PREIMAGE/FIELDS; NO_RAW_REEXTRACTION',
        'cost_scope':'offline validation with parallel server load; not LeWM benchmark or speedup',
        'full_execution_model_semantics':'OPEN','first_stage_complete':False,'transformation_authorized':False,
        'elapsed_seconds':time.monotonic()-started,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    write('summary.json',report);progress({'phase':'GATE_COMPLETE','status':report['status'],'counts':counts})


if __name__=='__main__':main()
