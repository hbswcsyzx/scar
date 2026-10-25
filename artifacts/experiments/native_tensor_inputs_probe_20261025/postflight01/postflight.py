"""Root-owned offline read of the saved failed CPU experiment; no Torch import."""
from pathlib import Path
from hashlib import sha256
import json
import sys
import time
import traceback

P = Path(__file__).resolve().parent
O = P.parent
B = P.parents[3]


def pin_check(rows):
    for row in rows:
        raw = (B / row['path']).read_bytes()
        if len(raw) != row['bytes'] or sha256(raw).hexdigest() != row['sha256']:
            raise ValueError('offline frozen bytes differ: ' + row['path'])


def main():
    freeze = json.loads((P / 'freeze.json').read_bytes())
    pin_check(freeze['files'])
    original = json.loads((O / 'freeze.json').read_bytes())
    failure = json.loads((O / 'failure.json').read_bytes())
    assert failure['type'] == 'ValueError' and 'expected a non-empty list of Tensors' in failure['message']
    from scar.trace.native_tensor_inputs import read_native_tensor_inputs
    assert 'torch' not in sys.modules

    path = B / freeze['native_input_manifest']['path']
    raw = path.read_bytes()
    doc = json.loads(raw)
    observations = []
    verified = read_native_tensor_inputs(path,
        expected_sha256=freeze['native_input_manifest']['sha256'],
        max_bytes=16000000, max_rows=10000, on_row=observations.append)
    assert len(doc['chunks']) == 22 and len(observations) == doc['visited_torch_ops'] == 43
    tensors = []
    for row in observations:
        for slot in row['inputs']['slots']:
            if slot['kind'] == 'TENSOR':
                tensors.append(slot['metadata'])
            elif slot['kind'] == 'TENSOR_LIST':
                tensors.extend(item['metadata'] for item in slot['items'])
    assert tensors and any(value['sizes'] == [] for value in tensors)
    assert verified['counts'].get('TENSOR_LIST', 0) > 0
    assert verified['counts'].get('OPAQUE', 0) > 0
    assert verified['counts'].get('SCALAR_OPAQUE', 0) > 0
    assert all(row['inputs']['availability'] == 'OBSERVED' for row in observations)
    assert any(not row['name'].startswith('scar-dispatch:') for row in observations)
    assert verified['capabilities']['native_outputs'] == 'UNAVAILABLE_IN_PINNED_API'
    # Check the actual saved RAISED receipt rather than revising the first exit.
    receipt = doc['inputs']['dispatch_observations']
    dispatch = Path(receipt['path'])
    assert dispatch.parent == path.parent.parent and dispatch.stat().st_size <= 1000000
    data = dispatch.read_bytes()
    assert len(data) == receipt['raw_bytes'] and sha256(data).hexdigest() == receipt['raw_sha256']
    rows = [json.loads(line) for line in data.splitlines()]
    assert len(rows) == receipt['lines']
    raised = [row for row in rows if row['kind'] == 'DISPATCH_END' and row['outcome'] == 'RAISED']
    assert len(raised) == 1
    begin = next(row for row in rows if row['sequence'] == raised[0]['sequence'] and row['kind'] == 'DISPATCH_BEGIN')
    pin_check(freeze['files'])
    # The existing 355-source freeze is reused; only imported local files need
    # reading. No new whole-source freeze or historical raw validation occurs.
    source_pins = {str((B / row['path']).resolve()): row for row in original['sources']}
    imported = []
    for module in tuple(sys.modules.values()):
        value = getattr(module, '__file__', None)
        if value is None:
            continue
        source = Path(value).resolve()
        if source.is_relative_to(B / 'scar') and source.suffix == '.py':
            assert str(source) in source_pins, 'unfrozen local imported source: ' + str(source)
            imported.append(source_pins[str(source)])
    pin_check(imported)
    assert 'torch' not in sys.modules
    return {'status': 'OFFLINE_SAVED_NATIVE_INPUT_RETENTION_VERIFIED', 'consumer_only': True,
        'original_root_session': 12421, 'original_actual_exit': 1,
        'original_failure_type': failure['type'], 'original_failure_message': failure['message'],
        'original_failure_cause': 'probe caught RuntimeError but actual intended empty-list operation raised ValueError',
        'actual_dispatch_raised': {'sequence': raised[0]['sequence'], 'end_index': raised[0]['index'],
            'begin_index': begin['index'], 'operator': begin['operator']},
        'saved_dispatch_bytes_read': len(data), 'native_input_manifest': freeze['native_input_manifest'],
        'reader': verified, 'chunks': 22, 'observed_torch_ops': 43,
        'zero_dim_metadata_seen': True, 'empty_tensor_lists_seen': verified['counts'].get('empty_tensor_lists', 0),
        'feature_CPU_captures': 1, 'prior_witness_CPU_gate_captures': 1,
        'postflight_new_CPU_captures': 0, 'Torch_imported': False,
        'GPU_runs': 0, 'LeWM_runs': 0, 'old_raw_DB_reads': 0, 'full_native_runs': 0,
        'ordinary_capture_membership_established': False, 'ETO_port_join_established': False,
        'old_1901_ports_newly_qualified': 0, 'logical_content_or_ready_established': False,
        'whole_model': 'OPEN'}


if __name__ == '__main__':
    if (P / 'result.json').exists() or (P / 'failure.json').exists():
        raise SystemExit('fresh offline output required')
    started = time.monotonic()
    try:
        result = main()
    except BaseException as error:
        with (P / 'failure.json').open('x') as target:
            json.dump({'status': 'OFFLINE_POSTFLIGHT_FAILED', 'type': type(error).__name__,
                'message': str(error), 'elapsed_seconds': time.monotonic() - started,
                'traceback': traceback.format_exc()}, target, indent=2, sort_keys=True)
            target.write('\n')
        raise
    result['elapsed_seconds'] = time.monotonic() - started
    with (P / 'result.json').open('x') as target:
        json.dump(result, target, indent=2, sort_keys=True)
        target.write('\n')
    print(json.dumps(result), flush=True)
