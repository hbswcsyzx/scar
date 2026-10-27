"""Environment declarations retain role, port and state-domain distinctions."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace

import pytest

from scar.ir.program.environments import (
    EnvironmentInterface, EnvironmentMember, EnvironmentRole, FunctionEntryLayout,
)
from scar.ir.program.functions import FormalPort
from scar.ir.program.ids import (
    EnvironmentInterfaceID, LocationID, OperationID, RegionID, UseID, ValueID,
)
from scar.ir.record_codec import decode, encode
from scar.ir.v2.ids import OperationDefinitionID, ValueSlotID


def environment(cell_count=0):
    world = LocationID("world")
    base = tuple(EnvironmentMember(role, ValueID(role.value.lower()), (world,))
                 for role in tuple(EnvironmentRole)[:-1])
    cells = tuple(EnvironmentMember(
        EnvironmentRole.CAPTURED_CELL, ValueID(f"cell.{i}"), (world,),
        ValueSlotID(f"free.{i}"), i) for i in range(cell_count))
    return EnvironmentInterface(EnvironmentInterfaceID("environment"),
                                RegionID("body"), OperationDefinitionID("function"),
                                base + cells)


@pytest.mark.parametrize("cell_count", [0, 1, 2])
def test_record_round_trip_preserves_all_ordered_ports_and_shared_world(cell_count):
    original = environment(cell_count)
    wire = encode(original)
    assert decode(EnvironmentInterface, wire) == original
    assert [row["role"] for row in wire["members"][:5]] == [
        "FUNCTION_OBJECT", "GLOBALS_NAMESPACE", "BUILTINS_NAMESPACE",
        "DEFAULTS", "KEYWORD_DEFAULTS",
    ]
    assert all(member.locations == (LocationID("world"),) for member in original.members)
    assert [member.cell_position for member in original.members[5:]] == list(range(cell_count))


def test_interface_has_no_second_value_packet_or_argument_binding_table():
    assert {field.name for field in fields(EnvironmentInterface)} == {
        "id", "region", "code_definition", "members",
    }
    assert {field.name for field in fields(EnvironmentMember)} == {
        "role", "reference", "locations", "cell_slot", "cell_position",
    }
    item = environment()
    # These are unique parameter definitions; the declaration has no actual
    # object identity or disjointness field that could forbid aliasing at a call.
    assert len({member.reference for member in item.members}) == 5
    with pytest.raises(FrozenInstanceError):
        item.region = RegionID("other")
    with pytest.raises(FrozenInstanceError):
        item.members[0].reference = ValueID("other")


@pytest.mark.parametrize("field,value", [
    ("role", "FUNCTION_OBJECT"),
    ("role", True),
    ("reference", UseID("reference")),
    ("reference", "program_value:reference"),
    ("locations", [LocationID("world")]),
    ("locations", (ValueID("world"),)),
    ("locations", ("world",)),
])
def test_member_rejects_untyped_fields(field, value):
    with pytest.raises(TypeError):
        replace(environment().members[0], **{field: value})


@pytest.mark.parametrize("role", tuple(EnvironmentRole)[:-1])
@pytest.mark.parametrize("field,value", [("cell_slot", ValueSlotID("x")), ("cell_position", 0)])
def test_cell_fields_cannot_be_attached_to_noncell_roles(role, field, value):
    with pytest.raises(ValueError, match="only captured"):
        EnvironmentMember(role, ValueID("member"), **{field: value})


@pytest.mark.parametrize("field,value", [
    ("cell_slot", None), ("cell_slot", ValueID("x")), ("cell_slot", "x"),
    ("cell_position", None), ("cell_position", True), ("cell_position", False),
    ("cell_position", 0.0), ("cell_position", "0"), ("cell_position", -1),
])
def test_captured_cell_needs_typed_slot_and_nonboolean_nonnegative_position(field, value):
    with pytest.raises((TypeError, ValueError)):
        replace(environment(1).members[-1], **{field: value})


def test_location_repetition_is_rejected_within_member_but_sharing_is_allowed():
    item = environment(2)
    with pytest.raises(ValueError, match="locations must not repeat"):
        replace(item.members[0], locations=(LocationID("world"), LocationID("world")))
    assert decode(EnvironmentInterface, encode(item)) == item
    # A record with no state-domain declaration is representable; the graph
    # validator, not this record, decides whether its entry/state contract fits.
    assert replace(item.members[0], locations=()).locations == ()


@pytest.mark.parametrize("field,value", [
    ("id", RegionID("environment")),
    ("id", "program_environment:environment"),
    ("region", ValueID("body")),
    ("code_definition", OperationID("function")),
    ("code_definition", "function"),
])
def test_interface_rejects_wrong_identifier_namespaces(field, value):
    with pytest.raises(TypeError):
        replace(environment(), **{field: value})


@pytest.mark.parametrize("mutation", [
    "empty", "missing_builtins", "swapped_namespaces", "duplicate_role",
    "cell_before_defaults", "extra_base_role", "repeated_reference",
    "cell_reference_reuses_base", "repeated_cell_slot", "cell_position_gap",
    "reversed_cells", "list_members", "untyped_member",
])
def test_interface_rejects_incomplete_or_ambiguous_layout(mutation):
    item = environment(2)
    members = item.members
    if mutation == "empty": members = ()
    elif mutation == "missing_builtins": members = members[:2] + members[3:]
    elif mutation == "swapped_namespaces": members = (members[0], members[2], members[1]) + members[3:]
    elif mutation == "duplicate_role": members = members[:2] + (replace(members[2], role=EnvironmentRole.GLOBALS_NAMESPACE),) + members[3:]
    elif mutation == "cell_before_defaults": members = members[:3] + (members[5],) + members[3:5] + members[6:]
    elif mutation == "extra_base_role": members += (replace(members[0], reference=ValueID("extra")),)
    elif mutation == "repeated_reference": members = (replace(members[0], reference=members[1].reference),) + members[1:]
    elif mutation == "cell_reference_reuses_base": members = members[:-1] + (replace(members[-1], reference=members[0].reference),)
    elif mutation == "repeated_cell_slot": members = members[:-1] + (replace(members[-1], cell_slot=members[-2].cell_slot),)
    elif mutation == "cell_position_gap": members = members[:-1] + (replace(members[-1], cell_position=2),)
    elif mutation == "reversed_cells": members = members[:5] + tuple(reversed(members[5:]))
    elif mutation == "list_members": members = list(members)
    else: members = (encode(members[0]),) + members[1:]
    with pytest.raises((TypeError, ValueError)):
        replace(item, members=members)


@pytest.mark.parametrize("mutation", [
    "extra_interface_field", "missing_interface_field", "extra_member_field",
    "missing_cell_position", "boolean_cell_position", "wrong_reference_namespace",
    "wrong_environment_namespace", "unknown_role", "wrong_wire", "duplicate_cell_slot",
])
def test_strict_codec_rejects_tampered_environment_records(mutation):
    wire = deepcopy(encode(environment(2)))
    if mutation == "extra_interface_field": wire["call_arguments"] = []
    elif mutation == "missing_interface_field": del wire["code_definition"]
    elif mutation == "extra_member_field": wire["members"][0]["actual_object"] = "invented"
    elif mutation == "missing_cell_position": del wire["members"][-1]["cell_position"]
    elif mutation == "boolean_cell_position": wire["members"][5]["cell_position"] = False
    elif mutation == "wrong_reference_namespace": wire["members"][0]["reference"] = encode(UseID("function"))
    elif mutation == "wrong_environment_namespace": wire["id"] = encode(RegionID("environment"))
    elif mutation == "unknown_role": wire["members"][0]["role"] = "FUNCTION_ENVIRONMENT"
    elif mutation == "wrong_wire": wire["id"]["wire"] = "program_environment:other"
    else: wire["members"][-1]["cell_slot"] = wire["members"][-2]["cell_slot"]
    with pytest.raises((TypeError, ValueError)):
        decode(EnvironmentInterface, wire)


def test_exact_types_reject_identifier_and_tuple_subclasses():
    class DerivedValueID(ValueID):
        pass

    class DerivedTuple(tuple):
        pass

    with pytest.raises(TypeError):
        replace(environment().members[0], reference=DerivedValueID("reference"))
    with pytest.raises(TypeError):
        replace(environment().members[0], locations=DerivedTuple((LocationID("world"),)))
    with pytest.raises(TypeError):
        replace(environment(), members=DerivedTuple(environment().members))


def test_frozen_record_tampering_cannot_round_trip_through_strict_decode():
    item = environment(1)
    object.__setattr__(item.members[-1], "cell_position", False)
    with pytest.raises((TypeError, ValueError)):
        decode(EnvironmentInterface, encode(item))


@pytest.mark.parametrize("parameter_count", [0, 1, 3])
def test_function_entry_layout_round_trip_keeps_formal_order_without_duplicate_environment(parameter_count):
    # Names deliberately do not sort lexically: layout order is declaration
    # order, not ValueID order or the physical entry block's argument order.
    ports = tuple(FormalPort(ValueSlotID(name), ValueID(f"formal.{name}"))
                  for name in ("z", "a", "m")[:parameter_count])
    layout = FunctionEntryLayout(environment().id, ports)
    assert decode(FunctionEntryLayout, encode(layout)) == layout
    assert layout.parameters == ports
    assert set(encode(layout)) == {"environment", "parameters"}
    assert {field.name for field in fields(FunctionEntryLayout)} == {"environment", "parameters"}
    with pytest.raises(FrozenInstanceError):
        layout.parameters = ()


@pytest.mark.parametrize("bad_environment", [
    RegionID("environment"), ValueID("environment"), "program_environment:environment", None,
])
def test_function_entry_layout_rejects_wrong_environment_namespace(bad_environment):
    with pytest.raises(TypeError):
        FunctionEntryLayout(bad_environment, ())


@pytest.mark.parametrize("bad_parameters", [
    [], [FormalPort(ValueSlotID("x"), ValueID("x"))],
    ({"slot": "x", "value": "x"},), (ValueID("x"),),
    (FormalPort(ValueID("x"), ValueID("x")),),
    (FormalPort("x", ValueID("x")),),
    (FormalPort(ValueSlotID("x"), UseID("x")),),
    (FormalPort(ValueSlotID("x"), LocationID("x")),),
    (FormalPort(ValueSlotID("x"), "program_value:x"),),
])
def test_function_entry_layout_rechecks_formal_fields_not_validated_by_formalport(bad_parameters):
    with pytest.raises(TypeError):
        FunctionEntryLayout(environment().id, bad_parameters)


@pytest.mark.parametrize("duplicate", ["slot", "value"])
def test_function_entry_layout_rejects_repeated_slot_or_value(duplicate):
    first = FormalPort(ValueSlotID("x"), ValueID("x"))
    second = FormalPort(first.slot if duplicate == "slot" else ValueSlotID("y"),
                        first.value if duplicate == "value" else ValueID("y"))
    with pytest.raises(ValueError, match="distinct"):
        FunctionEntryLayout(environment().id, (first, second))


def test_function_entry_layout_rejects_formal_and_nested_id_subclasses():
    class DerivedFormal(FormalPort):
        pass

    class DerivedSlot(ValueSlotID):
        pass

    class DerivedValue(ValueID):
        pass

    class DerivedTuple(tuple):
        pass

    candidates = (
        (DerivedFormal(ValueSlotID("x"), ValueID("x")),),
        (FormalPort(DerivedSlot("x"), ValueID("x")),),
        (FormalPort(ValueSlotID("x"), DerivedValue("x")),),
        DerivedTuple((FormalPort(ValueSlotID("x"), ValueID("x")),)),
    )
    for parameters in candidates:
        with pytest.raises(TypeError):
            FunctionEntryLayout(environment().id, parameters)


@pytest.mark.parametrize("mutation", [
    "extra_region", "extra_actuals", "missing_parameters", "wrong_environment",
    "wrong_slot", "wrong_value", "duplicate_slot", "duplicate_value",
])
def test_function_entry_layout_codec_rejects_tamper_without_a_parallel_binding_table(mutation):
    ports = (FormalPort(ValueSlotID("x"), ValueID("x")),
             FormalPort(ValueSlotID("y"), ValueID("y")))
    wire = encode(FunctionEntryLayout(environment().id, ports))
    if mutation == "extra_region": wire["region"] = encode(RegionID("body"))
    elif mutation == "extra_actuals": wire["call_arguments"] = []
    elif mutation == "missing_parameters": del wire["parameters"]
    elif mutation == "wrong_environment": wire["environment"] = encode(RegionID("environment"))
    elif mutation == "wrong_slot": wire["parameters"][0]["slot"] = encode(ValueID("x"))
    elif mutation == "wrong_value": wire["parameters"][0]["value"] = encode(UseID("x"))
    elif mutation == "duplicate_slot": wire["parameters"][1]["slot"] = wire["parameters"][0]["slot"]
    else: wire["parameters"][1]["value"] = wire["parameters"][0]["value"]
    with pytest.raises((TypeError, ValueError)):
        decode(FunctionEntryLayout, wire)
