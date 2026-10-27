"""Resolve a new test's premise against isolated, unchanged baseline code."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import textwrap

from scripts.run_gate import fingerprint


HERE = Path(__file__).resolve().parent
BASE = '51a6eb3354eb05f7c02c9ff189239166f2cd4081'
destination = HERE / 'subclass-baseline-probe.json'
assert not destination.exists()
before, sources = fingerprint()
payload = subprocess.check_output(['git', 'archive', BASE, 'scar', 'tests/fixtures',
                                   'tests/unit/test_execution_state_preservation.py'])
script = textwrap.dedent('''
    from dataclasses import fields
    import hashlib, json, pathlib, sys, types
    root = pathlib.Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    namespace = types.ModuleType('tests')
    namespace.__path__ = [str(root / 'tests')]
    sys.modules['tests'] = namespace
    from scar.ir.program import codec, state_address_validation
    from scar.ir.program.model import ProgramGraph
    from scar.ir.program.queries import ProgramIndex
    from scar.ir.program.validation import validate
    from tests.unit.test_execution_state_preservation import _preservation_program
    assert codec.SCHEMA_VERSION == 24
    for module in (codec, state_address_validation):
        assert pathlib.Path(module.__file__).resolve().is_relative_to(root)
    graph, _ = _preservation_program()
    assert validate(graph) == ()
    class Derived(ProgramGraph):
        pass
    derived = Derived(**{field.name: getattr(graph, field.name) for field in fields(graph)})
    issues = validate(derived)
    try:
        ProgramIndex(derived)
    except ValueError as exc:
        public = {'kind': 'ValueError', 'message': str(exc)}
    else:
        public = {'kind': 'ACCEPTED'}
    print(json.dumps({'reader_maximum': codec.SCHEMA_VERSION,
        'issues': [{'code': row.code, 'path': row.path, 'message': row.message} for row in issues],
        'public_index': public,
        'address_validator_sha256': hashlib.sha256(pathlib.Path(state_address_validation.__file__).read_bytes()).hexdigest()}))
''')
with tempfile.TemporaryDirectory(prefix='scar-subclass-baseline-') as directory:
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        archive.extractall(directory, filter='data')
    command = [sys.executable, '-c', script, directory]
    process = subprocess.run(command, cwd=directory,
        env={**os.environ, 'PYTHONPATH': directory, 'PYTHONDONTWRITEBYTECODE': '1'},
        capture_output=True, text=True)
    observation = None if process.returncode else json.loads(process.stdout)
after, final = fingerprint()
assert before == after and sources == final
record = {'base_revision': BASE, 'python': sys.version, 'python_executable': sys.executable,
    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'child_script': script, 'returncode': process.returncode,
    'stdout': process.stdout, 'stderr': process.stderr, 'observation': observation,
    'source_sha256_before': before, 'source_sha256_after': after, 'sources': sources,
    'tests_started': 0, 'source_runtime_verified': False}
destination.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({key: record[key] for key in ('returncode', 'observation',
    'source_sha256_before', 'source_sha256_after', 'tests_started')}, indent=2))
raise SystemExit(process.returncode)
