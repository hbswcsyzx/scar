"""One CPU capture of existing experimental profiler metadata/dataflow APIs.

No SCAR import, no Tensor content serialization, no install, no GPU work.
Stages preserve failures and do not retry capture with different options.
"""
import hashlib
import json
import platform
import sys
import traceback
from pathlib import Path

import torch
from torch._C._profiler import _EventType, _TensorMetadata


def tensor_metadata(value):
    if isinstance(value, _TensorMetadata):
        return {"type": "TensorMetadata", "impl_ptr": value.impl_ptr,
                "storage_data_ptr": value.storage_data_ptr, "id": value.id,
                "allocation_id": value.allocation_id, "layout": str(value.layout),
                "device": str(value.device), "dtype": str(value.dtype),
                "sizes": list(value.sizes), "strides": list(value.strides)}
    if isinstance(value, (tuple, list)):
        return [tensor_metadata(item) for item in value]
    return {"type": type(value).__qualname__}  # no scalar/tensor payloads


def tensor_key(key):
    return {"tensor_id": key.id, "allocation_id": key.storage.allocation_id,
            "storage_data_ptr": key.storage.ptr, "device": str(key.device)}


report = {
    "python": sys.version, "implementation": platform.python_implementation(),
    "torch": torch.__version__, "torch_git_revision": torch.version.git_version,
    "cuda_build": torch.version.cuda,
    "cuda_initialized_before": torch.cuda.is_initialized(),
    "capture_count": 1,
    "options": {"activities": ["CPU"], "record_shapes": True,
                "profile_memory": True, "with_stack": True},
    "stages": {}, "checks": {},
    "boundaries": ["Experimental/private APIs and this build only.",
                   "One configuration, not an options-availability matrix.",
                   "No test of allocator reuse, external writes, GPU readiness or logical equivalence.",
                   "DataFlowGraph mutation versions are schema-based provider facts, not SCAR LogicalVersion."],
}
profiler = None
try:
    original = torch.arange(4, dtype=torch.float32)
    with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU],
                                record_shapes=True, profile_memory=True, with_stack=True) as profiler:
        value = original + 1
        view = value.view(2, 2)
        value.add_(1)
        value.add_(2)
        copied = view.clone()
        del copied
    report["stages"]["capture"] = {"status": "PASS"}
except BaseException as error:
    report["stages"]["capture"] = {"status": "FAIL", "type": type(error).__name__,
                                      "message": str(error), "traceback": traceback.format_exc()}

if report["stages"]["capture"]["status"] == "PASS":
    try:
        roots = profiler.profiler.kineto_results.experimental_event_tree()
        events = []
        stack = list(reversed(roots))
        while stack:
            event = stack.pop()
            stack.extend(reversed(event.children))
            tag, extra = event.typed
            if tag not in (_EventType.TorchOp, _EventType.Allocation):
                continue
            entry = {"name": event.name, "tag": str(tag), "id": event.id,
                     "correlation_id": event.correlation_id,
                     "start_time_ns": event.start_time_ns,
                     "duration_time_ns": event.duration_time_ns}
            if tag == _EventType.TorchOp:
                entry["inputs"] = tensor_metadata(extra.inputs)
            else:
                entry["allocation"] = {"ptr": extra.ptr, "id": extra.id,
                                       "allocation_id": extra.allocation_id,
                                       "alloc_size": extra.alloc_size, "device": str(extra.device)}
            events.append(entry)
        report["event_tree"] = events
        tensors = [item for event in events for item in event.get("inputs", [])
                   if isinstance(item, dict) and item.get("type") == "TensorMetadata"]
        assert tensors, "no TensorMetadata found"
        assert any(item["allocation_id"] is not None for item in tensors), "no assigned allocation ID"
        report["checks"]["metadata_fields_present"] = True
        report["checks"]["some_allocation_ids_assigned"] = True
        report["stages"]["experimental_event_tree"] = {"status": "PASS", "record_count": len(events)}
    except BaseException as error:
        report["stages"]["experimental_event_tree"] = {
            "status": "FAIL", "type": type(error).__name__, "message": str(error),
            "traceback": traceback.format_exc()}
    try:
        memory = profiler._memory_profile()
        rows = []
        for node in memory._data_flow_graph.flow_nodes:
            rows.append({"name": node._event.name, "event_id": node._event.id,
                         "inputs": [{**tensor_key(key), "may_mutate": mutable, "version": version}
                                    for key, (mutable, version) in node.inputs.items()],
                         "outputs": [{**tensor_key(key), "version": version}
                                     for key, version in node.outputs.items()]})
        report["memory_dataflow"] = rows
        additions = [row for row in rows if row["name"] == "aten::add_"]
        assert len(additions) == 2, f"expected two leaf add_ events, got {len(additions)}"
        transitions = []
        for row in additions:
            mutable = [item for item in row["inputs"] if item["may_mutate"]]
            assert len(mutable) == 1, f"expected one mutable Tensor input: {row}"
            source = mutable[0]
            matches = [item for item in row["outputs"]
                       if (item["tensor_id"], item["allocation_id"], item["device"])
                       == (source["tensor_id"], source["allocation_id"], source["device"])]
            assert len(matches) == 1 and matches[0]["version"] == source["version"] + 1
            transitions.append({"tensor_id": source["tensor_id"], "allocation_id": source["allocation_id"],
                                "before": source["version"], "after": matches[0]["version"]})
        assert transitions[0]["tensor_id"] == transitions[1]["tensor_id"]
        assert transitions[0]["allocation_id"] == transitions[1]["allocation_id"]
        assert transitions[0]["after"] == transitions[1]["before"]
        report["checks"]["two_sequential_schema_based_mutation_increments"] = transitions
        report["stages"]["memory_profile"] = {"status": "PASS", "node_count": len(rows)}
    except BaseException as error:
        report["stages"]["memory_profile"] = {"status": "FAIL", "type": type(error).__name__,
                                               "message": str(error), "traceback": traceback.format_exc()}

report["cuda_initialized_after"] = torch.cuda.is_initialized()
report["scar_imported"] = any(name == "scar" or name.startswith("scar.") for name in sys.modules)
report["source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
report["source_evidence"] = {}
for path in (Path(torch.__file__).parent / "profiler/profiler.py",
             Path(torch.__file__).parent / "profiler/_memory_profiler.py",
             Path(torch.__file__).parent / "_C/_profiler.pyi"):
    report["source_evidence"][str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
Path(__file__).with_name("results.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"stages": report["stages"], "checks": report["checks"],
                  "cuda_initialized_after": report["cuda_initialized_after"]}))
if any(stage["status"] == "FAIL" for stage in report["stages"].values()):
    raise SystemExit(1)
