#!/usr/bin/env python3
"""Tiny CPU-only probe of PyTorch's public Python-call profiler events.

This script was added to make the earlier capability check reproducible. It
does not run automatically as part of the report/commit and is not a benchmark.
"""

from __future__ import annotations

import json
import platform

import torch
from torch.profiler import ProfilerActivity, profile


def leaf(value: torch.Tensor) -> torch.Tensor:
    return torch.add(value, 1)


def nested(value: torch.Tensor) -> torch.Tensor:
    return leaf(value)


def run(with_stack: bool) -> dict[str, object]:
    value = torch.ones((2,), device="cpu")
    with profile(activities=[ProfilerActivity.CPU], with_stack=with_stack) as prof:
        result = nested(value)
        # Retain only a scalar check; no tensor payload is serialized.
        result.sum().item()

    events = list(prof.events())
    names = [str(event.name) for event in events]
    return {
        "with_stack": with_stack,
        "event_count": len(events),
        "event_names": names,
        "target_python_names_visible": {
            name: any(event_name == name or event_name.endswith("." + name)
                      for event_name in names)
            for name in ("nested", "leaf")
        },
        "event_thread_ids": sorted({int(event.thread) for event in events}),
        "has_cpu_parent_links": any(event.cpu_parent is not None for event in events),
    }


def main() -> None:
    result = {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "runs": [run(False), run(True)],
        "note": "Capability probe only; event names/timing are not a SCAR CodeID or operand binding.",
    }
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
