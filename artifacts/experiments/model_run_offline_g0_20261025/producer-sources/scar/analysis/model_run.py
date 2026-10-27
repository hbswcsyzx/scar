"""Offline orchestration of existing model producers; this is not graph authority.

Metadata planning imports no workload or modeling producer and opens no raw
provider stream. Completed stage directories are immutable; resume retries in a
new attempt and never turns a saved failure into a success.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time


SCHEMA = "scar.model-run/1"


@dataclass(frozen=True)
class ModelRunBudget:
    max_metadata_bytes: int = 2_000_000
    max_raw_bytes: int = 64_000_000
    max_record_bytes: int = 64_000_000
    max_output_bytes: int = 128_000_000
    max_calls: int = 256
    max_codes: int = 128
    max_source_files: int = 4
    max_source_bytes: int = 256_000
    max_bodies: int = 4
    max_operations: int = 4000
    max_seconds: int = 180
    max_compile_keys: int = 4
    max_witness_bytes: int = 16_000_000

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in asdict(self).values()):
            raise ValueError("model-run budgets must be positive exact integers")


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _decode(raw):
    def invalid(value):
        raise ValueError("non-finite JSON token: " + value)
    result = json.loads(raw, object_pairs_hook=_unique_pairs, parse_constant=invalid)
    if type(result) is not dict:
        raise ValueError("metadata must be a JSON object")
    return result


def _safe(path, root):
    path = Path(path).absolute()
    if path != path.resolve() or not path.is_relative_to(root):
        raise ValueError("noncanonical or escaped path: " + str(path))
    return path


def _publish(path, document):
    raw = _canonical(document) + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(raw)
    return {"uri": str(path), "sha256": _sha(raw), "size_bytes": len(raw)}


class _Metadata:
    def __init__(self, root, maximum):
        self.root, self.maximum, self.read_bytes = root, maximum, 0
        self.receipts = []

    def read(self, path):
        path = _safe(path, self.root)
        size = path.stat().st_size
        if not path.is_file() or size > self.maximum - self.read_bytes:
            raise ValueError("metadata total input byte budget exceeded: " + str(path))
        with path.open("rb") as stream:
            raw = stream.read(size)
        self.read_bytes += len(raw)
        if len(raw) != size or path.stat().st_size != size:
            raise ValueError("metadata changed while reading: " + str(path))
        document = _decode(raw)
        self.receipts.append({"uri": str(path), "sha256": _sha(raw),
                              "size_bytes": len(raw), "schema": document.get("schema")})
        return document


def _one(directory, pattern):
    # Bound directory enumeration too. This never opens the matching payloads.
    matches = []
    with os.scandir(directory) as entries:
        for ordinal, entry in enumerate(entries):
            if ordinal >= 4096:
                raise ValueError("capture metadata directory entry budget exceeded")
            if re.fullmatch(pattern, entry.name):
                matches.append(Path(entry.path))
    if len(matches) != 1:
        raise ValueError("expected one metadata declaration: " + pattern)
    return matches[0]


def plan_model_run(capture, *, budget=ModelRunBudget()):
    """Read at most max_metadata_bytes; raw membership remains unverified.

    A returned plan contains declarations, never owned CaptureCoordinates. Its
    origins refer to the exact original metadata file and field. Missing cwd or
    entry never falls back to this analyzer's cwd.
    """
    if type(budget) is not ModelRunBudget:
        raise ValueError("budget must be ModelRunBudget")
    budget.__post_init__()
    root = Path(capture).absolute()
    if root != root.resolve() or not root.is_dir():
        raise ValueError("capture must be a canonical directory")
    trace = _safe(root / "trace", root)
    if not trace.is_dir() or not _safe(root / "os", root).is_dir():
        raise ValueError("P0 requires the retained trace/ and os/ capture layout")
    reader = _Metadata(root, budget.max_metadata_bytes)
    run_path = trace / "run.json"
    run = reader.read(run_path)
    command = run.get("command")
    if (type(command) is not list or not command
            or any(type(arg) is not str or not arg for arg in command)
            or type(run.get("returncode")) is not int or run["returncode"] != 0):
        raise ValueError("P0 requires a successful explicit launcher command")
    native_path = _one(trace, r"execution-evidence\.[1-9][0-9]*\.json")
    native = reader.read(native_path)
    pid = native.get("pid")
    if (native.get("schema") != "scar.execution-evidence-collection"
            or type(native.get("schema_version")) is not int or native["schema_version"] != 1
            or native.get("status") != "CLOSED" or native.get("failures") != []
            or type(pid) is not int or pid < 1
            or native_path.name != f"execution-evidence.{pid}.json"):
        raise ValueError("unsupported or unsuccessful native collector metadata")
    meta_path = trace / f"call-meta.{pid}.json"
    meta = reader.read(meta_path)
    project_root = meta.get("project_root")
    if (meta.get("schema") != "scar.call-edge-trace" or type(meta.get("schema_version")) is not int
            or meta["schema_version"] != 1 or meta.get("process_id") != pid
            or type(project_root) is not str or not Path(project_root).is_absolute()
            or str(Path(project_root).resolve()) != project_root or project_root == "/"):
        raise ValueError("call metadata lacks a canonical recorded project boundary")
    if meta.get("python") != sys.version:
        raise ValueError("captured Python version differs from the source analyzer")
    archive_path = root / "archive-index.json"
    archive = reader.read(archive_path)
    if (archive.get("schema") != "scar.lossless-capture-archive"
            or type(archive.get("schema_version")) is not int or archive["schema_version"] != 1
            or archive.get("verified_roundtrip") is not True or type(archive.get("files")) is not list):
        raise ValueError("unsupported retained archive declaration")
    declared_raw = 0
    seen = set()
    for item in archive["files"]:
        if (type(item) is not dict or type(item.get("raw_bytes")) is not int
                or item["raw_bytes"] < 0 or type(item.get("logical_path")) is not str
                or item["logical_path"] in seen):
            raise ValueError("invalid/duplicate archive member declaration")
        seen.add(item["logical_path"])
        declared_raw += item["raw_bytes"]
    declared_calls, declared_codes = meta.get("invocations"), meta.get("codes")
    blockers = []
    for name, value, maximum in (("raw_bytes", declared_raw, budget.max_raw_bytes),
                                  ("calls", declared_calls, budget.max_calls),
                                  ("codes", declared_codes, budget.max_codes)):
        if type(value) is not int or value < 0:
            blockers.append("invalid declared " + name)
        elif value > maximum:
            blockers.append("declared " + name + " exceeds G1 budget")
    # Native declarations carry source artifact URIs. Coordinate binding, not
    # this metadata reader, is responsible for their membership and relocation.
    artifacts = native.get("artifacts", {})
    if type(artifacts) is not dict:
        raise ValueError("native artifacts declaration must be an object")
    source_catalog = {"status": "DEFERRED_VERIFIED_CALL_SEEDS", "sources": None}
    origins = {
        "command": {"value": command, "uri": str(run_path), "field": "/command",
                    "qualification": "launcher declaration"},
        "target_exec_cwd": {"value": None, "status": "OPEN",
                            "reason": "run.json does not witness target exec cwd"},
        "command_entry": {"value": None, "status": "OPEN",
                          "reason": "not inferred from arbitrary argv or analyzer cwd"},
        "analysis_seed": {"value": None, "status": "DEFERRED_VERIFIED_CALL_SEEDS",
                          "rule": "lexically first canonical verified local .py source link; not __main__"},
        "project_root": {"value": project_root, "uri": str(meta_path), "field": "/project_root",
                         "qualification": "recorded call analysis boundary; not cwd/sys.path"},
        "workload_code_witness": {"status": "FRESH_OWNED_ACQUISITION_PLANNED",
                                  "collector_archives_substituted": False},
        "native_artifacts": {"value": artifacts, "uri": str(native_path), "field": "/artifacts",
                             "qualification": "declared only; G1 coordinate binder checks bytes"},
    }
    return {"schema": "scar.model-run-plan/1", "capture": str(root),
            "status": "BLOCKED" if blockers else "METADATA_PLANNED_WITH_OPEN", "blockers": blockers,
            "input_receipts": reader.receipts, "origins": origins, "source_catalog": source_catalog,
            "declared": {"process_id": pid, "raw_bytes": declared_raw,
                         "calls": declared_calls, "codes": declared_codes},
            "budget": asdict(budget), "io": {"metadata_bytes_read": reader.read_bytes,
                                              "raw_bytes_read": 0},
            "stages": ["capture-import", "source-seeds", "source-inventory", "source-layers",
                       "source-composition", "source-bindings", "workload-witness"],
            "open": ["target exec cwd and command entry are not established",
                     "raw membership and provider contracts await public coordinate/import checks",
                     "static dependency closure and observed sources await public source discovery",
                     "monolithic P0 is not the partitioned production/SourceFrontend path",
                     "native V2 and unified scope ledger are not connected by P0",
                     "data/state/object identity/readiness and whole ProgramModel remain OPEN"],
            "target_executed": False, "whole_model_established": False}


def _implementation_receipts():
    paths = (Path(__file__).resolve(), Path(__file__).resolve().parents[1] / "cli.py")
    return [{"uri": str(p), "sha256": _sha(p.read_bytes()), "size_bytes": p.stat().st_size}
            for p in paths]


def run_model(capture, out, *, plan_only=False, resume=False, budget=ModelRunBudget()):
    """Publish a fresh immutable attempt and a small navigation root.

    Resume preserves every old attempt. It currently recomputes the metadata
    plan rather than trusting serialized stage ownership or success booleans.
    """
    root, cap = Path(out).absolute(), Path(capture).absolute()
    if root != root.resolve() or cap != cap.resolve() or root == cap or root.is_relative_to(cap) or cap.is_relative_to(root):
        raise ValueError("capture/output must be separate canonical paths")
    if root.exists() and not resume:
        raise ValueError("output exists; --resume explicitly creates a fresh attempt")
    if resume and not (root / "model-run.json").is_file():
        raise ValueError("resume requires an existing model-run root")
    root.mkdir(parents=True, exist_ok=True)
    previous = None
    if resume:
        path = root / "model-run.json"
        if path.stat().st_size > budget.max_metadata_bytes:
            raise ValueError("previous workflow root exceeds metadata budget")
        raw = path.read_bytes()
        previous = _decode(raw)
        if previous.get("schema") != SCHEMA or previous.get("capture") != str(cap):
            raise ValueError("resume capture/root schema differs")
    attempts = root / "attempts"
    attempts.mkdir(exist_ok=True)
    attempt = attempts / (str(time.time_ns()) + "-" + str(os.getpid()))
    attempt.mkdir()
    started = time.monotonic()
    inputs = {"capture": str(cap), "budget": asdict(budget), "plan_only": plan_only,
              "implementation": _implementation_receipts(),
              "previous_attempt": previous.get("attempt") if previous else None}
    _publish(attempt / "started.json", inputs)
    result = {"schema": SCHEMA, "capture": str(cap), "attempt": str(attempt),
              "plan_only": plan_only, "whole_model_established": False,
              "target_executed": False, "partial_route": "MONOLITHIC_BOOTSTRAP",
              "stages": [], "implementation": inputs["implementation"]}
    try:
        plan = plan_model_run(cap, budget=budget)
        result["plan"] = _publish(attempt / "plan.json", plan)
        result["open"] = plan["open"]
        result["status"] = plan["status"]
        if not plan_only and not plan["blockers"]:
            result = _execute_stages(cap, attempt, plan, result, budget)
    except BaseException as error:
        result.update(status="FAILED", failure={"type": type(error).__name__, "detail": str(error)})
    result["wall_seconds"] = time.monotonic() - started
    terminal = _publish(attempt / "terminal.json", result)
    navigation = {**result, "terminal": terminal}
    temporary = root / (".model-run-" + attempt.name + ".json")
    _publish(temporary, navigation)
    os.replace(temporary, root / "model-run.json")
    return navigation


def _execute_stages(capture, attempt, plan, result, budget):
    # G0 is independently usable while the existing public G1 chain is wired.
    result.update(status="BLOCKED", blockers=["G1 public stage wiring is not yet implemented"])
    return result
