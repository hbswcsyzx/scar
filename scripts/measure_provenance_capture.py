"""Measure field reads, actual observer capture and explicit checkpoint cost.

Usage: python scripts/measure_provenance_capture.py --out REPORT.json
Creates a small seeded tensor locally. This measures evidence collection cost,
not an optimization or workload speedup. No tensor payload is written to disk.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torch  # noqa: E402

from scar.trace.checkpoint import (  # noqa: E402
    CheckpointBudgetExceeded, CheckpointStore, ComparisonStatus,
)
from scar.trace.values_v2 import TensorObserver  # noqa: E402


def _sources():
    paths = sorted([*ROOT.joinpath("scar").rglob("*.py"), Path(__file__).resolve()])
    files = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in paths}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(), files


def _git(*arguments):
    result = subprocess.run(["git", *arguments], cwd=ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.strip() if result.returncode == 0 else None


def _statistics(samples):
    return {"unit": "ns", "samples": samples, "median": statistics.median(samples),
            "minimum": min(samples), "maximum": max(samples),
            "variance": statistics.pvariance(samples), "count": len(samples)}


def _descriptor(tensor):
    return {"shape": list(tensor.shape), "dtype": str(tensor.dtype),
            "device": str(tensor.device), "strides": list(tensor.stride()),
            "offset": tensor.storage_offset()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--numel", type=int, default=65536)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    args = parser.parse_args()
    if args.numel < 16 or args.warmup < 0 or args.repetitions < 1:
        parser.error("numel >= 16, warmup >= 0 and repetitions >= 1 are required")
    if args.device == "cuda" and not torch.cuda.is_available():
        parser.error("CUDA requested but unavailable")
    device = "cuda" if args.device == "cuda" or (args.device == "auto" and torch.cuda.is_available()) else "cpu"
    source_sha, files = _sources()
    revision, worktree = _git("rev-parse", "HEAD"), _git("status", "--porcelain")
    generator = torch.Generator(device="cpu").manual_seed(args.seed)
    cpu = torch.randn(args.numel, dtype=torch.float32, generator=generator)
    tensor = cpu.to(device)
    if device == "cuda":
        torch.cuda.synchronize(tensor.device)
    nbytes = cpu.numel() * cpu.element_size()
    observer = TensorObserver(namespace="checkpoint-cost-observer")
    initial_started = time.perf_counter_ns()
    observer_handle = observer.observe(tensor)
    initial_observer_ns = time.perf_counter_ns() - initial_started
    store = CheckpointStore(max_bytes=nbytes, prefix_elements=8, allow_cuda=device == "cuda")
    checkpoint_id = store.enroll(cpu)
    checkpoint = store.describe(checkpoint_id)

    for _ in range(args.warmup):
        _descriptor(tensor)
        observer.observe(tensor)
        store.compare(checkpoint_id, tensor)
    descriptors, captures, comparisons, statuses, checked_bytes = [], [], [], [], []
    synchronized = []
    observer_handle_reused = True
    for _ in range(args.repetitions):
        started = time.perf_counter_ns()
        _descriptor(tensor)
        descriptors.append(time.perf_counter_ns() - started)
        started = time.perf_counter_ns()
        observed = observer.observe(tensor)
        captures.append(time.perf_counter_ns() - started)
        observer_handle_reused = observer_handle_reused and observed == observer_handle
        comparison = store.compare(checkpoint_id, tensor)
        comparisons.append(comparison.duration_ns)
        statuses.append(comparison.status.value)
        checked_bytes.append(comparison.checked_bytes)
        synchronized.append(comparison.synchronized_cuda)

    # The same explicit checkpoint is used for three captures. Their bitwise
    # equality does not assign them one semantic identity or prove provenance.
    returned = tensor.to("cpu")
    cpu_before = store.compare(checkpoint_id, cpu)
    roundtrip = store.compare(checkpoint_id, returned)
    tensor[-1] += 1  # Deliberately outside the prefix; full verification required.
    changed = store.compare(checkpoint_id, tensor)
    budget_rejected = False
    try:
        store.enroll(torch.empty(1))
    except CheckpointBudgetExceeded:
        budget_rejected = True
    retained_bytes = store.bytes_used
    released = store.release(checkpoint_id)
    source_unchanged = _sources()[0] == source_sha
    verified = (all(status == ComparisonStatus.EXACT.value for status in statuses)
                and all(value == nbytes for value in checked_bytes)
                and cpu_before.status is ComparisonStatus.EXACT
                and roundtrip.status is ComparisonStatus.EXACT
                and changed.status is ComparisonStatus.DIFFERENT
                and changed.method == "bitwise_full" and budget_rejected
                and retained_bytes == nbytes and released and store.bytes_used == 0
                and observer_handle_reused and observer.checkpoints.bytes_used == 0
                and source_unchanged)
    report = {
        "schema": "scar.gate.g4.checkpoint_pressure", "schema_version": 2,
        "status": "Verified" if verified else "Rejected",
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "revision": revision, "worktree_status": worktree,
        "source_sha256": source_sha, "measured_files": files,
        "source_unchanged": source_unchanged,
        "environment": {"python": sys.version, "executable": sys.executable,
                        "platform": platform.platform(), "torch": str(torch.__version__),
                        "torch_cuda": torch.version.cuda,
                        "device": str(tensor.device),
                        "gpu": torch.cuda.get_device_name(tensor.device) if device == "cuda" else None},
        "configuration": {"numel": args.numel, "dtype": "torch.float32", "seed": args.seed,
                          "warmup": args.warmup, "repetitions": args.repetitions,
                          "prefix_elements": 8, "max_bytes": nbytes,
                          "caller_write_exclusion": "single-threaded local input"},
        "descriptor": _descriptor(tensor),
        "checkpoint": checkpoint,
        "field_reads": _statistics(descriptors),
        "initial_observer_capture_ns": initial_observer_ns,
        "warm_observer_capture": _statistics(captures),
        "explicit_compare": _statistics(comparisons),
        "observer": {"same_live_handle_reused": observer_handle_reused,
                     "checkpoint_payload_bytes": observer.checkpoints.bytes_used,
                     "guard_state": observer.registry.guard(observer_handle).state.value,
                     "logical_versions": len(observer.registry.graph.versions),
                     "materializations": len(observer.registry.graph.materializations)},
        "comparison_statuses": statuses, "checked_bytes": checked_bytes,
        "cuda_synchronized": synchronized,
        "cpu_before": cpu_before.as_dict(), "returned_cpu": roundtrip.as_dict(),
        "outside_prefix_mutation": changed.as_dict(),
        "budget_rejected": budget_rejected, "retained_payload_bytes": retained_bytes,
        "retained_payload_bytes_after_release": store.bytes_used,
        "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 / 1024 if sys.platform == "darwin" else 1),
        "scope": {"field_reads": "Tensor shape/dtype/device/stride/offset access only",
                  "warm_observer_capture": "actual TensorObserver.observe on the same live tensor, including weak lifetime/storage/registry bookkeeping; no explicit checkpoint or CUDA sync",
                  "comparison": "explicit full bitwise at-time verification including requested CUDA synchronization and host staging",
                  "provenance": "not inferred by this measurement",
                  "physical_transfer": "device copy requests performed; physical memcpy not profiled",
                  "speedup": "not measured; operation microcost, not end-to-end tracing overhead"},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": report["status"], "report": str(args.out.resolve()),
                      "field_reads_median_ns": report["field_reads"]["median"],
                      "warm_observer_median_ns": report["warm_observer_capture"]["median"],
                      "checkpoint_median_ns": report["explicit_compare"]["median"]}))
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
