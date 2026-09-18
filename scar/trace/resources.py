"""Low-dependency process and GPU resource sampling for trace runs.

The sampler is deliberately optional.  It records an evidence stream beside
the execution events, so measurements can be reported separately from the
instrumented wall-clock trace and never become a legality proof by themselves.
CPU process time comes from ``/proc``; GPU utilization and memory come from the
existing ``nvidia-smi`` command when it is available.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


def _proc_cpu_seconds(pid: int) -> float | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        # The comm field can contain spaces and parentheses. Everything after
        # the final ") " starts at the state field (field 3).
        fields = raw.rsplit(") ", 1)[1].split()
        user_ticks = int(fields[11])  # field 14
        system_ticks = int(fields[12])  # field 15
        return (user_ticks + system_ticks) / float(os.sysconf("SC_CLK_TCK"))
    except (OSError, IndexError, ValueError, TypeError):
        return None


def _gpu_snapshot() -> list[dict[str, Any]]:
    command = [
        "nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=1.0, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    values: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        columns = [column.strip() for column in line.split(",")]
        if len(columns) != 4:
            continue
        try:
            values.append({
                "index": int(columns[0]),
                "utilization_gpu_percent": float(columns[1]),
                "memory_used_mib": float(columns[2]),
                "memory_total_mib": float(columns[3]),
            })
        except (TypeError, ValueError):
            continue
    return values


class ResourceSampler:
    """Sample resources for one traced process until :meth:`stop` is called."""

    def __init__(self, out: str | Path, *, pid: int | None = None,
                 interval_s: float = 0.1):
        if interval_s <= 0:
            raise ValueError("resource sampling interval must be positive")
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.pid = int(pid or os.getpid())
        self.interval_s = float(interval_s)
        self.path = self.out / "resources.jsonl"
        self.summary_path = self.out / "resources.summary.json"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._file = None
        self._started_ns: int | None = None
        self._sample_count = 0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._file = self.path.open("a", buffering=1, encoding="utf-8")
        self._started_ns = time.perf_counter_ns()
        self._thread = threading.Thread(target=self._run, name="scar-resource-sampler",
                                         daemon=True)
        self._thread.start()

    def _run(self) -> None:
        previous_cpu = _proc_cpu_seconds(self.pid)
        previous_ns = time.perf_counter_ns()
        while not self._stop.is_set():
            self._stop.wait(self.interval_s)
            now_ns = time.perf_counter_ns()
            cpu = _proc_cpu_seconds(self.pid)
            elapsed_s = max((now_ns - previous_ns) / 1e9, 1e-9)
            cpu_util = None
            if cpu is not None and previous_cpu is not None:
                cpu_util = max(0.0, (cpu - previous_cpu) / elapsed_s * 100.0
                               / max(os.cpu_count() or 1, 1))
            sample = {
                "ts_ns": now_ns,
                "pid": self.pid,
                "cpu_process_seconds": cpu,
                "cpu_utilization_percent": cpu_util,
                "gpu": _gpu_snapshot(),
                "evidence": "Observed",
            }
            if self._file is not None:
                self._file.write(json.dumps(sample, separators=(",", ":")) + "\n")
            self._sample_count += 1
            previous_cpu, previous_ns = cpu, now_ns

    def stop(self) -> dict[str, Any]:
        if self._thread is None:
            return {"enabled": False, "status": "NotCollected"}
        self._stop.set()
        self._thread.join(timeout=max(1.0, self.interval_s * 4))
        if self._file is not None:
            self._file.close()
        samples: list[dict[str, Any]] = []
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        samples.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        cpu_values = [float(item["cpu_utilization_percent"]) for item in samples
                      if item.get("cpu_utilization_percent") is not None]
        gpu_values = [gpu for item in samples for gpu in item.get("gpu", [])]
        gpu_util = [float(item["utilization_gpu_percent"]) for item in gpu_values
                    if item.get("utilization_gpu_percent") is not None]
        gpu_memory = [float(item["memory_used_mib"]) for item in gpu_values
                      if item.get("memory_used_mib") is not None]
        summary: dict[str, Any] = {
            "enabled": True,
            "status": "Observed" if samples else "UNKNOWN",
            "pid": self.pid,
            "sample_count": len(samples),
            "interval_s": self.interval_s,
            "started_ns": self._started_ns,
            "ended_ns": time.perf_counter_ns(),
            "cpu_utilization_percent": {
                "average": sum(cpu_values) / len(cpu_values) if cpu_values else None,
                "peak": max(cpu_values) if cpu_values else None,
            },
            "gpu_utilization_percent": {
                "average": sum(gpu_util) / len(gpu_util) if gpu_util else None,
                "peak": max(gpu_util) if gpu_util else None,
            },
            "gpu_memory_used_mib": {
                "peak": max(gpu_memory) if gpu_memory else None,
                "average": sum(gpu_memory) / len(gpu_memory) if gpu_memory else None,
            },
            "gpu_count_observed": len({item.get("index") for item in gpu_values}),
            "evidence": "Observed",
        }
        self.summary_path.write_text(json.dumps(summary, indent=2) + "\n",
                                     encoding="utf-8")
        return summary


__all__ = ["ResourceSampler"]
