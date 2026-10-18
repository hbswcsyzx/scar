from dataclasses import FrozenInstanceError

import pytest

from scar.ir.program.model import AccessMode
from scar.ir.program.state_addresses import (
    AddressCoverage, AddressEffect, AddressUnit, CellContent, DomainOwner,
    DynamicField, Element, ExistingAccess, InvokeStateOperand, NamespaceKey,
    ObjectField, ReferenceOwner, ResourceOwner, Slice, StateAddressRefinement,
    StorageRange, UnknownOwner, UnknownSelection, WholeOwner, address_effect_uses,
    selector_uses,
)
from scar.ir.program.ids import OperationID, ResourceRequirementID, UseID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.state_modes import AccessMode as StateAccessMode


def test_access_mode_is_one_shared_enum_and_address_variants_are_typed():
    assert AccessMode is StateAccessMode
    site = ExistingAccess(OperationID("op"), 0)
    invoke = InvokeStateOperand(OperationID("invoke"), UseID("state"))
    assert (site.operation.wire, site.index) == ("program_operation:op", 0)
    assert invoke.state_use.wire == "program_use:state"
    assert DomainOwner() != WholeOwner()
    assert CellContent() != WholeOwner()
    assert NamespaceKey(UseID("k")) != DynamicField(UseID("k"))


def test_all_selector_variants_keep_ordered_operands_and_duplicates():
    key = UseID("key")
    name = UseID("name")
    selectors = (
        WholeOwner(), NamespaceKey(key), ObjectField("field"), DynamicField(name),
        CellContent(), Element(key), Slice(key, None, key),
        StorageRange(AddressUnit.BYTE, key, key), UnknownSelection("opaque", (name, key)),
    )
    effect = AddressEffect(UnknownOwner("owner", (key, name, key)), selectors,
                           AccessMode.READ_WRITE, 3)
    assert selector_uses(selectors[0]) == ()
    assert selector_uses(selectors[1]) == (key,)
    assert selector_uses(selectors[6]) == (key, key)
    assert selector_uses(selectors[7]) == (key, key)
    assert address_effect_uses(effect) == (key, name, key, key, key, key, key, name, key)
    # Owner operands are separate from the path projection; neither is deduped.
    assert effect.owner.operands == (key, name, key)
    assert effect.path is selectors


def test_refinement_requires_nonempty_effects_and_nonempty_paths():
    with pytest.raises(ValueError, match="path must be nonempty"):
        AddressEffect(DomainOwner(), (), AccessMode.READ)
    effect = AddressEffect(DomainOwner(), (WholeOwner(),), AccessMode.READ)
    with pytest.raises(ValueError, match="effects must be nonempty"):
        StateAddressRefinement(ExistingAccess(OperationID("op"), 0), (),
                               AddressCoverage.PARTIAL)
    with pytest.raises(TypeError):
        AddressEffect(DomainOwner(), (WholeOwner(),), AccessMode.READ, stage=True)
    with pytest.raises(TypeError):
        ExistingAccess(OperationID("op"), True)
    with pytest.raises(TypeError):
        StorageRange(AddressUnit.BYTE, UseID("start"), True)
    assert effect.stage is None


def test_protocol_is_a_scoped_fact_reference_not_a_truth_flag():
    artifact = ProviderArtifact("provider://schema", "0" * 64, 0, "state-address-v1")
    protocol = ProviderFactReference(artifact, "protocol/selectors")
    refinement = StateAddressRefinement(
        ExistingAccess(OperationID("op"), 0),
        (AddressEffect(DomainOwner(), (WholeOwner(),), AccessMode.READ),),
        AddressCoverage.DECLARED_COMPLETE, protocol,
    )
    assert refinement.protocol is protocol
    assert not hasattr(refinement, "verified")


def test_nested_exact_types_are_revalidated_and_records_are_frozen():
    refinement = StateAddressRefinement(
        ExistingAccess(OperationID("op"), 0),
        (AddressEffect(DomainOwner(), (WholeOwner(),), AccessMode.READ),),
        AddressCoverage.PARTIAL,
    )
    with pytest.raises(FrozenInstanceError):
        refinement.coverage = AddressCoverage.DECLARED_COMPLETE
    object.__setattr__(refinement.effects[0], "stage", True)
    with pytest.raises(TypeError):
        refinement.__post_init__()
    with pytest.raises(TypeError):
        AddressEffect(type("DerivedOwner", (DomainOwner,), {})(),
                      (WholeOwner(),), AccessMode.READ)


def test_slice_omission_is_distinct_from_a_real_none_value_use():
    omitted = Slice()
    explicit_value = UseID("none-value")
    explicit = Slice(explicit_value, None, None)
    assert selector_uses(omitted) == ()
    assert selector_uses(explicit) == (explicit_value,)

