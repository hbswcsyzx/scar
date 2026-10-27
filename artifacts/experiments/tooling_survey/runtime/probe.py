"""CPU-only metadata witnesses for existing runtime evidence tools."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
import torch

OUT = Path(__file__).resolve().parent
observed = {"python": sys.version, "torch": torch.__version__, "torch_git": torch.version.git_version,
            "cuda_build": torch.version.cuda, "cuda_initialized_before": torch.cuda.is_initialized(),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

# No event/observer was active before installation in this child process.
monitoring = sys.monitoring
tool_id = next(i for i in range(6) if monitoring.get_tool(i) is None)
monitoring.use_tool_id(tool_id, "scar-readonly-runtime-survey")
monitoring_rows = []
def callee(a, b):
    return a + b
def control(flag):
    result = callee(2, 3)
    if flag:
        result += len([1, 2])
    return result
def callback(name):
    def record(*args):
        monitoring_rows.append({"event": name, "code": args[0].co_name,
                                "argument_types": [type(arg).__name__ for arg in args],
                                "offset": args[1], "collector_perf_counter_ns": time.perf_counter_ns()})
    return record
local_names = ["PY_START", "PY_RETURN", "CALL", "INSTRUCTION", "BRANCH_LEFT", "BRANCH_RIGHT", "JUMP"]
try:
    for name in local_names + ["C_RETURN", "C_RAISE"]:
        monitoring.register_callback(tool_id, getattr(monitoring.events, name), callback(name))
    mask = sum(getattr(monitoring.events, name) for name in local_names)
    for code in (callee.__code__, control.__code__):
        monitoring.set_local_events(tool_id, code, mask)
    control(True)
finally:
    monitoring.free_tool_id(tool_id)
observed["monitoring"] = {"rows": monitoring_rows, "tool_released": monitoring.get_tool(tool_id) is None,
                           "counts": dict(Counter(row["event"] for row in monitoring_rows))}

observer = torch.profiler.ExecutionTraceObserver().register_callback(str(OUT / "execution-trace.json"))
observer.set_extra_resource_collection(False)
array = np.zeros(4, dtype=np.float32)
shared = torch.from_numpy(array)
python_state = {"counter": 0}
def ordinary_python_region():
    python_state["counter"] += 1
    (OUT / "small-output.txt").write_text("witness\n")
    return python_state["counter"]
try:
    with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU],
                                record_shapes=True, profile_memory=True, with_stack=True,
                                execution_trace_observer=observer) as profiler:
        x = torch.arange(4, dtype=torch.float32).reshape(2, 2)
        view = x.t()
        copied = x.clone()
        copied.add_(1)
        before_mutation = copied.sum()
        copied.add_(2)
        after_mutation = copied.sum()
        # Foreign alias writes and ordinary Python/File activity have no aten node.
        array[3] = 7
        ordinary_python_region()
        alias_consumer = shared.sum()
    profiler.export_chrome_trace(str(OUT / "chrome-trace.json"))
    host_events = []
    for event in profiler.events():
        host_events.append({"name": event.name, "input_shapes": event.input_shapes,
                            "cpu_parent": event.cpu_parent.name if event.cpu_parent else None,
                            "kernels": len(event.kernels), "device_type": str(event.device_type),
                            "sequence_nr": event.sequence_nr})
finally:
    observer.unregister_callback()
et = json.loads((OUT / "execution-trace.json").read_text())
chrome = json.loads((OUT / "chrome-trace.json").read_text())
observed["execution_trace"] = {"schema": et.get("schema"), "top_fields": list(et),
                               "node_count": len(et.get("nodes", [])),
                               "node_fields": sorted({key for n in et.get("nodes", []) for key in n}),
                               "node_names": dict(Counter(n["name"] for n in et.get("nodes", []))),
                               "extra_resources_enabled": observer.extra_resources_collection}
observed["chrome"] = {"schemaVersion": chrome.get("schemaVersion"), "top_fields": list(chrome),
                      "categories": dict(Counter(str(e.get("cat")) for e in chrome.get("traceEvents", []))),
                      "ts_fields": [{key: chrome[key] for key in ("baseTimeNanoseconds", "displayTimeUnit") if key in chrome}]}
observed["profiler_cpu_events"] = host_events
observed["cuda_initialized_after"] = torch.cuda.is_initialized()
observed["source_sha256"] = {
    str(Path(torch.__file__).parent / "profiler/profiler.py"): hashlib.sha256((Path(torch.__file__).parent / "profiler/profiler.py").read_bytes()).hexdigest(),
}
(OUT / "probe.json").write_text(json.dumps(observed, indent=2) + "\n")
print(json.dumps({k: v for k, v in observed.items() if k not in ("profiler_cpu_events", "monitoring")}, indent=2))
