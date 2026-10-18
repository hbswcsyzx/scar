"""Schema-v5 production records with strict old-wire preservation."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from scar.ir.execution.codec import SCHEMA_VERSION, dumps, from_dict, loads, to_dict
from scar.ir.execution.common import EvidencePoint, MissingEvidence, Unresolved
from scar.ir.execution.content import (
    EndpointContent,
    EvidenceEdgeRef,
    MaterializationRef,
    NativeOutputRef,
    ObjectRef,
    ProtocolSelector,
    StorageContent,
    VersionRef,
)
from scar.ir.execution.coordinates import AccessRef
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
from scar.ir.execution.resources import AllocationTarget
from scar.ir.program.ids import NativeBoundaryID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceNodeKind
from scar.ir.v2.ids import (
    LogicalValueID,
    MaterializationID,
    MeasurementID,
    ObjectID,
    OperationInstanceID,
    ResourceID,
    StorageAllocationID,
    StorageRegionID,
    ValueVersionID,
)
from tests.fixtures.execution_content_graphs import content_connection_fixture


FIXTURES = Path(__file__).parents[1] / "fixtures"
CONTENT_FIELDS = ("denotations", "work_evidence_bindings", "observation_requirements",
                 "observation_roots", "content_reads")
PRODUCTION_FIELDS = ("source_inventories", "source_bridges", "writes", "produced")


def _artifact(uri, schema):
    return ProviderArtifact(uri, "a" * 64, 16, schema)


@pytest.fixture
def production_model():
    _, model, value_graphs, evidence_graphs, details = content_connection_fixture(
        consumer="work", duplicate_use=True, observation=True)
    value_artifact = details["value_graph_artifact"]
    evidence_artifact = details["evidence_artifact"]
    fact = ProviderFactReference(model.snapshot.artifact, "production-fixture/fact")
    inventory_id = EvidenceInventoryID("production.inventory")
    source_ref = InventorySourceRef(inventory_id, "evidence/main")
    inventory = EvidenceInventoryBinding(
        inventory_id, RunID("production.run"),
        _artifact("memory:manifest", "scar.capture-manifest"),
        _artifact("memory:index", "scar.normalization-index"), fact)

    version = details["version"].version
    region = next(iter(value_graphs[value_artifact.sha256].regions))
    materialization = details["materialization"]
    evidence = evidence_graphs[evidence_artifact.sha256]
    operation_instance = next(iter(evidence.instances))
    endpoints = (
        EvidenceEndpoint(EvidenceNodeKind.VALUE_VERSION, version),
        EvidenceEndpoint(EvidenceNodeKind.MATERIALIZATION, materialization.materialization),
        EvidenceEndpoint(EvidenceNodeKind.OPERATION_INSTANCE, operation_instance),
        EvidenceEndpoint(EvidenceNodeKind.VALUE_OBSERVATION, "content.read.data"),
        EvidenceEndpoint(EvidenceNodeKind.OBJECT, ObjectID("production.endpoint.object")),
        EvidenceEndpoint(EvidenceNodeKind.ALLOCATION, StorageAllocationID("production.endpoint.alloc")),
        EvidenceEndpoint(EvidenceNodeKind.STORAGE_REGION, StorageRegionID("production.endpoint.region")),
        EvidenceEndpoint(EvidenceNodeKind.RESOURCE, ResourceID("production.endpoint.resource")),
        EvidenceEndpoint(EvidenceNodeKind.MEASUREMENT, MeasurementID("production.endpoint.measurement")),
        EvidenceEndpoint(EvidenceNodeKind.CONTROL_EVENT, "content.read"),
    )
    bridge_targets = (
        VersionRef(value_artifact, version),
        materialization,
        ObjectRef(evidence_artifact, ObjectID("production.object")),
        RegionRef(value_artifact, region),
        AllocationTarget(value_artifact, StorageAllocationID("production.alloc")),
    )
    bridges = tuple(SourceEndpointBridge(
        SourceBridgeID(f"production.bridge.{index}"),
        SourceEndpointRef(source_ref, endpoint),
        bridge_targets[index % len(bridge_targets)], fact)
        for index, endpoint in enumerate(endpoints))

    operation = model.operations[0].id
    value_occurrence = details["value"]
    raw = RawRecordRef(source_ref, 4, "b" * 64)
    source_edge = SourceEdgeRef(source_ref, "content.edge.produce")
    native_output = NativeOutputRef(NativeBoundaryID("production.native"), operation, 0)
    external = ExternalEstablishment(EvidencePoint(RunID("production.run"), None, fact))
    gap = Unresolved("fixture endpoint not captured", EvidencePoint(
        RunID("production.run"), None, MissingEvidence("fixture-only")))
    target = bridge_targets[-1]
    region_ref = RegionRef(value_artifact, region)
    writes = (
        WriteAssociation(WriteAssociationID("production.write.raw"), raw,
            WorkWrite(details["ticket"]), ValueProduction(value_occurrence),
            StorageContent(materialization, region_ref), (source_edge,), fact),
        WriteAssociation(WriteAssociationID("production.write.edge"), source_edge,
            HostWrite(operation), StateProduction(AccessRef(operation, 0)),
            EndpointContent(materialization, target, ProtocolSelector(fact)),
            (source_edge,), fact),
        WriteAssociation(WriteAssociationID("production.write.native"), native_output,
            external, gap, gap, (), fact),
        WriteAssociation(WriteAssociationID("production.write.unknown"), gap,
            gap, gap, gap, (), fact),
    )
    outcomes = (
        OutcomeProduction(OutcomeProductionID("production.outcome.region"), writes[0].id,
            WorkOutcomeID("production.work.outcome"), 0, region_ref, BytePrefixWrite(), fact),
        OutcomeProduction(OutcomeProductionID("production.outcome.protocol"), writes[1].id,
            WorkOutcomeID("production.work.outcome.unknown"), gap, ProtocolSelector(fact),
            gap, fact),
        OutcomeProduction(OutcomeProductionID("production.outcome.none"), writes[2].id,
            WorkOutcomeID("production.work.outcome.none"), None, gap, BytePrefixWrite(), fact),
    )
    return replace(model, source_inventories=(inventory,), source_bridges=bridges,
                   writes=writes, produced=outcomes)


def _fields(document):
    return document["model"]["fields"]


def test_v5_roundtrip_reaches_all_production_records_and_target_variants(production_model):
    document = to_dict(production_model)
    assert document["schema_version"] == 5
    assert SCHEMA_VERSION >= 5
    assert all(_fields(document)[field] for field in PRODUCTION_FIELDS)
    restored = loads(dumps(production_model))
    assert restored == production_model
    assert dumps(restored) == dumps(production_model)
    assert tuple(type(row) for row in restored.source_bridges) == (
        SourceEndpointBridge,) * len(restored.source_bridges)
    assert type(restored.source_bridges[0].target.version) is ValueVersionID
    assert type(restored.source_bridges[1].endpoint.endpoint.reference) is MaterializationID
    assert tuple(type(row.endpoint.endpoint.reference) for row in restored.source_bridges) == (
        ValueVersionID, MaterializationID, OperationInstanceID, str, ObjectID,
        StorageAllocationID, StorageRegionID, ResourceID, MeasurementID, str)
    assert type(restored.writes[0].writer) is WorkWrite
    assert type(restored.writes[1].writer) is HostWrite
    assert type(restored.writes[2].writer) is ExternalEstablishment
    assert type(restored.writes[1].production) is StateProduction
    assert type(restored.produced[0].rule) is BytePrefixWrite
    assert restored.produced[1].frontier is not None


def test_v4_golden_from_immutable_old_codec_is_byte_exact():
    payload = (FIXTURES / "execution_v4_frozen.json").read_bytes()
    proof = json.loads((FIXTURES / "execution_v4_frozen.json.proof.json").read_text())
    assert proof["source_revision"] == "5ab22f8d8fcbabbc59d494b571651d480468f3d5"
    assert proof["wire_schema_version"] == 4
    assert proof["payload_sha256"] == hashlib.sha256(payload).hexdigest()
    assert proof["payload_size_bytes"] == len(payload)
    model = loads(payload.decode())
    assert all(getattr(model, name) == () for name in PRODUCTION_FIELDS)
    assert to_dict(model)["schema_version"] == 4
    assert dumps(model).encode() == payload


@pytest.mark.parametrize("field", PRODUCTION_FIELDS)
def test_each_production_table_selects_v5_and_cannot_be_downgraded(production_model, field):
    model = replace(production_model, **{
        name: getattr(production_model, name) if name == field else ()
        for name in PRODUCTION_FIELDS
    })
    assert to_dict(model)["schema_version"] == 5
    assert loads(dumps(model)) == model
    for version in (1, 2, 3, 4):
        with pytest.raises(ValueError, match="production capability"):
            dumps(model, schema_version=version)


def test_explicit_v5_with_empty_production_tables_does_not_upgrade_default():
    model = content_connection_fixture(consumer="work", duplicate_use=True,
                                       observation=True)[1]
    doc = to_dict(model, schema_version=5)
    assert all(_fields(doc)[name] == [] for name in PRODUCTION_FIELDS)
    assert loads(dumps(model, schema_version=5)) == model
    restored = from_dict(doc)
    assert to_dict(restored)["schema_version"] == 4


@pytest.mark.parametrize("field", PRODUCTION_FIELDS)
def test_v1_v4_wire_rejects_explicit_production_table_fields(field):
    for version in (1, 2, 3, 4):
        payload = (FIXTURES / f"execution_v{version}_frozen.json").read_text()
        document = json.loads(payload)
        _fields(document)[field] = []
        with pytest.raises(ValueError, match="missing or unknown fields"):
            from_dict(document)


def test_p_tags_are_absent_from_v1_v4_vocabulary():
    old_payload = json.loads((FIXTURES / "execution_v4_frozen.json").read_text())
    fields = _fields(old_payload)
    fields["runs"][0]["fields"]["source"] = {
        "$record": "scar.ir.execution.production.EvidenceInventoryBinding",
        "fields": {},
    }
    with pytest.raises(ValueError, match="unknown type tag"):
        from_dict(old_payload)


def test_production_wire_rejects_malformed_new_nested_fields(production_model):
    document = to_dict(production_model)
    inventory = _fields(document)["source_inventories"][0]
    inventory["fields"]["run"]["kind"] = "exec_work_ticket"
    with pytest.raises(ValueError):
        from_dict(document)

    document = to_dict(production_model)
    source_endpoint = _fields(document)["source_bridges"][2]["fields"]["endpoint"]["fields"]["endpoint"]
    source_endpoint["fields"]["reference"]["kind"] = "wrong"
    with pytest.raises(ValueError):
        from_dict(document)

    document = to_dict(production_model)
    resource_endpoint = _fields(document)["source_bridges"][7]["fields"]["endpoint"]["fields"]["endpoint"]
    reference = resource_endpoint["fields"]["reference"]
    reference["$id"] = "scar.ir.v2.ids.OperationInstanceID"
    reference["kind"] = "opinst"
    reference["value"] = "wrong-kind"
    reference["wire"] = "opinst:wrong-kind"
    with pytest.raises(ValueError):
        from_dict(document)

    document = to_dict(production_model)
    resource_endpoint = _fields(document)["source_bridges"][7]["fields"]["endpoint"]["fields"]["endpoint"]
    resource_endpoint["fields"]["reference"]["$id"] = "untrusted.CustomIdentifier"
    with pytest.raises(ValueError, match="unknown type tag"):
        from_dict(document)


def test_schema_version_six_remains_unsupported(production_model):
    # Keep the historical case ID; the next unsupported capability moved to 7.
    for value in (7, True, "5"):
        with pytest.raises(ValueError, match="schema_version"):
            dumps(production_model, schema_version=value)
        doc = to_dict(production_model)
        doc["schema_version"] = value
        with pytest.raises(ValueError, match="schema_version"):
            from_dict(doc)

