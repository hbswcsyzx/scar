from dataclasses import FrozenInstanceError
import json
import sys
import types

import pytest

from scar.ir.program import (
    AccessMode, Behavior, Block, BlockArgument, BlockID, DataValue, ExitKind,
    ExitPort, Footprint, FootprintKind, LiteralOrigin, LocationID, Operation,
    OperationID, OperationResult, OrderEdge, ProgramGraph, ReferenceValue, Region,
    RegionID, Stability, StateAccess, StateLocation, StateVersionValue, Successor,
    Terminator, TerminatorKind, Use, UseID, UseRole, ValueID, ValueKind, ValueType,
    dumps, loads, value_type,
)
from scar.ir.record_codec import encode


@pytest.fixture
def skip_graph_validation(monkeypatch):
    """Exercise record serialization independently of the parent graph validator."""
    module = types.ModuleType("scar.ir.program.validation")
    module.require_valid = lambda graph: None
    monkeypatch.setitem(sys.modules, "scar.ir.program.validation", module)


def minimal_graph(*, values=(), locations=()):
    root = RegionID("main")
    block_id = BlockID("entry")
    operation_id = OperationID("return")
    terminator = Terminator(TerminatorKind.RETURN, exit="normal")
    operation = Operation(operation_id, "return", (Behavior.CONTROL,),
                           terminator=terminator)
    block = Block(block_id, (), (operation_id,))
    region = Region(root, "main", block_id, (block,),
                    (ExitPort("normal", ExitKind.NORMAL, ()),))
    return ProgramGraph(root, (region,), (operation,), tuple(values), tuple(locations))


def test_program_ids_have_disjoint_program_prefixes():
    assert ValueID("x").wire == "program_value:x"
    assert LocationID("x").wire == "program_location:x"
    assert OperationID("x").wire == "program_operation:x"
    assert RegionID("x").wire == "program_region:x"
    assert BlockID("x").wire == "program_block:x"
    assert UseID("x").wire == "program_use:x"


def test_records_are_frozen_and_value_types_are_explicit():
    location = LocationID("file")
    data = ValueType(ValueKind.DATA, data_type="builtins.bool")
    state = ValueType(ValueKind.STATE, location=location)
    reference = ValueType(ValueKind.REFERENCE)
    assert data.kind is ValueKind.DATA and data.data_type == "builtins.bool"
    assert state.kind is ValueKind.STATE and state.location == location
    assert reference.kind is ValueKind.REFERENCE
    with pytest.raises(ValueError):
        ValueType(ValueKind.REFERENCE, data_type="builtins.object")
    with pytest.raises(ValueError):
        ValueType(ValueKind.REFERENCE, location=location)
    with pytest.raises(FrozenInstanceError):
        data.kind = ValueKind.STATE


@pytest.mark.parametrize("kind,start,stop", [
    (FootprintKind.WHOLE, 0, 4),
    (FootprintKind.UNKNOWN, 1, None),
    (FootprintKind.INTERVAL, True, 5),
    (FootprintKind.INTERVAL, 5, 2),
])
def test_footprint_rejects_malformed_bounds(kind, start, stop):
    with pytest.raises((TypeError, ValueError)):
        Footprint(kind, start, stop)


def test_footprint_and_state_access_enforce_local_write_contract():
    whole = Footprint(FootprintKind.WHOLE)
    interval = Footprint(FootprintKind.INTERVAL, 4, 9)
    unknown = Footprint()
    assert (whole.start, whole.stop) == (None, None)
    assert (interval.start, interval.stop) == (4, 9)
    assert unknown.kind is FootprintKind.UNKNOWN
    empty_interval = Footprint(FootprintKind.INTERVAL, 3, 3)
    assert (empty_interval.start, empty_interval.stop) == (3, 3)

    location = LocationID("buffer")
    before = UseID("state-before")
    after = ValueID("state-after")
    assert StateAccess(location, before, AccessMode.READ).after is None
    StateAccess(location, before, AccessMode.WRITE, after, whole, full_overwrite=True)
    with pytest.raises(ValueError):
        StateAccess(location, before, AccessMode.READ, after)
    with pytest.raises(ValueError):
        StateAccess(location, before, AccessMode.WRITE)
    with pytest.raises(ValueError):
        StateAccess(location, before, AccessMode.READ_WRITE, after,
                    whole, full_overwrite=True)
    with pytest.raises(TypeError):
        StateAccess(location, before, AccessMode.WRITE, after, whole,
                    full_overwrite=1)


def test_literal_origin_is_limited_to_exact_builtin_typed_data_values():
    region = RegionID("r")
    assert value_type(DataValue(ValueID("b"), region, LiteralOrigin(True),
                                "builtins.bool")) == ValueType(
                                    ValueKind.DATA, data_type="builtins.bool")
    assert DataValue(ValueID("i"), region, LiteralOrigin(4),
                     "builtins.int").data_type == "builtins.int"
    assert DataValue(ValueID("f"), region, LiteralOrigin(2.5),
                     "builtins.float").data_type == "builtins.float"
    assert DataValue(ValueID("s"), region, LiteralOrigin("x"),
                     "builtins.str").data_type == "builtins.str"
    assert DataValue(ValueID("n"), region, LiteralOrigin(None),
                     "builtins.NoneType").data_type == "builtins.NoneType"
    # Nonliteral computational values retain their caller-declared type names.
    assert DataValue(ValueID("opaque"), region, OperationResult(OperationID("op"), 0),
                     "library.Tensor").data_type == "library.Tensor"

    with pytest.raises(ValueError):
        DataValue(ValueID("bad-bool"), region, LiteralOrigin(True), "builtins.int")
    with pytest.raises(ValueError):
        DataValue(ValueID("bad-int"), region, LiteralOrigin(1), "builtins.bool")
    with pytest.raises(ValueError):
        ReferenceValue(ValueID("ref"), region, LiteralOrigin("x"))
    with pytest.raises(TypeError):
        LiteralOrigin(float("nan"))


def test_constructor_integer_fields_reject_bool():
    with pytest.raises(ValueError):
        BlockArgument(BlockID("b"), True)
    with pytest.raises(ValueError):
        OperationResult(OperationID("o"), False)
    with pytest.raises(ValueError):
        StateLocation(LocationID("l"), "label", extent=True)


def test_operation_preserves_use_occurrences_and_checks_owned_use_links():
    operation_id = OperationID("eq")
    value = ValueID("same")
    first = Use(UseID("left-use"), value, UseRole.DATA)
    second = Use(UseID("right-use"), value, UseRole.DATA)
    operation = Operation(operation_id, "compare", (Behavior.COMPUTE,),
                           uses=(first, second), results=(ValueID("result"),))
    assert operation.uses == (first, second)
    assert operation.uses[0].value == operation.uses[1].value
    with pytest.raises(ValueError):
        Operation(operation_id, "bad", (Behavior.COMPUTE,), uses=(first, first))
    with pytest.raises(ValueError):
        Operation(operation_id, "bad-call", (Behavior.COMPUTE,),
                  call_arguments=(first.id,))


def test_terminator_shapes_and_state_use_roles_are_local():
    successor = Successor(BlockID("next"), (UseID("edge-arg"),))
    assert Terminator(TerminatorKind.JUMP, (Successor(BlockID("next"), ()),)).kind is TerminatorKind.JUMP
    assert Terminator(TerminatorKind.BRANCH,
                      (Successor(BlockID("yes"), ()), Successor(BlockID("no"), ())),
                      condition=UseID("cond")).condition == UseID("cond")
    with pytest.raises(ValueError):
        Terminator(TerminatorKind.JUMP, (successor, successor))
    with pytest.raises(ValueError):
        Terminator(TerminatorKind.BRANCH, condition=UseID("cond"))

    state = Use(UseID("old-state"), ValueID("s0"), UseRole.STATE_CONTENT)
    wrong_role = Use(UseID("old-state-order"), ValueID("s0"), UseRole.STATE_ORDER)
    access = StateAccess(LocationID("file"), state.id, AccessMode.READ)
    Operation(OperationID("read"), "read", (Behavior.READ,), uses=(state,), accesses=(access,))
    with pytest.raises(ValueError):
        Operation(OperationID("bad-read"), "read", (Behavior.READ,),
                  uses=(wrong_role,), accesses=(access,))


def test_graph_tuple_registries_reject_duplicate_ids_without_overwrite():
    graph = minimal_graph()
    with pytest.raises(ValueError):
        ProgramGraph(graph.root, graph.regions, graph.operations,
                     (DataValue(ValueID("dup"), graph.root,
                                OperationResult(OperationID("a"), 0), "x"),
                      DataValue(ValueID("dup"), graph.root,
                                OperationResult(OperationID("b"), 0), "y")))


def test_codec_roundtrips_distinct_value_union_variants_and_literal_scalars(skip_graph_validation):
    region = RegionID("main")
    location = LocationID("state")
    values = (
        DataValue(ValueID("literal-bool"), region, LiteralOrigin(True), "builtins.bool"),
        DataValue(ValueID("literal-int"), region, LiteralOrigin(1), "builtins.int"),
        ReferenceValue(ValueID("ref"), region, BlockArgument(BlockID("entry"), 0),
                       referent_identity="object-token", targets=(location,),
                       selector=Footprint(FootprintKind.INTERVAL, 0, 3)),
        StateVersionValue(ValueID("state-v1"), region,
                          OperationResult(OperationID("write"), 0), location),
    )
    graph = minimal_graph(values=values,
                          locations=(StateLocation(location, "state", extent=8,
                                                   stability=Stability.INTERNAL),))
    payload = dumps(graph)
    restored = loads(payload)
    assert restored == graph
    assert type(restored.values[0]) is DataValue
    assert type(restored.values[1]) is DataValue
    assert restored.values[0].origin.value is True
    assert type(restored.values[0].origin.value) is bool
    assert restored.values[1].origin.value == 1
    assert type(restored.values[1].origin.value) is int
    assert type(restored.values[2]) is ReferenceValue
    assert type(restored.values[3]) is StateVersionValue


def test_codec_rejects_unknown_schema_fields_wrong_version_duplicate_json_keys(skip_graph_validation):
    graph = minimal_graph()
    document = json.loads(dumps(graph))
    document["unexpected"] = True
    with pytest.raises(ValueError):
        loads(json.dumps(document))
    document = json.loads(dumps(graph))
    document["schema_version"] = True
    with pytest.raises(ValueError):
        loads(json.dumps(document))
    document = json.loads(dumps(graph))
    document["regions"][0]["unexpected"] = 3
    with pytest.raises(ValueError):
        loads(json.dumps(document))
    duplicate_key_payload = '{"schema":"scar.program-graph","schema":"scar.program-graph"}'
    with pytest.raises(ValueError):
        loads(duplicate_key_payload)


def test_codec_tuple_decode_rejects_duplicate_registry_ids(skip_graph_validation):
    graph = minimal_graph()
    document = json.loads(dumps(graph))
    first = DataValue(ValueID("duplicate"), graph.root,
                      OperationResult(OperationID("p0"), 0), "result")
    second = DataValue(ValueID("duplicate"), graph.root,
                       OperationResult(OperationID("p1"), 0), "result")
    document["values"] = [encode(first), encode(second)]
    with pytest.raises(ValueError, match="duplicate"):
        loads(json.dumps(document))


def test_codec_calls_full_graph_validation(skip_graph_validation, monkeypatch):
    graph = minimal_graph()
    module = types.ModuleType("scar.ir.program.validation")
    def reject(candidate):
        raise ValueError("cross-reference rejected")
    module.require_valid = reject
    monkeypatch.setitem(sys.modules, "scar.ir.program.validation", module)
    with pytest.raises(ValueError, match="cross-reference rejected"):
        dumps(graph)


def test_codec_accepts_a_real_valid_program_and_rejects_missing_root():
    from scar.ir.program.validation import require_valid

    graph = minimal_graph()
    require_valid(graph)
    assert loads(dumps(graph)) == graph
    invalid = ProgramGraph(RegionID("missing"), graph.regions,
                           graph.operations, graph.values)
    with pytest.raises(ValueError, match="missing_root"):
        dumps(invalid)


def test_real_validator_accepts_zero_size_half_open_reference_selector():
    from scar.ir.program.validation import require_valid

    root = RegionID("main")
    block_id = BlockID("entry")
    location_id = LocationID("empty-buffer")
    value_id = ValueID("empty-reference")
    operation_id = OperationID("return")
    operation = Operation(operation_id, "return", (Behavior.CONTROL,),
                          terminator=Terminator(TerminatorKind.RETURN, exit="normal"))
    block = Block(block_id, (value_id,), (operation_id,))
    region = Region(root, "main", block_id, (block,),
                    (ExitPort("normal", ExitKind.NORMAL, ()),))
    reference = ReferenceValue(
        value_id, root, BlockArgument(block_id, 0), targets=(location_id,),
        selector=Footprint(FootprintKind.INTERVAL, 4, 4))
    location = StateLocation(location_id, "empty-buffer", extent=4)
    graph = ProgramGraph(root, (region,), (operation,), (reference,), (location,))

    require_valid(graph)
    assert loads(dumps(graph)) == graph
