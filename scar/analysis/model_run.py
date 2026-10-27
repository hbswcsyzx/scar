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


@dataclass(frozen=True)
class DependencyRunBudget:
    """Independent source-only profile; never substitutes bootstrap defaults."""

    max_metadata_bytes: int = 2_000_000
    max_raw_bytes: int = 64_000_000
    max_record_bytes: int = 64_000_000
    max_output_bytes: int = 128_000_000
    max_calls: int = 512
    max_codes: int = 16
    max_source_files: int = 6
    max_source_bytes: int = 1_000_000
    max_roots: int = 8
    max_metadata_entries: int = 4096
    max_provider_metadata_files: int = 512
    max_provider_metadata_bytes: int = 16_000_000
    max_provider_metadata_record_bytes: int = 4_000_000
    max_archive_record_bytes: int = 64_000_000
    max_archive_bytes: int = 256_000_000
    max_report_bytes: int = 8_000_000
    max_compile_variants: int = 21
    max_context_compressed_bytes: int = 128_000_000
    max_context_record_bytes: int = 64_000_000
    max_compile_keys: int = 21
    max_witness_bytes: int = 32_000_000
    max_seconds: int = 180

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in asdict(self).values()):
            raise ValueError("dependency-run budgets must be positive exact integers")


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


def _publish(path, document, *, maximum=None):
    raw = _canonical(document) + b"\n"
    if maximum is not None and len(raw) > maximum:
        raise ValueError("orchestration report byte budget exceeded")
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


def run_model(capture, out, *, plan_only=False, resume=False, budget=ModelRunBudget(), source_only=False):
    """Publish a fresh immutable attempt and a small navigation root.

    Resume preserves every old attempt. It currently recomputes the metadata
    plan rather than trusting serialized stage ownership or success booleans.
    """
    if type(budget) is not ModelRunBudget or type(plan_only) is not bool or type(resume) is not bool or type(source_only) is not bool:
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
              "plan_only": plan_only, "source_only": source_only, "whole_model_established": False,
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
            result = (_execute_source_bootstrap(cap, attempt, plan, result, budget) if source_only
                      else _execute_stages(cap, attempt, plan, result, budget))
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

    retention = coordinates.report.get('retention', {})
    native_storage = capture_report.get('native_bundle_storage', {})
    if retention.get('mode') == 'lossless_archive' and native_storage.get('kind') == 'partitioned':
        from scar.trace.native_port_sidecar import build_native_port_publication
        members = [row for row in coordinates.report['membership']
                   if row['artifact']['schema'] == 'pytorch.execution-trace.v1']
        if len(members) != 1:
            raise ValueError('native port stage needs one original ETO membership')
        member = members[0]
        source = member.get('local_path', member['artifact']['uri'])
        port_index, port_stage = stages.call('native-ports', build_native_port_publication,
            lambda stage: build_native_port_publication(source, capture / 'archive-index.json',
                retention['archive_sha256'], Path(native_storage['manifest']).parent, stage / 'ports'))
        port_receipt = link('native_ports', port_stage / 'ports' / 'index.json')
        result['native_port_summary'] = {'source_nodes': port_index.source_nodes,
            'operation_rows': port_index.operation_rows, 'input_ports': port_index.input_ports,
            'output_ports': port_index.output_ports, 'classification_counts': port_index.classification_counts,
            'whole_model_established': False}
        from scar.trace.native_reference_flow import build_native_reference_flow_publication
        reference_index, reference_stage = stages.call('native-reference-flow', build_native_reference_flow_publication,
            lambda stage: build_native_reference_flow_publication(port_stage / 'ports',
                Path(native_storage['manifest']).parent, stage / 'references',
                expected_native_port_index_sha256=port_receipt['sha256']))
        reference_receipt = link('native_reference_flow', reference_stage / 'references' / 'index.json')
        result['native_reference_summary'] = {
            'reference_ports': reference_index.reference_ports,
            'ports_with_one_original_edge': reference_index.ports_with_one_original_edge,
            'groups_with_input_and_output': reference_index.groups_with_input_and_output,
            'ordering_basis': 'ETO_SOURCE_ORDINAL_ONLY',
            'content_versions_or_causal_def_use_proved': False, 'whole_model_established': False}
        from scar.trace.native_operator_value_interface import build_native_operator_value_declaration_publication
        (value_index, _), value_stage = stages.call('native-operator-values',
            build_native_operator_value_declaration_publication,
            lambda stage: build_native_operator_value_declaration_publication(port_stage / 'ports',
                Path(native_storage['manifest']).parent, reference_stage / 'references', stage / 'values',
                expected_native_port_index_sha256=port_receipt['sha256'],
                expected_reference_flow_index_sha256=reference_receipt['sha256']))
        link('native_operator_values', value_stage / 'values' / 'index.json')
        result['native_operator_value_summary'] = {
            'operation_rows': value_index.operation_rows,
            'ports': value_index.input_ports + value_index.output_ports,
            'tensor_ports': value_index.tensor_input_ports + value_index.tensor_output_ports,
            'persisted_value_graph_records': 0, 'whole_model_established': False}
    else:
        result['native_port_scope'] = 'not generated: this route lacks a lossless ETO archive or partitioned bundle'
    return _execute_source_stages(capture, attempt, plan, result, budget, stages, products,
                                  coordinates, link, progress)


def _execute_source_bootstrap(capture, attempt, plan, result, budget):
    """The ordinary source stages without native import or a target execution."""
    from scar.trace.capture_coordinates import bind_capture_coordinates
    stages = _Stages(attempt, result, budget)
    products = result["products"] = {}
    result["partial_route"] = "SOURCE_BOOTSTRAP_ONLY"
    def link(name, path):
        for row in reversed(result['stages']):
            for receipt in row.get('post_stage', {}).get('stage_outputs', ()):
                if receipt['uri'] == str(path):
                    products[name] = receipt
                    return receipt
        raise ValueError('normative source stage root was not checked: ' + str(path))
    def progress(record):
        print(json.dumps({'schema': SCHEMA, 'producer_progress': record}, allow_nan=False), flush=True)
    def coordinate_stage(stage):
        path = stage / 'capture-coordinates.json'
        coordinates = bind_capture_coordinates(capture, max_bytes=budget.max_raw_bytes,
                                              max_lines=200_000, profile_uri=str(path))
        with path.open('xb') as stream:
            stream.write(coordinates.payload)
        return coordinates
    coordinates, directory = stages.call('source-coordinates', bind_capture_coordinates, coordinate_stage)
    link('source_coordinates', directory / 'capture-coordinates.json')
    return _execute_source_stages(capture, attempt, plan, result, budget, stages, products,
                                  coordinates, link, progress, source_only=True)


def _execute_source_stages(capture, attempt, plan, result, budget, stages, products,
                           coordinates, link, progress, *, source_only=False):
    from scar.analysis.call_seeds import _read_call_source_seeds
    from scar.analysis.call_demand import _SourceWorkspace, inventory_from_calls
    from scar.analysis.program_inventory import inventory_program
    from scar.analysis.source_layers import reconstruct_source_layers
    from scar.analysis.program_composition import compose_program, CompositionIndex
    from scar.analysis.source_invocations import bind_source_invocations
    from scar.analysis.code_witness import CodeWitnessStore, CodeWitnessBudget, CodeWitnessUnavailable
    from scar.ir.program.call_edges import CallEdgeBudget, CallLinkStatus
    from scar.ir.program.compilation import CallCompilationProfile
    from scar.ir.program.expansion import ContextStoreBudget
    from scar.ir.program.functions import BodyLoweringProfile
    from scar.ir.program.inventory import InventoryBudget
    call_budget = CallEdgeBudget(max_raw_bytes=budget.max_raw_bytes,
        max_lines=budget.max_calls * 4 + budget.max_codes + 128,
        max_line_bytes=min(budget.max_record_bytes, budget.max_raw_bytes),
        max_codes=budget.max_codes, max_events=budget.max_calls * 2,
        max_source_files=budget.max_source_files, max_source_bytes=budget.max_source_bytes)
    context_budget = ContextStoreBudget(max_compressed_bytes=budget.max_record_bytes,
                                       max_record_bytes=budget.max_record_bytes)
    project_root = plan['origins']['project_root']['value']
    with _SourceWorkspace(project_root, context_budget) as workspace:
        try:
            return _build_source_stages(capture, plan, result, budget, stages, products,
                                        coordinates, link, progress, call_budget, workspace, source_only)
        finally:
            if workspace.captured_session is not None:
                try:
                    result['source_input_scope'] = workspace.captured_session.report()
                finally:
                    workspace.captured_session.close()


def _build_source_stages(capture, plan, result, budget, stages, products, coordinates,
                         link, progress, call_budget, workspace, source_only):
    from scar.analysis.call_seeds import _read_call_source_seeds
    from scar.analysis.captured_source_owner import CapturedSourceBudget
    from scar.analysis.call_demand import inventory_from_calls
    from scar.analysis.program_inventory import inventory_program
    from scar.analysis.source_layers import reconstruct_source_layers
    from scar.analysis.program_composition import compose_program, CompositionIndex
    from scar.analysis.source_invocations import bind_source_invocations
    from scar.analysis.code_witness import CodeWitnessStore, CodeWitnessBudget, CodeWitnessUnavailable
    from scar.ir.program.call_edges import CallLinkStatus
    from scar.ir.program.compilation import CallCompilationProfile
    from scar.ir.program.expansion import ContextStoreBudget
    from scar.ir.program.functions import BodyLoweringProfile
    from scar.ir.program.inventory import InventoryBudget
    project_root = plan["origins"]["project_root"]["value"]

    def seeds_stage(stage):
        seeds = _read_call_source_seeds(capture / "trace", project_root, budget=call_budget,
            compilation_profile=CallCompilationProfile.RECORDED_FUTURE_FLAGS,
            _source_workspace=workspace, coordinates=coordinates,
            captured_source_budget=CapturedSourceBudget(
                max_metadata_bytes=min(budget.max_metadata_bytes, call_budget.max_raw_bytes),
                max_rows_bytes=call_budget.max_raw_bytes,
                max_row_bytes=min(budget.max_record_bytes, call_budget.max_line_bytes),
                max_files=call_budget.max_codes, max_source_bytes=call_budget.max_raw_bytes,
                max_codes=call_budget.max_codes, max_code_bytes=call_budget.max_raw_bytes))
        summary = seeds.summary()
        if summary["counts"]["entered_invocations"] > budget.max_calls:
            raise ValueError("verified seed invocation count exceeds call budget")
        _write_document(stage / "source-seeds.json.gz", seeds.to_dict(), budget.max_record_bytes)
        return seeds

    seeds, seed_stage = stages.call("source-seeds", _read_call_source_seeds, seeds_stage)
    link("source_seeds", seed_stage / "source-seeds.json.gz")
    result["source_seed_summary"] = seeds.summary()
    verified_links = tuple(row for row in seeds.model.code_links if row.status is CallLinkStatus.VERIFIED)
    paths = sorted({row.snapshot.path for row in verified_links
                    if row.snapshot is not None and Path(row.snapshot.path).suffix == ".py"
                    and ((workspace.captured_session is not None
                          and workspace.captured_session.has_path(row.snapshot.path))
                         or (Path(row.snapshot.path).is_file()
                             and str(Path(row.snapshot.path).resolve()) == row.snapshot.path))})
    result["source_catalog"] = {"qualification": "verified observed code source links; not complete dependency closure",
                                "paths": paths, "producer": products["source_seeds"]}
    if not paths:
        result.update(status="BLOCKED", blockers=["no verified canonical local .py analysis seed"])
        return result
    analysis_seed = paths[0]
    result["analysis_seed"] = {"path": analysis_seed, "qualification": "deterministic verified source; not command-entry proof"}

    def inventory_stage(stage):
        if workspace.captured_session is not None:
            inventory = inventory_from_calls(analysis_seed, project_root=project_root, source_roots=(),
                budget=InventoryBudget(max_files=budget.max_source_files, max_bytes=budget.max_source_bytes,
                    max_lowered_bodies=budget.max_bodies, max_operations=budget.max_operations,
                    max_call_witnesses=budget.max_calls),
                call_trace=capture / 'trace', call_budget=call_budget,
                context_budget=ContextStoreBudget(max_compressed_bytes=budget.max_record_bytes,
                                                 max_record_bytes=budget.max_record_bytes),
                body_profile=BodyLoweringProfile.STRUCTURED_ENV,
                _seed_report=seeds, _workspace=workspace, coordinates=coordinates)
        else:
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
            max_record_bytes=budget.max_record_bytes, max_total_bytes=budget.max_output_bytes,
            captured_source_session=workspace.captured_session))
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

    if not source_only:
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
    else:
        result['source_binding_scope'] = 'NOT_ATTEMPTED_SOURCE_BOOTSTRAP_ONLY'

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
                if workspace.captured_session is not None:
                    writer.admit_captured_source(row.snapshot, captured=captured[row.code],
                        source_owner=workspace.captured_session.owner)
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
    result.update(status="SOURCE_BOOTSTRAP_WITH_OPEN" if source_only else "COMPONENTS_LINKED_WITH_OPEN")
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


class _PinnedModelInputs:
    """Small JSON inputs only; reading never restores an owned model object."""

    def __init__(self, maximum):
        self.maximum, self.stored_bytes, self.decoded_bytes = maximum, 0, 0
        self.receipts = []

    def read(self, path, expected=None):
        path = Path(path).absolute()
        if path != path.resolve() or not path.is_file():
            raise ValueError("model input must be a canonical regular file")
        size = path.stat().st_size
        required = size if path.suffix == ".gz" else size * 2
        if required > self.maximum - self.stored_bytes - self.decoded_bytes:
            raise ValueError("small model input stored+decoded budget exceeded")
        if expected is not None and (expected.get("uri") != str(path)
                or type(expected.get("size_bytes")) is not int or expected["size_bytes"] != size
                or re.fullmatch(r"[0-9a-f]{64}", str(expected.get("sha256", ""))) is None):
            raise ValueError("model input receipt/path/size differs")
        with path.open("rb") as stream:
            raw = stream.read(size)
        self.stored_bytes += len(raw)
        if len(raw) != size or path.stat().st_size != size:
            raise ValueError("model input changed during read")
        receipt = {"uri": str(path), "size_bytes": size, "sha256": _sha(raw)}
        if expected is not None and receipt["sha256"] != expected["sha256"]:
            raise ValueError("model input stored SHA differs")
        if path.suffix == ".gz":
            remaining = self.maximum - self.stored_bytes - self.decoded_bytes
            with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as stream:
                decoded = stream.read(remaining + 1)
        else:
            decoded = raw
        self.decoded_bytes += len(decoded)
        # A gzip overflow probe is explicitly charged, including its one byte.
        if self.stored_bytes + self.decoded_bytes > self.maximum:
            raise ValueError("small model input stored+decoded budget exceeded (overflow probe charged)")
        receipt["decoded_bytes"] = len(decoded)
        self.receipts.append(receipt)
        return _decode(decoded), receipt


def _source_catalog(model):
    captures, groups = {}, {}
    for row in model["codes"]:
        key = row["process_id"], row["code"]["key"]
        if key in captures:
            raise ValueError("duplicate original captured-code identity")
        captures[key] = row
    for row in model["groups"]:
        key = row["process_id"], row["code"]
        if key in groups or type(row["count"]) is not int or row["count"] < 1:
            raise ValueError("invalid original entered-code group")
        groups[key] = row
    return [{"process_id": key[0], "code": key[1], "captured_code": captures[key]["code"] if key in captures else None,
             "descriptor_anchor": captures[key]["anchor"] if key in captures else None, "entered_invocations": group["count"],
             "first_anchor": group["first_anchor"], "last_anchor": group["last_anchor"]}
            for key, group in sorted(groups.items())]


def _dependency_base(path, reader):
    path = Path(path).absolute()
    if path.is_dir():
        path = path / "model-run.json"
    document, declaration = reader.read(path)
    if document.get("schema") != SCHEMA:
        raise ValueError("unsupported model-run input schema")
    if "terminal" in document:
        expected = document["terminal"]
        attempt = Path(document["attempt"])
        if attempt.parent != path.parent / "attempts" or expected.get("uri") != str(attempt / "terminal.json"):
            raise ValueError("navigation terminal is outside its exact attempt")
        terminal, terminal_receipt = reader.read(expected["uri"], expected)
        if _canonical(document) != _canonical({**terminal, "terminal": expected}):
            raise ValueError("navigation differs from its immutable terminal")
    else:
        terminal, terminal_receipt = document, declaration
        if path.name != "terminal.json" or str(path.parent) != terminal.get("attempt"):
            raise ValueError("direct model input must be its immutable attempt terminal")
    # These checks constrain scope/representation. No success boolean grants
    # evidence; the new dependency producer independently checks the raw scan.
    if terminal.get("schema") != SCHEMA or terminal.get("partial_route") != "MONOLITHIC_BOOTSTRAP":
        raise ValueError("dependency source stage requires an original bootstrap context")
    capture = Path(terminal["capture"])
    if not capture.is_absolute() or capture != capture.resolve():
        raise ValueError("original capture path is not canonical")
    original_attempt = Path(terminal["attempt"])
    seed_ref = terminal["products"]["source_seeds"]
    seed_path = _safe(seed_ref["uri"], original_attempt)
    seeds, seed_receipt = reader.read(seed_path, seed_ref)
    if (seeds.get("schema") != "scar.call-source-seeds" or type(seeds.get("schema_version")) is not int
            or seeds["schema_version"] != 2 or seeds.get("compilation_profile") != "RECORDED_FUTURE_FLAGS_V1"
            or seeds.get("target_executed_by_resolver") is not False):
        raise ValueError("original seeds lack their exact recorded-flags profile")
    model = seeds["model"]
    if model["trace_directory"] != str(capture / "trace"):
        raise ValueError("original seed trace is outside the selected capture")
    project = Path(model["project_root"])
    if not project.is_absolute() or str(project) == project.anchor or project != project.resolve():
        raise ValueError("original project boundary is invalid")
    binding_ref = terminal["products"]["source_bindings"]
    binding_path = _safe(binding_ref["uri"], original_attempt)
    binding, binding_receipt = reader.read(binding_path, binding_ref)
    if (binding.get("schema") != "scar.source-invocations" or type(binding.get("schema_version")) is not int
            or binding["schema_version"] != 1 or _canonical(binding["trace_files"]) != _canonical(model["files"])):
        raise ValueError("bootstrap binding and seed raw manifests differ")
    return {"input": declaration, "terminal": terminal_receipt, "source_seeds": seed_receipt,
            "source_bindings": binding_receipt, "raw_collection_metadata": binding["collection_metadata"],
            "raw_scan_issues": binding["raw_scan_issues"],
            "capture": str(capture), "project_root": str(project), "catalog": _source_catalog(model),
            "seed_model": model, "original_binding_summary": binding["summary"],
            "original_products": terminal["products"]}


def _verify_dependency_scope(report, base):
    model = base["seed_model"]
    if (report.get("schema") != "scar.dependency-source-admissions" or type(report.get("schema_version")) is not int
            or report["schema_version"] != 1
            or report["program_root"] != base["project_root"] or report["trace_directory"] != model["trace_directory"]
            or _canonical(report["trace_files"]) != _canonical(model["files"])
            or _canonical(report["collection_metadata"]) != _canonical(base["raw_collection_metadata"])
            or _canonical(report["raw_scan_issues"]) != _canonical(base["raw_scan_issues"])):
        raise ValueError("dependency admission changed the original raw/source scope")
    actual = {(row["process_id"], row["code"]): row for row in report["admissions"]}
    if len(actual) != len(report["admissions"]) or len(actual) != len(base["catalog"]):
        raise ValueError("dependency admission changed the entered-code denominator")
    for original in base["catalog"]:
        row = actual.get((original["process_id"], original["code"]))
        if row is None or _canonical({field: row[field] for field in original}) != _canonical(original):
            raise ValueError("dependency admission changed descriptor, anchor or call weight")
    if report["summary"]["entered_invocations"] != sum(row["entered_invocations"] for row in base["catalog"]):
        raise ValueError("dependency admission changed the original invocation denominator")


def _dependency_budget_contract(budget):
    return {"profile": "INDEPENDENT_DEPENDENCY_SOURCE_PROFILE",
        "input_metadata": "pre-read stored and bounded decoded accounting; one-byte gzip overflow probe charged",
        "raw": {"max_bytes_per_public_scan": budget.max_raw_bytes, "cumulative_input_stored_plus_decoded_io": "OPEN"},
        "source_metadata_archive_compile": "independent CallEdgeBudget/DependencySourceBudget/ContextStoreBudget hard limits; frontiers retained",
        "report": {"max_bytes": budget.max_report_bytes, "mode": "producer admissions bound; orchestration report post-check"},
        "record": {"max_bytes": budget.max_record_bytes, "mode": "post-stage check plus producer archive-record limits"},
        "output": {"max_stored_bytes": budget.max_output_bytes, "mode": "post-stage current-attempt total; not a continuous limit"},
        "witness": {"max_compile_keys": budget.max_compile_keys, "max_archive_bytes": budget.max_witness_bytes,
                    "mode": "CodeWitnessStore hard bounds; independent of source matcher compile variants"},
        "wall": {"max_seconds": budget.max_seconds, "mode": "between stages plus required external timeout"}}


def run_dependency_admission(model_run_path, out, *, plan_only=False, resume=False,
                             budget=DependencyRunBudget(), budget_sources=None):
    """Publish source fragments/witness only; never re-run bootstrap producers."""
    if type(budget) is not DependencyRunBudget or type(plan_only) is not bool or type(resume) is not bool:
        raise ValueError("dependency stage requires typed budget and exact Boolean options")
    budget.__post_init__()
    root, source = Path(out).absolute(), Path(model_run_path).absolute()
    if root != root.resolve() or source != source.resolve():
        raise ValueError("source/output paths must be canonical")
    if source.is_dir():
        source = source / "model-run.json"
    if root == source.parent or root.is_relative_to(source.parent) or source.is_relative_to(root):
        raise ValueError("source-only output cannot overlap the original model")
    if root.exists() and not resume:
        raise ValueError("source-only output exists; --resume requires a fresh attempt")
    fields = asdict(budget)
    sources = {name: "API_BUDGET_OBJECT" for name in fields} if budget_sources is None else dict(budget_sources)
    if set(sources) != set(fields) or any(type(value) is not str or not value for value in sources.values()):
        raise ValueError("budget configuration provenance must cover every independent field")
    root.mkdir(parents=True, exist_ok=True)
    attempts = _safe(root / "attempts", root)
    attempts.mkdir(exist_ok=True)
    attempt = attempts / (str(time.time_ns()) + "-" + str(os.getpid()))
    attempt.mkdir()
    started = time.monotonic()
    result = {"schema": SCHEMA, "attempt": str(attempt), "partial_route": "DEPENDENCY_SOURCE_ONLY",
              "status": "RUNNING", "stages": [], "products": {}, "plan_only": plan_only,
              "whole_model_established": False, "target_executed": False,
              "implementation": _implementation_receipts(), "budget": fields, "budget_sources": sources,
              "budget_enforcement": _dependency_budget_contract(budget),
              "resume_policy": "FRESH_SOURCE_ONLY_ATTEMPT; BOOTSTRAP_IS_NOT_REPLAYED",
              "open": ["source admission is not body connectivity or a new inventory",
                       "entry catalog, partitioned proof handoff and ordinary binding remain unconnected",
                       "module entry, frozen provider and original tooling root require independent evidence",
                       "ordered runtime data/state/content, object identity, ready and whole ProgramModel remain OPEN"]}
    reader = _PinnedModelInputs(budget.max_metadata_bytes)
    previous = None
    if resume:
        previous, _receipt = reader.read(_safe(root / "model-run.json", root))
        if previous.get("schema") != SCHEMA or previous.get("partial_route") != "DEPENDENCY_SOURCE_ONLY":
            raise ValueError("resume requires a source-only workflow root")
        result["previous_attempt"] = {"path": previous["attempt"], "status": previous["status"]}
    _publish(attempt / "started.json", {"from_model_run": str(source), "budget": fields,
        "budget_sources": sources, "implementation": result["implementation"]})
    _update_navigation(root, attempt, result)
    old_signal = signal.signal(signal.SIGTERM, _interrupt) if threading.current_thread() is threading.main_thread() else None
    try:
        base = _dependency_base(source, reader)
        capture = Path(base["capture"])
        if root == capture or root.is_relative_to(capture) or capture.is_relative_to(root):
            raise ValueError("source-only output overlaps the original capture")
        if previous is not None and previous.get("input_terminal") != base["terminal"]:
            raise ValueError("source-only resume changed the immutable original terminal")
        result.update(capture=base["capture"], input_terminal=base["terminal"],
                      source_seed_input=base["source_seeds"], source_binding_input=base["source_bindings"],
                      original_binding_summary=base["original_binding_summary"])
        catalog = base["catalog"]
        counts = {"captured_codes": len(base["seed_model"]["codes"]), "entered_code_groups": len(catalog),
                  "entered_invocations": sum(row["entered_invocations"] for row in catalog)}
        result["original_denominators"] = counts
        blockers = []
        if counts["captured_codes"] > budget.max_codes or counts["entered_invocations"] > budget.max_calls:
            blockers.append("original source cohort exceeds independent code/call budget")
        result["plan"] = _publish(attempt / "plan.json", {"schema": "scar.model-run-dependency-plan/1",
            "input_terminal": base["terminal"], "source_seeds": base["source_seeds"], "project_root": base["project_root"],
            "catalog": catalog, "denominators": counts, "budget": fields, "budget_sources": sources,
            "namespace_policy": "original project boundary; current public producer roots; unresolved tooling is not remapped",
            "blockers": blockers, "raw_bytes_read": 0, "canonical_bodies_established": False}, maximum=budget.max_report_bytes)
        result["status"] = "BLOCKED" if blockers else "METADATA_PLANNED_WITH_OPEN"
        if not plan_only and not blockers:
            _execute_dependency_stages(base, attempt, result, budget)
    except BaseException as error:
        result.update(status="FAILED", failure={"type": type(error).__name__, "detail": str(error)})
    finally:
        result["planning_io"] = {"stored_metadata_bytes_read": reader.stored_bytes,
                                 "decoded_metadata_bytes": reader.decoded_bytes,
                                 "scope": "small workflow inputs only; source producer I/O is separate"}
        result["input_receipts"] = reader.receipts
        if old_signal is not None:
            signal.signal(signal.SIGTERM, old_signal)
    result["wall_seconds"] = time.monotonic() - started
    final = _canonical(result) + b"\n"
    stored = sum(p.stat().st_size for p in _regular_files(attempt))
    projected = {"uri": str(attempt / "terminal.json"), "size_bytes": len(final), "sha256": _sha(final)}
    if (len(final) > budget.max_report_bytes or stored + len(final)
            + len(_canonical({**result, "terminal": projected})) + 1 > budget.max_output_bytes):
        result.update(status="FAILED", failure={"type": "PostStageBudgetExceeded",
            "detail": "orchestration report/output post-check exceeded; partial products retained"})
    terminal = _publish(attempt / "terminal.json", result)
    navigation = {**result, "terminal": terminal}
    _update_navigation(root, attempt, navigation)
    return navigation


def _update_navigation(root, attempt, document):
    temporary = root / (".model-run-" + str(time.time_ns()) + "-" + attempt.name + ".json")
    _publish(temporary, document)
    os.replace(temporary, root / "model-run.json")


def _execute_dependency_stages(base, attempt, result, budget):
    from scar.analysis.dependency_sources import DependencySourceBudget, admit_dependency_sources
    from scar.analysis.code_witness import CodeWitnessBudget, CodeWitnessStore, CodeWitnessUnavailable
    from scar.ir.program.call_edges import CallEdgeBudget, CapturedCode, CodeSourceLink, CallLinkStatus
    from scar.ir.program.expansion import ContextStoreBudget
    from scar.ir.record_codec import decode

    stages = _Stages(attempt, result, budget)
    calls = CallEdgeBudget(max_raw_bytes=budget.max_raw_bytes, max_codes=budget.max_codes,
        max_events=budget.max_calls * 2, max_lines=budget.max_calls * 4 + budget.max_codes + 128,
        max_line_bytes=min(budget.max_record_bytes, budget.max_raw_bytes),
        max_source_files=budget.max_source_files, max_source_bytes=budget.max_source_bytes)
    admission_budget = DependencySourceBudget(max_roots=budget.max_roots,
        max_metadata_entries=budget.max_metadata_entries, max_metadata_files=budget.max_provider_metadata_files,
        max_metadata_bytes=budget.max_provider_metadata_bytes,
        max_metadata_record_bytes=budget.max_provider_metadata_record_bytes,
        max_archive_record_bytes=budget.max_archive_record_bytes, max_archive_bytes=budget.max_archive_bytes,
        max_report_bytes=budget.max_report_bytes, max_compile_variants=budget.max_compile_variants)
    contexts = ContextStoreBudget(max_compressed_bytes=budget.max_context_compressed_bytes,
                                  max_record_bytes=budget.max_context_record_bytes)

    def progress(row):
        print(json.dumps({"schema": SCHEMA, "producer_progress": row}, allow_nan=False), flush=True)

    def link(name, path):
        for stage in reversed(result["stages"]):
            for receipt in stage.get("post_stage", {}).get("stage_outputs", ()):
                if receipt["uri"] == str(path):
                    result["products"][name] = receipt
                    return receipt
        raise ValueError("dependency product has no checked stored receipt")

    def admit(stage):
        report = admit_dependency_sources(Path(base["capture"]) / "trace", base["project_root"], stage / "admissions",
            call_budget=calls, budget=admission_budget, context_budget=contexts, progress=progress)
        _verify_dependency_scope(report, base)
        return report

    report, admission_stage = stages.call("dependency-sources", admit_dependency_sources, admit)
    admission_receipt = link("dependency_admissions", admission_stage / "admissions" / "admissions.json")
    result["dependency_summary"] = report["summary"]
    result["dependency_measurements"] = report["measurements"]
    result["source_roots"] = report["source_roots"]
    result["root_frontiers"], result["provider_frontiers"] = report["root_frontiers"], report["provider_frontiers"]

    def witness(stage):
        limits = CodeWitnessBudget(max_compile_keys=budget.max_compile_keys,
            max_source_files=budget.max_source_files, max_source_bytes=budget.max_source_bytes,
            max_module_bytes=min(budget.max_record_bytes, budget.max_witness_bytes),
            max_archive_bytes=budget.max_witness_bytes, max_manifest_bytes=budget.max_metadata_bytes)
        archive = stage / "archive"
        writer = CodeWitnessStore(archive, budget=limits, create=True, compile_missing=True,
            producer={"profile": "SCAR_OFFLINE_DEPENDENCY_WITNESS_V1", "admissions": admission_receipt,
                      "adapter": result["implementation"]}, progress=progress)
        acquired, frontiers = [], []
        for index, row in enumerate(report["admissions"]):
            if row["status"] != "SOURCE_VERIFIED":
                continue
            captured = decode(CapturedCode, row["captured_code"])
            source = decode(CodeSourceLink, row["code_source_link"])
            if source.status is not CallLinkStatus.VERIFIED or source.code != captured.key or source.snapshot is None:
                raise ValueError("admission claims a contradictory verified source witness")
            origin = {"artifact": admission_receipt, "pointer": "#/admissions/" + str(index),
                      "source_root": row["source_root"], "process_id": row["process_id"], "code": row["code"]}
            try:
                _code, proof = writer.resolve(captured, source.snapshot, source.optimize_levels, allow_compile=True)
            except CodeWitnessUnavailable as error:
                frontiers.append({"origin": origin, "reason": str(error)})
            else:
                acquired.append((captured, source, proof, origin))
        receipt = writer.receipt()
        readonly = CodeWitnessStore(archive, budget=limits)
        if readonly.receipt() != receipt:
            raise ValueError("dependency archive changed before read-only consumption")
        for captured, source, proof, _origin in acquired:
            _code, actual = readonly.resolve(captured, source.snapshot, source.optimize_levels, allow_compile=False)
            if actual != proof:
                raise ValueError("dependency read-only complete descriptor proof differs")
        document = {"schema": "scar.model-run-workload-witness/1", "scope": "dependency source fragments only",
                    "archive": receipt, "acquired": [origin for _code, _source, _proof, origin in acquired],
                    "frontiers": frontiers, "writer_activity": writer.counts, "readonly_activity": readonly.counts,
                    "body_connectivity_established": False, "target_executed": False}
        _publish(stage / "witness-resolution.json", document, maximum=budget.max_report_bytes)
        return document

    witnesses, witness_stage = stages.call("dependency-witness", CodeWitnessStore, witness)
    link("dependency_workload_witness", witness_stage / "archive" / "manifest.json")
    link("dependency_witness_resolution", witness_stage / "witness-resolution.json")
    result["dependency_witness_summary"] = {key: witnesses[key] for key in
        ("acquired", "frontiers", "writer_activity", "readonly_activity")}
    result["next_interface"] = {"entry_catalog": "UNCONNECTED", "partitioned_proof_handoff": "UNCONNECTED",
        "ordinary_new_source_binding": "NOT_RUN", "canonical_body_publication": "NOT_RUN",
        "ordered_runtime_data_state": "OPEN", "original_binding_facts_changed": False}
    result["status"] = "DEPENDENCY_SOURCE_FRAGMENTS_WITH_OPEN"
