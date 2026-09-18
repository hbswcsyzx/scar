"""Import measured CUDA activities from a PyTorch/Kineto Chrome trace."""
from __future__ import annotations

import json
from pathlib import Path

from scar.ir import Effect, Event


def correlate_transfer_states(transfer_records, physical_events) -> dict[str, int]:
    """Attach only conservative logical metadata to physical memcpy events.

    SCAR's host wrapper and Kineto use different clocks and currently expose
    no shared correlation ID for a Tensor `.to()` call. Matching therefore
    requires direction and byte count. A logical version is attached only
    when exactly one unmatched host transfer has that signature; otherwise
    the physical event remains explicitly ambiguous.
    """
    buckets: dict[tuple[str, int], list[tuple[int, Event]]] = {}
    for index, transfer in transfer_records:
        source = str(transfer.resource.get("source_device", ""))
        destination = str(transfer.resource.get("destination_device", ""))
        if source.startswith("cpu") and destination.startswith("cuda"):
            direction = "HtoD"
        elif source.startswith("cuda") and destination.startswith("cpu"):
            direction = "DtoH"
        elif source.startswith("cuda") and destination.startswith("cuda"):
            direction = "DtoD"
        else:
            continue
        moved = transfer.resource.get("bytes")
        if moved is None:
            continue
        buckets.setdefault((direction, int(moved)), []).append((index, transfer))

    counts = {"matched_unique": 0, "ambiguous": 0, "unmatched": 0}
    for physical in physical_events:
        if physical.kind != "cuda_memcpy":
            continue
        direction = str(physical.resource.get("direction", "unknown"))
        moved = physical.resource.get("bytes")
        try:
            candidates = buckets.get((direction, int(moved)), [])
        except (TypeError, ValueError):
            candidates = []
        if len(candidates) == 1:
            index, transfer = candidates[0]
            physical.metadata.update({
                "logical_tensor_mapping": "inferred_unique_signature",
                "mapping_confidence": "Inferred",
                "matched_transfer_event_index": index,
                "logical_version": transfer.outputs[0].get("logical_version"),
                "storage_id": transfer.outputs[0].get("storage_id"),
            })
            buckets[(direction, int(moved))].clear()
            counts["matched_unique"] += 1
        elif len(candidates) > 1:
            physical.metadata.update({
                "logical_tensor_mapping": "AMBIGUOUS_SIGNATURE",
                "mapping_confidence": "UNKNOWN",
            })
            counts["ambiguous"] += 1
        else:
            counts["unmatched"] += 1
    return counts


def profiler_activities(path: str | Path, process_id: int):
    """Keep physical copies distinct from Tensor.to calls and API enqueues.

    Correlation IDs link GPU activities to their host runtime call, but do not
    prove which logical tensor was copied. That mapping remains unknown.
    Kineto timestamps are retained in their own clock domain.
    """
    records = json.loads(Path(path).read_text()).get("traceEvents", [])
    runtime = {event.get("args", {}).get("correlation"): event for event in records
               if event.get("cat") in {"cuda_runtime", "cuda_driver"}
               and event.get("args", {}).get("correlation") is not None}
    for event in records:
        category, name = event.get("cat"), str(event.get("name", ""))
        args = event.get("args", {})
        if event.get("ph") != "X":
            continue
        if category == "gpu_memcpy":
            kind, labels = "cuda_memcpy", ["XFER"]
        elif category == "kernel":
            kind, labels = "cuda_kernel", ["VAL"]
        elif category in {"cuda_runtime", "cuda_driver"} and (
                "Synchronize" in name or "WaitEvent" in name):
            kind, labels = "cuda_barrier", ["ORDER"]
        else:
            continue
        host = runtime.get(args.get("correlation"), {})
        resource = {key: args[key] for key in ("device", "stream", "context", "bytes") if key in args}
        if kind == "cuda_memcpy":
            resource["direction"] = next((direction for direction in
                ("HtoD", "DtoH", "DtoD", "HtoH", "PtoP") if direction in name), "unknown")
        yield Event(kind=kind, ts_ns=round(event.get("ts", 0) * 1000),
                    duration_ns=round(event.get("dur", 0) * 1000),
                    labels=labels, effect=Effect(), resource=resource,
                    metadata={"operation": name, "process_id": process_id,
                              "profiler_pid": event.get("pid"), "profiler_tid": event.get("tid"),
                              "clock_domain": "kineto", "source": str(path),
                              "correlation": args.get("correlation"),
                              "external_id": args.get("External id"),
                              "host_runtime": host.get("name"), "host_tid": host.get("tid"),
                              "physical": True if kind == "cuda_memcpy" else None,
                              "logical_tensor_mapping": "UNKNOWN"})
