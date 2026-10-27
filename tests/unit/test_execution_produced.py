"""Production follows original effects/results, preserving unresolved native facts."""
from dataclasses import replace
import os

import pytest

from scar.ir.execution.common import Unresolved
from scar.ir.execution.coordinates import AccessRef
from scar.ir.execution.ids import OperationOccurrenceID, OutcomeProductionID, WorkOutcomeID, WorkTicketID, WriteAssociationID
from scar.ir.execution.production import HostWrite, StateProduction, WorkWrite
from scar.ir.execution.snapshot import external_artifact
from scar.ir.execution.validation import require_valid, validate
from scar.ir.execution.work import WorkOutcomeKind
from scar.ir.program.validation import require_valid as require_program_valid
from tests.fixtures.execution_produced_graphs import byte_prefix_execution, produced_execution, source_write_execution


def _report(program, model, values):
    return validate(model, program, value_graphs=values)


@pytest.mark.parametrize('options', ({}, {'host': True}, {'external': True}, {'value': True},
    {'host': True, 'invoke': True}, {'host': True, 'invoke': True, 'raised': True},
    {'invoke': True}, {'invoke': True, 'raised': True}))
def test_original_host_external_and_work_productions_do_not_invent_evidence(options):
    program, model, values = produced_execution(**options)
    require_program_valid(program)
    require_valid(model, program, value_graphs=values)
    report = _report(program, model, values)
    assert report.valid
    assert any(row.code == 'production_source_join_unverified' for row in report.gaps)
    assert not report.source_runtime_verified and not report.transformation_authorized
    if options.get('host') or options.get('external') or options.get('value'):
        assert not model.submissions and not model.outcomes and not model.produced


@pytest.mark.parametrize('case,code', (
    ('write', 'production_write'), ('outcome', 'production_outcome'),
    ('ticket', 'production_ticket'), ('frontier-index', 'production_frontier'),
    ('frontier-none', 'production_state_frontier'), ('effect', 'production_effect'),
    ('host-owner', 'production_host'), ('wrong-ticket', 'production_outcome_ticket'),
))
def test_missing_and_mismatched_original_endpoints_are_issues(case, code):
    program, model, values = produced_execution()
    write, produced = model.writes[0], model.produced[0]
    if case == 'write':
        produced = replace(produced, write=WriteAssociationID('absent'))
    elif case == 'outcome':
        produced = replace(produced, outcome=WorkOutcomeID('absent'))
    elif case == 'ticket':
        write = replace(write, writer=WorkWrite(WorkTicketID('absent')))
    elif case == 'frontier-index':
        produced = replace(produced, frontier=999)
    elif case == 'frontier-none':
        produced = replace(produced, frontier=None)
    elif case == 'effect':
        write = replace(write, production=StateProduction(AccessRef(model.operations[0].id, 999)))
    elif case == 'host-owner':
        write = replace(write, writer=HostWrite(OperationOccurrenceID('absent')))
    else:
        write = replace(write, writer=HostWrite(model.operations[1].id))
    model = replace(model, writes=(write,), produced=(produced,))
    assert any(row.code == code for row in _report(program, model, values).issues)


def test_explicit_unknown_frontier_does_not_masquerade_as_known_empty_or_whole():
    program, model, values = produced_execution()
    unknown = Unresolved('actual partial write frontier not captured', model.activations[0].entry)
    model = replace(model, produced=(replace(model.produced[0], frontier=unknown),))
    report = _report(program, model, values)
    assert report.valid
    assert any(row.code == 'production_frontier_unresolved' for row in report.gaps)


def test_work_value_production_has_a_real_original_output_and_no_state_frontier():
    program, model, values = produced_execution(work_value=True)
    require_program_valid(program)
    assert _report(program, model, values).valid
    assert model.produced[0].frontier is None
    changed = replace(model, produced=(replace(model.produced[0], frontier=0),))
    assert any(row.code == 'production_value_frontier' for row in _report(program, changed, values).issues)


def test_host_invoke_cannot_reuse_opposite_completion_state():
    program, model, values = produced_execution(host=True, invoke=True, raised=True)
    write = model.writes[0]
    effect = write.production.effect
    effect = replace(effect, post=replace(effect.post, successor_index=0))
    model = replace(model, writes=(replace(write, production=StateProduction(effect)),))
    report = _report(program, model, values)
    assert any(row.code.startswith('production_invoke_') for row in report.issues)


@pytest.mark.parametrize('kind,written', ((WorkOutcomeKind.COMPLETED, 4), (WorkOutcomeKind.COMPLETED, 0),
    (WorkOutcomeKind.FAILED, 4), (WorkOutcomeKind.CANCELLED, 4)))
def test_exact_raw_prefix_preserves_partial_and_empty_production_without_whole_or_authority(kind, written):
    program, model, values, payloads = byte_prefix_execution(kind=kind, written=written)
    report = validate(model, program, value_graphs=values, artifact_bytes=payloads)
    assert report.valid, report.issues
    graph = next(iter(values.values()))
    assert graph.regions[model.produced[0].actual.region].shape == (written,)
    assert graph.regions[model.writes[0].placement.selector.region].shape == (8,)
    assert not report.source_runtime_verified and not report.transformation_authorized
    assert any(row.code == 'production_native_protocol_unverified' for row in report.gaps)
    assert not any(row.code in ('production_profile_unavailable', 'production_result_unresolved') for row in report.gaps)


@pytest.mark.parametrize('changes,code', (
    ({'schema': 'unknown'}, 'production_profile'),
    ({'schema_version': True}, 'production_profile'),
    ({'stage': ''}, 'production_profile'),
    ({'terminal_status': 'SUCCESS'}, 'production_profile'),
    ({'requested_bytes': True}, 'production_profile_count'),
    ({'written_bytes': -1}, 'production_profile_count'),
    ({'written_bytes': 9}, 'production_profile_count'),
))
def test_raw_profile_is_closed_and_counts_are_not_caller_success_labels(changes, code):
    profile = {'schema': 'scar.native.byte-prefix-write', 'schema_version': 1,
               'stage': 'native-prefix-stage', 'requested_bytes': 8, 'written_bytes': 4, **changes}
    program, model, values, payloads = byte_prefix_execution(profile=profile)
    report = validate(model, program, value_graphs=values, artifact_bytes=payloads)
    assert any(row.code == code for row in report.issues), report


@pytest.mark.parametrize('case,code', (('count', 'production_selector_count'),
                                      ('offset', 'production_selector_offset'),
                                      ('allocation', 'production_selector_allocation')))
def test_actual_prefix_must_match_original_geometry_and_allocation(case, code):
    from scar.ir.v2.ids import StorageAllocationID
    from scar.ir.v2.values import StorageAllocation
    program, model, values, payloads = byte_prefix_execution()
    old_artifact = model.produced[0].actual.artifact
    graph = values[old_artifact.sha256]
    actual = graph.regions[model.produced[0].actual.region]
    if case == 'count':
        actual.shape = (8,)
    elif case == 'offset':
        actual.offset = 1
    else:
        other = StorageAllocationID('other-allocation')
        graph.add_allocation(StorageAllocation(other, 'cpu', 32))
        actual.allocation = other
    artifact = external_artifact(graph)
    placement = model.writes[0].placement
    placement = replace(placement, materialization=replace(placement.materialization, artifact=artifact),
                        selector=replace(placement.selector, artifact=artifact))
    model = replace(model, writes=(replace(model.writes[0], placement=placement),),
        produced=(replace(model.produced[0], actual=replace(model.produced[0].actual, artifact=artifact)),))
    report = validate(model, program, value_graphs={artifact.sha256: graph}, artifact_bytes=payloads)
    assert any(row.code == code for row in report.issues), report


def test_actual_prefix_result_locator_cannot_select_another_raw_line():
    program, model, values, payloads = byte_prefix_execution()
    outcome = model.outcomes[0]
    model = replace(model, outcomes=(replace(outcome,
        protocol_result=replace(outcome.protocol_result, locator='#L2/metadata/scar_native_result')),))
    report = validate(model, program, value_graphs=values, artifact_bytes=payloads)
    assert any(row.code == 'production_protocol_result' for row in report.issues)


def test_missing_original_raw_bytes_keep_a_concrete_gap_without_profile_crash():
    program, model, values, payloads = byte_prefix_execution()
    raw = model.outcomes[0].protocol_result.artifact
    payloads = {key: value for key, value in payloads.items() if key != raw.sha256}
    report = validate(model, program, value_graphs=values, artifact_bytes=payloads)
    assert report.valid, report.issues
    assert any(row.code == 'inventory_artifact_missing' for row in report.gaps)


@pytest.mark.parametrize('wrong_target', (False, True))
def test_source_write_uses_same_bundle_original_version_and_materialization(wrong_target):
    program, model, values, payloads = source_write_execution(wrong_target=wrong_target)
    report = validate(model, program, value_graphs=values, artifact_bytes=payloads)
    if wrong_target:
        assert {'production_source_version', 'production_source_materialization'} <= {row.code for row in report.issues}
    else:
        assert report.valid, report.issues
        assert any(row.code == 'production_source_join_unverified' for row in report.gaps)


@pytest.mark.parametrize('literal', (4, 5, True))
def test_only_exact_literal_integer_result_can_match_or_conflict_with_parsed_count(literal):
    from scar.ir.execution.coordinates import ValueOccurrence
    from scar.ir.execution.ids import ValueOccurrenceID
    from scar.ir.execution.snapshot import snapshot_for
    from scar.ir.program.ids import ValueID
    from scar.ir.program.model import DataValue, LiteralOrigin
    program, model, values, payloads = byte_prefix_execution()
    value = DataValue(ValueID('native.count'), program.root, LiteralOrigin(literal),
                      'builtins.bool' if type(literal) is bool else 'builtins.int')
    program = replace(program, values=(*program.values, value))
    observed = ValueOccurrence(ValueOccurrenceID('native.count'), value.id, model.activations[0].id)
    model = replace(model, snapshot=snapshot_for(program), values=(*model.values, observed),
                    outcomes=(replace(model.outcomes[0], protocol_result=observed.id),))
    report = validate(model, program, value_graphs=values, artifact_bytes=payloads)
    if type(literal) is int and literal != 4:
        assert any(row.code == 'production_protocol_result' for row in report.issues)
    else:
        assert report.valid, report.issues
    if literal is True:
        assert any(row.code == 'production_result_unresolved' for row in report.gaps)


@pytest.mark.skipif(not hasattr(os, 'pwrite'), reason='generic positional OS write unavailable')
def test_real_native_write_then_wrapper_raise_keeps_actual_request_distinct_from_desired_output(tmp_path, record_property):
    destination = tmp_path / 'partial-output.bin'
    destination.write_bytes(b'........')
    native_payload = b'abcd'
    descriptor = os.open(destination, os.O_WRONLY)
    written = None
    try:
        with pytest.raises(RuntimeError, match='controlled failure after native completion'):
            written = os.pwrite(descriptor, native_payload, 0)
            raise RuntimeError('controlled failure after native completion')
    finally:
        os.close(descriptor)
    observed = destination.read_bytes()
    assert written == len(native_payload) == 4
    assert observed == b'abcd....'
    record_property('desired_output_bytes', 8)
    record_property('native_requested_bytes', len(native_payload))
    record_property('native_returned_bytes', written)
    record_property('actual_file_hex', observed.hex())
    record_property('host_completion', 'RAISE')
    record_property('native_outcome', 'COMPLETED')
    program, model, values, payloads = byte_prefix_execution(requested=len(native_payload), written=written,
        invoke=True, raised=True, kind=WorkOutcomeKind.COMPLETED)
    report = validate(model, program, value_graphs=values, artifact_bytes=payloads)
    assert report.valid, report.issues
    assert model.outcomes[0].kind is WorkOutcomeKind.COMPLETED
    assert model.transfers[0].successor_index == 1
    assert not report.source_runtime_verified
