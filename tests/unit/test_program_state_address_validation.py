from dataclasses import replace

from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Footprint, FootprintKind, ReferenceValue, UseRole,
)
from scar.ir.program.state_addresses import (
    AddressCoverage, AddressEffect, DomainOwner, Element, ExistingAccess,
    InvokeStateOperand, ObjectField, ReferenceOwner, StateAddressRefinement,
    UnknownOwner, WholeOwner,
)
from scar.ir.program.state_address_validation import state_address_errors
from scar.ir.program.validation import require_valid
from tests.fixtures.program_graphs import branch_state_program
from tests.fixtures.program_state_addresses import state_address_program


def _codes(graph):
    return {code for code, _, _ in state_address_errors(graph)}


def _replace_refinement(graph, index, row):
    rows = list(graph.state_address_refinements)
    rows[index] = row
    return replace(graph, state_address_refinements=tuple(rows))


def test_mixed_owner_access_and_real_invoke_ports_form_valid_overlay():
    graph, details = state_address_program()
    require_valid(graph)
    assert state_address_errors(graph) == ()
    root, invoke = graph.state_address_refinements
    assert type(root.site) is ExistingAccess
    assert root.site.operation == details["root_operation"]
    assert [effect.mode for effect in root.effects] == [
        AccessMode.READ, AccessMode.WRITE, AccessMode.READ_WRITE,
    ]
    assert type(invoke.site) is InvokeStateOperand
    assert graph.operations[1].terminator.successors[0].block == details["invoke_normal_block"]
    assert graph.operations[1].terminator.successors[1].block == details["invoke_raise_block"]


def test_foreign_selector_use_and_wrong_access_index_are_rejected():
    graph, _ = state_address_program()
    root = graph.state_address_refinements[0]
    bad_effect = replace(root.effects[0], path=(Element(UseID("not-owned")),))
    bad = replace(root, effects=(bad_effect, *root.effects[1:]))
    assert "address_operand_use" in _codes(_replace_refinement(graph, 0, bad))
    wrong_site = replace(root, site=ExistingAccess(root.site.operation, 9))
    assert "address_access_index" in _codes(_replace_refinement(graph, 0, wrong_site))


def test_effect_modes_cannot_exceed_or_misstate_complete_coarse_access():
    graph, _ = state_address_program()
    root = graph.state_address_refinements[0]
    read_as_write = replace(root.effects[0], mode=AccessMode.READ_WRITE)
    bad_mode = replace(root, effects=(read_as_write, *root.effects[1:]))
    root_operation = graph.operations[0]
    access = replace(root_operation.accesses[0], mode=AccessMode.READ, after=None)
    operations = (replace(root_operation, accesses=(access,)), *graph.operations[1:])
    read_summary = replace(graph, operations=operations)
    assert "address_mode_exceeds_summary" in _codes(_replace_refinement(read_summary, 0, bad_mode))
    only_reads = replace(root, effects=tuple(
        replace(effect, mode=AccessMode.READ) for effect in root.effects
    ), coverage=AddressCoverage.DECLARED_COMPLETE)
    assert "address_mode_incomplete" in _codes(_replace_refinement(graph, 0, only_reads))


def test_existing_reference_envelope_cannot_be_bypassed_by_other_owners():
    graph, _ = state_address_program()
    root = graph.state_address_refinements[0]
    operation = graph.operations[0]
    source_use = operation.uses[0]
    accesses = list(operation.accesses)
    accesses[0] = replace(accesses[0], reference=source_use.id)
    operations = (replace(operation, accesses=tuple(accesses)), *graph.operations[1:])
    envelope_graph = replace(graph, operations=operations)
    assert "address_reference_envelope" in _codes(envelope_graph)
    assert "address_reference_envelope" in _codes(_replace_refinement(
        envelope_graph, 0, root))


def test_local_selector_cannot_refine_an_existing_full_overwrite():
    graph = branch_state_program()
    operations = {operation.id: operation for operation in graph.operations}
    write = operations[OperationID("write")]
    uses = tuple(replace(use, role=UseRole.STATE_ORDER)
                 if use.id == UseID("write.state") else use for use in write.uses)
    full = replace(write.accesses[0], footprint=Footprint(FootprintKind.WHOLE),
                   full_overwrite=True)
    reference_use = next(use for use in uses if use.id == UseID("write.reference"))
    values = tuple(replace(value, selector=Footprint(FootprintKind.WHOLE))
                   if isinstance(value, ReferenceValue) and value.id == reference_use.value
                   else value for value in graph.values)
    operations[write.id] = replace(write, uses=uses, accesses=(full,))
    base = replace(graph, operations=tuple(operations[row.id] for row in graph.operations),
                   values=values)
    row = StateAddressRefinement(
        ExistingAccess(write.id, 0),
        (AddressEffect(ReferenceOwner(reference_use.id), (ObjectField("field"),),
                       AccessMode.WRITE),),
        AddressCoverage.DECLARED_COMPLETE,
    )
    assert "address_full_overwrite" in _codes(replace(base, state_address_refinements=(row,)))


def test_invoke_selector_must_use_actual_invoke_argument_not_edge_forwarding():
    graph, details = state_address_program()
    invoke_id = details["invoke_operation"]
    operations = {operation.id: operation for operation in graph.operations}
    invoke = operations[invoke_id]
    operations[invoke_id] = replace(
        invoke, invoke_arguments=tuple(use for use in invoke.invoke_arguments
                                      if use != details["dynamic_key_use"]),
    )
    bad_graph = replace(graph, operations=tuple(operations[row.id] for row in graph.operations))
    assert "address_invoke_argument" in _codes(bad_graph)


def test_invoke_address_refinement_cannot_change_core_state_content_role():
    graph, details = state_address_program()
    invoke_id = details["invoke_operation"]
    operations = {operation.id: operation for operation in graph.operations}
    invoke = operations[invoke_id]
    operations[invoke_id] = replace(
        invoke,
        uses=tuple(replace(use, role=UseRole.STATE_ORDER)
                   if use.id == details["invoke_state_use"] else use for use in invoke.uses),
    )
    bad_graph = replace(graph, operations=tuple(operations[row.id] for row in graph.operations))
    assert "address_invoke_role" in _codes(bad_graph)


def test_distinct_invoke_state_uses_cannot_refine_the_same_carrier_twice():
    graph, details = state_address_program()
    invoke_id = details["invoke_operation"]
    operations = {operation.id: operation for operation in graph.operations}
    invoke = operations[invoke_id]
    duplicate_state = replace(invoke.uses[0], id=UseID("address.invoke.world.alias"))
    invoke = replace(invoke, uses=(*invoke.uses, duplicate_state),
                     invoke_arguments=(*invoke.invoke_arguments, duplicate_state.id))
    operations[invoke_id] = invoke
    first = graph.state_address_refinements[1]
    second = replace(first, site=InvokeStateOperand(invoke_id, duplicate_state.id))
    bad_graph = replace(
        graph,
        operations=tuple(operations[row.id] for row in graph.operations),
        state_address_refinements=(*graph.state_address_refinements, second),
    )
    assert "address_duplicate_carrier" in _codes(bad_graph)


def test_unknown_and_domain_owner_cannot_override_an_explicit_reference():
    graph, _ = state_address_program()
    root = graph.state_address_refinements[0]
    operation = graph.operations[0]
    accesses = (replace(operation.accesses[0], reference=operation.uses[0].id),)
    operations = (replace(operation, accesses=accesses), *graph.operations[1:])
    graph = replace(graph, operations=operations)
    unknown_effect = AddressEffect(
        UnknownOwner("unknown", (operation.uses[2].id,)),
        (WholeOwner(),), AccessMode.WRITE,
    )
    row = replace(root, effects=(unknown_effect,), coverage=AddressCoverage.PARTIAL)
    assert "address_reference_envelope" in _codes(_replace_refinement(graph, 0, row))
    domain_effect = AddressEffect(DomainOwner(), (WholeOwner(),), AccessMode.WRITE)
    domain = replace(root, effects=(domain_effect,), coverage=AddressCoverage.PARTIAL)
    assert "address_reference_envelope" in _codes(_replace_refinement(graph, 0, domain))

