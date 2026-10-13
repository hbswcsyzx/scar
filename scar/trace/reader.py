"""Read JSONL traces back into the IR."""
from __future__ import annotations

import json
from pathlib import Path

from scar.ir import Effect, Event, ExecutionGraph, Knowledge
from .files import open_text, resolve


def load(path: str | Path) -> ExecutionGraph:
    path = Path(path)
    graph = ExecutionGraph()
    events_file = resolve(path, default_name="events.jsonl")
    with open_text(events_file) as stream:
        for line in stream:
            if not line.strip():
                continue
            raw = json.loads(line)
            effect_raw = raw.pop("effect", {})
            for key in ("rng_effect", "may_raise", "external_effect", "ordering_effect"):
                value = effect_raw.get(key, "UNKNOWN")
                try:
                    effect_raw[key] = Knowledge(value)
                except ValueError:
                    effect_raw[key] = Knowledge.UNKNOWN
            raw.pop("index", None)
            graph.add(Event(effect=Effect(**effect_raw), **raw))
    return graph

