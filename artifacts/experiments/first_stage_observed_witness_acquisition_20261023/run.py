"""ONE observed-only compiler acquisition; compilation does not execute code."""
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
STARTED = time.perf_counter()
log = (HERE / 'progress.jsonl').open('x', buffering=1)
def save(name, document):
    path = HERE / name
    with path.open('x') as stream:
        json.dump(document, stream, indent=2); stream.write('\n')
def receipt(path):
    path = Path(path).resolve(); raw = path.read_bytes()
    return {'path': str(path), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}
def progress(event):
    log.write(json.dumps({'elapsed_s': time.perf_counter() - STARTED,
        'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **event}) + '\n')
def expired(signum, frame):
    raise TimeoutError('independent ONE acquisition gate exceeded wall180s')
signal.signal(signal.SIGALRM, expired)
signal.setitimer(signal.ITIMER_REAL, 180.0)

old_before = None
try:
    candidate_sources = {str(path.resolve()): receipt(path)
                         for path in sorted((ROOT / 'scar').rglob('*.py'))}
    save('source-candidates-before.json', list(candidate_sources.values()))
    from preflight import checked_plan, PLAN
    from scar.analysis.compiler_witness_archives import (
        CompilerWitnessArchives, CompilerArchiveBudget, ObservedAcquisitionBudget,
        acquire_observed_witnesses,
    )
    from scar.analysis.code_witness import CodeWitnessStore, CodeWitnessBudget
    from scar.analysis.program_composition import CompositionIndex
    from scar.ir.program.call_edges import CapturedCode, CodeSourceLink
    from scar.ir.program.inventory import DefinitionInventory
    from scar.ir.record_codec import decode, encode
    from scar.trace.code_snapshot import describe_code

    module = ROOT / 'scar/analysis/compiler_witness_archives.py'
    if receipt(module)['sha256'] != '8b7f9b3875098bd545775f9937d9a89c07ff4136fcdcbf6869fc228583f2c0a0':
        raise ValueError('approved compiler acquisition producer differs')
    manifest, tables, table_receipts = checked_plan()
    selected = [row for row in tables['bodies']
                if row['metadata_status'] == 'CODE_WITNESS_MODULE_VARIANT_MISSING']
    if not 0 < len(selected) <= 10 or len({row['file_index'] for row in selected}) > 8:
        raise ValueError('mechanically selected cohort exceeds independent definitions/files budget')
    source_paths = {row['snapshot']['path'] for row in selected}
    target_exec_attempts = []
    def audit(event, arguments):
        if event == 'exec' and arguments and getattr(arguments[0], 'co_filename', None) in source_paths:
            target_exec_attempts.append(arguments[0].co_filename)
            raise RuntimeError('target code execution is prohibited in compiler witness acquisition')
    sys.addaudithook(audit)

    composition_path = HERE.parent / 'first_stage_source_publication_current_20261023/result/composition/index.json.gz'
    attachment_declarations = tuple((row['report']['artifact']['uri'], row['report']['artifact']['sha256'])
                                   for row in manifest['document']['composition_inputs']['attachments'])
    composition = CompositionIndex(composition_path, source_attachments=attachment_declarations)
    if composition.source_inputs() != manifest['document']['composition_inputs']:
        raise ValueError('actual composition inputs differ from full original worklist')
    progress({'stage': 'COMPOSITION_AND_PLAN_VERIFIED', 'selected_bodies': len(selected),
              'selected_files': len({row['file_index'] for row in selected})})

    old_directory = HERE.parent / 'first_stage_partitioned_operand_routes_20261023/result/code-witnesses'
    def old_snapshot():
        return [receipt(path) for path in sorted(old_directory.iterdir()) if path.is_file()]
    old_before = old_snapshot(); save('old-archive-before.json', old_before)
    old_reader_budget = CodeWitnessBudget(max_compile_keys=20)
    archives = CompilerWitnessArchives(((old_directory, receipt(old_directory / 'manifest.json')['sha256']),),
        store_budget=old_reader_budget,
        budget=CompilerArchiveBudget(max_archives=1, max_total_modules=20, max_total_sources=32,
                                    max_declared_payload_bytes=256_000_000))
    old_receipt = archives.receipts()[0]
    old_store = archives.store_for(old_receipt)
    definition_records = [decode(DefinitionInventory, row['definition']) for row in selected]
    composition.prefetch_definition_references(tuple((row['file_index'], definition.id)
        for row, definition in zip(selected, definition_records)))
    references, source_inputs = [], []
    for row, definition in zip(selected, definition_records):
        reference = composition.definition_reference(row['file_index'], definition.id)
        actual = composition.resolve_definition(reference)
        if (encode(reference.snapshot) != row['snapshot'] or encode(reference.context) != row['context']
                or reference.definition != definition.id or reference.source != definition.source
                or actual.id != definition.id):
            raise ValueError('qualified source/definition/context differs from original worklist')
        references.append(reference)
        source_inputs.append({'body_key': row['body_key'], 'body_locator': row['body_locator'],
            'definition_reference': encode(reference), 'current_calls': row['current_calls'],
            'current_groups': row['current_groups'], 'original_code_variants': row['code_variants']})
    save('selected-qualified-definitions.json', source_inputs)
    writer_budget = CodeWitnessBudget(max_compile_keys=8, max_source_files=8,
        max_source_bytes=2_000_000, max_module_bytes=2_000_000, max_archive_bytes=32_000_000)
    acquisition_budget = ObservedAcquisitionBudget(max_definitions=10, max_requests=10,
        max_attempts=10, max_elapsed_seconds=180, max_record_bytes=2_000_000, max_report_bytes=16_000_000)
    producer = {'head_at_start': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'pid': os.getpid(), 'runner': receipt(__file__), 'preflight': receipt(HERE / 'preflight.py'),
        'approved_acquirer': receipt(module), 'composition': receipt(composition_path),
        'plan_manifest': receipt(PLAN / 'manifest.json'), 'plan_sha256': manifest['plan_sha256'],
        'selected_qualified_definitions': receipt(HERE / 'selected-qualified-definitions.json'),
        'old_archive': old_receipt, 'source_prepare': 0, 'target_executed': False}
    save('producer.json', producer)
    save('inputs.json', {'plan_tables': table_receipts, 'plan_manifest': receipt(PLAN / 'manifest.json'),
        'composition': receipt(composition_path), 'composition_inputs': composition.source_inputs(),
        'current_source_files': [receipt(path) for path in sorted(source_paths)],
        'qualified_definition_input': receipt(HERE / 'selected-qualified-definitions.json')})
    save('budgets.json', {'old_reader': asdict(old_reader_budget), 'new_writer': asdict(writer_budget),
        'acquisition': asdict(acquisition_budget), 'independent_total_gate_wall_seconds': 180})
    progress({'stage': 'ACQUIRE_OBSERVED_WITNESSES', 'status': 'BEGIN'})
    result = acquire_observed_witnesses(composition, tuple(references), archives, HERE / 'result',
        producer=producer, budget=acquisition_budget, store_budget=writer_budget, progress=progress)
    progress({'stage': 'ACQUIRE_OBSERVED_WITNESSES', 'status': result['status']})

    # Independent bounded reopened reader, using only requests the public API
    # rederived from the original observed seed and qualified source references.
    readonly = CodeWitnessStore(HERE / 'result/archive', budget=writer_budget)
    if readonly.receipt() != result['archive']:
        raise ValueError('new immutable archive differs before independent read-only replay')
    acquired_plan = json.loads((HERE / 'result/plan.json').read_text())
    attempts = {row['request_id']: row for row in result['attempts']}
    descriptor_checks = []
    for request in acquired_plan['requests']:
        attempt = attempts[request['request_id']]
        if attempt['status'] != 'ACQUIRED_VERIFIED':
            descriptor_checks.append({'request_id': request['request_id'], 'status': attempt['status'],
                                      'replayed': False})
            continue
        captured = decode(CapturedCode, request['captured'])
        link = decode(CodeSourceLink, request['source_link'])
        level = request['preferred_compile_key']['optimize']
        if level != min(link.optimize_levels):
            raise ValueError('preferred compile key does not use the lowest recorded matching optimize level')
        code, witness = readonly.resolve(captured, link.snapshot, (level,), allow_compile=False)
        if describe_code(code) != encode(captured) or witness != attempt['witness']:
            raise ValueError('independent readonly complete descriptor/path differs')
        descriptor_checks.append({'request_id': request['request_id'], 'captured_key': captured.key,
                                  'verified': True, 'witness': witness})
    save('independent-readonly-replay.json', {'store': readonly.receipt(), 'counts': dict(readonly.counts),
        'checks': descriptor_checks, 'compile_permitted': False, 'target_executed': False})
    old_after = old_snapshot(); save('old-archive-after.json', old_after)
    if old_after != old_before:
        raise ValueError('historical store manifest/payload bytes changed')
    participating = []
    archive = HERE / 'participating-source-evidence'; archive.mkdir()
    for module_object in tuple(sys.modules.values()):
        path = getattr(module_object, '__file__', None)
        if not path:
            continue
        path = Path(path).resolve()
        if not path.is_relative_to(ROOT / 'scar') or path.suffix != '.py':
            continue
        current = receipt(path)
        if candidate_sources.get(str(path)) != current:
            raise ValueError('participating imported source drifted: ' + str(path))
        if current not in participating:
            participating.append(current)
            (archive / (current['sha256'] + '.py-source')).write_bytes(path.read_bytes())
    save('participating-producer.json', {'sources': participating, 'all_bytes_unchanged': True,
        'git_head_change_alone_is_not_source_drift': True})
    summary = {'schema': 'scar.observed-witness-acquisition-gate', 'schema_version': 1,
        'status': result['status'], 'bodies': len(tables['bodies']), 'groups': len(tables['groups']),
        'calls': sum(row['current_calls'] for row in tables['groups']),
        'selected_definitions': len(references), 'selected_files': len(source_paths),
        'selected_current_calls': sum(row['current_calls'] for row in selected),
        'writer_counts': result['writer_counts'], 'internal_read_only_counts': result['read_only_counts'],
        'independent_read_only_counts': dict(readonly.counts), 'old_reader_counts': dict(old_store.counts),
        'published_compile_keys': result['unique_published_compile_keys'],
        'statuses': {name: sum(row['status'] == name for row in result['attempts'])
                     for name in sorted({row['status'] for row in result['attempts']})},
        'old_archive_bytes_unchanged': True, 'target_exec_attempts': target_exec_attempts,
        'new_body_graphs': 0, 'current_run_coverage_changed': False, 'source_prepared': False,
        'observed_descriptors_reproduced_not_runtime_identity': True,
        'elapsed_s': time.perf_counter() - STARTED,
        'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    save('summary.json', summary); progress({'stage': 'FINISHED', **summary})
    print(json.dumps(summary))
except BaseException as error:
    if old_before is not None:
        try:
            after = old_snapshot()
            save('old-archive-after-failure.json', after)
        except BaseException:
            pass
    failure = {'type': type(error).__name__, 'detail': str(error), 'traceback': traceback.format_exc(),
               'elapsed_s': time.perf_counter() - STARTED, 'retained_all_partial_outputs': True}
    save('gate-failure.json', failure); progress({'stage': 'FAILED', **failure})
    raise
finally:
    signal.setitimer(signal.ITIMER_REAL, 0)
