"""One root-authorized episode; ordinary capture CLI, then fresh public binding.

Preparation never executes this file. No imported historical runner, target
patch, optimization, graph import or qualification restored from JSON.
"""
from __future__ import annotations

import hashlib
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
TREE = HERE.parents[2]
PYTHON = Path('/home/zyf/miniconda3/envs/lewm/bin/python')
LEWM = Path('/home/zyf/AAA/le-wm')
CAPTURE = HERE / 'capture'
OUTPUT = HERE / 'lewm-output'
MAX_REPORT = 8_000_000


def need(value, message):
    if not value:
        raise ValueError(message)


def dump(name, value):
    raw = (json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2,
                      allow_nan=False) + '\n').encode('ascii')
    need(len(raw) <= MAX_REPORT, 'gate report byte budget')
    with (HERE / name).open('xb') as stream:
        stream.write(raw)


def digest(path):
    h = hashlib.sha256()
    n = 0
    with path.open('rb') as stream:
        while block := stream.read(1_048_576):
            h.update(block)
            n += len(block)
    return h.hexdigest(), n


def stamp(path):
    s = path.stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def verify_freeze(document, *, sources_only=False):
    rows = document['sources'] if sources_only else document['sources'] + document['controls'] + document['external_inputs']
    total = 0
    for item in rows:
        path = Path(item['uri'])
        actual, size = digest(path)
        total += size
        need((actual, size) == (item['sha256'], item['size_bytes']), 'frozen bytes changed: ' + str(path))
    actual_sources = sorted(str(p) for p in (TREE / 'scar').rglob('*.py'))
    need(actual_sources == [r['uri'] for r in document['sources']], 'main SCAR source inventory changed')
    return total


def small_json(path, limit=2_000_000):
    need(path.stat().st_size <= limit, 'metadata size budget: ' + str(path))
    raw = path.read_bytes()
    need(len(raw) <= limit, 'metadata changed size: ' + str(path))
    return json.loads(raw)


def imported_sources(freeze):
    expected = {r['uri']: r for r in freeze['sources']}
    rows = []
    for name, module in sorted(sys.modules.items()):
        if name != 'scar' and not name.startswith('scar.'):
            continue
        filename = getattr(module, '__file__', None)
        need(filename is not None, 'SCAR module without concrete file: ' + name)
        path = Path(filename).resolve()
        need(str(path) in expected, 'imported SCAR source outside main freeze: ' + str(path))
        h, n = digest(path)
        need((h, n) == (expected[str(path)]['sha256'], expected[str(path)]['size_bytes']), 'imported source changed')
        rows.append({'module': name, 'uri': str(path), 'sha256': h, 'size_bytes': n})
    return rows


def stop_owned_cli(cli):
    """Stop only this live CLI's exact planned strace child session, if any."""
    actions = []
    intents = sorted(CAPTURE.glob('os-capture-intent.*.json'))
    if len(intents) == 1 and cli.poll() is None:
        planned = small_json(intents[0])['actual_exec_argv_planned']
        children = Path('/proc') / str(cli.pid) / 'task' / str(cli.pid) / 'children'
        try:
            child_pids = children.read_text().split()
        except OSError:
            child_pids = []
        for token in child_pids:
            pid = int(token)
            try:
                base = Path('/proc') / token
                command = [os.fsdecode(v) for v in (base / 'cmdline').read_bytes().split(b'\0') if v]
                status = (base / 'status').read_text().splitlines()
                ppid = next(int(v.split(':', 1)[1]) for v in status if v.startswith('PPid:'))
                if command == planned and ppid == cli.pid and os.getpgid(pid) == pid:
                    os.killpg(pid, signal.SIGTERM)
                    actions.append({'provider_pid': pid, 'signal': 'SIGTERM', 'basis': 'own live CLI child, exact planned/proc argv, PPID and self-led group'})
            except (OSError, StopIteration):
                continue
    if cli.poll() is None:
        try:
            cli.wait(timeout=30)
        except subprocess.TimeoutExpired:
            cli.terminate()
            cli.wait(timeout=30)
    return actions


def main():
    started = time.monotonic()
    phase = 'PREFLIGHT'
    cli = None
    cli_count = 0
    result = {'schema': 'scar.lewm-joint-capture-gate-result', 'schema_version': 1,
              'status': 'STARTED', 'target_episodes_requested': 1,
              'sets_target_rlimit_as': False, 'whole_model_established': False}
    try:
        freeze = small_json(HERE / 'freeze.json', 4_000_000)
        result['preflight_hash_bytes'] = verify_freeze(freeze)
        need(Path(sys.executable).resolve() == PYTHON.resolve(), 'conda lewm interpreter required')
        need(Path.cwd().resolve() == TREE, 'gate cwd must be main tree')
        need(os.environ.get('PYTHONPATH') == str(TREE), 'exact main PYTHONPATH required')
        result['inherited_rlimit_as'] = list(resource.getrlimit(resource.RLIMIT_AS))
        need(resource.getrlimit(resource.RLIMIT_AS)[0] == resource.RLIM_INFINITY,
             'finite inherited RLIMIT_AS: gate does not change CUDA target address-space limit')
        need(not CAPTURE.exists() and not OUTPUT.exists(), 'one fresh capture/output only; never retry in place')
        need(not (HERE / 'STARTED.json').exists(), 'this root gate was already started')
        for row in freeze['stat_only_inputs']:
            need(stamp(Path(row['uri'])) == row['stat5'], 'stat-only dataset/root changed since freeze: ' + row['uri'])
        argv = small_json(HERE / 'COMMAND.json')
        env = {k: v for k, v in os.environ.items() if not k.startswith('SCAR_')}
        env.update(argv['environment'])
        need(env['PYTHONPATH'] == str(TREE), 'target must use main code')
        dump('STARTED.json', {'phase': phase, 'pid': os.getpid(), 'target_episodes_requested': 1,
                              'actual_cli_argv': argv['cli_argv'], 'target_argv': argv['target_argv'],
                              'cwd': argv['cwd'], 'selected_environment': argv['environment'],
                              'freeze_sha256': digest(HERE / 'freeze.json')[0]})
        dump('progress.json', {'phase': 'CAPTURE', 'elapsed_seconds': time.monotonic() - started})
        phase = 'CAPTURE'
        with (HERE / 'cli-stdout.txt').open('xb') as stdout, (HERE / 'cli-stderr.txt').open('xb') as stderr:
            cli = subprocess.Popen(argv['cli_argv'], cwd=argv['cwd'], env=env, stdout=stdout, stderr=stderr,
                                   start_new_session=True)
            cli_count += 1
            cli_returncode = cli.wait()
        result['cli_returncode'] = cli_returncode
        result['capture_elapsed_seconds'] = time.monotonic() - started
        launch_paths = sorted(CAPTURE.glob('os-capture-launch.*.json'))
        if len(launch_paths) == 1:
            launch = small_json(launch_paths[0])
            result['provider_returncode'] = launch['returncode']
            result['provider_budget_stop'] = launch['budget_stop']
            options = launch['actual_exec_argv'][1:launch['target_argv_index']]
            need(options.count('-s') == 1 and options[options.index('-s') + 1] == '4096', 'V2 actual strace string limit differs')
            need(launch['actual_exec_argv'][launch['target_argv_index']:] == argv['target_argv'], 'actual target argv differs')
            result['actual_provider_launch'] = {'uri': str(launch_paths[0]), 'sha256': digest(launch_paths[0])[0],
                                                'provider_pid': launch['provider_pid'], 'actual_string_limit': 4096}
        need(cli_returncode == 0, 'ordinary capture CLI failed; saved target/provider/failure artifacts are retained')
        need(len(launch_paths) == 1, 'one actual owned provider launch required')
        need(result['provider_returncode'] == 0 and result['provider_budget_stop'] is None, 'provider failed or budget stop')
        run_metadata = small_json(CAPTURE / 'trace/run.json')
        need(run_metadata['command'] == argv['target_argv'] and run_metadata['returncode'] == 0, 'actual target command/return differs')
        phase = 'ORDINARY_PUBLIC_BIND_AND_WITNESS'
        dump('capture-terminal.json', {'phase': phase, 'cli_returncode': cli_returncode,
                                       'run_metadata': run_metadata, 'elapsed_seconds': time.monotonic() - started})
        from scar.trace.capture_coordinates import bind_capture_coordinates
        from scar.trace.collector_execution_witness import bind_collector_execution_witness
        from scar.ir.record_codec import encode
        coordinates = bind_capture_coordinates(CAPTURE, max_bytes=4_000_000_000,
            max_lines=6_000_000, profile_uri=str(CAPTURE / 'capture-coordinates.json'), publish_os_profile=False)
        saved_coordinates = (CAPTURE / 'capture-coordinates.json').read_bytes()
        need(coordinates.payload == saved_coordinates, 'fresh ordinary coordinates differ from CLI publication')
        membership = coordinates.report['collector_execution_membership']
        need(membership['capability'] == 'SCAR_COLLECTOR_EXECUTION_MEMBERSHIP_V2', 'explicit V2 witness membership required')
        witness_artifact = membership['manifest']
        joined = bind_collector_execution_witness(witness_artifact['uri'],
            expected_sha256=witness_artifact['sha256'], coordinates=coordinates)
        dump('collector-binding.json', encode(joined))
        input_membership = coordinates.report['native_tensor_input_membership']
        need(input_membership['capability'] == 'SCAR_NATIVE_TENSOR_INPUT_MEMBERSHIP_V1', 'ordinary native input membership required')
        # The original closed native manifest is uncompressed metadata. Its
        # exact path comes from the already checked command PID/nonce family.
        native_paths = sorted((CAPTURE / 'trace').glob('execution-evidence.*.json'))
        need(len(native_paths) == 1, 'one target closed native lifecycle required')
        native = small_json(native_paths[0])
        need(native['status'] == 'CLOSED' and native['failures'] == [], 'native lifecycle has explicit failures')
        need(native['configuration']['native_tensor_input_observations']['requested'] is True,
             'native input retention was not requested')
        archive = small_json(CAPTURE / 'archive-index.json')
        from scar.trace.capture_coordinates import _Files
        metadata_files = _Files(CAPTURE, CAPTURE, archive, 2_000_000)
        companion, companion_artifact = metadata_files.document(
            Path(input_membership['manifest']['uri']), 'scar.native-tensor-input-trace')
        need(encode(companion_artifact) == input_membership['manifest'],
             'observer companion metadata differs from ordinary coordinate member')
        need(archive['verified_roundtrip'] is True and archive.get('capabilities') == ['COLLECTOR_WITNESS_MEMBERS_V2'],
             'lossless archive/witness capability differs')
        need(archive.get('retained_plain_members'), 'CodeWitness ordinary reader requires exact retained plain members')
        image_root = small_json(Path(witness_artifact['uri']).parent / 'process-images/manifest.json')
        call_meta = small_json(CAPTURE / 'trace' / ('call-meta.' + str(coordinates.target_process.pid) + '.json'))
        operand_meta = small_json(CAPTURE / 'trace' / ('call-operand-meta.' + str(coordinates.target_process.pid) + '.json'))
        result.update(status='ACTUAL_CAPTURE_AND_ORDINARY_MEMBERSHIP_WITH_OPEN',
            target_returncode=run_metadata['returncode'], run=encode(coordinates.run.id),
            target_process=encode(coordinates.target_process), coordinate_artifact=encode(coordinates.artifact),
            coordinate_open=coordinates.report['open'], witness_membership=membership,
            issuer=joined['issuer'], process_birth_join=joined.get('process_birth_join'),
            witness_frontiers=joined['frontiers'], native_input_membership=input_membership,
            observer_metadata_verified_bytes=metadata_files.total,
            companion_retention={k: companion[k] for k in ('status', 'retained_rows', 'visited_torch_ops', 'raw_bytes', 'frontier', 'transport_failure')},
            call_summary={k: call_meta.get(k) for k in ('events','event_attempts','invocations','invocation_attempts','codes','bytes','dropped_events','dropped_codes','unknown_exits','suspended_exits','open_invocations','errors','io_failed')},
            operand_summary={k: operand_meta.get(k) for k in ('events','bytes','dropped_events','errors','io_failed')},
            process_image_summary={k: image_root[k] for k in ('profile', 'actual_backing_bytes_read', 'frontiers')},
            archive_io_accounting=archive['io_accounting'], archive_entries=len(archive['files']),
            physical_outputs_and_port_joins_established=False, logical_values_state_ready_established=False,
            whole_model_established=False)
        result['parent_imports'] = imported_sources(freeze)
        result['post_source_hash_bytes'] = verify_freeze(freeze, sources_only=True)
        result['phase'] = 'COMPLETE'
    except BaseException as error:
        # Preserve a failed episode, no fallback, mutation or automatic retry.
        if cli is not None and cli.poll() is None:
            result['owned_stop_actions'] = stop_owned_cli(cli)
        result.update(status='FAILED', phase=phase, error_type=type(error).__name__, error=str(error),
                      traceback=traceback.format_exc())
        dump('FAILURE.json', result)
        traceback.print_exc()
        return 1
    finally:
        result['cli_popen_count'] = cli_count
        result['whole_elapsed_seconds'] = time.monotonic() - started
        dump('result.json', result)
    print(json.dumps({'status': result['status'], 'whole_elapsed_seconds': result['whole_elapsed_seconds'],
                      'whole_model_established': False}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
