"""G3 captures and G4 attested identities remain distinct, linked records."""
import torch

from scar.ir.frontend_v2 import build_semantic
from scar.ir.v2 import EvidenceClaim, EvidenceKind, ValueSlotID, canonical_json
from scar.trace.normalize_v2 import normalize_records
from scar.trace.values_v2 import TensorObserver


def test_legacy_tokens_do_not_merge_values_and_attestations_preserve_raw_graph(tmp_path):
    descriptor = {"object_id": "reused-token", "storage_id": "reused-address",
                  "logical_version": "legacy-same", "type": "Tensor", "shape": [4],
                  "strides": [1], "offset": 0, "dtype": "torch.float32", "device": "cpu"}
    records = [{"index": i, "kind": "module_call", "code_id": "generic:operation",
                "invocation_id": i, "ts_ns": 100 + i, "duration_ns": 1,
                "inputs": [descriptor], "outputs": [], "labels": [], "resource": {},
                "metadata": {}, "effects": {}} for i in range(2)]
    bundle = normalize_records(records).bundle
    observations = list(bundle.evidence.observations.values())
    assert len(observations) == 2
    assert observations[0].version != observations[1].version
    before = canonical_json(bundle.to_dict())
    source = tmp_path / "generic.py"
    source.write_text("def consume(value):\n    return value\n")
    semantic = build_semantic(source).graph
    observer = TensorObserver()
    handle = observer.observe(torch.arange(4, dtype=torch.float32))
    evidence = EvidenceClaim(EvidenceKind.DECLARED, ("fixture:explicit-capture-attestation",),
                             scope=observer.registry.scope)
    observer.registry.attach_observation(observations[0].observation_id, handle, evidence)
    observer.registry.bind_slot(next(iter(semantic.slots)), handle, evidence)
    assert observer.registry.validate_references(semantic=semantic, evidence=bundle.evidence) == []
    assert canonical_json(bundle.to_dict()) == before
    assert observer.registry.guard(handle).state.value == "NEEDS_VERIFICATION"


def test_dangling_external_attachment_and_slot_are_reported(tmp_path):
    observer = TensorObserver()
    handle = observer.observe(torch.zeros(2))
    evidence = EvidenceClaim(EvidenceKind.DECLARED, ("fixture:bad-attestation",), scope="run")
    observer.registry.attach_observation("absent-capture", handle, evidence)
    observer.registry.bind_slot(ValueSlotID("absent-slot"), handle, evidence)
    source = tmp_path / "generic.py"
    source.write_text("pass\n")
    semantic = build_semantic(source).graph
    execution = normalize_records([]).bundle.evidence
    errors = observer.registry.validate_references(semantic=semantic, evidence=execution)
    assert any("observation" in error for error in errors)
    assert any("slot" in error for error in errors)
