"""One original272038 formal source attachment/binding/dispatch public API gate."""
from collections import Counter
from copy import deepcopy
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import threading
import time

from scar.analysis.dispatch_sources import bind_dispatch_sources, query_dispatch_source
from scar.analysis.program_composition import CompositionIndex
from scar.analysis.source_attachments import SourceAttachmentBudget
from scar.analysis.source_invocations import bind_source_invocations
from scar.ir.program.call_edges import CallEdgeBudget
from scar.ir.program.source_references import SourceDefinitionReference
from scar.ir.record_codec import decode, encode
from scar.trace.capture_coordinates import bind_capture_coordinates

BASE = Path(__file__).resolve().parent
REPO, EXPS = BASE.parents[2], BASE.parent
OLD = EXPS / 'first_stage_partitioned_composition_bindings_20261023'
COMPOSITION = OLD / 'composition/index.json.gz'
CAPTURE = EXPS / 'first_stage_lewm_dispatch_20261023'
BRIDGE = EXPS / 'first_stage_joined_dispatch_20261023/result/native/dispatch-bridge.json.gz'
ATTACHMENT = EXPS / 'first_stage_dependency_continuation_20261023/result/continuation.json'
PARENT = EXPS / 'first_stage_dependency_sources_20261023/result/admissions.json'
EXPECTED_ATTACHMENT = 'c9ff2f87a0e90ee42297501d256d9d24aeeab60273c6172fe692c0323207173e'
EXPECTED_PARENT = 'fc97075aa66a92758938ad8416347d895e6b18ef0e454053fc7f9c1a7d2f0424'
EXPECTED_RUN = 'capture:91a2ed5e3f92817799bd02fb2453dadd65ad28fbf4361165c31b881c371c0c66'
MODULES = ('scar/ir/program/source_references.py', 'scar/analysis/source_layers.py',
    'scar/analysis/source_attachments.py', 'scar/analysis/program_composition.py',
    'scar/analysis/source_invocations.py', 'scar/analysis/dispatch_sources.py',
    'scar/analysis/inventory_partitions.py', 'scar/analysis/call_trace_reader.py',
    'scar/trace/capture_coordinates.py', 'scar/ir/record_codec.py')
START, PHASE, INDEX = time.monotonic(), 'startup', None
STOP, LOCK = threading.Event(), threading.Lock()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def receipt(path):
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while block := stream.read(1_048_576):
            digest.update(block); size += len(block)
    return {'path': str(path), 'stored_sha256': digest.hexdigest(), 'stored_bytes': size}


def attachment_measurements():
    # Read-only diagnostic counters, not a canonical graph/proof input.
    return [catalog.measurements() for catalog in INDEX._attachments] if INDEX is not None else []


def log(event, **fields):
    row = {'event': event, 'phase': PHASE, 'elapsed_seconds': time.monotonic() - START,
           'pid': os.getpid(), 'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **fields}
    with LOCK:
        with (BASE / 'progress.jsonl').open('a') as stream:
            stream.write(json.dumps(row, sort_keys=True) + '\n')
    print(json.dumps(row, sort_keys=True), flush=True)


def heartbeat():
    while not STOP.wait(20):
        try:
            values = attachment_measurements()
        except RuntimeError:
            values = 'concurrent diagnostic counter update; no coverage interpretation'
        log('HEARTBEAT', attachment_measurements=values,
            meaning='phase liveness and read counters; not complete program coverage')


def no_file_index(value):
    if type(value) is dict:
        assert 'file_index' not in value
        for item in value.values(): no_file_index(item)
    elif type(value) is list:
        for item in value: no_file_index(item)


def validate_bindings(index, report):
    parent = json.loads(ATTACHMENT.read_bytes())
    original_rows = {(row['process_id'], row['code']): row for row in parent['admissions']}
    old_table = json.loads((OLD / 'bindings/bindings.json').read_bytes())['bindings']
    table = json.loads((BASE / 'bindings/bindings.json').read_bytes())['bindings']
    assert report['schema_version'] == 3
    assert report['summary']['code_captures'] == 855
    assert report['summary']['entered_code_groups'] == len(table) == 817
    assert report['summary']['invocations'] == report['summary']['exits'] == 100438
    assert report['summary']['orphan_exits'] == 0
    assert report['run']['id']['value'] == EXPECTED_RUN
    ext, unresolved, statuses, current_drift = Counter(), Counter(), Counter(), Counter()
    samples = {}
    for row, old in zip(table, old_table, strict=True):
        key = row['process_id'], row['code']
        original = original_rows[key]
        assert row['binding_index'] == old['binding_index']
        assert key == (old['process_id'], old['code'])
        assert row['body'] == old['body']
        statuses[row['status']] += row['entered_invocations']
        if row['definition'] is not None:
            no_file_index(row['definition'])
        if original['status'] == 'SOURCE_VERIFIED':
            ext['groups'] += 1; ext['calls'] += row['entered_invocations']
            assert row['source_origin'] == 'SOURCE_ATTACHMENT'
            assert row['status'] == 'SOURCE_LINKED_REUSED_WITNESS'
            assert row['body'] is None and row['composition_element'] is None
            assert row['definition'] is not None
            assert row['attachment_witness']['code_source_link'] == original['code_source_link']
            assert row['definition']['definition'] == original['code_source_link']['definition']
            assert row['definition']['source'] == original['code_source_link']['source']
            assert row['definition_locator'] == row['definition']['graph']
            assert 'CANONICAL_BODY_NOT_MODELLED_BY_SOURCE_ATTACHMENT' in row['frontiers']
            witness = row['attachment_witness']
            assert witness['witness_scope'] == 'HISTORICAL_CAPTURE_SOURCE_EVIDENCE'
            assert witness['guard_scope'] == 'RECORDED_AT_ATTACHMENT_ADMISSION_NOT_REFRESHED'
            if witness['guard'] is not None and witness['guard']['matches'] is False:
                current_drift['groups'] += 1; current_drift['calls'] += row['entered_invocations']
                assert row['current_source_check'] is None
                samples['historical-source-current-drift'] = row
            if original['captured_code']['qualname'] == 'find_torch_dispatch_rule':
                samples['external-source-only'] = row
        else:
            assert row['source_origin'] == 'INVENTORY'
            assert row['composition_element'] == old['definition']
            if original['captured_code'] is not None and original['captured_code']['filename'].startswith('<'):
                unresolved['groups'] += 1; unresolved['calls'] += row['entered_invocations']
                assert row['definition'] is None and row['body'] is None
                assert row['attachment_frontiers']
            if row['definition'] is not None:
                samples.setdefault('project-source', row)
    assert dict(ext) == {'groups': 243, 'calls': 86702}
    assert dict(unresolved) == {'groups': 21, 'calls': 803}
    assert dict(current_drift) == {'groups': 1, 'calls': 14}
    assert sum(statuses.values()) == 100438
    counts, invocations, events_digest, raw_bytes = Counter(), set(), hashlib.sha256(), 0
    with gzip.open(BASE / 'bindings/invocations.jsonl.gz', 'rb') as stream:
        for raw in stream:
            events_digest.update(raw); raw_bytes += len(raw)
            event = json.loads(raw); counts['rows'] += 1
            key = canonical(event['invocation']); assert key not in invocations; invocations.add(key)
            binding = table[event['source_binding_index']]
            assert event['status'] == binding['status'] and event['code'] == binding['code']
            if binding['source_origin'] == 'SOURCE_ATTACHMENT':
                counts['external_source_only_calls'] += 1
                assert event['region_activation'] is None and event['region_namespace'] is None
            if event['region_activation'] is not None: counts['activations'] += 1
    assert counts['rows'] == 100438 and counts['external_source_only_calls'] == 86702
    assert (events_digest.hexdigest(), raw_bytes) == (report['invocations']['raw_sha256'], report['invocations']['raw_bytes'])
    old_dispatch = json.loads((EXPS / 'first_stage_partitioned_dispatch_sources_20261023/result/report.json').read_bytes())
    assert counts['activations'] == old_dispatch['source_audit']['region_activations']
    # Record selected references here; resolve after dispatch so these selected
    # graph-view queries cannot change the per-stage attachment read counters.
    return table, samples, {'external_source_only': dict(ext), 'non_file_frontiers': dict(unresolved),
        'historical_source_current_guard_false': dict(current_drift), 'weighted_statuses': dict(statuses),
        'invocations': dict(counts)}


def validate_dispatch(index, report, binding_table):
    counts, statuses, samples, digest, raw_bytes = Counter(), Counter(), {}, hashlib.sha256(), 0
    with gzip.open(BASE / 'dispatch/associations.jsonl.gz', 'rb') as stream:
        for raw in stream:
            digest.update(raw); raw_bytes += len(raw)
            row = json.loads(raw); counts['rows'] += 1
            counts['slots'] += len(row['qualified_slot_path_indices']); statuses[row['status']] += 1
            assert row['relationship'] == 'RETAINED_ANCESTOR_CONTEXT' and row['direct_callsite_established'] is False
            if row['source_origin'] == 'SOURCE_ATTACHMENT':
                counts['external_source_only_rows'] += 1
                assert row['body'] is None and row['region_activation'] is None and row['region_namespace'] is None
                assert row['composition_element'] is None and row['definition'] is not None
                samples.setdefault('EXTERNAL_SOURCE_ONLY', row['marker_instance'])
            samples.setdefault(row['status'], row['marker_instance'])
    assert counts['rows'] == report['observations']['rows'] == 79592
    assert counts['slots'] == 109288
    assert (digest.hexdigest(), raw_bytes) == (report['observations']['raw_sha256'], report['observations']['raw_bytes'])
    queries = {}
    for label, marker in sorted(samples.items()):
        row = query_dispatch_source(BASE / 'dispatch', marker)
        query = {'marker': marker, 'row': row, 'selected_original_row_sha_verified': True}
        if row['source_binding_reference'] is not None:
            position = int(row['source_binding_reference']['locator'].split('/')[-1])
            assert row['definition'] == binding_table[position]['definition']
            query['exact_binding_definition_preserved'] = True
        queries[label] = query
    (BASE / 'dispatch-queries.json').write_bytes(canonical(queries))
    return {'counts': dict(counts), 'statuses': dict(statuses), 'query_labels': sorted(queries)}


def main():
    global PHASE, INDEX
    producer = {'revision': subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        'script': receipt(Path(__file__)), 'modules': [receipt(REPO / name) for name in MODULES],
        'inputs': [receipt(path) for path in (COMPOSITION, OLD / 'bindings/report.json',
            OLD / 'bindings/bindings.json', ATTACHMENT, PARENT, BRIDGE,
            CAPTURE / 'archive-index.json')],
        'target_process_id': 272038, 'target_run': EXPECTED_RUN,
        'source_reprepared': False, 'source_recompiled': False, 'target_executed': False,
        'first_stage_complete': False, 'transformation_authorized': False}
    assert receipt(ATTACHMENT)['stored_sha256'] == EXPECTED_ATTACHMENT
    assert receipt(PARENT)['stored_sha256'] == EXPECTED_PARENT
    (BASE / 'producer.json').write_bytes(canonical(producer))
    # Includes new untracked modules verbatim; no repository mutation is needed.
    patch = subprocess.check_output(['git','diff','--',*MODULES],cwd=REPO)
    (BASE / 'implementation.patch').write_bytes(patch)
    snapshots = BASE / 'modules'; snapshots.mkdir(exist_ok=False)
    for name in MODULES:
        destination = snapshots / name; destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes((REPO / name).read_bytes())
    log('START', revision=producer['revision'])
    thread = threading.Thread(target=heartbeat,daemon=True); thread.start()
    stages = {}
    try:
        PHASE = 'strict-original-capture-coordinates'
        stage_start = time.monotonic()
        coordinates = bind_capture_coordinates(CAPTURE, max_bytes=2_000_000_000,
            max_lines=2_000_000, profile_uri=str(BASE / 'capture-coordinates.json'))
        (BASE / 'capture-coordinates.json').write_bytes(coordinates.payload)
        assert coordinates.run.id.value == EXPECTED_RUN
        stages[PHASE] = time.monotonic() - stage_start
        log('PHASE_END', duration_seconds=stages[PHASE], membership=len(coordinates.report['membership']))
        PHASE = 'explicit-original-composition-and-source-attachments'
        stage_start = time.monotonic()
        composition_before = receipt(COMPOSITION)
        INDEX = CompositionIndex(COMPOSITION, source_attachments=((str(ATTACHMENT),EXPECTED_ATTACHMENT),),
            attachment_budget=SourceAttachmentBudget(max_record_bytes=128_000_000,max_artifact_bytes=2_200_000_000))
        original_document = deepcopy(INDEX.document)
        original_document_sha = hashlib.sha256(canonical(original_document)).hexdigest()
        assert INDEX.inventory_file_count == 151
        stages[PHASE] = time.monotonic() - stage_start
        log('PHASE_END', duration_seconds=stages[PHASE], attachment_measurements=attachment_measurements())
        PHASE = 'same-capture-source-invocation-binding-v3'
        stage_start = time.monotonic()
        report = bind_source_invocations(INDEX, coordinates, CAPTURE / 'trace', BASE / 'bindings',
            call_budget=CallEdgeBudget(max_raw_bytes=256_000_000,max_lines=300_000,
                max_events=250_000,max_references=2_000_000),witness_mode='same_capture')
        stages[PHASE] = time.monotonic() - stage_start
        binding_metrics = attachment_measurements()
        log('PHASE_END', duration_seconds=stages[PHASE], summary=report['summary'],attachment_measurements=binding_metrics)
        PHASE = 'binding-output-denominator-audit'
        stage_start = time.monotonic()
        table, selected, binding_audit = validate_bindings(INDEX, report)
        stages[PHASE] = time.monotonic() - stage_start
        log('PHASE_END', duration_seconds=stages[PHASE],audit=binding_audit)
        PHASE = 'common-resolver-source-dispatch-association-v3'
        stage_start = time.monotonic()
        dispatch = bind_dispatch_sources(BASE / 'bindings',BRIDGE,coordinates,BASE / 'dispatch',composition_index=INDEX)
        stages[PHASE] = time.monotonic() - stage_start
        dispatch_metrics = attachment_measurements()
        log('PHASE_END',duration_seconds=stages[PHASE],summary=dispatch['summary'],
            formal_source_scope_audit=dispatch['formal_source_scope_audit'],attachment_measurements=dispatch_metrics)
        PHASE = 'published-dispatch-queries-and-selected-original-source-views'
        stage_start = time.monotonic()
        dispatch_audit = validate_dispatch(INDEX,dispatch,table)
        queries = {}
        for label, row in sorted(selected.items()):
            reference = decode(SourceDefinitionReference,row['definition'])
            definition = INDEX.resolve_definition(reference)
            view = INDEX.source_view(reference)
            assert definition == view.semantic.definitions[reference.definition]
            assert view.snapshot == reference.snapshot and view.context == reference.context
            assert view.semantic.source_atoms[reference.source.atom_id].reference == reference.source
            assert reference.source.atom_id in definition.source_atoms
            no_file_index(encode(reference))
            queries[label] = {'reference': encode(reference),'definition':encode(definition),
                'snapshot_context_source_atom_and_original_definition_verified':True,
                'source_view_metadata':view.metadata}
        (BASE / 'source-queries.json').write_bytes(canonical(queries))
        stages[PHASE] = time.monotonic() - stage_start
        assert INDEX.document == original_document
        assert hashlib.sha256(canonical(INDEX.document)).hexdigest() == original_document_sha
        assert receipt(COMPOSITION) == composition_before
        assert INDEX.source_inputs() == report['source_inputs'] == dispatch['source_inputs']
        for original in producer['modules']:
            assert receipt(Path(original['path'])) == original
        summary = {'status':'PASS','run':EXPECTED_RUN,'target_process_id':272038,
            'binding_schema_version':report['schema_version'],'dispatch_schema_version':dispatch['schema_version'],
            'binding_audit':binding_audit,'dispatch_audit':dispatch_audit,
            'original_composition_document_unchanged':True,'composition_canonical_sha256':original_document_sha,
            'formal_source_scope_audit':dispatch['formal_source_scope_audit'],
            'attachment_measurements_after_binding':binding_metrics,
            'attachment_measurements_after_dispatch':dispatch_metrics,
            'attachment_measurements_after_selected_queries':attachment_measurements(),
            'stage_seconds':stages,'elapsed_seconds':time.monotonic()-START,
            'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'source_recompiled':False,'source_reprepared':False,'target_executed':False,
            'first_stage_complete':False,'transformation_authorized':False}
        (BASE / 'summary.json').write_bytes(canonical(summary))
        log('PASS',summary=summary)
    except BaseException as error:
        log('FAILED',error_type=type(error).__name__,detail=str(error))
        raise
    finally:
        STOP.set(); thread.join()


if __name__ == '__main__':
    main()
