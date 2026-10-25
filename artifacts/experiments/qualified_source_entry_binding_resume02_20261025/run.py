"""Consume the existing CP2 publication; fresh genuine coordinates + raw binder."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'artifacts/experiments/qualified_source_entry_gate_20261025'
PREVIOUS = ROOT / 'artifacts/experiments/qualified_source_entry_binding_resume01_20261025'
assert hashlib.sha256((OLD / 'run.py').read_bytes()).hexdigest() == '83c27b4a83965e376a5e4a8d07e8a9f3bad6304d1cb48973efc1101023344245'
SPEC = importlib.util.spec_from_file_location('qualified_entry_original_helpers', OLD / 'run.py')
helpers = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helpers)  # definitions only; original run/prepare never called
sha, small, put = helpers.sha, helpers.small, helpers.put

# Explicit Root-authorized metadata verifier ceilings, not derived permission
# from the input's producer budget and never passed to the current raw scanner.
SEED_VERIFIER = dict(max_raw_bytes=64_000_000, max_lines=2304, max_line_bytes=64_000_000,
    max_processes=128, max_codes=128, max_events=1024, max_source_files=4,
    max_source_bytes=256_000, max_references=1_000_000, max_path=128)
CALL_SCANNER = dict(max_raw_bytes=2_000_000, max_lines=2048, max_line_bytes=1_000_000,
                    max_processes=4, max_codes=16, max_events=1024)


def prepare(label):
    assert not (HERE / 'freeze.json').exists()
    oldfreeze = small(OLD / 'freeze.json')
    failed = small(OLD / 'result.json')
    assert failed['status'] == 'FAILED' and failed['publication']['body_count'] == 1
    assert failed['failure']['phase'] == 'ordinary-same-capture-source-binder'
    inputs = {row['uri']: {key: row[key] for key in ('uri', 'sha256', 'size_bytes')} for row in oldfreeze['inputs']}
    manifest = Path(failed['publication']['manifest'])
    publication = small(manifest)
    assert sha(manifest)['sha256'] == failed['publication']['sha256']
    for path in (OLD / 'freeze.json', OLD / 'run.py', OLD / 'result.json', manifest):
        inputs[str(path)] = sha(path)
    previous = small(PREVIOUS / 'result.json')
    assert previous['status'] == 'FAILED' and previous['failure']['type'] == 'KeyError'
    for path in (PREVIOUS / 'freeze.json', PREVIOUS / 'run.py', PREVIOUS / 'result.json'):
        inputs[str(path)] = sha(path)
    for row in publication['bodies']:
        ref = row['checkpoint']
        inputs[ref['uri']] = {'uri': ref['uri'], 'sha256': ref['physical_sha256'], 'size_bytes': ref['physical_bytes']}
    put(HERE / 'freeze.json', {'schema': 'scar.qualified-source-entry-binding-resume-freeze/1', 'head_label': label,
        'entry': sha(Path(__file__).resolve()), 'sources': [sha(path) for path in sorted((ROOT / 'scar').rglob('*.py'))],
        'inputs': list(inputs.values()), 'capture_model': oldfreeze['capture_model'],
        'publication': failed['publication'], 'entry_terminal': oldfreeze['entry_terminal'],
        'seed_verification_budget': SEED_VERIFIER, 'actual_call_scanner_parameters': CALL_SCANNER,
        'budget': {**oldfreeze['budget'], 'source_seed_verification_budget_role': 'metadata decode only'},
        'old_gate_actual_exit': 1, 'old_gate_actual_wall_s': failed['wall_seconds'],
        'previous_binding_consumer': {'actual_exit': 1, 'wall_seconds': previous['wall_seconds'],
            'source_invocations_sha256': '883d1d6e43d8d40ed53208943c3854b68b3e92885aeac45c2d49ad942fe56c2e',
            'failure': previous['failure']},
        'old_consumer': {'source_invocations_sha256': '96dcff563e32299bda6710dcfa2314326be5b2a7e68f8ed649042ba481f258df',
                         'program_composition_sha256': '02185c3bad03196cd5a24c101dc4eceb357007fcb52f98757a4c3dbaa70a1f56'},
        'graph_decode_during_prepare': 0, 'source_payload_copies': 0, 'runtime_binary_freeze': 'OPEN'})
    print(json.dumps({'status': 'PREPARED_NOT_RUN', 'freeze': sha(HERE / 'freeze.json')}), flush=True)


def verify(freeze):
    assert sorted(str(path) for path in (ROOT / 'scar').rglob('*.py')) == sorted(row['uri'] for row in freeze['sources'])
    amount = 0
    for ref in (freeze['entry'], *freeze['sources'], *freeze['inputs']):
        measured = sha(Path(ref['uri']))
        assert measured == {key: ref[key] for key in measured}, 'frozen bytes changed: ' + ref['uri']
        amount += measured['size_bytes']
    return amount


def run():
    freeze = small(HERE / 'freeze.json')
    out = HERE / 'result'
    assert not out.exists()
    out.mkdir()
    started = time.monotonic()
    result = {'schema': 'scar.qualified-source-entry-binding-resume/1', 'status': 'RUNNING',
        'original_gate': {'exit': 1, 'wall_seconds': freeze['old_gate_actual_wall_s']},
        'previous_binding_consumer': freeze['previous_binding_consumer'],
        'publication': freeze['publication'], 'publication_repeated': False, 'lower_compile_prepare_target': 'NOT_RUN',
        'construction_operations': None, 'whole_model': 'OPEN', 'cumulative_all_input_IO': 'OPEN'}
    phase = 'precheck'
    try:
        result['precheck_stored_bytes_read'] = verify(freeze)
        from scar.analysis.model_run import _PinnedModelInputs
        from scar.analysis.source_entry_run import _terminal
        from scar.analysis.program_composition import CompositionIndex
        from scar.analysis.source_attachments import SourceAttachmentBudget
        from scar.analysis.compiler_witness_archives import CompilerWitnessArchives, CompilerArchiveBudget
        from scar.analysis.code_witness import CodeWitnessBudget
        from scar.analysis.source_invocations import bind_source_invocations
        from scar.ir.program.call_edges import CallEdgeBudget
        from scar.ir.record_codec import encode
        reader = _PinnedModelInputs(2_000_000)
        entry = small(Path(freeze['entry_terminal']['uri']))
        inputs = _terminal(entry['dependency_terminal']['uri'], reader)
        archives = CompilerWitnessArchives(tuple((str(Path(inputs[key]['uri']).parent), inputs[key]['sha256'])
            for key in ('archive', 'project_archive')),
            store_budget=CodeWitnessBudget(max_compile_keys=21, max_source_files=6, max_source_bytes=1_000_000,
                max_archive_bytes=32_000_000, max_manifest_bytes=2_000_000),
            budget=CompilerArchiveBudget(max_archives=2, max_total_modules=21, max_total_sources=6,
                                         max_declared_payload_bytes=32_000_000))
        before = [dict(archives.store_for(ref).counts) for ref in archives.receipts()]
        phase = 'ordinary-existing-publication-reader'
        composition = CompositionIndex.from_source_entry_publication(freeze['publication']['manifest'],
            expected_sha256=freeze['publication']['sha256'], archives=archives,
            attachment_budget=SourceAttachmentBudget(max_report_bytes=2_000_000, max_files=6, max_codes=16,
                max_roots=8, max_artifact_bytes=128_000_000, max_record_bytes=64_000_000, cached_files=1))
        queries = []
        for product in entry['products']['source_programs']:
            from scar.ir.program.source_references import SourceDefinitionReference
            from scar.ir.record_codec import decode
            definition = decode(SourceDefinitionReference, product['entry_reference'])
            reference = composition.body_reference(definition)
            typed = composition.typed_qualified_body(reference)
            assert reference.source_program.artifact.uri == product['source_program']['uri']
            assert reference.source_program.artifact.sha256 == product['source_program']['physical_sha256']
            assert typed.body.construction_operations is None and typed.body.graph.root == reference.identity
            queries.append({'definition': encode(definition), 'body': encode(reference), 'namespace': typed.namespace,
                'operations': len(typed.body.graph.operations), 'source_shape_verified': typed.source_shape_verified,
                'source_code_verified': typed.source_code_witness_verified, 'construction_operations': None})
        result['public_queries'] = queries
        phase = 'fresh-genuine-coordinates'
        coordinates, capture = helpers.genuine_coordinates(freeze['capture_model'], out / 'capture-coordinates.json', result)
        assert str(capture) == inputs['capture']
        phase = 'ordinary-same-capture-source-binder'
        report = bind_source_invocations(composition, coordinates, capture / 'trace', out / 'bindings',
            call_budget=CallEdgeBudget(**CALL_SCANNER), seed_verification_budget=CallEdgeBudget(**SEED_VERIFIER), witness_mode='same_capture')
        bindings = small(out / 'bindings/bindings.json')
        assert report['schema_version'] == bindings['schema_version'] == 4
        assert report['source_inputs'] == composition.source_inputs() == bindings['source_inputs']
        assert report['source_seed_verification_budget'] == SEED_VERIFIER
        assert report['actual_call_scan']['raw_bytes'] <= CALL_SCANNER['max_raw_bytes']
        old = small(Path(inputs['admissions']['uri']))
        expected = old['summary']
        assert len(bindings['bindings']) == expected['entered_code_groups']
        assert report['summary']['invocations'] == expected['entered_invocations']
        selected = {json.dumps(row['definition'], sort_keys=True) for row in queries}
        selected_groups = [row for row in bindings['bindings'] if json.dumps(row['definition'], sort_keys=True) in selected]
        assert all(row['body'] is not None and row['body']['kind'] == 'QUALIFIED_SOURCE_BODY'
                   and row['status'] == 'BODY_LINKED_REUSED_WITNESS'
                   and row['definition'] == row['body']['reference']['definition'] for row in selected_groups)
        assert selected_groups
        result['actual_body_linked_weight'] = sum(row['entered_invocations'] for row in selected_groups)
        result['binding_summary'] = report['summary']
        result['binding_root'] = sha(out / 'bindings/report.json')
        result['actual_call_scan'] = report['actual_call_scan']
        result['source_seed_verification_budget'] = report['source_seed_verification_budget']
        result['call_budget'] = report['call_budget']
        result['budget_roles'] = report['budget_roles']
        result['source_inputs'] = composition.source_inputs()
        result['remaining_groups'] = [{'code': row['code'], 'calls': row['entered_invocations'], 'status': row['status'],
            'frontiers': row['frontiers']} for row in bindings['bindings'] if row not in selected_groups]
        assert all(report[name] is False for name in ('actual_formal_routing_established', 'function_environment_established',
                                                     'state_versions_established', 'first_stage_complete'))
        result['readonly_activity'] = [{key: archives.store_for(ref).counts[key] - prior.get(key, 0)
            for key in archives.store_for(ref).counts} for ref, prior in zip(archives.receipts(), before)]
        assert all(row['compile_attempts'] == 0 for row in result['readonly_activity'])
        result['planning_io'] = {'stored': reader.stored_bytes, 'decoded': reader.decoded_bytes}
        result['postcheck_stored_bytes_read'] = verify(freeze)
        result['poststage_output_bytes'] = sum(path.stat().st_size for path in out.rglob('*') if path.is_file())
        assert result['poststage_output_bytes'] + len(json.dumps(result).encode()) < 128_000_000
        result['status'] = 'QUALIFIED_BODY_ASSOCIATIONS_WITH_OPEN'
    except BaseException as error:
        result.update(status='FAILED', failure={'phase': phase, 'type': type(error).__name__, 'detail': str(error),
                                                'traceback': traceback.format_exc()})
        try:
            result['post_failure_source_input_check_bytes'] = verify(freeze)
        except BaseException as check_error:
            result['post_failure_source_input_check_error'] = str(check_error)
    result['wall_seconds'] = time.monotonic() - started
    put(HERE / 'result.json', result)
    print(json.dumps({'status': result['status'], 'wall_seconds': result['wall_seconds'], 'failure': result.get('failure')}), flush=True)
    return int(result['status'] == 'FAILED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--head-label', default='root supplied; actual source bytes independently pinned')
    args = parser.parse_args()
    if args.prepare:
        prepare(args.head_label)
    else:
        raise SystemExit(run())
