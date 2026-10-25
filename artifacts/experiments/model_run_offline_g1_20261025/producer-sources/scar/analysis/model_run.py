"""Offline orchestration of existing model producers; this is not graph authority.

Metadata planning imports no workload or modeling producer and opens no raw
provider stream. Completed stage directories are immutable; resume retries in a
new attempt and never turns a saved failure into a success.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import gzip
import io
import json
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time


SCHEMA = "scar.model-run/1"


class _RunInterrupted(BaseException):
    pass


def _interrupt(signum, _frame):
    raise _RunInterrupted("external signal " + str(signum))


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


def plan_model_run(capture, *, budget=ModelRunBudget(), _metadata_reader=None):
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
    reader = _metadata_reader if _metadata_reader is not None else _Metadata(root, budget.max_metadata_bytes)
    if reader.root != root or reader.maximum != budget.max_metadata_bytes:
        raise ValueError("metadata reader scope/budget differs")
    run_path = trace / "run.json"
    run = reader.read(run_path)
    command = run.get("command")
    if (type(command) is not list or not command
            or any(type(arg) is not str for arg in command) or not command[0]
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
            "budget_enforcement": _budget_contract(budget),
            "stages": ["capture-import", "source-seeds", "source-inventory", "source-layers",
                       "source-composition", "source-bindings", "workload-witness"],
            "open": ["target exec cwd and command entry are not established",
                     "collector execution-source version and continuous mutation exclusion are not established by G0",
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


def _budget_contract(budget):
    return {
        "metadata": {"maximum": budget.max_metadata_bytes, "mode": "PRE_READ_TOTAL_CAPTURE_METADATA"},
        "raw": {"maximum": budget.max_raw_bytes, "mode": "PER_PUBLIC_API_CALL",
                "cumulative_stored_plus_decoded_io": "OPEN",
                "repeated_reads": "capture import coordinates; fresh source coordinates; seeds; inventory seeds; binding scan"},
        "calls": {"maximum": budget.max_calls,
                  "mode": "METADATA_DECLARATION_THEN_VERIFIED_SEED_INVOCATIONS_POST_SCAN",
                  "scanner_max_events": budget.max_calls * 2},
        "codes_sources": {"mode": "PER_PUBLIC_CALL_TYPED_BUDGET",
                           "max_codes": budget.max_codes, "max_source_files": budget.max_source_files,
                           "max_source_bytes": budget.max_source_bytes},
        "bodies_operations": {"mode": "GLOBAL_REMAINING_ALLOWANCE_IN_INVENTORY_EXPANSION",
                              "max_bodies": budget.max_bodies, "max_operations": budget.max_operations},
        "records": {"maximum": budget.max_record_bytes,
                    "mode": "POST_STAGE_DECODED_DOCUMENT_OR_JSONL_LINE_CHECK_AND_AVAILABLE_API_PARAMETERS"},
        "output": {"maximum": budget.max_output_bytes,
                   "mode": "POST_STAGE_CUMULATIVE_STORED_ATTEMPT_BYTES",
                   "continuous_hard_limit": False, "over_limit": "FAILED_PARTIAL_RETAINED"},
        "wall": {"maximum_seconds": budget.max_seconds,
                 "mode": "BETWEEN_STAGE_CHECK_PLUS_REQUIRED_EXTERNAL_TIMEOUT",
                 "continuous_in_process_limit": False},
        "workload_witness": {"mode": "CODE_WITNESS_STORE_HARD_BUDGET",
                             "max_compile_keys": budget.max_compile_keys,
                             "max_archive_bytes": budget.max_witness_bytes,
                             "source_matching_compilations_in_other_public_producers": "NOT_CHARGED_AS_ARCHIVE_KEYS"},
    }


def _stored_receipt(path):
    before = path.stat()
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        while block := stream.read(1_048_576):
            count += len(block)
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, count) != (after.st_size, after.st_mtime_ns, after.st_size):
        raise ValueError("file changed while hashing: " + str(path))
    return {"uri": str(path), "sha256": digest.hexdigest(), "size_bytes": count}


def _regular_files(root):
    files = []
    for directory, subdirs, names in os.walk(root, followlinks=False):
        for name in subdirs + names:
            path = Path(directory) / name
            _safe(path, root)
            if path.is_symlink():
                raise ValueError("symlink in stage output: " + str(path))
        files.extend(Path(directory) / name for name in names)
        if len(files) > 10_000:
            raise ValueError("stage output file count exceeds 10000")
    return sorted(files)


def _post_stage(attempt, stage, budget):
    files = _regular_files(attempt)
    total = sum(path.stat().st_size for path in files)
    if total > budget.max_output_bytes:
        raise ValueError("post-stage total stored output budget exceeded: " + str(total))
    receipts, decoded = [], 0
    for path in files:
        if not path.is_relative_to(stage):
            continue
        if path.stat().st_size > budget.max_record_bytes:
            raise ValueError("post-stage stored file/record budget exceeded: " + str(path))
        receipt = _stored_receipt(path)
        if path.suffix == ".gz":
            size = 0
            with gzip.open(path, "rb") as stream:
                if path.name.endswith(".jsonl.gz"):
                    while line := stream.readline(budget.max_record_bytes + 1):
                        size += len(line)
                        if len(line) > budget.max_record_bytes:
                            raise ValueError("post-stage decoded JSONL record budget exceeded: " + str(path))
                else:
                    while block := stream.read(min(1_048_576, budget.max_record_bytes - size + 1)):
                        size += len(block)
                        if size > budget.max_record_bytes:
                            raise ValueError("post-stage decoded document budget exceeded: " + str(path))
            receipt["decoded_bytes_checked"] = size
            decoded += size
        receipts.append(receipt)
    return {"stage_outputs": receipts, "attempt_stored_bytes_at_check": total,
            "decoded_output_bytes_read_for_check": decoded,
            "scope": "post-stage snapshot; journal/root bytes written afterward are checked at final publication"}


class _Stages:
    def __init__(self, attempt, result, budget):
        self.attempt, self.result, self.budget = attempt, result, budget
        self.started = time.monotonic()

    def call(self, name, producer, function):
        if time.monotonic() - self.started > self.budget.max_seconds:
            raise TimeoutError("between-stage wall budget exceeded; external timeout is also required")
        stage = self.attempt / (f"{len(self.result['stages']) + 1:02d}-" + name)
        stage.mkdir()
        started = time.monotonic()
        code = Path(sys.modules[producer.__module__].__file__).resolve()
        _publish(stage / "started.json", {"stage": name, "producer": producer.__module__ + "." + producer.__name__,
                                         "producer_source": _stored_receipt(code)})
        record = {"stage": name, "directory": str(stage)}
        self.result["stages"].append(record)
        print(json.dumps({"schema": SCHEMA, "stage": name, "status": "STARTED"}), flush=True)
        try:
            value = function(stage)
            record.update(status="COMPLETED", post_stage=_post_stage(self.attempt, stage, self.budget))
        except BaseException as error:
            record.update(status="FAILED_PARTIAL_RETAINED",
                          failure={"type": type(error).__name__, "detail": str(error)})
            try:
                remaining = _regular_files(self.attempt)
                record["partial_output_stat"] = {"files": len(remaining),
                    "attempt_stored_bytes": sum(path.stat().st_size for path in remaining)}
            except (OSError, ValueError) as stat_error:
                record["partial_output_stat"] = {"status": "UNAVAILABLE", "reason": str(stat_error)}
            raise
        finally:
            record["wall_seconds"] = time.monotonic() - started
            record["terminal"] = _publish(stage / "terminal.json", dict(record))
            print(json.dumps({"schema": SCHEMA, "stage": name, "status": record["status"],
                              "wall_seconds": record["wall_seconds"]}), flush=True)
        return value, stage


def run_model(capture, out, *, plan_only=False, resume=False, budget=ModelRunBudget()):
    """Publish a fresh immutable attempt and a small navigation root.

    Resume preserves every old attempt. It currently recomputes the metadata
    plan rather than trusting serialized stage ownership or success booleans.
    """
    if type(budget) is not ModelRunBudget or type(plan_only) is not bool or type(resume) is not bool:
        raise ValueError("typed budget and exact Boolean options required")
    budget.__post_init__()
    root, cap = Path(out).absolute(), Path(capture).absolute()
    if root != root.resolve() or cap != cap.resolve() or root == cap or root.is_relative_to(cap) or cap.is_relative_to(root):
        raise ValueError("capture/output must be separate canonical paths")
    if root.exists() and not resume:
        raise ValueError("output exists; --resume explicitly creates a fresh attempt")
    if resume and not (root / "model-run.json").is_file():
        raise ValueError("resume requires an existing model-run root")
    root.mkdir(parents=True, exist_ok=True)
    previous, previous_bytes = None, 0
    if resume:
        path = _safe(root / "model-run.json", root)
        if path.stat().st_size > budget.max_metadata_bytes:
            raise ValueError("previous workflow root exceeds metadata budget")
        raw = path.read_bytes()
        previous_bytes = len(raw)
        previous = _decode(raw)
        if previous.get("schema") != SCHEMA or previous.get("capture") != str(cap):
            raise ValueError("resume capture/root schema differs")
    attempts = _safe(root / "attempts", root)
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
              "stages": [], "implementation": inputs["implementation"],
              "resume_policy": "FRESH_ATTEMPT_REPLAY_NO_SERIALIZED_OWNERSHIP_RESTORED",
              "budget_enforcement": _budget_contract(budget)}
    # A killed process may leave only RUNNING plus immutable started/stage
    # records. Resume keeps those bytes and records NO_TERMINAL, not success.
    running = {**result, "status": "RUNNING"}
    if previous:
        running["previous_attempt"] = {"path": previous.get("attempt"),
                                       "status": previous.get("status", "NO_TERMINAL")}
        result["previous_attempt"] = running["previous_attempt"]
    initial = root / (".model-run-start-" + attempt.name + ".json")
    _publish(initial, running)
    os.replace(initial, root / "model-run.json")
    previous_signal = None
    if threading.current_thread() is threading.main_thread():
        previous_signal = signal.signal(signal.SIGTERM, _interrupt)
    metadata_reader = _Metadata(cap, budget.max_metadata_bytes)
    metadata_reader.read_bytes = previous_bytes
    try:
        plan = plan_model_run(cap, budget=budget, _metadata_reader=metadata_reader)
        result["plan"] = _publish(attempt / "plan.json", plan)
        result["open"] = plan["open"]
        result["status"] = plan["status"]
        if not plan_only and not plan["blockers"]:
            result = _execute_stages(cap, attempt, plan, result, budget)
    except BaseException as error:
        result.update(status="FAILED", failure={"type": type(error).__name__, "detail": str(error)})
    finally:
        result["planning_io"] = {"metadata_bytes_read_including_resume_root": metadata_reader.read_bytes,
                                 "raw_bytes_read": 0, "scope": "metadata planning only; G1 repeated provider reads are separate OPEN"}
        if previous_signal is not None:
            signal.signal(signal.SIGTERM, previous_signal)
    result["wall_seconds"] = time.monotonic() - started
    # The approved output ceiling is a post-stage check, including the final
    # terminal/navigation bytes. Preserve a failure receipt on exceedance.
    final_bytes = _canonical(result) + b"\n"
    stored = sum(p.stat().st_size for p in _regular_files(attempt))
    projected_terminal = {"uri": str(attempt / "terminal.json"), "sha256": _sha(final_bytes), "size_bytes": len(final_bytes)}
    projected_root = _canonical({**result, "terminal": projected_terminal}) + b"\n"
    if stored + len(final_bytes) + len(projected_root) > budget.max_output_bytes:
        result.update(status="FAILED", failure={"type": "OutputBudgetExceeded",
                      "detail": "final post-stage cumulative output check failed; partial products retained"})
    terminal = _publish(attempt / "terminal.json", result)
    navigation = {**result, "terminal": terminal}
    temporary = root / (".model-run-" + attempt.name + ".json")
    _publish(temporary, navigation)
    os.replace(temporary, root / "model-run.json")
    return navigation


def _execute_stages(capture, attempt, plan, result, budget):
    # Lazy public imports keep G0 entirely outside raw/modeling producers.
    from scar.trace.capture_import import import_capture
    from scar.trace.capture_coordinates import bind_capture_coordinates
    from scar.analysis.call_seeds import read_call_source_seeds
    from scar.analysis.program_inventory import inventory_program
    from scar.analysis.source_layers import reconstruct_source_layers
    from scar.analysis.program_composition import compose_program, CompositionIndex
    from scar.analysis.source_invocations import bind_source_invocations
    from scar.analysis.code_witness import CodeWitnessStore, CodeWitnessBudget, CodeWitnessUnavailable
    from scar.ir.program.call_edges import CallEdgeBudget, CallLinkStatus
    from scar.ir.program.compilation import CallCompilationProfile
    from scar.ir.program.expansion import ContextStoreBudget
    from scar.ir.program.functions import BodyLoweringProfile
    from scar.ir.record_codec import encode

    stages = _Stages(attempt, result, budget)
    products = result["products"] = {}

    def link(name, path):
        uri = str(path)
        for row in reversed(result["stages"]):
            for receipt in row.get("post_stage", {}).get("stage_outputs", ()):
                if receipt["uri"] == uri:
                    products[name] = receipt
                    return receipt
        raise ValueError("normative stage root was not checked: " + uri)

    def progress(record):
        print(json.dumps({"schema": SCHEMA, "producer_progress": record}, allow_nan=False), flush=True)

    call_budget = CallEdgeBudget(max_raw_bytes=budget.max_raw_bytes,
        max_lines=budget.max_calls * 4 + budget.max_codes + 128,
        max_line_bytes=min(budget.max_record_bytes, budget.max_raw_bytes),
        max_codes=budget.max_codes, max_events=budget.max_calls * 2,
        max_source_files=budget.max_source_files, max_source_bytes=budget.max_source_bytes)
    capture_report, capture_stage = stages.call("capture-import", import_capture,
        lambda stage: import_capture(capture, stage / "model", max_bytes=budget.max_raw_bytes,
            max_lines=200_000, schema_contracts=True, bundle_partitions=True,
            os_interface_work=True, progress=progress))
    link("capture_model", capture_stage / "model" / "capture-model.json")
    result["capture_scope"] = {key: capture_report[key] for key in
        ("run", "processes", "coordinate_identity_consistent", "coverage_obligations")}

    def source_coordinates(stage):
        path = stage / "capture-coordinates.json"
        value = bind_capture_coordinates(capture, max_bytes=budget.max_raw_bytes,
                                        max_lines=200_000, profile_uri=str(path))
        if encode(value.run) != capture_report["run"]:
            raise ValueError("fresh source coordinates changed the imported Run")
        with path.open("xb") as stream:
            stream.write(value.payload)
        return value

    coordinates, coordinate_stage = stages.call("source-coordinates", bind_capture_coordinates, source_coordinates)
    link("source_coordinates", coordinate_stage / "capture-coordinates.json")
    project_root = plan["origins"]["project_root"]["value"]

    def seeds_stage(stage):
        seeds = read_call_source_seeds(capture / "trace", project_root, budget=call_budget,
            compilation_profile=CallCompilationProfile.RECORDED_FUTURE_FLAGS)
        summary = seeds.summary()
        if summary["counts"]["entered_invocations"] > budget.max_calls:
            raise ValueError("verified seed invocation count exceeds call budget")
        _write_document(stage / "source-seeds.json.gz", seeds.to_dict(), budget.max_record_bytes)
        return seeds

    seeds, seed_stage = stages.call("source-seeds", read_call_source_seeds, seeds_stage)
    link("source_seeds", seed_stage / "source-seeds.json.gz")
    result["source_seed_summary"] = seeds.summary()
    verified_links = tuple(row for row in seeds.model.code_links if row.status is CallLinkStatus.VERIFIED)
    paths = sorted({row.snapshot.path for row in verified_links
                    if row.snapshot is not None and Path(row.snapshot.path).suffix == ".py"
                    and Path(row.snapshot.path).is_file()
                    and str(Path(row.snapshot.path).resolve()) == row.snapshot.path})
    result["source_catalog"] = {"qualification": "verified observed code source links; not complete dependency closure",
                                "paths": paths, "producer": products["source_seeds"]}
    if not paths:
        result.update(status="BLOCKED", blockers=["no verified canonical local .py analysis seed"])
        return result
    analysis_seed = paths[0]
    result["analysis_seed"] = {"path": analysis_seed, "qualification": "deterministic verified source; not command-entry proof"}

    def inventory_stage(stage):
        inventory = inventory_program(analysis_seed, project_root=project_root, source_roots=(),
            max_files=budget.max_source_files, max_bytes=budget.max_source_bytes,
            max_lowered_bodies=budget.max_bodies, max_operations=budget.max_operations,
            max_call_witnesses=budget.max_calls, calls_trace=capture / "trace", call_budget=call_budget,
            context_budget=ContextStoreBudget(max_compressed_bytes=budget.max_record_bytes,
                                             max_record_bytes=budget.max_record_bytes),
            body_profile=BodyLoweringProfile.STRUCTURED_ENV)
        _write_document(stage / "inventory.json.gz", inventory.to_dict(), budget.max_record_bytes)
        return inventory.summary()

    inventory_summary, inventory_stage_path = stages.call("source-inventory", inventory_program, inventory_stage)
    inventory_path = inventory_stage_path / "inventory.json.gz"
    link("source_inventory", inventory_path)
    result["source_inventory_summary"] = inventory_summary

    _layer_report, layer_stage = stages.call("source-layers", reconstruct_source_layers,
        lambda stage: reconstruct_source_layers(inventory_path, stage / "layers",
            max_input_bytes=budget.max_record_bytes, max_files=budget.max_source_files,
            max_record_bytes=budget.max_record_bytes, max_total_bytes=budget.max_output_bytes))
    layers = layer_stage / "layers"
    link("source_layers", layers / "index.json")
    composition_summary, composition_stage = stages.call("source-composition", compose_program,
        lambda stage: compose_program(inventory_path, layers, stage / "composition",
            max_input_bytes=budget.max_record_bytes, max_files=budget.max_source_files,
            max_record_bytes=budget.max_record_bytes, max_output_bytes=budget.max_output_bytes,
            progress=progress))
    composition_path = composition_stage / "composition" / "index.json.gz"
    link("source_composition", composition_path)
    result["source_composition_summary"] = composition_summary

    def binding_stage(stage):
        composition = CompositionIndex(composition_path, max_input_bytes=budget.max_record_bytes,
                                       max_record_bytes=budget.max_record_bytes)
        return bind_source_invocations(composition, coordinates, capture / "trace", stage / "bindings",
                                       call_budget=call_budget, witness_mode="same_capture")

    binding_report, binding_stage_path = stages.call("source-bindings", bind_source_invocations, binding_stage)
    link("source_bindings", binding_stage_path / "bindings" / "report.json")
    result["source_binding_summary"] = binding_report["summary"]
    if binding_report.get("schema") != "scar.source-invocations" or binding_report.get("schema_version") != 1:
        raise ValueError("monolithic P0 did not produce the expected genuine source-invocations1")

    def witness_stage(stage):
        witness_budget = CodeWitnessBudget(max_compile_keys=budget.max_compile_keys,
            max_source_files=budget.max_source_files, max_source_bytes=budget.max_source_bytes,
            max_module_bytes=min(budget.max_record_bytes, budget.max_witness_bytes),
            max_archive_bytes=budget.max_witness_bytes, max_manifest_bytes=budget.max_metadata_bytes)
        directory = stage / "archive"
        writer = CodeWitnessStore(directory, budget=witness_budget, create=True, compile_missing=True,
            producer={"profile": "SCAR_OFFLINE_MODEL_RUN_WORKLOAD_WITNESS_V1",
                      "source_seeds": products["source_seeds"],
                      "adapter": result["implementation"]}, progress=progress)
        captured = {row.code.key: row.code for row in seeds.model.codes}
        acquired, frontiers = [], []
        for row in sorted(verified_links, key=lambda item: item.code):
            try:
                _code, proof = writer.resolve(captured[row.code], row.snapshot, row.optimize_levels, allow_compile=True)
            except CodeWitnessUnavailable as error:
                frontiers.append({"code": row.code, "reason": str(error)})
            else:
                acquired.append((row, proof))
        receipt = writer.receipt()
        readonly = CodeWitnessStore(directory, budget=witness_budget)
        if readonly.receipt() != receipt:
            raise ValueError("workload archive changed before read-only consumption")
        for row, proof in acquired:
            _code, actual = readonly.resolve(captured[row.code], row.snapshot, row.optimize_levels, allow_compile=False)
            if actual != proof:
                raise ValueError("read-only workload descriptor proof differs")
        report = {"schema": "scar.model-run-workload-witness/1", "archive": receipt,
                  "acquired_codes": [row.code for row, _proof in acquired], "frontiers": frontiers,
                  "writer_activity": writer.counts, "readonly_activity": readonly.counts,
                  "target_executed": False, "collector_archives_substituted": False}
        _publish(stage / "witness-resolution.json", report)
        return report

    witness_report, witness_stage_path = stages.call("workload-witness", CodeWitnessStore, witness_stage)
    link("workload_witness", witness_stage_path / "archive" / "manifest.json")
    link("workload_witness_resolution", witness_stage_path / "witness-resolution.json")
    result["workload_witness_summary"] = {key: witness_report[key] for key in
        ("acquired_codes", "frontiers", "writer_activity", "readonly_activity")}
    # Confirm the exact declarations that selected this capture. This additional
    # bounded metadata read is explicitly separate from the G0 read accounting.
    checked = 0
    for receipt in plan["input_receipts"]:
        path = _safe(receipt["uri"], capture)
        if path.stat().st_size != receipt["size_bytes"]:
            raise ValueError("capture metadata changed during modeling")
        current = _stored_receipt(path)
        checked += current["size_bytes"]
        if current["sha256"] != receipt["sha256"]:
            raise ValueError("capture metadata changed during modeling")
    result["final_capture_metadata_recheck_bytes"] = checked
    result.update(status="COMPONENTS_LINKED_WITH_OPEN")
    return result


def _write_document(path, document, maximum):
    """Bounded transport of the existing producer's document, no new schema."""
    count = 0
    with Path(path).open("xb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
            with io.BufferedWriter(compressed, buffer_size=65_536) as buffered:
                encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                for token in encoder.iterencode(document):
                    encoded = token.encode("utf-8")
                    count += len(encoded)
                    if count > maximum:
                        raise ValueError("existing document transport record budget exceeded")
                    buffered.write(encoded)
                if count + 1 > maximum:
                    raise ValueError("existing document transport record budget exceeded")
                buffered.write(b"\n")
