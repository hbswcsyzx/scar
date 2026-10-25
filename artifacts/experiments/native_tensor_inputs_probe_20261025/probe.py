"""One new CPU-only feature experiment; root reviews before running."""
from pathlib import Path
from hashlib import sha256
import json
import os
import sys
import time
import traceback

O = Path(__file__).resolve().parent
B = O.parents[2]


def pin_check(freeze):
    for row in freeze['sources'] + freeze['runner']:
        raw = (B / row['path']).read_bytes()
        if len(raw) != row['bytes'] or sha256(raw).hexdigest() != row['sha256']:
            raise ValueError('frozen file changed: ' + row['path'])


def main():
    freeze = json.loads((O / 'freeze.json').read_bytes())
    pin_check(freeze)
    if (O / 'trace').exists():
        raise ValueError('fresh probe trace required')
    # No CLI, OS collector, whole-bundle import, target process or GPU activity
    # is started. This one new feature experiment owns the normal collector.
    import torch
    from scar.trace.call_edges import CallEdgeRecorder
    from scar.trace.execution_evidence import ExecutionEvidence
    from scar.trace.native_tensor_inputs import read_native_tensor_inputs

    assert torch.version.git_version == freeze['provider_revision']
    os.environ['SCAR_TENSOR_PHYSICAL'] = '1'
    os.environ['SCAR_NATIVE_TENSOR_INPUTS'] = '1'
    recorder = CallEdgeRecorder(O / 'trace', O, max_events=10000, max_bytes=2000000)
    manager = ExecutionEvidence(O / 'trace', recorder=recorder, native_input_chunk_rows=2)
    if manager.status != 'RECORDING':
        raise AssertionError('owned CPU profiler did not start: ' + manager.status)
    raised_empty_list = False
    try:
        scalar = torch.ones((), device='cpu')
        other = scalar + 1
        joined = torch.cat([scalar.reshape(1), other.reshape(1)])
        torch.empty_like(scalar, memory_format=None)
        # The source/retention inventory must preserve a legal empty TensorList
        # input even though this ordinary operator then raises.
        try:
            torch.ops.aten.cat.default([], 0)
        except RuntimeError:
            raised_empty_list = True
        assert joined.device.type == 'cpu'
    finally:
        manager.close()
        recorder.close()
    assert manager.status == 'CLOSED'
    manifests = list((O / 'trace').glob('native-tensor-inputs.*/manifest.json'))
    assert len(manifests) == 1
    path = manifests[0]
    manifest_raw = path.read_bytes()
    observed = []
    verified = read_native_tensor_inputs(path, expected_sha256=sha256(manifest_raw).hexdigest(),
        max_bytes=16000000, max_rows=10000, on_row=observed.append)
    doc = json.loads(manifest_raw)
    assert len(doc['chunks']) >= 2 and len(observed) == doc['visited_torch_ops'] > 0
    all_tensors = []
    for row in observed:
        for slot in row['inputs']['slots']:
            if slot['kind'] == 'TENSOR':
                all_tensors.append(slot['metadata'])
            elif slot['kind'] == 'TENSOR_LIST':
                all_tensors.extend(item['metadata'] for item in slot['items'])
    assert all_tensors and any(t['sizes'] == [] for t in all_tensors)
    assert verified['counts'].get('TENSOR_LIST', 0) > 0
    assert verified['counts'].get('OPAQUE', 0) > 0
    assert verified['counts'].get('SCALAR_OPAQUE', 0) > 0
    assert all(row['inputs']['availability'] == 'OBSERVED' for row in observed)
    assert any(not row['name'].startswith('scar-dispatch:') for row in observed)
    # Actual output metadata remains unsupported, irrespective of held markers.
    assert verified['capabilities']['native_outputs'] == 'UNAVAILABLE_IN_PINNED_API'
    pin_check(freeze)
    imported = {str((B / row['path']).resolve()) for row in freeze['sources']}
    for module in tuple(sys.modules.values()):
        value = getattr(module, '__file__', None)
        if value:
            file = Path(value).resolve()
            if file.is_relative_to(B / 'scar') and file.suffix == '.py' and str(file) not in imported:
                raise AssertionError('unfrozen imported source: ' + str(file))
    return {'status': 'CPU_ACTUAL_NATIVE_INPUT_METADATA_RETAINED_AND_READ',
        'profile': verified['profile'], 'provider_revision': torch.version.git_version,
        'manifest': {'path': str(path), 'sha256': sha256(manifest_raw).hexdigest(), 'bytes': len(manifest_raw)},
        'reader': verified, 'chunks': len(doc['chunks']), 'observed_torch_ops': len(observed),
        'zero_dim_metadata_seen': True, 'empty_tensor_lists_seen': verified['counts'].get('empty_tensor_lists', 0),
        'empty_list_operation_raised': raised_empty_list,
        'actual_feature_CPU_capture_runs': 1, 'prior_witness_gate_CPU_capture_runs_unchanged': 1,
        'GPU_runs': 0, 'LeWM_runs': 0, 'old_raw_DB_reads': 0, 'new_native_full_gate_runs': 0,
        'ordinary_capture_membership_established': False, 'ETO_port_join_established': False,
        'old_1901_ports_newly_qualified': 0, 'logical_content_or_ready_established': False,
        'whole_model': 'OPEN'}


if __name__ == '__main__':
    if (O / 'result.json').exists() or (O / 'failure.json').exists():
        raise SystemExit('fresh feature output required')
    started = time.monotonic()
    try:
        result = main()
    except BaseException as error:
        with (O / 'failure.json').open('x') as target:
            json.dump({'status': 'FEATURE_CPU_PROBE_FAILED', 'type': type(error).__name__,
                'message': str(error), 'elapsed_seconds': time.monotonic() - started,
                'traceback': traceback.format_exc()}, target, indent=2, sort_keys=True)
            target.write('\n')
        raise
    result['elapsed_seconds'] = time.monotonic() - started
    with (O / 'result.json').open('x') as target:
        json.dump(result, target, indent=2, sort_keys=True)
        target.write('\n')
    print(json.dumps(result), flush=True)
