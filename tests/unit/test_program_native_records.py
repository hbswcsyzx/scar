"""P1 thin-boundary constructors; no artifact replay or equivalence proof."""
from dataclasses import FrozenInstanceError, fields, replace

import pytest

from scar.ir.program.ids import (
    BoundaryRelationID, NativeBoundaryID, ProviderID, RegionID, UseID, ValueID,
)
from scar.ir.program.native import (
    BoundaryDomain, BoundaryObligation, BoundaryPortPair, BoundaryRelation,
    CoreInputPort, CoreOutputPort, EntryPortRef, ExitPortRef, NativeBoundary,
    NativeInputSlot, NativeOutputSlot,
)
from scar.ir.program.providers import (
    ProviderArtifact, ProviderCondition, ProviderConditionDomain, ProviderFactReference,
)


def fact(name="signature"):
    return ProviderFactReference(
        ProviderArtifact("unopened://" + name, "a" * 64, 0, "native.test.v1"), "/" + name)


def entry(name="z"):
    return EntryPortRef(RegionID("left"), ValueID(name))


def exit_port(index=0):
    return ExitPortRef(RegionID("left"), "normal", index)


def native_input(position=0, name="z"):
    return NativeInputSlot(position, "USER_INPUT", fact("input"), entry(name))


def native_output(position=0, index=0):
    return NativeOutputSlot(position, "USER_OUTPUT", fact("output"), exit_port(index))


def boundary():
    return NativeBoundary(
        NativeBoundaryID("left.boundary"), ProviderID("provider"), RegionID("left"),
        fact(), None, None, (native_input(),), (native_output(),),
        (CoreInputPort(entry("state.before"), "canonical state port"),),
        (CoreOutputPort(exit_port(1), "canonical state result"),),
    )


def pair():
    return BoundaryPortPair(entry(), EntryPortRef(RegionID("right"), ValueID("input")), fact("pair"))


def relation():
    return BoundaryRelation(
        BoundaryRelationID("relation"), NativeBoundaryID("left.boundary"),
        NativeBoundaryID("right.boundary"), (pair(),), (),
        tuple(BoundaryObligation(domain, "not yet established", None) for domain in BoundaryDomain),
        fact("rule"),
    )


def test_boundary_keeps_native_signature_order_and_external_trees_as_opaque_facts():
    item = boundary()
    # The signature and both tree facts may live in distinct auxiliary files.
    item = replace(item, input_tree=fact("user-input-tree"), output_tree=fact("user-output-tree"),
                   inputs=(native_input(0, "z"), native_input(1, "a")))
    assert tuple(slot.port.value for slot in item.inputs) == (ValueID("z"), ValueID("a"))
    assert item.signature.artifact != item.input_tree.artifact != item.output_tree.artifact
    assert replace(item, input_tree=None).input_tree is None  # missing, not an empty tree
    assert not hasattr(item, "tree_leaves") and not hasattr(item, "actuals")


def test_raw_roles_do_not_mirror_export_enums_or_retype_canonical_ports():
    item = replace(native_output(), role="BUFFER_MUTATION")
    assert item.port == exit_port() and item.role == "BUFFER_MUTATION"
    assert replace(item, role="FUTURE_PROVIDER_ROLE").role == "FUTURE_PROVIDER_ROLE"
    assert replace(native_input(), role="provider-specific-role").port == entry()
    # Slot constructors do not see core Value variants. They neither ban STATE
    # endpoints nor claim to validate raw role semantics or mutation write-back.
    assert native_input(name="declared.state").port.value == ValueID("declared.state")


@pytest.mark.parametrize("field", ["inputs", "outputs"])
@pytest.mark.parametrize("positions", [(1,), (0, 2), (0, 0), (1, 0)])
def test_signature_positions_are_contiguous_ordered_and_not_a_set(field, positions):
    make = native_input if field == "inputs" else native_output
    slots = tuple(make(position) for position in positions)
    with pytest.raises(ValueError, match="ordered consecutively from zero"):
        replace(boundary(), **{field: slots})


def test_zero_native_ports_are_representable_without_claiming_core_partition_complete():
    item = replace(boundary(), inputs=(), outputs=())
    assert item.inputs == item.outputs == ()
    assert item.core_inputs and item.core_outputs
    # Existence, owner and complete/disjoint coverage belong to graph validation.
    foreign = replace(item, core_inputs=(CoreInputPort(
        EntryPortRef(RegionID("unresolved.region"), ValueID("missing")), "unresolved declaration"),))
    assert foreign.core_inputs[0].port.region == RegionID("unresolved.region")


@pytest.mark.parametrize("field,value", [
    ("id", BoundaryRelationID("left")), ("provider", NativeBoundaryID("provider")),
    ("region", ValueID("left")), ("signature", True), ("input_tree", {}),
    ("output_tree", "unparsed tree"), ("inputs", [native_input()]),
    ("outputs", [native_output()]), ("core_inputs", [CoreInputPort(entry(), "reason")]),
    ("core_outputs", [CoreOutputPort(exit_port(), "reason")]),
])
def test_boundary_rejects_wrong_ids_untyped_facts_and_list_containers(field, value):
    with pytest.raises(TypeError):
        replace(boundary(), **{field: value})


def test_ports_slots_and_core_only_records_reject_mixed_direction_or_wrong_fields():
    for invalid in (True, -1, 0.0):
        with pytest.raises((TypeError, ValueError)):
            replace(exit_port(), index=invalid)
        with pytest.raises((TypeError, ValueError)):
            replace(native_input(), position=invalid)
    for changes in ({"region": ValueID("left")}, {"value": UseID("z")}):
        with pytest.raises(TypeError):
            replace(entry(), **changes)
    with pytest.raises(TypeError):
        replace(native_input(), port=exit_port())
    with pytest.raises(TypeError):
        replace(native_output(), port=entry())
    with pytest.raises(TypeError):
        CoreInputPort(exit_port(), "wrong direction")
    with pytest.raises(TypeError):
        CoreOutputPort(entry(), "wrong direction")
    for record in (replace(native_input(), role="role"), CoreInputPort(entry(), "reason"),
                   CoreOutputPort(exit_port(), "reason")):
        field = "role" if isinstance(record, NativeInputSlot) else "reason"
        with pytest.raises(ValueError):
            replace(record, **{field: ""})
    with pytest.raises(ValueError):
        replace(exit_port(), exit_name="")


def test_port_pairs_are_same_direction_and_do_not_assume_unique_return_producer():
    entry_pair = pair()
    exit_pair = BoundaryPortPair(exit_port(), ExitPortRef(RegionID("right"), "normal", 1), fact("exits"))
    assert type(entry_pair.left) is type(entry_pair.right) is EntryPortRef
    assert type(exit_pair.left) is type(exit_pair.right) is ExitPortRef
    assert {field.name for field in fields(exit_pair.left)} == {"region", "exit_name", "index"}
    assert not hasattr(exit_pair.left, "producer")
    with pytest.raises(TypeError):
        replace(entry_pair, right=exit_pair.right)
    with pytest.raises(TypeError):
        replace(exit_pair, left=entry_pair.left)
    with pytest.raises(TypeError):
        replace(entry_pair, left=ValueID("input"))


def test_relation_allows_partial_many_to_many_declared_port_correspondence():
    original = pair()
    pairs = (original, replace(original, right=replace(original.right, value=ValueID("other"))),
             replace(original, left=entry("other.left")))
    item = replace(relation(), ports=pairs)
    assert len(item.ports) == 3
    assert replace(item, ports=()).ports == ()
    assert not hasattr(item, "actuals") and not hasattr(item, "verified")


def test_same_port_pair_cannot_be_repeated_by_changing_its_evidence():
    original = pair()
    changed_fact = replace(original, evidence=fact("different-evidence"))
    with pytest.raises(ValueError, match="repeat a port pair"):
        replace(relation(), ports=(original, changed_fact))


def test_relation_requires_distinct_boundary_ids_and_expected_namespaces():
    item = relation()
    with pytest.raises(ValueError, match="distinct boundary IDs"):
        replace(item, right=item.left)
    for changes in ({"id": NativeBoundaryID("relation")}, {"left": RegionID("left")},
                    {"right": ProviderID("right")}, {"rule": None},
                    {"ports": [pair()]}, {"conditions": [ProviderCondition(
                        ProviderConditionDomain.SHAPE, fact("condition"))]}):
        with pytest.raises(TypeError):
            replace(item, **changes)


def test_all_eight_obligations_are_required_order_independent_and_always_unproved():
    item = relation()
    assert {row.domain for row in item.obligations} == set(BoundaryDomain)
    assert replace(item, obligations=tuple(reversed(item.obligations))).obligations[0] == item.obligations[-1]
    for rows in ((), item.obligations[:-1], (*item.obligations, item.obligations[0]),
                 (item.obligations[0],) * len(BoundaryDomain)):
        with pytest.raises(ValueError, match="exactly one obligation"):
            replace(item, obligations=rows)
    obligation = replace(item.obligations[0], evidence=fact("comparison-result"))
    assert {field.name for field in fields(obligation)} == {"domain", "reason", "evidence"}
    assert not hasattr(obligation, "proven")
    with pytest.raises(TypeError):
        BoundaryObligation(BoundaryDomain.NUMERICS, "claim", None, proven=True)
    with pytest.raises(TypeError):
        replace(obligation, domain="NUMERICS")
    with pytest.raises(ValueError):
        replace(obligation, reason="")


def test_nested_ports_facts_obligations_and_conditions_are_rechecked_after_tampering():
    item = boundary()
    bad_input = replace(item.inputs[0])
    object.__setattr__(bad_input.port, "value", UseID("wrong.namespace"))
    with pytest.raises(TypeError):
        replace(item, inputs=(bad_input,))

    bad_tree = fact("tree")
    object.__setattr__(bad_tree.artifact, "size_bytes", False)
    with pytest.raises(TypeError):
        replace(boundary(), input_tree=bad_tree)

    bad_obligation = replace(relation().obligations[0])
    object.__setattr__(bad_obligation, "reason", "")
    with pytest.raises(ValueError):
        replace(relation(), obligations=(bad_obligation, *relation().obligations[1:]))

    bad_condition = ProviderCondition(ProviderConditionDomain.MODE, fact("mode"))
    object.__setattr__(bad_condition.evidence, "locator", "")
    with pytest.raises(ValueError):
        replace(relation(), conditions=(bad_condition,))


def test_exact_types_reject_id_port_record_and_tuple_subclasses():
    class DerivedBoundaryID(NativeBoundaryID):
        pass

    class DerivedEntry(EntryPortRef):
        pass

    class DerivedTuple(tuple):
        pass

    class DerivedPair(BoundaryPortPair):
        pass

    with pytest.raises(TypeError):
        replace(boundary(), id=DerivedBoundaryID("left"))
    with pytest.raises(TypeError):
        replace(native_input(), port=DerivedEntry(RegionID("left"), ValueID("z")))
    with pytest.raises(TypeError):
        replace(boundary(), inputs=DerivedTuple((native_input(),)))
    with pytest.raises(TypeError):
        replace(relation(), obligations=DerivedTuple(relation().obligations))
    with pytest.raises(TypeError):
        replace(relation(), ports=(DerivedPair(pair().left, pair().right, fact()),))
    with pytest.raises(TypeError):
        BoundaryPortPair(DerivedEntry(RegionID("left"), ValueID("z")), pair().right, fact())


def test_all_new_records_are_frozen_slotted_and_store_only_declared_fields():
    records = (entry(), exit_port(), native_input(), native_output(),
               CoreInputPort(entry(), "reason"), CoreOutputPort(exit_port(), "reason"),
               boundary(), pair(), relation().obligations[0], relation())
    for record in records:
        assert not hasattr(record, "__dict__")
        assert not ({"verified", "proven", "authorized", "actuals", "producer", "types"}
                    & {field.name for field in fields(record)})
        name = fields(record)[0].name
        with pytest.raises(FrozenInstanceError):
            setattr(record, name, getattr(record, name))
