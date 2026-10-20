"""Provider associations must never manufacture content identity or order."""
from copy import deepcopy
import gzip
import json
import subprocess
import sys

import pytest

from scar.ir.v2 import (EvidenceClaim, EvidenceGraph, EvidenceKind,
                        EvidenceNodeKind, EvidenceRelation, ProviderReference,
                        bundle_from_dict)
from scar.ir.v2.codec import evidence_from_dict
from scar.trace.native_import import import_native_evidence


REVISION = "cf30153c4c131c8164ee7798e5022d810682e2cb"


def _slots(values=(), types=(), shapes=(), strides=()):
    return {"values": list(values), "types": list(types),
            "shapes": list(shapes), "strides": list(strides)}


def _node(identifier, name, parent, rf, inputs=None, outputs=None):
    return {"id": identifier, "name": name, "ctrl_deps": parent,
            "inputs": inputs or _slots(), "outputs": outputs or _slots(),
            "attrs": [{"name": "rf_id", "type": "uint64", "value": rf},
                      {"name": "tid", "type": "uint64", "value": 0 if identifier == 1 else 1},
                      {"name": "scope", "type": "uint64", "value": 7 if identifier <= 2 else 0},
                      {"name": "op_schema", "type": "string", "value": ""}]}


def _documents():
    tensor = [100, 200, 0, 4, 4, "cuda:0"]
    view = [101, 200, 0, 4, 4, "cuda:0"]
    first = _slots([tensor], ["Tensor(float)"], [[4]], [[1]])
    viewed = _slots([view], ["Tensor(float)"], [[2, 2]], [[2, 1]])
    # ETO serialization is completion order, with parents after their children.
    nodes = [_node(4, "generic::view", 3, 11, first, viewed),
             _node(3, "generic::produce", 2, 10, outputs=first),
             _node(5, "generic::mutate", 2, 12, first, first),
             _node(6, "generic::consume_list", 2, 13,
                   _slots([[[100, 200, 0, 4, 4, "cuda:0"],
                            [101, 200, 0, 4, 4, "cuda:0"]], [1, 2, 3, 4, 5, 6]],
                          ["GenericList[Tensor(float),Tensor(float)]", "GenericList[Int,Int,Int,Int,Int,Int]"],
                          [[[4], [2, 2]], [[], [], [], [], [], []]],
                          [[[1], [2, 1]], [[], [], [], [], [], []]])),
             _node(2, "[pytorch|profiler|execution_trace|thread]", 1, 0),
             _node(1, "[pytorch|profiler|execution_trace|process]", 1, 0)]
    eto = {"schema": "1.1.1-chakra.0.0.4", "pid": 42, "time": "fixture",
           "start_ts": 1, "finish_ts": 100, "nodes": nodes}
    events = [{"ph": "X", "cat": "cpu_op", "name": name, "pid": 42,
               "tid": 43, "ts": index + 10, "dur": 1,
               "args": {"Record function id": rf, "External id": rf}}
              for index, (name, rf) in enumerate([
                  ("generic::produce", 10), ("generic::view", 11),
                  ("generic::mutate", 12), ("generic::consume_list", 13)])]
    # Device activity overlaps the runtime call. Correlation is not return-before-start.
    events.extend([
        {"ph": "X", "cat": "cuda_runtime", "name": "cudaLaunchKernel", "pid": 42,
         "tid": 43, "ts": 15, "dur": 5, "args": {"correlation": 123, "External id": 12}},
        {"ph": "X", "cat": "kernel", "name": "generic_kernel", "pid": 0,
         "tid": 7, "ts": 16, "dur": 20,
         "args": {"correlation": 123, "device": 0, "context": 1, "stream": 7}},
        {"ph": "i", "cat": "future_category", "name": "retained", "pid": 42,
         "tid": 43, "ts": 17, "args": {}},
    ])
    return eto, {"schemaVersion": 1, "traceEvents": events}


def _import(tmp_path, eto=None, chrome=None, *, compressed=False, max_bytes=512000000):
    default_eto, default_chrome = _documents()
    eto = default_eto if eto is None else eto
    chrome = default_chrome if chrome is None else chrome
    paths = [tmp_path / (name + (".gz" if compressed else ""))
             for name in ("eto.json", "chrome.json")]
    for path, doc in zip(paths, (eto, chrome), strict=True):
        payload = json.dumps(doc).encode()
        path.write_bytes(gzip.compress(payload) if compressed else payload)
    return import_native_evidence(*paths, provider_revision=REVISION, max_bytes=max_bytes)


def test_reference_edges_preserve_views_mutation_slots_and_async_submission(tmp_path):
    result = _import(tmp_path)
    bundle = result.bundle
    assert bundle.assert_valid()["valid"]
    assert result.report["cpu_rf_matches"] == 4
    assert result.report["runtime_gpu_matches"] == 1
    assert result.report["whole_model_established"] is False
    relations = [edge.relation for edge in bundle.evidence.edges.values()]
    assert relations.count(EvidenceRelation.SUBMITS_WORK) == 1
    assert relations.count(EvidenceRelation.INPUT_REFERENCE) == 4
    assert relations.count(EvidenceRelation.OUTPUT_REFERENCE) == 3
    assert EvidenceRelation.HAPPENS_BEFORE not in relations
    assert EvidenceRelation.ALIASES not in relations
    assert EvidenceRelation.PRODUCES not in relations
    assert not bundle.values.versions
    assert not bundle.evidence.observations
    assert len({edge.target.reference for edge in bundle.evidence.edges.values()
                if edge.target.kind is EvidenceNodeKind.PROVIDER_REFERENCE}) == 2
    # A real graph roundtrip must retain every exact locator and repeated slot.
    wire = bundle.to_dict()
    assert bundle_from_dict(deepcopy(wire)).to_dict() == wire


def test_duplicate_runtime_id_refuses_to_guess_a_submission(tmp_path):
    eto, chrome = _documents()
    chrome["traceEvents"].append(deepcopy(chrome["traceEvents"][4]))
    result = _import(tmp_path, eto, chrome)
    assert result.report["runtime_gpu_matches"] == 0
    assert not any(edge.relation is EvidenceRelation.SUBMITS_WORK
                   for edge in result.bundle.evidence.edges.values())
    assert result.report["gaps"]


def test_duplicate_rf_refuses_to_merge_cpu_observations(tmp_path):
    eto, chrome = _documents()
    chrome["traceEvents"].append(deepcopy(chrome["traceEvents"][0]))
    result = _import(tmp_path, eto, chrome)
    assert result.report["cpu_rf_matches"] == 3
    assert result.report["gaps"]


def test_lossless_compressed_inputs_and_decompressed_budget(tmp_path):
    result = _import(tmp_path, compressed=True)
    assert result.report["cpu_rf_matches"] == 4
    with pytest.raises(ValueError):
        _import(tmp_path, compressed=True, max_bytes=100)


@pytest.mark.parametrize("mutation", ["schema", "pid", "duplicate_node", "cycle", "self_cycle"])
def test_invalid_provider_structure_is_not_a_valid_model(tmp_path, mutation):
    eto, chrome = _documents()
    if mutation == "schema":
        eto["schema"] = "not-a-supported-schema"
    elif mutation == "pid":
        eto["pid"] = True
    elif mutation == "duplicate_node":
        eto["nodes"].append(deepcopy(eto["nodes"][0]))
    elif mutation == "cycle":
        eto["nodes"][-1]["ctrl_deps"] = 4
    else:
        eto["nodes"][0]["ctrl_deps"] = eto["nodes"][0]["id"]
    with pytest.raises(ValueError):
        _import(tmp_path, eto, chrome)


def test_unknown_provider_revision_and_duplicate_json_keys_are_rejected(tmp_path):
    eto, chrome = _documents()
    eto_path, chrome_path = tmp_path / "eto.json", tmp_path / "chrome.json"
    eto_path.write_text(json.dumps(eto))
    chrome_path.write_text(json.dumps(chrome))
    with pytest.raises(ValueError):
        import_native_evidence(eto_path, chrome_path, provider_revision="not-a-revision")
    eto_path.write_text('{"schema":"first","schema":"second"}')
    with pytest.raises(ValueError):
        import_native_evidence(eto_path, chrome_path, provider_revision=REVISION)


def test_provider_references_are_owned_versioned_and_never_external_placeholders(tmp_path):
    old = EvidenceGraph().to_dict()
    assert old["schema_version"] == 3
    assert evidence_from_dict(old).to_dict() == old
    graph = _import(tmp_path).bundle.evidence
    wire = graph.to_dict()
    assert wire["schema_version"] == 4
    assert len(graph.provider_references) == 2
    assert evidence_from_dict(deepcopy(wire)).to_dict() == wire
    downgraded = deepcopy(wire)
    downgraded["schema_version"] = 3
    with pytest.raises(ValueError):
        evidence_from_dict(downgraded)
    dangling = deepcopy(wire)
    dangling["provider_references"] = []
    with pytest.raises(ValueError):
        evidence_from_dict(dangling)
    with pytest.raises((TypeError, ValueError)):
        ProviderReference("ref", "provider", "scope", "tensor_impl_map", True,
                          (EvidenceClaim(EvidenceKind.OBSERVED, ("fixture",)),))


def test_public_cli_imports_collected_files_and_preserves_existing_output(tmp_path):
    _import(tmp_path)
    output = tmp_path / "imported"
    command = [sys.executable, "-m", "scar.cli", "import-native",
               "--execution-trace", str(tmp_path / "eto.json"),
               "--kineto", str(tmp_path / "chrome.json"),
               "--provider-revision", REVISION, "--out", str(output)]
    run = subprocess.run(command, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["cpu_rf_matches"] == 4
    with gzip.open(output / "import-report.json.gz", "rt") as stream:
        assert json.load(stream)["whole_model_established"] is False
    with gzip.open(output / "evidence-bundle.json.gz", "rt") as stream:
        bundle = bundle_from_dict(json.load(stream))
    assert bundle.assert_valid()["valid"]
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    again = subprocess.run(command, capture_output=True, text=True)
    assert again.returncode != 0
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before


def test_observed_references_cannot_silently_become_content_or_control_ports(tmp_path):
    from scar.analysis.regions_v2 import RegionInventory
    from scar.ir.execution.ids import EvidenceInventoryID
    from scar.ir.execution.production import InventorySourceRef, SourceEndpointRef
    from scar.ir.v2 import EvidenceEndpoint
    result = _import(tmp_path)
    reference_edge = next(edge for edge in result.bundle.evidence.edges.values()
                          if edge.relation is EvidenceRelation.INPUT_REFERENCE)
    with pytest.raises(ValueError, match="no established region port mapping"):
        RegionInventory(result.bundle, view="execution").region((reference_edge.source.reference,))
    source = InventorySourceRef(EvidenceInventoryID("fixture"), "native")
    with pytest.raises(ValueError, match="do not establish a source content endpoint"):
        SourceEndpointRef(source, EvidenceEndpoint(EvidenceNodeKind.PROVIDER_REFERENCE,
                                                  reference_edge.target.reference))
