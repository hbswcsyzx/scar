"""Program26 isolates new async uses of the existing admission subjects.

Only root's serial runner executes these tests or the immutable Program25
encoder subprocess. No new predicate tag or stored phase fact is introduced.
"""
from copy import deepcopy
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
from scar.ir.program.call_effect_expansion import CallEffectExpansion
from scar.ir.program.ids import RegionID
from scar.ir.program.model import ProgramGraph
from scar.ir.program.protocol_connections import (
    has_async_initial_control_capability, has_protocol_connection_capability,
)
from scar.ir.program.protocols import (
    AdmissionPredicate, BodyStateCondition, ProtocolClause, ProtocolProfile,
    ReferenceIsNoneCondition, RequestProcessing, RequestProcessingRule,
)
from scar.ir.program.validation import require_valid
from scar.ir.record_codec import encode
from tests.fixtures.program_admission_graphs import admission_program
from tests.fixtures.program_async_connections import request_state_program
from tests.fixtures.program_call_return_graphs import call_return_program


REPOSITORY = Path(__file__).resolve().parents[2]
ORACLE_REVISION = '96b8a322590217151ff6a5e839c7ab17d068f560'
ORACLE_CODEC_SHA256 = '304ba8680fefcc14e123979ca9363dd29a795a2db44ce271f295a7aad838da90'
NEW_SUBJECTS = (BodyStateCondition, ReferenceIsNoneCondition)


def _program():
    from tests.fixtures.program_async_initial_control_graphs import async_initial_control_program
    graph, details = async_initial_control_program(scenario='created-none')
    require_valid(graph)
    rows = tuple(row for row in graph.protocol_operations
        if type(row.contract) is AdmissionPredicate and type(row.contract.subject) in NEW_SUBJECTS)
    assert {type(row.contract.subject) for row in rows} == set(NEW_SUBJECTS)
    return graph, details, rows


def _subjects(document):
    return tuple(row['contract']['subject'] for row in document['protocol_operations']
        if row['contract'].get('kind') == 'PROTOCOL_ADMISSION_PREDICATE'
        and row['contract']['subject'].get('kind') in (
            'PROTOCOL_BODY_STATE_CONDITION', 'PROTOCOL_REFERENCE_IS_NONE_CONDITION'))


def _effect_program():
    graph, details = call_return_program()
    call = next(op for op in graph.operations if op.id == details['root_calls'][0])
    return replace(graph, call_effect_expansions=(CallEffectExpansion(call.id, call.callee),))


@pytest.mark.parametrize('subject', ('body', 'none'))
def test_program26_preserves_original_body_none_ports_and_uses_the_existing_subject_tags(subject):
    graph, _, rows = _program()
    cls = BodyStateCondition if subject == 'body' else ReferenceIsNoneCondition
    row = next(row for row in rows if type(row.contract.subject) is cls)
    operation = next(op for op in graph.operations if op.id == row.operation)
    wire = codec.dumps(graph)
    document = json.loads(wire)
    assert codec.SCHEMA_VERSION == 27 and document['schema_version'] == 26
    assert execution_codec.SCHEMA_VERSION == 8
    assert set(document) == ({field.name for field in fields(ProgramGraph)} - {'stored_value_writes', 'stored_value_reads'}) | {'schema', 'schema_version'}
    assert document['call_effect_expansions'] == []
    assert has_async_initial_control_capability(graph)
    assert has_protocol_connection_capability(graph)
    encoded = next(item for item in _subjects(document) if item['kind'] == (
        'PROTOCOL_BODY_STATE_CONDITION' if subject == 'body' else 'PROTOCOL_REFERENCE_IS_NONE_CONDITION'))
    assert set(encoded) == ({'kind', 'instance_use', 'state_sites', 'rule'}
        if subject == 'body' else {'kind', 'input_use'})
    recovered = codec.loads(wire)
    assert recovered == graph and codec.dumps(recovered) == wire
    assert recovered.operations == graph.operations and recovered.values == graph.values
    assert recovered.driver_interfaces == graph.driver_interfaces
    assert recovered.async_request_creates == graph.async_request_creates
    assert recovered.request_association_reads == graph.request_association_reads
    restored = next(item for item in recovered.protocol_operations
        if (item.scope, item.clause, item.operation, item.slot) ==
           (row.scope, row.clause, row.operation, row.slot))
    assert restored.contract == row.contract
    assert next(op for op in recovered.operations if op.id == operation.id).uses == operation.uses


def test_capability_is_the_exact_async_subject_profile_clause_combination():
    graph, _, rows = _program()
    row = next(row for row in rows if type(row.contract.subject) is BodyStateCondition)
    # Other metadata is irrelevant to this raw capability test. It does not
    # claim these deliberately isolated declarations form a valid full graph.
    isolated = replace(graph, protocol_operations=(row,))
    for clause in (ProtocolClause.ASYNC_REQUEST_SOURCE, ProtocolClause.ASYNC_REQUEST_DELIVERY):
        assert has_async_initial_control_capability(replace(isolated,
            protocol_operations=(replace(row, clause=clause),)))
    assert not has_async_initial_control_capability(replace(isolated,
        protocol_operations=(replace(row, clause=ProtocolClause.BODY_INGRESS),)))
    assert not has_async_initial_control_capability(replace(isolated,
        protocol_scopes=tuple(replace(scope, profile=ProtocolProfile.GENERATOR_BODY_V1)
            if scope.id == row.scope else scope for scope in graph.protocol_scopes)))
    assert not has_async_initial_control_capability(replace(isolated, protocol_scopes=()))


@pytest.mark.parametrize('version', (19, 25))
def test_historical_headers_reject_the_new_combination_even_with_old_untagged_subject_shapes(version):
    graph, _, _ = _program()
    document = json.loads(codec.dumps(graph))
    document['schema_version'] = version
    if version < 25:
        del document['call_effect_expansions']
    if version < 21:
        del document['exception_matches']
    with pytest.raises(ValueError, match='historical schema cannot contain async initial control capability'):
        codec.loads(json.dumps(document))
    untagged = deepcopy(document)
    for subject in _subjects(untagged):
        del subject['kind']
    # These subjects were already tagged in these historical readers. Their
    # missing tag is rejected before the semantic profile capability check.
    with pytest.raises(ValueError, match='value does not match union type'):
        codec.loads(json.dumps(untagged))


@pytest.mark.parametrize('old_subject', ('body', 'none'))
def test_old_profile_subjects_remain_program18_and_cannot_select_program26_by_header(old_subject):
    graph, _ = admission_program(subject=old_subject)
    wire = codec.dumps(graph)
    document = json.loads(wire)
    assert document['schema_version'] == 18
    assert not has_async_initial_control_capability(graph)
    assert codec.loads(wire) == graph
    document['schema_version'] = 26
    document['exception_matches'] = []
    document['call_effect_expansions'] = []
    document.setdefault('protocol_call_inputs', [])
    document.setdefault('protocol_result_consumers', [])
    document.setdefault('protocol_bindings', [])
    with pytest.raises(ValueError, match='schema version 26 requires explicit async initial control capability'):
        codec.loads(json.dumps(document))


def test_old_initial_asend_processing_rule_alone_does_not_select_program26():
    graph, _ = request_state_program(target='start')
    operations = {op.id: op for op in graph.operations}
    graph = replace(graph, protocol_operations=tuple(replace(row,
        contract=replace(row.contract, raw_use=operations[row.operation].invoke_arguments[1],
                         rule=RequestProcessingRule.CHECK_INITIAL_ASEND))
        if type(row.contract) is RequestProcessing else row for row in graph.protocol_operations))
    require_valid(graph)
    assert not has_async_initial_control_capability(graph)
    wire = codec.dumps(graph)
    assert json.loads(wire)['schema_version'] == 19
    assert codec.loads(wire) == graph


def test_program26_can_coexist_with_expansions_while_program25_still_requires_the_nonempty_table():
    graph, _, _ = _program()
    call = next(op for op in graph.operations if op.callee is not None)
    graph = replace(graph, call_effect_expansions=(CallEffectExpansion(call.id, call.callee),))
    wire = codec.dumps(graph)
    assert json.loads(wire)['schema_version'] == 26
    assert codec.loads(wire) == graph
    historical = json.loads(codec.dumps(_effect_program()))
    assert historical['schema_version'] == 25
    historical['call_effect_expansions'] = []
    with pytest.raises(ValueError, match='schema version 25 requires explicit call effect expansion capability'):
        codec.loads(json.dumps(historical))
    historical['schema_version'] = 26
    with pytest.raises(ValueError, match='schema version 26 requires explicit async initial control capability'):
        codec.loads(json.dumps(historical))


@pytest.mark.parametrize('fault', ('wrong-use-namespace', 'duplicate-read', 'invented-phase'))
def test_program26_does_not_relax_original_subject_types_or_allow_new_phase_facts(fault):
    graph, _, _ = _program()
    document = json.loads(codec.dumps(graph))
    subject = next(item for item in _subjects(document)
                   if item['kind'] == 'PROTOCOL_BODY_STATE_CONDITION')
    if fault == 'wrong-use-namespace':
        subject['instance_use'] = encode(RegionID('initial.codec.not-a-use'))
    elif fault == 'duplicate-read':
        assert subject['state_sites']
        subject['state_sites'].append(deepcopy(subject['state_sites'][0]))
    else:
        subject['created'] = True
    with pytest.raises((TypeError, ValueError)):
        codec.loads(json.dumps(document))


@pytest.mark.parametrize('version', (True, 28))
def test_boolean_or_future_schema_does_not_enable_async_initial_control(version):
    graph, _, _ = _program()
    document = json.loads(codec.dumps(graph))
    document['schema_version'] = version
    with pytest.raises(ValueError, match='unsupported program graph schema version'):
        codec.loads(json.dumps(document))


def test_independent_program25_encoder_keeps_the_original_effect_expansion_bytes(tmp_path):
    archive = tmp_path / 'immutable-v25'
    archive.mkdir()
    tar_path = tmp_path / 'source.tar'
    with tar_path.open('wb') as target:
        subprocess.run(['git', 'archive', ORACLE_REVISION, 'scar', 'tests/fixtures'],
                       cwd=REPOSITORY, stdout=target, check=True)
    with tarfile.open(tar_path) as source:
        source.extractall(archive, filter='data')
    script = textwrap.dedent('''
        from dataclasses import replace
        import hashlib, json, pathlib, sys, types
        root = pathlib.Path(sys.argv[1]).resolve()
        sys.path.insert(0, str(root))
        namespace = types.ModuleType('tests')
        namespace.__path__ = [str(root / 'tests')]
        sys.modules['tests'] = namespace
        from scar.ir.program import codec, model
        from scar.ir.program import call_effect_expansion as expansion
        from tests.fixtures import program_call_return_graphs as fixture
        assert codec.SCHEMA_VERSION == 25
        for module in (codec, model, expansion, fixture):
            assert pathlib.Path(module.__file__).resolve().is_relative_to(root)
        graph, details = fixture.call_return_program()
        call = next(op for op in graph.operations if op.id == details['root_calls'][0])
        graph = replace(graph, call_effect_expansions=(
            expansion.CallEffectExpansion(call.id, call.callee),))
        wire = codec.dumps(graph).encode('ascii')
        assert json.loads(wire)['schema_version'] == 25
        assert json.loads(wire)['call_effect_expansions']
        (root / 'oracle.json').write_bytes(wire)
        print(json.dumps({
            'schema_version':25,
            'source_codec_sha256':hashlib.sha256(pathlib.Path(codec.__file__).read_bytes()).hexdigest(),
            'fixture_source_sha256':hashlib.sha256(pathlib.Path(fixture.__file__).read_bytes()).hexdigest(),
            'fixture_sha256':hashlib.sha256(wire).hexdigest(),
            'fixture_bytes':len(wire),
            'module_paths':[str(pathlib.Path(m.__file__).resolve())
                            for m in (codec,model,expansion,fixture)]},sort_keys=True))
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
        (REPOSITORY / 'tests/fixtures/program_call_return_graphs.py').read_bytes()).hexdigest()
    proof.update(source_revision=ORACLE_REVISION,
        fixture_profile='call_return_program()+exact-root-call-CallEffectExpansion',
        archive_command=['git', 'archive', ORACLE_REVISION, 'scar', 'tests/fixtures'], child_command=command)
    (tmp_path / 'v25.proof.json').write_text(json.dumps(proof, sort_keys=True, indent=2))
    print(json.dumps(proof, sort_keys=True))
    graph = _effect_program()
    assert not has_async_initial_control_capability(graph)
    recovered = codec.loads(wire.decode('ascii'))
    assert recovered == graph
    assert codec.dumps(recovered).encode('ascii') == wire
    assert codec.dumps(graph).encode('ascii') == wire
