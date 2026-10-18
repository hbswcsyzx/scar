"""Static address views retain original ports, unknowns and coarse state SSA."""
from dataclasses import replace

import pytest

from scar.ir.program.ids import OperationID, UseID
from scar.ir.program.model import (
    CompletionResult, DataValue, ReferenceValue, StateVersionValue, Use, UseRole,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.state_addresses import (
    AddressCoverage, Element, ExistingAccess, InvokeStateOperand, NamespaceKey,
    ReferenceOwner, ResourceOwner, Slice, UnknownOwner, UnknownSelection,
    address_effect_uses,
)
from tests.fixtures.program_state_addresses import state_address_program


VIEW_KEYS = {"site", "refinement", "operation", "carrier", "access", "before", "after",
             "completions", "effects", "coarse_dependencies_retained",
             "address_interpretation_verified", "conditions",
             "source_runtime_verified", "transformation_authorized"}


def test_all_declared_sites_keep_original_records_and_owned_use_sites():
    graph, _ = state_address_program()
    index = ProgramIndex(graph)
    locations = {location.id: location for location in graph.locations}
    resource_uses = {(row.operation, row.requirement): row for row in graph.resource_uses}
    for row in graph.state_address_refinements:
        view = index.state_address(row.site)
        assert set(view) == VIEW_KEYS
        assert view["site"] is row.site and view["refinement"] is row
        operation = index.operations[row.site.operation]
        assert view["operation"] is operation
        assert view["coarse_dependencies_retained"] is True
        assert view["address_interpretation_verified"] is False
        assert type(view["conditions"]) is tuple
        assert any("Footprint" in condition for condition in view["conditions"])
        assert any("DECLARED_COMPLETE" in condition for condition in view["conditions"])
        assert view["source_runtime_verified"] is view["transformation_authorized"] is False
        if type(row.site) is ExistingAccess:
            access = operation.accesses[row.site.index]
            assert view["access"] is access
            assert view["carrier"] is locations[access.location]
            assert view["before"] is index.use_site(access.before)
            assert view["after"] is (None if access.after is None else index.values[access.after])
            assert view["completions"] == ()
        else:
            assert view["access"] is view["after"] is None
            assert view["before"] is index.use_site(row.site.state_use)
            assert view["carrier"] is locations[index.values[view["before"].use.value].location]
        assert len(view["effects"]) == len(row.effects)
        for number, effect_view in enumerate(view["effects"]):
            effect = row.effects[number]
            assert set(effect_view) == {"index", "effect", "owner_use", "resource_use", "operands"}
            assert effect_view["index"] == number and effect_view["effect"] is effect
            expected_owner = index.use_site(effect.owner.use) if type(effect.owner) is ReferenceOwner else None
            assert effect_view["owner_use"] is expected_owner
            expected_resource = (resource_uses[operation.id, effect.owner.requirement]
                                 if type(effect.owner) is ResourceOwner else None)
            assert effect_view["resource_use"] is expected_resource
            prefix = effect.owner.operands if type(effect.owner) is UnknownOwner else ()
            expected = (*prefix, *address_effect_uses(effect))
            assert len(effect_view["operands"]) == len(expected)
            assert all(actual is index.use_site(use)
                       for actual, use in zip(effect_view["operands"], expected))


def test_remove_refinements_retains_coarse_sites_and_original_state_dependencies():
    graph, _ = state_address_program()
    sites = tuple(row.site for row in graph.state_address_refinements)
    graph = replace(graph, state_address_refinements=())
    index = ProgramIndex(graph)
    for site in sites:
        view = index.state_address(site)
        assert view["refinement"] is None and view["effects"] == ()
        assert view["operation"] is index.operations[site.operation]
        assert view["before"] is index.use_site(view["before"].use.id)
        assert type(index.values[view["before"].use.value]) is StateVersionValue
        assert view["coarse_dependencies_retained"] is True
        assert view["address_interpretation_verified"] is False
        assert any("unknown" in condition for condition in view["conditions"])
        assert view["source_runtime_verified"] is view["transformation_authorized"] is False


def test_invoke_views_return_each_original_completion_even_when_edges_are_reversed():
    graph, _ = state_address_program()
    row = next(row for row in graph.state_address_refinements if type(row.site) is InvokeStateOperand)
    operation = next(op for op in graph.operations if op.id == row.site.operation)
    operation = replace(operation, terminator=replace(operation.terminator,
        successors=tuple(reversed(operation.terminator.successors))))
    graph = replace(graph, operations=tuple(operation if old.id == operation.id else old
                                            for old in graph.operations))
    index = ProgramIndex(graph)
    view = index.state_address(row.site)
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    assert view["after"] is None and view["access"] is None
    assert len(view["completions"]) == len(operation.terminator.successors) == 2
    for edge_view in view["completions"]:
        assert set(edge_view) == {"successor_index", "successor", "formal", "argument"}
        successor = operation.terminator.successors[edge_view["successor_index"]]
        assert edge_view["successor"] is successor
        position = blocks[successor.block].arguments.index(edge_view["formal"].id)
        assert edge_view["formal"] is index.values[blocks[successor.block].arguments[position]]
        assert edge_view["argument"] is successor.arguments[position]
        assert type(edge_view["argument"]) is CompletionResult
        assert edge_view["formal"].location == view["carrier"].id


def test_invoke_forwarded_state_stays_a_real_edge_use_without_fake_after():
    graph, _ = state_address_program()
    row = next(row for row in graph.state_address_refinements if type(row.site) is InvokeStateOperand)
    index = ProgramIndex(graph)
    view = index.state_address(row.site)
    chosen = view["completions"][0]
    operation = view["operation"]
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    position = blocks[chosen["successor"].block].arguments.index(chosen["formal"].id)
    forwarded = Use(UseID("state-address.test.forward"), view["before"].use.value, UseRole.STATE_CONTENT)
    removed_slot = chosen["argument"].index
    arguments = list(chosen["successor"].arguments)
    arguments[position] = forwarded.id
    arguments = [replace(actual, index=actual.index - 1)
                 if type(actual) is CompletionResult and actual.index > removed_slot else actual
                 for actual in arguments]
    successor = replace(chosen["successor"], arguments=tuple(arguments))
    successors = tuple(successor if number == chosen["successor_index"] else edge
                       for number, edge in enumerate(operation.terminator.successors))
    operation = replace(operation, effects_complete=True, uses=(*operation.uses, forwarded),
                        completions=tuple(replace(signature,
                            types=tuple(value_type for number, value_type in enumerate(signature.types)
                                        if number != removed_slot))
                            if signature.kind is successor.kind else signature
                            for signature in operation.completions),
                        terminator=replace(operation.terminator, successors=successors))
    graph = replace(graph, operations=tuple(operation if old.id == operation.id else old
                                            for old in graph.operations))
    index = ProgramIndex(graph)
    result = index.state_address(row.site)
    actual = result["completions"][chosen["successor_index"]]
    assert actual["argument"] is forwarded.id
    assert index.use_site(actual["argument"]).use is forwarded
    assert result["after"] is None


def test_path_order_preserves_repeated_uses_and_same_value_independent_ports():
    graph, _ = state_address_program()
    operations = {op.id: op for op in graph.operations}
    values = {value.id: value for value in graph.values}
    row = next(row for row in graph.state_address_refinements if type(row.site) is ExistingAccess
               and operations[row.site.operation].accesses[row.site.index].reference is None)
    operation = operations[row.site.operation]
    # Two actual ports may alias the same object/value; they remain two Uses.
    candidates = tuple(use for use in operation.uses
                       if type(values[use.value]) in (DataValue, ReferenceValue))
    first, second = candidates[:2]
    assert first.id != second.id
    second = replace(second, value=first.value, role=first.role)
    operation = replace(operation, uses=tuple(second if use.id == second.id else use
                                               for use in operation.uses))
    path = (Element(first.id), Slice(first.id, None, second.id), NamespaceKey(second.id),
            UnknownSelection("unresolved selector", (first.id, second.id, first.id)))
    effect = replace(row.effects[0], path=path)
    row = replace(row, effects=(effect,), coverage=AddressCoverage.PARTIAL)
    graph = replace(graph, operations=tuple(operation if old.id == operation.id else old
                                            for old in graph.operations),
                    state_address_refinements=(row,))
    index = ProgramIndex(graph)
    expected = (first.id, first.id, second.id, second.id, first.id, second.id, first.id)
    actual = index.state_address(row.site)["effects"][0]["operands"]
    assert tuple(item.use.id for item in actual) == expected
    assert all(item is index.use_site(identity) for item, identity in zip(actual, expected))
    assert index.use_site(first.id).use.value == index.use_site(second.id).use.value
    assert index.use_site(first.id) is not index.use_site(second.id)


def test_unknown_owner_dependencies_are_preserved_before_selector_operands():
    graph, _ = state_address_program()
    operations = {op.id: op for op in graph.operations}
    values = {value.id: value for value in graph.values}
    row = next(row for row in graph.state_address_refinements if type(row.site) is ExistingAccess
               and operations[row.site.operation].accesses[row.site.index].reference is None)
    operation = operations[row.site.operation]
    operand = next(use.id for use in operation.uses if type(values[use.value]) in (DataValue, ReferenceValue))
    effect = replace(row.effects[0], owner=UnknownOwner("unresolved owner", (operand, operand)),
                     path=(Element(operand),))
    row = replace(row, effects=(effect,), coverage=AddressCoverage.PARTIAL)
    graph = replace(graph, state_address_refinements=(row,))
    index = ProgramIndex(graph)
    view = index.state_address(row.site)["effects"][0]
    assert view["owner_use"] is None
    assert view["operands"] == (index.use_site(operand),) * 3
    assert all(item is index.use_site(operand) for item in view["operands"])


def test_query_rejects_wrong_sites_and_does_not_accept_caller_proof_facts():
    graph, _ = state_address_program()
    index = ProgramIndex(graph)
    row = graph.state_address_refinements[0]
    with pytest.raises(TypeError):
        index.state_address(row.site.operation)
    with pytest.raises(KeyError):
        index.state_address(ExistingAccess(OperationID("state-address.missing"), 0))
    with pytest.raises(KeyError):
        index.state_address(ExistingAccess(row.site.operation, 10**6))
    with pytest.raises(ValueError):
        index.state_address(InvokeStateOperand(row.site.operation, UseID("state-address.not-an-operand")))
    with pytest.raises(TypeError):
        index.state_address(row.site, facts={"verified": True})
    bad = ExistingAccess(row.site.operation, 0)
    object.__setattr__(bad, "index", True)
    with pytest.raises((ValueError, TypeError)):
        index.state_address(bad)


def test_returned_dictionary_mutation_does_not_modify_canonical_records_or_next_view():
    graph, _ = state_address_program()
    index = ProgramIndex(graph)
    row = graph.state_address_refinements[0]
    first = index.state_address(row.site)
    first["effects"][0]["operands"] = ()
    first["refinement"] = None
    first["source_runtime_verified"] = True
    second = index.state_address(row.site)
    assert second["refinement"] is row
    assert second["effects"][0]["effect"] is row.effects[0]
    assert second["source_runtime_verified"] is False
    assert row in graph.state_address_refinements
