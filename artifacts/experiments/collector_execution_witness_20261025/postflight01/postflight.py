"""Root-owned offline postflight; consumes the sole saved CPU capture only."""
from pathlib import Path
from hashlib import sha256
import json
import sys
import time
import traceback

P = Path(__file__).resolve().parent
O = P.parent
B = P.parents[3]


def read_pin(item):
    payload = (B / item['path']).read_bytes()
    if len(payload) != item['bytes'] or sha256(payload).hexdigest() != item['sha256']:
        raise ValueError('postflight frozen bytes differ: ' + item['path'])
    return payload


def check_freeze(freeze):
    for item in freeze['sources'] + freeze['runner'] + freeze['inputs']:
        read_pin(item)


def main():
    from scar.trace.capture_coordinates import bind_capture_coordinates
    from scar.trace.collector_execution_witness import (
        bind_collector_execution_witness, read_collector_execution_witness)
    from scar.ir.record_codec import encode

    freeze = json.loads((P / 'freeze.json').read_bytes())
    check_freeze(freeze)
    coord_path = O / 'capture/capture-coordinates.json'
    saved = coord_path.read_bytes()
    # Use the ordinary public binder, never reconstruct its private membership
    # owner from report data. The retained small CPU capture is read offline.
    coordinates = bind_capture_coordinates(O / 'capture', max_bytes=300000000,
        max_lines=500000, profile_uri=str(coord_path), publish_os_profile=False)
    if coordinates.payload != saved:
        raise ValueError('offline coordinates differ from the CLI saved bytes')
    witness_path = O / freeze['witness_relative_to_experiment']
    raw = witness_path.read_bytes()
    digest = sha256(raw).hexdigest()
    doc = read_collector_execution_witness(witness_path, expected_sha256=digest)
    observed = json.loads((O / 'observed-registration.json').read_bytes())
    if observed['issuer'] != doc['issuer'] or observed['process_id'] != doc['registration_scope']['process_id']:
        raise ValueError('saved actual-hook observation differs from witness')
    binding = bind_collector_execution_witness(witness_path,
        expected_sha256=digest, coordinates=coordinates)
    if len(binding['schema_views']) != 1 or binding['schema_views'][0]['rule'] != 'SCAR_CALL_META_SCHEMA1_TO_COORDINATE_FAMILY_META_V1':
        raise ValueError('unexpected schema view mapping inventory')
    # The original sole negative is now saved outside the immutable sidecar.
    # Its fresh SHA is supplied, so rejection must precede hash/path checks.
    bad = json.loads(raw)
    bad['issuer']['generation'] = 2
    candidate = json.dumps(bad, sort_keys=True).encode()
    bad_path = P / 'rejected-generation-candidate.json'
    with bad_path.open('xb') as target:
        target.write(candidate)
    try:
        read_collector_execution_witness(bad_path, expected_sha256=sha256(candidate).hexdigest())
    except ValueError as error:
        rejection = str(error)
    else:
        raise AssertionError('re-sealed changed issuer was accepted')
    if rejection != 'collector issuer generation/process mismatch':
        raise AssertionError('negative rejected for another reason: ' + rejection)
    check_freeze(freeze)
    pinned = {str((B / item['path']).resolve()) for item in freeze['sources']}
    unexpected = []
    for module in tuple(sys.modules.values()):
        file = getattr(module, '__file__', None)
        if file is None:
            continue
        path = Path(file).resolve()
        if path.is_relative_to(B) and path.suffix == '.py' and str(path) not in pinned and path != Path(__file__).resolve():
            unexpected.append(str(path))
    if unexpected:
        raise ValueError('unfrozen local imported source: ' + repr(sorted(unexpected)))
    return {'status': 'SAVED_CPU_SHARED_REGISTRATION_CLOSED_AND_POSTCAPTURE_BOUND',
        'consumer_only': True, 'saved_coordinates_byte_equal': True,
        'coordinates_sha256': sha256(saved).hexdigest(),
        'witness': {'uri': str(witness_path), 'sha256': digest, 'size_bytes': len(raw)},
        'binding': encode(binding), 'changed_issuer_rejected': rejection,
        'candidate_resealed': True, 'roles': observed['roles'],
        'original_CPU_capture_runs': 1, 'new_target_runs': 0, 'LeWM_runs': 0,
        'GPU_runs': 0, 'new_full_native_runs': 0,
        'original_gate_status': 'FAILED_AT_POSTCAPTURE_BINDER_SCHEMA_VIEW',
        'original_producer_freeze': freeze['original_producer_freeze'],
        'producer_source_archive': freeze['producer_source_archive'],
        'consumer_source': next(x for x in freeze['sources'] if x['path'] == 'scar/trace/collector_execution_witness.py'),
        'whole_model': 'OPEN', 'logical_content_ready_established': False}


if __name__ == '__main__':
    if (P / 'result.json').exists() or (P / 'failure.json').exists():
        raise SystemExit('fresh offline postflight output required')
    started = time.monotonic()
    try:
        result = main()
    except BaseException as error:
        failure = {'status': 'OFFLINE_POSTFLIGHT_FAILED', 'type': type(error).__name__,
            'message': str(error), 'elapsed_seconds': time.monotonic() - started,
            'new_target_runs': 0, 'traceback': traceback.format_exc()}
        with (P / 'failure.json').open('x') as target:
            json.dump(failure, target, indent=2, sort_keys=True)
            target.write('\n')
        raise
    result['elapsed_seconds'] = time.monotonic() - started
    with (P / 'result.json').open('x') as target:
        json.dump(result, target, indent=2, sort_keys=True)
        target.write('\n')
    print(json.dumps(result), flush=True)
