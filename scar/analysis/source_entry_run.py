"""Offline source-entry stage over pinned existing dependency products.

The workflow document is navigation. Source graphs, code witnesses and body
artifacts keep their original producers; JSON never restores a live owner.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import os
import signal
import threading
import time

from scar.analysis.model_run import (
    SCHEMA, _PinnedModelInputs, _canonical, _dependency_base, _interrupt,
    _publish, _regular_files, _safe, _sha, _update_navigation, _verify_dependency_scope,
)


@dataclass(frozen=True)
class SourceEntryRunBudget:
    max_metadata_bytes: int = 2_000_000
    max_dispatch_entries: int = 1
    max_source_files: int = 1
    max_source_bytes: int = 1_000_000
    max_operations_per_body: int = 4000
    max_total_operations: int = 4000
    max_selected_decode_bytes: int = 128_000_000
    max_record_bytes: int = 64_000_000
    max_output_bytes: int = 128_000_000
    max_report_bytes: int = 8_000_000
    max_catalog_groups: int = 16
    max_catalog_entries: int = 16
    max_catalog_source_files: int = 6
    max_source_roots: int = 8
    max_archive_keys: int = 21
    max_archive_sources: int = 6
    max_archives: int = 2
    max_archive_bytes: int = 32_000_000
    max_seconds: int = 180

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in asdict(self).values()):
            raise ValueError('source-entry budgets must be positive exact integers')
        if self.max_operations_per_body > 100000:
            raise ValueError('entry per-body budget exceeds the public lowerer ceiling')


def _receipt(path):
    raw = path.read_bytes()
    return {'uri': str(path), 'sha256': _sha(raw), 'size_bytes': len(raw)}


def _terminal(path, reader):
    path = Path(path).absolute()
    if path.is_dir():
        path = path / 'model-run.json'
    document, declaration = reader.read(path)
    if document.get('schema') != SCHEMA:
        raise ValueError('source-entries requires a model-run terminal')
    if 'terminal' in document:
        ref = document['terminal']
        attempt = Path(document['attempt'])
        if attempt.parent != path.parent / 'attempts' or ref.get('uri') != str(attempt / 'terminal.json'):
            raise ValueError('navigation points outside its exact immutable attempt')
        terminal, measured = reader.read(ref['uri'], ref)
        if _canonical(document) != _canonical({**terminal, 'terminal': ref}):
            raise ValueError('navigation differs from the pinned immutable terminal')
    else:
        terminal, measured = document, declaration
        if path.name != 'terminal.json' or terminal.get('attempt') != str(path.parent):
            raise ValueError('direct input must be the original attempt terminal')
    if terminal.get('partial_route') != 'DEPENDENCY_SOURCE_ONLY':
        raise ValueError('source-entries requires the dependency-source route, not a success label')
    attempt = Path(terminal['attempt'])
    products = terminal['products']
    admissions, admission_ref = reader.read(_safe(products['dependency_admissions']['uri'], attempt),
                                           products['dependency_admissions'])
    archive, archive_ref = reader.read(_safe(products['dependency_workload_witness']['uri'], attempt),
                                      products['dependency_workload_witness'])
    resolution, resolution_ref = reader.read(_safe(products['dependency_witness_resolution']['uri'], attempt),
                                             products['dependency_witness_resolution'])
    original = _dependency_base(terminal['input_terminal']['uri'], reader)
    if any(original['terminal'][key] != terminal['input_terminal'][key] for key in ('uri', 'sha256', 'size_bytes')):
        raise ValueError('dependency terminal changed its original bootstrap terminal')
    if terminal['capture'] != original['capture']:
        raise ValueError('dependency terminal changed the original capture namespace')
    for name, ref in (('source_seed_input', original['source_seeds']), ('source_binding_input', original['source_bindings'])):
        if any(terminal[name][key] != ref[key] for key in ('uri', 'sha256', 'size_bytes')):
            raise ValueError('dependency terminal changed original source inputs')
    _verify_dependency_scope(admissions, original)
    project = original['original_products']
    project_composition, project_composition_ref = reader.read(project['source_composition']['uri'], project['source_composition'])
    project_inventory, project_inventory_ref = reader.read(project['source_inventory']['uri'], project['source_inventory'])
    project_layers, project_layers_ref = reader.read(project['source_layers']['uri'], project['source_layers'])
    project_archive, project_archive_ref = reader.read(project['workload_witness']['uri'], project['workload_witness'])
    if (project_composition.get('schema') != 'scar.program-composition' or project_composition.get('schema_version') != 1
            or project_inventory.get('schema') != 'scar.program-inventory'
            or project_layers.get('schema') != 'scar.source-layers'
            or _canonical(project_inventory['call_sources']['model']) != _canonical(original['seed_model'])
            or project_inventory['discovery']['project_root'] != original['project_root']):
        raise ValueError('original project composition/inventory/source scope differs')
    for declared, actual in ((project_composition['inventory'], project_inventory_ref),
                             (project_composition['source_layers'], project_layers_ref)):
        if declared['path'] != actual['uri'] or declared['raw_sha256'] != actual['sha256'] or declared['raw_bytes'] != actual['size_bytes']:
            raise ValueError('original project composition changed its exact inventory/layer inputs')
    if (project_archive.get('schema') != 'scar.code-witness-store' or type(project_archive.get('schema_version')) is not int
            or project_archive['schema_version'] != 1 or any(project_archive.get(name) is not False for name in
                ('target_executed', 'source_prepared', 'transformation_authorized'))):
        raise ValueError('original project archive schema/authority differs')
    if (archive.get('schema') != 'scar.code-witness-store' or type(archive.get('schema_version')) is not int
            or archive['schema_version'] != 1 or any(archive.get(name) is not False for name in
                ('target_executed', 'source_prepared', 'transformation_authorized'))):
        raise ValueError('unsupported or overqualified dependency compiler archive')
    if (resolution.get('schema') != 'scar.model-run-workload-witness/1'
            or resolution.get('target_executed') is not False
            or resolution['archive']['path'] != archive_ref['uri']
            or resolution['archive']['sha256'] != archive_ref['sha256']
            or resolution['archive']['bytes'] != archive_ref['size_bytes']):
        raise ValueError('dependency witness resolution selects a different original archive')
    groups = [{'process_id': row['process_id'], 'code': row['code'],
               'captured_code': row['captured_code'], 'descriptor_anchor': row['descriptor_anchor'],
               'first_anchor': row['first_anchor'], 'last_anchor': row['last_anchor'],
               'entered_invocations': row['entered_invocations'], 'source_status': row['status'],
               'source_link': row['code_source_link'], 'frontiers': row['frontiers']}
              for row in admissions['admissions']]
    project_frontiers = [{'code': row['code'], 'source_link': row,
                          'frontier': 'SOURCE_DEFINITION_INTERFACE_UNAVAILABLE'}
                         for row in original['seed_model']['code_links']
                         if row['status'] == 'VERIFIED' and (row['definition'] is None or row['source'] is None)]
    return {'dependency_terminal': measured, 'dependency_input': declaration,
            'admissions': admission_ref, 'archive': archive_ref, 'witness_resolution': resolution_ref,
            'project_root': admissions['program_root'], 'capture': original['capture'],
            'groups': groups, 'summary': admissions['summary'], 'project_entry_frontiers': project_frontiers,
            'project_composition': project_composition_ref, 'project_inventory': project_inventory_ref,
            'project_layers': project_layers_ref, 'project_archive': project_archive_ref,
            'source_file_declarations': len(admissions['source_files']) + len(project_inventory['files']),
            'archive_modules': len(archive['modules']) + len(project_archive['modules']),
            'archive_sources': len(archive['sources']) + len(project_archive['sources']),
            'bootstrap_products': original['original_products'], 'bootstrap_terminal': original['terminal']}


def run_source_entry_stage(model_run_path, out, *, plan_only=False, resume=False,
                           budget=SourceEntryRunBudget(), budget_sources=None, source_entry_profile=None):
    if type(budget) is not SourceEntryRunBudget or type(plan_only) is not bool or type(resume) is not bool:
        raise ValueError('source-entry stage requires exact budget and Boolean options')
    budget.__post_init__()
    from scar.analysis.source_frontend_worklist import SOURCE_ENTRY_PROFILES
    if source_entry_profile is not None and source_entry_profile not in SOURCE_ENTRY_PROFILES:
        raise ValueError('unsupported automatic source-entry frontend profile')
    root, source = Path(out).absolute(), Path(model_run_path).absolute()
    if root != root.resolve() or source != source.resolve():
        raise ValueError('source-entry input/output must be canonical')
    if source.is_dir():
        source = source / 'model-run.json'
    if root == source.parent or root.is_relative_to(source.parent) or source.is_relative_to(root):
        raise ValueError('source-entry output overlaps its original dependency input')
    if root.exists() and not resume:
        raise ValueError('source-entry output exists; --resume makes a fresh attempt')
    fields = asdict(budget)
    sources = {key: 'API_BUDGET_OBJECT' for key in fields} if budget_sources is None else dict(budget_sources)
    if set(sources) != set(fields) or any(type(value) is not str or not value for value in sources.values()):
        raise ValueError('every source-entry budget needs explicit configuration provenance')
    reader = _PinnedModelInputs(budget.max_metadata_bytes)
    previous = None
    if resume:
        previous, _old = reader.read(_safe(root / 'model-run.json', root))
        if previous.get('schema') != SCHEMA or previous.get('partial_route') != 'SOURCE_ENTRIES_ONLY':
            raise ValueError('entry resume requires the original entry-stage root')
    root.mkdir(parents=True, exist_ok=True)
    attempts = _safe(root / 'attempts', root)
    attempts.mkdir(exist_ok=True)
    attempt = attempts / (str(time.time_ns()) + '-' + str(os.getpid()))
    attempt.mkdir()
    started = time.monotonic()
    implementation = [_receipt(Path(__file__).resolve()), _receipt(Path(__file__).resolve().parents[1] / 'cli.py'),
                      _receipt(Path(__file__).resolve().parent / 'model_run.py')]
    result = {'schema': SCHEMA, 'partial_route': 'SOURCE_ENTRIES_ONLY', 'attempt': str(attempt),
        'status': 'RUNNING', 'plan_only': plan_only, 'implementation': implementation,
        'budget': fields, 'budget_sources': sources, 'products': {}, 'stages': [],
        'publication': 'NOT_RUN', 'runtime_binding': 'NOT_RUN', 'target_executed': False,
        'whole_model_established': False,
        'open': ['SP5 recovery/reader is not publication or runtime body linkage',
                 'live owned return expires at process exit; JSON cannot restore it',
                 'same SP5 may receive later ordinary independent CP2 admission with unknown cost; no re-lower required',
                 'module/frozen/tool origin and data/state/identity/ready/completeness remain OPEN'],
        'budget_enforcement': {'metadata': 'bounded stored+decoded original headers; overflow probe charged',
            'source_provider_decode': 'SourceAttachments unique canonical-byte bound; selected original graphs only',
            'worker': 'SourceFrontendBudget dispatch/file/operations/time parameters',
            'output': 'post-stage total stored current-attempt check, not continuous hard ceiling',
            'wall': 'worker between tasks plus required external timeout',
            'cumulative_stored_plus_decoded_input_io': 'OPEN'},
        'resume_policy': 'fresh source-entry attempt; no dependency/raw/native/OS replay or ownership restoration'}
    if source_entry_profile is not None:
        result['source_entry_profile'] = source_entry_profile
    if previous is not None:
        result['previous_attempt'] = {'path': previous['attempt'], 'status': previous['status']}
    _publish(attempt / 'started.json', {'input': str(source), 'implementation': implementation,
                                      'budget': fields, 'budget_sources': sources})
    _update_navigation(root, attempt, result)
    old_signal = signal.signal(signal.SIGTERM, _interrupt) if threading.current_thread() is threading.main_thread() else None
    try:
        inputs = _terminal(source, reader)
        capture = Path(inputs['capture'])
        if root == capture or root.is_relative_to(capture) or capture.is_relative_to(root):
            raise ValueError('entry output overlaps the original capture')
        if previous is not None and _canonical(previous.get('dependency_terminal')) != _canonical(inputs['dependency_terminal']):
            raise ValueError('entry resume changed the immutable dependency terminal')
        result.update(dependency_terminal=inputs['dependency_terminal'], capture=inputs['capture'],
                      retained_inputs={key: inputs[key] for key in ('admissions', 'archive', 'witness_resolution',
                          'project_composition', 'project_inventory', 'project_layers', 'project_archive')},
                      project_entry_frontiers=inputs['project_entry_frontiers'],
                      original_denominators={'groups': len(inputs['groups']),
                          'calls': sum(row['entered_invocations'] for row in inputs['groups'])})
        blockers = []
        if (len(inputs['groups']) > budget.max_catalog_groups or inputs['archive_modules'] > budget.max_archive_keys
                or inputs['archive_sources'] > budget.max_archive_sources
                or inputs['source_file_declarations'] > budget.max_catalog_source_files):
            blockers.append('original metadata cohort exceeds independent entry profile')
        result['plan'] = _publish(attempt / 'plan.json', {'schema': 'scar.source-entry-stage-plan/1',
            'dependency_terminal': inputs['dependency_terminal'], 'inputs': result['retained_inputs'],
            'project_root': inputs['project_root'], 'groups': inputs['groups'], 'summary': inputs['summary'],
            'budget': fields, 'budget_sources': sources, 'blockers': blockers,
            'raw_read': False, 'graph_decode': False, 'lower_run': False}, maximum=budget.max_report_bytes)
        result['status'] = 'BLOCKED' if blockers else 'METADATA_PLANNED_WITH_OPEN'
        if not blockers and not plan_only:
            _execute(inputs, attempt, result, budget, source_entry_profile=source_entry_profile)
    except BaseException as error:
        result.update(status='FAILED', failure={'type': type(error).__name__, 'detail': str(error)})
    finally:
        result['planning_io'] = {'stored_metadata_bytes': reader.stored_bytes, 'decoded_metadata_bytes': reader.decoded_bytes,
                                 'scope': 'original small headers only; actual graph/code/worker I/O separate'}
        result['input_receipts'] = reader.receipts
        if old_signal is not None:
            signal.signal(signal.SIGTERM, old_signal)
    result['wall_seconds'] = time.monotonic() - started
    raw = _canonical(result) + b'\n'
    projection = {'uri': str(attempt / 'terminal.json'), 'sha256': _sha(raw), 'size_bytes': len(raw)}
    stored = sum(path.stat().st_size for path in _regular_files(attempt))
    if len(raw) > budget.max_report_bytes or stored + len(raw) + len(_canonical({**result, 'terminal': projection})) + 1 > budget.max_output_bytes:
        result.update(status='FAILED', failure={'type': 'PostStageOutputBudget', 'detail': 'partial outputs retained'})
    terminal = _publish(attempt / 'terminal.json', result)
    navigation = {**result, 'terminal': terminal}
    _update_navigation(root, attempt, navigation)
    return navigation


def _execute(inputs, attempt, result, budget, *, source_entry_profile=None):
    from scar.analysis.code_witness import CodeWitnessBudget
    from scar.analysis.compiler_witness_archives import CompilerArchiveBudget, CompilerWitnessArchives
    from scar.analysis.source_attachments import SourceAttachmentBudget, SourceAttachments
    from scar.analysis.source_entry_catalog import SourceEntryCatalog
    from scar.analysis.program_composition import CompositionIndex
    from scar.analysis.source_frontend_worklist import SourceFrontendBudget, plan_source_entries, run_source_entries
    from scar.ir.record_codec import encode

    stage = attempt / 'source-entries'
    stage.mkdir()
    tick = time.monotonic()
    record = {'stage': 'source-entries', 'directory': str(stage), 'status': 'STARTED'}
    result['stages'].append(record)
    _publish(stage / 'started.json', {'inputs': result['retained_inputs'], 'budget': asdict(budget)})
    def progress(row):
        print(json.dumps({'schema': SCHEMA, 'source_entry_progress': row}, allow_nan=False), flush=True)
    try:
        owner = SourceAttachments.from_admissions(inputs['admissions']['uri'],
            expected_report_sha256=inputs['admissions']['sha256'], project_root=inputs['project_root'],
            budget=SourceAttachmentBudget(max_report_bytes=budget.max_metadata_bytes,
                max_files=budget.max_catalog_source_files, max_codes=budget.max_catalog_groups,
                max_roots=budget.max_source_roots, max_artifact_bytes=budget.max_selected_decode_bytes,
                max_record_bytes=budget.max_record_bytes, cached_files=1))
        declarations = tuple(dict.fromkeys((str(Path(inputs[key]['uri']).parent), inputs[key]['sha256'])
                                           for key in ('archive', 'project_archive')))
        archives = CompilerWitnessArchives(declarations,
            store_budget=CodeWitnessBudget(max_compile_keys=budget.max_archive_keys, max_source_files=budget.max_archive_sources,
                max_source_bytes=budget.max_source_bytes, max_archive_bytes=budget.max_archive_bytes,
                max_manifest_bytes=budget.max_metadata_bytes),
            budget=CompilerArchiveBudget(max_archives=budget.max_archives, max_total_modules=budget.max_archive_keys,
                max_total_sources=budget.max_archive_sources, max_declared_payload_bytes=budget.max_archive_bytes))
        project = CompositionIndex(inputs['project_composition']['uri'], max_input_bytes=budget.max_record_bytes,
                                   max_record_bytes=budget.max_record_bytes)
        before = [dict(archives.store_for(ref).counts) for ref in archives.receipts()]
        catalog = SourceEntryCatalog(archives=archives, admissions=(owner,), projects=(project,), max_groups=budget.max_catalog_groups,
            max_candidates=budget.max_catalog_entries, max_selected_decode_bytes=budget.max_selected_decode_bytes)
        worker_budget = SourceFrontendBudget(max_catalog_files=budget.max_catalog_source_files,
            max_catalog_bodies=budget.max_catalog_entries, max_catalog_groups=budget.max_catalog_groups,
            max_dispatch_bodies=budget.max_dispatch_entries, max_source_files=budget.max_source_files,
            max_source_bytes=budget.max_source_bytes, max_operations_per_body=budget.max_operations_per_body,
            max_total_operations=budget.max_total_operations, max_record_bytes=budget.max_record_bytes,
            max_output_bytes=budget.max_output_bytes, max_elapsed_seconds=budget.max_seconds)
        profile_options = ({'source_entry_profile': source_entry_profile}
                           if source_entry_profile is not None else {})
        plan = plan_source_entries(catalog, budget=worker_budget, out_dir=stage / 'plan', **profile_options)
        if source_entry_profile is not None and plan.dispatch:
            from scar.trace.lean_capture import LeanCapturePlan
            try:
                capture_plan = LeanCapturePlan.from_source_entry_plan(plan, namespace_root=inputs['project_root'])
                capture_directory = stage / 'capture-plan'
                capture_directory.mkdir()
                capture_ref = capture_plan.publish(capture_directory, os.getpid())
                result['products']['capture_plan'] = _receipt(Path(capture_ref.uri))
                result['capture_plan_scope'] = {'planned_bodies': len(capture_plan.bodies),
                    'selection': 'this source-entry dispatch window; not whole-program coverage'}
            except (ValueError, OSError) as error:
                # A future capture selector is optional to source recovery.
                # Missing/stale code or source keeps an explicit local frontier.
                result['capture_plan_frontier'] = {'type': type(error).__name__, 'detail': str(error)}
        worker = run_source_entries(plan, stage / 'worker', budget=worker_budget, progress=progress)
        worker.require_unchanged()
        after = [dict(archives.store_for(ref).counts) for ref in archives.receipts()]
        result['readonly_activity'] = [{key: right[key] - left[key] for key in left} for left, right in zip(before, after)]
        if any(row['compile_attempts'] != 0 for row in result['readonly_activity']):
            raise ValueError('readonly source-entry stage acquired compiler modules')
        result['worker'] = worker.document
        result['live_owned_returns_in_this_process'] = len(worker.owned_returns)
        result['products']['entry_worker_manifest'] = _receipt(stage / 'worker/manifest.json')
        programs = []
        for returned in worker.owned_returns:
            returned.require_unchanged()
            if returned.program_reference is not None:
                programs.append({'entry_reference': encode(returned.entry.reference),
                                 'source_program': returned.program_reference['artifact'],
                                 'worker_terminal': _receipt(Path(returned.program_reference['artifact']['uri']).parent / 'result.json')})
        result['products']['source_programs'] = programs
        if worker.document['original_current_groups'] != result['original_denominators']['groups'] or worker.document['original_current_calls'] != result['original_denominators']['calls']:
            raise ValueError('entry worker changed the original source denominator')
        stored = sum(path.stat().st_size for path in _regular_files(attempt))
        if stored > budget.max_output_bytes:
            raise ValueError('source-entry post-stage stored output budget exceeded')
        record.update(status='COMPLETED', post_stage_stored_bytes=stored)
        result['status'] = 'FAILED' if worker.document['counts'].get('FAILED', 0) else 'SOURCE_ENTRY_ATTEMPT_WITH_OPEN'
    except BaseException as error:
        record.update(status='FAILED_PARTIAL_RETAINED', failure={'type': type(error).__name__, 'detail': str(error)})
        raise
    finally:
        record['wall_seconds'] = time.monotonic() - tick
        record['terminal'] = _publish(stage / 'terminal.json', dict(record))


@dataclass(frozen=True)
class SourceEntryBindingBudget:
    """Independent publication/binding profile; seed ceilings grant no raw I/O."""
    max_metadata_bytes: int = 2_000_000
    max_programs: int = 1
    max_operations_per_body: int = 4000
    max_selected_decode_bytes: int = 128_000_000
    max_record_bytes: int = 64_000_000
    max_output_bytes: int = 128_000_000
    max_report_bytes: int = 8_000_000
    max_catalog_groups: int = 16
    max_catalog_entries: int = 16
    max_catalog_source_files: int = 6
    max_source_roots: int = 8
    max_archive_keys: int = 21
    max_archive_sources: int = 6
    max_archives: int = 2
    max_archive_bytes: int = 32_000_000
    max_source_bytes: int = 1_000_000
    max_raw_bytes: int = 2_000_000
    max_lines: int = 2048
    max_line_bytes: int = 1_000_000
    max_processes: int = 4
    max_codes: int = 16
    max_events: int = 1024
    max_coordinate_bytes: int = 64_000_000
    max_coordinate_control_bytes: int = 1_000_000
    max_seed_raw_bytes: int = 64_000_000
    max_seed_lines: int = 2304
    max_seed_line_bytes: int = 64_000_000
    max_seed_processes: int = 128
    max_seed_codes: int = 128
    max_seed_events: int = 1024
    max_seed_source_files: int = 4
    max_seed_source_bytes: int = 256_000
    max_seed_references: int = 1_000_000
    max_seed_path: int = 128
    max_seconds: int = 180

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in asdict(self).values()):
            raise ValueError('binding profile ceilings must be positive exact integers')
        if self.max_coordinate_bytes > 68_000_000 or self.max_coordinate_control_bytes > 1_000_000:
            raise ValueError('binding coordinate ceiling exceeds the public payload-budget contract')


def _binding_require(condition, detail):
    if not condition:
        raise ValueError('source-entry bindings: ' + detail)


def _binding_inputs(path, reader, budget):
    """Bounded original headers only; no source/graph/archive payload is opened."""
    path = Path(path).absolute()
    if path.is_dir():
        path = path / 'model-run.json'
    document, declared = reader.read(path)
    _binding_require(document.get('schema') == SCHEMA, 'model-run input schema differs')
    if 'terminal' in document:
        ref, attempt = document['terminal'], Path(document['attempt'])
        _binding_require(attempt.parent == path.parent / 'attempts' and ref['uri'] == str(attempt / 'terminal.json'),
                         'navigation terminal leaves the original attempt')
        terminal, measured = reader.read(ref['uri'], ref)
        _binding_require(_canonical(document) == _canonical({**terminal, 'terminal': ref}),
                         'navigation differs from its immutable terminal')
    else:
        terminal, measured = document, declared
        _binding_require(path.name == 'terminal.json' and terminal.get('attempt') == str(path.parent),
                         'direct input is not an immutable attempt terminal')
    _binding_require(terminal.get('partial_route') == 'SOURCE_ENTRIES_ONLY', 'source-entry terminal route required')
    inputs = _terminal(terminal['dependency_terminal']['uri'], reader)
    _binding_require(all(inputs['dependency_terminal'][key] == terminal['dependency_terminal'][key]
                         for key in ('uri', 'sha256', 'size_bytes')), 'dependency terminal changed')
    _binding_require(terminal['capture'] == inputs['capture'] and terminal['retained_inputs'] ==
        {key: inputs[key] for key in ('admissions', 'archive', 'witness_resolution', 'project_composition',
                                      'project_inventory', 'project_layers', 'project_archive')},
        'entry terminal changed original project/dependency/archive scope')
    denominator = {'groups': len(inputs['groups']), 'calls': sum(row['entered_invocations'] for row in inputs['groups'])}
    _binding_require(terminal['original_denominators'] == denominator, 'entry denominator differs')
    attempt, products = Path(terminal['attempt']), terminal['products']
    manifest_ref = products.get('entry_worker_manifest')
    requests, retained, blockers = [], [], []
    if manifest_ref is None:
        blockers.append('SOURCE_ENTRY_WORKER_PRODUCT_UNAVAILABLE')
    else:
        worker, _ = reader.read(_safe(manifest_ref['uri'], attempt), manifest_ref)
        _binding_require(worker.get('schema') == 'scar.source-frontend-result' and worker.get('schema_version') == 2
            and worker == terminal['worker'] and worker['original_current_groups'] == denominator['groups']
            and worker['original_current_calls'] == denominator['calls'], 'worker scope/original denominator differs')
        saved_programs = products.get('source_programs', [])
        legacy_unambiguous = len(saved_programs) == worker['counts'].get('SUCCEEDED', 0)
        if not legacy_unambiguous and any('worker_terminal' not in row for row in saved_programs):
            blockers.append('SUCCESS_ARTIFACT_MEMBERSHIP_UNAVAILABLE')
        seen = set()
        for product in saved_programs:
            reference, program = product['entry_reference'], product['source_program']
            program_path = _safe(program['uri'], attempt)
            _binding_require(program_path.is_file() and not program_path.is_symlink()
                and program_path.stat().st_size == program['physical_bytes']
                and program['representation'] == 'scar.source-program/5' and program['external'] is True,
                'saved source program declaration/path/size differs')
            record_path = program_path.parent / 'result.json'
            expected_record = product.get('worker_terminal')
            if expected_record is not None:
                _binding_require(expected_record['uri'] == str(record_path), 'worker terminal is outside its original body attempt')
            record, record_ref = reader.read(record_path, expected_record)
            _binding_require(record['program'] == program and record['entry_reference'] == reference,
                             'saved program and original worker terminal record differ')
            identity = _canonical(reference)
            _binding_require(identity not in seen, 'duplicate qualified original source program')
            seen.add(identity)
            retained.append({'entry_reference': reference, 'source_program': program,
                             'worker_record': record_ref, 'worker_status': record['status']})
            if record['status'] != 'SUCCEEDED':
                continue
            _binding_require(record['public_structure_reader'] is True and record['independent_code_reader'] is True,
                             'successful worker record contradicts its reader outcomes')
            requests.append({'entry_key': record['entry_key'], 'source_program': program})
        _binding_require(worker['counts'].get('SUCCEEDED', 0) == len(requests),
                         'successful program denominator differs from the worker')
    if not requests:
        blockers.append('NO_SUCCESSFUL_SOURCE_PROGRAMS')
    if len(requests) > budget.max_programs:
        blockers.append('ALL_SUCCESSFUL_PROGRAMS_EXCEED_BINDING_WINDOW')
    if (len(inputs['groups']) > budget.max_catalog_groups or inputs['archive_modules'] > budget.max_archive_keys
            or inputs['archive_sources'] > budget.max_archive_sources
            or inputs['source_file_declarations'] > budget.max_catalog_source_files):
        blockers.append('ORIGINAL_CATALOG_EXCEEDS_BINDING_PROFILE')
    model_ref = inputs['bootstrap_products']['capture_model']
    model, model_receipt = reader.read(model_ref['uri'], model_ref)
    _binding_require(model.get('schema') == 'scar.capture-model' and model.get('schema_version') == 1
                     and model['capture'] == inputs['capture'], 'original capture-model schema/scope differs')
    coordinate_ref = model['coordinate_binding']
    coordinate, coordinate_receipt = reader.read(coordinate_ref['uri'], coordinate_ref)
    old_binding_ref = inputs['bootstrap_products']['source_bindings']
    old_binding, _ = reader.read(old_binding_ref['uri'], old_binding_ref)
    _binding_require(coordinate['schema'] == 'scar.capture-coordinates' and coordinate['schema_version'] == 1
        and coordinate['local_root'] == inputs['capture'] and coordinate['run'] == model['run'] == old_binding['run']
        and all(old_binding['coordinate_binding'][key] == coordinate_ref[key] for key in ('sha256', 'size_bytes')),
        'original coordinate/Run/capture scope differs')
    return {**inputs, 'source_entry_terminal': measured, 'source_entry_input': declared,
            'worker_manifest': manifest_ref, 'program_declarations': retained, 'requests': tuple(requests),
            'capture_model': model_receipt, 'coordinate_profile': coordinate_receipt,
            'original_denominators': denominator, 'blockers': sorted(set(blockers))}


def _binding_coordinates(model_ref, out, budget, result):
    """Fresh genuine ordinary binder, with the verified complete-pass accounting.

    Persisted coordinate JSON supplies receipts only. It never restores a live
    object. No capture/native/OS model import or target execution occurs here.
    """
    from scar.trace.capture_coordinates import bind_capture_coordinates
    from scar.trace.native_tensor_inputs import NativeInputPayloadBudget
    from scar.ir.execution.coordinates import ExecutionRun
    from scar.ir.record_codec import decode
    ledger = NativeInputPayloadBudget(maximum=budget.max_coordinate_bytes,
                                     control_maximum=budget.max_coordinate_control_bytes)
    def control(path, expected=None):
        path = Path(path)
        _binding_require(path.is_absolute() and path.is_file() and not path.is_symlink(), 'unsafe coordinate control path')
        size = path.stat().st_size
        reservation = ledger.charge('control: ' + path.name, size, size, control=True)
        with path.open('rb') as stream:
            raw = stream.read(size + 1)
        _binding_require(len(raw) == size and (expected is None or _sha(raw) == expected), 'coordinate control bytes changed')
        ledger.complete(reservation)
        return json.loads(raw), raw
    try:
        model, _ = control(model_ref['uri'], model_ref['sha256'])
        _binding_require(model['schema'] == 'scar.capture-model' and model['schema_version'] == 1, 'capture-model schema differs')
        root = Path(model['capture']).resolve()
        retained, retained_raw = control(model['coordinate_binding']['uri'], model['coordinate_binding']['sha256'])
        _binding_require(len(retained_raw) == model['coordinate_binding']['size_bytes']
                         and retained['local_root'] == str(root), 'coordinate root/size differs')
        archive, archive_raw = control(root / 'archive-index.json', retained['seed']['archive_sha256'])
        _binding_require(archive['schema'] == 'scar.lossless-capture-archive' and archive['schema_version'] == 1,
                         'current coordinate acquisition requires the supported lossless retention profile')
        members = {row['artifact']['uri']: row for row in retained['membership']}
        archived = {row['logical_path']: row for row in archive['files']}
        _binding_require(len(members) == len(retained['membership']) and len(archived) == len(archive['files']),
                         'duplicate coordinate/archive membership')
        def one(schema, required=True):
            rows = [row['artifact'] for row in retained['membership'] if row['artifact']['schema'] == schema]
            _binding_require(len(rows) == 1 if required else len(rows) <= 1, 'coordinate member cardinality: ' + schema)
            return rows[0] if rows else None
        def stored(artifact):
            record = archived.get(artifact['uri'])
            return record['compressed_bytes'] if record is not None else artifact['size_bytes']
        native = one('scar.execution-evidence-collection')
        native_meta, _ = control(members[native['uri']]['local_path'], native['sha256'])
        run_size = (root / 'trace/run.json').stat().st_size
        plain = sum(row['artifact']['size_bytes'] for row in retained['membership'] if row['artifact']['uri'] not in archived) + run_size
        archive_stored = sum(row['compressed_bytes'] for row in archive['files'])
        verified_raw = sum(row['raw_bytes'] for row in archive['files']) + plain
        _binding_require(verified_raw == retained['counts']['verified_raw_bytes']
                         and verified_raw <= budget.max_coordinate_bytes, 'coordinate complete inventory/raw ceiling differs')
        ledger.charge('ordinary binder verified complete members', 2 * archive_stored + plain, verified_raw,
            basis='precharged complete SHA passes; fresh ordinary binder reconciles exact receipts')
        os_rows = [row['artifact'] for row in retained['membership'] if row['artifact']['schema'] == 'strace.syscalls.text.v1']
        ledger.charge('ordinary binder OS fact parse', sum(stored(row) for row in os_rows),
            sum(row['size_bytes'] for row in os_rows), basis='unchanged complete OS fact parse passes')
        cap = retained.get('native_tensor_input_membership')
        if cap is not None:
            ledger.charge('ordinary binder strict companion parse', sum(stored(row) for row in cap['chunks']),
                sum(row['size_bytes'] for row in cap['chunks']), basis='unchanged complete strict companion parse passes')
        companion = [native, one('scar.tensor-physical-trace', False), one('scar.dispatch-observation-trace', False)]
        if cap is not None:
            companion.append(cap['manifest'])
        size = sum(row['size_bytes'] for row in companion if row is not None)
        ledger.charge('ordinary binder strict companion metadata parse', size, size, basis='cached verified document parse')
        names = ('call-meta.', 'call-operand-meta.', 'function-environment-meta.', 'dispatch-meta.', 'tensor-physical-meta.')
        docs = sum(row['artifact']['size_bytes'] for row in retained['membership']
                   if Path(row['logical_path']).name.startswith(names)) + run_size
        if cap is not None:
            docs += cap['manifest']['size_bytes']
        ledger.charge('ordinary binder other metadata parse', docs, docs, basis='complete document passes')
        size = native['size_bytes'] + len(archive_raw)
        ledger.charge('ordinary binder initial native/archive', size, size, basis='complete initial document reads')
        provider = retained.get('os_capture_provider')
        if provider is not None:
            controls = sum(row['size_bytes'] for row in (provider['launch'], provider['profile'],
                native_meta['configuration']['os_capture_intent']['intent']))
            ledger.charge('ordinary binder OS intent/launch/coverage', 2 * controls, 2 * controls,
                          basis='receipt read plus document read')
        coordinates = bind_capture_coordinates(root, max_bytes=verified_raw, profile_uri=str(out))
        _binding_require(coordinates.run == decode(ExecutionRun, model['run']) and coordinates.payload == retained_raw
            and coordinates.report['counts']['verified_raw_bytes'] == verified_raw,
            'genuine current coordinates differ from exact original Run/membership')
        ledger.complete_prefix('ordinary binder ')
        with out.open('xb') as stream:
            stream.write(coordinates.payload)
        return coordinates, root
    finally:
        result['coordinate_accounting'] = ledger.report()


def _execute_entry_bindings(inputs, attempt, result, budget):
    from scar.analysis.model_run import _Stages
    from scar.analysis.source_attachments import SourceAttachments, SourceAttachmentBudget
    from scar.analysis.compiler_witness_archives import CompilerWitnessArchives, CompilerArchiveBudget
    from scar.analysis.code_witness import CodeWitnessBudget
    from scar.analysis.source_entry_catalog import SourceEntryCatalog
    from scar.analysis.program_composition import CompositionIndex
    from scar.analysis.source_program_publication import publish_source_entries, plan_source_entry_publication
    from scar.analysis.source_invocations import bind_source_invocations
    from scar.ir.program.call_edges import CallEdgeBudget
    from scar.ir.program.source_references import SourceDefinitionReference
    from scar.ir.record_codec import encode, decode
    stages = _Stages(attempt, result, budget)
    result['phase'] = 'readonly-archive-inputs'
    attachment_budget = SourceAttachmentBudget(max_report_bytes=budget.max_metadata_bytes,
        max_files=budget.max_catalog_source_files, max_codes=budget.max_catalog_groups, max_roots=budget.max_source_roots,
        max_artifact_bytes=budget.max_selected_decode_bytes, max_record_bytes=budget.max_record_bytes, cached_files=1)
    archives = CompilerWitnessArchives(tuple((str(Path(inputs[key]['uri']).parent), inputs[key]['sha256'])
        for key in ('archive', 'project_archive')),
        store_budget=CodeWitnessBudget(max_compile_keys=budget.max_archive_keys, max_source_files=budget.max_archive_sources,
            max_source_bytes=budget.max_source_bytes, max_archive_bytes=budget.max_archive_bytes,
            max_manifest_bytes=budget.max_metadata_bytes),
        budget=CompilerArchiveBudget(max_archives=budget.max_archives, max_total_modules=budget.max_archive_keys,
            max_total_sources=budget.max_archive_sources, max_declared_payload_bytes=budget.max_archive_bytes))
    before = [dict(archives.store_for(ref).counts) for ref in archives.receipts()]
    def publish(stage):
        parent = CompositionIndex(inputs['project_composition']['uri'], max_input_bytes=budget.max_record_bytes,
                                  max_record_bytes=budget.max_record_bytes)
        owner = SourceAttachments.from_admissions(inputs['admissions']['uri'], expected_report_sha256=inputs['admissions']['sha256'],
            project_root=inputs['project_root'], budget=attachment_budget)
        catalog = SourceEntryCatalog(archives=archives, admissions=(owner,), projects=(parent,),
            max_groups=budget.max_catalog_groups, max_candidates=budget.max_catalog_entries,
            max_selected_decode_bytes=budget.max_selected_decode_bytes)
        actual = catalog.metadata()
        _binding_require(actual['entered_code_groups'] == inputs['original_denominators']['groups']
            and actual['entered_invocations'] == inputs['original_denominators']['calls'], 'publication catalog changed scope')
        publication_plan = plan_source_entry_publication(parent, catalog, inputs['requests'], max_programs=budget.max_programs)
        return publish_source_entries(parent, catalog, inputs['requests'], stage / 'publication', plan=publication_plan,
            max_programs=budget.max_programs, max_operations_per_body=budget.max_operations_per_body,
            max_record_bytes=budget.max_record_bytes,
            progress=lambda row: print(json.dumps({'schema': SCHEMA, 'publication_progress': row}), flush=True))
    publication, _ = stages.call('qualified-publication', publish_source_entries, publish)
    result['products']['entry_publication'] = _receipt(Path(publication['manifest']))
    result['publication'] = publication
    def read(stage):
        composition = CompositionIndex.from_source_entry_publication(publication['manifest'], expected_sha256=publication['sha256'],
            archives=archives, attachment_budget=attachment_budget, max_input_bytes=budget.max_record_bytes,
            max_record_bytes=budget.max_record_bytes, max_programs=budget.max_programs,
            max_operations_per_body=budget.max_operations_per_body, max_catalog_groups=budget.max_catalog_groups,
            max_catalog_entries=budget.max_catalog_entries, max_selected_decode_bytes=budget.max_selected_decode_bytes)
        queries = []
        for saved in inputs['program_declarations']:
            if saved['worker_status'] != 'SUCCEEDED':
                continue
            definition = decode(SourceDefinitionReference, saved['entry_reference'])
            reference = composition.body_reference(definition)
            typed = composition.typed_qualified_body(reference)
            original = saved['source_program']
            _binding_require(reference.source_program.artifact.uri == original['uri']
                and reference.source_program.artifact.sha256 == original['physical_sha256']
                and typed.body.construction_operations is None and typed.body.graph.root == reference.identity,
                'public query changed the original qualified body')
            queries.append({'definition': encode(definition), 'body': encode(reference), 'namespace': typed.namespace,
                'operations': len(typed.body.graph.operations), 'source_shape_verified': typed.source_shape_verified,
                'source_code_verified': typed.source_code_witness_verified, 'construction_operations': None})
        result['public_queries'] = queries
        _publish(stage / 'queries.json', {'queries': queries, 'source_inputs': composition.source_inputs()},
                 maximum=budget.max_report_bytes)
        return composition
    composition, query_stage = stages.call('qualified-body-reader', CompositionIndex.from_source_entry_publication, read)
    result['products']['qualified_queries'] = _receipt(query_stage / 'queries.json')
    (coordinates, capture), coordinate_stage = stages.call('genuine-source-coordinates', _binding_coordinates,
        lambda stage: _binding_coordinates(inputs['capture_model'], stage / 'capture-coordinates.json', budget, result))
    _binding_require(str(capture) == inputs['capture'], 'fresh coordinate capture changed')
    result['products']['source_coordinates'] = _receipt(coordinate_stage / 'capture-coordinates.json')
    scan = CallEdgeBudget(max_raw_bytes=budget.max_raw_bytes, max_lines=budget.max_lines, max_line_bytes=budget.max_line_bytes,
        max_processes=budget.max_processes, max_codes=budget.max_codes, max_events=budget.max_events)
    seed = CallEdgeBudget(**{name: getattr(budget, name.replace('max_', 'max_seed_', 1))
                            for name in CallEdgeBudget.__dataclass_fields__})
    report, binding_stage = stages.call('source-entry-bindings', bind_source_invocations,
        lambda stage: bind_source_invocations(composition, coordinates, capture / 'trace', stage / 'bindings',
            call_budget=scan, seed_verification_budget=seed, witness_mode='same_capture'))
    result['products']['source_bindings'] = _receipt(binding_stage / 'bindings/report.json')
    checks = _PinnedModelInputs(budget.max_report_bytes)
    document, _ = checks.read(binding_stage / 'bindings/bindings.json')
    _binding_require(report['schema_version'] == document['schema_version'] == 4
        and report['source_inputs'] == document['source_inputs'] == composition.source_inputs()
        and len(document['bindings']) == inputs['original_denominators']['groups']
        and report['summary']['invocations'] == inputs['original_denominators']['calls'], 'ordinary binding scope differs')
    result.update(source_binding_summary=report['summary'], actual_call_scan=report['actual_call_scan'],
        call_budget=report['call_budget'], source_seed_verification_budget=report['source_seed_verification_budget'],
        budget_roles=report['budget_roles'], source_inputs=composition.source_inputs(),
        body_linked_calls=report['summary']['invocation_statuses'].get('BODY_LINKED_REUSED_WITNESS', 0))
    result['remaining_groups'] = [{'code': row['code'], 'calls': row['entered_invocations'],
        'status': row['status'], 'frontiers': row['frontiers']} for row in document['bindings'] if row['body'] is None]
    result['readonly_activity'] = [{key: archives.store_for(ref).counts[key] - prior.get(key, 0)
        for key in archives.store_for(ref).counts} for ref, prior in zip(archives.receipts(), before)]
    _binding_require(all(row['compile_attempts'] == 0 for row in result['readonly_activity']), 'readonly archive compiled source')
    result['status'] = 'SOURCE_ENTRY_BINDINGS_WITH_OPEN'


def run_source_entry_binding_stage(model_run_path, out, *, plan_only=False, resume=False,
                                   budget=SourceEntryBindingBudget(), budget_sources=None):
    """Generic offline stage: original saved source bodies into ordinary bindings."""
    _binding_require(type(budget) is SourceEntryBindingBudget and type(plan_only) is bool and type(resume) is bool,
                     'exact binding budget and Boolean options required')
    budget.__post_init__()
    root, source = Path(out).absolute(), Path(model_run_path).absolute()
    _binding_require(root == root.resolve() and source == source.resolve(), 'input/output must be canonical')
    if source.is_dir():
        source = source / 'model-run.json'
    _binding_require(root != source.parent and not root.is_relative_to(source.parent) and not source.is_relative_to(root),
                     'output overlaps its original model input')
    _binding_require(not root.exists() or resume, 'output exists; resume requires a fresh immutable attempt')
    fields = asdict(budget)
    sources = {key: 'API_BUDGET_OBJECT' for key in fields} if budget_sources is None else dict(budget_sources)
    _binding_require(set(sources) == set(fields) and all(type(value) is str and value for value in sources.values()),
                     'every binding ceiling needs configuration provenance')
    reader = _PinnedModelInputs(budget.max_metadata_bytes)
    previous = None
    if resume:
        previous, _ = reader.read(root / 'model-run.json')
        _binding_require(previous.get('schema') == SCHEMA and previous.get('partial_route') == 'SOURCE_ENTRY_BINDINGS_ONLY',
                         'resume root is not an original binding-stage root')
        _binding_require(previous.get('input') == str(source), 'resume changed its original source input path')
    root.mkdir(parents=True, exist_ok=True)
    attempts = _safe(root / 'attempts', root)
    attempts.mkdir(exist_ok=True)
    attempt = attempts / (str(time.time_ns()) + '-' + str(os.getpid()))
    attempt.mkdir()
    implementation = [_receipt(Path(__file__).resolve()), _receipt(Path(__file__).resolve().parents[1] / 'cli.py')]
    result = {'schema': SCHEMA, 'partial_route': 'SOURCE_ENTRY_BINDINGS_ONLY', 'attempt': str(attempt),
        'input': str(source), 'status': 'RUNNING', 'plan_only': plan_only, 'implementation': implementation, 'products': {}, 'stages': [],
        'budget': fields, 'budget_sources': sources, 'lower_prepare_compile_target': 'NOT_RUN',
        'owned_lower_return_restored': False, 'construction_operations': None, 'whole_model_established': False,
        'open': ['code/source/body association is not actual-formal/return/environment/state/effect/readiness proof',
                 'v4 is not a completed old SBA v2/v3 proof', 'other code groups keep source/body frontiers',
                 'cumulative all-input stored+decoded I/O and complete phase1 remain OPEN'],
        'budget_enforcement': {'metadata': 'pre-read stored+decoded bounded headers; no graph/raw planning',
            'seed': 'explicit metadata verifier only; no current raw/source I/O grant',
            'scan': 'independent actual CallEdgeBudget and complete original raw scope verification',
            'coordinates': 'precharged complete-pass stored+decoded reservations; fresh ordinary binder reconciliation',
            'output': 'per-stage actual stored/decompressed output checks; total post-stage bound, not continuous',
            'wall': 'between-stage bound plus required external timeout', 'cumulative_all_input_io': 'OPEN'}}
    if previous is not None:
        result['previous_attempt'] = {'path': previous['attempt'], 'status': previous['status']}
    _publish(attempt / 'started.json', {'input': str(source), 'implementation': implementation, 'budget': fields})
    _update_navigation(root, attempt, result)
    started = time.monotonic()
    old_signal = signal.signal(signal.SIGTERM, _interrupt) if threading.current_thread() is threading.main_thread() else None
    try:
        inputs = _binding_inputs(source, reader, budget)
        capture = Path(inputs['capture'])
        _binding_require(root != capture and not root.is_relative_to(capture) and not capture.is_relative_to(root),
                         'binding output overlaps original capture')
        if previous is not None and previous.get('source_entry_terminal') is not None:
            _binding_require(previous['source_entry_terminal'] == inputs['source_entry_terminal'], 'resume changed source-entry terminal')
        result.update(source_entry_terminal=inputs['source_entry_terminal'], dependency_terminal=inputs['dependency_terminal'],
            capture=inputs['capture'], original_denominators=inputs['original_denominators'],
            program_declarations=inputs['program_declarations'], selected_programs=len(inputs['requests']),
            project_entry_frontiers=inputs['project_entry_frontiers'], blockers=inputs['blockers'])
        result['products']['parent_source_composition'] = inputs['project_composition']
        result['plan'] = _publish(attempt / 'plan.json', {key: result[key] for key in
            ('source_entry_terminal', 'dependency_terminal', 'capture', 'original_denominators',
             'program_declarations', 'selected_programs', 'budget', 'budget_sources', 'blockers')}, maximum=budget.max_report_bytes)
        result['status'] = 'BLOCKED' if inputs['blockers'] else 'METADATA_PLANNED_WITH_OPEN'
        if not inputs['blockers'] and not plan_only:
            _execute_entry_bindings(inputs, attempt, result, budget)
    except BaseException as error:
        import traceback
        result.update(status='FAILED', failure={'type': type(error).__name__, 'detail': str(error),
            'traceback': traceback.format_exc(), 'stage': result['stages'][-1]['stage'] if result['stages'] else result.get('phase', 'metadata-plan')})
    finally:
        result['planning_io'] = {'stored_metadata_bytes': reader.stored_bytes, 'decoded_metadata_bytes': reader.decoded_bytes}
        result['input_receipts'] = reader.receipts
        result['wall_seconds'] = time.monotonic() - started
        if old_signal is not None:
            signal.signal(signal.SIGTERM, old_signal)
    raw_size = len(_canonical(result))
    stored = sum(path.stat().st_size for path in _regular_files(attempt))
    if raw_size > budget.max_report_bytes or stored + 2 * raw_size + 4096 > budget.max_output_bytes:
        result.update(status='FAILED', failure={'type': 'PostStageOutputBudget', 'detail': 'partial outputs retained'})
    result['post_stage_stored_bytes'] = stored
    terminal = _publish(attempt / 'terminal.json', result)
    _update_navigation(root, attempt, {**result, 'terminal': terminal})
    return {**result, 'terminal': terminal}


__all__ = ['SourceEntryRunBudget', 'run_source_entry_stage', 'SourceEntryBindingBudget',
           'run_source_entry_binding_stage']
