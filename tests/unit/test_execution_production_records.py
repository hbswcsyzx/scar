from dataclasses import FrozenInstanceError

import pytest

from scar.ir.execution.common import EvidencePoint, MissingEvidence, Unresolved
from scar.ir.execution.content import (
    EvidenceEdgeRef,
    MaterializationRef,
    NativeOutputRef,
    ProtocolSelector,
    StorageContent,
    VersionRef,
)
from scar.ir.execution.coordinates import AccessRef, OperationOccurrenceID, ValueOccurrenceID
from scar.ir.execution.coverage import RegionRef
from scar.ir.execution.ids import (
    EvidenceInventoryID,
    OutcomeProductionID,
    RunID,
    SourceBridgeID,
    WorkOutcomeID,
    WorkTicketID,
    WriteAssociationID,
)
from scar.ir.execution.production import (
    BytePrefixWrite,
    EvidenceInventoryBinding,
    ExternalEstablishment,
    HostWrite,
    InventorySourceRef,
    OutcomeProduction,
    RawRecordRef,
    SourceEdgeRef,
    SourceEndpointBridge,
    SourceEndpointRef,
    StateProduction,
    ValueProduction,
    WorkWrite,
    WriteAssociation,
)
from scar.ir.program.ids import NativeBoundaryID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceNodeKind
from scar.ir.v2.ids import (
    LogicalValueID,
    MaterializationID,
    ObjectID,
    OperationInstanceID,
    StorageRegionID,
    ValueVersionID,
)


def _artifact(uri: str, schema: str = "test") -> ProviderArtifact:
    return ProviderArtifact(uri, "a" * 64, 16, schema)


def _fact(artifact: ProviderArtifact, locator: str = "fact:1") -> ProviderFactReference:
    return ProviderFactReference(artifact, locator)


def _source_ref() -> InventorySourceRef:
    return InventorySourceRef(EvidenceInventoryID("inventory"), "eeg/main")


def test_scoped_inventory_bridge_and_write_records_keep_existing_endpoints():
    evidence_artifact = _artifact("evidence.json", "scar.eeg.v2")
    value_artifact = _artifact("values.json", "scar.values.v2")
    fact = _fact(evidence_artifact)
    source = _source_ref()

    inventory = EvidenceInventoryBinding(
        EvidenceInventoryID("inventory"), RunID("run-1"),
        _artifact("manifest.json", "capture-manifest"),
        _artifact("index.json", "normalization-index"), fact)
    endpoint = SourceEndpointRef(
        source, EvidenceEndpoint(EvidenceNodeKind.OPERATION_INSTANCE,
                                 OperationInstanceID("legacy-op")))
    target = VersionRef(value_artifact, ValueVersionID(LogicalValueID("logical"), 2))
    bridge = SourceEndpointBridge(SourceBridgeID("bridge"), endpoint, target, fact)

    raw = RawRecordRef(source, 7, "b" * 64)
    edge = SourceEdgeRef(source, "edge:write")
    occurrence = OperationOccurrenceID("occurrence")
    value = ValueOccurrenceID("value-occurrence")
    materialization = MaterializationRef(value_artifact, MaterializationID("mat"))
    selector = RegionRef(value_artifact, StorageRegionID("region"))
    association = WriteAssociation(
        WriteAssociationID("association"), raw, WorkWrite(WorkTicketID("ticket")),
        ValueProduction(value), StorageContent(materialization, selector), (edge,), fact)
    outcome = OutcomeProduction(
        OutcomeProductionID("outcome-production"), association.id,
        WorkOutcomeID("outcome"), 0, selector, BytePrefixWrite(), fact)

    assert inventory.run == RunID("run-1")
    assert bridge.target == target
    assert association.stage == raw and association.evidence == (edge,)
    assert outcome.frontier == 0 and type(outcome.frontier) is int


def test_source_endpoint_revalidates_exact_evidence_endpoint_type():
    source = _source_ref()

    class DerivedOperationInstanceID(OperationInstanceID):
        pass

    # EvidenceEndpoint itself uses isinstance and accepts this subclass. The
    # production source boundary must reject it to keep the endpoint wire type
    # canonical.
    endpoint = EvidenceEndpoint(
        EvidenceNodeKind.OPERATION_INSTANCE, DerivedOperationInstanceID("op"))
    with pytest.raises(TypeError):
        SourceEndpointRef(source, endpoint)


def test_nested_endpoint_tampering_is_caught_on_parent_revalidation():
    source = _source_ref()
    endpoint = EvidenceEndpoint(
        EvidenceNodeKind.OPERATION_INSTANCE, OperationInstanceID("op"))
    reference = SourceEndpointRef(source, endpoint)

    class DerivedOperationInstanceID(OperationInstanceID):
        pass

    object.__setattr__(endpoint, "reference", DerivedOperationInstanceID("op"))
    with pytest.raises(TypeError):
        reference.__post_init__()


def test_raw_record_coordinates_and_frontier_reject_bool_or_malformed_digest():
    source = _source_ref()
    with pytest.raises(TypeError):
        RawRecordRef(source, True, "c" * 64)
    with pytest.raises(ValueError):
        RawRecordRef(source, 1, "g" * 64)
    with pytest.raises(ValueError):
        RawRecordRef(source, 1, "c" * 63)

    fact = _fact(_artifact("evidence.json"))
    write = WriteAssociation(
        WriteAssociationID("write"), Unresolved("raw not mapped", EvidencePoint(
            RunID("run"), None, MissingEvidence("point not captured"))),
        ExternalEstablishment(EvidencePoint(RunID("run"), None, fact)),
        ValueProduction(ValueOccurrenceID("v")), Unresolved("placement unknown", EvidencePoint(
            RunID("run"), None, fact)), (), fact)
    args = (OutcomeProductionID("op"), write.id, WorkOutcomeID("work-outcome"))
    with pytest.raises(TypeError):
        OutcomeProduction(*args, True, Unresolved("actual unknown", EvidencePoint(
            RunID("run"), None, fact)), Unresolved("rule unknown", EvidencePoint(
            RunID("run"), None, fact)), fact)


def test_exact_variants_and_frozen_records():
    fact = _fact(_artifact("evidence.json"))
    occurrence = OperationOccurrenceID("op")
    access = AccessRef(occurrence, 0)
    assert StateProduction(access).effect is access
    assert HostWrite(occurrence).operation is occurrence

    class DerivedAccessRef(AccessRef):
        pass

    with pytest.raises(TypeError):
        StateProduction(DerivedAccessRef(occurrence, 0))

    inv = EvidenceInventoryBinding(
        EvidenceInventoryID("inventory"), RunID("run"),
        _artifact("manifest", "manifest"), _artifact("index", "index"), fact)
    with pytest.raises(FrozenInstanceError):
        inv.run = RunID("other")
    assert not hasattr(inv, "__dict__")


def test_typed_native_and_object_targets_are_supported_without_joining_by_id():
    source = _source_ref()
    evidence_artifact = _artifact("evidence.json", "scar.eeg.v2")
    fact = _fact(evidence_artifact)
    native_endpoint = SourceEndpointRef(
        source, EvidenceEndpoint(EvidenceNodeKind.CONTROL_EVENT, "raw-control"))
    target = RegionRef(_artifact("values.json", "scar.values.v2"), StorageRegionID("r"))
    bridge = SourceEndpointBridge(SourceBridgeID("native-bridge"), native_endpoint,
                                  target, fact)
    assert bridge.target is target

    native_stage = NativeOutputRef(NativeBoundaryID("boundary"),
                                   OperationOccurrenceID("return-op"), 0)
    assert native_stage.position == 0
    assert ProtocolSelector(fact).reference is fact

