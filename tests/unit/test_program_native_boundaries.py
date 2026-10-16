"""Native port declarations stay thin and leave canonical calls/Uses intact."""
from dataclasses import replace

import pytest

from scar.ir.program.codec import dumps
from scar.ir.program.ids import (
    NativeBoundaryID, OperationID, RegionID, UseID, ValueID,
)
from scar.ir.program.model import ValueKind, value_type
from scar.ir.program.native import (
    BoundaryDomain, BoundaryPortPair, CoreOutputPort, EntryPortRef, ExitPortRef,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import validate
from tests.fixtures.program_graphs import shared_body_calls_program
from tests.fixtures.program_native_graphs import native_boundary_graph


def _boundary(graph, boundary_id=NativeBoundaryID("native.rep.boundary")):
    return next(item for item in graph.native_boundaries if item.id == boundary_id)


def _replace_boundary(graph, changed):
    return replace(graph, native_boundaries=tuple(
        changed if item.id == changed.id else item for item in graph.native_boundaries))


def _rejects(graph, prefix):
    issues = validate(graph)
    assert any(issue.code.startswith(prefix) for issue in issues), issues
    with pytest.raises(ValueError):
        dumps(graph)


def test_native_boundaries_partition_existing_ports_without_rewriting_core_calls():
    graph = native_boundary_graph()
    assert validate(graph) == ()

    before = {op.id: op for op in shared_body_calls_program().operations
              if op.id in (OperationID("call1"), OperationID("call2"))}
    after = {op.id: op for op in graph.operations if op.id in before}
    assert after == before
    assert tuple(op.callee for op in (after[OperationID("call1")], after[OperationID("call2")])) == (
        RegionID("callee"), RegionID("callee"),
    )

    index = ProgramIndex(graph)
    native = _boundary(graph)
    assert native.region == RegionID("native.rep")
    assert index.native_boundary(native.id) == native
    assert index.native_boundary_for_region(RegionID("native.rep")) == native

    # Native order is flag/reference; core entry order is reference/state/flag.
    native_inputs = index.native_input_values(native.id)
    assert tuple(value.id for value in native_inputs) == (ValueID("native.flag"), ValueID("native.ref"))
    assert tuple(value_type(value).kind for value in native_inputs) == (ValueKind.DATA, ValueKind.REFERENCE)
    assert tuple(item.port for item in native.core_inputs) == (
        EntryPortRef(RegionID("native.rep"), ValueID("native.world")),
    )

    # The repeated output slots retain distinct Use IDs at each Return, even
    # though each pair reads one underlying Value. Both Return sites survive.
    slot0, slot1, raise_slot = index.native_output_uses(native.id)
    assert tuple(site.operation for site in slot0) == (
        OperationID("native.return.a.op"), OperationID("native.return.b.op"),
    )
    assert tuple(site.operation for site in slot1) == tuple(site.operation for site in slot0)
    for first, second in zip(slot0, slot1):
        assert first.use.value == second.use.value
        assert first.use.id != second.use.id
    assert len(raise_slot) == 1
    assert raise_slot[0].operation == OperationID("native.raise.op")
    assert raise_slot[0].use.id == UseID("native.raise.error.use")

    # ExitPortRef deliberately has no kind bit: its existing logical exit
    # name resolves either NORMAL or RAISE according to the core Region.
    assert not hasattr(native.outputs[2].port, "kind")
    assert native.outputs[2].port == ExitPortRef(RegionID("native.rep"), "failure", 0)

    relation = graph.boundary_relations[0]
    assert index.boundary_relation(relation.id) == relation
    assert index.boundary_relations(native.id) == (relation,)
    assert len(relation.obligations) == 8
    assert {item.domain for item in relation.obligations} == set(BoundaryDomain)
    assert relation.conditions == ()
    assert not hasattr(relation, "verified")

    left_unpaired, right_unpaired = index.boundary_unpaired_ports(relation.id)
    assert left_unpaired == (
        EntryPortRef(RegionID("native.rep"), ValueID("native.flag")),
        ExitPortRef(RegionID("native.rep"), "normal", 1),
        ExitPortRef(RegionID("native.rep"), "failure", 1),
    )
    assert right_unpaired == ()


def test_entry_query_resolves_only_the_named_existing_entry_port():
    index = ProgramIndex(native_boundary_graph())
    assert index.entry_port(EntryPortRef(RegionID("native.rep"), ValueID("native.flag"))).id == ValueID("native.flag")
    with pytest.raises(KeyError):
        index.entry_port(EntryPortRef(RegionID("native.rep"), ValueID("native.missing")))


def test_a_boundary_must_cover_each_entry_and_exit_exactly_once():
    graph = native_boundary_graph()
    boundary = _boundary(graph)

    # Duplicate one native input while preserving local slot positions.
    duplicate = replace(boundary.inputs[1], port=boundary.inputs[0].port)
    _rejects(_replace_boundary(graph, replace(boundary, inputs=(boundary.inputs[0], duplicate))),
             "native_port")

    # Omit one native output and its core-only set: a well-typed record still
    # cannot silently leave a canonical exit position outside the partition.
    _rejects(_replace_boundary(graph, replace(boundary, outputs=(boundary.outputs[0],),
                                               core_outputs=())), "native_port_partition")


def test_port_region_owner_and_boundary_relation_endpoints_are_exact():
    graph = native_boundary_graph()
    boundary = _boundary(graph)

    wrong_region_slot = replace(
        boundary.inputs[0],
        port=EntryPortRef(RegionID("callee"), ValueID("native.flag")),
    )
    _rejects(_replace_boundary(graph, replace(boundary,
                                               inputs=(wrong_region_slot, boundary.inputs[1]))),
             "native_port_region")

    wrong_owner = replace(boundary, provider=graph.provider_envelopes[0].id)
    _rejects(_replace_boundary(graph, wrong_owner), "native_owner")

    bad_relation = graph.boundary_relations[0]
    bad_pair = replace(
        bad_relation.ports[0],
        left=EntryPortRef(RegionID("caller"), ValueID("caller.input")),
    )
    invalid = replace(graph, boundary_relations=(replace(
        bad_relation, ports=(bad_pair, *bad_relation.ports[1:])),))
    _rejects(invalid, "boundary_port")


def test_relation_needs_two_existing_boundaries_in_distinct_regions():
    graph = native_boundary_graph()
    relation = graph.boundary_relations[0]
    missing = replace(graph, boundary_relations=(replace(
        relation, right=NativeBoundaryID("missing.boundary")),))
    _rejects(missing, "boundary_reference")

    same_region_boundary = replace(graph.native_boundaries[0], region=RegionID("native.rep"))
    same_region = _replace_boundary(graph, same_region_boundary)
    assert any(issue.code == "boundary_region" for issue in validate(same_region))


@pytest.mark.parametrize("port", [
    ExitPortRef(RegionID("native.rep"), "absent", 0),
    ExitPortRef(RegionID("native.rep"), "normal", 3),
    ExitPortRef(RegionID("callee"), "normal", 0),
])
def test_native_output_cannot_point_to_missing_or_foreign_logical_slot(port):
    graph = native_boundary_graph()
    boundary = _boundary(graph)
    bad = replace(boundary.outputs[0], port=port)
    _rejects(_replace_boundary(graph, replace(boundary, outputs=(bad, *boundary.outputs[1:]))),
             "native_port")


def test_core_only_ports_cannot_duplicate_native_ports_or_hide_an_input():
    graph = native_boundary_graph()
    boundary = _boundary(graph)
    extra = CoreOutputPort(boundary.outputs[0].port, "duplicate across the partition")
    _rejects(_replace_boundary(graph, replace(boundary, core_outputs=(*boundary.core_outputs, extra))),
             "native_port_duplicate")
    _rejects(_replace_boundary(graph, replace(boundary, core_inputs=())), "native_port_partition")


def test_partial_many_to_many_pairs_and_record_reordering_preserve_canonical_occurrences():
    graph = native_boundary_graph()
    relation = graph.boundary_relations[0]
    first = relation.ports[2]  # A reference output paired with a data output.
    extra = BoundaryPortPair(first.left, relation.ports[3].right, first.evidence)
    relation = replace(relation, ports=(*relation.ports, extra))
    graph = replace(graph, boundary_relations=(relation,))
    assert validate(graph) == ()  # Declaration, never a same-type/equivalence inference.
    before = ProgramIndex(graph)
    reordered = replace(graph, regions=tuple(reversed(graph.regions)),
                        operations=tuple(reversed(graph.operations)),
                        native_boundaries=tuple(reversed(graph.native_boundaries)))
    after = ProgramIndex(reordered)
    identity = NativeBoundaryID("native.rep.boundary")
    assert after.native_input_values(identity) == before.native_input_values(identity)
    assert after.native_output_uses(identity) == before.native_output_uses(identity)
    assert after.boundary_unpaired_ports(relation.id) == before.boundary_unpaired_ports(relation.id)
    assert after.boundary_relation(relation.id).ports == relation.ports

