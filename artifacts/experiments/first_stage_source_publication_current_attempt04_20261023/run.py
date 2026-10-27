"""Formal publication and current-capture connection, with retained frontiers.

No target execution, source preparation, new compilation or optimization.
The public pipeline owns its raw reader; this runner cannot supply observations.
"""
from __future__ import annotations

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

from prepare import (HERE, ROOT, OLD, CAPTURE, COMPOSITION, ATTACHMENT, BRIDGE,
                     COORDINATES, CACHE, PROGRAMS, EXPECTED_RUN, load)
from report_archive import partitions, receipt, write_json


RESULT = HERE / 'result'
START = time.monotonic()
PHASE = 'startup'
LOCK = threading.Lock()
STOP = threading.Event()
INDEX = None


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode()


def notify(event=None, **fields):
    if type(event) is dict:
        fields = {**event, **fields}
        event = fields.pop('stage', 'API_PROGRESS')
    # Progress APIs may carry a complete receipt. Store it in the log, while
    # routine stdout stays bounded and never prints the whole report.
    row = {'event': event, 'phase': PHASE, 'elapsed_s': time.monotonic() - START,
           'pid': os.getpid(), 'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
           **fields}
    with LOCK:
        with (HERE / 'progress.jsonl').open('a') as stream:
            stream.write(json.dumps(row, sort_keys=True) + '\n')
    small = {key: value for key, value in row.items()
             if key in ('event', 'phase', 'elapsed_s', 'pid', 'max_rss_kib',
                        'seconds', 'error_type', 'detail')}
    print(json.dumps(small, sort_keys=True), flush=True)


def heartbeat():
    while not STOP.wait(20):
        notify('HEARTBEAT', meaning='process liveness only')


def exact_sources(*, final=False):
    frozen = load(HERE / 'frozen/producer.json')
    expected = {row['path']: row for row in frozen['modules']}
    imported = {str(Path(module.__file__).resolve()) for module in tuple(sys.modules.values())
                if getattr(module, '__file__', None)
                and str(Path(module.__file__).resolve()).startswith(str(ROOT / 'scar') + '/')}
    selected = imported | {str(path) for path in HERE.glob('*.py')} | {str(HERE / 'run.sh')}
    checked = []
    for path in sorted(selected):
        if path not in expected or receipt(path) != expected[path]:
            raise ValueError('participating producer differs from pre-run freeze: ' + path)
        checked.append(expected[path])
    if final:
        out = HERE / 'participating-source-evidence'
        out.mkdir(exist_ok=False)
        for row in checked:
            target = out / (row['sha256'] + '.py-source')
            if not target.exists():
                shutil.copyfile(row['path'], target)
        write_json(HERE / 'participating-producer.json', {
            'actual_imports': sorted(imported), 'checked': checked,
            'all_imported_sources_unchanged': True, 'unused_candidates_not_authority': True,
        })


def publication_audit(base, current):
    """Compare original graph references, not reconstructed same-looking IDs."""
    from scar.analysis.inventory_partitions import InventoryPartitions
    parts = InventoryPartitions(current.document['inventory']['path'])
    old, new = base.document, current.document
    assert len(old['files']) == len(new['files']) == 151
    changes, retained, added = [], [], []
    for index, (before, after) in enumerate(zip(old['files'], new['files'], strict=True)):
        assert before['snapshot'] == after['snapshot'] and before['context'] == after['context']
        assert len(before['bodies']) == len(after['bodies'])
        if before != after:
            changes.append(index)
        for j, (a, b) in enumerate(zip(before['bodies'], after['bodies'], strict=True)):
            if a['namespace'] is not None:
                assert b['namespace'] == a['namespace']
                for field in ('graph_locator', 'metadata_locator', 'program_canonical_sha256',
                              'program_schema_version', 'root', 'status'):
                    assert a[field] == b[field], (field, index, j)
                retained.append((index, j))
            elif b['namespace'] is not None:
                added.append((index, j))
    program_definitions = {load(path)['interface']['definition']['wire']: path for path in PROGRAMS}
    found = {}
    for i, j in added:
        body = new['files'][i]['bodies'][j]
        assert body['definition'] in program_definitions
        original_path = program_definitions[body['definition']]
        document = load(original_path)
        namespace = body['namespace']
        raw = gzip.decompress(original_path.read_bytes())
        assert namespace['artifact']['uri'] == str(original_path)
        assert namespace['artifact']['decoded_sha256'] == hashlib.sha256(raw).hexdigest()
        assert namespace['record_pointer'] == '#/graph'
        assert body['graph_locator']['pointer'] == '#/graph'
        assert body['graph_locator']['artifact']['representation'] == 'scar.source-program/5'
        typed = parts.typed_body(i, j)
        graph = typed.body.graph
        assert graph.root.wire == document['graph']['root']['wire']
        assert set(value.id.wire for value in graph.operations) == {
            row['id']['wire'] for row in document['graph']['operations']}
        assert typed.namespace == namespace
        assert typed.language is not None
        found[body['definition']] = {'file_index': i, 'body_index': j,
            'namespace': namespace, 'graph_locator': body['graph_locator'],
            'operations': len(graph.operations), 'source_program': receipt(original_path)}
    assert len(changes) == 1 and len(retained) == 840 and len(added) == 2
    assert set(found) == set(program_definitions)
    assert current.code_source_origin() == base.code_source_origin()
    result = {'changed_source_indices': changes, 'unchanged_source_projections': 151 - len(changes),
        'original_graph_references_retained': len(retained), 'new_graphs': found,
        'original_static_code_source_origin_unchanged': True,
        'new_construction_cost_inferred_from_graph_size': False,
        'whole_program_established': False}
    write_json(HERE / 'publication-audit.json', result)
    return result


def dynamic_audit(source, markers, operand_report, new_definitions, source_directory):
    previous = load(OLD / 'result/source/bindings.json')['bindings']
    source_directory = Path(source_directory)
    current = load(source_directory / 'bindings.json')['bindings']
    before = {(row['process_id'], row['code']): row for row in previous}
    after = {(row['process_id'], row['code']): row for row in current}
    assert set(before) == set(after) and len(after) == 817
    promoted = {}
    for key, row in after.items():
        old = before[key]
        assert row['entered_invocations'] == old['entered_invocations']
        assert row['definition'] == old['definition']
        assert row['code_capture'] == old['code_capture']
        if old['body'] is None and row['body'] is not None:
            definition = row['definition']['definition']['wire']
            assert definition in new_definitions
            assert row['body']['namespace'] == new_definitions[definition]['namespace']
            promoted[definition] = {'current_calls': row['entered_invocations'], 'code': row['code']}
        elif old['body'] is not None:
            assert row['body'] is not None and row['body']['namespace'] == old['body']['namespace']
        else:
            assert row['body'] is None
    assert set(promoted) == set(new_definitions)
    actual = Counter((edge.entry.invocation.process_id, edge.entry.code)
                     for edge in operand_report.frame_model.edges)
    assert actual == Counter({key: row['entered_invocations'] for key, row in after.items()})
    assert sum(actual.values()) == len(operand_report.frame_model.exits) == 100438
    assert len(operand_report.frame_model.codes) == 855
    assert len(operand_report.operands.events) == 312812
    assert operand_report.environments['summary']['events'] == 16403
    invocation_count = activation_count = 0
    with gzip.open(source_directory / 'invocations.jsonl.gz', 'rb') as stream:
        for raw in stream:
            row = json.loads(raw)
            invocation_count += 1
            if row['region_activation'] is not None:
                activation_count += 1
                assert row['region_activation']['entry']['run']['value'] == EXPECTED_RUN
    assert invocation_count == sum(actual.values())
    marker_count = marker_slots = 0
    marker_statuses = Counter()
    with gzip.open(RESULT / 'connections/dispatch/associations.jsonl.gz', 'rb') as stream:
        for raw in stream:
            row = json.loads(raw)
            marker_count += 1
            marker_slots += len(row['qualified_slot_path_indices'])
            marker_statuses[row['status']] += 1
            assert row['direct_callsite_established'] is False
    assert (marker_count, marker_slots) == (79592, 109288)
    assert source['run']['id']['value'] == EXPECTED_RUN
    result = {'current_groups': len(actual), 'current_invocations': invocation_count,
        'current_activations': activation_count, 'promoted_bodies': promoted,
        'current_body_groups': sum(row['body'] is not None for row in current),
        'current_body_calls': sum(row['entered_invocations'] for row in current if row['body'] is not None),
        'binding_statuses': dict(Counter(row['status'] for row in current)),
        'markers': marker_count, 'marker_slots': marker_slots, 'marker_statuses': dict(marker_statuses),
        'entry_parameter_occurrences': len(operand_report.entry_parameters),
        'operand_route_summary': operand_report.routing.summary(),
        'environment_summary': operand_report.environments['summary'],
        'new_counts_derived_from_current_raw': True,
        'logical_contents_world_effects_or_readiness_established': False}
    write_json(HERE / 'dynamic-audit.json', result)
    return result


def main():
    global PHASE, INDEX
    exact_sources()
    frozen = load(HERE / 'frozen/producer.json')
    assert receipt(HERE / 'inputs.json') == frozen['fixed_inputs']
    for row in frozen['additional_inputs']:
        assert receipt(row['path']) == row
    RESULT.mkdir(exist_ok=False)
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    durations = {}
    try:
        from scar.analysis.program_composition import CompositionIndex, compose_source_publication
        from scar.analysis.source_attachments import SourceAttachmentBudget
        from scar.analysis.source_program_publication import publish_source_programs
        from scar.analysis.current_source_evidence import connect_current_capture
        from scar.analysis.code_witness import CodeWitnessStore, CodeWitnessBudget
        from scar.trace.capture_coordinates import bind_capture_coordinates
        from scar.ir.program.call_edges import CallEdgeBudget
        from scar.ir.program.call_operands import CallOperandBudget
        from scar.ir.program.call_operand_routes import OperandRouteBudget
        exact_sources()
        PHASE = 'parent-coordinate-membership-revalidation'
        start = time.monotonic()
        coordinates = bind_capture_coordinates(CAPTURE, max_bytes=2_000_000_000, max_lines=2_000_000,
            profile_uri=str(OLD / 'result/capture-coordinates.json'))
        assert coordinates.run.id.value == EXPECTED_RUN
        assert coordinates.payload == (OLD / 'result/capture-coordinates.json').read_bytes()
        (RESULT / 'capture-coordinates.json').write_bytes(coordinates.payload)
        durations[PHASE] = time.monotonic() - start
        notify('PHASE_END', seconds=durations[PHASE])
        attachment_sha = receipt(ATTACHMENT)['sha256']
        base = CompositionIndex(COMPOSITION, source_attachments=((str(ATTACHMENT), attachment_sha),),
            attachment_budget=SourceAttachmentBudget(max_record_bytes=128_000_000, max_artifact_bytes=2_200_000_000))
        original = deepcopy(base.document)
        cache_before = receipt(CACHE / 'manifest.json')
        store = CodeWitnessStore(CACHE, create=False, compile_missing=False,
            budget=CodeWitnessBudget(max_compile_keys=20), progress=notify)
        PHASE = 'public-read-of-published-source-checkpoint'
        start = time.monotonic()
        parent_result = HERE.parent / 'first_stage_source_publication_current_20261023/result'
        publication = {'reused_published_manifest': receipt(parent_result / 'publication/manifest.json'),
                       'publisher_reexecuted': False}
        composition = load(parent_result / 'composition/summary.json')
        INDEX = CompositionIndex(parent_result / 'composition/index.json.gz',
            source_attachments=((str(ATTACHMENT), attachment_sha),),
            attachment_budget=SourceAttachmentBudget(max_record_bytes=128_000_000, max_artifact_bytes=2_200_000_000))
        static = publication_audit(base, INDEX)
        durations[PHASE] = time.monotonic() - start
        notify('PHASE_END', seconds=durations[PHASE], publication=publication, composition=composition)
        PHASE = 'same-retained-run-owned-reader-connections'
        start = time.monotonic()
        completed_source = HERE.parent / 'first_stage_source_publication_current_attempt02_20261023/result/connections/source'
        connected = connect_current_capture(INDEX, coordinates, CAPTURE / 'trace', RESULT / 'connections',
            resume_source_directory=completed_source,
            resume_source_report_sha256=receipt(completed_source / 'report.json')['sha256'],
            resume_source_bindings_sha256=receipt(completed_source / 'bindings.json')['sha256'],
            previous_source_directory=OLD / 'result/source',
            previous_report_sha256=receipt(OLD / 'result/source/report.json')['sha256'],
            previous_bindings_sha256=receipt(OLD / 'result/source/bindings.json')['sha256'],
            previous_producer=(OLD / 'frozen/producer.json', receipt(OLD / 'frozen/producer.json')['sha256']),
            previous_participating_producer=(OLD / 'participating-producer.json', receipt(OLD / 'participating-producer.json')['sha256']),
            code_witnesses=store, dispatch_bridge=BRIDGE,
            frame_budget=CallEdgeBudget(max_raw_bytes=256_000_000, max_lines=300_000, max_events=250_000,
                max_references=2_000_000, max_source_files=256, max_source_bytes=16_000_000),
            operand_budget=CallOperandBudget(), route_budget=OperandRouteBudget(),
            include_environments=True, progress=notify)
        durations[PHASE] = time.monotonic() - start
        report = connected['operand_report']
        current = dynamic_audit(connected['source_report'], connected['dispatch_report'], report, static['new_graphs'], connected['source_directory'])
        notify('PHASE_END', seconds=durations[PHASE], current=current,
               reader_counts=connected['reader_counts'], proof_reuse=connected['proof_reuse'])
        PHASE = 'bounded-original-report-export'
        start = time.monotonic()
        archive = partitions(report.to_dict(), RESULT / 'analysis')
        durations[PHASE] = time.monotonic() - start
        assert base.document == original
        assert receipt(CACHE / 'manifest.json') == cache_before
        assert store.counts['compile_attempts'] == store.counts['source_bytes_read'] == 0
        exact_sources(final=True)
        summary = {'status': 'PASS_WITH_OPEN_MODEL_OBLIGATIONS', 'run': EXPECTED_RUN,
            'publication': static, 'current': current, 'reader_counts': connected['reader_counts'],
            'proof_reuse': connected['proof_reuse'], 'code_witness_activity': store.counts,
            'canonical_report_sha256': archive['canonical_document_sha256'],
            'canonical_report_bytes': archive['canonical_document_bytes'], 'stages_seconds': durations,
            'elapsed_seconds': time.monotonic() - START,
            'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'source_reprepared': False, 'target_executed': False, 'code_compiled': False,
            'first_stage_complete': False, 'transformation_authorized': False}
        write_json(HERE / 'summary.json', summary)
        notify('PASS', summary_receipt=receipt(HERE / 'summary.json'))
    except BaseException as error:
        failure = {'type': type(error).__name__, 'detail': str(error), 'phase': PHASE,
                   'elapsed_s': time.monotonic() - START, 'first_stage_complete': False}
        write_json(HERE / 'failure.json', failure)
        notify('FAILED', error_type=type(error).__name__, detail=str(error))
        raise
    finally:
        STOP.set()
        thread.join()


if __name__ == '__main__':
    main()
