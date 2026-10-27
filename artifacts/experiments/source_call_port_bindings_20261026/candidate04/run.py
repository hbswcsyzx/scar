"""ONE fresh owned raw -> source -> dispatch -> SBA gate on published revision.

Adds a same-session conditional source-port consumer.
No publication, lowering, compilation, target import/execution or old source
checkpoint resume. Current observations come only from connect_current_capture.
"""
from __future__ import annotations
from copy import deepcopy
import json
import os
from pathlib import Path
import resource
import signal
import sys
import threading
import time
import traceback

from config import (HERE, ROOT, DATA_ROOT, OLD, COMPOSITION, CAPTURE, ATTACHMENT, BRIDGE,
    PROFILE, CACHE, STALE_SOURCE, EXPECTED_RUN, BUDGETS,
    FRAME_BUDGET, OPERAND_BUDGET, ROUTE_BUDGET, SOURCE_PORT_BUDGET, EXPECTED_ATTEMPTS, EXPECTED_FRAMES)
from prepare import load, check, tree
from report_archive import receipt, write_json, partitions
from audit import need, snapshot, dynamic
from port_consumer import PortConsumer

RESULT = HERE / 'result'
START = time.monotonic()
PHASE = 'startup'
LAST_API = None
LOCK = threading.Lock()
STOP = threading.Event()
OUTPUT_OVERFLOW = False


def notify(event=None, **fields):
    global LAST_API
    if type(event) is dict:
        fields = {**event, **fields}; event = fields.pop('stage', 'API_PROGRESS')
        LAST_API = event
    row = {'event': event, 'phase': PHASE, 'last_api_stage': LAST_API,
        'elapsed_s': time.monotonic() - START, 'pid': os.getpid(),
        'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **fields}
    with LOCK:
        with (HERE / 'progress.jsonl').open('a') as stream:
            stream.write(json.dumps(row, sort_keys=True) + '\n')
    small = {k: v for k, v in row.items() if k in ('event', 'phase', 'last_api_stage',
        'elapsed_s', 'pid', 'max_rss_kib', 'seconds', 'error_type', 'detail', 'observed_output_phase')}
    print(json.dumps(small, sort_keys=True), flush=True)


def heartbeat():
    global OUTPUT_OVERFLOW
    while not STOP.wait(BUDGETS['heartbeat_seconds']):
        connection = RESULT / 'connections'
        source_done = (connection / 'source/report.json').is_file()
        dispatch_done = (connection / 'dispatch/report.json').is_file()
        inferred = ('SBA' if dispatch_done else 'dispatch' if source_done else
                    'source-binder' if connection.is_dir() else 'pre-source')
        paths = list(connection.glob('*/report.json')) + list(connection.glob('*/bindings.json'))
        paths += list(connection.glob('.source-invocations-*/*.gz'))
        total_output=sum(p.stat().st_size for p in RESULT.rglob('*') if p.is_file()) if RESULT.exists() else 0
        if total_output > BUDGETS['output_total_bytes']:
            OUTPUT_OVERFLOW = True
            os.kill(os.getpid(), signal.SIGXCPU)
        notify('HEARTBEAT', meaning='liveness and output file progress only',
            observed_output_phase=inferred,
            active_artifact_sizes=[{'path': str(p), 'bytes': p.stat().st_size} for p in sorted(paths) if p.is_file()])


def sources(*, final=False):
    frozen=load(HERE/'frozen/producer.json')
    expected={row['path']:row for row in frozen['modules']+frozen['runtime']}
    imported=set()
    for module in tuple(sys.modules.values()):
        path=getattr(module,'__file__',None)
        if path and Path(path).is_file():
            p=Path(path).resolve()
            if p.suffix in ('.pyc','.pyo'):
                import importlib.util
                try:p=Path(importlib.util.source_from_cache(str(p))).resolve()
                except ValueError:pass
            imported.add(str(p))
    selected=imported|{str(p)for p in HERE.glob('*.py')}|{str(p)for p in HERE.glob('*.sh')}
    checked=[];mismatches=[]
    for path in sorted(selected):
        actual=receipt(path)
        if expected.get(path)!=actual:mismatches.append({'expected':expected.get(path),'actual':actual})
        checked.append(actual)
    if final:
        write_json(HERE/'participating-producer.json',{'actual_imports':sorted(imported),
          'checked':checked,'mismatches':mismatches,'all_imported_sources_unchanged':not mismatches,
          'consumer_worktree':str(ROOT),'unused_candidates_not_authority':True,
          'source_payload_copies':False,'historical_capture_producer_requalified':False})
    need(not mismatches,'actual participating producer/runtime differs from isolated freeze')


def fixed_inputs():
    frozen = load(HERE / 'frozen/producer.json')
    need(receipt(HERE / 'inputs.json') == frozen['fixed_inputs'], 'fixed-input declaration changed')
    need(sys.version == frozen['python'] and sys.executable == frozen['python_executable'],
        'gate Python build/executable differs from freeze')
    document = load(HERE / 'inputs.json')
    for row in document['inputs']: check(row)
    for name, names in document['directories'].items():
        need(tree(Path(name)) == names, 'fixed raw/store/publication directory membership changed')
    need(document['resume_source_directory'] is None, 'gate config attempted a source checkpoint resume')
    return document


def expired(signum, frame):
    if OUTPUT_OVERFLOW:
        raise ValueError('aggregate result output exceeds fixed 1GB ceiling')
    raise TimeoutError('fresh current gate exceeded independent wall/CPU ceiling')


def limits():
    signal.signal(signal.SIGALRM, expired); signal.signal(signal.SIGXCPU, expired)
    signal.setitimer(signal.ITIMER_REAL, BUDGETS['wall_seconds'])
    resource.setrlimit(resource.RLIMIT_CPU, (BUDGETS['cpu_seconds'], BUDGETS['cpu_seconds'] + 5))
    resource.setrlimit(resource.RLIMIT_AS, (BUDGETS['address_space_bytes'], BUDGETS['address_space_bytes']))
    resource.setrlimit(resource.RLIMIT_FSIZE, (BUDGETS['max_output_file_bytes'], BUDGETS['max_output_file_bytes']))


def main():
    global PHASE
    need(not RESULT.exists() and not (HERE / 'progress.jsonl').exists()
        and not (HERE / 'summary.json').exists() and not (HERE / 'failure.json').exists(), 'gate output must be fresh')
    thread = threading.Thread(target=heartbeat, daemon=True)
    durations = {}; connected = None; store = None; index = None
    try:
        limits(); thread.start(); notify('START', budgets=BUDGETS)
        PHASE = 'fixed-input-and-producer-revalidation'
        began = time.monotonic(); sources(); fixed = fixed_inputs()
        from scar.analysis.program_composition import CompositionIndex
        from scar.analysis.source_attachments import SourceAttachmentBudget
        from scar.analysis.current_source_evidence import connect_current_capture
        from scar.analysis.code_witness import CodeWitnessStore, CodeWitnessBudget
        from scar.analysis.source_body_access import SourceBodyAccess
        from scar.trace.capture_coordinates import bind_capture_coordinates
        from scar.ir.program.call_edges import CallEdgeBudget
        from scar.ir.program.call_operands import CallOperandBudget
        from scar.ir.program.call_operand_routes import OperandRouteBudget
        from scar.ir.program.source_call_bindings import SourceCallPortBudget
        sources(); RESULT.mkdir(exist_ok=False)
        durations[PHASE] = time.monotonic() - began; notify('PHASE_END', seconds=durations[PHASE])
        PHASE = 'all-source-table-body-physical-preflight'
        began = time.monotonic()
        from body_preflight import body_check
        body_inputs = body_check()
        write_json(HERE / 'body-preflight-at-run.json', body_inputs)
        need(not body_inputs['missing'] and body_inputs['status'] == 'PASS_ALL_SOURCE_TABLE_PHYSICAL_REFS_ONLY',
            'full source-table body physical dependency preflight failed before composition read')
        durations[PHASE] = time.monotonic() - began; notify('PHASE_END', seconds=durations[PHASE])
        PHASE = 'capture-local-closed-namespace-preflight'
        began = time.monotonic()
        from capture_preflight import check_capture
        capture_check = check_capture()
        write_json(HERE / 'capture-preflight-at-run.json', capture_check)
        need(not capture_check['missing'] and capture_check['status'] == 'PASS_PHYSICAL_NAMESPACE_AND_STORED_SHA_ONLY',
            'capture physical namespace preflight failed before composition read')
        durations[PHASE] = time.monotonic() - began; notify('PHASE_END', seconds=durations[PHASE])
        PHASE = 'public-read-of-official-858-snapshot'
        began = time.monotonic()
        index = CompositionIndex(COMPOSITION, source_attachments=((str(ATTACHMENT), receipt(ATTACHMENT)['sha256']),),
            attachment_budget=SourceAttachmentBudget(max_record_bytes=128_000_000, max_artifact_bytes=2_200_000_000))
        origin = deepcopy(index.original_code_source_origin())
        old_report = load(OLD / 'result/source/report.json')
        need(origin['inventory'] == old_report['inventory'], 'strict original compiler inventory differs')
        changed = snapshot(index)
        ancestor = index.require_source_membership_ancestor(old_report['composition_canonical_sha256'],
            old_report['inventory'], max_depth=BUDGETS['ancestry_depth'],
            max_total_decoded_bytes=BUDGETS['ancestry_decoded_bytes'])
        write_json(HERE / 'ancestor.json', ancestor)
        before = index.source_membership_query_counts()
        try:
            index.require_source_membership_ancestor('0' * 64, old_report['inventory'])
        except ValueError as error:
            need('requested ancestor is not in the bounded exact source chain' in str(error),
                'wrong ancestor failed for an unrelated reason')
            write_json(HERE / 'wrong-ancestor-rejected.json', {'type': type(error).__name__, 'detail': str(error),
                'before': before, 'after': index.source_membership_query_counts()})
        else: raise ValueError('nonexistent ancestor unexpectedly accepted')
        durations[PHASE] = time.monotonic() - began; notify('PHASE_END', seconds=durations[PHASE])
        PHASE = 'original-coordinate-profile-membership'
        began = time.monotonic()
        coordinates = bind_capture_coordinates(CAPTURE, max_bytes=BUDGETS['coordinate_bytes'],
            max_lines=BUDGETS['coordinate_lines'], profile_uri=str(PROFILE))
        need(coordinates.run.id.value == EXPECTED_RUN and coordinates.payload == PROFILE.read_bytes(),
            'original coordinate profile identity/bytes changed')
        (RESULT / 'capture-coordinates.json').write_bytes(coordinates.payload)
        durations[PHASE] = time.monotonic() - began; notify('PHASE_END', seconds=durations[PHASE])
        PHASE = 'readonly-store-and-stale-checkpoint-header'
        began = time.monotonic()
        store = CodeWitnessStore(CACHE, create=False, compile_missing=False,
            budget=CodeWitnessBudget(max_compile_keys=20), progress=notify)
        try:
            SourceBodyAccess(index, STALE_SOURCE, coordinates, store)
        except ValueError as error:
            need('source report composition/inventory receipt differs' in str(error),
                'old snapshot checkpoint failed beyond its expected header boundary')
            write_json(HERE / 'old-checkpoint-rejected.json', {'type': type(error).__name__, 'detail': str(error),
                'old_report': receipt(STALE_SOURCE / 'report.json'), 'raw_read_performed_by_this_check': False,
                'historical_bad_graph_typed': False, 'resume_attempt_executed': False})
        else: raise ValueError('old snapshot checkpoint unexpectedly accepted')
        durations[PHASE] = time.monotonic() - began; notify('PHASE_END', seconds=durations[PHASE])
        PHASE = 'fresh-owned-raw-source-dispatch-SBA'
        began = time.monotonic()
        port_consumer = PortConsumer(RESULT / 'source-ports')
        connected = connect_current_capture(index, coordinates, CAPTURE / 'trace', RESULT / 'connections',
            previous_source_directory=OLD / 'result/source',
            previous_report_sha256=receipt(OLD / 'result/source/report.json')['sha256'],
            previous_bindings_sha256=receipt(OLD / 'result/source/bindings.json')['sha256'],
            previous_producer=(OLD / 'frozen/producer.json', receipt(OLD / 'frozen/producer.json')['sha256']),
            previous_participating_producer=(OLD / 'participating-producer.json', receipt(OLD / 'participating-producer.json')['sha256']),
            code_witnesses=store, dispatch_bridge=BRIDGE, frame_budget=CallEdgeBudget(**FRAME_BUDGET),
            operand_budget=CallOperandBudget(**OPERAND_BUDGET), route_budget=OperandRouteBudget(**ROUTE_BUDGET),
            include_environments=True, progress=notify,
            source_port_consumer=port_consumer, source_port_budget=SourceCallPortBudget(**SOURCE_PORT_BUDGET))
        durations[PHASE] = time.monotonic() - began
        need(connected['source_checkpoint'] is None and Path(connected['source_directory']) == RESULT / 'connections/source',
            'source binder did not produce a fresh current snapshot output')
        need(connected['reader_counts']['source_binder_runs'] == 1
            and connected['reader_counts']['completed_source_checkpoints'] == 0, 'unexpected checkpoint/binder activity')
        proof = connected['proof_reuse']
        need(proof['rule'] == 'SAME_RUN_STATIC_SOURCE_MEMBERSHIP_ANCESTRY_V2' and proof['rule_version'] == 2
            and proof['source_membership_ancestry'] == ancestor and proof['static_membership_only'] is True
            and proof['old_body_or_activation_reused'] is False, 'private factory did not install exact ancestry V2')
        need(index.static_source_proof_receipt() == proof
            and connected['source_report']['same_run_source_proof'] == proof
            and connected['source_report']['source_inputs'] == index.source_inputs(), 'new source output proof differs')
        write_json(HERE / 'connections-receipt.json', {'reader_counts': connected['reader_counts'],
            'proof_reuse': proof, 'source_report': receipt(RESULT / 'connections/source/report.json'),
            'source_bindings': receipt(RESULT / 'connections/source/bindings.json'),
            'fresh_source_binder_run': True, 'source_checkpoint_resumed': False})
        notify('PHASE_END', seconds=durations[PHASE], reader_counts=connected['reader_counts'])
        PHASE = 'current-output-denominator-and-namespace-audit'
        began = time.monotonic(); report = connected['operand_report']
        need(len(report.operands.attempts) == EXPECTED_ATTEMPTS and len(report.frame_model.edges) == EXPECTED_FRAMES,
            'original complete attempt/frame denominator differs')
        port_result = port_consumer.compare_legacy(report.routing)
        write_json(HERE / 'source-port-audit.json', port_result)
        document = report.to_dict()  # Exactly one conversion of the original report.
        current, scope = dynamic(index, connected, document, changed, RESULT)
        durations[PHASE] = time.monotonic() - began; notify('PHASE_END', seconds=durations[PHASE])
        PHASE = 'bounded-original-report-export'
        began = time.monotonic(); archive = partitions(document, RESULT / 'analysis')
        del document
        durations[PHASE] = time.monotonic() - began; notify('PHASE_END', seconds=durations[PHASE])
        PHASE = 'final-input-and-participating-producer-check'
        began = time.monotonic(); fixed_inputs()
        need(index.original_code_source_origin() == origin, 'original compiler-origin dictionary changed')
        need(store.counts['compile_attempts'] == 0 and store.counts['source_bytes_read'] == 0,
            'readonly code witness attempted compilation or target source reading')
        need(sum(p.stat().st_size for p in RESULT.rglob('*') if p.is_file()) <= BUDGETS['output_total_bytes'],
            'aggregate result output exceeds fixed 1GB ceiling')
        sources(final=True); durations[PHASE] = time.monotonic() - began
        summary = {'status': 'PASS_WITH_OPEN_MODEL_OBLIGATIONS', 'run': EXPECTED_RUN,
            'published_snapshot': receipt(COMPOSITION), 'current': current,
            'source_ports': port_result, 'source_port_artifact': receipt(RESULT / 'source-ports/model.json.gz'),
            'source_port_consumer_calls': port_consumer.calls, 'isolated_consumer_worktree': str(ROOT), 'original_data_root': str(DATA_ROOT),
            'reference_scope_audit': receipt(HERE / 'reference-scope-audit.json'),
            'reader_counts': connected['reader_counts'], 'proof_reuse': proof,
            'owned_ancestor_reader_counts': index.source_membership_query_counts(),
            'code_witness_activity': store.counts, 'canonical_report_sha256': archive['canonical_document_sha256'],
            'canonical_report_bytes': archive['canonical_document_bytes'], 'stages_seconds': durations,
            'elapsed_seconds': time.monotonic() - START,
            'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'source_checkpoint_resumed': False, 'publisher_reexecuted': False,
            'source_reprepared': False, 'source_lowered': False, 'code_compiled': False,
            'target_executed': False, 'first_stage_complete': False, 'transformation_authorized': False}
        write_json(HERE / 'summary.json', summary); notify('PASS', summary_receipt=receipt(HERE / 'summary.json'))
    except BaseException as error:
        failure = {'type': type(error).__name__, 'detail': str(error), 'phase': PHASE, 'last_api_stage': LAST_API,
            'traceback': traceback.format_exc(), 'elapsed_s': time.monotonic() - START,
            'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'partial_outputs_retained': True, 'automatic_retry_or_resume': False,
            'reader_counts': connected['reader_counts'] if connected else None,
            'code_witness_activity': store.counts if store else None,
            'owned_ancestor_reader_counts': index.source_membership_query_counts() if index else None,
            'first_stage_complete': False, 'transformation_authorized': False}
        write_json(HERE / 'failure.json', failure)
        notify('FAILED', error_type=type(error).__name__, detail=str(error))
        if not (HERE / 'participating-producer.json').exists():
            try: sources(final=True)
            except BaseException as archive_error:
                write_json(HERE / 'failure-producer-archive-error.json', {'type': type(archive_error).__name__, 'detail': str(archive_error)})
        raise
    finally:
        STOP.set()
        if thread.is_alive(): thread.join(timeout=2)
        signal.setitimer(signal.ITIMER_REAL, 0)


if __name__ == '__main__': main()
