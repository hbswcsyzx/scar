"""Execution owners may name an object without inventing its contents."""
from dataclasses import replace

import pytest

from scar.ir.execution.content import ObjectIdentity, ObjectRef
from scar.ir.execution.ids import (
    EvidenceInventoryID, RunID, ValueOccurrenceID,
)
from scar.ir.execution.production import InventorySourceRef, SourceEndpointRef
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.inventory import ResolvedSource
from scar.ir.execution.resources import (
    ObjectHandle, ObjectHolder, OwnershipClaim, ReleaseAuthority, Sharing,
)
from scar.ir.execution.snapshot import external_artifact
from scar.ir.execution.validation import validate as validate_execution
from scar.ir.v2.common import EvidenceClaim, EvidenceKind
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceGraph
from scar.ir.v2.evidence import EvidenceNodeKind as N
from scar.ir.v2.ids import ObjectID
from scar.ir.v2.schemas import IRBundle
from scar.ir.v2.semantic import SemanticGraph
from scar.ir.v2.values import ObjectInstance, ValueGraph
from scar.ir.execution.source_validation import resolve_endpoint, target_original
from scar.ir.execution.production import EvidenceInventoryBinding
from scar.ir.execution.common import MissingEvidence
from tests.fixtures.execution_frame_identity_graphs import frame_identity_execution
from tests.fixtures.execution_resource_graphs import resource_execution_program


_CLAIM = EvidenceClaim(
    EvidenceKind.OBSERVED, ("execution-object-registry-fixture",),
    scope="fixture:process:1",
)


def _objects(*identities):
    graph = ValueGraph()
    instances = []
    for identity in identities:
        instance = ObjectInstance(
            identity, "fixture:process:1", (_CLAIM,), {"observation": "weakref"},
        )
        graph.add_object(instance)
        instances.append(instance)
    assert graph.logical_values == graph.versions == graph.materializations == {}
    assert graph.bindings == []
    return graph, tuple(instances)


def test_bundle_object_owner_is_valid_without_a_logical_version_and_unknown_object_fails():
    identity = ObjectID("bundle.object")
    values, _instances = _objects(identity)
    evidence = EvidenceGraph()
    endpoint = EvidenceEndpoint(N.OBJECT, identity)
    evidence.register_external(endpoint)

    assert IRBundle(SemanticGraph(), evidence, values).validate()["valid"] is True
    missing = IRBundle(SemanticGraph(), evidence, ValueGraph()).validate()
    assert not missing["valid"]
    assert any("external reference object:" in issue for issue in missing["errors"])


def test_object_ref_content_and_identity_queries_use_object_directory_and_recheck_metadata():
    program, model, details = frame_identity_execution(instances=2, retry=True)
    assignments = details["object_assignments"]
    values, instances = _objects(*sorted(set(assignments.values()), key=lambda item: item.wire))
    artifact = external_artifact(values, "memory:execution-object-directory")
    denotations = tuple(
        replace(row, identity=ObjectIdentity(ObjectRef(artifact, assignments[row.value])))
        if row.value in assignments else row
        for row in model.denotations
    )
    changed = replace(model, denotations=denotations)
    catalogs = {artifact.sha256: values}
    report = validate_execution(
        changed, program, value_graphs=catalogs,
        evidence_graphs=details["evidence_graphs"],
    )
    assert report.valid, report.issues
    index = ExecutionIndex(
        changed, program, value_graphs=catalogs,
        evidence_graphs=details["evidence_graphs"],
    )
    first = details["frame_identities"][0]
    left = first["publication_owners"][-1].id
    right = first["read_value"].id

    complete = index.object_identity(left, right)
    assert complete["match"] is True
    assert all(row["registered"] is True for row in complete["inventory"])
    assert complete["budget"]["costs"]["object_identity_registry_objects"] == 2

    # Both endpoint records stay visible even when the second object-directory
    # lookup or an earlier identity-query phase exhausts the shared budget.
    limited = index.object_identity(left, right, budget=9)
    assert tuple(row["value"].id for row in limited["inventory"]) == (left, right)
    assert limited["match"] is None and limited["status"] == "UNPROVED"
    assert limited["cursor"]["phase"] == "registry_objects"
    tiny = index.object_identity(left, right, budget=1)
    assert tuple(row["value"].id for row in tiny["inventory"]) == (left, right)
    assert tiny["match"] is None and tiny["status"] == "UNPROVED"

    unknown = ObjectID("frame.identity.not-registered")
    first_read = first["read_value"].id
    missing_denotations = tuple(
        replace(row, identity=ObjectIdentity(ObjectRef(artifact, unknown)))
        if row.value == first_read else row
        for row in changed.denotations
    )
    missing_report = validate_execution(
        replace(changed, denotations=missing_denotations), program,
        value_graphs=catalogs, evidence_graphs=details["evidence_graphs"],
    )
    assert any(issue.code == "content_object" for issue in missing_report.issues)

    # The artifact snapshot covers mutable registry metadata too.
    instances[0].metadata["changed-after-index"] = True
    with pytest.raises(ValueError, match="external_snapshot|snapshot"):
        index.object_identity(left, right)


def test_object_handle_and_object_holder_accept_registered_reference_without_versions():
    program, model = resource_execution_program(activations=1)
    identity = ObjectID("resource.object")
    values, _instances = _objects(identity)
    artifact = external_artifact(values, "memory:resource-object-directory")
    binding = model.handles[0]
    handle_value = ValueOccurrenceID("activation.0.resource.handle")
    owner = ObjectHolder(artifact, identity)
    ownership = OwnershipClaim(
        owner, ReleaseAuthority.UNKNOWN, Sharing.UNKNOWN,
        binding.support, binding.source,
    )
    endpoint = ObjectHandle(handle_value, artifact, identity, binding.source)
    changed_binding = replace(binding, handle=endpoint, ownership=(ownership,))
    changed = replace(model, handles=(changed_binding,))
    report = validate_execution(
        changed, program, value_graphs={artifact.sha256: values},
    )
    assert report.valid, report.issues
    assert values.versions == values.materializations == {}

    absent_values = ValueGraph()
    absent_artifact = external_artifact(absent_values, "memory:empty-object-directory")
    absent_binding = replace(
        binding,
        handle=ObjectHandle(handle_value, absent_artifact, identity, binding.source),
        ownership=(OwnershipClaim(
            ObjectHolder(absent_artifact, identity), ReleaseAuthority.UNKNOWN,
            Sharing.UNKNOWN, binding.support, binding.source,
        ),),
    )
    absent_report = validate_execution(
        replace(model, handles=(absent_binding,)), program,
        value_graphs={absent_artifact.sha256: absent_values},
    )
    issue_codes = {issue.code for issue in absent_report.issues}
    assert "resource_object_handle_identity" in issue_codes
    assert "resource_ownership_holder" in issue_codes


class _ResolverContext:
    def __init__(self, inventory, stream, source, values, values_artifact):
        self.source_inventories = {inventory.id: inventory}
        self.inventory_sources = {(inventory.id, stream): source}
        self.source_resolutions = {}
        self.values = values
        self.values_artifact = values_artifact
        self.issues = []
        self.gaps = []

    def issue(self, code, path, message):
        self.issues.append((code, path, message))

    def gap(self, code, path, message):
        self.gaps.append((code, path, message))

    def external_values(self, artifact, path):
        if artifact == self.values_artifact:
            return self.values
        self.issue("external_graph_type", path, "unexpected values artifact")
        return None


def test_source_object_endpoint_stays_an_object_facet_and_does_not_select_contents():
    identity = ObjectID("source.object")
    values, instances = _objects(identity)
    evidence = EvidenceGraph()
    endpoint = EvidenceEndpoint(N.OBJECT, identity)
    evidence.register_external(endpoint)
    values_artifact = external_artifact(values, "memory:source-object-values")
    evidence_artifact = external_artifact(evidence, "memory:source-object-evidence")
    semantic = SemanticGraph()
    semantic_artifact = external_artifact(semantic, "memory:source-object-semantic")
    bundle = IRBundle(semantic, evidence, values)
    assert bundle.validate()["valid"] is True
    inventory_id = EvidenceInventoryID("source.object.inventory")
    stream = "evidence/main"
    missing = MissingEvidence("source fixture declaration")
    inventory = EvidenceInventoryBinding(
        inventory_id, RunID("source.object.run"), values_artifact,
        values_artifact, missing,
    )
    source = ResolvedSource(
        stream, evidence_artifact, (), bundle, evidence_artifact,
        values_artifact, semantic_artifact, True,
    )
    context = _ResolverContext(inventory, stream, source, values, values_artifact)
    reference = SourceEndpointRef(InventorySourceRef(inventory_id, stream), endpoint)

    resolved = resolve_endpoint(context, reference, "source_endpoint")
    assert resolved["object"] == identity
    assert resolved["value_version"] is None
    assert resolved["materialization"] is None
    assert resolved["region"] is None
    assert resolved["allocation"] is None
    assert context.issues == []

    target = target_original(context, ObjectRef(values_artifact, identity), "target")
    assert target["facet"] == "object"
    assert target["original"] is instances[0]
    unknown = target_original(
        context, ObjectRef(values_artifact, ObjectID("source.not-registered")), "unknown_target",
    )
    assert unknown is None
    assert any(code == "inventory_bridge_target" for code, _path, _message in context.issues)
