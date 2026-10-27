import json
from dataclasses import replace

import pytest

from scar.ir.program import (
    AccessMode, Behavior, BindingDefinition, BindingRead, BindingState,
    Block, BlockArgument, BlockID, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, LocalBindingType,
    LocalBindingValue, LiteralOrigin, LocationID, Operation, OperationID,
    OperationResult, ProgramGraph, ReferenceValue, Region, RegionID,
    StateAccess, StateLocation, StateVersionValue, Successor, Terminator,
    TerminatorKind, Use, UseID, UseRole, ValueID, ValueKind, ValueType,
    derive_binding_facts, dumps, loads, value_type,
)
from scar.ir.program.binding_validation import validate_bindings
from scar.ir.program.validation import validate
from scar.ir.record_codec import encode
from scar.ir.v2.ids import ValueSlotID


def _type_state():
    return ValueType(ValueKind.STATE, location=LocationID("world"))


def _bound_graph():
    region = RegionID("bound")
    slot = ValueSlotID("x")
    payload = ReferenceValue(ValueID("payload"), region, LiteralOrigin("object"), targets=())
    token = LocalBindingValue(ValueID("binding"), region,
                              OperationResult(OperationID("bind"), 0), slot)
    bind_payload = Use(UseID("bind.payload"), payload.id, UseRole.REFERENCE)
    bind = Operation(OperationID("bind"), "bind", (Behavior.COMPUTE,),
                     (bind_payload,), (token.id,))
    read_input = Use(UseID("read.binding"), token.id, UseRole.LOCAL_BINDING)
    read = Operation(OperationID("read"), "read local", (Behavior.COMPUTE,),
                      (read_input,))
    returned = Use(UseID("return.value"), payload.id, UseRole.REFERENCE)
    ret = Operation(OperationID("return"), "return", (Behavior.CONTROL,),
                    (returned,), terminator=Terminator(
                        TerminatorKind.RETURN, exit="normal", values=(returned.id,)))
    block = Block(BlockID("entry"), (), (bind.id, read.id, ret.id))
    body = Region(region, "bound local", block.id, (block,), (
        ExitPort("normal", ExitKind.NORMAL, (ValueType(ValueKind.REFERENCE),)),
    ))
    graph = ProgramGraph(
        region, (body,), (bind, read, ret), (payload, token),
        binding_definitions=(BindingDefinition(token.id, BindingState.BOUND,
                                               bind_payload.id),),
        binding_reads=(BindingRead(read.id, read_input.id, payload.id),),
    )
    return graph


def _maybe_bound_graph():
    region_id = RegionID("maybe")
    slot = ValueSlotID("item")
    world = LocationID("world")
    values = (
        DataValue(ValueID("condition"), region_id, BlockArgument(BlockID("entry"), 0),
                  "builtins.bool"),
        StateVersionValue(ValueID("world.entry"), region_id,
                          BlockArgument(BlockID("entry"), 1), world),
        StateVersionValue(ValueID("world.bound"), region_id,
                          BlockArgument(BlockID("bound"), 0), world),
        StateVersionValue(ValueID("world.unbound"), region_id,
                          BlockArgument(BlockID("unbound"), 0), world),
        LocalBindingValue(ValueID("token.bound"), region_id,
                          OperationResult(OperationID("bind"), 0), slot),
        LocalBindingValue(ValueID("token.unbound"), region_id,
                          OperationResult(OperationID("unbind"), 0), slot),
        LocalBindingValue(ValueID("token.merge"), region_id,
                          BlockArgument(BlockID("join"), 0), slot),
        StateVersionValue(ValueID("world.join"), region_id,
                          BlockArgument(BlockID("join"), 1), world),
        ReferenceValue(ValueID("payload"), region_id, LiteralOrigin("value"), targets=()),
        ReferenceValue(ValueID("loaded"), region_id,
                       BlockArgument(BlockID("normal"), 0)),
        StateVersionValue(ValueID("world.normal"), region_id,
                          BlockArgument(BlockID("normal"), 1), world),
        ReferenceValue(ValueID("exception"), region_id,
                       BlockArgument(BlockID("failure"), 0)),
        StateVersionValue(ValueID("world.failure"), region_id,
                          BlockArgument(BlockID("failure"), 1), world),
    )
    values_by_id = {value.id: value for value in values}

    def u(name, value, role=UseRole.DATA):
        return Use(UseID(name), ValueID(value), role)

    branch_uses = (
        u("branch.condition", "condition"),
        u("branch.bound.world", "world.entry", UseRole.STATE_CONTENT),
        u("branch.unbound.world", "world.entry", UseRole.STATE_CONTENT),
    )
    branch = Operation(
        OperationID("branch"), "branch", (Behavior.CONTROL,), branch_uses,
        terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(BlockID("bound"), (branch_uses[1].id,)),
            Successor(BlockID("unbound"), (branch_uses[2].id,)),
        ), condition=branch_uses[0].id),
    )

    payload_use = u("bind.payload", "payload", UseRole.REFERENCE)
    bind = Operation(OperationID("bind"), "bound assignment", (Behavior.COMPUTE,),
                     (payload_use,), (ValueID("token.bound"),))
    unbind = Operation(OperationID("unbind"), "unbound initialization", (Behavior.COMPUTE,),
                       results=(ValueID("token.unbound"),))

    bound_carry = (
        u("bound.token", "token.bound", UseRole.LOCAL_BINDING),
        u("bound.world", "world.bound", UseRole.STATE_CONTENT),
    )
    bound_jump = Operation(OperationID("bound.jump"), "bound carry", (Behavior.CONTROL,),
                           bound_carry, terminator=Terminator(TerminatorKind.JUMP, (
                               Successor(BlockID("join"), tuple(use.id for use in bound_carry)),
                           )))
    unbound_carry = (
        u("unbound.token", "token.unbound", UseRole.LOCAL_BINDING),
        u("unbound.world", "world.unbound", UseRole.STATE_CONTENT),
    )
    unbound_jump = Operation(OperationID("unbound.jump"), "unbound carry", (Behavior.CONTROL,),
                             unbound_carry, terminator=Terminator(TerminatorKind.JUMP, (
                                 Successor(BlockID("join"), tuple(use.id for use in unbound_carry)),
                             )))

    read_token = u("load.token", "token.merge", UseRole.LOCAL_BINDING)
    read_world = u("load.world", "world.join", UseRole.STATE_CONTENT)
    read_signature = (ValueType(ValueKind.REFERENCE), _type_state())
    read = Operation(
        OperationID("load"), "maybe-bound read", (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
        (read_token, read_world), effects_complete=False,
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID("normal"),
                                (CompletionResult(0), CompletionResult(1))),
            CompletionSuccessor(ExitKind.RAISE, BlockID("failure"),
                                (CompletionResult(0), CompletionResult(1))),
        )),
        completions=(CompletionSignature(ExitKind.NORMAL, read_signature),
                     CompletionSignature(ExitKind.RAISE, read_signature)),
        invoke_arguments=(read_token.id, read_world.id),
    )

    normal_uses = (
        u("return.loaded", "loaded", UseRole.REFERENCE),
        u("return.world", "world.normal", UseRole.STATE_CONTENT),
    )
    normal = Operation(OperationID("normal"), "normal return", (Behavior.CONTROL,),
                       normal_uses, terminator=Terminator(
                           TerminatorKind.RETURN, exit="normal",
                           values=tuple(use.id for use in normal_uses)))
    failure_uses = (
        u("raise.exception", "exception", UseRole.REFERENCE),
        u("raise.world", "world.failure", UseRole.STATE_CONTENT),
    )
    failure = Operation(OperationID("failure"), "raise", (Behavior.CONTROL,),
                        failure_uses, terminator=Terminator(
                            TerminatorKind.RAISE, exit="raise",
                            values=tuple(use.id for use in failure_uses)))

    blocks = (
        Block(BlockID("entry"), (ValueID("condition"), ValueID("world.entry")),
              (branch.id,)),
        Block(BlockID("bound"), (ValueID("world.bound"),),
              (bind.id, bound_jump.id)),
        Block(BlockID("unbound"), (ValueID("world.unbound"),),
              (unbind.id, unbound_jump.id)),
        Block(BlockID("join"), (ValueID("token.merge"), ValueID("world.join")),
              (read.id,)),
        Block(BlockID("normal"), (ValueID("loaded"), ValueID("world.normal")),
              (normal.id,)),
        Block(BlockID("failure"), (ValueID("exception"), ValueID("world.failure")),
              (failure.id,)),
    )
    body = Region(region_id, "maybe-bound merge", BlockID("entry"), blocks, (
        ExitPort("normal", ExitKind.NORMAL,
                 (ValueType(ValueKind.REFERENCE), _type_state())),
        ExitPort("raise", ExitKind.RAISE,
                 (ValueType(ValueKind.REFERENCE), _type_state())),
    ))
    graph = ProgramGraph(
        region_id, (body,), (branch, bind, unbind, bound_jump, unbound_jump,
                             read, normal, failure), values,
        (StateLocation(world, "Python world"),),
        binding_definitions=(
            BindingDefinition(ValueID("token.bound"), BindingState.BOUND,
                              payload_use.id),
            BindingDefinition(ValueID("token.unbound"), BindingState.UNBOUND),
        ),
        binding_reads=(BindingRead(read.id, read_token.id, ValueID("loaded")),),
    )
    return graph, values_by_id


def test_local_binding_types_are_distinct_and_strict():
    slot = ValueSlotID("local:x")
    local_type = LocalBindingType(slot)
    token = LocalBindingValue(ValueID("token"), RegionID("r"),
                              OperationResult(OperationID("op"), 0), slot)
    assert value_type(token) == local_type
    assert local_type != ValueType(ValueKind.REFERENCE)
    with pytest.raises(TypeError):
        LocalBindingType("local:x")
    with pytest.raises(ValueError):
        LocalBindingValue(ValueID("bad"), RegionID("r"),
                          LiteralOrigin(None), slot)


def test_bound_definition_and_read_form_a_valid_typed_chain():
    graph = _bound_graph()
    assert validate(graph) == ()
    restored = loads(dumps(graph))
    assert restored == graph
    assert json.loads(dumps(graph))["schema_version"] == 3
    assert isinstance(restored.values[1], LocalBindingValue)
    assert restored.binding_definitions[0].state is BindingState.BOUND
    assert restored.binding_reads[0].normal_result == ValueID("payload")


def test_merge_boundness_is_derived_and_requires_invoke_for_maybe_read():
    graph, _ = _maybe_bound_graph()
    assert validate(graph) == ()

    read_op = next(op for op in graph.operations if op.id == OperationID("load"))
    forged = replace(read_op, effects_complete=True)
    changed = replace(graph, operations=tuple(forged if op.id == forged.id else op
                                              for op in graph.operations))
    issues = validate(changed)
    assert any(issue.code == "binding_read_effects" for issue in issues)

    # Changing only the metadata from a MAYBE merge to a normal result cannot
    # bypass the fact derived from the two incoming operation definitions.
    changed = replace(graph, binding_reads=(BindingRead(
        read_op.id, UseID("load.token"), None),))
    assert any(issue.code == "binding_read_missing_normal" for issue in validate(changed))

    # A definitely-bound read may still keep a conservative invocation edge.
    unbound_op = next(op for op in graph.operations if op.id == OperationID("unbind"))
    payload_use = Use(UseID("unbound.path.payload"), ValueID("payload"), UseRole.REFERENCE)
    concrete_unbound_op = replace(unbound_op, uses=(payload_use,))
    concrete_defs = (
        graph.binding_definitions[0],
        BindingDefinition(ValueID("token.unbound"), BindingState.BOUND, payload_use.id),
    )
    definitely_bound = replace(
        graph,
        operations=tuple(concrete_unbound_op if op.id == unbound_op.id else op
                         for op in graph.operations),
        binding_definitions=concrete_defs,
    )
    assert validate(definitely_bound) == ()
    invoke_read = next(op for op in definitely_bound.operations if op.id == read_op.id)
    overclaimed_read = replace(invoke_read, effects_complete=True)
    overclaimed = replace(
        definitely_bound,
        operations=tuple(overclaimed_read if op.id == overclaimed_read.id else op
                         for op in definitely_bound.operations),
    )
    assert any(issue.code == "binding_read_effects" for issue in validate(overclaimed))


def test_definitely_unbound_read_may_keep_a_dormant_normal_invoke_completion():
    graph, _ = _maybe_bound_graph()
    definitions = tuple(
        BindingDefinition(item.value, BindingState.UNBOUND)
        for item in graph.binding_definitions
    )
    only_unbound = replace(graph, binding_definitions=definitions)

    # The NORMAL completion is structurally represented, but its reference is
    # only a dormant completion parameter: derived boundness says this edge is
    # infeasible. A source query/oracle must not traverse it as a real read.
    assert validate(only_unbound) == ()
    facts = derive_binding_facts(only_unbound)
    assert facts[ValueID("token.merge")] == frozenset((BindingState.UNBOUND,))

    maybe_facts = derive_binding_facts(graph)
    assert maybe_facts[ValueID("token.merge")] == frozenset(
        (BindingState.BOUND, BindingState.UNBOUND))


def test_unknown_update_requires_old_binding_and_incomplete_world_access():
    region = RegionID("unknown")
    slot = ValueSlotID("x")
    previous = LocalBindingValue(ValueID("previous"), region,
                                 OperationResult(OperationID("initial"), 0), slot)
    unknown = LocalBindingValue(ValueID("unknown"), region,
                                OperationResult(OperationID("uncertain"), 0), slot)
    world = LocationID("world")
    before = StateVersionValue(ValueID("before"), region,
                              BlockArgument(BlockID("entry"), 0), world)
    after = StateVersionValue(ValueID("after"), region,
                              OperationResult(OperationID("uncertain"), 1), world)
    error_value = ReferenceValue(ValueID("error"), region,
                                 OperationResult(OperationID("make.error"), 0))
    payload = ReferenceValue(ValueID("payload"), region, LiteralOrigin("object"), targets=())
    payload_use = Use(UseID("initial.payload"), payload.id, UseRole.REFERENCE)
    initial = Operation(OperationID("initial"), "initialize", (Behavior.COMPUTE,),
                        (payload_use,), (previous.id,))
    old_def = BindingDefinition(previous.id, BindingState.BOUND, payload_use.id)
    with pytest.raises(ValueError, match="previous binding"):
        BindingDefinition(unknown.id, BindingState.UNKNOWN)
    prior_use = Use(UseID("uncertain.previous"), previous.id, UseRole.LOCAL_BINDING)
    state_use = Use(UseID("uncertain.world"), before.id, UseRole.STATE_CONTENT)
    uncertain = Operation(
        OperationID("uncertain"), "unknown update", (Behavior.READ, Behavior.WRITE),
        (prior_use, state_use), (unknown.id, after.id),
        accesses=(StateAccess(world, state_use.id, AccessMode.READ_WRITE, after.id),),
        effects_complete=False,
    )
    invalid = BindingDefinition(unknown.id, BindingState.UNKNOWN,
                                previous=prior_use.id)
    make_error = Operation(OperationID("make.error"), "typed error producer",
                           (Behavior.COMPUTE,), results=(error_value.id,))
    binding_use = Use(UseID("raise.binding"), unknown.id, UseRole.LOCAL_BINDING)
    error_use = Use(UseID("raise.error"), error_value.id, UseRole.REFERENCE)
    after_use = Use(UseID("raise.world"), after.id, UseRole.STATE_CONTENT)
    raised = Operation(
        OperationID("raise"), "raise unbound", (Behavior.CONTROL,),
        (binding_use, error_use, after_use),
        terminator=Terminator(TerminatorKind.RAISE, exit="raise",
                              values=(error_use.id, after_use.id)),
    )
    block = Block(BlockID("entry"), (before.id,),
                  (initial.id, uncertain.id, make_error.id, raised.id))
    body = Region(region, "unknown binding", block.id, (block,), (
        ExitPort("raise", ExitKind.RAISE,
                 (ValueType(ValueKind.REFERENCE), _type_state())),
    ))
    graph = ProgramGraph(
        region, (body,), (initial, uncertain, make_error, raised),
        (payload, previous, unknown, before, after, error_value),
        (StateLocation(world, "Python world"),),
        binding_definitions=(old_def, invalid),
        binding_reads=(BindingRead(raised.id, binding_use.id, None),),
    )
    issues = validate(graph)
    assert not any(issue.code == "binding_unknown_effect" for issue in issues)
    assert any(issue.code == "binding_read_missing_normal" for issue in issues)


def test_unbound_read_raises_without_exposing_binding_token_as_exit_value():
    region = RegionID("unbound")
    slot = ValueSlotID("missing")
    world = LocationID("world")
    token = LocalBindingValue(ValueID("token"), region,
                              OperationResult(OperationID("unbind"), 0), slot)
    state = StateVersionValue(ValueID("world.entry"), region,
                              BlockArgument(BlockID("entry"), 0), world)
    error_value = ReferenceValue(ValueID("error"), region,
                                 OperationResult(OperationID("make.error"), 0))
    unbind = Operation(OperationID("unbind"), "unbound", (Behavior.COMPUTE,),
                       results=(token.id,))
    make_error = Operation(OperationID("make.error"), "typed error producer",
                           (Behavior.COMPUTE,), results=(error_value.id,))
    binding_use = Use(UseID("raise.binding"), token.id, UseRole.LOCAL_BINDING)
    error_use = Use(UseID("raise.error"), error_value.id, UseRole.REFERENCE)
    state_use = Use(UseID("raise.world"), state.id, UseRole.STATE_CONTENT)
    raised = Operation(
        OperationID("raise"), "raise unbound", (Behavior.CONTROL,),
        (binding_use, error_use, state_use),
        terminator=Terminator(TerminatorKind.RAISE, exit="raise",
                              values=(error_use.id, state_use.id)),
    )
    block = Block(BlockID("entry"), (state.id,),
                  (unbind.id, make_error.id, raised.id))
    body = Region(region, "unbound read", block.id, (block,), (
        ExitPort("raise", ExitKind.RAISE,
                 (ValueType(ValueKind.REFERENCE), _type_state())),
    ))
    graph = ProgramGraph(
        region, (body,), (unbind, make_error, raised),
        (token, state, error_value), (StateLocation(world, "Python world"),),
        binding_definitions=(BindingDefinition(token.id, BindingState.UNBOUND),),
        binding_reads=(BindingRead(raised.id, binding_use.id, None),),
    )
    assert validate(graph) == ()
    document = json.loads(dumps(graph))
    assert document["schema_version"] == 3
    assert document["binding_reads"][0]["normal_result"] is None
    assert loads(json.dumps(document)) == graph

    # A normal reference cannot be attached to an all-unbound token.
    forged = replace(graph, binding_reads=(BindingRead(
        raised.id, binding_use.id, error_value.id),))
    assert any(issue.code in {"control_binding", "binding_read_false_normal",
                              "binding_read_raise"}
               for issue in validate(forged))


def test_unbound_read_can_raise_a_reference_from_normal_invoke_completion():
    region = RegionID("unbound-completion")
    slot = ValueSlotID("missing")
    world = LocationID("world")
    token = LocalBindingValue(ValueID("token"), region,
                              OperationResult(OperationID("unbind"), 0), slot)
    world_entry = StateVersionValue(ValueID("world.entry"), region,
                                    BlockArgument(BlockID("entry"), 0), world)
    error_normal = ReferenceValue(ValueID("error.normal"), region,
                                  BlockArgument(BlockID("normal"), 0))
    world_normal = StateVersionValue(ValueID("world.normal"), region,
                                     BlockArgument(BlockID("normal"), 1), world)
    error_failure = ReferenceValue(ValueID("error.failure"), region,
                                   BlockArgument(BlockID("failure"), 0))
    world_failure = StateVersionValue(ValueID("world.failure"), region,
                                      BlockArgument(BlockID("failure"), 1), world)

    unbind = Operation(OperationID("unbind"), "unbound local",
                       (Behavior.COMPUTE,), results=(token.id,))
    invoke_world = Use(UseID("make-error.world"), world_entry.id, UseRole.STATE_CONTENT)
    completion_signature = (ValueType(ValueKind.REFERENCE), _type_state())
    make_error = Operation(
        OperationID("make-error"), "error construction invoke",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), (invoke_world,),
        effects_complete=False,
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID("normal"),
                                (CompletionResult(0), CompletionResult(1))),
            CompletionSuccessor(ExitKind.RAISE, BlockID("failure"),
                                (CompletionResult(0), CompletionResult(1))),
        )),
        completions=(CompletionSignature(ExitKind.NORMAL, completion_signature),
                     CompletionSignature(ExitKind.RAISE, completion_signature)),
        invoke_arguments=(invoke_world.id,),
    )

    binding_use = Use(UseID("raise.binding"), token.id, UseRole.LOCAL_BINDING)
    normal_error_use = Use(UseID("raise.normal.error"), error_normal.id, UseRole.REFERENCE)
    normal_world_use = Use(UseID("raise.normal.world"), world_normal.id, UseRole.STATE_CONTENT)
    normal_raise = Operation(
        OperationID("raise.normal"), "unbound local raise",
        (Behavior.CONTROL,), (binding_use, normal_error_use, normal_world_use),
        terminator=Terminator(TerminatorKind.RAISE, exit="raise",
                              values=(normal_error_use.id, normal_world_use.id)),
    )
    failure_error_use = Use(UseID("raise.failure.error"), error_failure.id, UseRole.REFERENCE)
    failure_world_use = Use(UseID("raise.failure.world"), world_failure.id, UseRole.STATE_CONTENT)
    failure_raise = Operation(
        OperationID("raise.failure"), "construction failure raise",
        (Behavior.CONTROL,), (failure_error_use, failure_world_use),
        terminator=Terminator(TerminatorKind.RAISE, exit="raise",
                              values=(failure_error_use.id, failure_world_use.id)),
    )
    blocks = (
        Block(BlockID("entry"), (world_entry.id,), (unbind.id, make_error.id)),
        Block(BlockID("normal"), (error_normal.id, world_normal.id), (normal_raise.id,)),
        Block(BlockID("failure"), (error_failure.id, world_failure.id), (failure_raise.id,)),
    )
    body = Region(region, "local error completion", BlockID("entry"), blocks, (
        ExitPort("raise", ExitKind.RAISE, completion_signature),
    ))
    graph = ProgramGraph(
        region, (body,), (unbind, make_error, normal_raise, failure_raise),
        (token, world_entry, error_normal, world_normal, error_failure, world_failure),
        (StateLocation(world, "Python world"),),
        binding_definitions=(BindingDefinition(token.id, BindingState.UNBOUND),),
        binding_reads=(BindingRead(normal_raise.id, binding_use.id, None),),
    )
    assert validate(graph) == ()
    assert derive_binding_facts(graph)[token.id] == frozenset((BindingState.UNBOUND,))


def test_coarse_frame_lifetime_operation_can_consume_a_binding_token():
    region = RegionID("frame-lifetime")
    slot = ValueSlotID("x")
    world = LocationID("world")
    token = LocalBindingValue(ValueID("token"), region,
                              OperationResult(OperationID("unbind"), 0), slot)
    before = StateVersionValue(ValueID("world.before"), region,
                               BlockArgument(BlockID("entry"), 0), world)
    after = StateVersionValue(ValueID("world.after"), region,
                              OperationResult(OperationID("frame.exit"), 0), world)
    result = ReferenceValue(ValueID("result"), region, LiteralOrigin("done"), targets=())
    unbind = Operation(OperationID("unbind"), "initialize unbound local",
                       (Behavior.COMPUTE,), results=(token.id,))
    token_use = Use(UseID("frame.binding"), token.id, UseRole.LOCAL_BINDING)
    state_use = Use(UseID("frame.world"), before.id, UseRole.STATE_CONTENT)
    transition = Operation(
        OperationID("frame.exit"), "opaque lifetime transition",
        (Behavior.READ, Behavior.WRITE, Behavior.MEMORY), (token_use, state_use),
        (after.id,),
        (StateAccess(world, state_use.id, AccessMode.READ_WRITE, after.id),),
        effects_complete=False,
    )
    return_use = Use(UseID("return.result"), result.id, UseRole.REFERENCE)
    world_use = Use(UseID("return.world"), after.id, UseRole.STATE_CONTENT)
    returned = Operation(
        OperationID("return"), "return",
        (Behavior.CONTROL,), (return_use, world_use),
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=(return_use.id, world_use.id)),
    )
    block = Block(BlockID("entry"), (before.id,),
                  (unbind.id, transition.id, returned.id))
    body = Region(region, "frame lifetime", block.id, (block,), (
        ExitPort("normal", ExitKind.NORMAL,
                 (ValueType(ValueKind.REFERENCE), _type_state())),
    ))
    graph = ProgramGraph(
        region, (body,), (unbind, transition, returned),
        (token, before, after, result), (StateLocation(world, "Python world"),),
        binding_definitions=(BindingDefinition(token.id, BindingState.UNBOUND),),
    )
    assert validate(graph) == ()

    # The allowance is only for the constrained incomplete memory transition;
    # it does not make an arbitrary compute operation a binding consumer.
    untyped = replace(transition, behaviors=(Behavior.COMPUTE,))
    forged = replace(graph, operations=tuple(untyped if op.id == untyped.id else op
                                             for op in graph.operations))
    assert any(issue.code == "binding_use_unaccounted" for issue in validate(forged))


def test_v2_wire_is_byte_compatible_and_v1_v2_do_not_accept_binding_fields():
    from pathlib import Path
    from tests.fixtures.program_graphs import loop_state_program

    graph = loop_state_program()
    # Generated by the original isolated dcd4986 implementation, not by today's
    # dataclass fields. New capabilities must never enter a historical envelope.
    legacy = (Path(__file__).parents[1] / "fixtures/program_graph_v2_frozen.json").read_text().rstrip("\n")
    assert dumps(graph) == legacy
    assert json.loads(dumps(graph))["schema_version"] == 2
    assert loads(legacy) == graph

    doc = json.loads(legacy)
    doc["binding_definitions"] = []
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps(doc))
    doc = json.loads(legacy)
    doc["schema_version"] = 1
    for operation in doc["operations"]:
        operation.pop("completions")
        operation.pop("invoke_arguments")
    doc["binding_reads"] = []
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps(doc))


def test_local_binding_tokens_cannot_use_reference_or_call_ports():
    graph = _bound_graph()
    token = next(value for value in graph.values if isinstance(value, LocalBindingValue))
    ret = next(op for op in graph.operations if op.id == OperationID("return"))
    fake_use = Use(UseID("fake.return"), token.id, UseRole.LOCAL_BINDING)
    forged_return = replace(ret, uses=(fake_use,),
                            terminator=replace(ret.terminator, values=(fake_use.id,)))
    forged = replace(graph, operations=tuple(forged_return if op.id == ret.id else op
                                             for op in graph.operations))
    issues = validate(forged)
    assert any(issue.code in {"exit_type", "binding_use_unaccounted"}
               for issue in issues)


def test_v3_cannot_be_used_without_binding_capability():
    from tests.fixtures.program_graphs import loop_state_program

    graph = loop_state_program()
    document = json.loads(dumps(graph))
    document["schema_version"] = 3
    document["binding_definitions"] = []
    document["binding_reads"] = []
    with pytest.raises(ValueError, match="requires local-binding"):
        loads(json.dumps(document))
