"""Retain one final focused attempt; never retry or start a full suite."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
out = HERE / sys.argv[1]
out.mkdir(parents=True, exist_ok=False)
fingerprint = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']


def write(name, value):
    (out / name).write_text(json.dumps(value, indent=2) + '\n')


before = fingerprint()
write('source.before.json', {'source_sha256': before[0], 'files': before[1]})
owned = Path(tempfile.mkdtemp(prefix='scar-protocol-final-focus-'))
command = [sys.executable, '-m', 'pytest', '-q',
    'tests/unit/test_program_protocol_records.py',
    'tests/unit/test_program_protocol_codec.py',
    'tests/unit/test_program_protocol_connections.py',
    'tests/unit/test_program_protocol_ledger.py',
    'tests/unit/test_program_protocol_release_connections.py',
    'tests/unit/test_program_protocol_path_safety.py',
    'tests/unit/test_program_literal_codec.py',
    'tests/unit/test_program_resumption_codec.py::test_resumption_graph_uses_strict_v10_tagged_wire_and_roundtrips',
    'tests/unit/test_program_driver_codec.py::test_raw_only_create_without_drive_and_full_driver_each_select_v11',
    'tests/unit/test_program_publication_codec.py::test_scoped_body_publication_roundtrips_as_v12_without_adding_other_d2_tables',
    'tests/unit/test_program_no_body_codec.py::test_no_body_and_predicate_only_roundtrip_without_publishing_future_d2_tables',
    'tests/unit/test_program_session_release_codec.py::test_session_release_roundtrip_preserves_all_canonical_producers',
    'tests/unit/test_lifecycle_composition_codec.py::test_immutable_d2_3_v14_wire_is_unchanged_by_query_scope_views',
    'tests/unit/test_program_state_address_codec.py::test_v15_roundtrip_keeps_single_access_mode_and_original_producers',
    '--junitxml=' + str(out / 'junit.xml'), '--basetemp=' + str(owned), '-p', 'no:cacheprovider']
write('command.json', {'command': command, 'cwd': str(ROOT), 'python': sys.version,
    'activation': 'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm',
    'environment': {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(ROOT)},
    'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
started = time.perf_counter()
result = subprocess.run(command, cwd=ROOT,
    env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT)),
    capture_output=True, text=True)
(out / 'stdout.log').write_text(result.stdout)
(out / 'stderr.log').write_text(result.stderr)
after = fingerprint()
write('source.after.json', {'source_sha256': after[0], 'files': after[1]})
shutil.rmtree(owned)
report = {'returncode': result.returncode, 'duration_seconds': time.perf_counter() - started,
          'source_unchanged_during_test': before == after,
          'owned_basetemp_removed_after_child_exit': str(owned)}
write('report.json', report)
print(json.dumps(report))
print(result.stdout[-16000:])
print(result.stderr[-2000:])
raise SystemExit(result.returncode or int(before != after))
