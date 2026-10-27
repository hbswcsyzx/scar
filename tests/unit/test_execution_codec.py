"""Tagged execution wire validates records, without claiming graph/runtime proof."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from scar.ir.execution.codec import (
    SCHEMA, SCHEMA_VERSION, dumps, from_dict, loads, to_dict,
)
from scar.ir.execution.common import Unresolved
from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint, UseRef
from scar.ir.execution.ids import (
    NativeHandleLifetimeID, OperationOccurrenceID, ResourceBindingID,
)
from scar.ir.execution.model import ExecutionModel, LegacyOperationRef, OccurrenceEvidenceBinding
from scar.ir.execution.resources import (
    ActivationHolder, CapacityAt, ConstraintEvidence, EndedAt,
    HandleHolder, ObjectHandle, ObjectHolder, OwnershipClaim,
    ProtocolCondition, ProtocolRight, RelationAt, ReleaseAuthority, RightsClaim,
    Sharing, TargetHolder,
)
from scar.ir.program.ids import ResourceRequirementID, UseID, ValueID
from scar.ir.program.providers import ProviderFactReference
from scar.ir.v2.common import Completeness
from scar.ir.v2.ids import ObjectID, OperationInstanceID, StorageAllocationID
from tests.fixtures.execution_resource_graphs import (
    resource_execution_program, resource_execution_with_allocation,
)


@pytest.fixture(scope="module")
def base():
    return resource_execution_program()[1]


def _fields(document):
    return document["model"]["fields"]


@pytest.mark.parametrize("options", [
    {}, {"external": True}, {"implicit": True}, {"native_handles": True},
])
def test_canonical_resource_fixtures_roundtrip_without_collapsing_ids(options):
    _, model = resource_execution_program(**options)
    payload = dumps(model)
    restored = loads(payload)
    assert restored == model
    assert dumps(restored) == payload
    assert type(restored.values[0].value) is ValueID
    assert type(restored.operations[0].id) is OperationOccurrenceID
    assert restored.resources[0].id != restored.resources[1].id
    assert to_dict(model)["schema"] == SCHEMA == "scar.execution-model"
    assert to_dict(model)["schema_version"] == 1  # No work capability retains original v1 bytes.
    assert SCHEMA_VERSION >= 5
    if options.get("native_handles"):
        assert type(restored.handles[1].handle) is type(model.handles[1].handle)
        assert restored.handles[1].target == restored.handles[2].target
        assert restored.handles[1].handle.lifetime != restored.handles[2].handle.lifetime


def test_allocation_target_preserves_original_v2_allocation_namespace():
    _, model, _ = resource_execution_with_allocation()
    restored = from_dict(to_dict(model))
    assert restored == model
    allocation = restored.placements[0].allocation.allocation
    assert type(allocation) is StorageAllocationID
    assert allocation.wire == "alloc:resource.storage"
    wire = _fields(to_dict(model))["placements"][0]["fields"]["allocation"]["fields"]["allocation"]
    assert wire == {"$id": "scar.ir.v2.ids.StorageAllocationID", "kind": "alloc",
                    "value": "resource.storage", "wire": "alloc:resource.storage"}


def test_deep_rights_ownership_constraints_and_legacy_evidence_are_tagged(base):
    point = base.activations[0].entry
    fact = ProviderFactReference(base.snapshot.artifact, "/declaration")
    gap = Unresolved("not observed", point)
    support = base.handles[0].support
    namespace = base.handles[0].target
    handle = ObjectHandle(base.values[0].id, base.snapshot.artifact, ObjectID("wrapper"), fact)
    owners = (
        ObjectHolder(base.snapshot.artifact, ObjectID("holder")),
        HandleHolder(NativeHandleLifetimeID("fd")),
        ActivationHolder(base.activations[0].id), TargetHolder(namespace),
    )
    binding = replace(base.handles[0], handle=handle,
        rights=RightsClaim((ProtocolRight(fact, fact),), Completeness.PARTIAL, support, fact),
        ownership=tuple(OwnershipClaim(holder, ReleaseAuthority.BORROWED, Sharing.SHARED,
                                       support, fact) for holder in owners),
        end=EndedAt(OccurrencePoint(base.operations[0].id, OccurrencePhase.EDGE, 0), fact))
    requirement = ResourceRequirementID("declared")
    refs = (CapacityAt(requirement, 0), RelationAt(requirement, 1, ResourceBindingID("related")),
            ProtocolCondition(fact, fact, (UseRef(base.operations[0].id, UseID("use")),)))
    access = replace(base.accesses[0], constraints=tuple(
        ConstraintEvidence(ref, support, fact) for ref in refs), handle=gap)
    legacy = OccurrenceEvidenceBinding(base.operations[0].id,
        LegacyOperationRef(base.snapshot.artifact, OperationInstanceID("legacy")), fact)
    model = replace(base, handles=(binding,), accesses=(access,), evidence_bindings=(legacy,))
    restored = loads(dumps(model))
    assert restored == model
    assert type(restored.handles[0].handle.object) is ObjectID
    assert type(restored.evidence_bindings[0].legacy.instance) is OperationInstanceID
    assert restored.evidence_bindings[0].legacy.instance != restored.operations[0].id
    assert type(restored.handles[0].rights.completeness) is Completeness
    assert type(restored.handles[0].ownership[0].sharing) is Sharing


def test_codec_does_not_open_artifacts_or_perform_graph_validation(base, monkeypatch):
    import scar.ir.execution.validation as validation

    def forbidden(*args, **kwargs):
        raise AssertionError("codec must not resolve/validate graph or artifacts")

    monkeypatch.setattr(validation, "validate", forbidden)
    # This occurrence points to a missing visit: a local record is valid,
    # although a separate graph validation must reject the foreign key.
    from scar.ir.execution.ids import BlockVisitID
    model = replace(base, operations=(replace(base.operations[0], visit=BlockVisitID("missing")),))
    monkeypatch.setattr("builtins.open", forbidden)
    assert loads(dumps(model)) == model


@pytest.mark.parametrize("mutation", [
    "missing-envelope", "extra-envelope", "missing-default-table", "extra-record",
    "unknown-record", "missing-record-tag", "forged-union", "wrong-tag-family",
    "bad-id-kind", "bad-id-wire", "wrong-id-class", "bad-enum-class", "bad-enum-value",
    "primitive-enum", "kind-role-invariant", "bool-version", "bool-index", "tuple-not-json-array",
])
def test_wire_rejects_missing_extra_tags_union_and_type_forgery(base, mutation):
    document = to_dict(base)
    fields = _fields(document)
    if mutation == "missing-envelope":
        del document["schema"]
    elif mutation == "extra-envelope":
        document["runtime_verified"] = True
    elif mutation == "missing-default-table":
        del fields["transfers"]
    elif mutation == "extra-record":
        fields["resources"][0]["fields"]["ready"] = True
    elif mutation == "unknown-record":
        document["model"]["$record"] = "arbitrary.module.ExecutionModel"
    elif mutation == "missing-record-tag":
        del fields["handles"][0]["$record"]
    elif mutation == "forged-union":
        # ProcessRealm is a known record, but cannot be a ResourceTarget.
        fields["handles"][0]["fields"]["target"] = deepcopy(fields["resources"][0]["fields"]["realm"])
    elif mutation == "wrong-tag-family":
        origin = fields["resources"][0]["fields"]["origin"]
        origin["$enum"] = origin.pop("$record")
    elif mutation in ("bad-id-kind", "bad-id-wire", "wrong-id-class"):
        identity = fields["values"][0]["fields"]["value"]
        if mutation == "bad-id-kind":
            identity["kind"] = "exec_value_occurrence"
        elif mutation == "bad-id-wire":
            identity["wire"] += ".forged"
        else:
            identity["$id"] = "scar.ir.execution.ids.ValueOccurrenceID"
    elif mutation in ("bad-enum-class", "bad-enum-value", "primitive-enum"):
        resource = fields["resources"][0]["fields"]
        if mutation == "bad-enum-class":
            resource["role"]["$enum"] = "scar.ir.v2.contracts.ResourceKind"
        elif mutation == "bad-enum-value":
            resource["role"]["value"] = "PROVEN"
        else:
            resource["role"] = "OPEN_FILE_DESCRIPTION"
    elif mutation == "kind-role-invariant":
        fields["resources"][0]["fields"]["kind"]["value"] = "GPU"
    elif mutation == "bool-version":
        document["schema_version"] = True
    elif mutation == "bool-index":
        fields["handles"][0]["fields"]["start"]["fields"]["successor_index"] = True
    elif mutation == "tuple-not-json-array":
        fields["resources"] = tuple(fields["resources"])
    with pytest.raises(ValueError):
        from_dict(document)


@pytest.mark.parametrize("payload", [
    '{"schema":"scar.execution-model","schema":"scar.execution-model"}',
    '{"outer":{"key":0,"key":1}}',
    '{"bad":NaN}', '{"bad":Infinity}', '{"bad":-Infinity}',
])
def test_loads_rejects_duplicate_keys_and_nonfinite_json(payload):
    with pytest.raises(ValueError):
        loads(payload)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_from_dict_and_encoder_reject_nonfinite_values(base, bad):
    document = to_dict(base)
    _fields(document)["snapshot"]["fields"]["artifact"]["fields"]["size_bytes"] = bad
    with pytest.raises(ValueError):
        from_dict(document)
    model = deepcopy(base)
    object.__setattr__(model.snapshot.artifact, "size_bytes", bad)
    with pytest.raises(ValueError):
        dumps(model)


@pytest.mark.parametrize("mutation", ["deep-artifact", "raw-enum", "wrong-tuple", "wrong-id", "id-prefix", "subclass"])
def test_encoder_rechecks_private_nested_mutation_and_exact_variants(base, mutation):
    model = deepcopy(base)
    if mutation == "deep-artifact":
        object.__setattr__(model.snapshot.artifact, "size_bytes", True)
    elif mutation == "raw-enum":
        object.__setattr__(model.resources[0], "role", "OPEN_FILE_DESCRIPTION")
    elif mutation == "wrong-tuple":
        object.__setattr__(model, "resources", list(model.resources))
    elif mutation == "wrong-id":
        object.__setattr__(model.runs[0].id, "value", False)
    elif mutation == "id-prefix":
        object.__setattr__(model.runs[0].id, "prefix", "not-original-namespace")
    else:
        class DerivedModel(ExecutionModel):
            pass
        model = DerivedModel(model.snapshot)
    with pytest.raises(ValueError):
        to_dict(model)


def test_wrong_root_types_are_rejected_and_json_is_deterministic(base):
    assert json.loads(dumps(base)) == to_dict(base)
    for value in (None, [], "not-model", 1):
        with pytest.raises(ValueError):
            to_dict(value)
        with pytest.raises(ValueError):
            from_dict(value)
    with pytest.raises(ValueError):
        loads(dumps(base).encode())
