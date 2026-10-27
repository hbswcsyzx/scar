"""Manual canonical graphs with thin native-interface declarations.

These fixtures do not load or interpret the referenced provider artifacts.
They exercise only typed core ports, declared native slot mappings, and
explicitly unproved cross-representation obligations.
"""
from dataclasses import replace

from scar.ir.program.ids import (
    BoundaryRelationID, BlockID, LocationID, NativeBoundaryID, OperationID,
    RegionID, UseID, ValueID,
)
from scar.ir.program.model import (
    Behavior, BlockArgument, DataValue, ExitKind, ExitPort, Operation,
    ReferenceValue, Region, StateVersionValue, Successor, Terminator,
    TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.native import (
    BoundaryDomain, BoundaryObligation, BoundaryPortPair, BoundaryRelation,
    CoreInputPort, CoreOutputPort, EntryPortRef, ExitPortRef, NativeBoundary,
    NativeInputSlot, NativeOutputSlot,
)
from scar.ir.program.providers import ProviderRegion, ProviderRegionRelation

from tests.fixtures.program_graphs import (
    block as core_block,
    state_type,
)
from tests.fixtures.program_provider_graphs import _envelope, _fact, definition_provider_graph


def _use(name, value, role=UseRole.DATA):
    return Use(UseID(name), ValueID(value), role)


def _native_region():
    """Sibling Region: physical entry order differs from native flat order.

    It returns one reference twice. Both logical exit positions and both
    normal-return sites have distinct Uses even though they name one Value.
    """
    region_id = RegionID("native.rep")
    values = (
        ReferenceValue(ValueID("native.ref"), region_id,
                       BlockArgument(BlockID("native.entry"), 0)),
        StateVersionValue(ValueID("native.world"), region_id,
                          BlockArgument(BlockID("native.entry"), 1), LocationID("calls")),
        DataValue(ValueID("native.flag"), region_id,
                  BlockArgument(BlockID("native.entry"), 2), "builtins.bool"),
        ReferenceValue(ValueID("native.more.ref"), region_id,
                       BlockArgument(BlockID("native.choose.more"), 0)),
        StateVersionValue(ValueID("native.more.world"), region_id,
                          BlockArgument(BlockID("native.choose.more"), 1), LocationID("calls")),
        DataValue(ValueID("native.more.flag"), region_id,
                  BlockArgument(BlockID("native.choose.more"), 2), "builtins.bool"),
        ReferenceValue(ValueID("native.a.ref"), region_id,
                       BlockArgument(BlockID("native.return.a"), 0)),
        StateVersionValue(ValueID("native.a.world"), region_id,
                          BlockArgument(BlockID("native.return.a"), 1), LocationID("calls")),
        ReferenceValue(ValueID("native.b.ref"), region_id,
                       BlockArgument(BlockID("native.return.b"), 0)),
        StateVersionValue(ValueID("native.b.world"), region_id,
                          BlockArgument(BlockID("native.return.b"), 1), LocationID("calls")),
        ReferenceValue(ValueID("native.raise.error"), region_id,
                       BlockArgument(BlockID("native.raise"), 0)),
        StateVersionValue(ValueID("native.raise.world"), region_id,
                          BlockArgument(BlockID("native.raise"), 1), LocationID("calls")),
    )
    choose = Operation(
        OperationID("native.choose"), "select one ordinary exit",
        (Behavior.CONTROL,),
        (
            _use("native.choose.condition", "native.flag"),
            _use("native.choose.a.ref", "native.ref", UseRole.REFERENCE),
            _use("native.choose.a.world", "native.world", UseRole.STATE_CONTENT),
            _use("native.choose.more.ref", "native.ref", UseRole.REFERENCE),
            _use("native.choose.more.world", "native.world", UseRole.STATE_CONTENT),
            _use("native.choose.more.flag", "native.flag"),
        ),
        terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(BlockID("native.return.a"),
                      (UseID("native.choose.a.ref"), UseID("native.choose.a.world"))),
            Successor(BlockID("native.choose.more"), (
                UseID("native.choose.more.ref"),
                UseID("native.choose.more.world"),
                UseID("native.choose.more.flag"),
            )),
        ), condition=UseID("native.choose.condition")),
    )
    choose_more = Operation(
        OperationID("native.choose.more.op"), "select normal or raise",
        (Behavior.CONTROL,),
        (
            _use("native.choose.more.condition", "native.more.flag"),
            _use("native.choose.more.normal.ref", "native.more.ref", UseRole.REFERENCE),
            _use("native.choose.more.normal.world", "native.more.world", UseRole.STATE_CONTENT),
            _use("native.choose.more.raise.error", "native.more.ref", UseRole.REFERENCE),
            _use("native.choose.more.raise.world", "native.more.world", UseRole.STATE_CONTENT),
        ),
        terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(BlockID("native.return.b"), (
                UseID("native.choose.more.normal.ref"),
                UseID("native.choose.more.normal.world"),
            )),
            Successor(BlockID("native.raise"), (
                UseID("native.choose.more.raise.error"),
                UseID("native.choose.more.raise.world"),
            )),
        ), condition=UseID("native.choose.more.condition")),
    )
    return_a = Operation(
        OperationID("native.return.a.op"), "return duplicate references A",
        (Behavior.CONTROL,),
        (
            _use("native.return.a.out0", "native.a.ref", UseRole.REFERENCE),
            _use("native.return.a.out1", "native.a.ref", UseRole.REFERENCE),
            _use("native.return.a.world", "native.a.world", UseRole.STATE_CONTENT),
        ),
        terminator=Terminator(TerminatorKind.RETURN, exit="normal", values=(
            UseID("native.return.a.out0"), UseID("native.return.a.out1"),
            UseID("native.return.a.world"),
        )),
    )
    return_b = Operation(
        OperationID("native.return.b.op"), "return duplicate references B",
        (Behavior.CONTROL,),
        (
            _use("native.return.b.out0", "native.b.ref", UseRole.REFERENCE),
            _use("native.return.b.out1", "native.b.ref", UseRole.REFERENCE),
            _use("native.return.b.world", "native.b.world", UseRole.STATE_CONTENT),
        ),
        terminator=Terminator(TerminatorKind.RETURN, exit="normal", values=(
            UseID("native.return.b.out0"), UseID("native.return.b.out1"),
            UseID("native.return.b.world"),
        )),
    )
    raise_op = Operation(
        OperationID("native.raise.op"), "raise one reference with current state",
        (Behavior.CONTROL,),
        (
            _use("native.raise.error.use", "native.raise.error", UseRole.REFERENCE),
            _use("native.raise.world.use", "native.raise.world", UseRole.STATE_CONTENT),
        ),
        terminator=Terminator(TerminatorKind.RAISE, exit="failure", values=(
            UseID("native.raise.error.use"), UseID("native.raise.world.use"),
        )),
    )
    reference = ValueType(ValueKind.REFERENCE)
    region = Region(
        region_id, "sibling native representation", BlockID("native.entry"),
        (
            core_block("native.entry", ("native.ref", "native.world", "native.flag"),
                       ("native.choose",)),
            core_block("native.choose.more", ("native.more.ref", "native.more.world", "native.more.flag"),
                       ("native.choose.more.op",)),
            core_block("native.return.a", ("native.a.ref", "native.a.world"),
                       ("native.return.a.op",)),
            core_block("native.return.b", ("native.b.ref", "native.b.world"),
                       ("native.return.b.op",)),
            core_block("native.raise", ("native.raise.error", "native.raise.world"),
                       ("native.raise.op",)),
        ),
        (
            ExitPort("normal", ExitKind.NORMAL,
                     (reference, reference, state_type("calls"))),
            ExitPort("failure", ExitKind.RAISE,
                     (reference, state_type("calls"))),
        ),
        parent=RegionID("caller"),
    )
    return region, (choose, choose_more, return_a, return_b, raise_op), values


def native_boundary_graph():
    """Add two independently owned representations without changing calls.

    Native input order is flag/reference while canonical entry order is
    reference/state/flag. The state is explicitly core-only. Output positions
    0 and 1 name the same reference Value; output state is core-only. The
    relation pairs unlike ValueKinds intentionally: its obligations remain
    open, and it does not rewrite either Region or the existing calls.
    """
    graph = definition_provider_graph()
    native_region, native_operations, native_values = _native_region()
    definition = graph.provider_envelopes[0]
    native_provider = _envelope("native-representation-provider")
    native_owner = ProviderRegion(
        native_provider.id, "external.native.rep", RegionID("native.rep"),
        ProviderRegionRelation.DEFINES_REPRESENTATION,
    )

    callee_boundary_id = NativeBoundaryID("callee.boundary")
    native_boundary_id = NativeBoundaryID("native.rep.boundary")
    callee_entry_ref = EntryPortRef(RegionID("callee"), ValueID("body.input"))
    callee_entry_state = EntryPortRef(RegionID("callee"), ValueID("body.initial"))
    callee_exit_value = ExitPortRef(RegionID("callee"), "normal", 0)
    callee_exit_state = ExitPortRef(RegionID("callee"), "normal", 1)
    native_entry_ref = EntryPortRef(RegionID("native.rep"), ValueID("native.ref"))
    native_entry_state = EntryPortRef(RegionID("native.rep"), ValueID("native.world"))
    native_entry_flag = EntryPortRef(RegionID("native.rep"), ValueID("native.flag"))
    native_exit_first = ExitPortRef(RegionID("native.rep"), "normal", 0)
    native_exit_second = ExitPortRef(RegionID("native.rep"), "normal", 1)
    native_exit_state = ExitPortRef(RegionID("native.rep"), "normal", 2)
    native_raise_error = ExitPortRef(RegionID("native.rep"), "failure", 0)
    native_raise_state = ExitPortRef(RegionID("native.rep"), "failure", 1)

    callee_facts = lambda name: _fact(definition.artifact, f"#/native-interface/{name}")
    native_facts = lambda name: _fact(native_provider.artifact, f"#/native-interface/{name}")
    callee_boundary = NativeBoundary(
        callee_boundary_id, definition.id, RegionID("callee"),
        callee_facts("signature"), callee_facts("input-tree"), callee_facts("output-tree"),
        (
            NativeInputSlot(0, "positional input", callee_facts("input/0"), callee_entry_ref),
            NativeInputSlot(1, "state port", callee_facts("input/1"), callee_entry_state),
        ),
        (
            NativeOutputSlot(0, "primary output", callee_facts("output/0"), callee_exit_value),
            NativeOutputSlot(1, "state output", callee_facts("output/1"), callee_exit_state),
        ),
        (), (),
    )
    native_boundary = NativeBoundary(
        native_boundary_id, native_provider.id, RegionID("native.rep"),
        native_facts("signature"), native_facts("input-tree"), native_facts("output-tree"),
        (
            NativeInputSlot(0, "opaque reordered role", native_facts("input/0"), native_entry_flag),
            NativeInputSlot(1, "BUFFER_MUTATION", native_facts("input/1"), native_entry_ref),
        ),
        (
            NativeOutputSlot(0, "opaque output role", native_facts("output/0"), native_exit_first),
            NativeOutputSlot(1, "same Value, second port", native_facts("output/1"), native_exit_second),
            NativeOutputSlot(2, "raise payload role", native_facts("output/raise"), native_raise_error),
        ),
        (CoreInputPort(native_entry_state, "canonical world state is not a native flat input"),),
        (
            CoreOutputPort(native_exit_state, "canonical world state is not a native flat output"),
            CoreOutputPort(native_raise_state, "raise world state is not a native flat output"),
        ),
    )
    relation_fact = native_facts("boundary-relation")
    relation = BoundaryRelation(
        BoundaryRelationID("native-to-callee-relation"),
        native_boundary_id, callee_boundary_id,
        (
            BoundaryPortPair(native_entry_ref, callee_entry_ref, native_facts("pair/input-reference")),
            BoundaryPortPair(native_entry_state, callee_entry_state, native_facts("pair/input-state")),
            # A declaration can pair unlike core types; the obligation remains open.
            BoundaryPortPair(native_exit_first, callee_exit_value, native_facts("pair/output-value")),
            BoundaryPortPair(native_exit_state, callee_exit_state, native_facts("pair/output-state")),
            # RAISE exit slots are addressable by the same typed reference and
            # may be declared; this does not establish cross-kind equivalence.
            BoundaryPortPair(native_raise_error, callee_exit_value, native_facts("pair/raise-value")),
        ),
        (),
        tuple(BoundaryObligation(
            domain, "cross-representation condition remains unproved", relation_fact,
        ) for domain in BoundaryDomain),
        relation_fact,
    )
    return replace(
        graph,
        regions=(*graph.regions, native_region),
        operations=(*graph.operations, *native_operations),
        values=(*graph.values, *native_values),
        provider_envelopes=(*graph.provider_envelopes, native_provider),
        provider_regions=(*graph.provider_regions, native_owner),
        native_boundaries=(callee_boundary, native_boundary),
        boundary_relations=(relation,),
    )


__all__ = ["native_boundary_graph"]
