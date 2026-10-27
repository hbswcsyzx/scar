"""Raw-byte inventory fixtures, without runtime execution or capture proof."""
import json

from scar.ir.execution.inventory import build_inventory


def inventory_sources(*, raw_streams=None, metadata=None, scopes=None):
    """Return (manifest artifact, index artifact, exact payload bytes catalog)."""
    if raw_streams is None:
        row = {"kind": "torch_dispatch", "invocation_id": 1, "code_id": "declared-op",
               "ts_ns": 20, "duration_ns": 10,
               "metadata": {"process_id": 101, "thread_id": 1, "operation": "declared.op"},
               "inputs": [], "outputs": [{"type": "torch.Tensor", "shape": [4], "strides": [1],
                   "offset": 0, "device": "cpu", "dtype": "uint8", "storage_id": "hint",
                   "object_id": "hint", "logical_version": "hint-v0"}]}
        raw_streams = {"main": (json.dumps(row) + "\n").encode()}
    return build_inventory(raw_streams, metadata=metadata, scopes=scopes)
