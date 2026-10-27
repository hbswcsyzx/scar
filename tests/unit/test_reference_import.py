"""Exact marker references add no contents, alias or direct-call assertions."""
from copy import deepcopy
import gzip
import json
import subprocess
import sys

import pytest

from scar.ir.v2 import bundle_from_dict, EvidenceKind, EvidenceRelation
from scar.ir.v2.codec import evidence_from_dict
from scar.trace.reference_import import RESEARCH_PROFILE, import_reference_bridge
from tests.unit.test_native_import import REVISION, _node, _slots


def _documents():
    name = "scar-observation:" + "a" * 32 + ":42:1:"
    tensor = [100, 200, 0, 4, 4, "cpu"]
    view = [101, 200, 0, 4, 4, "cpu"]
    eto = {"schema": "1.1.1-chakra.0.0.4", "pid": 42, "nodes": [
        _node(3, name + "input", 2, 11, _slots([tensor, tensor], ["Tensor(float)"] * 2)),
        _node(4, name + "output", 2, 12, _slots([view], ["Tensor(float)"])),
        _node(2, "provider-wrapper", 1, 10),
        _node(1, "[pytorch|profiler|execution_trace|process]", 1, 0)]}
    context = {"invocation": 1, "code": "code", "source_file": "/case.py", "bytecode_offset": 12,
               "kind": "retained ancestor context, not a proven direct caller"}
    markers = [{"name": name + "input", "sequence": 1, "phase": "input", "context": context,
                "tensor_references": [{"path": [0, 0], "ref": "weak:42:1"},
                                      {"path": [0, 1], "ref": "weak:42:1"}]},
               {"name": name + "output", "sequence": 1, "phase": "output", "context": context,
                "tensor_references": [{"path": [], "ref": "weak:42:2"}]}]
    calls = [{"index": 1, "kind": "call_enter", "process_id": 42, "thread_id": 43,
              "invocation_id": 1, "code": "code"},
             {"index": 2, "kind": "call_exit", "process_id": 42, "thread_id": 43,
              "invocation_id": 1, "code": "code"}]
    codes = [{"key": "code", "filename": "/case.py"}]
    meta = {"schema": "scar.call-edge-trace", "schema_version": 1, "process_id": 42,
            "events": 2, "codes": 1, "dropped_events": 0, "dropped_codes": 0,
            "open_invocations": 0, "active_frames": 0, "io_failed": False, "errors": []}
    return [eto, markers, calls, codes, meta]


def _import(tmp_path, docs=None, **kwargs):
    docs = _documents() if docs is None else docs
    paths = [tmp_path / name for name in ("eto.json", "markers.json", "calls.jsonl", "codes.jsonl", "meta.json")]
    for index, (path, doc) in enumerate(zip(paths, docs, strict=True)):
        path.write_text("\n".join(json.dumps(row) for row in doc) if index in (2, 3) else json.dumps(doc))
    return import_reference_bridge(*paths, reference_profile=RESEARCH_PROFILE,
                                   provider_revision=REVISION, **kwargs)


def test_flattened_duplicate_slots_and_output_marker_arguments_remain_distinct(tmp_path):
    result = _import(tmp_path)
    assert result.bundle.assert_valid()["valid"]
    assert len(result.bundle.values.objects) == 2
    assert not result.bundle.values.versions and not result.bundle.values.bindings
    assert not result.bundle.values.allocations and not result.bundle.values.materializations
    assert not result.report["kineto_supplied"]
    assert any(gap["code"] == "kineto_not_supplied" for gap in result.report["gaps"])
    edges = [edge for edge in result.bundle.evidence.edges.values()
             if edge.relation is EvidenceRelation.OBJECT_REFERENCE_ASSOCIATION]
    assert len(edges) == 3 and edges[0].source == edges[1].source
    assert all(edge.evidence.kind is EvidenceKind.INFERRED for edge in edges)
    relations = {edge.relation for edge in result.bundle.evidence.edges.values()}
    assert not relations & {EvidenceRelation.ALIASES, EvidenceRelation.PRODUCES,
                           EvidenceRelation.HAPPENS_BEFORE, EvidenceRelation.MATERIALIZES}
    paths = result.report["reference_bridge"]["paths"]
    assert paths[0]["original_payload_path"] == [0, 0]
    assert paths[0]["provider_argument_ordinal"] == 0
    assert paths[-1]["marker_phase"] == "output" and paths[-1]["provider_role"] == "inputs"
    wire = result.bundle.to_dict()
    assert wire["values"]["schema_version"] == 2
    assert wire["evidence"]["schema_version"] == 6
    assert bundle_from_dict(deepcopy(wire)).to_dict() == wire
    for version in (3, 4, 5):
        old = deepcopy(wire["evidence"])
        old["schema_version"] = version
        with pytest.raises(ValueError):
            evidence_from_dict(old)


@pytest.mark.parametrize("mutation", ["eto_duplicate", "row_duplicate", "missing_node", "missing_phase",
    "wrong_process", "snapshot", "duplicate_path", "reordered_phase", "wrong_code", "wrong_file",
    "missing_tensor", "bad_descriptor", "bool_index", "direct_context", "unaccounted_marker",
    "lossy_meta", "duplicate_call", "duplicate_code", "mixed_nonce", "missing_inputs", "non_array_inputs"])
def test_ambiguous_incomplete_or_unscoped_references_are_rejected(tmp_path, mutation):
    eto, markers, calls, codes, meta = docs = _documents()
    if mutation == "eto_duplicate":
        eto["nodes"].append({**deepcopy(eto["nodes"][0]), "id": 99})
    elif mutation == "row_duplicate":
        markers.append(deepcopy(markers[0]))
    elif mutation == "missing_node":
        eto["nodes"].pop(0)
    elif mutation == "missing_phase":
        markers.pop()
    elif mutation == "wrong_process":
        meta["process_id"] = 43
    elif mutation == "snapshot":
        markers[0]["tensor_references"][0]["ref"] = "snapshot:42:1:2"
    elif mutation == "duplicate_path":
        markers[0]["tensor_references"][1]["path"] = [0, 0]
    elif mutation == "reordered_phase":
        markers[0]["phase"] = "output"
    elif mutation == "wrong_code":
        markers[0]["context"]["code"] = "other"
    elif mutation == "wrong_file":
        markers[0]["context"]["source_file"] = "/other.py"
    elif mutation == "missing_tensor":
        eto["nodes"][0]["inputs"]["values"].pop()
    elif mutation == "bad_descriptor":
        eto["nodes"][0]["inputs"]["values"][0] = [1, 2]
    elif mutation == "bool_index":
        markers[0]["tensor_references"][0]["path"] = [True]
    elif mutation == "direct_context":
        markers[0]["context"]["kind"] = "direct caller"
    elif mutation == "unaccounted_marker":
        eto["nodes"].append({**deepcopy(eto["nodes"][0]), "id": 99,
                             "name": markers[0]["name"].replace(":1:input", ":2:input")})
    elif mutation == "lossy_meta":
        meta["dropped_events"] = 1
    elif mutation == "duplicate_call":
        calls.append(deepcopy(calls[0]))
        meta["events"] += 1
    elif mutation == "duplicate_code":
        codes.append(deepcopy(codes[0]))
        meta["codes"] += 1
    elif mutation == "mixed_nonce":
        markers[1]["name"] = markers[1]["name"].replace("a" * 32, "b" * 32)
        eto["nodes"][1]["name"] = markers[1]["name"]
    elif mutation == "missing_inputs":
        del eto["nodes"][0]["inputs"]
    elif mutation == "non_array_inputs":
        eto["nodes"][0]["inputs"]["values"] = None
    with pytest.raises(ValueError):
        _import(tmp_path, docs)


def test_replay_is_bounded_and_requires_an_explicit_profile(tmp_path):
    with pytest.raises(ValueError, match="max_bytes"):
        _import(tmp_path, max_bytes=10)
    with pytest.raises(ValueError, match="max_markers"):
        _import(tmp_path, max_markers=1)
    with pytest.raises(ValueError, match="profile"):
        import_reference_bridge(None, None, None, None, None,
            reference_profile="arbitrary", provider_revision=REVISION)


def test_jsonl_locators_use_physical_lines_after_empty_lines(tmp_path):
    _import(tmp_path)
    for name in ("calls.jsonl", "codes.jsonl"):
        path = tmp_path / name
        path.write_bytes(b"\n\n" + path.read_bytes())
    result = import_reference_bridge(*(tmp_path / name for name in
        ("eto.json", "markers.json", "calls.jsonl", "codes.jsonl", "meta.json")),
        reference_profile=RESEARCH_PROFILE, provider_revision=REVISION)
    edges = [edge for edge in result.bundle.evidence.edges.values()
             if edge.relation is EvidenceRelation.OBJECT_REFERENCE_ASSOCIATION]
    assert all(sum(ref.endswith("#line/3") for ref in edge.evidence.references) == 2 for edge in edges)


def test_public_native_cli_imports_explicit_research_profile(tmp_path):
    _import(tmp_path)
    command = [sys.executable, "-m", "scar.cli", "import-native", "--execution-trace", str(tmp_path / "eto.json"),
        "--reference-markers", str(tmp_path / "markers.json"), "--call-events", str(tmp_path / "calls.jsonl"),
        "--call-codes", str(tmp_path / "codes.jsonl"), "--call-meta", str(tmp_path / "meta.json"),
        "--reference-profile", RESEARCH_PROFILE, "--provider-revision", REVISION, "--out", str(tmp_path / "cli")]
    run = subprocess.run(command, text=True, capture_output=True)
    assert run.returncode == 0, run.stderr
    with gzip.open(tmp_path / "cli/evidence-bundle.json.gz", "rt") as stream:
        bundle = bundle_from_dict(json.load(stream))
    assert len(bundle.values.objects) == 2 and not bundle.values.versions
    partial = command.copy()
    meta_index = partial.index("--call-meta")
    del partial[meta_index:meta_index + 2]
    partial[-1] = str(tmp_path / "incomplete")
    incomplete = subprocess.run(partial, text=True, capture_output=True)
    assert incomplete.returncode != 0 and "together" in incomplete.stderr
    assert not (tmp_path / "incomplete").exists()
