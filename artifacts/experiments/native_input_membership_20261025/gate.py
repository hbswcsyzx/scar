"""One real CLI capture; the only wrapper observes closed plain artifacts."""
from contextlib import redirect_stdout, redirect_stderr
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import sys
import time
import traceback

O = Path(__file__).resolve().parent
B = O.parents[2]


def pin_check(freeze):
    for item in freeze['sources'] + freeze['runner']:
        raw = (B / item['path']).read_bytes()
        if len(raw) != item['bytes'] or sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('frozen bytes differ: ' + item['path'])


def membership(coordinates):
    from scar.ir.program.providers import ProviderArtifact
    from scar.ir.record_codec import decode
    cap = coordinates.report['native_tensor_input_membership']
    assert cap['capability'] == 'SCAR_NATIVE_TENSOR_INPUT_MEMBERSHIP_V1'
    assert len(cap['chunks']) >= 2
    for item in [cap['manifest'], *cap['chunks']]:
        assert coordinates.process_for(decode(ProviderArtifact, item), coordinates.target_process.pid) == coordinates.target_process
    assert not any(cap[key] for key in ('native_port_join_established', 'Python_identity_established',
        'geometry_established', 'logical_content_established', 'resource_ready_established'))
    assert cap['native_outputs'] == 'UNAVAILABLE_IN_PINNED_API'
    return cap


def main():
    freeze = json.loads((O / 'freeze.json').read_bytes())
    pin_check(freeze)
    capture = O / 'capture'
    assert not capture.exists()
    from scar.trace import os_capture_launch
    from scar.trace.capture_coordinates import bind_capture_coordinates, _Files
    from scar.trace.native_tensor_inputs import read_native_tensor_inputs
    from scar.cli import main as cli_main

    original_archive = os_capture_launch.archive_owned_capture
    state = {'postclose_archive_calls': 0}

    def observe_plain_then_archive(root, *, budgets=None):
        # CLI has already waited for the sole owned provider and written run.json.
        # This wrapper does not replace collection or the original archiver.
        state['postclose_archive_calls'] += 1
        assert state['postclose_archive_calls'] == 1 and Path(root) == capture
        plain = bind_capture_coordinates(root, max_bytes=budgets.max_raw_bytes,
            max_lines=budgets.max_os_lines, profile_uri=str(O / 'plain-coordinates.json'),
            allow_plain_owned_capture=True)
        cap = membership(plain)
        provider = plain.report['os_capture_provider']
        assert provider['selection_qualification'] == 'PENDING_LOSSLESS_ARCHIVE' and provider['profile'] is None
        assert any(gap['code'] == 'owned_archive_publication_pending' for gap in plain.report['open'])
        assert not list(capture.glob('os-capture-coverage.*.json'))
        (O / 'plain-coordinates.json').write_bytes(plain.payload)
        state.update(plain=plain, plain_cap=cap)
        return original_archive(root, budgets=budgets)

    os_capture_launch.archive_owned_capture = observe_plain_then_archive
    args = ['trace', '--call-operands', '--execution-evidence', '--tensor-physical',
        '--os-capture-root', str(capture), '--out', str(capture / 'trace'),
        '--project-root', str(O / 'target'), '--max-os-bytes', '128000000',
        '--max-capture-bytes', '256000000', '--max-archive-bytes', '128000000',
        '--os-timeout', '120', '--', sys.executable, '-B', str(O / 'target/probe.py')]
    os.environ['SCAR_NATIVE_TENSOR_INPUTS'] = '1'
    os.environ['SCAR_MEMBERSHIP_PROBE_RESULT'] = str(O / 'target-result.json')
    try:
        with (O / 'stdout.txt').open('x') as stdout, (O / 'stderr.txt').open('x') as stderr:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                actual_exit = cli_main(args)
    finally:
        os_capture_launch.archive_owned_capture = original_archive
    assert actual_exit == 0 and state['postclose_archive_calls'] == 1
    launches = list(capture.glob('os-capture-launch.*.json'))
    assert len(launches) == 1
    launch = json.loads(launches[0].read_bytes())
    command = [sys.executable, '-B', str(O / 'target/probe.py')]
    assert launch['target_argv'] == command and launch['returncode'] == 0
    assert launch['actual_exec_argv'][launch['target_argv_index']:] == command
    target = json.loads((O / 'target-result.json').read_bytes())
    assert target['expected_exception_type'] == 'ValueError'
    archived = bind_capture_coordinates(capture, max_bytes=256000000, max_lines=2000000,
        profile_uri=str(capture / 'capture-coordinates.json'))
    saved = (capture / 'capture-coordinates.json').read_bytes()
    assert archived.payload == saved
    cap = membership(archived)
    plain = state['plain']
    assert plain.run.id == archived.run.id and plain.target_process.id == archived.target_process.id
    assert state['plain_cap'] == cap
    assert archived.report['os_capture_provider']['selection_qualification'] == 'EXPLICIT_ARGV'
    archive = json.loads((capture / 'archive-index.json').read_bytes())
    files = _Files(capture.resolve(), PurePosixPath(archived.report['original_root']), archive, 256000000)
    checked = read_native_tensor_inputs(cap['manifest']['uri'], expected_sha256=cap['manifest']['sha256'],
        max_bytes=64000000, _retained_files=files)
    entries = {row['logical_path']: row for row in archive['files']}
    assert all(item['uri'] in entries for item in cap['chunks'])
    assert all(not Path(item['uri']).exists() and Path(entries[item['uri']]['actual_path']).is_file() for item in cap['chunks'])
    assert checked['retained_rows'] == cap['retained_rows']
    pin_check(freeze)
    return {'status': 'ONE_CLI_CAPTURE_NATIVE_INPUT_MEMBERSHIP_VERIFIED_WITH_OPEN_MODEL',
        'CLI_actual_exit': actual_exit, 'actual_command': command,
        'actual_owned_exec_argv': launch['actual_exec_argv'], 'owned_Popen_receipts': 1,
        'postclose_archive_calls': state['postclose_archive_calls'], 'CPU_captures_this_gate': 1,
        'plain_RunID': plain.run.id.value, 'archive_RunID': archived.run.id.value,
        'plain_archive_RunID_equal': True, 'plain_provider_status': 'PENDING_LOSSLESS_ARCHIVE',
        'archive_provider_status': 'EXPLICIT_ARGV', 'plain_coverage_profile_published': False,
        'new_member_artifacts': 1 + len(cap['chunks']), 'retained_rows': checked['retained_rows'],
        'native_input_reader': checked, 'all_new_members_process_for_exact_target': True,
        'coordinate_payload_sha256': sha256(saved).hexdigest(),
        'original_URI_namespace_preserved': True, 'native_outputs': 'UNAVAILABLE_IN_PINNED_API',
        'open_obligations': archived.report['open'], 'LeWM_runs': 0, 'GPU_runs': 0,
        'old_raw_DB_reads': 0, 'old1901_newly_qualified': 0,
        'native_port_or_C_value_ready_qualified': False, 'whole_model': 'OPEN'}


if __name__ == '__main__':
    if (O / 'result.json').exists() or (O / 'failure.json').exists():
        raise SystemExit('fresh gate output required')
    start = time.monotonic()
    try:
        result = main()
    except BaseException as error:
        with (O / 'failure.json').open('x') as out:
            json.dump({'status': 'MEMBERSHIP_GATE_FAILED', 'type': type(error).__name__,
                'message': str(error), 'elapsed_seconds': time.monotonic() - start,
                'traceback': traceback.format_exc()}, out, indent=2, sort_keys=True)
            out.write('\n')
        raise
    result['elapsed_seconds'] = time.monotonic() - start
    with (O / 'result.json').open('x') as out:
        json.dump(result, out, indent=2, sort_keys=True)
        out.write('\n')
    print(json.dumps(result), flush=True)
