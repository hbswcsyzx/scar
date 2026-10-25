"""Offline completion after a gate-only launch-field KeyError; no target run."""
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import sys
import time
import traceback

P = Path(__file__).resolve().parent
O = P.parent
B = P.parents[3]


def main():
    freeze = json.loads((P / 'freeze.json').read_bytes())
    cache = {}

    def read(item):
        name = item['path']
        if name not in cache:
            raw = (B / name).read_bytes()
            if len(raw) != item['bytes'] or sha256(raw).hexdigest() != item['sha256']:
                raise ValueError('postflight frozen bytes differ: ' + name)
            cache[name] = raw
        return cache[name]

    for item in freeze['files']:
        read(item)
    pins = {item['label']: item for item in freeze['inputs']}
    original = json.loads(read(pins['original_freeze']))
    failure = json.loads(read(pins['original_failure']))
    assert failure['type'] == 'KeyError' and failure['message'] == "'target_argv'"
    # One retained plain payload read; it remains a historical report. No
    # CaptureCoordinates object or live authority is reconstructed from JSON.
    plain_raw = read(pins['plain_coordinates'])
    plain = json.loads(plain_raw)
    launch = json.loads(read(pins['launch']))
    intent = json.loads(read(pins['intent']))
    command_receipt = json.loads(read(pins['command']))
    target = json.loads(read(pins['target_result']))
    capture = O / 'capture'
    command = [sys.executable, '-B', str(O / 'target/probe.py')]
    assert command_receipt['command'] == command and command_receipt['returncode'] == 0
    assert launch['schema'] == 'scar.os-capture-launch' and launch['schema_version'] == 2
    assert launch['status'] == 'CLOSED' and launch['returncode'] == 0
    assert launch['failure'] is None and launch['budget_stop'] is None
    boundary = launch['target_argv_index']
    assert type(boundary) is int and 0 < boundary < len(launch['actual_exec_argv'])
    assert launch['actual_exec_argv'][boundary:] == command == intent['target_argv']
    assert intent['actual_exec_argv_planned'] == launch['actual_exec_argv']
    assert launch['intent']['uri'] == str(B / pins['intent']['path'])
    assert launch['intent']['sha256'] == pins['intent']['sha256']
    assert launch['intent']['size_bytes'] == pins['intent']['bytes']
    assert target['expected_exception_type'] == 'ValueError'

    from scar.trace.capture_coordinates import bind_capture_coordinates, _Files
    from scar.trace.native_tensor_inputs import read_native_tensor_inputs
    from scar.ir.program.providers import ProviderArtifact
    from scar.ir.record_codec import decode

    archived = bind_capture_coordinates(capture, max_bytes=256000000, max_lines=2000000,
        profile_uri=str(capture / 'capture-coordinates.json'))
    archived_saved = read(pins['archived_coordinates'])
    assert archived.payload == archived_saved
    cap = archived.report['native_tensor_input_membership']
    assert cap == plain['native_tensor_input_membership']
    assert cap['capability'] == 'SCAR_NATIVE_TENSOR_INPUT_MEMBERSHIP_V1' and len(cap['chunks']) >= 2
    process = archived.target_process
    members = [cap['manifest'], *cap['chunks']]
    plain_members = {row['artifact']['uri']: row for row in plain['membership']}
    plain_creations = {row['logical_path'] for row in plain['evidence']
        if row['kind'] == 'EXCLUSIVE_ARTIFACT_CREATION'}
    for item in members:
        assert archived.process_for(decode(ProviderArtifact, item), process.pid) == process
        observed = plain_members[item['uri']]
        assert observed['artifact'] == item and observed['process'] == plain['target_process']
        assert item['uri'] in plain_creations
    assert plain['run']['id']['value'] == archived.run.id.value
    assert plain['target_process']['value'] == process.id.value
    seed_keys = {'profile', 'archive_sha256', 'native_manifest_sha256', 'command_sha256', 'target_exec', 'target_birth'}
    assert set(plain['seed']) == set(archived.report['seed']) == seed_keys
    identity_seed = dict(plain['seed'], archive_sha256=None)
    assert identity_seed == dict(archived.report['seed'], archive_sha256=None)
    canonical = json.dumps(identity_seed, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()
    assert archived.run.id.value == 'capture:' + sha256(canonical).hexdigest()
    assert plain['seed']['archive_sha256'] is None
    assert archived.report['seed']['archive_sha256'] == pins['archive_index']['sha256']
    assert plain['os_capture_provider']['selection_qualification'] == 'PENDING_LOSSLESS_ARCHIVE'
    assert plain['os_capture_provider']['profile'] is None
    assert any(gap['code'] == 'owned_archive_publication_pending' for gap in plain['open'])
    assert archived.report['os_capture_provider']['selection_qualification'] == 'EXPLICIT_ARGV'
    archive = json.loads(read(pins['archive_index']))
    files = _Files(capture.resolve(), PurePosixPath(archived.report['original_root']), archive, 256000000)
    checked = read_native_tensor_inputs(cap['manifest']['uri'], expected_sha256=cap['manifest']['sha256'],
        max_bytes=64000000, _retained_files=files)
    entries = {row['logical_path']: row for row in archive['files']}
    assert all(item['uri'] in entries for item in cap['chunks'])
    assert all(not Path(item['uri']).exists() and Path(entries[item['uri']]['actual_path']).is_file() for item in cap['chunks'])
    assert checked['retained_rows'] == cap['retained_rows']
    assert not any(cap[key] for key in ('native_port_join_established', 'Python_identity_established',
        'geometry_established', 'logical_content_established', 'resource_ready_established'))
    assert cap['native_outputs'] == 'UNAVAILABLE_IN_PINNED_API'
    # Check actual imports against the original source freeze without restoring
    # any private runtime owner or scanning a second capture.
    source_pins = {str((B / item['path']).resolve()): item for item in original['sources']}
    for module in tuple(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if name:
            path = Path(name).resolve()
            if path.is_relative_to(B / 'scar') and path.suffix == '.py':
                assert str(path) in source_pins, 'unfrozen imported source'
                pin = source_pins[str(path)]
                fresh = path.read_bytes()
                assert len(fresh) == pin['bytes'] and sha256(fresh).hexdigest() == pin['sha256'], 'imported source changed'
    assert 'torch' not in sys.modules
    return {'status': 'OFFLINE_NATIVE_INPUT_MEMBERSHIP_AND_ENCODING_INVARIANCE_VERIFIED',
        'original_target_exit': 0, 'original_CLI_exit': 0, 'original_outer_exit': 1,
        'original_outer_failure': 'gate read nonexistent launch.target_argv; actual launch schema2 uses actual_exec_argv and target_argv_index',
        'actual_command': command, 'actual_owned_exec_argv': launch['actual_exec_argv'],
        'owned_launch_receipts': 1, 'original_CPU_captures_this_gate': 1, 'new_CPU_captures': 0,
        'plain_payload_read_count': 1, 'plain_payload_sha256': pins['plain_coordinates']['sha256'],
        'plain_live_owner_restored': False, 'plain_RunID': plain['run']['id']['value'],
        'archive_RunID': archived.run.id.value, 'plain_archive_RunID_equal': True,
        'identity_seed_fields_unchanged': True, 'new_members_are_not_identity_seed_fields': True,
        'plain_provider_status': 'PENDING_LOSSLESS_ARCHIVE', 'plain_coverage_published': False,
        'archive_provider_status': 'EXPLICIT_ARGV', 'new_member_artifacts': len(members),
        'retained_rows': checked['retained_rows'], 'native_input_reader': checked,
        'archived_process_for_all_new_members_exact': True,
        'recorded_plain_members_have_exact_target_and_creation_facts': True,
        'original_URI_namespace_preserved': True, 'native_outputs': 'UNAVAILABLE_IN_PINNED_API',
        'open_obligations': archived.report['open'], 'Torch_imported': False,
        'LeWM_GPU_old_raw_DB_runs': 0, 'old1901_newly_qualified': 0,
        'native_port_C_value_ready_qualified': False, 'whole_model': 'OPEN'}


if __name__ == '__main__':
    if (P / 'result.json').exists() or (P / 'failure.json').exists():
        raise SystemExit('fresh offline postflight output required')
    start = time.monotonic()
    try:
        result = main()
    except BaseException as error:
        with (P / 'failure.json').open('x') as out:
            json.dump({'status': 'OFFLINE_MEMBERSHIP_POSTFLIGHT_FAILED', 'type': type(error).__name__,
                'message': str(error), 'elapsed_seconds': time.monotonic() - start,
                'traceback': traceback.format_exc()}, out, indent=2, sort_keys=True)
            out.write('\n')
        raise
    result['elapsed_seconds'] = time.monotonic() - start
    with (P / 'result.json').open('x') as out:
        json.dump(result, out, indent=2, sort_keys=True)
        out.write('\n')
    print(json.dumps(result), flush=True)
