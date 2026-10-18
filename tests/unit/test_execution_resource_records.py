"""Resource declarations retain scoped identity/evidence, not runtime authority.

Only local constructor contracts are tested here. Whether the referenced
occurrences, current states, pool roles, and lifetimes agree is graph validation.
"""
from dataclasses import FrozenInstanceError, fields, replace

import pytest

from scar.ir.execution.common import EvidencePoint, MissingEvidence, Unresolved
from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint, UseRef
from scar.ir.execution.ids import (
    ExternalRealmID, HandleBindingID, HostThreadInstanceID, NativeHandleLifetimeID,
    OperationOccurrenceID, ProcessInstanceID, RealizationID, RegionActivationID,
    ResourceAccessID, ResourceBindingID, ResourceInstanceID, RunID, ValueOccurrenceID,
)
from scar.ir.execution.resources import (
    ActivationHolder, AllocationPlacement, AllocationTarget, CapacityAt,
    ConstraintEvidence, CreatedAt, EndedAt, ExplicitHandle, ExternalRealm,
    HandleBinding, HandleHolder, HandleNamespace, ImplicitBinding, ImportedAt,
    InstanceTarget, NativeHandle, ObjectHandle, ObjectHolder, OwnershipClaim,
    ProcessRealm, ProcessTarget, ProtocolCondition, ProtocolRight, RelationAt,
    ReleaseAuthority, RequirementBinding, ResourceAccessBinding, ResourceInstance,
    ResourceRealization, RightsClaim, RunRealm, Sharing, TargetHolder, ThreadTarget,
    UnresolvedHandle,
)
from scar.ir.program.ids import (
    OperationID, ResourceDefinitionID, ResourceRequirementID, UseID,
)
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.resources import ResourceKind, ResourceRole
from scar.ir.record_codec import decode, encode
from scar.ir.v2.common import Completeness
from scar.ir.v2.ids import ObjectID, StorageAllocationID


def _artifact():
    return ProviderArtifact("memory://resource-facts", "a" * 64, 0, "test-v1")


def _fact(locator="/facts/0"):
    return ProviderFactReference(_artifact(), locator)


def _point():
    return EvidencePoint(RunID("run"), ProcessInstanceID("process"), _fact())


def _gap():
    return Unresolved("not captured", _point())


def _support():
    return (ValueOccurrenceID("current.world"),)


def _native():
    return NativeHandle(
        ValueOccurrenceID("fd-value"),
        HandleNamespace(ProcessRealm(ProcessInstanceID("process")), _fact("/fd")),
        NativeHandleLifetimeID("fd-generation-one"), _fact(),
    )


def _binding(**changes):
    args = dict(
        id=HandleBindingID("handle-binding"), handle=_native(),
        target=InstanceTarget(ResourceInstanceID("ofd-one")),
        start=OccurrencePoint(OperationOccurrenceID("open"), OccurrencePhase.AFTER),
        end=_gap(), support=_support(), rights=_gap(), ownership=_gap(),
        source=_fact(),
    )
    args.update(changes)
    return HandleBinding(**args)


def _access(**changes):
    args = dict(
        id=ResourceAccessID("access"), operation=OperationOccurrenceID("read"),
        requirement=ResourceBindingID("bound-file"),
        handle=ExplicitHandle(HandleBindingID("handle-binding")),
        support=_support(), constraints=(), source=_fact(),
    )
    args.update(changes)
    return ResourceAccessBinding(**args)


def _resource(**changes):
    args = dict(
        id=ResourceInstanceID("ofd-one"), kind=ResourceKind.FILE,
        role=ResourceRole.OPEN_FILE_DESCRIPTION,
        realm=ProcessRealm(ProcessInstanceID("process")),
        origin=CreatedAt(OperationOccurrenceID("open")), source=_fact(),
    )
    args.update(changes)
    return ResourceInstance(**args)


def test_records_are_frozen_slotted_and_do_not_create_proof_or_state_fields():
    records = (_resource(), _binding(), _access())
    for record in records:
        assert not hasattr(record, "__dict__")
        assert not ({"verified", "proven", "ready", "state", "generation"}
                    & {field.name for field in fields(record)})
        with pytest.raises(FrozenInstanceError):
            record.source = MissingEvidence("changed")
        assert decode(type(record), encode(record)) == record
    with pytest.raises(TypeError):
        _access(proven=True)


def test_one_static_creation_can_have_distinct_occurrences_without_freshness_proof():
    first = _resource()
    second = _resource(id=ResourceInstanceID("ofd-two"),
                       origin=CreatedAt(OperationOccurrenceID("open.visit-two")))
    definition = ResourceDefinitionID("static.open")
    realization = ResourceRealization(
        RealizationID("realization-one"), definition, first.origin.operation,
        InstanceTarget(first.id), _fact())
    another = replace(realization, id=RealizationID("realization-two"),
                      site=second.origin.operation, target=InstanceTarget(second.id))
    assert another.definition == realization.definition
    assert another.target != realization.target
    # An alias acquisition can realize the already-existing target too.
    assert replace(another, target=realization.target).target == realization.target
    binding = RequirementBinding(
        ResourceBindingID("bound-file"), ResourceRequirementID("file"),
        RegionActivationID("activation"), realization.target, MissingEvidence("binding gap"))
    assert type(binding.owner) is RegionActivationID


def test_realms_imports_and_existing_target_identities_remain_distinct():
    external = _resource(realm=ExternalRealm(ExternalRealmID("external"), _fact("/namespace")),
                         origin=ImportedAt(_point()))
    run_scoped = replace(external, realm=RunRealm(RunID("run")), origin=_gap())
    assert type(run_scoped.origin) is Unresolved
    targets = (
        InstanceTarget(external.id),
        AllocationTarget(_artifact(), StorageAllocationID("allocation")),
        ProcessTarget(ProcessInstanceID("process")),
        ThreadTarget(HostThreadInstanceID("host-thread")),
    )
    for target in targets:
        realization = ResourceRealization(RealizationID("r"), ResourceDefinitionID("d"),
                                          RegionActivationID("a"), target, _fact())
        assert decode(type(realization), encode(realization)).target == target


def test_native_handle_lifetime_is_not_wrapper_object_or_resource_lifetime():
    first = _native()
    # Reused descriptor scalar value cannot collapse two namespace lifetimes.
    reused = replace(first, lifetime=NativeHandleLifetimeID("fd-generation-two"))
    assert reused.value == first.value and reused != first
    dup = replace(first, value=ValueOccurrenceID("dup-fd"),
                  lifetime=NativeHandleLifetimeID("dup-lifetime"))
    assert _binding(handle=dup).target == _binding().target
    wrapper = ObjectHandle(ValueOccurrenceID("wrapper"), _artifact(),
                           ObjectID("python-wrapper"), _fact())
    assert type(_binding(handle=wrapper).handle.object) is ObjectID
    assert _binding(handle=UnresolvedHandle(None, _gap())).handle.value is None
    with pytest.raises(TypeError):
        replace(first, lifetime=ObjectID("not-native-lifetime"))


def test_rights_unknown_is_distinct_from_complete_empty_and_ownership_axes_are_independent():
    empty = RightsClaim((), Completeness.COMPLETE, _support(), _fact())
    rights = RightsClaim((ProtocolRight(_fact("/protocol"), _fact("/read")),),
                        Completeness.PARTIAL, _support(), _fact())
    holders = (ObjectHolder(_artifact(), ObjectID("o")),
               HandleHolder(NativeHandleLifetimeID("h")),
               ActivationHolder(RegionActivationID("a")),
               TargetHolder(ProcessTarget(ProcessInstanceID("p"))))
    owners = tuple(OwnershipClaim(holder, ReleaseAuthority.OWNED, Sharing.SHARED,
                                  _support(), _fact()) for holder in holders)
    binding = _binding(rights=rights, ownership=owners)
    assert decode(HandleBinding, encode(binding)) == binding
    assert _binding(rights=empty).rights.members == ()
    assert type(_binding().rights) is Unresolved
    borrowed = replace(owners[0], authority=ReleaseAuthority.BORROWED,
                       sharing=Sharing.EXCLUSIVE)
    assert borrowed.authority is ReleaseAuthority.BORROWED


def test_implicit_binding_requires_no_fabricated_handle_value_and_retains_constraints():
    condition = ProtocolCondition(_fact("/rule"), _fact("/selected-stream"),
                                  (UseRef(OperationOccurrenceID("read"), UseID("state-read")),))
    constraints = tuple(ConstraintEvidence(ref, _support(), _fact()) for ref in (
        CapacityAt(ResourceRequirementID("capacity"), 0),
        RelationAt(ResourceRequirementID("relation"), 1, ResourceBindingID("other")),
        condition,
    ))
    access = _access(handle=ImplicitBinding(_fact("/cpu-selection"), _support()),
                     constraints=constraints)
    assert not hasattr(access.handle, "value")
    assert decode(ResourceAccessBinding, encode(access)) == access
    assert type(replace(access, handle=_gap()).handle) is Unresolved


def test_allocation_placement_reuses_allocation_identity_and_requires_pool_instance_target():
    placement = AllocationPlacement(AllocationTarget(_artifact(), StorageAllocationID("alloc")),
                                    InstanceTarget(ResourceInstanceID("pool")), _fact())
    assert decode(AllocationPlacement, encode(placement)) == placement
    with pytest.raises(TypeError):
        replace(placement, pool=ProcessTarget(ProcessInstanceID("not-pool")))


@pytest.mark.parametrize("changes", [
    {"id": ResourceDefinitionID("static-not-instance")},
    {"kind": "FILE"}, {"role": "OPEN_FILE_DESCRIPTION"},
    {"kind": ResourceKind.GPU},
    {"realm": ProcessInstanceID("not-realm")},
    {"origin": OperationID("static-not-occurrence")}, {"source": None},
])
def test_resource_rejects_static_dynamic_confusion_and_raw_fields(changes):
    with pytest.raises((TypeError, ValueError)):
        _resource(**changes)


@pytest.mark.parametrize("changes", [
    {"requirement": ResourceRequirementID("not-bound-instance")},
    {"operation": OperationID("not-occurrence")},
    {"support": []}, {"support": (ObjectID("not-state-occurrence"),)},
    {"constraints": []}, {"handle": "current-stream"},
])
def test_access_requires_typed_binding_and_state_occurrence_support(changes):
    with pytest.raises((TypeError, ValueError)):
        _access(**changes)


@pytest.mark.parametrize("index", [True, -1, 0.0])
def test_constraint_indices_are_nonnegative_exact_int(index):
    with pytest.raises((TypeError, ValueError)):
        CapacityAt(ResourceRequirementID("r"), index)
    with pytest.raises((TypeError, ValueError)):
        RelationAt(ResourceRequirementID("r"), index, ResourceBindingID("b"))


def test_exact_ids_and_nested_variants_reject_subclasses():
    class DerivedInstance(ResourceInstanceID):
        pass

    class DerivedTarget(InstanceTarget):
        pass

    with pytest.raises(TypeError):
        InstanceTarget(DerivedInstance("instance"))
    with pytest.raises(TypeError):
        _binding(target=DerivedTarget(ResourceInstanceID("instance")))


def test_private_mutation_is_rechecked_recursively_at_owner_constructor():
    handle = _native()
    object.__setattr__(handle.namespace.protocol.artifact, "size_bytes", True)
    with pytest.raises((TypeError, ValueError)):
        _binding(handle=handle)

    target = InstanceTarget(ResourceInstanceID("resource"))
    object.__setattr__(target.instance, "value", True)
    with pytest.raises((TypeError, ValueError)):
        _binding(target=target)

    end = EndedAt(OccurrencePoint(OperationOccurrenceID("close"), OccurrencePhase.EDGE, 0), _fact())
    object.__setattr__(end.point, "successor_index", True)
    with pytest.raises((TypeError, ValueError)):
        _binding(end=end)

    use = UseRef(OperationOccurrenceID("read"), UseID("state"))
    condition = ProtocolCondition(_fact(), _fact(), (use,))
    evidence = ConstraintEvidence(condition, _support(), _fact())
    object.__setattr__(use, "use", "not-a-use-id")
    with pytest.raises((TypeError, ValueError)):
        _access(constraints=(evidence,))

    rights = RightsClaim((), Completeness.UNKNOWN, (), _fact())
    object.__setattr__(rights, "completeness", "UNKNOWN")
    with pytest.raises(TypeError):
        _binding(rights=rights)

    owner = OwnershipClaim(HandleHolder(NativeHandleLifetimeID("h")),
                           ReleaseAuthority.UNKNOWN, Sharing.UNKNOWN, (), _fact())
    object.__setattr__(owner, "holder", "opaque-work-ticket")
    with pytest.raises(TypeError):
        _binding(ownership=(owner,))


def test_unknowns_are_explicit_not_none_or_empty_permission_proofs():
    assert type(_access(source=MissingEvidence("not observed")).source) is MissingEvidence
    for changes in ({"end": None}, {"rights": None}, {"ownership": "owned"},
                    {"ownership": []}):
        with pytest.raises((TypeError, ValueError)):
            _binding(**changes)
    with pytest.raises(TypeError):
        RightsClaim((), "COMPLETE", (), _fact())
    with pytest.raises(TypeError):
        ProtocolCondition(_fact(), _fact(), [])
