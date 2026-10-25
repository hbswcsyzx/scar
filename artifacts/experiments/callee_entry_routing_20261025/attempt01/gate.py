"""One saved-CPU actual callee-entry snapshot/port gate. Root owns execution."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]


def verify_sources(freeze):
    amount=0
    for ref in freeze['sources']+freeze['runner']:
        actual=sha(Path(ref['uri']))
        assert actual==ref,ref['uri']
        amount+=actual['size_bytes']
    return amount


def run():
    freeze=small(HERE/'freeze.json')
    out=HERE/'products'
    assert not out.exists()
    out.mkdir()
    source_bytes=verify_sources(freeze)
    from scar.analysis.model_run import _PinnedModelInputs
    from scar.analysis.source_entry_run import _terminal
    from scar.analysis.program_composition import CompositionIndex
    from scar.analysis.source_attachments import SourceAttachmentBudget
    from scar.analysis.compiler_witness_archives import CompilerWitnessArchives,CompilerArchiveBudget
    from scar.analysis.code_witness import CodeWitnessBudget
    from scar.analysis.source_invocations import bind_source_invocations
    from scar.analysis.source_entry_routing import ENTRY_ROUTING_PROFILE
    from scar.analysis.source_entry_routing_validation import EntryRoutingError
    from scar.ir.program.call_edges import CallEdgeBudget
    from scar.ir.program.call_operands import CallOperandBudget
    reader=_PinnedModelInputs(2_000_000)
    entry=small(Path(freeze['entry_terminal']['uri']))
    inputs=_terminal(entry['dependency_terminal']['uri'],reader)
    archives=CompilerWitnessArchives(tuple((str(Path(inputs[key]['uri']).parent),inputs[key]['sha256'])
        for key in ('archive','project_archive')),
        store_budget=CodeWitnessBudget(max_compile_keys=21,max_source_files=6,max_source_bytes=1_000_000,
            max_archive_bytes=32_000_000,max_manifest_bytes=2_000_000),
        budget=CompilerArchiveBudget(max_archives=2,max_total_modules=21,max_total_sources=6,max_declared_payload_bytes=32_000_000))
    before=[dict(archives.store_for(ref).counts) for ref in archives.receipts()]
    composition=CompositionIndex.from_source_entry_publication(freeze['publication']['manifest'],
        expected_sha256=freeze['publication']['sha256'],archives=archives,
        attachment_budget=SourceAttachmentBudget(max_report_bytes=2_000_000,max_files=6,max_codes=16,
            max_roots=8,max_artifact_bytes=128_000_000,max_record_bytes=64_000_000,cached_files=1))
    result={'schema':'scar.callee-entry-parameter-gate','schema_version':1,'status':'RUNNING',
        'publication_repeated':False,'lower_compile_target_capture':'NOT_RUN','whole_model':'OPEN'}
    coordinates,capture=genuine_coordinates(freeze['capture_model'],out/'capture-coordinates.json',result)
    assert str(capture)==inputs['capture']
    negative=[]

    def consume(session):
        rows=session.rows()
        candidates=[(i,row) for i,row in enumerate(rows)
                    if row['status']=='QUALIFIED_CALLEE_ENTRY_SNAPSHOT' and len(row['parameters'])>=2]
        result['actual_entry_summary']=session.summary()
        if not candidates:return
        index,row=candidates[0]
        first,second=row['parameters'][:2]
        assert first['formal_slot']!=second['formal_slot'] and first['source']!=second['source']
        candidate=list(deepcopy(rows))
        a,z=candidate[index]['parameters'][:2]
        for key in ('formal_position','formal_slot','source'):
            a[key],z[key]=z[key],a[key]
        a['occurrence']['core_value'],z['occurrence']['core_value']=z['occurrence']['core_value'],a['occurrence']['core_value']
        candidate=json.loads(json.dumps(candidate))
        try:
            session.check_rows(candidate)
        except EntryRoutingError as error:
            assert 'entry_parameter_port' in str(error) and 'entry_parameter_source' in str(error)
            negative.append({'case':'swap_actual_same_entry_formal_ports_and_parameter_sources','rejected':True,
                'reason':str(error),'independent_semantic_rejection':True,'seal_rejection':False,
                'invocation':row['invocation'],'anchor':row['anchor'],
                'original_pair':[first,second]})
        else:raise AssertionError('actual parameter port/source exchange accepted')

    report=bind_source_invocations(composition,coordinates,capture/'trace',out/'bindings',
        witness_mode='same_capture',call_budget=CallEdgeBudget(**freeze['frame_scanner']),
        seed_verification_budget=CallEdgeBudget(**freeze['seed_verifier']),
        entry_routing_profile=ENTRY_ROUTING_PROFILE,
        entry_operand_budget=CallOperandBudget(**freeze['operand_scanner']),on_entry_routing=consume)
    assert report['schema_version']==5 and report['entry_routing_profile']==ENTRY_ROUTING_PROFILE
    assert report['summary']['invocations']==report['summary']['exits']==271
    assert report['summary']['entered_code_groups']==9 and report['summary']['orphan_exits']==0
    assert all(value==271 for value in report['summary']['unconnected_interfaces'].values())
    assert len(report['summary']['unconnected_interfaces'])==5
    assert report['actual_entry_raw_scan']['frame_complete_passes']==1
    assert report['actual_entry_raw_scan']['total_bytes']<=2_000_000
    assert report['actual_entry_raw_scan']['frame_bytes']==sum(x['raw_bytes'] for x in report['trace_files'])
    assert report['entry_routing_summary']==result['actual_entry_summary']
    assert report['entry_parameter_projection']['rows']==271
    assert all(report[key] is False for key in ('actual_formal_routing_established','return_value_routing_established',
        'function_environment_established','state_versions_established','effects_established','execution_model_established'))
    if len(negative)!=1:
        result.update(status='BLOCKED_NO_REAL_TWO_FORMAL_ENTRY',report=report,gate_exit=2)
        return result
    result['sole_negative']=negative[0]
    result['report']=report
    result['readonly_activity']=[{key:archives.store_for(ref).counts[key]-prior.get(key,0)
        for key in archives.store_for(ref).counts} for ref,prior in zip(archives.receipts(),before)]
    assert all(x['compile_attempts']==0 for x in result['readonly_activity'])
    frozen={x['uri']:x for x in freeze['sources']}
    imports=[]
    for name,module in sorted(sys.modules.items()):
        if name!='scar' and not name.startswith('scar.'):continue
        path=str(Path(module.__file__).resolve())
        assert path in frozen and Path(path).is_relative_to(ROOT/'scar'),(name,path)
        imports.append({'module':name,'uri':path,'sha256':frozen[path]['sha256']})
    source_bytes+=verify_sources(freeze)
    result.update(status='ACTUAL_CALLEE_ENTRY_SNAPSHOT_PORTS_WITH_OPEN',gate_exit=0,
        actual_SCAR_imports=imports,source_SHA_pass_bytes_separate=source_bytes,
        metadata_planning_reads={'stored':reader.stored_bytes,'decoded':reader.decoded_bytes},
        poststage_output_bytes=sum(p.stat().st_size for p in out.rglob('*') if p.is_file()),
        new_capture_runs=0,new_target_runs=0,Tensor_values_materialized=0,
        caller_expression_object_logical_state_ready_established=False)
    assert result['poststage_output_bytes']+len(json.dumps(result).encode())<128_000_000
    return result



def sha(path):
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while block := stream.read(1_048_576):
            digest.update(block); size += len(block)
    return {'uri': str(path), 'sha256': digest.hexdigest(), 'size_bytes': size}

def small(path):
    assert path.is_file() and not path.is_symlink() and path.stat().st_size <= 2_000_000
    return json.loads(path.read_bytes())

def put(path, document):
    with path.open('x') as stream:
        json.dump(document, stream, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n')

def genuine_coordinates(ref, out, report):
    # The unchanged native_capture_batch.py:1166-1236 acquisition idiom,
    # stopping before native input preparation/V2/source index/model batching.
    from scar.trace.capture_coordinates import bind_capture_coordinates
    from scar.trace.native_tensor_inputs import NativeInputPayloadBudget
    from scar.ir.execution.coordinates import ExecutionRun
    from scar.ir.record_codec import decode
    ledger = NativeInputPayloadBudget(maximum=64_000_000, control_maximum=1_000_000)
    report['coordinate_accounting'] = ledger.report()
    def control(path, expected=None):
        path = Path(path)
        assert path.is_absolute() and not path.is_symlink() and path.is_file()
        size = path.stat().st_size
        reservation = ledger.charge('control: ' + path.name, size, size, control=True)
        with path.open('rb') as stream:
            raw = stream.read(size + 1)
        assert len(raw) == size and (expected is None or hashlib.sha256(raw).hexdigest() == expected)
        ledger.complete(reservation)
        return json.loads(raw), raw
    try:
        model, _ = control(ref['uri'], ref['sha256'])
        assert model['schema'] == 'scar.capture-model' and model['schema_version'] == 1
        root = Path(model['capture']).resolve()
        retained, retained_raw = control(model['coordinate_binding']['uri'], model['coordinate_binding']['sha256'])
        assert len(retained_raw) == model['coordinate_binding']['size_bytes'] and retained['local_root'] == str(root)
        archive, archive_raw = control(root / 'archive-index.json', retained['seed']['archive_sha256'])
        assert archive['schema'] == 'scar.lossless-capture-archive' and archive['schema_version'] == 1
        members = {row['artifact']['uri']: row for row in retained['membership']}
        archived = {row['logical_path']: row for row in archive['files']}
        assert len(members) == len(retained['membership']) and len(archived) == len(archive['files'])
        def one(schema):
            rows = [row['artifact'] for row in retained['membership'] if row['artifact']['schema'] == schema]
            assert len(rows) == 1, schema
            return rows[0]
        native = one('scar.execution-evidence-collection')
        native_meta, _ = control(members[native['uri']]['local_path'], native['sha256'])
        run_size = (root / 'trace/run.json').stat().st_size
        plain = sum(row['artifact']['size_bytes'] for row in retained['membership'] if row['artifact']['uri'] not in archived) + run_size
        archive_stored = sum(row['compressed_bytes'] for row in archive['files'])
        verified_raw = sum(row['raw_bytes'] for row in archive['files']) + plain
        assert verified_raw == retained['counts']['verified_raw_bytes'] and verified_raw <= 64_000_000
        ledger.charge('ordinary binder verified complete members', 2 * archive_stored + plain, verified_raw,
            basis='precharged complete SHA passes; fresh ordinary binder reconciles exact receipts')
        os_rows = [row['artifact'] for row in retained['membership'] if row['artifact']['schema'] == 'strace.syscalls.text.v1']
        ledger.charge('ordinary binder OS fact parse', sum(archived[row['uri']]['compressed_bytes'] for row in os_rows),
            sum(row['size_bytes'] for row in os_rows), basis='unchanged complete OS fact parse passes')
        cap = retained['native_tensor_input_membership']
        ledger.charge('ordinary binder strict companion parse', sum(archived[row['uri']]['compressed_bytes'] for row in cap['chunks']),
            sum(row['size_bytes'] for row in cap['chunks']), basis='unchanged complete strict companion parse passes')
        companion = sum(row['size_bytes'] for row in (native, one('scar.tensor-physical-trace'), one('scar.dispatch-observation-trace'), cap['manifest']))
        ledger.charge('ordinary binder strict companion metadata parse', companion, companion, basis='cached verified document parse')
        doc_names = ('call-meta.', 'call-operand-meta.', 'function-environment-meta.', 'dispatch-meta.', 'tensor-physical-meta.')
        docs = sum(row['artifact']['size_bytes'] for row in retained['membership'] if Path(row['logical_path']).name.startswith(doc_names)) + cap['manifest']['size_bytes'] + run_size
        ledger.charge('ordinary binder other metadata parse', docs, docs, basis='complete document passes')
        initial = native['size_bytes'] + len(archive_raw)
        ledger.charge('ordinary binder initial native/archive', initial, initial, basis='complete initial document reads')
        controls = sum(row['size_bytes'] for row in (retained['os_capture_provider']['launch'], retained['os_capture_provider']['profile'],
                                                   native_meta['configuration']['os_capture_intent']['intent']))
        ledger.charge('ordinary binder OS intent/launch/coverage', 2 * controls, 2 * controls, basis='receipt read plus document read')
        coordinates = bind_capture_coordinates(root, max_bytes=verified_raw, profile_uri=str(out))
        assert coordinates.run == decode(ExecutionRun, model['run']) and coordinates.payload == retained_raw
        assert coordinates.report['counts']['verified_raw_bytes'] == verified_raw
        ledger.complete_prefix('ordinary binder ')
        out.write_bytes(coordinates.payload)
        return coordinates, root
    finally:
        report['coordinate_accounting'] = ledger.report()


if __name__=='__main__':
    if any((HERE/n).exists() for n in ('products','result.json','failure.json')):raise SystemExit('fresh gate required')
    started=time.monotonic()
    try:
        result=run()
    except BaseException as error:
        result={'status':'FAILED_CALLEE_ENTRY_ROUTING_GATE','error_type':type(error).__name__,'message':str(error),
            'traceback':traceback.format_exc(),'elapsed_seconds':time.monotonic()-started,'whole_model':'OPEN'}
        put(HERE/'failure.json',result)
        print(json.dumps(result),flush=True)
        raise
    result['elapsed_seconds']=time.monotonic()-started
    put(HERE/'result.json',result)
    print(json.dumps(result),flush=True)
    raise SystemExit(result['gate_exit'])
