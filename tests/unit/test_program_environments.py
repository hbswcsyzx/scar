"""Declared entry environments over real core call/state/control graphs.

These are manually constructed interfaces, not recovered source or runtime
code/environment proofs. Declared locations are necessary domains, not complete
read/alias summaries; sharing and omitted domains grant no purity authority.
"""
from dataclasses import replace

import pytest

from scar.ir.program.codec import dumps, loads
from scar.ir.program.environment_validation import environment_errors
from scar.ir.program.environments import (
    EnvironmentInterface, EnvironmentMember, EnvironmentRole, FunctionEntryLayout,
)
from scar.ir.program.functions import FormalPort
from scar.ir.program.ids import (
    BlockID, EnvironmentInterfaceID, LocationID, OperationID, RegionID, UseID, ValueID,
)
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, Footprint, FootprintKind,
    Operation, OperationResult, ProgramGraph, ReferenceValue, Region, StateLocation,
    StateVersionValue, Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.validation import require_valid, validate
from scar.ir.program.queries import ProgramIndex
from scar.ir.v2.ids import OperationDefinitionID, ValueSlotID
from tests.fixtures.program_graphs import shared_body_calls_program


_ROLES = (
    EnvironmentRole.FUNCTION_OBJECT, EnvironmentRole.GLOBALS_NAMESPACE,
    EnvironmentRole.BUILTINS_NAMESPACE, EnvironmentRole.DEFAULTS,
    EnvironmentRole.KEYWORD_DEFAULTS, EnvironmentRole.CAPTURED_CELL,
)


def _op(graph, name):
    return next(operation for operation in graph.operations if operation.id == OperationID(name))


def _replace_op(graph, name, **kwargs):
    return replace(graph, operations=tuple(
        replace(operation, **kwargs) if operation.id == OperationID(name) else operation
        for operation in graph.operations))


def _invoke_region(prefix):
    """Opaque body invocation with independent normal/raise post-state ports."""
    region = RegionID(prefix)
    entry = BlockID(prefix + ".entry")
    world = LocationID("world")
    values = [ReferenceValue(ValueID(prefix + ".input"), region, BlockArgument(entry, 0)),
              StateVersionValue(ValueID(prefix + ".before"), region, BlockArgument(entry, 1), world)]
    operands = (Use(UseID(prefix + ".input.use"), values[0].id, UseRole.REFERENCE),
                Use(UseID(prefix + ".state.use"), values[1].id, UseRole.STATE_CONTENT))
    blocks = [Block(entry, tuple(value.id for value in values), (OperationID(prefix + ".invoke"),))]
    signatures, successors, exits, terminals = [], [], [], []
    for kind in (ExitKind.NORMAL, ExitKind.RAISE):
        path = prefix + "." + kind.value.lower()
        block = BlockID(path)
        result = ReferenceValue(ValueID(path + ".value"), region, BlockArgument(block, 0))
        state = StateVersionValue(ValueID(path + ".state"), region, BlockArgument(block, 1), world)
        values.extend((result, state))
        result_types = (ValueType(ValueKind.REFERENCE), ValueType(ValueKind.STATE, location=world))
        signatures.append(CompletionSignature(kind, result_types))
        successors.append(CompletionSuccessor(kind, block, (CompletionResult(0), CompletionResult(1))))
        exits.append(ExitPort(kind.value.lower(), kind, result_types))
        uses = (Use(UseID(path + ".result.use"), result.id, UseRole.REFERENCE),
                Use(UseID(path + ".state.use"), state.id, UseRole.STATE_CONTENT))
        terminal = Operation(OperationID(path + ".done"), path, (Behavior.CONTROL,), uses,
                             terminator=Terminator(
                                 TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE,
                                 exit=kind.value.lower(), values=tuple(use.id for use in uses)))
        terminals.append(terminal)
        blocks.append(Block(block, (result.id, state.id), (terminal.id,)))
    invoke = Operation(OperationID(prefix + ".invoke"), "opaque invocation",
                       (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), operands,
                       terminator=Terminator(TerminatorKind.INVOKE, tuple(successors)),
                       completions=tuple(signatures), invoke_arguments=tuple(use.id for use in operands))
    owner = Region(region, prefix, entry, tuple(blocks), tuple(exits))
    return ProgramGraph(region, (owner,), (invoke, *terminals), tuple(values),
                        (StateLocation(world, "shared coarse environment state"),))


def _base_invoke_graph():
    parent, child = _invoke_region("parent"), _invoke_region("child")
    child_region = replace(child.regions[0], parent=parent.root)
    graph = replace(parent, regions=(*parent.regions, child_region),
                    operations=(*parent.operations, *child.operations),
                    values=(*parent.values, *child.values))
    return _replace_op(graph, "parent.invoke", callee=child.root)


def _environment_graph(*, invoke=False, alias_actuals=False, unknown_targets=False):
    graph = _base_invoke_graph() if invoke else shared_body_calls_program()
    if not invoke:
        # Python formals carry object references even for scalar arguments.
        # Preserve the generic shared fixture and its internal Data results.
        input_ids = {ValueID("caller.input"), ValueID("body.input")}
        graph = replace(graph, values=tuple(
            ReferenceValue(value.id, value.region, value.origin)
            if value.id in input_ids else value for value in graph.values),
            operations=tuple(replace(operation, uses=tuple(
                replace(use, role=UseRole.REFERENCE) if use.value in input_ids else use
                for use in operation.uses)) for operation in graph.operations))
        # No protocol here proves arbitrary reference arithmetic has no effects.
        graph = _replace_op(graph, "twice", effects_complete=False)
    location = graph.locations[0].id
    refs_by_region, regions, values = {}, [], list(graph.values)
    for region in graph.regions:
        entry = next(block for block in region.blocks if block.id == region.entry)
        references = tuple(ReferenceValue(
            ValueID(region.id.value + ".env." + role.value), region.id,
            BlockArgument(entry.id, len(entry.arguments) + index),
            targets=None if unknown_targets else (location,),
            selector=Footprint(FootprintKind.WHOLE)) for index, role in enumerate(_ROLES))
        refs_by_region[region.id] = references
        values.extend(references)
        entry = replace(entry, arguments=(*entry.arguments, *(ref.id for ref in references)))
        regions.append(replace(region, blocks=tuple(entry if block.id == entry.id else block
                                                    for block in region.blocks)))
    graph = replace(graph, regions=tuple(regions), values=tuple(values))
    operations = []
    for operation in graph.operations:
        if operation.callee is not None:
            caller = next(region for region in graph.regions
                          if any(operation.id in block.operations for block in region.blocks))
            references = refs_by_region[caller.id]
            operands = tuple(Use(UseID(operation.id.value + ".env." + role.value),
                                 references[0 if alias_actuals else index].id, UseRole.REFERENCE)
                             for index, role in enumerate(_ROLES))
            field = "invoke_arguments" if invoke else "call_arguments"
            operation = replace(operation, uses=(*operation.uses, *operands),
                                **{field: (*getattr(operation, field), *(use.id for use in operands))})
        operations.append(operation)
    graph = replace(graph, operations=tuple(operations))
    child = graph.regions[-1]
    references = refs_by_region[child.id]
    members = tuple(EnvironmentMember(
        role, reference.id, (location,),
        ValueSlotID("captured.counter") if role is EnvironmentRole.CAPTURED_CELL else None,
        0 if role is EnvironmentRole.CAPTURED_CELL else None,
    ) for role, reference in zip(_ROLES, references))
    environment = EnvironmentInterface(EnvironmentInterfaceID("function.environment"), child.id,
                                       OperationDefinitionID("declared.code.not.runtime.proof"), members)
    parameter = next(value for value in graph.values
                     if value.id == child.blocks[0].arguments[0])
    layout = FunctionEntryLayout(environment.id, (FormalPort(ValueSlotID("input"), parameter.id),))
    graph = replace(graph, environments=(environment,), function_entries=(layout,))
    if not invoke:
        # Existing explicit READ_WRITE now names the captured-cell reference;
        # state versions remain the ordinary entry/call/write/exit SSA values.
        count = _op(graph, "count.call")
        reference_use = Use(UseID("count.cell.reference"), references[-1].id, UseRole.REFERENCE)
        graph = _replace_op(graph, "count.call", uses=(*count.uses, reference_use),
                            accesses=(replace(count.accesses[0], reference=reference_use.id),),
                            effects_complete=not unknown_targets)
    return graph


def _codes(graph):
    return {issue.code for issue in validate(graph)}


def _replace_member(graph, position=0, **kwargs):
    environment = graph.environments[0]
    members = tuple(replace(member, **kwargs) if index == position else member
                    for index, member in enumerate(environment.members))
    return replace(graph, environments=(replace(environment, members=members),))


def _reorder_callee_entry(graph, order):
    """Reorder canonical ports and actuals together, preserving exact ValueIDs."""
    child = graph.regions[-1]
    entry = next(block for block in child.blocks if block.id == child.entry)
    arguments = tuple(entry.arguments[position] for position in order)
    positions = {identity: index for index, identity in enumerate(arguments)}
    child = replace(child, blocks=tuple(
        replace(block, arguments=arguments) if block.id == entry.id else block
        for block in child.blocks))
    operations = []
    for operation in graph.operations:
        if operation.callee == child.id:
            field = "invoke_arguments" if operation.terminator is not None else "call_arguments"
            actuals = getattr(operation, field)
            operation = replace(operation, **{field: tuple(actuals[index] for index in order)})
        operations.append(operation)
    return replace(graph, regions=(*graph.regions[:-1], child), operations=tuple(operations),
                   values=tuple(replace(value, origin=BlockArgument(entry.id, positions[value.id]))
                                if value.id in positions else value for value in graph.values))


@pytest.mark.parametrize("invoke", [False, True])
def test_environment_uses_canonical_entry_ports_and_existing_call_bindings(invoke):
    graph = _environment_graph(invoke=invoke)
    require_valid(graph)
    assert loads(dumps(graph)) == graph
    assert len(graph.environments[0].members) == 6
    assert not hasattr(graph, "environment_bindings")
    caller = next(operation for operation in graph.operations if operation.callee is not None)
    arguments = caller.invoke_arguments if invoke else caller.call_arguments
    assert len(arguments) == len(graph.regions[-1].blocks[0].arguments)


def test_captured_cell_contents_advance_between_two_calls_not_frozen_by_interface():
    graph = _environment_graph()
    require_valid(graph)
    first, second = _op(graph, "call1"), _op(graph, "call2")
    assert first.uses[1].value == ValueID("caller.initial")
    assert second.uses[1].value == ValueID("call1.state")
    count = _op(graph, "count.call")
    assert count.accesses[0].reference == UseID("count.cell.reference")
    assert count.accesses[0].after == ValueID("body.updated")
    stale = replace(second.uses[1], value=ValueID("caller.initial"))
    bad = _replace_op(graph, "call2", uses=(second.uses[0], stale, *second.uses[2:]))
    assert "stale_state" in _codes(bad)


@pytest.mark.parametrize("invoke", [False, True])
def test_distinct_environment_ports_allow_repeated_actual_object_references(invoke):
    graph = _environment_graph(invoke=invoke, alias_actuals=True)
    require_valid(graph)
    members = graph.environments[0].members
    assert len({member.reference for member in members}) == len(members)
    operation = next(operation for operation in graph.operations if operation.callee is not None)
    assert len({use.id for use in operation.uses[-6:]}) == 6
    assert len({use.value for use in operation.uses[-6:]}) == 1


@pytest.mark.parametrize("invoke", [False, True])
def test_missing_environment_actual_is_rejected_by_existing_call_interface(invoke):
    graph = _environment_graph(invoke=invoke)
    operation = next(operation for operation in graph.operations if operation.callee is not None)
    field = "invoke_arguments" if invoke else "call_arguments"
    bad = _replace_op(graph, operation.id.value, uses=operation.uses[:-1],
                      **{field: getattr(operation, field)[:-1]})
    expected = "invoke_callee_arity" if invoke else "call_arity"
    assert expected in _codes(bad)


@pytest.mark.parametrize("path", ["normal", "raise"])
def test_invoke_environment_keeps_path_specific_poststate_and_rejects_stale_exit(path):
    graph = _environment_graph(invoke=True)
    require_valid(graph)
    operation = _op(graph, "child." + path + ".done")
    assert operation.uses[1].value == ValueID("child." + path + ".state")
    stale = replace(operation.uses[1], value=ValueID("child.before"))
    bad = _replace_op(graph, operation.id.value, uses=(operation.uses[0], stale))
    assert "stale_state" in _codes(bad)


def test_environment_owner_must_exist_and_have_at_most_one_interface():
    graph = _environment_graph()
    environment = graph.environments[0]
    bad = replace(graph, environments=(replace(environment, region=RegionID("missing")),))
    assert "environment_owner" in _codes(bad)
    duplicate = replace(environment, id=EnvironmentInterfaceID("second"))
    assert "environment_region" in _codes(replace(graph, environments=(environment, duplicate)))


@pytest.mark.parametrize("which", ["missing", "state", "other_region", "non_entry_argument"])
def test_environment_member_must_be_an_owned_entry_reference(which):
    graph = _environment_graph(invoke=True)
    target = {"missing": ValueID("not.defined"), "state": ValueID("child.before"),
              "other_region": ValueID("parent.input"),
              "non_entry_argument": ValueID("child.raise.value")}[which]
    bad = _replace_member(graph, reference=target)
    assert "environment_reference" in _codes(bad)


def test_environment_cannot_replace_entry_identity_by_a_body_operation_result():
    graph = _environment_graph()
    child = graph.regions[-1]
    producer = Operation(OperationID("make.environment.reference"), "make reference",
                         (Behavior.MEMORY,), results=(ValueID("body.created.reference"),))
    reference = ReferenceValue(producer.results[0], child.id, OperationResult(producer.id, 0))
    region = replace(child, blocks=tuple(
        replace(block, operations=(producer.id, *block.operations)) if block.id == child.entry else block
        for block in child.blocks))
    graph = replace(graph, regions=(*graph.regions[:-1], region),
                    operations=(producer, *graph.operations), values=(*graph.values, reference))
    require_valid(replace(graph, environments=(), function_entries=()))
    assert "environment_reference" in _codes(_replace_member(graph, reference=reference.id))


def test_member_entry_origin_position_must_match_exact_canonical_argument():
    graph = _environment_graph()
    identity = graph.environments[0].members[0].reference
    reference = next(value for value in graph.values if value.id == identity)
    bad_reference = replace(reference, origin=replace(reference.origin, index=0))
    bad = replace(graph, values=tuple(bad_reference if value.id == identity else value
                                     for value in graph.values))
    # Exercise this validator directly as well as the earlier core origin check.
    issues = tuple(environment_errors(bad, {}, {}))
    assert "environment_reference" in {issue[0] for issue in issues}
    assert "argument_origin" in _codes(bad)


def test_environment_location_needs_existing_canonical_entry_state_domain():
    graph = _environment_graph()
    missing = _replace_member(graph, locations=(LocationID("missing"),))
    assert {"environment_location", "environment_state_domain"} <= _codes(missing)
    extra = StateLocation(LocationID("not.carried"), "not an entry state domain")
    bad = _replace_member(replace(graph, locations=(*graph.locations, extra)),
                          locations=(extra.id,))
    assert "environment_state_domain" in _codes(bad)


def test_environment_locations_cannot_contradict_known_reference_targets():
    graph = _environment_graph()
    identity = graph.environments[0].members[0].reference
    graph = replace(graph, values=tuple(replace(value, targets=()) if value.id == identity else value
                                        for value in graph.values))
    assert "environment_reference_targets" in _codes(graph)


def test_declared_locations_are_subset_not_full_read_or_alias_summary():
    graph = _environment_graph()
    environment = graph.environments[0]
    extra = StateLocation(LocationID("unread.target"), "possible target not required by this interface")
    # References may point at more than the aggregate's required entry domains.
    graph = replace(graph, locations=(*graph.locations, extra), values=tuple(
        replace(value, targets=(*value.targets, extra.id))
        if isinstance(value, ReferenceValue) and ".env.FUNCTION_OBJECT" in value.id.value else value
        for value in graph.values))
    require_valid(graph)
    assert all(extra.id not in member.locations for member in environment.members)
    omitted = replace(graph, environments=(replace(environment, members=tuple(
        replace(member, locations=()) for member in environment.members)),))
    require_valid(omitted)
    assert _op(omitted, "count.call").accesses  # omitted != NONE or a dropped write


def test_shared_coarse_domains_and_unknown_targets_do_not_assert_disjointness():
    graph = _environment_graph(unknown_targets=True)
    require_valid(graph)
    assert len({member.locations for member in graph.environments[0].members}) == 1
    assert not _op(graph, "count.call").effects_complete


def test_code_definition_is_only_a_declaration_not_runtime_verification():
    graph = _environment_graph()
    changed = replace(graph, environments=(replace(graph.environments[0],
                      code_definition=OperationDefinitionID("another.unverified.declaration")),))
    require_valid(changed)
    assert changed.operations == graph.operations
    assert changed.values == graph.values
    assert not hasattr(changed.environments[0], "runtime_verified")


def test_distinct_member_ports_do_not_allow_reusing_one_entry_value_definition():
    graph = _environment_graph()
    environment = graph.environments[0]
    duplicate = replace(environment.members[1], reference=environment.members[0].reference)
    with pytest.raises(ValueError, match="distinct"):
        replace(environment, members=(environment.members[0], duplicate, *environment.members[2:]))


def test_every_environment_has_exactly_one_explicit_function_entry_layout():
    graph = _environment_graph()
    assert "function_entry_missing" in _codes(replace(graph, function_entries=()))
    layout = graph.function_entries[0]
    dangling = replace(layout, environment=EnvironmentInterfaceID("missing.environment"))
    assert {"function_entry_environment", "function_entry_missing"} <= _codes(
        replace(graph, function_entries=(dangling,)))
    with pytest.raises(ValueError, match="function entry environments"):
        replace(graph, function_entries=(layout, layout))


def test_formal_slot_cannot_also_be_same_body_free_variable_slot():
    graph = _environment_graph()
    layout = graph.function_entries[0]
    cell_slot = graph.environments[0].members[-1].cell_slot
    parameter = replace(layout.parameters[0], slot=cell_slot)
    bad = replace(graph, function_entries=(replace(layout, parameters=(parameter,)),))
    assert _codes(bad) == {"function_entry_slot"}
    with pytest.raises(ValueError, match="function_entry_slot"):
        dumps(bad)


@pytest.mark.parametrize("invoke", [False, True])
@pytest.mark.parametrize("which", ["environment", "state", "missing", "body"])
def test_python_formal_must_be_its_own_exact_entry_reference(invoke, which):
    graph = _environment_graph(invoke=invoke)
    invalid = {
        "environment": graph.environments[0].members[0].reference,
        "state": ValueID("child.before" if invoke else "body.initial"),
        "missing": ValueID("absent.formal"),
        "body": ValueID("child.raise.value" if invoke else "body.result"),
    }[which]
    layout = graph.function_entries[0]
    bad = replace(graph, function_entries=(replace(
        layout, parameters=(replace(layout.parameters[0], value=invalid),)),))
    assert {"function_entry_parameter", "function_entry_partition"} <= _codes(bad)


@pytest.mark.parametrize("invoke", [False, True])
def test_python_formal_partition_cannot_omit_an_existing_reference_port(invoke):
    graph = _environment_graph(invoke=invoke)
    layout = replace(graph.function_entries[0], parameters=())
    assert _codes(replace(graph, function_entries=(layout,))) == {"function_entry_partition"}


def test_scalar_data_entry_is_not_a_python_object_reference_formal():
    graph = _environment_graph()
    identities = {ValueID("caller.input"), ValueID("body.input")}
    graph = replace(graph, values=tuple(
        DataValue(value.id, value.region, value.origin, "builtins.int")
        if value.id in identities else value for value in graph.values), operations=tuple(
            replace(operation, uses=tuple(
                replace(use, role=UseRole.DATA) if use.value in identities else use
                for use in operation.uses)) for operation in graph.operations))
    assert _codes(graph) == {"function_entry_parameter"}


def test_python_formal_requires_exact_entry_origin_not_just_matching_identity():
    graph = _environment_graph(invoke=True)
    identity = graph.function_entries[0].parameters[0].value
    bad = replace(graph, values=tuple(
        replace(value, origin=replace(value.origin, index=1)) if value.id == identity else value
        for value in graph.values))
    assert "function_entry_parameter" in {code for code, _, _ in environment_errors(bad, {}, {})}
    assert "argument_origin" in _codes(bad)


@pytest.mark.parametrize("invoke", [False, True])
def test_distinct_formal_and_environment_ports_may_receive_the_same_actual_reference(invoke):
    graph = _environment_graph(invoke=invoke)
    # Give both routes the same declared domain/selector; otherwise the core
    # quite correctly rejects unknown actual targets passed to a narrow formal.
    input_ids = {ValueID("parent.input"), ValueID("child.input")} if invoke else {
        ValueID("caller.input"), ValueID("body.input")}
    graph = replace(graph, values=tuple(replace(
        value, targets=(graph.locations[0].id,), selector=Footprint(FootprintKind.WHOLE))
        if value.id in input_ids else value for value in graph.values))
    operations = []
    for operation in graph.operations:
        if operation.callee is not None:
            env_use = UseID(operation.id.value + ".env.FUNCTION_OBJECT")
            operation = replace(operation, uses=tuple(
                replace(use, value=operation.uses[0].value) if use.id == env_use else use
                for use in operation.uses))
        operations.append(operation)
    graph = replace(graph, operations=tuple(operations))
    require_valid(graph)
    for operation in operations:
        if operation.callee is None:
            continue
        derived = ProgramIndex(graph).environment_call(operation.id)
        assert derived.parameters[0].parameter.value != derived.arguments[0].member.reference
        assert derived.parameters[0].actual.use.value == derived.arguments[0].actual.use.value


@pytest.mark.parametrize("invoke", [False, True])
def test_entry_physical_order_and_logical_parameter_order_are_independent(invoke):
    graph = _environment_graph(invoke=invoke)
    regions, values, added = [], list(graph.values), {}
    # A second ordinary reference makes signature order distinct from port order.
    for region in graph.regions:
        entry = next(block for block in region.blocks if block.id == region.entry)
        reference = ReferenceValue(ValueID(region.id.value + ".second.parameter"), region.id,
                                   BlockArgument(entry.id, len(entry.arguments)))
        added[region.id] = reference.id
        values.append(reference)
        regions.append(replace(region, blocks=tuple(
            replace(block, arguments=(*block.arguments, reference.id)) if block.id == entry.id else block
            for block in region.blocks)))
    operations = []
    for operation in graph.operations:
        if operation.callee is not None:
            actual = Use(UseID(operation.id.value + ".second.parameter"), added[graph.root],
                         UseRole.REFERENCE)
            field = "invoke_arguments" if invoke else "call_arguments"
            operation = replace(operation, uses=(*operation.uses, actual),
                                **{field: (*getattr(operation, field), actual.id)})
        operations.append(operation)
    layout = graph.function_entries[0]
    layout = replace(layout, parameters=(FormalPort(ValueSlotID("second"), added[graph.regions[-1].id]),
                                         *layout.parameters))
    graph = replace(graph, regions=tuple(regions), values=tuple(values),
                    operations=tuple(operations), function_entries=(layout,))
    # Mix environment, ordinary parameter, state and captured-cell ports. The
    # original formal is now physical index4, the logical first formal index1.
    graph = _reorder_callee_entry(graph, (2, 8, 1, 7, 0, 3, 4, 5, 6))
    require_valid(graph)
    assert loads(dumps(graph)) == graph
    index = ProgramIndex(graph)
    assert index.function_entry_layout(graph.regions[-1].id) == layout
    for operation in graph.operations:
        if operation.callee is None:
            continue
        derived = index.environment_call(operation.id)
        assert tuple(argument.parameter for argument in derived.parameters) == layout.parameters
        assert derived.parameters[0].actual.use.id == UseID(operation.id.value + ".second.parameter")
        assert derived.parameters[0].actual.use.value == added[graph.root]
        assert derived.parameters[1].actual.use.value == ValueID("parent.input" if invoke else "caller.input")
        for argument in derived.arguments:
            assert argument.actual.use.id == UseID(operation.id.value + ".env." + argument.member.role.value)
            assert len(argument.state_arguments) == 1
            assert argument.state_arguments[0].use.value == (
                ValueID("parent.before") if invoke else
                ValueID("caller.initial" if operation.id == OperationID("call1") else "call1.state"))
