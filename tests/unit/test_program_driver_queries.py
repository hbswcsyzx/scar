"""Driver queries expose original canonical endpoints, never runtime proofs."""
from dataclasses import replace

import pytest

from scar.ir.program.codec import dumps, loads
from scar.ir.program.drivers import BodyDriveResult, NormalResultPort, RawRequestKind
from scar.ir.program.ids import BlockID, OperationID, RegionID, ValueID
from scar.ir.program.model import (
    BlockArgument, CompletionResult, ExitKind, StateVersionValue, TerminatorKind,
)
from scar.ir.program.queries import InstanceCaptureInput, ProgramIndex
from scar.ir.program.resumption import ResumeSlotKind
from tests.fixtures.program_driver_graphs import (
    async_request_program, create_only_program, driver_program, raw_only_program,
)


@pytest.mark.parametrize("kind", list(RawRequestKind))
def test_raw_request_operands_are_original_ordered_uses_and_known_empty_is_not_unknown(kind):
    graph = raw_only_program(kind)
    index = ProgramIndex(graph)
    row = graph.raw_driver_requests[0]
    assert index.raw_driver_request(row.value) is row
    operands = index.raw_driver_operands(row.value)
    assert tuple(site.use.id for site in operands) == row.operands
    assert all(site is index.use_site(site.use.id) for site in operands)
    if kind in (RawRequestKind.NEXT, RawRequestKind.CLOSE):
        assert operands == ()
    reference = next(value.id for value in graph.values if value.id != row.value)
    assert index.raw_driver_request(reference) is None
    assert index.raw_driver_operands(reference) is None


def test_create_bindings_and_normal_handle_keep_original_formals_uses_and_producer():
    graph = create_only_program()
    index = ProgramIndex(graph)
    row = graph.resumable_creates[0]
    assert index.resumable_create(row.operation) is row
    bindings = index.creation_bindings(row.operation)
    assert tuple(binding.formal for binding in bindings) == tuple(capture.formal for capture in row.captures)
    for binding, capture in zip(bindings, row.captures):
        assert binding.actual is index.use_site(capture.source)
    handle = index.normal_result(row.operation, row.handle_result)
    assert handle is index.values[handle.id]
    assert type(handle.origin) is BlockArgument
    assert index.producer(handle.id) is handle.origin
    assert index.body_drive(row.operation) is None
    assert graph.body_drives == ()


def test_request_creation_and_association_normal_ports_return_canonical_values_without_identity_claims():
    graph = async_request_program()
    index = ProgramIndex(graph)
    create = graph.async_request_creates[0]
    read = graph.request_association_reads[0]
    assert index.async_request_create(create.operation) is create
    assert index.request_association_read(read.operation) is read
    request = index.normal_result(create.operation, create.request_result)
    body = index.normal_result(read.operation, read.body_result)
    latent = index.normal_result(read.operation, read.latent_result)
    assert all(index.values[value.id] is value for value in (request, body, latent))
    assert all(type(value.origin) is BlockArgument for value in (request, body, latent))
    assert latent.protocol.value == "RAW_DRIVER_REQUEST"
    assert index.raw_driver_request(latent.id) is None
    assert index.raw_driver_operands(latent.id) is None
    assert graph.body_drives == ()


def test_normal_result_uses_projection_index_instead_of_landing_position():
    graph = create_only_program()
    row = graph.resumable_creates[0]
    op = next(operation for operation in graph.operations if operation.id == row.operation)
    edge = next(edge for edge in op.terminator.successors if edge.kind is ExitKind.NORMAL)
    block = next(block for region in graph.regions for block in region.blocks if block.id == edge.block)
    permutation = tuple(reversed(range(len(block.arguments))))
    formals = tuple(block.arguments[index] for index in permutation)
    reordered = replace(edge, arguments=tuple(edge.arguments[index] for index in permutation))
    op = replace(op, terminator=replace(op.terminator, successors=tuple(
        reordered if current is edge else current for current in op.terminator.successors)))
    graph = replace(graph,
        operations=tuple(op if operation.id == op.id else operation for operation in graph.operations),
        regions=tuple(replace(region, blocks=tuple(
            replace(current, arguments=formals) if current.id == block.id else current
            for current in region.blocks)) for region in graph.regions),
        values=tuple(replace(value, origin=BlockArgument(block.id, formals.index(value.id)))
                     if value.id in formals else value for value in graph.values))
    index = ProgramIndex(graph)
    result = index.normal_result(row.operation, row.handle_result)
    original_position = next(position for position, actual in enumerate(edge.arguments)
                             if type(actual) is CompletionResult and actual.index == row.handle_result.index)
    assert result.id == block.arguments[original_position]
    assert result.origin.index != original_position


def test_external_start_projects_instance_captures_and_current_states_without_selecting_a_create():
    graph = driver_program(extra_domain=True)
    before = dumps(graph)
    index = ProgramIndex(graph)
    drive = graph.body_drives[0]
    assert graph.resumable_creates == ()
    body = index.regions[drive.target.body]
    entry = next(block for block in body.blocks if block.id == body.entry)
    bindings = index.drive_input_bindings(drive.operation)
    assert tuple(binding.formal for binding in bindings) == entry.arguments
    states = {item.location: item.source for item in drive.state_inputs}
    for binding in bindings:
        value = index.values[binding.formal]
        if isinstance(value, StateVersionValue):
            assert binding.source is index.use_site(states[value.location])
        else:
            assert type(binding.source) is InstanceCaptureInput
            assert binding.source.instance is index.use_site(drive.instance)
            assert binding.source.formal == binding.formal
        assert type(index.producer(binding.formal)) is BlockArgument
    assert dumps(graph) == before


@pytest.mark.parametrize("target", ["value", "packet"])
def test_resume_inputs_keep_original_saved_uses_and_match_current_state_and_payload_slots(target):
    graph = driver_program(target=target, extra_domain=True)
    index = ProgramIndex(graph)
    drive = graph.body_drives[0]
    states = {item.location: item.source for item in drive.state_inputs}
    payloads = {item.slot: item.source for item in drive.resume_inputs}
    suspend = index.operations[drive.target.suspend]
    edge = suspend.terminator.successors[drive.target.successor]
    recipes = index.resumption_bindings(drive.target.suspend, drive.target.successor)
    bindings = index.drive_input_bindings(drive.operation)
    assert len(bindings) == len(recipes)
    seen = set()
    for binding, recipe, projection in zip(bindings, recipes, edge.arguments):
        assert binding.formal == recipe.formal
        assert binding.source is index.use_site(binding.source.use.id)
        assert type(index.producer(binding.formal)) is BlockArgument
        if recipe.saved is not None:
            assert binding.source is recipe.saved
            assert binding.source.operation == suspend.id
            seen.add("saved")
        else:
            slot = edge.inputs[projection.resume_slot]
            expected = states[slot.location] if slot.kind is ResumeSlotKind.STATE else payloads[projection.resume_slot]
            assert binding.source is index.use_site(expected)
            assert binding.source.operation == drive.operation
            seen.add("state" if slot.kind is ResumeSlotKind.STATE else "payload")
    assert seen == {"saved", "state", "payload"}
    driver_uses = {use.id for use in index.operations[drive.operation].uses}
    assert driver_uses.isdisjoint(slot.use for slot in suspend.terminator.saved)


@pytest.mark.parametrize("target, expected", [
    ("start", TerminatorKind.SUSPEND), ("value", TerminatorKind.RETURN),
    ("packet", TerminatorKind.RAISE),
])
def test_drive_outcomes_and_bindings_resolve_actual_source_uses_and_extra_state(target, expected):
    graph = driver_program(target=target, extra_domain=True)
    index = ProgramIndex(graph)
    row = graph.body_drives[0]
    assert index.body_drive(row.operation) is row
    gate = graph.final_body_gates[0]
    assert index.final_body_gate(gate.operation) is gate
    assert index.driver_interface(graph.driver_interfaces[0].region) is graph.driver_interfaces[0]
    outcomes = index.drive_outcomes(row.operation)
    assert len(outcomes) == 1 and outcomes[0].kind is expected
    assert all(site is index.use_site(site.use.id) for site in outcomes[0].values)
    term = index.operations[row.operation].terminator
    edge = term.successors[0]
    assert outcomes[0].operation == edge.source
    bindings = index.drive_bindings(row.operation, edge.source)
    source_sites = outcomes[0].values
    assert len(bindings) == len(edge.arguments)
    for binding, actual in zip(bindings, edge.arguments):
        assert type(index.producer(binding.formal)) is BlockArgument
        assert binding.actual is index.use_site(binding.actual.use.id)
        if type(actual) is BodyDriveResult:
            assert binding.actual is source_sites[actual.index]
        else:
            assert binding.actual is index.use_site(actual)
            assert binding.actual.operation == row.operation
    if target == "start":
        saved = {slot.use for slot in index.operations[edge.source].terminator.saved}
        assert saved.isdisjoint(site.use.id for site in outcomes[0].values)
    assert dumps(loads(dumps(graph))) == dumps(graph)


def test_strict_queries_do_not_infer_a_driver_for_unrelated_values_regions_or_operations():
    graph = driver_program(create=True)
    index = ProgramIndex(graph)
    row = graph.body_drives[0]
    unrelated = OperationID("factory.raw.pack")
    assert index.body_drive(unrelated) is None
    assert index.creation_bindings(unrelated) is None
    assert index.drive_outcomes(unrelated) is None
    assert index.drive_input_bindings(unrelated) is None
    assert index.driver_interface(RegionID("resume")) is None
    assert index.async_request_create(unrelated) is None
    assert index.request_association_read(unrelated) is None
    for call in (
        lambda: index.raw_driver_request("raw"),
        lambda: index.body_drive("driver.drive"),
        lambda: index.driver_interface("driver"),
        lambda: index.drive_bindings(row.operation, "resume.suspend"),
        lambda: index.normal_result(OperationID("factory.create"), 0),
    ):
        with pytest.raises(TypeError):
            call()
    with pytest.raises(KeyError):
        index.raw_driver_request(ValueID("missing"))
    with pytest.raises(KeyError):
        index.body_drive(OperationID("missing"))
    with pytest.raises(KeyError):
        index.driver_interface(RegionID("missing"))
    with pytest.raises(KeyError):
        index.drive_bindings(row.operation, OperationID("missing"))
    with pytest.raises(ValueError, match="not an outcome"):
        index.drive_bindings(row.operation, unrelated)
    with pytest.raises(ValueError, match="requires INVOKE"):
        index.normal_result(unrelated, NormalResultPort(0))
    with pytest.raises(IndexError):
        index.normal_result(OperationID("factory.create"), NormalResultPort(100))
