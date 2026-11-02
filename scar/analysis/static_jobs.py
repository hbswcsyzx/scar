"""One current analyzer-task record, separate from the program being modeled.

This records construction progress and terminal outcomes, not runtime program
events. A missing terminal write never establishes successful publication.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import traceback
import uuid


SCHEMA = "scar.static-link-task"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _process(pid):
    """Linux process start identity; PID alone is unsafe after process reuse."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return "STOPPED", None
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        return "LIVE", {"pid": pid, "start_ticks": int(fields[19]), "boot_id": boot}
    except FileNotFoundError:
        return "STOPPED", None
    except (OSError, ValueError, IndexError):
        return "UNKNOWN", None


def read_static_link_task(path):
    """Report stored state and independently checked current process liveness."""
    path = Path(path).absolute()
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("static task path must not traverse symlinks")
    record = json.loads(path.read_bytes())
    if record.get("schema") != SCHEMA or record.get("schema_version") != 1:
        raise ValueError("unrecognized static task record")
    result = dict(record)
    if record["state"] == "RUNNING":
        status, identity = _process(record["process"]["pid"])
        if status == "STOPPED" or status == "LIVE" and identity != record["process"]:
            result["observed_state"] = "STOPPED_WITHOUT_TERMINAL_RECORD"
        else:
            result["observed_state"] = "RUNNING" if status == "LIVE" else "UNKNOWN_LIVENESS"
    else:
        result["observed_state"] = record["state"]
    return result


class StaticLinkTask:
    """Throttle activity writes; always flush publication, failure or interrupt."""

    def __init__(self, directory, *, input_manifest_sha256, budget, family="calls"):
        output = Path(directory).absolute()
        if family not in ("calls", "classes"):
            raise ValueError("unknown static relation task family")
        self.family = family
        self.path = output.parent / ("static-link-task.json" if family == "calls" else "static-class-link-task.json")
        if self.path.parent.resolve() != self.path.parent or self.path.is_symlink():
            raise ValueError("static task record must remain in its owned parent")
        if self.path.exists():
            previous = read_static_link_task(self.path)
            if previous["observed_state"] in ("RUNNING", "UNKNOWN_LIVENESS"):
                raise RuntimeError("another static linking task has no verified terminal state")
        status, identity = _process(os.getpid())
        if status != "LIVE":
            raise RuntimeError("cannot establish this analyzer process identity")
        self.started = time.monotonic()
        self.last_write = float("-inf")
        self.record = {"schema": SCHEMA, "schema_version": 1,
            "task_id": uuid.uuid4().hex, "process": identity,
            "family": family,
            "model": str(output), "input_manifest_sha256": input_manifest_sha256,
            "state": "RUNNING", "started_at": _now(), "activity": {"stage": "PREPARING"},
            "budget": asdict(budget) if is_dataclass(budget) else budget}
        self._write(force=True)

    def _write(self, *, force=False):
        now = time.monotonic()
        if not force and now - self.last_write < 1:
            return
        self.record.update(updated_at=_now(), elapsed_seconds=now - self.started)
        handle, temporary = tempfile.mkstemp(prefix=".static-link-task-", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf8") as stream:
                json.dump(self.record, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
                stream.write("\n")
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self.last_write = now

    def activity(self, event):
        self.record["activity"] = dict(event)
        self._write()

    def published(self, manifest, output_manifest_sha256):
        publication = manifest["static_" + self.family]
        if self.family == "calls":
            result = {key: publication[key] for key in ("complete", "status", "scope", "counts", "published_calls")}
        else:
            complete = publication["scope"]["enumeration_complete"]
            result = {"complete": complete,
                "status": "ENUMERATED_WITH_RELATION_FRONTIERS" if complete else "PARTIAL_ENUMERATION",
                "scope": publication["scope"], "counts": publication["counts"], "issue": publication["issue"]}
        self.record.update(state="PUBLISHED", ended_at=_now(),
            output_manifest_sha256=output_manifest_sha256,
            result={**result, "frontier_counts": dict(Counter(row["kind"] for row in publication["frontiers"]))},
            whole_program_model_complete=False)
        self._write(force=True)

    def failed(self, error):
        self.record.update(state="INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "FAILED",
            ended_at=_now(), error={"type": type(error).__name__, "message": str(error),
                "traceback_tail": "".join(traceback.format_exception(error))[-16000:]})
        self._write(force=True)
