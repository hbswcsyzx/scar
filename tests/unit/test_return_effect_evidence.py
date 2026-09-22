"""Entry, exit and callback evidence retain their own scope and raw source."""
import hashlib
import json

import scar.ir.v2 as ir
from scar.trace.normalize_v2 import normalize_records


def event(kind, index, invocation=1, *, effect=None, inputs=(), outputs=(), **metadata):
    return {"kind": kind, "index": index, "ts_ns": index * 100,
            "duration_ns": None, "invocation_id": invocation,
            "code_id": f"fixture-function:{invocation}",
            "inputs": list(inputs), "outputs": list(outputs),
            "effect": effect or {}, "resource": {}, "labels": [],
            "metadata": {"process_id": 1, "thread_id": 2,
                         "clock_domain": "perf_counter", **metadata}}


def tensor():
    return {"object_id": "py:1:buffer", "storage_id": "storage:1:buffer",
            "logical_version": "storage:1:buffer@0:v0", "shape": [4],
            "strides": [1], "offset": 0, "dtype": "torch.float32", "device": "cpu"}


def test_paired_return_preserves_escape_evidence_without_replacing_entry_reads():
    value = tensor()
    entry_effect = {"reads": ["argument-token"], "collection_knowledge": {"reads": "UNKNOWN"}}
    exit_effect = {"escapes": [value["logical_version"]],
                   "collection_knowledge": {"escapes": "KNOWN"}, "external_effect": "UNKNOWN"}
    records = [event("python_call", 0, effect=entry_effect),
               event("python_return", 1, effect=exit_effect, outputs=[value],
                     return_escape_evidence="Observed", outcome="return")]
    result = normalize_records(records, source="fixture.jsonl")
    instance = next(iter(result.bundle.evidence.instances.values()))
    assert instance.metadata["legacy_effect"] == entry_effect
    boundary = instance.metadata["return_boundary"]
    assert boundary["legacy_effect"] == exit_effect
    assert boundary["raw_reference"] == "fixture.jsonl#L2"
    expected_bytes = (json.dumps(records[1], sort_keys=True, ensure_ascii=False) + "\n").encode()
    assert boundary["raw_sha256"] == hashlib.sha256(expected_bytes).hexdigest()
    assert boundary["return_escape_evidence"] == "Observed"
    assert boundary["effects_complete"] is False
    assert instance.metadata["effects_complete"] is False
    assert result.coverage["raw_records"] == result.coverage["accounted_records"] == 2
    assert len(result.bundle.evidence.instances) == 1


def test_callback_entry_and_return_descriptors_survive_round_trip():
    callback = {"object_id": "py:1:callback", "logical_version": "callback:opaque",
                "type": "function", "representation": "python_callable",
                "callable_code_id": "python-code:callback", "closure_names": ["captured"],
                "callable_capture": "UNKNOWN", "input_path": "callback"}
    records = [event("python_call", 0, inputs=[callback], callable_inputs=[callback],
                     callable_capture="UNKNOWN"),
               event("python_return", 1, returned_callables=[callback],
                     return_escape_evidence="UNKNOWN", outcome="return")]
    result = normalize_records(records)
    restored = ir.IRBundle.from_json(ir.canonical_json(result.bundle))
    instance = next(iter(restored.evidence.instances.values()))
    assert instance.metadata["callable_inputs"] == [callback]
    assert instance.metadata["callable_capture"] == "UNKNOWN"
    assert instance.metadata["return_boundary"]["returned_callables"] == [callback]
    assert instance.metadata["return_boundary"]["return_escape_evidence"] == "UNKNOWN"
    observation = next(iter(restored.evidence.observations.values()))
    hints = observation.metadata["legacy_hints"]
    assert hints["callable_code_id"] == callback["callable_code_id"]
    assert hints["closure_names"] == ["captured"]
    assert hints["callable_capture"] == "UNKNOWN"
    assert observation.metadata["logical_equivalence"] == "UNKNOWN"


def test_return_completion_tag_does_not_prove_exception_free_execution():
    result = normalize_records([event("python_call", 0),
                                event("python_return", 1, outcome="return")])
    instance = next(iter(result.bundle.evidence.instances.values()))
    assert instance.metadata["completion"] == "paired_return"
    assert instance.metadata["outcome"] == "return"
    assert instance.metadata["unknown_exception_status"] is True
    assert instance.metadata["return_boundary"]["unknown_exception_status"] is True
    assert instance.metadata["return_boundary"]["effects_complete"] is False


def test_unmatched_return_keeps_its_exit_boundary_and_callback_evidence():
    effect = {"escapes": ["opaque-return"], "collection_knowledge": {"escapes": "UNKNOWN"}}
    callback = {"object_id": "py:1:callback", "callable_code_id": "code:callback"}
    result = normalize_records([event("python_return", 0, effect=effect,
                                      returned_callables=[callback], return_escape_evidence="UNKNOWN")])
    instance = next(iter(result.bundle.evidence.instances.values()))
    assert instance.metadata["raw_kind"] == "unmatched_python_return"
    assert instance.metadata["legacy_effect"] == effect
    assert instance.metadata["return_boundary"]["legacy_effect"] == effect
    assert instance.metadata["return_boundary"]["returned_callables"] == [callback]
    assert result.coverage["status_counts"]["unmatched"] == 1


def test_nested_returns_keep_separate_invocation_boundaries():
    result = normalize_records([
        event("python_call", 0, 1),
        event("python_call", 1, 2, parent_invocation_id=1),
        event("python_return", 2, 2, effect={"escapes": ["child-value"]}),
        event("python_return", 3, 1, effect={"escapes": ["parent-value"]}),
    ])
    by_invocation = {item.metadata["legacy_invocation_id"]: item
                     for item in result.bundle.evidence.instances.values()}
    parent, child = by_invocation[1], by_invocation[2]
    assert child.parent == parent.id
    assert parent.metadata["return_boundary"]["legacy_effect"]["escapes"] == ["parent-value"]
    assert child.metadata["return_boundary"]["legacy_effect"]["escapes"] == ["child-value"]
    assert parent.metadata["return_boundary"]["raw_reference"] == "memory#L4"
    assert child.metadata["return_boundary"]["raw_reference"] == "memory#L3"


def test_missing_return_does_not_invent_empty_escape_evidence():
    result = normalize_records([event("python_call", 0)])
    instance = next(iter(result.bundle.evidence.instances.values()))
    assert instance.metadata["completion"] == "missing_return"
    assert "return_boundary" not in instance.metadata
    assert instance.metadata["unknown_exception_status"] is True
    assert instance.metadata["effects_complete"] is False
