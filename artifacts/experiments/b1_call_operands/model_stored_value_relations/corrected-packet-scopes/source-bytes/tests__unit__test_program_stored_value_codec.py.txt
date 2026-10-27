"""New slot capability must preserve an independently executed Program26 wire."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import textwrap

import pytest

from scar.ir.program import codec
from tests.fixtures.program_async_initial_control_graphs import async_initial_control_program
from tests.fixtures.execution_stored_values import stored_values_execution


ROOT = Path(__file__).resolve().parents[2]
BASE = '5fd5a7f0b246f72ff708f53ba000728817a8feca'
CODEC_SHA = '7aeb4f0dd1716f1bcde5434410551e0fd1114871f68111c840b6a9cf71f1e076'
FIXTURE_SHA = '3923a8fb36b4d1516df929e83ebf7591e7bfcd14e90378f922ea3a482abe35de'


def test_independent_program26_encoder_preserves_all_old_fields_tags_and_bytes(tmp_path):
    frozen = tmp_path / 'program26'
    frozen.mkdir()
    archive = tmp_path / 'source.tar'
    with archive.open('wb') as target:
        subprocess.run(['git', 'archive', BASE, 'scar', 'tests/fixtures'],
                       cwd=ROOT, stdout=target, check=True)
    with tarfile.open(archive) as source:
        source.extractall(frozen, filter='data')
    script = textwrap.dedent('''
        import hashlib, json, pathlib, sys, types
        root = pathlib.Path(sys.argv[1]).resolve()
        sys.path.insert(0, str(root))
        tests = types.ModuleType('tests')
        tests.__path__ = [str(root / 'tests')]
        sys.modules['tests'] = tests
        from scar.ir.program import codec, model
        from tests.fixtures import program_async_initial_control_graphs as fixture
        assert codec.SCHEMA_VERSION == 26
        for module in (codec, model, fixture):
            assert pathlib.Path(module.__file__).resolve().is_relative_to(root)
        graph, _ = fixture.async_initial_control_program(scenario='created-none')
        wire = codec.dumps(graph).encode('ascii')
        assert json.loads(wire)['schema_version'] == 26
        (root / 'oracle.json').write_bytes(wire)
        print(json.dumps({
            'codec_sha256': hashlib.sha256(pathlib.Path(codec.__file__).read_bytes()).hexdigest(),
            'fixture_sha256': hashlib.sha256(pathlib.Path(fixture.__file__).read_bytes()).hexdigest(),
            'wire_sha256': hashlib.sha256(wire).hexdigest(), 'wire_bytes': len(wire)}))
    ''')
    result = subprocess.run([sys.executable, '-B', '-c', script, str(frozen)], cwd=frozen,
        check=True, capture_output=True, text=True,
        env={**os.environ, 'PYTHONPATH': str(frozen), 'PYTHONDONTWRITEBYTECODE': '1'})
    proof = json.loads(result.stdout)
    assert proof['codec_sha256'] == CODEC_SHA and proof['fixture_sha256'] == FIXTURE_SHA
    wire = (frozen / 'oracle.json').read_bytes()
    assert hashlib.sha256(wire).hexdigest() == proof['wire_sha256']
    assert len(wire) == proof['wire_bytes']
    graph, _ = async_initial_control_program(scenario='created-none')
    assert graph.stored_value_reads == graph.stored_value_writes == ()
    assert codec.dumps(graph).encode('ascii') == wire
    assert codec.loads(wire.decode('ascii')) == graph
    print(json.dumps({**proof, 'source_revision': BASE}, sort_keys=True))


def test_program27_requires_a_nonempty_stored_value_capability():
    graph, _, _ = stored_values_execution()
    document = json.loads(codec.dumps(graph))
    assert document['schema_version'] == 27
    document['stored_value_writes'] = document['stored_value_reads'] = []
    with pytest.raises(ValueError, match='requires explicit stored value capability'):
        codec.loads(json.dumps(document))


def test_program26_cannot_smuggle_new_tables_even_when_they_are_empty():
    graph, _ = async_initial_control_program(scenario='created-none')
    document = json.loads(codec.dumps(graph))
    assert document['schema_version'] == 26
    document.update(stored_value_reads=[], stored_value_writes=[])
    with pytest.raises(ValueError, match='top-level fields'):
        codec.loads(json.dumps(document))
