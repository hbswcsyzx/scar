"""Hand-built D2.2 true/false close-test graphs.

The fixtures encode typed operations, values, Uses, state versions and control
edges. They do not implement or claim the runtime close predicate.
"""
from __future__ import annotations

from dataclasses import replace

from scar.ir.program.control import ProtocolValueKind as P, ProtocolValueType
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.lifecycle import CreatedCloseTest, NoBodyFinish
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature, CompletionSuccessor, DataValue, ExitKind, ExitPort,
    Footprint, FootprintKind, Operation, OperationResult, ProtocolValue,
    ReferenceValue, StateAccess, StateVersionValue, Successor, Terminator,
    TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.structured import ControlEdgeReference

from tests.fixtures.program_publication_graphs import publication_program, with_publications


REFERENCE = ValueType(ValueKind.REFERENCE)


def _clone(value, identity, block, index):
    origin = BlockArgument(block, index)
    if isinstance(value, (ReferenceValue, ProtocolValue, StateVersionValue, DataValue)):
        return replace(value, id=identity, origin=origin)
    raise TypeError(f"unsupported driver block argument type: {type(value).__name__}")


def _role(values, value):
    item = values[value]
    if isinstance(item, StateVersionValue):
        return UseRole.STATE_CONTENT
    if isinstance(item, ProtocolValue):
        return UseRole.PROTOCOL
    if isinstance(item, DataValue):
        return UseRole.DATA
    return UseRole.REFERENCE


def _terminal(name, arguments, values, *, fail=False):
    uses = tuple(Use(UseID(f"{name}.use.{index}"), value, _role(values, value))
                 for index, value in enumerate(arguments))
    return Operation(OperationID(name), name, (Behavior.CONTROL,), uses,
        terminator=Terminator(TerminatorKind.RAISE if fail else TerminatorKind.RETURN,
                              exit="failure" if fail else "normal",
                              values=tuple(use.id for use in uses)))


def _driver_region(graph, interface):
    region = next(item for item in graph.regions if item.id == interface.region)
    return region, {block.id: block for block in region.blocks}


def _add_external_effective_request(graph, region, entry, values):
    """Add an actual raw effective request to an ASYNC_REQUEST entry."""
    raw = ProtocolValue(ValueID("driver.external.effective"), region.id,
                        BlockArgument(entry.id, len(entry.arguments)), P.RAW_DRIVER_REQUEST)
    values[raw.id] = raw
    entry = replace(entry, arguments=(*entry.arguments, raw.id))
    return entry, raw.id


def _insert_association(graph, interface, gate, gate_row, entry, values):
    """Create a real association INVOKE before the test, with state outcomes.

    This narrow helper is used only for ASYNC_REQUEST. Request and states are
    actual invoke inputs; body/effective request are NORMAL CompletionResults.
    Fixed scheduler/session and resume delivery are independent forwarded Uses.
    """
    from scar.ir.program.drivers import NormalResultPort, RequestAssociationRead

    region = next(item for item in graph.regions if item.id == interface.region)
    blocks = {block.id: block for block in region.blocks}
    original_args = tuple(entry.arguments)
    request_value = original_args[gate_row.session_argument]
    scheduler_value = original_args[gate_row.scheduler_argument]
    delivery_values = tuple(original_args[index] for index in gate_row.delivery_arguments)
    state_values = tuple(value for value in original_args if isinstance(values[value], StateVersionValue))
    locations = tuple(values[value].location for value in state_values)

    request = Use(UseID("driver.association.request"), request_value, UseRole.REFERENCE)
    state_uses = tuple(Use(UseID(f"driver.association.state.{i}"), value, UseRole.STATE_CONTENT)
                       for i, value in enumerate(state_values))
    forward_values = (scheduler_value, request_value, *delivery_values)
    forwards = tuple(Use(UseID(f"driver.association.forward.{i}"), value, _role(values, value))
                     for i, value in enumerate(forward_values))

    test_block_id = BlockID("driver.no_body.test")
    body = ReferenceValue(ValueID("driver.association.body"), region.id,
                          BlockArgument(test_block_id, 0))
    effective = ProtocolValue(ValueID("driver.association.effective"), region.id,
                              BlockArgument(test_block_id, 1), P.RAW_DRIVER_REQUEST)
    test_args = [body.id, effective.id]
    test_values = [body, effective]
    for value in (scheduler_value, request_value, *delivery_values):
        index = len(test_args)
        copied = _clone(values[value], ValueID(f"driver.no_body.test.arg.{index}"),
                        test_block_id, index)
        test_args.append(copied.id)
        test_values.append(copied)
    for location in locations:
        index = len(test_args)
        current = StateVersionValue(ValueID(f"driver.no_body.test.state.{index}"), region.id,
                                    BlockArgument(test_block_id, index), location)
        test_args.append(current.id)
        test_values.append(current)
    values.update((value.id, value) for value in test_values)

    states = tuple(ValueType(ValueKind.STATE, location=location) for location in locations)
    normal_types = (REFERENCE, ProtocolValueType(P.RAW_DRIVER_REQUEST), *states)
    failure_types = (ProtocolValueType(P.EXCEPTION_PACKET), *states)
    normal = CompletionSuccessor(ExitKind.NORMAL, test_block_id,
        (CompletionResult(0), CompletionResult(1), *(use.id for use in forwards),
         *(CompletionResult(index) for index in range(2, 2 + len(locations)))))
    failure_id = BlockID("driver.association.raise")
    packet = ProtocolValue(ValueID("driver.association.packet"), region.id,
                           BlockArgument(failure_id, 0), P.EXCEPTION_PACKET)
    raised_states = tuple(StateVersionValue(ValueID(f"driver.association.raise.state.{i}"),
        region.id, BlockArgument(failure_id, i + 1), location)
        for i, location in enumerate(locations))
    values.update((value.id, value) for value in (packet, *raised_states))
    raise_args = (packet.id, *(state.id for state in raised_states))
    raise_terminal = _terminal("driver.association.raise.exit", raise_args, values, fail=True)
    failure = CompletionSuccessor(ExitKind.RAISE, failure_id,
        tuple(CompletionResult(index) for index in range(1 + len(locations))))
    assoc_id = OperationID("driver.association.read")
    association_op = Operation(assoc_id, "read request association", (Behavior.CONTROL,),
        (request, *state_uses, *forwards), invoke_arguments=(request.id, *(item.id for item in state_uses)),
        completions=(CompletionSignature(ExitKind.NORMAL, normal_types),
                     CompletionSignature(ExitKind.RAISE, failure_types)),
        terminator=Terminator(TerminatorKind.INVOKE, (normal, failure)), effects_complete=False)
    row = RequestAssociationRead(assoc_id, request.id, NormalResultPort(0),
                                 NormalResultPort(1), interface.rule)

    new_entry = replace(entry, operations=(assoc_id,))
    blocks[entry.id] = new_entry
    test_block = Block(test_block_id, tuple(test_args), ())
    raise_block = Block(failure_id, raise_args, (raise_terminal.id,))
    region = replace(region,
        blocks=tuple(blocks[block.id] for block in region.blocks) + (test_block, raise_block))
    graph = replace(graph,
        regions=tuple(region if old.id == region.id else old for old in graph.regions),
        operations=(*graph.operations, association_op, raise_terminal),
        values=(*graph.values, *test_values, packet, *raised_states),
        request_association_reads=(*graph.request_association_reads, row))
    sources = {
        "body": body.id,
        "effective": effective.id,
        "scheduler": test_args[2],
        "session": test_args[3],
        "delivery": tuple(test_args[4:4 + len(delivery_values)]),
        "states": tuple(test_args[4 + len(delivery_values):]),
    }
    return graph, test_block_id, sources


def no_body_program(receiver="BODY", direct_owner=False, strict_subset=False,
                    extra_domain=False, create=False, predicate_only=False,
                    target="start", association=False, base_graph=None):
    """Construct a generic close-test graph over a D1 driver.

    BODY uses the fixed scheduler as the effective request with a separate Use.
    ASYNC_REQUEST accepts an external RAW effective request, or with
    ``association=True`` produces B/E from a typed RequestAssociationRead.
    ``base_graph`` may be a driver fixture (including multiple Create sites);
    publication metadata is added only when it is not already present.
    """
    if receiver not in ("BODY", "ASYNC_REQUEST"):
        raise ValueError("receiver must be BODY or ASYNC_REQUEST")
    if association and receiver != "ASYNC_REQUEST":
        raise ValueError("association requires an ASYNC_REQUEST receiver")
    if association and create:
        raise ValueError("association fixture uses an external request boundary")
    if base_graph is None:
        graph = publication_program(target=target, extra_domain=extra_domain,
            strict_subset=strict_subset, create=create,
            async_request=receiver == "ASYNC_REQUEST")
    else:
        graph = (base_graph if base_graph.driver_lifecycles
                 else with_publications(base_graph, strict_subset=strict_subset))

    interface, = graph.driver_interfaces
    region, blocks = _driver_region(graph, interface)
    values = {value.id: value for value in graph.values}
    operations = {op.id: op for op in graph.operations}
    entry = blocks[region.entry]
    gate_row = next(row for row in graph.final_body_gates)
    gate = operations[gate_row.operation]
    original_entry_args = tuple(entry.arguments)
    original_gate_args = original_entry_args
    original_state_args = tuple(value for value in original_entry_args
                                if isinstance(values[value], StateVersionValue))

    external_effective = None
    if receiver == "ASYNC_REQUEST" and not association:
        entry, external_effective = _add_external_effective_request(
            graph, region, entry, values)
        original_entry_args = tuple(entry.arguments)
        blocks[entry.id] = entry

    if association:
        graph, test_block_id, associated = _insert_association(
            graph, interface, gate, gate_row, entry, values)
        region, blocks = _driver_region(graph, interface)
        values = {value.id: value for value in graph.values}
        operations = {op.id: op for op in graph.operations}
        entry = blocks[region.entry]
        test_args = blocks[test_block_id].arguments
        body_value = associated["body"]
        scheduler_value = associated["scheduler"]
        session_value = associated["session"]
        effective_value = associated["effective"]
        delivery_values = associated["delivery"]
        state_values = associated["states"]
        # For false, association NORMAL results replace only the BODY/E roles;
        # scheduler/session and delivered value remain explicit edge copies.
        gate_sources = (body_value, scheduler_value, session_value,
                        *delivery_values, *state_values)
    else:
        test_block_id = region.entry
        test_args = tuple(entry.arguments)
        body_value = test_args[gate_row.body_argument]
        scheduler_value = test_args[gate_row.scheduler_argument]
        session_value = (None if gate_row.session_argument is None
                         else test_args[gate_row.session_argument])
        effective_value = scheduler_value if receiver == "BODY" else external_effective
        delivery_values = tuple(test_args[index] for index in gate_row.delivery_arguments)
        state_values = tuple(value for value in test_args
                             if isinstance(values[value], StateVersionValue))
        gate_sources = tuple(original_entry_args[:-1] if external_effective is not None
                             else original_entry_args)

    gate_block_id = BlockID("driver.close.fallback")
    gate_args, gate_clones = [], []
    for index, source in enumerate(original_gate_args):
        identity = ValueID(f"driver.close.fallback.arg.{index}")
        cloned = _clone(values[source], identity, gate_block_id, index)
        gate_args.append(identity)
        gate_clones.append(cloned)
        values[identity] = cloned
    gate_map = dict(zip(original_gate_args, gate_args))
    gate = operations[gate_row.operation]
    moved_gate = replace(gate,
        uses=tuple(replace(use, value=gate_map.get(use.value, use.value)) for use in gate.uses))
    operations[gate.id] = moved_gate

    test_id = OperationID("driver.created_close.test")
    bool_value = DataValue(ValueID("driver.created_close.bool"), interface.region,
                           OperationResult(test_id, 0), "builtins.bool")
    instance_use = Use(UseID("driver.created_close.instance"), body_value, UseRole.REFERENCE)
    scheduler_use = Use(UseID("driver.created_close.scheduler"), scheduler_value, UseRole.PROTOCOL)
    effective_use = Use(UseID("driver.created_close.effective"), effective_value, UseRole.PROTOCOL)
    session_use = (None if receiver == "BODY" else
                   Use(UseID("driver.created_close.session"), session_value, UseRole.REFERENCE))
    roles = [instance_use, scheduler_use, effective_use]
    if session_use is not None:
        roles.append(session_use)
    state_uses, accesses = [], []
    current_by_location = {values[value].location: value for value in state_values}
    for index, location in enumerate(interface.lifecycle):
        current = current_by_location[location]
        before = Use(UseID(f"driver.created_close.before.{index}"), current, UseRole.STATE_CONTENT)
        state_uses.append(before)
        accesses.append(StateAccess(location, before.id, AccessMode.READ,
                                    footprint=Footprint(FootprintKind.WHOLE)))
    test = Operation(test_id, "created close predicate",
        (Behavior.CONTROL, Behavior.READ), (*roles, *state_uses), (bool_value.id,),
        tuple(accesses), effects_complete=True)
    condition = Use(UseID("driver.created_close.condition"), bool_value.id, UseRole.DATA)

    # The BRANCH starts a distinct no-body terminal path or sends the unchanged
    # current roles/states through a fresh gate corridor.
    true_id = BlockID("driver.no_body.finish")
    true_args, true_values = [], []
    if not direct_owner:
        owner = _clone(values[body_value], ValueID("driver.no_body.owner"), true_id, 0)
        true_args.append(owner.id)
        true_values.append(owner)
        values[owner.id] = owner
    state_start = len(true_args)
    driver_locations = tuple(values[value].location for value in state_values)
    for index, location in enumerate(driver_locations):
        identity = ValueID(f"driver.no_body.state.{index}")
        item = StateVersionValue(identity, interface.region,
                                 BlockArgument(true_id, len(true_args)), location)
        true_args.append(identity)
        true_values.append(item)
        values[identity] = item

    branch_uses = [condition]
    false_args = []
    for index, value in enumerate(gate_sources):
        use = Use(UseID(f"driver.created_close.false.{index}"), value, _role(values, value))
        branch_uses.append(use)
        false_args.append(use.id)
    true_args_uses = []
    if not direct_owner:
        use = Use(UseID("driver.created_close.true.owner"), body_value, UseRole.REFERENCE)
        branch_uses.append(use)
        true_args_uses.append(use.id)
    for index, state in enumerate(state_values):
        use = Use(UseID(f"driver.created_close.true.state.{index}"), state, UseRole.STATE_CONTENT)
        branch_uses.append(use)
        true_args_uses.append(use.id)

    rows = []
    operations_to_add = []
    if predicate_only:
        terminal_owner = body_value if direct_owner else true_args[0]
        current_states = {values[value].location: value for value in true_args[state_start:]}
    else:
        finish_id = OperationID("driver.no_body.finish")
        finish_instance = Use(UseID("driver.no_body.finish.instance"),
            body_value if direct_owner else true_args[0], UseRole.REFERENCE)
        finish_uses = [finish_instance]
        finish_accesses, finish_results = [], []
        true_states = true_args[state_start:]
        true_state_map = {values[value].location: value for value in true_states}
        write_location = interface.lifecycle[0]
        for index, location in enumerate(interface.lifecycle):
            before = Use(UseID(f"driver.no_body.finish.before.{index}"),
                         true_state_map[location], UseRole.STATE_CONTENT)
            finish_uses.append(before)
            if location == write_location:
                result = ValueID(f"driver.no_body.finish.after.{index}")
                after = StateVersionValue(result, interface.region,
                    OperationResult(finish_id, len(finish_results)), location)
                values[result] = after
                finish_results.append(result)
                finish_accesses.append(StateAccess(location, before.id, AccessMode.READ_WRITE,
                    result, Footprint(FootprintKind.WHOLE)))
            else:
                finish_accesses.append(StateAccess(location, before.id, AccessMode.READ,
                    footprint=Footprint(FootprintKind.WHOLE)))
        finish = Operation(finish_id, "no body finish",
            (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), tuple(finish_uses),
            tuple(finish_results), tuple(finish_accesses), effects_complete=True)
        operations_to_add.append(finish)
        rows.append(NoBodyFinish(finish_id, ControlEdgeReference(
            OperationID("driver.created_close.branch"), 0), finish_instance.id))
        terminal_owner = body_value if direct_owner else true_args[0]
        current_states = {values[value].location: value for value in true_states}
        for access in finish_accesses:
            if access.after is not None:
                current_states[access.location] = access.after

    normal_returns = [Use(UseID("driver.no_body.return.instance"), terminal_owner, UseRole.REFERENCE)]
    for index, location in enumerate(driver_locations):
        normal_returns.append(Use(UseID(f"driver.no_body.return.state.{index}"),
                                 current_states[location], UseRole.STATE_CONTENT))
    terminal = Operation(OperationID("driver.no_body.return"), "normal host return",
        (Behavior.CONTROL,), tuple(normal_returns),
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=tuple(use.id for use in normal_returns)))
    operations_to_add.append(terminal)
    true_block = Block(true_id, tuple(true_args), tuple(op.id for op in operations_to_add))

    branch_id = OperationID("driver.created_close.branch")
    branch = Operation(branch_id, "created-close choice", (Behavior.CONTROL,),
        tuple(branch_uses), terminator=Terminator(TerminatorKind.BRANCH,
            (Successor(true_id, tuple(true_args_uses)),
             Successor(gate_block_id, tuple(false_args))), condition=condition.id),
        effects_complete=True)
    entry_ops = (test.id, branch.id)

    # If association read is enabled, the entry remains the INVOKE and its
    # NORMAL block gets the test/branch. Otherwise the driver entry itself does.
    region, blocks = _driver_region(graph, interface)
    block_map = {block.id: block for block in region.blocks}
    operations = {op.id: op for op in graph.operations}
    operations[moved_gate.id] = moved_gate
    values.update((value.id, value) for value in graph.values)
    values.update((value.id, value) for value in (*gate_clones, bool_value, *true_values))
    if not association:
        block_map[region.entry] = replace(block_map[region.entry], operations=entry_ops,
                                          arguments=tuple(original_entry_args))
    else:
        block_map[test_block_id] = replace(block_map[test_block_id], operations=entry_ops)
    block_map[gate_block_id] = Block(gate_block_id, tuple(gate_args), (gate.id,))
    block_map[true_id] = true_block
    exits = list(region.exits)
    if not any(port.kind is ExitKind.NORMAL for port in exits):
        exits.append(ExitPort("normal", ExitKind.NORMAL,
            (REFERENCE, *(ValueType(ValueKind.STATE, location=location)
                          for location in driver_locations))))
    region = replace(region,
        blocks=tuple(block_map.get(block.id, block) for block in region.blocks)
            + tuple(block for identity, block in block_map.items()
                    if identity not in {item.id for item in region.blocks}),
        exits=tuple(exits))
    scopes = []
    for scope in graph.control_scopes:
        if scope.region == region.id:
            added = tuple(block.id for block in region.blocks if block.id not in scope.blocks)
            scope = replace(scope, blocks=(*scope.blocks, *added))
        scopes.append(scope)

    old_operation_ids = {op.id for op in graph.operations}
    operations.update((op.id, op) for op in (test, branch, *operations_to_add))
    graph = replace(graph,
        regions=tuple(region if old.id == region.id else old for old in graph.regions),
        operations=tuple(operations[op.id] for op in graph.operations)
            + tuple(op for op in (test, branch, *operations_to_add) if op.id not in old_operation_ids),
        values=tuple(values[value.id] for value in graph.values)
            + tuple(value for identity, value in values.items()
                    if identity not in {old.id for old in graph.values}),
        control_scopes=tuple(scopes),
        created_close_tests=(*graph.created_close_tests,
            CreatedCloseTest(test.id, instance_use.id, scheduler_use.id, effective_use.id,
                             None if session_use is None else session_use.id, bool_value.id)),
        no_body_finishes=(*graph.no_body_finishes, *rows))
    return graph


__all__ = ["no_body_program"]
