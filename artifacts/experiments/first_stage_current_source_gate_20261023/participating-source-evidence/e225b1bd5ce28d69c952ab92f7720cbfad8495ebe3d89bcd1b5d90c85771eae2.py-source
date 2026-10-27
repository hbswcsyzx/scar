"""ONE369749 current source -> markers -> operand/environment retained gate."""
from collections import Counter
from copy import deepcopy
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import sys
import threading
import time

from prepare import (HERE, ROOT, CAPTURE, COMPOSITION, ATTACHMENT, BRIDGE, CACHE,
                     EXPECTED_ATTACHMENT, EXPECTED_RUN, SCOPE, receipt)

START=time.monotonic()
PHASE='startup'
RESULT=HERE/'result'
STOP,LOCK=threading.Event(),threading.Lock()
INDEX=None
FROZEN=json.loads((HERE/'frozen/producer.json').read_bytes())
EXPECTED={row['path']:row for row in FROZEN['modules']}


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()


def write_json(path,value):
    with path.open('x') as stream:
        json.dump(value,stream,ensure_ascii=False,sort_keys=True,allow_nan=False,indent=2);stream.write('\n')


def measurements():
    return [item.measurements() for item in INDEX._attachments] if INDEX is not None else []


def notify(event=None,**fields):
    if type(event) is dict:
        fields={**event,**fields};event=fields.pop('stage','API_PROGRESS')
    row={'event':event,'phase':PHASE,'elapsed_s':time.monotonic()-START,'pid':os.getpid(),
         'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,**fields}
    with LOCK:
        with (HERE/'progress.jsonl').open('a') as out:out.write(json.dumps(row,sort_keys=True)+'\n')
    print(json.dumps(row,sort_keys=True),flush=True)


def heartbeat():
    while not STOP.wait(20):
        try:values=measurements()
        except RuntimeError:values='concurrent diagnostics update'
        notify('HEARTBEAT',attachment_measurements=values,meaning='liveness/read counters only')


def exact_sources(*,final=False):
    imported={str(Path(module.__file__).resolve()) for module in tuple(sys.modules.values())
              if getattr(module,'__file__',None) and str(Path(module.__file__).resolve()).startswith(str(ROOT/'scar')+'/')}
    mandatory={str(ROOT/'scar/analysis'/ (name+'.py')) for name in (
        'source_attachments','program_composition','source_invocations','dispatch_sources','source_body_access',
        'source_layers','code_witness','call_edges','call_operands','call_operand_routes','callable_environment_import')}
    names=imported|mandatory|{str(HERE/name) for name in ('run.py','prepare.py','run.sh')}
    checked=[]
    for name in sorted(names):
        assert name in EXPECTED,('unrecorded imported source',name)
        row=receipt(Path(name));assert row==EXPECTED[name],('participating producer drift',name)
        checked.append(row)
    if final:
        folder=HERE/'participating-source-evidence';folder.mkdir(exist_ok=False)
        for row in checked:
            path=folder/(row['sha256']+'.py-source')
            if not path.exists():shutil.copyfile(row['path'],path)
        write_json(HERE/'participating-producer.json',{'actual_imports':sorted(imported),'checked':checked,
            'sha_unchanged':True,'unused_candidates_not_authority':True})


def source_audit(report):
    doc=json.loads((RESULT/'source/bindings.json').read_bytes())
    table=doc['bindings'];indexes={(row['process_id'],row['code']):row for row in table}
    assert len(indexes)==len(table)==report['summary']['entered_code_groups']
    assert report['schema_version']==doc['schema_version']==3
    assert report['witness_mode']==doc['witness_mode']=='reused_code'
    assert report['attachment_source_match_rule']==doc['attachment_source_match_rule']=='EXACT_CAPTURED_CODE_STATIC_REUSE_V1'
    assert report['run']['id']['value']==EXPECTED_RUN
    current=Counter();activations=0;digest=hashlib.sha256();size=0
    with gzip.open(RESULT/'source/invocations.jsonl.gz','rb') as stream:
        for raw in stream:
            digest.update(raw);size+=len(raw);row=json.loads(raw)
            key=(row['invocation']['process_id'],row['code']);current[key]+=1
            binding=indexes[key]
            assert row['invocation']['process_id']==369749 and row['status']==binding['status']
            if row['region_activation'] is not None:
                activations+=1
                assert row['region_activation']['entry']['run']['value']==EXPECTED_RUN
            if binding['source_origin']=='SOURCE_ATTACHMENT':
                assert binding['body'] is None and binding['composition_element'] is None
                assert row['region_activation'] is None and row['region_namespace'] is None
    assert set(current)==set(indexes) and all(count==indexes[key]['entered_invocations'] for key,count in current.items())
    assert sum(current.values())==report['summary']['invocations']==report['invocations']['rows']
    assert (digest.hexdigest(),size)==(report['invocations']['raw_sha256'],report['invocations']['raw_bytes'])
    scope=json.loads(SCOPE.read_bytes())
    new={row['key'] for row in scope['new_code_descriptors']}
    for key in new:
        entered=indexes.get((369749,key))
        if entered is not None:
            assert entered['status']=='UNRESOLVED' and entered['definition'] is None and entered['body'] is None
            assert 'NO_MATCHING_STATIC_CODE_SOURCE_WITNESS' in entered['frontiers']
    for old in scope['historical_guard_drift']:
        assert (369749,old['code']) not in indexes
    external=[row for row in table if row['source_origin']=='SOURCE_ATTACHMENT']
    result={'current_entered_code_groups':len(current),'current_entries':sum(current.values()),
        'current_activations':activations,'current_binding_statuses':dict(Counter(row['status'] for row in table)),
        'current_weighted_statuses':dict(Counter({status:sum(row['entered_invocations'] for row in table if row['status']==status)
            for status in {row['status'] for row in table}})),
        'external_groups':len(external),'external_calls':sum(row['entered_invocations'] for row in external),
        'new_descriptor_frontier_current_calls':sum(indexes[(369749,key)]['entered_invocations'] for key in new if (369749,key) in indexes),
        'no_old_dynamic_counts_transferred':True,'current_guards':dict(Counter(row['status'] for row in report['current_source_checks']))}
    write_json(HERE/'source-audit.json',result)
    return indexes,current,result


def marker_audit(report):
    counts,statuses,samples=Counter(),Counter(),{}
    digest,size=hashlib.sha256(),0
    with gzip.open(RESULT/'dispatch/associations.jsonl.gz','rb') as stream:
        for raw in stream:
            digest.update(raw);size+=len(raw);row=json.loads(raw)
            counts['rows']+=1;counts['slots']+=len(row['qualified_slot_path_indices']);statuses[row['status']]+=1
            assert row['direct_callsite_established'] is False and row['relationship']=='RETAINED_ANCESTOR_CONTEXT'
            if row['invocation'] is not None:assert row['invocation']['process_id']==369749
            if row['source_origin']=='SOURCE_ATTACHMENT':
                counts['external_source_only_rows']+=1
                assert row['body'] is None and row['region_activation'] is None and row['composition_element'] is None
                samples.setdefault('EXTERNAL_SOURCE_ONLY',row['marker_instance'])
            samples.setdefault(row['status'],row['marker_instance'])
    assert counts['rows']==report['observations']['rows']==79592 and counts['slots']==109288
    assert (digest.hexdigest(),size)==(report['observations']['raw_sha256'],report['observations']['raw_bytes'])
    from scar.analysis.dispatch_sources import query_dispatch_source
    queries={label:query_dispatch_source(RESULT/'dispatch',marker) for label,marker in samples.items()}
    write_json(HERE/'marker-queries.json',queries)
    return {'counts':dict(counts),'statuses':dict(statuses),'query_statuses':sorted(queries)}


# Exact existing bounded serializer, copied without importing the old runner.
def partitions(document):
    """Preserve one to_dict document in bounded reference-only gzip tables."""
    destination = RESULT / 'analysis'
    destination.mkdir()
    maximum = 16_000_000
    tables = {}

    def table(name, rows):
        chunks, pending, total, number = [], bytearray(), 0, 0
        def flush():
            nonlocal pending, number
            if not pending:
                return
            path = destination / (name + '.' + str(len(chunks)).zfill(4) + '.jsonl.gz')
            payload = bytes(pending)
            with path.open('xb') as raw:
                with gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as stream:
                    stream.write(payload)
            chunks.append({**receipt(path), 'decoded_sha256': hashlib.sha256(payload).hexdigest(),
                           'decoded_bytes': len(payload), 'rows': number})
            pending, number = bytearray(), 0
        for row in rows:
            raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'
            if len(raw) > maximum:
                raise ValueError('one existing report record exceeds independent 16MB shard ceiling')
            if len(pending) + len(raw) > maximum or number == 1000:
                flush()
            pending.extend(raw)
            number += 1
            total += 1
        flush()
        tables[name] = {'rows': total, 'chunks': chunks}

    header = {key: value for key, value in document.items()
              if key not in ('routing', 'entry_parameters', 'environments', 'code_links')}
    table('code_links', document['code_links'])
    table('entry_parameters', document['entry_parameters'])
    routing = document['routing']
    header['routing'] = {key: value for key, value in routing.items() if type(value) is not list}
    for key, value in routing.items():
        if type(value) is list:
            table('routing.' + key, value)
    environment = document['environments']
    header['environments'] = {key: value for key, value in environment.items()
                              if key not in ('bindings', 'unresolved', 'files', 'metadata')}
    for key in ('bindings', 'unresolved', 'files', 'metadata'):
        table('environments.' + key, environment[key])
    raw = json.dumps(header, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > maximum:
        raise ValueError('report header exceeds independent 16MB shard ceiling')
    path = destination / 'header.json.gz'
    with path.open('xb') as out:
        with gzip.GzipFile(fileobj=out, mode='wb', filename='', mtime=0) as stream:
            stream.write(raw)
    digest, size = hashlib.sha256(), 0
    for text in json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).iterencode(document):
        block = text.encode()
        digest.update(block)
        size += len(block)
    manifest = {'schema': 'scar.partitioned-call-operand-links', 'schema_version': 1,
        'original_schema': document['schema'], 'original_schema_version': document['schema_version'],
        'canonical_document_sha256': digest.hexdigest(), 'canonical_document_bytes': size,
        'header': {**receipt(path), 'decoded_sha256': hashlib.sha256(raw).hexdigest(), 'decoded_bytes': len(raw)},
        'tables': tables, 'max_shard_decoded_bytes': maximum, 'max_rows_per_shard': 1000,
        'table_pointer_rule': 'dot-separated table names replace that original JSON array; header holds all other fields',
        'canonical_graphs_copied': False, 'whole_program_established': False, 'transformation_authorized': False}
    write_json(destination / 'manifest.json', manifest)
    return manifest


def main():
    global PHASE,INDEX
    exact_sources()
    fixed=json.loads((HERE/'inputs.json').read_bytes())
    assert receipt(HERE/'inputs.json')==FROZEN['fixed_inputs']
    for row in fixed['inputs']:assert receipt(Path(row['path']))==row
    RESULT.mkdir(exist_ok=False)
    notify('START',revision=FROZEN['revision'],fixed_inputs=len(fixed['inputs']))
    thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
    durations={}
    try:
        # Only normal retained-coordinate binding, never OS graph import/replay.
        from scar.trace.capture_coordinates import bind_capture_coordinates
        from scar.analysis.program_composition import CompositionIndex
        from scar.analysis.source_attachments import SourceAttachmentBudget
        from scar.analysis.source_invocations import bind_source_invocations
        from scar.analysis.dispatch_sources import bind_dispatch_sources
        from scar.analysis.code_witness import CodeWitnessStore,CodeWitnessBudget
        from scar.analysis.call_operands import link_call_operands
        from scar.ir.program.call_edges import CallEdgeBudget
        from scar.ir.program.call_operands import CallOperandBudget
        from scar.ir.program.call_operand_routes import OperandRouteBudget
        PHASE='current369749-coordinate-membership'
        start=time.monotonic()
        coordinates=bind_capture_coordinates(CAPTURE,max_bytes=2_000_000_000,max_lines=2_000_000,
            profile_uri=str(RESULT/'capture-coordinates.json'))
        assert coordinates.run.id.value==EXPECTED_RUN
        (RESULT/'capture-coordinates.json').write_bytes(coordinates.payload)
        durations[PHASE]=time.monotonic()-start;notify('PHASE_END',seconds=durations[PHASE])
        PHASE='explicit-original-composition-and-static-attachments'
        INDEX=CompositionIndex(COMPOSITION,source_attachments=((str(ATTACHMENT),EXPECTED_ATTACHMENT),),
            attachment_budget=SourceAttachmentBudget(max_record_bytes=128_000_000,max_artifact_bytes=2_200_000_000))
        before=deepcopy(INDEX.document);before_sha=hashlib.sha256(canonical(before)).hexdigest()
        assert INDEX.inventory_file_count==151
        frame_budget=CallEdgeBudget(max_raw_bytes=256_000_000,max_lines=300_000,max_events=250_000,
                                   max_references=2_000_000,max_source_files=256,max_source_bytes=16_000_000)
        PHASE='current-independent-source-binding-static-reuse'
        start=time.monotonic()
        source=bind_source_invocations(INDEX,coordinates,CAPTURE/'trace',RESULT/'source',
            call_budget=frame_budget,witness_mode='reused_code')
        durations[PHASE]=time.monotonic()-start
        current_collector=source['collection_metadata'][0]
        assert source['summary']['code_captures']==current_collector['codes']==855
        assert source['summary']['invocations']==source['summary']['exits']==current_collector['invocations']==100438
        current_bindings,weighted_groups,source_check=source_audit(source)
        source_reads=measurements()
        notify('PHASE_END',seconds=durations[PHASE],source_audit=source_check,attachment_measurements=source_reads)
        PHASE='same-current-run-production-markers'
        start=time.monotonic()
        marker=bind_dispatch_sources(RESULT/'source',BRIDGE,coordinates,RESULT/'dispatch',composition_index=INDEX)
        durations[PHASE]=time.monotonic()-start
        marker_check=marker_audit(marker);marker_reads=measurements()
        assert marker_reads==source_reads
        notify('PHASE_END',seconds=durations[PHASE],marker_audit=marker_check,attachment_measurements=marker_reads)
        PHASE='current-operand-frame-sourcebody-and-environment'
        start=time.monotonic()
        cache_before=receipt(CACHE/'manifest.json')
        store=CodeWitnessStore(CACHE,create=False,compile_missing=False,
            budget=CodeWitnessBudget(max_compile_keys=20),progress=notify)
        report=link_call_operands(CAPTURE/'trace','/home/zyf/AAA/le-wm',composition=INDEX,
            source_bindings=RESULT/'source',coordinates=coordinates,code_witnesses=store,
            frame_budget=frame_budget,operand_budget=CallOperandBudget(),route_budget=OperandRouteBudget(),
            include_environments=True,progress=notify)
        durations[PHASE]=time.monotonic()-start
        frame=report.frame_model
        independent_groups=Counter((edge.entry.invocation.process_id,edge.entry.code) for edge in frame.edges)
        assert independent_groups==weighted_groups
        assert len(frame.edges)==len(frame.exits)==source['summary']['invocations']
        assert len(frame.codes)==source['summary']['code_captures']
        assert all(edge.entry.invocation.process_id==369749 for edge in frame.edges)
        assert store.counts['compile_attempts']==0 and not store.writable and not store.compile_missing
        assert receipt(CACHE/'manifest.json')==cache_before
        assert report.source_body_access['current_raw_scan_verified'] is True
        assert report.source_body_access['run']['id']['value']==EXPECTED_RUN
        envmeta=json.loads((CAPTURE/'trace/function-environment-meta.369749.json').read_bytes())
        assert report.environments['summary']['events']==envmeta['events']
        notify('PHASE_END',seconds=durations[PHASE],summary=report.summary(),code_witness_activity=store.counts,
            environment_summary=report.environments['summary'],attachment_measurements=measurements())
        PHASE='existing-report-partition-export'
        start=time.monotonic()
        document=report.to_dict();archive=partitions(document)
        durations[PHASE]=time.monotonic()-start
        assert INDEX.document==before and hashlib.sha256(canonical(INDEX.document)).hexdigest()==before_sha
        assert INDEX.source_inputs()==source['source_inputs']==marker['source_inputs']
        assert receipt(CACHE/'manifest.json')==cache_before
        PHASE='selected-qualified-source-queries'
        from scar.ir.program.source_references import SourceDefinitionReference
        from scar.ir.record_codec import decode,encode
        selected_queries={}
        for origin in ('INVENTORY','SOURCE_ATTACHMENT'):
            available=[row for row in current_bindings.values() if row['source_origin']==origin and row['definition'] is not None]
            if not available:continue
            chosen=min(available,key=lambda row:row['definition']['graph']['decoded_bytes'])
            reference=decode(SourceDefinitionReference,chosen['definition'])
            definition=INDEX.resolve_definition(reference);view=INDEX.source_view(reference)
            assert view.snapshot==reference.snapshot and view.context==reference.context
            assert definition==view.semantic.definitions[reference.definition]
            assert view.semantic.source_atoms[reference.source.atom_id].reference==reference.source
            assert 'file_index' not in reference.__dataclass_fields__
            selected_queries[origin]={'reference':encode(reference),'definition':encode(definition),
                'original_snapshot_context_source_atom_definition_verified':True}
        write_json(HERE/'qualified-source-queries.json',selected_queries)
        exact_sources(final=True)
        summary={'status':'PASS_WITH_OPEN_MODEL_OBLIGATIONS','run':EXPECTED_RUN,'process_id':369749,
            'current_source':source_check,'current_marker':marker_check,
            'current_independent_entered_code_groups':len(independent_groups),
            'current_operand_events':len(report.operands.events),'current_entry_parameter_occurrences':len(report.entry_parameters),
            'current_environment_summary':report.environments['summary'],'operand_route_summary':report.routing.summary(),
            'operand_route_issue_kinds':dict(Counter(issue.kind.value for issue in report.routing.issues)),
            'source_body_access':report.source_body_access,'code_witness_activity':store.counts,
            'canonical_report_sha256':archive['canonical_document_sha256'],'canonical_report_bytes':archive['canonical_document_bytes'],
            'original_composition_sha256':before_sha,'original_composition_unchanged':True,
            'attachment_measurements_after_source':source_reads,'attachment_measurements_after_marker':marker_reads,
            'attachment_measurements_final':measurements(),'stages_seconds':durations,
            'elapsed_seconds':time.monotonic()-START,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'new_code_source_compiled':False,'source_reprepared':False,'target_executed':False,
            'old_dynamic_invocations_used':False,'first_stage_complete':False,'transformation_authorized':False}
        write_json(HERE/'summary.json',summary);notify('PASS',summary=summary)
    except BaseException as error:
        notify('FAILED',error_type=type(error).__name__,detail=str(error))
        write_json(HERE/'failure.json',{'type':type(error).__name__,'detail':str(error),'phase':PHASE,
            'elapsed_seconds':time.monotonic()-START,'first_stage_complete':False})
        raise
    finally:
        STOP.set();thread.join()


if __name__=='__main__':main()
