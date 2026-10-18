"""D1 static driver contracts, including graphs that retain opaque boundaries."""
from dataclasses import replace

import pytest

from scar.ir.program.control import ProtocolValueKind as P
from scar.ir.program.driver_validation import driver_errors
from scar.ir.program.drivers import BodyDriveResult, BodyResume, BodyStart, NormalResultPort, RawRequestKind
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, BlockArgument, CompletionResult, ExitKind, Operation,
    ProtocolValue, ReferenceValue, StateVersionValue, Use, UseRole,
)
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_driver_graphs import (
    async_request_program, create_only_program, driver_program, raw_only_program,
)


def _operation(graph, name):
    return next(item for item in graph.operations if item.id == OperationID(name))


def _change_operation(graph, name, update):
    return replace(graph, operations=tuple(update(item) if item.id == OperationID(name) else item
                                           for item in graph.operations))


def _codes(graph):
    return {issue.code for issue in validate(graph)}


def _metadata_codes(graph):
    """Exercise metadata errors independently of intentionally broken core shape."""
    operation_blocks = {identity: block.id for region in graph.regions for block in region.blocks
                        for identity in block.operations}
    values = {value.id: value for value in graph.values}
    domains = {region.id: {values[formal].location
                           for block in region.blocks if block.id == region.entry
                           for formal in block.arguments if isinstance(values[formal], StateVersionValue)}
               for region in graph.regions}
    incoming = {block.id: [] for region in graph.regions for block in region.blocks}
    for operation in graph.operations:
        if operation.terminator is not None:
            for index, edge in enumerate(operation.terminator.successors):
                incoming[edge.block].append((operation.id, index))
    return {code for code, _, _ in driver_errors(graph, operation_blocks=operation_blocks,
                                               region_domains=domains, incoming_edges=incoming)}


@pytest.mark.parametrize("kind", tuple(RawRequestKind))
def test_four_raw_request_kinds_are_real_pure_constructors(kind):
    require_valid(raw_only_program(kind))


@pytest.mark.parametrize("target", ("start", "value", "packet"))
@pytest.mark.parametrize("create,extra", ((False, False), (True, False), (False, True)))
def test_complete_created_or_external_start_resume_and_extra_state(target, create, extra):
    graph = driver_program(target=target, create=create, extra_domain=extra)
    require_valid(graph)
    assert set(graph.driver_interfaces[0].lifecycle) < {
        value.location for value in graph.values if value.region == RegionID("driver")
        and isinstance(value, StateVersionValue)
    }


def test_create_does_not_require_any_actual_drive():
    graph = create_only_program()
    require_valid(graph)
    assert graph.resumable_creates and not graph.body_drives


@pytest.mark.parametrize("target", ("start", "value", "packet"))
def test_async_request_receiver_is_distinct_from_body_and_scheduler(target):
    require_valid(driver_program(target=target, async_request=True, extra_domain=True))


def test_request_creation_and_current_association_are_real_invoke_results():
    graph = async_request_program()
    require_valid(graph)
    assert graph.async_request_creates and graph.request_association_reads
    assert not graph.body_drives


def test_raw_pack_rejects_an_extra_owned_use():
    graph = raw_only_program()
    value = next(value.id for value in graph.values if isinstance(value, ReferenceValue))
    graph = _change_operation(graph, "raw.pack", lambda op: replace(op, uses=(Use(UseID("raw.hidden"), value, UseRole.REFERENCE),)))
    assert "driver_raw_pack" in _codes(graph)


def test_raw_pack_cannot_be_an_ordinary_call_or_incomplete_effect_boundary():
    graph = raw_only_program()
    call = _change_operation(graph, "raw.pack", lambda op: replace(op, callee=graph.root))
    unknown = _change_operation(graph, "raw.pack", lambda op: replace(op, effects_complete=False))
    assert "driver_raw_pack" in _metadata_codes(call)
    assert "driver_raw_pack" in _metadata_codes(unknown)


def test_raw_operand_must_remain_a_reference_not_a_prepacked_packet():
    graph = raw_only_program(RawRequestKind.THROW)
    reference = next(value for value in graph.values if isinstance(value, ReferenceValue))
    packet = ProtocolValue(reference.id, reference.region, reference.origin, P.EXCEPTION_PACKET)
    graph = replace(graph, values=tuple(packet if value.id == reference.id else value for value in graph.values))
    assert "driver_raw" in _metadata_codes(graph)


def test_create_capture_partition_and_function_source_are_required():
    graph = create_only_program()
    row = graph.resumable_creates[0]
    missing = replace(graph, resumable_creates=(replace(row, captures=row.captures[:-1]),))
    function = replace(graph, resumable_creates=(replace(row, function_object=row.captures[0].source),))
    assert "driver_create_captures" in _codes(missing)
    assert "driver_create_function" in _codes(function)


def test_create_requires_bound_formal_environment_partition_and_reference_result():
    graph = create_only_program()
    no_environment = replace(graph, environments=(), function_entries=())
    wrong_result = replace(graph, resumable_creates=(replace(graph.resumable_creates[0], handle_result=NormalResultPort(1)),))
    assert "driver_create_environment" in _codes(no_environment)
    assert "driver_result" in _codes(wrong_result)


def test_association_body_and_latent_result_ports_are_not_interchangeable():
    graph = async_request_program()
    row = graph.request_association_reads[0]
    graph = replace(graph, request_association_reads=(replace(row, body_result=row.latent_result, latent_result=row.body_result),))
    assert "driver_result" in _codes(graph)


def test_lifecycle_is_a_nonempty_subset_of_all_driver_domains():
    graph = driver_program(extra_domain=True)
    row = graph.driver_interfaces[0]
    graph = replace(graph, driver_interfaces=(replace(row, lifecycle=(LocationID("not.a.driver.domain"),)),))
    assert "driver_lifecycle" in _codes(graph)


def _extra_entry_role(graph, *, raw):
    region = next(region for region in graph.regions if region.id == RegionID("driver"))
    entry = next(block for block in region.blocks if block.id == region.entry)
    origin = BlockArgument(entry.id, len(entry.arguments))
    value = (ProtocolValue(ValueID("driver.other.raw"), region.id, origin, P.RAW_DRIVER_REQUEST)
             if raw else ReferenceValue(ValueID("driver.other.receiver"), region.id, origin))
    region = replace(region, blocks=tuple(replace(block, arguments=(*block.arguments, value.id))
                                          if block.id == entry.id else block for block in region.blocks))
    original = graph.driver_interfaces[0].scheduler_request if raw else graph.driver_interfaces[0].receiver
    graph = replace(graph, values=(*graph.values, value), regions=tuple(region if item.id == region.id else item for item in graph.regions))
    return _change_operation(graph, "driver.gate", lambda op: replace(op, uses=tuple(
        replace(use, value=value.id) if use.value == original else use for use in op.uses)))


def test_locally_consistent_gate_forwarding_cannot_replace_the_fixed_scheduler():
    assert "driver_scheduler_copy" in _codes(_extra_entry_role(driver_program(), raw=True))


def test_locally_consistent_gate_forwarding_cannot_replace_the_fixed_receiver():
    assert "driver_receiver_copy" in _codes(_extra_entry_role(driver_program(), raw=False))


def test_async_mode_requires_its_fixed_request_session_role():
    graph = driver_program(async_request=True)
    gate = replace(graph.final_body_gates[0], session_argument=None)
    drive = replace(graph.body_drives[0], session=None)
    graph = replace(graph, final_body_gates=(gate,), body_drives=(drive,))
    assert "driver_receiver_copy" in _metadata_codes(graph)


def test_gate_normal_landing_cannot_insert_even_a_pure_operation():
    graph = driver_program()
    nop = Operation(OperationID("driver.ingress.nop"), "pure intervening operation", (Behavior.COMPUTE,), effects_complete=True)
    regions = tuple(replace(region, blocks=tuple(replace(block, operations=(nop.id, *block.operations))
                    if block.id == BlockID("driver.ingress") else block for block in region.blocks))
                    if region.id == RegionID("driver") else region for region in graph.regions)
    graph = replace(graph, regions=regions, operations=(*graph.operations, nop))
    assert "driver_gate_corridor" in _codes(graph)


def test_gate_new_reference_result_cannot_impersonate_its_original_owner():
    graph = driver_program()
    gate = _operation(graph, "driver.gate")
    normal, raised = gate.terminator.successors
    signatures = tuple(replace(signature, types=(*signature.types, value_type_reference()))
                       if signature.kind is ExitKind.NORMAL else signature for signature in gate.completions)
    normal = replace(normal, arguments=(CompletionResult(2), *normal.arguments[1:]))
    graph = _change_operation(graph, "driver.gate", lambda op: replace(op,
        uses=tuple(use for use in op.uses if use.id != UseID("driver.gate.forward.0")),
        completions=signatures, terminator=replace(op.terminator, successors=(normal, raised))))
    assert "driver_gate_forward" in _codes(graph)


def value_type_reference():
    from scar.ir.program.model import ValueKind, ValueType
    return ValueType(ValueKind.REFERENCE)


def test_gate_must_produce_all_poststates_not_forward_an_old_world():
    graph = driver_program()
    gate = _operation(graph, "driver.gate")
    normal, raised = gate.terminator.successors
    world_input = next(use for use in gate.uses if use.id == UseID("driver.gate.input.2"))
    forwarded = replace(world_input, id=UseID("driver.gate.old.world"))
    normal = replace(normal, arguments=(*normal.arguments[:2], forwarded.id, CompletionResult(0)))
    completions = tuple(replace(signature, types=signature.types[1:])
                        if signature.kind is ExitKind.NORMAL else signature for signature in gate.completions)
    graph = _change_operation(graph, "driver.gate", lambda op: replace(op, uses=(*op.uses, forwarded),
        completions=completions, terminator=replace(op.terminator, successors=(normal, raised))))
    assert "driver_gate_states" in _codes(graph)


def test_state_binding_is_by_location_not_tuple_position():
    graph = driver_program()
    row = graph.body_drives[0]
    first, second = row.state_inputs
    wrong = replace(row, state_inputs=(replace(first, source=second.source), replace(second, source=first.source)))
    graph = replace(graph, body_drives=(wrong,))
    assert {"driver_state_inputs", "driver_state_input"} & _codes(graph)


@pytest.mark.parametrize("target", (BodyStart(RegionID("missing.body")), BodyResume(OperationID("resume.suspend"), 9)))
def test_wrong_target_region_or_resume_case_is_rejected(target):
    graph = driver_program()
    graph = replace(graph, body_drives=(replace(graph.body_drives[0], target=target),))
    assert "driver_target" in _codes(graph)


def test_start_profile_has_no_source_for_nonreference_nonstate_formal():
    from scar.ir.program.model import DataValue, ValueKind, ValueType
    graph = driver_program()
    value = next(value for value in graph.values if value.id == ValueID("resume.x"))
    wrong = DataValue(value.id, value.region, value.origin, "builtins.int")
    graph = replace(graph, values=tuple(wrong if item.id == value.id else item for item in graph.values))
    assert "driver_start_interface" in _metadata_codes(graph)


def test_outcome_must_be_from_first_frontier_not_after_the_next_suspend():
    graph = driver_program()
    graph = _change_operation(graph, "driver.drive", lambda op: replace(op,
        terminator=replace(op.terminator, successors=(replace(op.terminator.successors[0], source=OperationID("resume.return")),))))
    assert "driver_outcomes" in _codes(graph)


def test_omitted_finite_outcome_is_a_contract_error():
    graph = _change_operation(driver_program(), "driver.drive", lambda op: replace(op,
        terminator=replace(op.terminator, successors=())))
    assert "driver_outcomes" in _metadata_codes(graph)


def test_duplicate_metadata_and_missing_gate_are_rejected():
    graph = driver_program()
    with pytest.raises(ValueError, match="duplicates"):
        replace(graph, final_body_gates=(*graph.final_body_gates, graph.final_body_gates[0]))
    missing = replace(graph, final_body_gates=())
    assert "driver_gate_pair" in _codes(missing)


def test_multiple_create_sites_merge_into_the_same_declared_driver_interface():
    from tests.fixtures.program_driver_graphs import multiple_creates_program
    graph = multiple_creates_program()
    require_valid(graph)
    assert len(graph.resumable_creates) == 2
    assert len(graph.driver_interfaces) == 1


def test_invoke_branch_frontier_has_all_private_return_and_raise_sources():
    from tests.fixtures.program_resumption_graphs import resumption_cleanup_invoke_program
    graph = driver_program(target="value", body_graph=resumption_cleanup_invoke_program())
    require_valid(graph)
    drive = _operation(graph, "driver.drive")
    assert {edge.source for edge in drive.terminator.successors} == {
        OperationID("finally.return"), OperationID("finally.raise-exit.op")}


def test_mixed_divergent_paths_keep_their_finite_frontier_without_totality_claim():
    from tests.fixtures.program_resumption_graphs import resumption_loop_program
    graph = driver_program(target="value", body_graph=resumption_loop_program())
    require_valid(graph)
    assert tuple(edge.source for edge in _operation(graph, "driver.drive").terminator.successors) == (
        OperationID("resume.return"),)


def test_fully_divergent_body_needs_no_fake_drive_completion_or_normal_host_exit():
    from tests.unit.test_body_outcome_frontier import _nonterminating_body
    graph = driver_program(body_graph=_nonterminating_body())
    require_valid(graph)
    assert _operation(graph, "driver.drive").terminator.successors == ()
    driver = next(region for region in graph.regions if region.id == RegionID("driver"))
    assert tuple(port.kind for port in driver.exits) == (ExitKind.RAISE,)


@pytest.mark.parametrize("behaviors", ((Behavior.WRITE,), (Behavior.READ,), (Behavior.MEMORY,),
    (Behavior.TRANSFER,), (Behavior.ORDER,), (Behavior.COMPUTE, Behavior.WRITE), ()))
def test_raw_pack_effect_labels_cannot_claim_physical_work(behaviors):
    graph = _change_operation(raw_only_program(), "raw.pack", lambda op: replace(op, behaviors=behaviors))
    assert "driver_raw_pack" in _codes(graph)


def test_raw_pack_allows_several_descriptor_behaviors_without_effect_labels():
    graph = _change_operation(raw_only_program(), "raw.pack", lambda op: replace(op,
        behaviors=(Behavior.COMPUTE, Behavior.CONTROL, Behavior.REPRESENT)))
    require_valid(graph)


def test_raw_pack_cannot_hide_a_real_state_read():
    from scar.ir.program.model import AccessMode, StateAccess, StateLocation, ValueKind, ValueType
    graph = raw_only_program()
    region = graph.regions[0]
    entry = region.blocks[0]
    location = LocationID("raw.hidden.domain")
    state = StateVersionValue(ValueID("raw.hidden.state"), region.id,
                              BlockArgument(entry.id, len(entry.arguments)), location)
    read = Use(UseID("raw.hidden.read"), state.id, UseRole.STATE_CONTENT)
    returned = Use(UseID("raw.hidden.return"), state.id, UseRole.STATE_CONTENT)
    graph = _change_operation(graph, "raw.pack", lambda op: replace(op,
        behaviors=(*op.behaviors, Behavior.READ), uses=(*op.uses, read),
        accesses=(StateAccess(location, read.id, AccessMode.READ),)))
    graph = _change_operation(graph, "raw.return", lambda op: replace(op,
        uses=(*op.uses, returned), terminator=replace(op.terminator, values=(*op.terminator.values, returned.id))))
    region = replace(region, blocks=(replace(entry, arguments=(*entry.arguments, state.id)),),
        exits=(replace(region.exits[0], types=(*region.exits[0].types, ValueType(ValueKind.STATE, location=location))),))
    graph = replace(graph, values=(*graph.values, state), locations=(*graph.locations, StateLocation(location, "actual read domain")),
                    regions=(region,))
    assert "driver_raw_pack" in _codes(graph)


def test_known_create_actual_body_mismatch_is_rejected_without_unique_instance_claim():
    from dataclasses import fields, is_dataclass
    from tests.fixtures.program_driver_graphs import _body_with_environment
    def rename(item):
        if type(item).__name__.endswith("ID") and isinstance(getattr(item, "value", None), str) and item.value.startswith("resume"):
            return type(item)("other" + item.value[len("resume"):])
        if isinstance(item, tuple):
            return tuple(rename(value) for value in item)
        if is_dataclass(item):
            return replace(item, **{field.name: rename(getattr(item, field.name)) for field in fields(item)})
        return item
    other = rename(_body_with_environment())
    graph = driver_program(create=True)
    row = graph.resumable_creates[0]
    row = replace(row, body=other.root, captures=tuple(replace(capture, formal=rename(capture.formal)) for capture in row.captures))
    graph = replace(graph, regions=(*graph.regions, replace(other.regions[0], parent=graph.root)),
        values=(*graph.values, *other.values), operations=(*graph.operations, *other.operations),
        locations=(*graph.locations, *other.locations), environments=(*graph.environments, *other.environments),
        function_entries=(*graph.function_entries, *other.function_entries),
        control_scopes=(*graph.control_scopes, *other.control_scopes),
        resumable_bodies=(*graph.resumable_bodies, *other.resumable_bodies),
        frame_context_initials=(*graph.frame_context_initials, *other.frame_context_initials),
        frame_context_attaches=(*graph.frame_context_attaches, *other.frame_context_attaches),
        frame_context_detaches=(*graph.frame_context_detaches, *other.frame_context_detaches),
        resumable_creates=(row,))
    assert "driver_instance_body" in _codes(graph)
