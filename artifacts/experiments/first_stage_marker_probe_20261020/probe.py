"""Research probe only: exact shared ETO input-map tokens, no value snapshots."""
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys

import torch
from torch.utils._python_dispatch import TorchDispatchMode

from scar.trace.call_edges import install

root = Path(__file__).resolve().parent
output = root / "raw"
output.mkdir(exist_ok=False)
nonce = secrets.token_hex(16)
recorder = install(output, root / "case")
if recorder is None:
    raise RuntimeError("call recorder not installed")
spec = importlib.util.spec_from_file_location("external_marker_case", root / "case/app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
rows = []


def leaves(value, path, collected):
    if type(value) is torch.Tensor:
        collected.append((path, value))
    elif type(value) in (tuple, list):
        for ordinal, child in enumerate(value):
            leaves(child, (*path, ordinal), collected)
    elif type(value) is dict:
        for name, child in value.items():
            if type(name) is not str:
                raise TypeError("probe only accepts exact string-key kwargs")
            leaves(child, (*path, name), collected)


def frame_context(frame):
    while frame is not None:
        retained = recorder.active.get((__import__("threading").get_ident(), id(frame)))
        if retained is not None:
            return {"invocation": retained[0], "code": retained[1],
                    "source_file": frame.f_code.co_filename,
                    "bytecode_offset": frame.f_lasti,
                    "kind": "retained ancestor context, not a proven direct caller"}
        frame = frame.f_back
    return None


def marker(sequence, phase, payload, context):
    observed = []
    leaves(payload, (), observed)
    with recorder.lock:
        seen = {}
        references = [{"path": list(path), "ref": recorder._reference(tensor, seen)}
                      for path, tensor in observed]
    name = f"scar-observation:{nonce}:{os.getpid()}:{sequence}:{phase}"
    row = {"name": name, "sequence": sequence, "phase": phase,
           "context": context, "tensor_references": references}
    rows.append(row)
    # The provider itself serializes these real Tensor arguments using the same
    # TensorImpl map as its ordinary operations. No address/shape matching.
    handle = torch.autograd._record_function_with_args_enter(name, *(value for _, value in observed))
    torch.autograd._record_function_with_args_exit(handle)


class Observe(TorchDispatchMode):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def __torch_dispatch__(self, func, types, args=(), kwargs=None):
        self.calls += 1
        sequence = self.calls
        with recorder.lock:
            context = frame_context(sys._getframe().f_back)
        marker(sequence, "input", (args, kwargs or {}), context)
        result = func(*args, **(kwargs or {}))
        marker(sequence, "output", result, context)
        return result


x = torch.arange(4.0, device="cpu")
g = torch.arange(4.0, device="cpu", requires_grad=True)
observer = torch.profiler.ExecutionTraceObserver().register_callback(str(output / "execution-trace.json"))
mode = Observe()
with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU],
                            execution_trace_observer=observer,
                            record_shapes=False, profile_memory=False):
    with mode:
        view, result, loss = app.run(x, g)
observer.unregister_callback()
recorder.close()
loss.backward()
assert torch.equal(g.grad, 2 * torch.arange(4.0, device="cpu"))
assert torch.equal(result, 2 * torch.arange(4.0, device="cpu"))
assert torch.equal(x, torch.arange(4.0, device="cpu") + 1)
(root / "markers.json").write_text(json.dumps(rows, indent=2) + "\n")
document = json.loads((output / "execution-trace.json").read_text())
markers = {node["name"]: node for node in document["nodes"] if node["name"].startswith("scar-observation:" + nonce)}
assert len(markers) == len(rows) == mode.calls * 2
for row in rows:
    node = markers[row["name"]]
    assert len(node["inputs"]["values"]) == len(row["tensor_references"])
    assert row["context"] is not None
receipt = {"schema": "scar.marker-research-probe", "whole_model_established": False,
           "dispatch_calls": mode.calls, "markers": len(markers),
           "grad_correct": True, "result_correct": True, "inplace_correct": True,
           "tensor_contents_saved": False, "tensor_version_used": False,
           "scope": "fresh CPU process; no foreign modes/subclasses/lifecycle claims"}
(root / "probe-result.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt))
