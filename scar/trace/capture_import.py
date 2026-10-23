"""Assemble existing evidence adapters in one verified capture coordinate space.

This is an execution-evidence assembly, not a substitute ProgramSnapshot.
Canonical source/control/value/effect/ready gaps remain explicit.  Source,
Torch and OS adapters retain their own fact IDs; only proved execution
coordinates are shared before any output snapshot is hashed.
"""
from __future__ import annotations

import gc
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
import time

from scar.ir.execution.common import EvidencePoint
from scar.ir.execution.resources import EndedAt
from scar.ir.record_codec import encode


def _write(path, document):
    """Serialize metadata without one gzip write per JSON punctuation token."""
    path = Path(path)
    with path.open('xb') as raw:
        compressed = gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) if path.suffix == '.gz' else raw
        try:
            with io.TextIOWrapper(compressed, encoding='utf-8', write_through=False) as text:
                json.dump(document, text, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
                text.write('\n')
        finally:
            if compressed is not raw:
                compressed.close()
    return path


def _stored(path):
    with Path(path).open('rb') as stream:
        digest = sha256()
        while block := stream.read(1_048_576):
            digest.update(block)
    return {'path': str(Path(path).resolve()), 'stored_sha256': digest.hexdigest(),
            'stored_bytes': Path(path).stat().st_size}


def _check_native_coordinates(document, coordinates):
    expected_run, process = encode(coordinates.run), encode(coordinates.target_process)
    if document['runs'] != [expected_run] or document['processes'] != [process]:
        raise ValueError('native adapter did not use the exact bound capture run/process')
    count = 0
    for row in document['target_lifetime_events']:
        point = row['at']
        if point['run'] != expected_run['id'] or point['process'] != process['id']:
            raise ValueError('native lifetime escaped shared capture coordinates')
        count += 1
    return count


def _check_os_coordinates(fragment, coordinates):
    if fragment.run != coordinates.run:
        raise ValueError('OS adapter changed the shared run declaration')
    processes = {process.id: process for process in coordinates.processes}
    threads = {thread.id: thread for thread in coordinates.threads}
    for process in fragment.processes:
        if processes.get(process.id) != process:
            raise ValueError('OS process does not equal the bound process declaration')
    for thread in fragment.threads:
        if threads.get(thread.id) != thread:
            raise ValueError('OS thread does not equal the bound thread declaration')
    points = []
    points.extend(row.at for row in fragment.target_lifetime_events)
    for row in fragment.handles:
        points.append(row.start)
        if type(row.end) is EndedAt:
            points.append(row.end.point)
    missing = 0
    for point in points:
        if type(point) is not EvidencePoint or point.run != coordinates.run.id:
            raise ValueError('OS evidence point escaped shared run coordinates')
        if point.process is not None and point.process not in processes:
            raise ValueError('OS evidence point uses an unbound process')
        missing += point.process is None
    return {'points_checked': len(points), 'points_with_unresolved_process': missing}


def import_capture(capture_dir, output_dir, *, max_bytes=1_000_000_000, max_lines=2_000_000,
                   schema_contracts=False, bundle_partitions=False, progress=None):
    """Import an unmodified successful collector capture, without target execution.

    The membership binder validates the original artifacts once.  The existing
    native and OS adapters independently validate their own provider contracts.
    Stored outputs include both the identity joins and their unresolved edges.
    """
    from scar.trace.capture_coordinates import bind_capture_coordinates
    from scar.trace.native_import import import_native_evidence
    from scar.trace.native_memory_export import export_native_memory
    from scar.trace.os_resources import import_os_resources

    capture, out = Path(capture_dir).resolve(), Path(output_dir).resolve()
    if out.exists():
        raise ValueError('capture import requires a fresh output directory')
    out.mkdir(parents=True)
    started, stages, outputs = time.perf_counter(), [], []

    def stage(name, status, **detail):
        record = {'stage': name, 'status': status, 'elapsed_s': time.perf_counter() - started, **detail}
        stages.append(record)
        payload = {'schema': 'scar.capture-import-progress', 'schema_version': 1,
                   'stages': stages, 'whole_model_established': False}
        temporary = out / '.progress.tmp'
        temporary.write_text(json.dumps(payload, indent=2) + '\n')
        temporary.replace(out / 'progress.json')
        if progress is not None:
            progress(record)

    try:
        stage('coordinates', 'RUNNING')
        coordinates = bind_capture_coordinates(capture, max_bytes=max_bytes, max_lines=max_lines,
            profile_uri=str(out / 'capture-coordinates.json'))
        (out / 'capture-coordinates.json').write_bytes(coordinates.payload)
        outputs.append(_stored(out / 'capture-coordinates.json'))
        stage('coordinates', 'IMPORTED', **coordinates.report['counts'])
        manifests = list((capture / 'trace').glob('execution-evidence.*.json'))
        if len(manifests) != 1:
            raise ValueError('capture manifest became ambiguous after membership validation')
        manifest = json.loads(manifests[0].read_bytes())
        members = coordinates.report['membership']
        def member_path(logical):
            matches = [row.get('local_path', row['artifact']['uri']) for row in members if row['logical_path'] == logical]
            if len(matches) != 1:
                raise ValueError('member has no exact bound artifact: ' + logical)
            return matches[0]
        def native_path(field):
            return member_path(manifest['artifacts'][field]['path'])
        native_out = out / 'native'
        native_out.mkdir()
        stage('native', 'RUNNING')
        native = import_native_evidence(native_path('execution_trace'), native_path('kineto'),
            max_bytes=max_bytes, provider_revision=manifest['provider']['torch_git_version'])
        dispatch_config = manifest.get('configuration', {}).get('dispatch_observations')
        if dispatch_config is not None and dispatch_config.get('started') is True:
            from scar.trace.dispatch_import import import_dispatch_bridge
            original_trace = str(Path(manifest['artifacts']['kineto']['path']).parent)
            pid = manifest['pid']
            stage('dispatch_bridge', 'RUNNING')
            import_dispatch_bridge(native,
                member_path(dispatch_config['events']), member_path(dispatch_config['metadata']),
                member_path(original_trace + f'/call-events.{pid}.jsonl'),
                member_path(original_trace + f'/call-codes.{pid}.jsonl'),
                member_path(original_trace + f'/call-meta.{pid}.json'),
                native_manifest_path=member_path(original_trace + '/' + manifests[0].name),
                coordinates=coordinates, max_bytes=max_bytes, max_events=max_lines)
            bridge = native.report['dispatch_bridge']
            _write(native_out / 'dispatch-bridge.json.gz', bridge)
            stage('dispatch_bridge', 'IMPORTED', dispatches=bridge['dispatches'],
                  slot_associations=bridge['slot_associations'], gaps=bridge['gaps'])
        physical_config = manifest.get('configuration', {}).get('tensor_physical_observations')
        if physical_config is not None and physical_config.get('requested') is True:
            from scar.trace.tensor_physical_import import import_tensor_physical
            stage('tensor_physical', 'RUNNING')
            physical = import_tensor_physical(native, member_path(physical_config['events']),
                member_path(physical_config['metadata']), coordinates=coordinates, max_bytes=max_bytes,
                max_rows=max_lines)
            _write(native_out / 'tensor-physical.json.gz', physical)
            stage('tensor_physical', 'IMPORTED_WITH_OPEN_OBLIGATIONS',
                marker_nodes=physical.get('marker_nodes', 0),
                physical_slots=physical.get('physical_slot_associations', 0),
                allocation_epochs=physical.get('allocation_epochs', 0), gaps=physical['gaps'])
        if schema_contracts:
            from scar.trace.native_schema import recover_schema_contracts
            stage('native_schema', 'RUNNING')
            schema = recover_schema_contracts(native, provider_revision=manifest['provider']['torch_git_version'])
            _write(native_out / 'schema-contracts.json.gz', schema)
            stage('native_schema', 'IMPORTED', schemas=schema['unique_schemas_parsed'],
                  formal_slots=schema['formal_slots'], actual_tensor_slot_counts=schema['actual_tensor_slot_counts'])
        memory = export_native_memory(native, native_out, coordinates=coordinates)
        checked_lifetimes = _check_native_coordinates(memory, coordinates) if memory is not None else 0
        if memory is not None:
            _write(native_out / 'native-memory-values.json.gz', native.bundle.values.to_dict())
            _write(native_out / 'native-memory-lifetimes.json.gz', memory)
        if bundle_partitions:
            from scar.store.bundle_partitions import publish_bundle
            stage('bundle_partitions', 'RUNNING')
            partition_manifest = publish_bundle(native.bundle, native_out / 'bundle-partitions',
                progress=lambda record: stage('bundle_partitions', 'WRITING', detail=record))
            stage('bundle_partitions', 'PUBLISHED_WITH_OPEN_OBLIGATIONS')
        else:
            _write(native_out / 'evidence-bundle.json.gz', native.bundle.to_dict())
        _write(native_out / 'provider-references.json.gz', native.references)
        _write(native_out / 'resource-observations.json.gz', native.resources)
        _write(native_out / 'import-report.json.gz', native.report)
        native_summary = {key: value for key, value in native.report.items()
                          if key not in ('memory', 'artifacts', 'dispatch_bridge', 'native_schema', 'tensor_physical') and not isinstance(value, list)}
        if 'dispatch_bridge' in native.report:
            native_summary['dispatch_bridge'] = {key: value for key, value in native.report['dispatch_bridge'].items()
                                                if key not in ('observations', 'paths', 'artifacts')}
        if 'native_schema' in native.report:
            native_summary['native_schema'] = {key: value for key, value in native.report['native_schema'].items()
                                              if key not in ('bindings', 'unqualified_without_schema')}
        if 'tensor_physical' in native.report:
            native_summary['tensor_physical'] = {key: value for key, value in native.report['tensor_physical'].items()
                                                 if key not in ('associations', 'epochs')}
        native_summary['memory'] = {key: value for key, value in native.report.get('memory', {}).items()
                                    if key not in ('records', 'source_artifact')}
        native_summary['shared_lifetime_points_checked'] = checked_lifetimes
        outputs.extend(_stored(path) for path in sorted(native_out.rglob('*')) if path.is_file())
        stage('native', 'IMPORTED', cpu_rf_matches=native.report['cpu_rf_matches'],
              runtime_gpu_matches=native.report['runtime_gpu_matches'], lifetime_points=checked_lifetimes)
        del native, memory
        gc.collect()
        stage('os_resources', 'RUNNING')
        os_out = out / 'os'
        os_out.mkdir()
        os_fragment = import_os_resources(capture / 'os', scope='capture-import',
            root_tid=manifest['pid'], max_bytes=max_bytes, max_lines=max_lines, coordinates=coordinates)
        os_check = _check_os_coordinates(os_fragment, coordinates)
        (os_out / 'os-resource-profile.json').write_bytes(os_fragment.protocol_bytes)
        _write(os_out / 'os-resources.json.gz', os_fragment.to_dict())
        _write(os_out / 'summary.json', os_fragment.summary)
        outputs.extend(_stored(path) for path in sorted(os_out.iterdir()))
        os_summary = dict(os_fragment.summary, coordinate_check=os_check)
        stage('os_resources', 'IMPORTED', **os_fragment.summary)
        del os_fragment
        gc.collect()
        required = [
            {'id': 'canonical_program_snapshot', 'status': 'OPEN', 'reason': 'source regions and call interfaces still need whole-program composition'},
            {'id': 'python_torch_occurrence', 'status': 'OPEN', 'reason': 'shared capture membership is not an invocation-to-RF mapping'},
            {'id': 'logical_value_provenance', 'status': 'OPEN', 'reason': 'provider object/storage tokens do not prove logical content versions'},
            {'id': 'source_state_effects', 'status': 'OPEN', 'reason': 'observations require source read/write and completion correspondences'},
            {'id': 'resource_lifetime_ready', 'status': 'OPEN', 'reason': 'profiler receipts and OS handles do not close every resource lifetime/ready interface'},
        ]
        report = {'schema': 'scar.capture-model', 'schema_version': 1, 'capture': str(capture),
            'coordinate_binding': encode(coordinates.artifact), 'run': encode(coordinates.run),
            'processes': encode(coordinates.processes), 'threads': encode(coordinates.threads),
            'native': native_summary, 'os': os_summary, 'outputs': outputs,
            'coordinate_identity_consistent': True, 'coverage_obligations': required,
            'whole_model_established': False, 'source_runtime_verified': False,
            'transformation_authorized': False, 'elapsed_s': time.perf_counter() - started}
        if bundle_partitions:
            report['native_bundle_storage'] = {'kind': 'partitioned',
                'manifest': str(native_out / 'bundle-partitions' / 'manifest.json'),
                'publication_is_model_completeness': False}
        _write(out / 'capture-model.json', report)
        stage('capture', 'IMPORTED_WITH_OPEN_OBLIGATIONS', coordinate_identity_consistent=True)
        return report
    except BaseException as error:
        stage('capture', 'FAILED', error=type(error).__name__ + ': ' + str(error))
        raise


__all__ = ['import_capture']
