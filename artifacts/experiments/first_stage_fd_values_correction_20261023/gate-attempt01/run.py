"""ONE offline FD-only requalification; old chunks retained, raw never reopened."""
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
EXP=ROOT/'artifacts/experiments'


def digest(path):
    raw=Path(path).read_bytes()
    return {'path':str(Path(path).absolute()),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def canonical(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()


def write(name,value):
    with (HERE/name).open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True);stream.write('\n')


def progress(value):print(json.dumps(value,sort_keys=True),flush=True)


def imports():
    return [{'module':name,**digest(module.__file__)} for name,module in sorted(sys.modules.items())
        if name.startswith('scar') and getattr(module,'__file__',None) and module.__file__.endswith('.py')]


def main():
    started=time.monotonic()
    freeze=json.loads((HERE.parent/'static-freeze.json').read_bytes())
    for row in freeze['files']:assert digest(ROOT/row['relative'])['sha256']==row['sha256'],row['relative']
    r1=EXP/'first_stage_os_interface_work_20261023'
    capture=EXP/'first_stage_lewm_physical_20261023'
    oldgate=EXP/'first_stage_os_fd_source_projection_20261023/gate-attempt01'
    selected=EXP/'first_stage_os_source_lookup_20261023/gate-attempt01'
    projection=EXP/'first_stage_fd_table_projection_20261023'
    paths={'base':r1/'result/interfaces/manifest.json',
        'r2':EXP/'first_stage_os_resource_refinement_20261023/gate-attempt01/result/manifest.json',
        'original_projection':oldgate/'result/manifest.json','original_selected_manifest':selected/'result/manifest.json',
        'archive':capture/'archive-index.json','coordinates':r1/'result/capture-coordinates.json',
        'r1_summary':r1/'result/summary.json','r1_audit':r1/'audit-attempt03-summary.json',
        'projection_summary':projection/'summary.json','projection_files':projection/'file-receipts.json',
        'projection_events':projection/'context-events.json',
        'context_evidence':selected/'automatic-witness/context-evidence.json',
        'probe_summary':EXP/'first_stage_strace_filter_probe_20261023/summary.json',
        'filter_review':EXP/'first_stage_fd_interval_review_20261023/capture-coverage-correction.json'}
    producer={'schema':'scar.fd-values-correction-gate-producer','schema_version':1,
        'revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'script':digest(__file__),'static_freeze':digest(HERE.parent/'static-freeze.json'),
        'inputs':{key:digest(value) for key,value in paths.items()},
        'scope':'ONE old-chunk/R2 requalification; no target, raw scan, Work replay or full-model claim'}
    write('producer.json',producer)
    original_raw=json.loads(paths['archive'].read_bytes())
    forbidden={str(Path(row[key]).absolute()) for row in original_raw['files'] for key in ('actual_path','logical_path')}
    raw_open_attempts=[]
    def prohibit_raw_open(event,args):
        if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
            name=str(Path(os.fsdecode(args[0])).absolute())
            if name in forbidden:
                raw_open_attempts.append(name)
                raise AssertionError('correction must not reopen original capture data: '+name)
    sys.addaudithook(prohibit_raw_open)
    from scar.ir.execution.common import Unresolved
    from scar.ir.execution.resources import HandleBinding,ProviderHandle
    from scar.ir.record_codec import decode,encode
    from scar.trace.os_resource_refinement import OSResourceBase,OSResourceRefinement
    from scar.trace.os_fd_table_contexts import FDTableContextInputs,OSFDTableContexts,build_os_fd_table_contexts
    from scar.trace.os_fd_source_projection import FDValuesInputs,OSFDValuesProjection,requalify_os_fd_values
    before=imports();write('actual-imports-before.json',before)
    base=OSResourceBase(paths['base'],cached_chunks=2)
    r2=OSResourceRefinement.read(base,paths['r2'])
    original_accesses=canonical(r2.document['provider_accesses'])
    context_inputs=FDTableContextInputs(capture,paths['archive'],paths['coordinates'],paths['r1_summary'],
        paths['r1_audit'],paths['projection_summary'],paths['projection_files'],paths['projection_events'],paths['context_evidence'])
    # No unsafe loader is used as input. Both public paths must reject before
    # any non-main raw replay or publication. Historical schema1 is unchanged.
    rejects=[]
    for operation,call in (
        ('legacy_context_read',lambda:OSFDTableContexts.read(base,paths['r2'],context_inputs,paths['original_selected_manifest'])),
        ('uncovered_context_build',lambda:build_os_fd_table_contexts(base,paths['r2'],context_inputs,HERE/'rejected-context'))):
        try:call()
        except ValueError as error:rejects.append({'operation':operation,'error_type':type(error).__name__,'message':str(error)})
        else:raise AssertionError('unqualified context must not be admitted')
    assert not (HERE/'rejected-context').exists()
    write('fail-closed-receipts.json',rejects)
    inputs=FDValuesInputs(paths['r2'],paths['original_projection'],paths['original_selected_manifest'],paths['archive'],paths['coordinates'])
    progress({'phase':'FD_VALUES_REQUALIFICATION_BEGIN','r2_provider_handles':len(r2.handles)})
    result=requalify_os_fd_values(base,r2,inputs,HERE/'result',progress=progress)
    progress({'phase':'EXPLICIT_SCHEMA2_PUBLISHED','receipt':result['manifest_receipt']})
    view=OSFDValuesProjection.read(base,r2,inputs,HERE/'result/manifest.json')
    counts=view.manifest['counts'];contracts=Counter();ports={};samples={};port_count=0
    with gzip.GzipFile(filename=str(HERE/'all-port-selector-proofs.jsonl.gz'),mode='xb',mtime=0,compresslevel=1) as proofs:
        for envelope in view.iter_records('fd_ports'):
            ordinal,row=envelope['ordinal'],envelope['record'];selector=view.selector('fd_ports',ordinal,'/record/fd')
            assert row['run']==encode(base.run.id) and type(row['fd']) is int and row['fd']>=0
            assert row['effects_coverage']=='UNKNOWN' and row['new_ir_resource_created'] is False
            ports[ordinal]={'fd':row['fd'],'reference':row['handle_reference'],'selector':encode(selector),'target':row['target']}
            contracts[row['extraction_contract']]+=1;port_count+=1
            samples.setdefault(selector.chunk.locator,(selector,row['fd']))
            proofs.write(canonical({'ordinal':ordinal,'selector':encode(selector),'fd':row['fd'],
                'row_sha256':envelope['row_sha256'],'raw_source':row['raw_source'],'reference':row['handle_reference'],
                'verification':'WHOLE_CHUNK_BYTES_AND_EXACT_STREAM_ROW/FD_SLOT'}))
    for selector,fd in samples.values():assert view.combined_resolve(selector)['value']==fd
    auxiliary={table:list(view.iter_records(table)) for table in ('birth_facts','frontiers')}
    assert port_count==counts['projected_fd_ports']
    progress({'phase':'ALL_PROVIDER_ROWS_PASS','fd_ports':port_count,'tables':{k:len(v) for k,v in auxiliary.items()}})
    selections=Counter();containers=Counter();targets=set();original_targets=set();process_none=0;handle_count=0
    with gzip.GzipFile(filename=str(HERE/'all-handle-field-proofs.jsonl.gz'),mode='xb',mtime=0,compresslevel=1) as proofs:
        for old,new in zip(base.reader.iter_records('handles'),view.iter_handle_records(),strict=True):
            ordinal,wire=old['ordinal'],new['record'];original=old['record']
            assert ordinal==new['ordinal'] and original['id']==wire['id']
            assert {k:v for k,v in original.items() if k!='handle'}=={k:v for k,v in wire.items() if k!='handle'}
            typed=decode(HandleBinding,wire);assert encode(typed)==wire
            assert type(typed.handle) is ProviderHandle and type(typed.handle.container) is Unresolved
            if typed.id in r2.handles:
                assert wire==encode(r2.handles[typed.id][1]);selections['original_R2_endpoint_exact']+=1
            else:
                row=ports[view.index[ordinal]]
                assert wire['handle']['selector']==row['selector'] and wire['target']==row['target']
                assert row['reference']['canonical_record_sha256']==hashlib.sha256(canonical(original)).hexdigest()
                assert row['reference']['selector']==encode(base.selector('handles',ordinal))
                selections['FD_values_only_endpoint']+=1
            handle_count+=1;containers[type(typed.handle.container).__name__]+=1
            process_none+=typed.start.process is None
            original_targets.add(original['target']['instance']['wire']);targets.add(wire['target']['instance']['wire'])
            proofs.write(canonical({'ordinal':ordinal,'id':wire['id'],'original_canonical_record_sha256':hashlib.sha256(canonical(original)).hexdigest(),
                'selected_canonical_record_sha256':hashlib.sha256(canonical(wire)).hexdigest(),
                'nonendpoint_fields_identical':True,'container':'Unresolved','selection':new['selection']}))
            if handle_count%2000==0:progress({'phase':'ALL_HANDLE_CODEC_AND_INVARIANTS','handles':handle_count})
    assert handle_count==counts['base_handles'] and targets==original_targets
    assert selections['original_R2_endpoint_exact']==len(r2.handles)
    assert selections['FD_values_only_endpoint']==counts['projected_fd_ports']
    assert counts['new_container_bindings']==counts['raw_bytes_read_during_requalification']==0
    works=[]
    for reference in r2.document['base_references']['submissions']:
        ordinal=reference['selector']['ordinal'];expected=r2.record('submissions',ordinal)
        actual=view.record('submissions',ordinal);assert actual==expected
        works.append({'ordinal':ordinal,'record_sha256':hashlib.sha256(canonical(actual['record'])).hexdigest()})
    assert canonical(r2.document['provider_accesses'])==original_accesses
    for ordinal in (min(view.index),max(view.index)):
        assert view.record('handles',ordinal)['record']['handle']['selector']==ports[view.index[ordinal]]['selector']
    links=[]
    for table,descriptor in view.manifest['tables'].items():
        for chunk in descriptor['chunks']:
            src=paths['original_projection'].parent/chunk['uri'];dst=HERE/'result'/chunk['uri']
            assert digest(src)['sha256']==digest(dst)['sha256']==chunk['physical_sha256']
            assert src.stat().st_ino==dst.stat().st_ino and src.stat().st_dev==dst.stat().st_dev
            links.append({'original':digest(src),'retained':digest(dst),'same_inode_device':True})
    write('hardlink-receipts.json',links);write('work-receipts.json',works);write('auxiliary-records.json',auxiliary)
    for name,receipt in producer['inputs'].items():assert digest(paths[name])==receipt,name
    after=imports();write('actual-imports-after.json',after)
    aftermap={row['module']:row for row in after};drift=[row for row in before if row!=aftermap[row['module']]]
    for row in freeze['files']:assert digest(ROOT/row['relative'])['sha256']==row['sha256'],row['relative']
    assert not drift
    report={'schema':'scar.fd-values-correction-gate-report','schema_version':1,
        'status':'PASS_FD_VALUES_ONLY_R2','counts':counts,'all_handle_public_codec':handle_count,
        'container_counts':dict(containers),'field_results':dict(selections),'port_selectors_batch_verified':port_count,
        'point_selector_samples':len(samples),'auxiliary_records':{k:len(v) for k,v in auxiliary.items()},
        'extraction_contracts':dict(contracts),'process_none_preserved':process_none,
        'baseline_resource_targets_preserved':len(targets),'baseline_target_lifetime_coidentity_semantics':'NOT_REPROVED',
        'selected_works_unchanged':len(works),'selected_accesses_unchanged':len(r2.accesses),
        'fail_closed_negative_paths':len(rejects),'hardlinked_payload_chunks':len(links),
        'manifest':result['manifest_receipt'],'raw_reopens':len(raw_open_attempts),
        'raw_open_guard':'all exact logical/local archive data paths denied by this-process audit hook',
        'source_drift':drift,'actual_scar_imports':len(after),
        'elapsed_seconds':time.monotonic()-started,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'scope':'offline with possible parallel load; not target benchmark','target_runs':0,
        'full_execution_model_semantics':'OPEN','first_stage_complete':False,'transformation_authorized':False}
    write('summary.json',report);progress({'phase':'GATE_COMPLETE','status':report['status'],'counts':counts})


if __name__=='__main__':main()
