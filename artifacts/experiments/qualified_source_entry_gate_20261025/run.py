"""One independent SP5 admission/query/ordinary-binding gate. Root runs it."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CLI = ROOT / 'artifacts/experiments/model_run_source_entries_gate_20261025'
ENTRY = CLI / 'model/attempts/1792962847383051508-1430458/terminal.json'


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


def prepare(label):
    assert not (HERE / 'freeze.json').exists()
    prior = small(CLI / 'freeze.json')
    inputs = {ref['uri']: {key: ref[key] for key in ('uri', 'sha256', 'size_bytes')} for ref in prior['inputs']}
    entry = small(ENTRY)
    assert entry['partial_route'] == 'SOURCE_ENTRIES_ONLY'
    inputs[str(ENTRY)] = sha(ENTRY)
    dependency_ref = entry['dependency_terminal']
    dependency = small(Path(dependency_ref['uri']))
    original_ref = dependency['input_terminal']
    original = small(Path(original_ref['uri']))
    for ref in (dependency_ref, original_ref, original['products']['capture_model'], original['products']['source_coordinates']):
        inputs[ref['uri']] = {key: ref[key] for key in ('uri', 'sha256', 'size_bytes')}
    for product in entry['products']['source_programs']:
        ref = product['source_program']
        assert Path(ref['uri']).stat().st_size == ref['physical_bytes']
        inputs[ref['uri']] = {'uri': ref['uri'], 'sha256': ref['physical_sha256'], 'size_bytes': ref['physical_bytes']}
    coordinates = small(Path(original['products']['source_coordinates']['uri']))
    capture = Path(coordinates['local_root'])
    controls = [capture / 'archive-index.json', capture / 'trace/run.json']
    native = [row for row in coordinates['membership'] if row['artifact']['schema'] == 'scar.execution-evidence-collection']
    assert len(native) == 1
    controls.append(Path(native[0]['local_path']))
    native_meta = small(controls[-1])
    for ref in (coordinates['os_capture_provider']['launch'], coordinates['os_capture_provider']['profile'],
                native_meta['configuration']['os_capture_intent']['intent']):
        controls.append(Path(ref['uri']))
    for path in controls:
        inputs[str(path)] = sha(path)
    sources = [sha(path) for path in sorted((ROOT / 'scar').rglob('*.py'))]
    put(HERE / 'freeze.json', {'schema': 'scar.qualified-source-entry-gate-freeze/1', 'head_label': label,
        'entry': sha(Path(__file__).resolve()), 'sources': sources, 'inputs': list(inputs.values()),
        'entry_terminal': inputs[str(ENTRY)], 'capture_model': original['products']['capture_model'],
        'raw_inputs': 'actual ordinary coordinate/call readers independently verify declared raw members; not opened in prepare',
        'source_payload_copies': 0, 'SP5_graph_decode_during_prepare': 0, 'runtime_binary_freeze': 'OPEN',
        'budget': {'programs': 1, 'operations_per_body': 4000, 'selecteddecode': 128_000_000,
            'record': 64_000_000, 'output_poststage': 128_000_000, 'metadata': 2_000_000,
            'call_raw': 2_000_000, 'call_lines': 2048, 'call_events': 1024,
            'coordinate_stored_plus_decoded_reservations': 64_000_000, 'external_seconds': 180}})
    print(json.dumps({'status': 'PREPARED_NOT_RUN', 'freeze': sha(HERE / 'freeze.json'),
                      'sources': len(sources), 'inputs': len(inputs)}), flush=True)


def verify(freeze):
    assert sorted(str(path) for path in (ROOT / 'scar').rglob('*.py')) == sorted(row['uri'] for row in freeze['sources'])
    amount = 0
    for ref in (freeze['entry'], *freeze['sources'], *freeze['inputs']):
        measured = sha(Path(ref['uri']))
        assert measured == {key: ref[key] for key in measured}, 'frozen bytes changed: ' + ref['uri']
        amount += measured['size_bytes']
    return amount


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


def run():
    freeze = small(HERE / 'freeze.json')
    output = HERE / 'result'
    assert not output.exists()
    output.mkdir()
    started = time.monotonic()
    result = {'schema': 'scar.qualified-source-entry-gate/1', 'status': 'RUNNING',
        'construction_operations': None, 'whole_model': 'OPEN', 'global_source858_runtime843_changed': False,
        'lower_compile_prepare_target': 'NOT_RUN', 'cumulative_all_input_IO': 'OPEN'}
    phase = 'precheck'
    def progress(row):
        print(json.dumps({'phase': phase, 'progress': row}), flush=True)
    try:
        result['precheck_stored_bytes_read'] = verify(freeze)
        from scar.analysis.model_run import _PinnedModelInputs
        from scar.analysis.source_entry_run import _terminal
        from scar.analysis.source_attachments import SourceAttachments, SourceAttachmentBudget
        from scar.analysis.compiler_witness_archives import CompilerWitnessArchives, CompilerArchiveBudget
        from scar.analysis.code_witness import CodeWitnessBudget
        from scar.analysis.program_composition import CompositionIndex
        from scar.analysis.source_entry_catalog import SourceEntryCatalog
        from scar.analysis.source_program_publication import publish_source_entries
        from scar.analysis.source_invocations import bind_source_invocations
        from scar.ir.program.call_edges import CallEdgeBudget
        from scar.ir.record_codec import encode
        reader = _PinnedModelInputs(2_000_000)
        terminal = small(ENTRY)
        inputs = _terminal(terminal['dependency_terminal']['uri'], reader)
        result['planning_io'] = {'stored': reader.stored_bytes, 'decoded': reader.decoded_bytes}
        attachments_budget = SourceAttachmentBudget(max_report_bytes=2_000_000, max_files=6, max_codes=16,
            max_roots=8, max_artifact_bytes=128_000_000, max_record_bytes=64_000_000, cached_files=1)
        archives = CompilerWitnessArchives(tuple((str(Path(inputs[key]['uri']).parent), inputs[key]['sha256'])
            for key in ('archive', 'project_archive')),
            store_budget=CodeWitnessBudget(max_compile_keys=21, max_source_files=6, max_source_bytes=1_000_000,
                max_archive_bytes=32_000_000, max_manifest_bytes=2_000_000),
            budget=CompilerArchiveBudget(max_archives=2, max_total_modules=21, max_total_sources=6,
                                         max_declared_payload_bytes=32_000_000))
        before = [dict(archives.store_for(ref).counts) for ref in archives.receipts()]
        parent = CompositionIndex(inputs['project_composition']['uri'], max_input_bytes=64_000_000, max_record_bytes=64_000_000)
        owner = SourceAttachments.from_admissions(inputs['admissions']['uri'], expected_report_sha256=inputs['admissions']['sha256'],
                                                  project_root=inputs['project_root'], budget=attachments_budget)
        catalog = SourceEntryCatalog(archives=archives, projects=(parent,), admissions=(owner,),
                                     max_groups=16, max_candidates=16, max_selected_decode_bytes=128_000_000)
        metadata = catalog.metadata()
        requests = []
        for product in terminal['products']['source_programs']:
            reference = product['entry_reference']
            candidates = [row for row in metadata['candidates'] if all(row['basis'][name] == reference[field]
                for name, field in (('source_snapshot', 'snapshot'), ('definition', 'definition'), ('source', 'source')))]
            assert len(candidates) == 1, 'saved qualified entry has no unique original catalog candidate'
            requests.append({'entry_key': candidates[0]['entry_key'], 'source_program': product['source_program']})
        assert len(requests) == 1  # profile window, never an operation/function name
        result['original_denominators'] = {key: metadata[key] for key in ('entered_code_groups', 'entered_invocations')}
        result['candidate_entries'] = len(metadata['candidates'])
        phase = 'independent-publication'
        publication = publish_source_entries(parent, catalog, tuple(requests), output / 'publication', progress=progress)
        result['publication'] = publication
        result['publisher_catalog_measurements'] = catalog.measurements()
        phase = 'ordinary-publication-reader'
        composition = CompositionIndex.from_source_entry_publication(publication['manifest'], expected_sha256=publication['sha256'],
            archives=archives, attachment_budget=attachments_budget)
        queries = []
        for request in requests:
            entry = catalog.resolve(request['entry_key'])
            body_ref = composition.body_reference(entry.reference)
            typed = composition.typed_qualified_body(body_ref)
            assert body_ref.source_program.artifact.uri == request['source_program']['uri']
            assert body_ref.source_program.artifact.sha256 == request['source_program']['physical_sha256']
            assert typed.body.graph.root == body_ref.identity and typed.body.construction_operations is None
            queries.append({'definition': encode(entry.reference), 'body': encode(body_ref), 'namespace': typed.namespace,
                'operations': len(typed.body.graph.operations), 'source_shape_verified': typed.source_shape_verified,
                'source_code_verified': typed.source_code_witness_verified, 'construction_operations': None})
        result['public_queries'] = queries
        result['source_inputs'] = composition.source_inputs()
        result['parent_inputs_unchanged'] = parent.source_inputs() == catalog.inputs()['projects'][0]
        assert result['parent_inputs_unchanged']
        phase = 'genuine-coordinate-acquisition'
        coordinates, capture = genuine_coordinates(freeze['capture_model'], output / 'capture-coordinates.json', result)
        assert str(capture) == inputs['capture']
        phase = 'ordinary-same-capture-source-binder'
        report = bind_source_invocations(composition, coordinates, capture / 'trace', output / 'bindings',
            call_budget=CallEdgeBudget(max_raw_bytes=2_000_000, max_lines=2048, max_line_bytes=1_000_000,
                max_processes=4, max_codes=16, max_events=1024), witness_mode='same_capture')
        bindings = small(output / 'bindings/bindings.json')
        result['binding_root'] = sha(output / 'bindings/report.json')
        result['binding_summary'] = report['summary']
        assert report['schema_version'] == bindings['schema_version'] == 4
        assert report['source_inputs'] == composition.source_inputs() == bindings['source_inputs']
        assert len(bindings['bindings']) == metadata['entered_code_groups']
        assert report['summary']['invocations'] == metadata['entered_invocations']
        selected = {request['entry_key'] for request in requests}
        selected_weight = sum(row['entered_invocations'] for row in metadata['groups'] if row.get('entry_key') in selected)
        body_rows = [row for row in bindings['bindings'] if row['body'] is not None]
        assert sum(row['entered_invocations'] for row in body_rows) == selected_weight
        assert all(row['body']['kind'] == 'QUALIFIED_SOURCE_BODY' and row['status'] == 'BODY_LINKED_REUSED_WITNESS'
                   and row['definition'] == row['body']['reference']['definition'] for row in body_rows)
        result['actual_body_linked_weight'] = sum(row['entered_invocations'] for row in body_rows)
        result['remaining_groups'] = [{'code': row['code'], 'calls': row['entered_invocations'], 'status': row['status'],
            'frontiers': row['frontiers']} for row in bindings['bindings'] if row['body'] is None]
        assert all(report[name] is False for name in ('actual_formal_routing_established', 'function_environment_established',
                                                     'state_versions_established', 'first_stage_complete'))
        result['readonly_activity'] = [{key: archives.store_for(ref).counts[key] - prior.get(key, 0)
            for key in archives.store_for(ref).counts} for ref, prior in zip(archives.receipts(), before)]
        assert all(row['compile_attempts'] == 0 for row in result['readonly_activity'])
        result['postcheck_stored_bytes_read'] = verify(freeze)
        result['poststage_output_bytes'] = sum(path.stat().st_size for path in output.rglob('*') if path.is_file())
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
    parser.add_argument('--head-label', default='root supplied; actual source hashes separately pinned')
    args = parser.parse_args()
    if args.prepare:
        prepare(args.head_label)
    else:
        raise SystemExit(run())
