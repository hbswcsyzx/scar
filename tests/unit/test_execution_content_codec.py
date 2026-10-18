"""D-layer declaration wire v4, without source/runtime or ready proof."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from scar.ir.execution.codec import SCHEMA_VERSION, dumps, from_dict, loads, to_dict
from scar.ir.execution.common import Unresolved
from scar.ir.execution.content import (
    ContentRead, DataIdentity, EndpointContent, EvidenceEdgeRef, EvidenceObservationRef,
    HostConsumer, NativeInputRef, NativeOutputRef, NativeWorkRead, ObjectIdentity, ObjectRef,
    ObservationConsumer, ProtocolInterval, ProtocolSelector, ResourceConsumer, StorageContent,
    ValueDenotation, VersionRef, WholeWorkRead, WorkEvidenceBinding,
)
from scar.ir.execution.coordinates import AccessRef, OccurrencePhase, OccurrencePoint, UseRef
from scar.ir.execution.coverage import RegionRef
from scar.ir.execution.ids import (
    ContentReadID, DenotationID, ObservationRequirementID, ObservationRootID, WorkEvidenceBindingID,
)
from scar.ir.execution.observations import (
    BoundEndpoint, ContractRef, ExternalEndpoint, ObservationRequirement, ObservationRoot,
    OutputValue, RequiredEndpoint, RequiredOutput,
)
from scar.ir.execution.resources import InstanceTarget
from scar.ir.execution.work import MaterializationRef
from scar.ir.program.ids import NativeBoundaryID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.v2.contracts import ContractFacet
from scar.ir.v2.ids import (
    ContractID, LogicalValueID, MaterializationID, ObjectID, OperationInstanceID,
    StorageRegionID, ValueSlotID, ValueVersionID,
)
from tests.fixtures.execution_order_graphs import event_order_execution


CONTENT_FIELDS = ("denotations", "work_evidence_bindings", "observation_requirements",
                  "observation_roots", "content_reads")
FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def content():
    # These are locally well-formed declaration examples, not an assertion that
    # the external IDs or native slots match collected source/runtime facts.
    program, model = event_order_execution(same_queue=False, with_wait=True)
    operation = model.operations[0].id
    core = next(row for row in program.operations if row.id == model.operations[0].operation)
    subject = UseRef(operation, core.uses[0].id)
    before = OccurrencePoint(operation, OccurrencePhase.BEFORE)
    after = OccurrencePoint(operation, OccurrencePhase.AFTER)
    gap = Unresolved("external denotation/source not collected", model.activations[0].entry)
    fact = ProviderFactReference(model.snapshot.artifact, "declared-content-protocol")
    values = ProviderArtifact("unavailable:values", "a" * 64, 1, "scar.ir.v2.values")
    evidence = ProviderArtifact("unavailable:evidence", "b" * 64, 1, "scar.ir.v2.evidence")
    semantics = ProviderArtifact("unavailable:semantics", "c" * 64, 1, "scar.ir.v2.semantic")
    interval = ProtocolInterval(before, after, fact, gap.point.source)
    denotation = ValueDenotation(DenotationID("content.data"), model.values[0].id,
        DataIdentity(VersionRef(values, ValueVersionID(LogicalValueID("logical"), 3))),
        EvidenceObservationRef(evidence, "observation"), fact)
    binding = WorkEvidenceBinding(WorkEvidenceBindingID("content.work"), model.submissions[0].id,
                                   evidence, OperationInstanceID("provider-instance"), fact)
    requirement = ObservationRequirement(ObservationRequirementID("content.requirement"),
        ContractRef(semantics, ContractID("contract")), RequiredOutput(ValueSlotID("output")), fact, fact)
    root = ObservationRoot(ObservationRootID("content.root"), requirement.id,
        OutputValue(model.values[0].id), interval, before, (model.values[0].id,), fact)
    read = ContentRead(ContentReadID("content.read"),
        ResourceConsumer(subject, WholeWorkRead(model.submissions[0].id), EvidenceEdgeRef(evidence, "input-edge")),
        StorageContent(MaterializationRef(values, MaterializationID("materialized")),
                       RegionRef(values, StorageRegionID("selector"))),
        AccessRef(operation, 0), before, (model.values[0].id,), denotation.basis, fact)
    return replace(model, denotations=(denotation,), work_evidence_bindings=(binding,),
                   observation_requirements=(requirement,), observation_roots=(root,), content_reads=(read,))


def _fields(document):
    return document["model"]["fields"]


def test_independently_archived_v3_event_work_wire_is_exact_and_old_bytes_unchanged():
    payload = (FIXTURES / "execution_v3_frozen.json").read_bytes()
    proof = json.loads((FIXTURES / "execution_v3_frozen.proof.json").read_text())
    assert proof["source_revision"] == "6efbe272bceb1036eba3725f11c47960fd5dd301"
    assert proof["codec_schema_version"] == proof["wire_schema_version"] == 3
    assert proof["payload_sha256"] == hashlib.sha256(payload).hexdigest()
    assert proof["payload_size_bytes"] == len(payload)
    assert SCHEMA_VERSION == 5
    model = loads(payload.decode())
    assert all(getattr(model, name) == () for name in CONTENT_FIELDS)
    assert dumps(model).encode() == dumps(model, schema_version=3).encode() == payload
    assert dumps(event_order_execution(same_queue=False, with_wait=True)[1]).encode() == payload
    for version in (1, 2):
        old = (FIXTURES / f"execution_v{version}_frozen.json").read_bytes()
        assert dumps(loads(old.decode())).encode() == old


def test_full_v4_roundtrip_preserves_original_typed_version_and_native_namespaces(content):
    document = to_dict(content)
    assert document["schema_version"] == 4
    restored = loads(dumps(content))
    assert restored == content and dumps(restored) == dumps(content)
    version = restored.denotations[0].identity.version.version
    assert type(version) is ValueVersionID
    assert type(version.logical_value) is LogicalValueID
    assert version.wire == "lv:logical@v3"
    wire = _fields(document)["denotations"][0]["fields"]["identity"]["fields"]["version"]["fields"]["version"]
    assert wire["$record"] == "scar.ir.v2.ids.ValueVersionID"
    assert wire["fields"]["logical_value"]["kind"] == "lv"
    assert type(restored.work_evidence_bindings[0].instance) is OperationInstanceID
    assert restored.work_evidence_bindings[0].instance != restored.operations[0].id


@pytest.mark.parametrize("field", CONTENT_FIELDS)
def test_each_content_table_alone_selects_v4_and_downgrade_cannot_drop_it(content, field):
    model = replace(content, **{name: getattr(content, name) if name == field else () for name in CONTENT_FIELDS})
    assert to_dict(model)["schema_version"] == 4
    assert loads(dumps(model)) == model
    for version in (1, 2, 3):
        with pytest.raises(ValueError, match="content capability"):
            dumps(model, schema_version=version)


def test_explicit_v4_empty_content_tables_do_not_invent_evidence_or_change_default_version():
    model = event_order_execution()[1]
    document = to_dict(model, schema_version=4)
    assert all(_fields(document)[name] == [] for name in CONTENT_FIELDS)
    assert from_dict(document) == model
    assert to_dict(from_dict(document))["schema_version"] == 3
    assert dumps(from_dict(document), schema_version=4) == dumps(model, schema_version=4)


@pytest.mark.parametrize("field", CONTENT_FIELDS)
def test_v4_requires_every_content_field_and_v1_v3_reject_even_empty_new_fields(content, field):
    document = to_dict(content)
    del _fields(document)[field]
    with pytest.raises(ValueError, match="missing or unknown fields"):
        from_dict(document)
    for version in (1, 2, 3):
        old = json.loads((FIXTURES / f"execution_v{version}_frozen.json").read_text())
        _fields(old)[field] = []
        with pytest.raises(ValueError, match="missing or unknown fields"):
            from_dict(old)


def test_content_tags_are_not_reachable_through_legacy_wire_vocabulary(content):
    tagged = _fields(to_dict(content))["denotations"][0]
    for version in (1, 2, 3):
        old = json.loads((FIXTURES / f"execution_v{version}_frozen.json").read_text())
        _fields(old)["runs"][0]["fields"]["source"] = deepcopy(tagged)
        with pytest.raises(ValueError, match="unknown type tag"):
            from_dict(old)


def test_denotation_native_reference_and_explicit_unknown_basis_variants_roundtrip(content):
    old = content.denotations[0]
    artifact = old.identity.version.artifact
    gap = Unresolved("source unavailable", content.activations[0].entry)
    bases = (EvidenceEdgeRef(artifact, "edge"),
             NativeInputRef(NativeBoundaryID("native"), content.visits[0].id, 2),
             NativeOutputRef(NativeBoundaryID("native"), content.operations[0].id, 3), gap)
    for identity in (ObjectIdentity(ObjectRef(artifact, ObjectID("object"))), gap):
        for basis in bases:
            model = replace(content, denotations=(replace(old, identity=identity, basis=basis),))
            assert loads(dumps(model)) == model


def test_host_nativework_and_observation_consumers_preserve_read_and_endpoint_variants(content):
    read = content.content_reads[0]
    interval = content.observation_roots[0].interval
    gap = Unresolved("unknown selector", content.activations[0].entry)
    target = InstanceTarget(content.resources[0].id)
    materialization = read.placement.materialization
    consumers = (HostConsumer(read.consumer.subject, interval),
                 ResourceConsumer(read.consumer.subject, NativeWorkRead(read.consumer.read.ticket, interval), gap),
                 ObservationConsumer(content.observation_roots[0].id))
    for consumer in consumers:
        for selector in (ProtocolSelector(interval.protocol), read.consumer.subject, read.effect, gap):
            model = replace(content, content_reads=(replace(read, consumer=consumer,
                placement=EndpointContent(materialization, target, selector), effect=None),))
            assert loads(dumps(model)) == model
    model = replace(content, content_reads=(replace(read, placement=gap, anchor=gap),))
    assert loads(dumps(model)) == model


def test_q_declared_output_endpoint_and_actual_root_variants_are_not_coerced(content):
    requirement = content.observation_requirements[0]
    root = content.observation_roots[0]
    gap = Unresolved("endpoint not mapped", content.activations[0].entry)
    targets = (RequiredEndpoint(content.requirements[0].requirement, ContractFacet.EXTERNAL),
               RequiredEndpoint(gap, ContractFacet.EXTERNAL))
    for target in targets:
        for actual in (BoundEndpoint(content.requirements[0].id),
                       ExternalEndpoint(InstanceTarget(content.resources[0].id)), gap):
            model = replace(content, observation_requirements=(replace(requirement, target=target),),
                             observation_roots=(replace(root, actual=actual),))
            assert loads(dumps(model)) == model


@pytest.mark.parametrize("corruption", ["missing-tag", "unknown-tag", "wrong-union", "bool-version", "extra-field"])
def test_nested_content_tag_or_type_forgery_is_rejected(content, corruption):
    document = to_dict(content)
    denotation = _fields(document)["denotations"][0]
    identity = denotation["fields"]["identity"]
    version = identity["fields"]["version"]["fields"]["version"]
    if corruption == "missing-tag":
        del identity["$record"]
    elif corruption == "unknown-tag":
        identity["$record"] = "attacker.Provider"
    elif corruption == "wrong-union":
        denotation["fields"]["identity"] = deepcopy(_fields(document)["content_reads"][0]["fields"]["consumer"])
    elif corruption == "bool-version":
        version["fields"]["version"] = True
    else:
        version["fields"]["verified"] = True
    with pytest.raises(ValueError):
        from_dict(document)


def test_private_mutation_cannot_hide_capability_or_create_false_typed_values(content):
    object.__setattr__(content, "content_reads", [])
    with pytest.raises(ValueError):
        dumps(content)


def test_codec_never_resolves_catalogs_or_opens_provider_artifacts(content, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("codec may not resolve external graphs or execute providers")
    monkeypatch.setattr("scar.ir.execution.snapshot.ExternalSnapshots.graph", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    assert loads(dumps(content)) == content


def test_versions_stay_exact_and_unsupported_versions_still_fail(content):
    for version in (True, 0, 6, "4"):
        with pytest.raises(ValueError, match="schema_version"):
            dumps(content, schema_version=version)
        document = to_dict(content)
        document["schema_version"] = version
        with pytest.raises(ValueError, match="schema_version"):
            from_dict(document)
