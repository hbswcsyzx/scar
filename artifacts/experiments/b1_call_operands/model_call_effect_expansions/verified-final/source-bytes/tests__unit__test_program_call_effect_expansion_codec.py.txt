"""Program25 effect coverage is explicit; historical wire remains historical.

The Program24 oracle is encoded by an isolated immutable archive. Only root's
serial test runner executes that archive or any of these tests.
"""
from dataclasses import fields, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import textwrap

import pytest

from scar.ir.execution import codec as execution_codec
from scar.ir.program import codec
from scar.ir.program.call_effect_expansion import (
    CALL_EFFECT_EXPANSION_RECORD_TAGS, CallEffectExpansion,
)
from scar.ir.program.ids import OperationID, RegionID
from scar.ir.program.model import ProgramGraph, TerminatorKind
from scar.ir.program.validation import require_valid
from scar.ir.record_codec import encode
from tests.fixtures.program_async_competition_graphs import async_competition_program
from tests.fixtures.program_call_return_graphs import call_return_program
from tests.fixtures.program_call_return_state_graphs import call_return_state_program


REPOSITORY = Path(__file__).resolve().parents[2]
ORACLE_REVISION = '51a6eb3354eb05f7c02c9ff189239166f2cd4081'
ORACLE_CODEC_SHA256 = 'ccbdd1299224c569aa3b15f3275b3d0ba25ff5fe5c57ad100293e27c6739837d'


def _program(kind='call'):
    if kind == 'invoke':
        original, details = call_return_state_program()
        call = details['callers']['a']['operation']
    else:
        original, details = call_return_program()
        call = next(op for op in original.operations if op.id == details['root_calls'][0])
    require_valid(original)
    row = CallEffectExpansion(call.id, call.callee)
    graph = replace(original, call_effect_expansions=(row,))
    require_valid(graph)
    return graph, original, row


@pytest.mark.parametrize('kind', ('call', 'invoke'))
def test_program25_roundtrip_preserves_original_calls_effects_and_all_completion_ports(kind):
    graph, original, row = _program(kind)
    assert not codec._has_session_occupancy_capability(graph)
    wire = codec.dumps(graph)
    document = json.loads(wire)
    assert codec.SCHEMA_VERSION == document['schema_version'] == 25
    assert execution_codec.SCHEMA_VERSION == 8
    assert set(document) == {field.name for field in fields(ProgramGraph)} | {'schema', 'schema_version'}
    assert document['call_effect_expansions'] == [
        encode(row, record_tags=CALL_EFFECT_EXPANSION_RECORD_TAGS)]
    assert set(document['call_effect_expansions'][0]) == {'kind', 'operation', 'callee'}
    assert document['call_effect_expansions'][0]['kind'] == 'CALL_EFFECT_EXPANSION'
    recovered = codec.loads(wire)
    assert recovered == graph and codec.dumps(recovered) == wire
    assert recovered.operations == original.operations
    assert recovered.values == original.values
    assert recovered.regions == original.regions
    call = next(op for op in recovered.operations if op.id == row.operation)
    assert call.callee == row.callee
    if kind == 'invoke':
        assert call.terminator.kind is TerminatorKind.INVOKE
        assert call.completions == next(op for op in original.operations if op.id == call.id).completions
        assert call.terminator == next(op for op in original.operations if op.id == call.id).terminator


@pytest.mark.parametrize('fault', ('missing-tag', 'wrong-tag'))
def test_program25_requires_the_new_records_own_explicit_tag(fault):
    graph, _, _ = _program()
    document = json.loads(codec.dumps(graph))
    row = document['call_effect_expansions'][0]
    if fault == 'missing-tag':
        del row['kind']
    else:
        row['kind'] = 'PROTOCOL_REQUEST_ASSOCIATION'
    with pytest.raises(ValueError, match='typed record (fields|discriminator) mismatch'):
        codec.loads(json.dumps(document))


@pytest.mark.parametrize('version', (2, 24))
def test_historical_headers_reject_both_tagged_and_empty_new_tables(version):
    if version == 2:
        original, _ = call_return_program()
    else:
        original, _ = async_competition_program(reject_raised=False, known_association=True)
    wire = codec.dumps(original)
    document = json.loads(wire)
    assert document['schema_version'] == version
    assert 'call_effect_expansions' not in document
    assert codec.loads(wire) == original
    call = next(op for op in original.operations if op.callee is not None)
    row = CallEffectExpansion(call.id, call.callee)
    document['call_effect_expansions'] = [encode(row, record_tags=CALL_EFFECT_EXPANSION_RECORD_TAGS)]
    assert document['call_effect_expansions'][0]['kind'] == 'CALL_EFFECT_EXPANSION'
    with pytest.raises(ValueError, match='incorrect top-level fields'):
        codec.loads(json.dumps(document))
    document['call_effect_expansions'] = []
    with pytest.raises(ValueError, match='incorrect top-level fields'):
        codec.loads(json.dumps(document))


def test_program25_requires_a_nonempty_explicit_effect_expansion():
    graph, _, _ = _program()
    document = json.loads(codec.dumps(graph))
    document['call_effect_expansions'] = []
    with pytest.raises(ValueError, match='schema version 25 requires explicit call effect expansion capability'):
        codec.loads(json.dumps(document))


def test_program25_cannot_omit_its_new_table():
    graph, _, _ = _program()
    document = json.loads(codec.dumps(graph))
    del document['call_effect_expansions']
    with pytest.raises(ValueError, match='incorrect top-level fields'):
        codec.loads(json.dumps(document))


@pytest.mark.parametrize('fault,code', (
    ('missing-operation', 'call_effect_expansion_operation'),
    ('missing-region', 'call_effect_expansion_region'),
    ('different-callee', 'call_effect_expansion_callee'),
    ('primitive', 'call_effect_expansion_callee'),
))
def test_typed_wire_does_not_bypass_the_original_call_and_callee_foreign_keys(fault, code):
    graph, original, row = _program()
    document = json.loads(codec.dumps(graph))
    encoded = document['call_effect_expansions'][0]
    if fault == 'missing-operation':
        encoded['operation'] = encode(OperationID('effect-expansion.absent.call'))
    elif fault == 'missing-region':
        encoded['callee'] = encode(RegionID('effect-expansion.absent.region'))
    elif fault == 'different-callee':
        encoded['callee'] = encode(original.root)
    else:
        primitive = next(op for op in original.operations if op.callee is None)
        encoded['operation'] = encode(primitive.id)
    assert row.callee in {region.id for region in original.regions}
    with pytest.raises(ValueError, match=code):
        codec.loads(json.dumps(document))


def test_wire_cannot_duplicate_one_calls_expansion_natural_key():
    graph, _, _ = _program()
    document = json.loads(codec.dumps(graph))
    document['call_effect_expansions'].append(dict(document['call_effect_expansions'][0]))
    with pytest.raises(ValueError, match='call effect expansion operations'):
        codec.loads(json.dumps(document))


def test_expansion_wire_keeps_operation_and_region_id_namespaces_separate():
    graph, _, row = _program()
    document = json.loads(codec.dumps(graph))
    document['call_effect_expansions'][0]['operation'] = encode(row.callee)
    with pytest.raises((TypeError, ValueError)):
        codec.loads(json.dumps(document))


def test_expansion_wire_cannot_invent_a_purity_or_preservation_fact():
    graph, _, _ = _program()
    document = json.loads(codec.dumps(graph))
    document['call_effect_expansions'][0]['pure'] = True
    with pytest.raises(ValueError, match='typed record fields mismatch'):
        codec.loads(json.dumps(document))


def test_deleting_the_relation_restores_the_exact_original_wire_without_adding_an_empty_table():
    graph, original, _ = _program()
    historical_wire = codec.dumps(original)
    assert json.loads(historical_wire)['schema_version'] == 2
    assert 'call_effect_expansions' not in json.loads(historical_wire)
    recovered = codec.loads(historical_wire)
    assert recovered.call_effect_expansions == ()
    assert recovered == original
    assert codec.dumps(replace(graph, call_effect_expansions=())) == historical_wire
    assert codec.dumps(recovered) == historical_wire


def test_program25_can_coexist_with_occupancy_without_requiring_or_replacing_that_subject():
    original, _ = async_competition_program(reject_raised=False, known_association=True)
    assert json.loads(codec.dumps(original))['schema_version'] == 24
    call = next(op for op in original.operations if op.callee is not None)
    row = CallEffectExpansion(call.id, call.callee)
    graph = replace(original, call_effect_expansions=(row,))
    wire = codec.dumps(graph)
    assert json.loads(wire)['schema_version'] == 25
    recovered = codec.loads(wire)
    assert recovered == graph and codec.dumps(recovered) == wire
    assert recovered.protocol_operations == original.protocol_operations
    assert codec._has_session_occupancy_capability(recovered)


@pytest.mark.parametrize('version', (True, 26))
def test_boolean_or_next_future_version_cannot_enable_effect_expansion(version):
    graph, _, _ = _program()
    document = json.loads(codec.dumps(graph))
    document['schema_version'] = version
    with pytest.raises(ValueError, match='unsupported program graph schema version'):
        codec.loads(json.dumps(document))


def test_independent_program24_encoder_preserves_the_original_occupancy_bytes(tmp_path):
    archive = tmp_path / 'immutable-v24'
    archive.mkdir()
    tar_path = tmp_path / 'source.tar'
    with tar_path.open('wb') as target:
        subprocess.run(['git', 'archive', ORACLE_REVISION, 'scar', 'tests/fixtures'],
                       cwd=REPOSITORY, stdout=target, check=True)
    with tarfile.open(tar_path) as source:
        source.extractall(archive, filter='data')
    script = textwrap.dedent('''
        import hashlib, json, pathlib, sys, types
        root = pathlib.Path(sys.argv[1]).resolve()
        sys.path.insert(0, str(root))
        namespace = types.ModuleType('tests')
        namespace.__path__ = [str(root / 'tests')]
        sys.modules['tests'] = namespace
        from scar.ir.program import codec, model
        from tests.fixtures import program_async_competition_graphs as fixture
        assert codec.SCHEMA_VERSION == 24
        for module in (codec, model, fixture):
            assert pathlib.Path(module.__file__).resolve().is_relative_to(root)
        graph, _ = fixture.async_competition_program(
            reject_raised=False, known_association=True)
        wire = codec.dumps(graph).encode('ascii')
        assert json.loads(wire)['schema_version'] == 24
        assert 'call_effect_expansions' not in json.loads(wire)
        (root / 'oracle.json').write_bytes(wire)
        proof = {
            'schema_version':24,
            'source_codec_sha256':hashlib.sha256(pathlib.Path(codec.__file__).read_bytes()).hexdigest(),
            'fixture_source_sha256':hashlib.sha256(pathlib.Path(fixture.__file__).read_bytes()).hexdigest(),
            'fixture_sha256':hashlib.sha256(wire).hexdigest(),
            'fixture_bytes':len(wire),
            'module_paths':[str(pathlib.Path(m.__file__).resolve()) for m in (codec,model,fixture)]}
        print(json.dumps(proof,sort_keys=True))
    ''')
    command = [sys.executable, '-B', '-c', script, str(archive)]
    result = subprocess.run(command, cwd=archive, check=True, capture_output=True, text=True,
        env={**os.environ, 'PYTHONPATH': str(archive), 'PYTHONDONTWRITEBYTECODE': '1'})
    proof = json.loads(result.stdout)
    wire = (archive / 'oracle.json').read_bytes()
    assert proof['source_codec_sha256'] == ORACLE_CODEC_SHA256
    assert proof['fixture_sha256'] == hashlib.sha256(wire).hexdigest()
    assert proof['fixture_bytes'] == len(wire)
    assert proof['fixture_source_sha256'] == hashlib.sha256(
        (REPOSITORY / 'tests/fixtures/program_async_competition_graphs.py').read_bytes()).hexdigest()
    proof.update(source_revision=ORACLE_REVISION,
        fixture_profile='async_competition_program(reject_raised=False,known_association=True)',
        archive_command=['git', 'archive', ORACLE_REVISION, 'scar', 'tests/fixtures'], child_command=command)
    (tmp_path / 'v24.proof.json').write_text(json.dumps(proof, sort_keys=True, indent=2))
    print(json.dumps(proof, sort_keys=True))
    recovered = codec.loads(wire.decode('ascii'))
    assert recovered.call_effect_expansions == ()
    assert codec._has_session_occupancy_capability(recovered)
    assert codec.dumps(recovered).encode('ascii') == wire
    current, _ = async_competition_program(reject_raised=False, known_association=True)
    assert codec.dumps(current).encode('ascii') == wire
