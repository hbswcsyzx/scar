"""Derived temporal facts and narrow protocol boundaries, not a driver gate.

Invalid mutations isolate individual fact derivations; they are not claimed to
pass full core/body validation. End-to-end body fixtures are tested separately.
"""
from dataclasses import replace

import pytest

from scar.ir.program.binding_validation import derive_binding_facts, validate_bindings
from scar.ir.program.bindings import BindingDefinition, BindingState
from scar.ir.program.cleanup_forward import derive_cleanup_forward
from scar.ir.program.cleanup_validation import analyze_cleanup
from scar.ir.program.control_validation import control_errors, derive_pending_facts
from scar.ir.program.control import ProtocolValueKind as P
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, BlockArgument, LocalBindingValue, Operation, OperationResult, ProtocolValue, Use, UseRole,
)
from scar.ir.program.provider_validation import provider_errors
from scar.ir.program.providers import (
    ProviderBinding, ProviderElement, ProviderElementKind, ProviderPathIndex,
    ProviderRegion, ProviderRegionRelation,
)
from scar.ir.program.resumption import ResumeInput, SavedInput, SavedRole, SavedSlot
from scar.ir.v2.ids import ValueSlotID
from tests.fixtures.program_provider_graphs import _envelope
from tests.fixtures.program_resumption_graphs import (
    resumption_binding_program, resumption_cleanup_program, resumption_program,
)


def _operation(graph, name):
    return next(op for op in graph.operations if op.id == OperationID(name))


def _change(graph, operation):
    return replace(graph, operations=tuple(operation if op.id == operation.id else op
                                           for op in graph.operations))


def _cleanup_facts(graph):
    interface, = graph.cleanup_interfaces
    scopes = {scope.id: scope for scope in graph.control_scopes}

    def inside(scope):
        while scope is not None:
            if scope == interface.scope:
                return True
            scope = scopes[scope].parent
        return False

    subtree = frozenset(block for scope in scopes.values() if inside(scope.id)
                        for block in scope.blocks)
    operation_blocks = {op: block.id for region in graph.regions
                        for block in region.blocks for op in block.operations}
    # In this fixture the cleanup entry dominates each of these three blocks.
    # Only that true membership is used by the helper's fresh-seed check.
    dominators = {block.id: {block.id, interface.entry} if block.id in subtree else {block.id}
                  for region in graph.regions for block in region.blocks}
    return (derive_cleanup_forward(graph, interface, scope_blocks=subtree,
                                   operation_blocks=operation_blocks, dominators=dominators),
            operation_blocks, dominators)


def test_binding_saved_actuals_keep_same_slot_bound_facts_in_validation_and_query():
    graph = resumption_binding_program()
    facts = derive_binding_facts(graph)
    for name in ("resume.binding", "resume.value.binding", "resume.packet.binding"):
        assert facts[ValueID(name)] == {BindingState.BOUND}
    assert validate_bindings(graph) == ()


def test_binding_saved_role_and_local_slot_are_not_inferred_from_value_type_alone():
    graph = resumption_binding_program()
    op = _operation(graph, "resume.suspend")
    bad_role = _change(graph, replace(op, terminator=replace(op.terminator, saved=tuple(
        replace(slot, role=SavedRole.VALUE) if slot.role is SavedRole.LOCAL_BINDING else slot
        for slot in op.terminator.saved))))
    assert not derive_binding_facts(bad_role).get(ValueID("resume.value.binding"), ())
    assert "binding_edge_slot" in {issue.code for issue in validate_bindings(bad_role)}
    bad_slot = replace(graph, values=tuple(
        replace(value, slot=ValueSlotID("different.local"))
        if value.id == ValueID("resume.value.binding") else value for value in graph.values))
    assert not derive_binding_facts(bad_slot).get(ValueID("resume.value.binding"), ())
    assert "binding_edge_slot" in {issue.code for issue in validate_bindings(bad_slot)}


def test_resume_input_does_not_fabricate_a_binding_history():
    graph = resumption_binding_program()
    op = _operation(graph, "resume.suspend")
    normal, other = op.terminator.successors
    # Swap the delivered-reference and binding argument positions, preserving
    # each ResumeInput's exact-once constructor condition. Core type checks
    # reject this too; the binding derivation must independently gain no seed.
    arguments = tuple(SavedInput(1) if index == 3 else ResumeInput(1) if index == 5 else actual
                      for index, actual in enumerate(normal.arguments))
    graph = _change(graph, replace(op, terminator=replace(op.terminator,
        successors=(replace(normal, arguments=arguments), other))))
    assert not derive_binding_facts(graph).get(ValueID("resume.value.binding"), ())
    assert "binding_resume_result" in {issue.code for issue in validate_bindings(graph)}


def test_unrestored_private_local_binding_is_an_authorized_retained_use():
    graph = resumption_program()
    source = Use(UseID("unused.binding.payload"), ValueID("resume.x"), UseRole.REFERENCE)
    binding = LocalBindingValue(ValueID("unused.binding"), graph.root,
        OperationResult(OperationID("unused.bind"), 0), ValueSlotID("unused.local"))
    bind = Operation(OperationID("unused.bind"), "bind retained local", (Behavior.COMPUTE,),
                     (source,), (binding.id,), effects_complete=True)
    blocks = tuple(replace(block, operations=(*block.operations[:2], bind.id, *block.operations[2:]))
                   if block.id == BlockID("resume.entry") else block
                   for block in graph.regions[0].blocks)
    graph = replace(graph, regions=(replace(graph.regions[0], blocks=blocks),),
        values=(*graph.values, binding), operations=(*graph.operations, bind),
        binding_definitions=(BindingDefinition(binding.id, BindingState.BOUND, source.id),))
    op = _operation(graph, "resume.suspend")
    retained = Use(UseID("unused.binding.saved"), binding.id, UseRole.LOCAL_BINDING)
    graph = _change(graph, replace(op, uses=(*op.uses, retained),
        terminator=replace(op.terminator, saved=(*op.terminator.saved,
            SavedSlot(SavedRole.LOCAL_BINDING, retained.id)))))
    assert derive_binding_facts(graph)[binding.id] == {BindingState.BOUND}
    assert validate_bindings(graph) == ()


def test_saved_same_port_repack_remains_fresh_and_cannot_resume_original_pending():
    graph = resumption_cleanup_program(replace_pending=True)
    normal, _, _ = _cleanup_facts(graph)
    assert ValueID("finally.landing.pending") in normal.pending
    assert ValueID("finally.landing.replacement") in normal.fresh
    op = _operation(graph, "finally.suspend")
    edge, = op.terminator.successors
    graph = _change(graph, replace(op, terminator=replace(op.terminator,
        successors=(replace(edge, arguments=(SavedInput(4), *edge.arguments[1:])),))))
    facts, _, _ = _cleanup_facts(graph)
    pending = derive_pending_facts(graph)
    assert pending[ValueID("finally.landing.pending")].complete
    assert pending[ValueID("finally.landing.pending")].ports == pending[
        ValueID("finally.cleanup.pending")].ports
    assert ValueID("finally.landing.pending") not in facts.pending
    assert ValueID("finally.landing.pending") in facts.fresh


@pytest.mark.parametrize("role,allowed", [(SavedRole.PENDING_COMPLETION, True),
                                         (SavedRole.VALUE, False)])
def test_unrestored_pending_needs_its_specific_private_saved_role(role, allowed):
    graph = resumption_cleanup_program()
    op = _operation(graph, "finally.suspend")
    retained = Use(UseID("extra.pending.retained"), ValueID("finally.cleanup.pending"), UseRole.PROTOCOL)
    graph = _change(graph, replace(op, uses=(*op.uses, retained),
        terminator=replace(op.terminator, saved=(*op.terminator.saved, SavedSlot(role, retained.id)))))
    escaped = {path for code, path, _ in control_errors(graph) if code == "pending_escape"}
    assert (retained.id not in escaped) is allowed


@pytest.mark.parametrize("role,allowed", [(SavedRole.CLEANUP_CONTEXT, True),
                                         (SavedRole.VALUE, False)])
def test_unrestored_cleanup_context_needs_owning_active_scope_and_private_role(role, allowed):
    graph = resumption_cleanup_program()
    op = _operation(graph, "finally.suspend")
    retained = Use(UseID("extra.context.retained"), ValueID("finally.saved-context"), UseRole.PROTOCOL)
    graph = _change(graph, replace(op, uses=(*op.uses, retained),
        terminator=replace(op.terminator, saved=(*op.terminator.saved, SavedSlot(role, retained.id)))))
    _, operation_blocks, dominators = _cleanup_facts(graph)
    issues, _ = analyze_cleanup(graph, operation_blocks=operation_blocks, dominators=dominators)
    escaped = {path for code, path, _ in issues if code == "cleanup_context_escape"}
    assert (retained.id not in escaped) is allowed


def test_c2_context_constructors_are_not_checked_as_c0_saved_context_constructors():
    graph = resumption_program()
    assert control_errors(graph) == []
    graph = replace(graph, control_scopes=())
    issues = control_errors(graph)
    assert [(code, path) for code, path, _ in issues] == [
        ("protocol_scope", ValueID("resume.packet.payload"))]


def test_resume_boundary_provider_ownership_does_not_change_block_argument_producer():
    graph = resumption_program()
    envelope = _envelope("resume-provider")
    owner = ProviderBinding(envelope.id, graph.root,
        ProviderElement(ProviderElementKind.OPERATION, "suspend.node"), OperationID("resume.suspend"))
    payload = ProviderBinding(envelope.id, graph.root,
        ProviderElement(ProviderElementKind.REFERENCE_VALUE, "suspend.node", (ProviderPathIndex(0),)),
        ValueID("resume.value.sent"))
    graph = replace(graph, provider_envelopes=(envelope,), provider_regions=(ProviderRegion(
        envelope.id, "external.body", graph.root, ProviderRegionRelation.DEFINES_REPRESENTATION),),
        provider_bindings=(owner, payload))
    operation_region = {op: region.id for region in graph.regions
                        for block in region.blocks for op in block.operations}
    uses = {use.id: (op.id, use) for op in graph.operations for use in op.uses}
    assert provider_errors(graph, operation_region, uses) == ()
    value = next(value for value in graph.values if value.id == payload.target)
    assert type(value.origin) is BlockArgument
    bad = replace(graph, provider_bindings=(owner, replace(payload, external=replace(
        payload.external, key="other.node"))))
    assert "provider_binding_owner" in {code for code, _, _ in provider_errors(bad, operation_region, uses)}


@pytest.mark.parametrize("attach_alias", [False, True])
def test_one_saved_frame_slot_can_bind_two_formals_and_attach_either(attach_alias):
    from scar.ir.program.queries import ProgramIndex
    from scar.ir.program.validation import validate

    graph = resumption_program()
    op = _operation(graph, "resume.suspend")
    edge, other = op.terminator.successors
    target = next(block for block in graph.regions[0].blocks if block.id == edge.block)
    alias = ProtocolValue(ValueID("resume.value.frame.alias"), graph.root,
                          BlockArgument(target.id, len(target.arguments)), P.FRAME_CONTEXT)
    graph = replace(graph, values=(*graph.values, alias), regions=(replace(
        graph.regions[0], blocks=tuple(replace(block, arguments=(*block.arguments, alias.id))
            if block.id == target.id else block for block in graph.regions[0].blocks)),))
    graph = _change(graph, replace(op, terminator=replace(op.terminator, successors=(
        replace(edge, arguments=(*edge.arguments, SavedInput(0))), other))))
    if attach_alias:
        attach = _operation(graph, "resume.value.attach")
        frame_use = next(row.frame for row in graph.frame_context_attaches if row.operation == attach.id)
        graph = _change(graph, replace(attach, uses=tuple(replace(use, value=alias.id)
            if use.id == frame_use else use for use in attach.uses)))
    assert validate(graph) == ()
    index = ProgramIndex(graph)
    bindings = {binding.formal: binding for binding in index.resumption_bindings(op.id, 0)}
    assert bindings[alias.id].saved == bindings[ValueID("resume.value.frame")].saved
    assert bindings[alias.id].supplied is None
    assert type(index.producer(alias.id)) is BlockArgument
