"""Bind retained collector artifacts to shared execution coordinates.

This bounded profile checks an existing calls/operands + ETO/Kineto + strace
capture, including optional function-environment sidecars. Artifact bytes,
exact OS file-creation/exec receipts and collector
manifests establish membership under explicit capture contracts.  Neither PID
equality nor nearby timestamps establishes membership.  Python thread ident,
ETO thread tokens and GPU lanes are not Linux native TIDs.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import gzip
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re

from scar.ir.execution.common import EvidencePoint
from scar.ir.execution.coordinates import ExecutionRun, HostThreadInstance, ProcessInstance, UnresolvedHostThread
from scar.ir.execution.ids import HostThreadInstanceID, ProcessInstanceID, RunID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import encode


_PROFILE = "RETAINED_COLLECTOR_PROCESS_MEMBERSHIP_V1"
_CALL = re.compile(r"^\d+(?:\.\d+)?\s+([A-Za-z0-9_]+)\((.*)\)\s+=\s+(-?(?:0x[0-9a-fA-F]+|[0-9]+))(.*)$")
_OS_NAME = re.compile(r"syscalls\.([1-9][0-9]*)$")
_MANIFEST_NAME = re.compile(r"execution-evidence\.([1-9][0-9]*)\.json$")
_SELECTED = frozenset(("execve", "execveat", "open", "openat", "openat2", "rename", "renameat",
                       "renameat2", "stat", "stat64", "newfstatat", "clone", "clone3", "fork", "vfork"))


def _need(condition, message):
    if not condition:
        raise ValueError("capture coordinates: " + message)


def _pairs(items):
    result = {}
    for key, value in items:
        _need(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _json(payload):
    def invalid(value):
        raise ValueError("capture coordinates: nonfinite JSON constant " + value)
    return json.loads(payload, object_pairs_hook=_pairs, parse_constant=invalid)


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _key(artifact):
    return artifact.sha256, artifact.size_bytes


def _fact(artifact, line):
    return ProviderFactReference(artifact, "#/lines/" + str(line))


def _quoted(value):
    try:
        result = _json(value)
    except (ValueError, UnicodeError):
        return None
    return result if type(result) is str else None


@dataclass(slots=True)
class CaptureCoordinates:
    run: ExecutionRun
    processes: tuple[ProcessInstance, ...]
    threads: tuple[HostThreadInstance, ...]
    target_process: ProcessInstance
    artifact: ProviderArtifact
    payload: bytes
    report: dict
    _process_members: dict = field(repr=False)
    _os_threads: dict = field(repr=False)
    _native_artifacts: frozenset = field(repr=False)

    def process_for(self, artifact, pid):
        """Resolve only a verified artifact/selector pair; no PID fallback."""
        if type(artifact) is not ProviderArtifact or not _integer(pid, 1):
            return None
        return self._process_members.get((_key(artifact), pid))

    def thread_for(self, artifact, token, namespace):
        """Return proved native coordinates or an explicit unresolved thread."""
        process = None
        if type(artifact) is ProviderArtifact:
            if namespace == "linux_native_tid" and _integer(token, 1):
                thread = self._os_threads.get((_key(artifact), token))
                if thread is not None:
                    return thread
            process = self.process_for(artifact, token) if _integer(token, 1) else None
            if process is None and _key(artifact) in self._native_artifacts:
                process = self.target_process
            source = ProviderFactReference(artifact, "#")
        else:
            source = ProviderFactReference(self.artifact, "#/open")
        return UnresolvedHostThread(
            "no verified mapping for thread namespace " + str(namespace)
            + "; Python ident, ETO tokens and device lanes cannot be equated to native TID",
            EvidencePoint(self.run.id, process.id if process is not None else None, source))

    def to_dict(self):
        return self.report


class _Files:
    def __init__(self, root, original_root, archive, maximum):
        self.root, self.original_root, self.maximum = root, original_root, maximum
        self.entries, self.verified, self.total = {}, {}, 0
        for entry in archive["files"] if archive is not None else ():
            _need(type(entry) is dict, "archive file entry is not an object")
            logical = PurePosixPath(entry["logical_path"])
            actual = PurePosixPath(entry["actual_path"])
            _need(logical.is_absolute() and actual.is_absolute() and ".." not in logical.parts
                  and ".." not in actual.parts, "archive paths are not canonical absolute paths")
            _need(logical.is_relative_to(original_root) and actual.is_relative_to(original_root),
                  "archive member is outside the collector-declared original capture root")
            _need(str(logical) not in self.entries, "duplicate archive logical path")
            _need(re.fullmatch(r"[0-9a-f]{64}", entry.get("raw_sha256", "")) is not None
                  and re.fullmatch(r"[0-9a-f]{64}", entry.get("gzip_sha256", "")) is not None
                  and _integer(entry.get("raw_bytes")) and _integer(entry.get("compressed_bytes")),
                  "archive entry has no exact raw/compressed hash and size")
            self.entries[str(logical)] = entry

    def contains(self, logical):
        """Check only this root's explicit retained namespace, never another URI."""
        logical = PurePosixPath(logical)
        _need(logical.is_relative_to(self.original_root) and ".." not in logical.parts,
              "requested artifact escapes the original capture namespace")
        entry = self.entries.get(str(logical))
        actual = PurePosixPath(entry["actual_path"]) if entry is not None else logical
        local = self.root / str(actual.relative_to(self.original_root))
        _need(not local.is_symlink() and local.resolve().is_relative_to(self.root),
              "mapped artifact is a symlink or escapes capture root")
        # A declared but missing sidecar is an invalid retained capture, not an
        # optional collector that never ran. Let the later exact verification
        # report the missing/non-file member.
        return entry is not None or local.exists()

    def os_names(self):
        """Enumerate original OS names; compressed files require archive entries."""
        names = {logical for logical in self.entries
                 if PurePosixPath(logical).parent == self.original_root / "os"
                 and _OS_NAME.fullmatch(PurePosixPath(logical).name)}
        directory = self.root / "os"
        _need(not directory.is_symlink() and directory.resolve().is_relative_to(self.root),
              "OS artifact directory is a symlink or escapes capture root")
        if directory.is_dir():
            names.update(str(self.original_root / "os" / path.name)
                         for path in directory.iterdir() if _OS_NAME.fullmatch(path.name))
        return sorted(names)

    def local(self, logical):
        logical = PurePosixPath(logical)
        _need(logical.is_relative_to(self.original_root) and ".." not in logical.parts,
              "requested artifact escapes the original capture namespace")
        entry = self.entries.get(str(logical))
        actual = PurePosixPath(entry["actual_path"]) if entry is not None else logical
        selected = self.root / str(actual.relative_to(self.original_root))
        local = selected.resolve()
        _need(not selected.is_symlink() and local.is_relative_to(self.root) and local.is_file(),
              "mapped local artifact is absent, symlinked or escapes capture root")
        return local, entry

    def verify(self, logical, schema):
        logical = str(logical)
        if logical in self.verified:
            original = self.verified[logical]
            return ProviderArtifact(original.uri, original.sha256, original.size_bytes, schema)
        local, entry = self.local(logical)
        digest, size = sha256(), 0
        opener = gzip.open if local.suffix == ".gz" else open
        with opener(local, "rb") as source:
            while payload := source.read(1024 * 1024):
                size += len(payload); digest.update(payload)
                _need(self.total + size <= self.maximum, "decompressed capture byte budget exceeded")
        self.total += size
        if entry is not None:
            _need(entry["raw_sha256"] == digest.hexdigest() and entry["raw_bytes"] == size,
                  "archive raw hash/byte count differs for " + logical)
            compressed = sha256()
            with local.open("rb") as source:
                while payload := source.read(1024 * 1024):
                    compressed.update(payload)
            _need(entry["gzip_sha256"] == compressed.hexdigest() and entry["compressed_bytes"] == local.stat().st_size,
                  "archive compressed hash/byte count differs for " + logical)
        # The raw evidence identity keeps its collector-declared logical URI.
        # Compression/relocation belongs to retention, not to this execution's
        # identity. Verified local paths are published separately for readers.
        artifact = ProviderArtifact(logical, digest.hexdigest(), size, schema)
        self.verified[logical] = artifact
        return artifact

    def document(self, logical, schema, limit=2_000_000):
        artifact = self.verify(logical, schema)
        _need(artifact.size_bytes <= limit, "collector metadata exceeds its fixed bound")
        local, _ = self.local(str(logical))
        opener = gzip.open if local.suffix == ".gz" else open
        with opener(local, "rb") as source:
            document = _json(source.read(limit + 1))
        _need(type(document) is dict, "collector metadata is not an object")
        return document, artifact


def _python_target_members(files, trace_root, pid, members, project_root):
    """Bind retained bytes and their issuer; call semantics use the v2 reader."""
    events = trace_root / f"python-call-targets.{pid}.jsonl"
    metadata = trace_root / f"python-call-target-meta.{pid}.json"
    present = files.contains(events)
    _need(present == files.contains(metadata), "Python target events and metadata must be retained together")
    if not present:
        return None, []
    document, declaration = files.document(metadata, "scar.python-call-target-collection")
    fields = {"schema", "schema_version", "capabilities", "process_id", "project_root", "scope_policy",
              "budget", "counts", "stopped", "file", "legacy_inputs",
              "receiver_is_separate_from_monitoring_arg0", "contents_state_ready_or_complete_program_established"}
    _need(set(document) == fields and document["schema"] == "scar.python-call-target-collection"
          and type(document["schema_version"]) is int and document["schema_version"] == 2
          and type(document["process_id"]) is int and document["process_id"] == pid
          and document["capabilities"] == ["PYTHON_CALL_TARGETS_V2", "OBSERVED_PYTHON_CALLEE_SCOPE_V1"]
          and document["scope_policy"] == "OBSERVED_EXACT_PYTHON_CALLEES_V1"
          and document["project_root"] == project_root
          and type(document["stopped"]) is bool
          and document["receiver_is_separate_from_monitoring_arg0"] is True
          and document["contents_state_ready_or_complete_program_established"] is False,
          "unsupported Python target collection/issuer")
    counts, budget = document["counts"], document["budget"]
    _need(type(counts) is dict and set(counts) == {"TARGET", "ENTRY", "GAP"}
          and all(_integer(v) for v in counts.values()) and type(budget) is dict
          and set(budget) == {"max_records", "max_bytes", "max_selected_codes"}
          and all(_integer(v, 1) for v in budget.values()), "invalid Python target counts/budgets")
    file = document["file"]
    _need(type(file) is dict and set(file) == {"path", "bytes", "sha256", "rows"}
          and file["path"] == str(events) and _integer(file["bytes"]) and _integer(file["rows"])
          and file["rows"] == sum(counts.values()) and file["rows"] <= budget["max_records"]
          and file["bytes"] <= budget["max_bytes"], "Python target event declaration differs")
    artifact = files.verify(events, "scar.python-call-targets.v2")
    _need((artifact.sha256, artifact.size_bytes) == (file["sha256"], file["bytes"]),
          "Python target retained bytes differ")
    expected = {family: trace_root / name for family, name in (
        ("codes", f"call-codes.{pid}.jsonl"), ("events", f"call-events.{pid}.jsonl"),
        ("meta", f"call-meta.{pid}.json"), ("operands", f"call-operands.{pid}.jsonl"),
        ("operand-meta", f"call-operand-meta.{pid}.json"))}
    legacy = document["legacy_inputs"]
    _need(type(legacy) is list and len(legacy) == len(expected)
          and all(type(row) is dict and set(row) == {"path", "family", "process_id", "raw_sha256", "raw_bytes", "lines"}
                  for row in legacy)
          and {row["family"] for row in legacy} == set(expected), "Python target legacy manifest differs")
    for row in legacy:
        name = str(expected[row["family"]])
        original = members[name]
        _need(row["path"] == name and type(row["process_id"]) is int and row["process_id"] == pid
              and _integer(row["raw_bytes"]) and _integer(row["lines"])
              and (row["raw_sha256"], row["raw_bytes"]) == (original.sha256, original.size_bytes),
              "Python targets refer to different original frame/operand bytes")
    members[str(events)], members[str(metadata)] = artifact, declaration
    return {"capability": "SCAR_PYTHON_CALL_TARGET_MEMBERSHIP_V2", "manifest": encode(declaration),
            "events": encode(artifact), "declared_counts": counts,
            "collector_stopped": document["stopped"], "call_ports_established": False}, [str(events), str(metadata)]


def _stream_interface_members(files, trace_root, pid, members, project_root):
    """Retained resource-interface bytes, not content or canonical-call proof."""
    events = trace_root / f'stream-interfaces.{pid}.jsonl'
    metadata = trace_root / f'stream-interface-meta.{pid}.json'
    present = files.contains(events)
    _need(present == files.contains(metadata), 'stream events and metadata must be retained together')
    if not present:
        return None, []
    doc, declaration = files.document(metadata, 'scar.stream-interface-collection')
    _need(doc.get('schema') == 'scar.stream-interface-collection' and type(doc.get('schema_version')) is int
          and doc['schema_version'] == 1 and doc.get('profile') == 'SCAR_BUILTIN_STREAM_INTERFACES_V1'
          and type(doc.get('process_id')) is int and doc['process_id'] == pid
          and doc.get('project_root') == project_root and type(doc.get('stopped')) is bool
          and type(doc.get('errors')) is list and doc.get('tensor_or_stream_contents_read') is False
          and doc.get('file_descriptor_table_replayed') is False
          and doc.get('source_body_or_content_proof_established') is False,
          'stream interface profile/issuer differs')
    counts = doc.get('counts')
    _need(type(counts) is dict and set(counts) == {'BEGIN', 'C_RETURN', 'C_RAISE', 'UNOBSERVED'}
          and all(_integer(v) for v in counts.values()), 'stream interface counts differ')
    artifact = files.verify(events, 'scar.stream-interfaces.events.v1')
    ref = doc['file']
    _need(ref.get('uri') == str(events) and ref.get('sha256') == artifact.sha256
          and ref.get('size_bytes') == artifact.size_bytes and ref.get('rows') == sum(counts.values()),
          'stream event receipt differs')
    legacy = doc['legacy_inputs']
    expected = {'codes': f'call-codes.{pid}.jsonl', 'events': f'call-events.{pid}.jsonl',
                'meta': f'call-meta.{pid}.json', 'operands': f'call-operands.{pid}.jsonl',
                'operand-meta': f'call-operand-meta.{pid}.json'}
    _need(type(legacy) is list and len(legacy) == len(expected)
          and {r.get('family') for r in legacy} == set(expected), 'stream legacy input families differ')
    for row in legacy:
        name = str(trace_root / expected[row['family']])
        original = members[name]
        _need(row['path'] == name and row['process_id'] == pid
              and (row['raw_sha256'], row['raw_bytes']) == (original.sha256, original.size_bytes),
              'stream sidecar refers to different original CALL/frame inputs')
    members[str(events)], members[str(metadata)] = artifact, declaration
    return {'capability': 'SCAR_STREAM_INTERFACE_MEMBERSHIP_V1', 'manifest': encode(declaration),
            'events': encode(artifact), 'declared_counts': counts,
            'collector_stopped': doc['stopped'], 'source_or_contents_established': False}, [str(events), str(metadata)]


def _lean_plan_member(files, trace_root, pid, members, calls, operands):
    """Bind the exact selector receipt, never upgrade its observation scope."""
    from scar.ir.program.call_operands import LEAN_PORTS_RULE
    from scar.ir.record_codec import decode
    from scar.trace.lean_capture import LeanCapturePlan, PROFILE
    if operands.get("rule") != LEAN_PORTS_RULE:
        _need(calls.get("capture_profile") != PROFILE and "capture_plan" not in calls,
              "lean frame plan requires the matching operand rule")
        return None, []
    scope = PROFILE + ": planned roots/direct thin boundaries; unplanned interiors/imports unexpanded"
    _need(calls.get("capture_profile") == PROFILE and calls.get("unplanned_bodies_expanded") is False
          and calls.get("scope") == scope and calls.get("project_root") == operands.get("project_root"),
          "lean capture must preserve its explicit thin-boundary scope and namespace")
    declaration = decode(ProviderArtifact, calls.get("capture_plan"))
    expected = trace_root / f"lean-plan.{pid}.json"
    _need(declaration.uri == str(expected) and declaration.schema == "scar.lean-capture-plan/1"
          and 0 < declaration.size_bytes <= 16_000_000, "lean plan receipt path/schema/size differs")
    local, entry = files.local(expected)
    _need((entry["raw_bytes"] if entry is not None else local.stat().st_size) == declaration.size_bytes,
          "lean plan retained byte declaration differs")
    document, artifact = files.document(expected, declaration.schema, limit=16_000_000)
    _need(artifact == declaration, "lean plan retained SHA/receipt differs")
    maximum = calls.get("limits", {}).get("max_codes")
    _need(_integer(maximum, 1), "lean frame code budget is not declared")
    plan = LeanCapturePlan.from_dict(document, max_codes=maximum)
    _need(plan.namespace_root == calls["project_root"], "lean plan namespace differs from its issuer")
    members[str(expected)] = artifact
    return {"capability": "SCAR_LEAN_CAPTURE_PLAN_MEMBERSHIP_V1", "profile": PROFILE,
            "plan": encode(artifact), "planned_codes": len(plan.bodies), "scope": scope,
            "unplanned_bodies_expanded": False,
            "source_compiler_runtime_contents_proved": False}, [str(expected)]


def bind_capture_coordinates(capture_dir, *, max_bytes=1_000_000_000, max_lines=2_000_000, profile_uri=None,
                             publish_os_profile=False, allow_plain_owned_capture=False):
    """Validate this retained capture profile and reuse existing coordinate types.

    Only files under capture_dir are opened. Plain files are selected by exact
    original names relocated root-relative. If archive-index.json is supplied,
    its explicit lossless entries are checked against raw and compressed hashes.
    No manifest URI is opened and gzip names are never guessed.
    This does not join Python operations, Tensor values or source state effects.
    An owned OS launch declaration can qualify a new profile after Run binding.
    Publishing that derived profile is explicit; no legacy launch is fabricated.
    Explicit plain-owned preflight can retain actual launch facts while archive
    publication is pending; it never publishes the qualified coverage profile.
    """
    from scar.trace.os_resources import _arguments, _clone_flags

    root = Path(capture_dir).resolve()
    _need(type(allow_plain_owned_capture) is bool, "plain preflight mode must be explicit")
    _need(root.is_dir() and _integer(max_bytes, 1) and _integer(max_lines, 1), "invalid directory or budgets")
    manifests = [path for path in (root / "trace").glob("execution-evidence.*.json")
                 if _MANIFEST_NAME.fullmatch(path.name)]
    _need(len(manifests) == 1, "profile requires one unambiguous native collector manifest")
    manifest_path = manifests[0]
    _need(manifest_path.resolve().is_relative_to(root) and manifest_path.stat().st_size <= 2_000_000,
          "native manifest escapes capture root or exceeds the metadata bound")
    native_payload = manifest_path.read_bytes()
    native = _json(native_payload)
    _need(type(native) is dict and native.get("schema") == "scar.execution-evidence-collection"
          and native.get("schema_version") == 1 and native.get("status") == "CLOSED"
          and native.get("failures") == [] and _integer(native.get("pid"), 1),
          "native collector did not close this supported process capture successfully")
    pid = native["pid"]
    _need(int(_MANIFEST_NAME.fullmatch(manifest_path.name)[1]) == pid, "native manifest filename/process mismatch")
    eto_name = PurePosixPath(native["artifacts"]["execution_trace"]["path"])
    kineto_name = PurePosixPath(native["artifacts"]["kineto"]["path"])
    _need(eto_name.is_absolute() and eto_name.parent == kineto_name.parent
          and eto_name.parent.name == "trace", "native artifact declarations have no common trace namespace")
    match = re.fullmatch(r"execution-trace\." + str(pid) + r"\.([0-9a-f]{32})\.json", eto_name.name)
    _need(match is not None and kineto_name.name == "kineto." + str(pid) + "." + match[1] + ".json",
          "native artifact declarations do not share the collector nonce")
    original_root, nonce = eto_name.parent.parent, match[1]
    archive_path = root / "archive-index.json"
    archive_payload, archive = None, None
    if archive_path.exists() or archive_path.is_symlink():
        _need(not archive_path.is_symlink() and archive_path.resolve().is_relative_to(root)
              and archive_path.is_file() and archive_path.stat().st_size <= 2_000_000,
              "archive index escapes capture root or exceeds bound")
        archive_payload = archive_path.read_bytes()
        archive = _json(archive_payload)
        _need(type(archive) is dict and archive.get("schema") == "scar.lossless-capture-archive"
              and archive.get("schema_version") == 1 and archive.get("verified_roundtrip") is True
              and type(archive.get("files")) is list, "unsupported lossless archive manifest")
    files = _Files(root, original_root, archive, max_bytes)
    trace_root = original_root / "trace"
    native_name = trace_root / manifest_path.name
    native_artifact = files.verify(native_name, "scar.execution-evidence-collection")
    _need(native_artifact.sha256 == sha256(native_payload).hexdigest(), "native manifest changed during binding")
    calls, call_meta = files.document(trace_root / ("call-meta." + str(pid) + ".json"), "scar.call-edge-trace")
    operands, operand_meta = files.document(trace_root / ("call-operand-meta." + str(pid) + ".json"), "scar.call-operands-trace")
    _need(calls.get("schema") == "scar.call-edge-trace" and calls.get("schema_version") == 1
          and calls.get("process_id") == pid and operands.get("schema") == "scar.call-operands-trace"
          and operands.get("schema_version") == 1 and operands.get("process_id") == pid,
          "call/operand collector schema or process differs")
    members = {str(native_name): native_artifact, str(trace_root / ("call-meta." + str(pid) + ".json")): call_meta,
               str(trace_root / ("call-operand-meta." + str(pid) + ".json")): operand_meta}
    base = operands.get("base_manifest")
    _need(type(base) is list and {item.get("family") for item in base} == {"codes", "events", "meta"}
          and len(base) == 3, "operand base manifest must bind the exact three call artifacts")
    for item in base:
        _need(item.get("process_id") == pid, "operand base manifest changes process")
        expected = trace_root / ("call-" + item["family"] + "." + str(pid)
                                 + (".json" if item["family"] == "meta" else ".jsonl"))
        _need(item.get("path") == str(expected), "operand base manifest changes the exact collector filename")
        artifact = files.verify(item["path"], "scar.call-edge-" + item["family"] + ".v1")
        _need((artifact.sha256, artifact.size_bytes) == (item["raw_sha256"], item["raw_bytes"]),
              "operand base manifest does not reproduce raw call bytes")
        members[item["path"]] = artifact
    operand_name = trace_root / ("call-operands." + str(pid) + ".jsonl")
    members[str(operand_name)] = files.verify(operand_name, "scar.call-operands.events.v1")
    _need(members[str(operand_name)].size_bytes == operands["bytes"], "operand event byte count differs")
    python_target_membership, python_target_names = _python_target_members(
        files, trace_root, pid, members, operands["project_root"])
    stream_membership, stream_names = _stream_interface_members(
        files, trace_root, pid, members, operands['project_root'])
    lean_plan_membership, lean_plan_names = _lean_plan_member(files, trace_root, pid, members, calls, operands)
    environment_name = trace_root / ("function-environments." + str(pid) + ".jsonl")
    environment_meta_name = trace_root / ("function-environment-meta." + str(pid) + ".json")
    environment_present = files.contains(environment_name)
    _need(environment_present == files.contains(environment_meta_name),
          "function-environment events and metadata must be retained together")
    environment = None
    if environment_present:
        environment, environment_meta = files.document(environment_meta_name, "scar.function-environment-trace")
        _need(environment.get("schema") == "scar.function-environment-trace"
              and environment.get("schema_version") == 1 and environment.get("process_id") == pid,
              "function-environment collector schema or process differs")
        declaration = environment.get("file")
        _need(type(declaration) is dict and declaration.get("path") == str(environment_name),
              "function-environment manifest selects a different exact event filename")
        environment_artifact = files.verify(environment_name, "scar.function-environment.events.v1")
        _need((environment_artifact.sha256, environment_artifact.size_bytes)
              == (declaration.get("raw_sha256"), declaration.get("raw_bytes"))
              and environment_artifact.size_bytes == environment.get("bytes")
              and _integer(declaration.get("lines")) and declaration["lines"] == environment.get("events"),
              "function-environment manifest does not reproduce exact event bytes/count declaration")
        members[str(environment_name)] = environment_artifact
        members[str(environment_meta_name)] = environment_meta
    dispatch_config = native.get("configuration", {}).get("dispatch_observations")
    dispatch = None
    dispatch_names = []
    if dispatch_config is not None:
        _need(type(dispatch_config) is dict and dispatch_config.get("profile") == "scar.dispatch-marker-collector-v1",
              "unsupported dispatch observation declaration")
        dispatch_name = trace_root / f"dispatch-observations.{pid}.{nonce}.jsonl"
        dispatch_meta_name = trace_root / f"dispatch-meta.{pid}.{nonce}.json"
        _need(dispatch_config.get("events") == str(dispatch_name)
              and dispatch_config.get("metadata") == str(dispatch_meta_name),
              "dispatch declaration does not select this exact collector namespace")
        dispatch, dispatch_meta = files.document(dispatch_meta_name, "scar.dispatch-observation-trace")
        _need(dispatch.get("schema") == "scar.dispatch-observation-trace"
              and dispatch.get("schema_version") == 1
              and dispatch.get("profile") == dispatch_config["profile"]
              and dispatch.get("process_id") == pid and dispatch.get("nonce") == nonce
              and dispatch.get("provider_revision") == native["provider"]["torch_git_version"],
              "dispatch collector schema/process/provider/nonce differs")
        declaration = dispatch.get("file", {})
        native_declaration = dispatch.get("native_manifest", {})
        _need(native_declaration.get("path") == str(native_name)
              and (native_declaration.get("raw_sha256"), native_declaration.get("raw_bytes"))
                  == (native_artifact.sha256, native_artifact.size_bytes),
              "dispatch collector does not bind this exact final native manifest")
        dispatch_artifact = files.verify(dispatch_name, "scar.dispatch-observation.events.v1")
        _need(declaration.get("path") == str(dispatch_name)
              and (declaration.get("raw_sha256"), declaration.get("raw_bytes"))
                  == (dispatch_artifact.sha256, dispatch_artifact.size_bytes)
              and dispatch.get("bytes") == dispatch_artifact.size_bytes
              and _integer(dispatch.get("events")) and declaration.get("lines") == dispatch["events"],
              "dispatch collector exact event bytes/count declaration differs")
        members[str(dispatch_name)] = dispatch_artifact
        members[str(dispatch_meta_name)] = dispatch_meta
        dispatch_names = [str(dispatch_name), str(dispatch_meta_name)]
    physical_config = native.get("configuration", {}).get("tensor_physical_observations")
    physical, physical_names = None, []
    if physical_config is not None:
        _need(type(physical_config) is dict and physical_config.get("requested") is True
              and physical_config.get("profile") == "scar.tensor-physical-event-tree-v1"
              and dispatch is not None, "unsupported physical observation declaration")
        physical_name = trace_root / f"tensor-physical.{pid}.{nonce}.jsonl"
        physical_meta_name = trace_root / f"tensor-physical-meta.{pid}.{nonce}.json"
        _need(physical_config.get("events") == str(physical_name)
              and physical_config.get("metadata") == str(physical_meta_name),
              "physical declaration does not select this exact collector namespace")
        physical, physical_meta = files.document(physical_meta_name, "scar.tensor-physical-trace")
        _need(physical.get("schema") == "scar.tensor-physical-trace"
              and physical.get("schema_version") == 1
              and physical.get("profile") == physical_config["profile"]
              and physical.get("process_id") == pid and physical.get("nonce") == nonce
              and physical.get("provider_revision") == native["provider"]["torch_git_version"],
              "physical schema/process/provider/nonce differs")
        for label, artifact in (("native_manifest", native_artifact),
                                ("dispatch_metadata", dispatch_meta),
                                ("dispatch_observations", dispatch_artifact)):
            source = physical.get("inputs", {}).get(label, {})
            _need((source.get("path"), source.get("raw_sha256"), source.get("raw_bytes"))
                  == (artifact.uri, artifact.sha256, artifact.size_bytes),
                  "physical collector does not bind exact " + label)
        physical_artifact = files.verify(physical_name, "scar.tensor-physical-observation.v1")
        declaration = physical.get("file", {})
        _need((declaration.get("path"), declaration.get("raw_sha256"), declaration.get("raw_bytes"))
              == (str(physical_name), physical_artifact.sha256, physical_artifact.size_bytes)
              and _integer(declaration.get("lines")), "physical exact byte/count declaration differs")
        members[str(physical_name)] = physical_artifact
        members[str(physical_meta_name)] = physical_meta
        physical_names = [str(physical_name), str(physical_meta_name)]
    native_input_names, native_input_membership = [], None
    native_input_config = native.get("configuration", {}).get("native_tensor_input_observations")
    if native_input_config is not None:
        from scar.trace.tensor_physical import NATIVE_INPUT_PROFILE
        from scar.trace.native_tensor_inputs import read_native_tensor_inputs
        companion_name = trace_root / f"native-tensor-inputs.{pid}.{nonce}" / "manifest.json"
        _need(type(native_input_config) is dict and native_input_config.get("requested") is True
              and native_input_config.get("profile") == NATIVE_INPUT_PROFILE
              and native_input_config.get("manifest") == str(companion_name) and physical is not None,
              "native input declaration has no exact physical companion namespace")
        companion, companion_artifact = files.document(companion_name, "scar.native-tensor-input-trace")
        checked = read_native_tensor_inputs(companion_name, expected_sha256=companion_artifact.sha256,
            max_bytes=max_bytes, _retained_files=files)
        original_physical = companion.get("legacy_physical_metadata", {})
        _need((original_physical.get("path"), original_physical.get("raw_sha256"), original_physical.get("raw_bytes"))
              == (physical_meta.uri, physical_meta.sha256, physical_meta.size_bytes),
              "native input companion has another closed physical metadata root")
        members[str(companion_name)] = companion_artifact
        native_input_names.append(str(companion_name))
        chunk_artifacts = []
        for chunk in companion["chunks"]:
            logical = companion_name.parent / chunk["path"]
            artifact = files.verify(logical, "scar.native-tensor-input-observation.v1")
            _need((artifact.sha256, artifact.size_bytes) == (chunk["raw_sha256"], chunk["raw_bytes"]),
                  "native input chunk differs from exact companion receipt")
            members[str(logical)] = artifact
            native_input_names.append(str(logical))
            chunk_artifacts.append(encode(artifact))
        native_input_membership = {"capability": "SCAR_NATIVE_TENSOR_INPUT_MEMBERSHIP_V1",
            "profile": NATIVE_INPUT_PROFILE, "manifest": encode(companion_artifact),
            "chunks": chunk_artifacts, "retained_rows": checked["retained_rows"],
            "scope": "exact retained artifacts and target-process creation only",
            "native_port_join_established": False, "Python_identity_established": False,
            "geometry_established": False, "logical_content_established": False,
            "resource_ready_established": False, "native_outputs": "UNAVAILABLE_IN_PINNED_API"}
    collector_names,collector_publication_names=[],[]
    collector_membership=None
    collector_config=native.get('configuration',{}).get('collector_execution_witness')
    if collector_config is not None:
        from scar.trace.collector_execution_witness import PROCESS_PROFILE,collector_witness_members
        issuer=collector_config.get('issuer',{});token=issuer.get('uuid','')
        witness_name=trace_root/('collector-witness.'+str(pid)+'.'+str(token))/'manifest.json'
        _need(type(token)is str and len(token)==32 and all(c in '0123456789abcdef' for c in token)
              and issuer.get('generation')==1 and issuer.get('process_id')==pid
              and collector_config.get('profile')==PROCESS_PROFILE and collector_config.get('requested') is True
              and collector_config.get('manifest')==str(witness_name) and collector_config.get('native_nonce')==nonce,
              'collector witness V2 declaration/namespace differs')
        witness,witness_artifact=files.document(witness_name,'scar.collector-execution-witness')
        checked,declared=collector_witness_members(witness_name,expected_sha256=witness_artifact.sha256)
        _need(checked==witness and witness['issuer']==issuer,'closed collector witness differs')
        for row in declared:
            logical=Path(row['uri']);artifact=files.verify(logical,row['schema'])
            _need(encode(artifact)==row,'declared collector witness member differs')
            members[str(logical)]=artifact
            if logical==witness_name.parent/'code-witnesses/manifest.json':collector_publication_names.append(str(logical))
            else:collector_names.append(str(logical))
        collector_membership={'capability':'SCAR_COLLECTOR_EXECUTION_MEMBERSHIP_V2','profile':PROCESS_PROFILE,
            'manifest':encode(witness_artifact),'issuer':issuer,'member_count':len(declared),
            'scope':'closed retained artifacts with exact target creation/publication; birth join requires witness binder',
            'source_build_established':False,'executed_binary_pages_established':False}
    for name, schema, field in ((eto_name, "pytorch.execution-trace.v1", "execution_trace"),
                                (kineto_name, "pytorch.kineto.chrome-trace.v1", "kineto")):
        artifact = files.verify(name, schema)
        _need(artifact.size_bytes == native["artifacts"][field]["size_bytes"], "native collector raw byte count differs")
        members[str(name)] = artifact
    run_document, run_artifact = files.document(original_root / "trace" / "run.json", "scar.command-result.v1")
    command = run_document.get("command")
    _need(type(command) is list and command and all(type(part) is str for part in command)
          and run_document.get("returncode") == 0, "original command receipt did not finish successfully")
    os_files, facts, parse_gaps, line_count = [], [], [], 0
    for logical in files.os_names():
        path = PurePosixPath(logical)
        name = _OS_NAME.fullmatch(path.name)
        if path.parent != original_root / "os" or name is None:
            continue
        tid = int(name[1]); artifact = files.verify(logical, "strace.syscalls.text.v1")
        os_files.append((logical, tid, artifact))
        local, _ = files.local(logical)
        opener = gzip.open if local.suffix == ".gz" else open
        with opener(local, "rb") as source:
            for number, raw in enumerate(source, 1):
                line_count += 1
                _need(line_count <= max_lines and len(raw) <= 1_000_000, "OS witness line budget exceeded")
                text = raw.decode("utf-8", errors="strict").rstrip("\r\n")
                parsed = _CALL.fullmatch(text)
                if parsed is None or parsed[1] not in _SELECTED:
                    if "<unfinished ...>" in text or " resumed>" in text:
                        parse_gaps.append({"code": "os_process_witness_frontier", "source": encode(_fact(artifact, number))})
                    continue
                try:
                    arguments = _arguments(parsed[2])
                except ValueError:
                    parse_gaps.append({"code": "os_process_witness_arguments", "source": encode(_fact(artifact, number))})
                    continue
                value = int(parsed[3], 16 if "x" in parsed[3].lower() else 10)
                facts.append({"tid": tid, "line": number, "name": parsed[1], "args": arguments,
                              "result": value, "tail": parsed[4], "source": _fact(artifact, number)})
    _need(os_files and len({tid for _, tid, _ in os_files}) == len(os_files), "OS per-TID artifact membership is absent or ambiguous")
    execs = []
    for fact in facts:
        if fact["name"] == "execve" and fact["result"] == 0 and len(fact["args"]) >= 2:
            try:
                argv = _json(fact["args"][1])
            except (ValueError, UnicodeError):
                continue
            if argv == command:
                execs.append(fact)
    _need(len(execs) == 1 and execs[0]["tid"] == pid, "exact original argv has no unique successful target exec receipt")
    target_exec = execs[0]
    clones = [fact for fact in facts if fact["name"] in ("clone", "clone3", "fork", "vfork") and fact["result"] > 0]
    birth_counts = Counter(fact["result"] for fact in clones)
    _need(birth_counts[pid] <= 1, "target process birth is ambiguous inside the retained OS capture")
    births = {fact["result"]: fact for fact in clones if birth_counts[fact["result"]] == 1
              and _clone_flags(fact) is not None}
    target_birth = births.get(pid, target_exec)
    _need(target_birth is target_exec or "CLONE_THREAD" not in _clone_flags(target_birth),
          "declared process PID is instead a shared-process thread birth")
    pid_for_tid, anchors = {pid: pid}, {pid: target_birth["source"]}
    pending = list(births.items())
    while pending:
        remaining, progress = [], False
        for child, birth in pending:
            if child in pid_for_tid:
                continue
            parent_pid = pid_for_tid.get(birth["tid"])
            if parent_pid is None:
                remaining.append((child, birth)); continue
            pid_for_tid[child] = parent_pid if "CLONE_THREAD" in _clone_flags(birth) else child
            anchors[child] = birth["source"]; progress = True
        if not progress:
            break
        pending = remaining
    target_facts = [fact for fact in facts if pid_for_tid.get(fact["tid"]) == pid]
    creations = {}
    for fact in target_facts:
        if fact["name"] not in ("open", "openat", "openat2") or fact["result"] < 0:
            continue
        offset = 0 if fact["name"] == "open" else 1
        if len(fact["args"]) <= offset + 1:
            continue
        path = _quoted(fact["args"][offset])
        if path is not None:
            creations.setdefault(path, []).append((fact, fact["args"][offset + 1]))
    proofs = []
    exclusive_names = [str(trace_root / ("call-" + family + "." + str(pid) + ".jsonl"))
                       for family in ("events", "codes")]
    exclusive_names += [str(operand_name), str(native_name),
                        str(trace_root / ("call-operand-meta." + str(pid) + ".json"))]
    exclusive_names += python_target_names
    exclusive_names += lean_plan_names
    exclusive_names += stream_names
    if environment_present:
        exclusive_names += [str(environment_name), str(environment_meta_name)]
    exclusive_names += dispatch_names
    exclusive_names += physical_names
    exclusive_names += native_input_names
    exclusive_names += collector_names
    for name in exclusive_names:
        witnessed = [fact for fact, flags in creations.get(name, ()) if "O_CREAT" in flags and "O_EXCL" in flags]
        _need(len(witnessed) == 1, "artifact lacks one exact target-process O_EXCL creation: " + name)
        proofs.append({"kind": "EXCLUSIVE_ARTIFACT_CREATION", "logical_path": name, "source": encode(witnessed[0]["source"])})
    for name in collector_publication_names:
        target=Path(name);temporary=str(target.parent/'.manifest.tmp')
        renames=[f for f in target_facts if f['name']=='rename' and f['result']==0
                 and len(f['args'])==2 and _quoted(f['args'][0])==temporary and _quoted(f['args'][1])==name]
        _need(renames and len({f['tid'] for f in renames})==1,'CodeWitness final manifest has no single-writer publication chain')
        tid=renames[0]['tid'];ordered=sorted(renames,key=lambda f:f['line']);last=ordered[-1]
        previous=ordered[-2]['line'] if len(ordered)>1 else 0
        opened=[f for f,flags in creations.get(temporary,()) if f['tid']==tid and previous<f['line']<last['line']
                and 'O_CREAT' in flags and 'O_EXCL' in flags]
        _need(len(opened)==1,'CodeWitness final rename lacks its exact exclusive temporary creation')
        proofs.append({'kind':'COLLECTOR_CODE_WITNESS_FINAL_PUBLICATION','logical_path':name,
            'source':encode(last['source']),'exclusive_temporary_creation':encode(opened[0]['source']),
            'basis':'last successful same-thread exact temp-to-manifest rename; original immutable final SHA checked'})
    _need(creations.get(str(eto_name)), "declared nonce ETO has no target-process open receipt")
    renamed = []
    for fact in target_facts:
        if fact["name"] != "rename" or fact["result"] != 0 or len(fact["args"]) != 2:
            continue
        old, new = (_quoted(value) for value in fact["args"])
        if new == str(kineto_name) and old == str(kineto_name) + ".tmp":
            renamed.append(fact)
        if new == str(native_name) and old == str(trace_root / (".execution-evidence." + str(pid) + "." + nonce + ".tmp")):
            proofs.append({"kind": "COLLECTOR_MANIFEST_PUBLICATION", "logical_path": new, "source": encode(fact["source"])})
    _need(len(renamed) == 1 and any(proof["kind"] == "COLLECTOR_MANIFEST_PUBLICATION" for proof in proofs),
          "collector nonce artifacts lack exact successful publication receipts")
    proofs.append({"kind": "KINETO_PUBLICATION", "logical_path": str(kineto_name), "source": encode(renamed[0]["source"])})
    seed = {"profile": _PROFILE, "archive_sha256": sha256(archive_payload).hexdigest() if archive_payload is not None else None,
            "native_manifest_sha256": native_artifact.sha256, "command_sha256": run_artifact.sha256,
            "target_exec": encode(target_exec["source"]), "target_birth": encode(target_birth["source"])}
    # Lossless compression/relocation changes the retention receipt, not the
    # observed execution. Keep the original plain-capture identity seed while
    # retaining the actual archive hash above as independently checked evidence.
    # This also preserves identities already exported from plain captures.
    identity_seed = dict(seed, archive_sha256=None)
    namespace = "capture:" + sha256(_canonical(identity_seed)).hexdigest()
    run = ExecutionRun(RunID(namespace), target_exec["source"])
    process_rows = {}
    for process_pid in sorted(set(pid_for_tid.values())):
        source = anchors[process_pid]
        process_rows[process_pid] = ProcessInstance(
            ProcessInstanceID(namespace + ":process:" + sha256(_canonical(encode(source))).hexdigest()),
            run.id, process_pid, source)
    thread_rows = {}
    for _, tid, _ in os_files:
        if tid not in pid_for_tid:
            continue
        source = anchors[tid]
        thread_rows[tid] = HostThreadInstance(
            HostThreadInstanceID(namespace + ":thread:" + sha256(_canonical(encode(source))).hexdigest()),
            process_rows[pid_for_tid[tid]].id, tid, source)
    target = process_rows[pid]
    process_members, os_threads, membership = {}, {}, []
    for logical, artifact in members.items():
        process_members[_key(artifact), pid] = target
        membership.append({"logical_path": logical, "local_path": str(files.local(logical)[0]),
                           "artifact": encode(artifact), "process": encode(target.id),
                           "basis": "exact collector/base/retained artifacts plus target-process creation/publication witnesses"})
    for logical, tid, artifact in os_files:
        if tid in pid_for_tid:
            process = process_rows[pid_for_tid[tid]]
            process_members[_key(artifact), tid] = process
            os_threads[_key(artifact), tid] = thread_rows[tid]
            membership.append({"logical_path": logical, "local_path": str(files.local(logical)[0]),
                               "artifact": encode(artifact), "process": encode(process.id),
                               "thread": encode(thread_rows[tid].id), "basis": "unique explicit Linux clone ancestry from the witnessed target exec"})
    native_keys = frozenset(_key(artifact) for artifact in members.values())
    # Linux native TID lookup is explicit.  It never applies to Python ident,
    # ETO collector tokens, GPU lanes, or unrelated artifacts.
    kineto_artifact = members[str(kineto_name)]
    for tid, thread in thread_rows.items():
        if pid_for_tid[tid] == pid:
            os_threads[_key(kineto_artifact), tid] = thread
    gaps = parse_gaps + [{"code": "os_actor_not_connected_to_target_ancestry", "tid": tid}
                         for _, tid, _ in os_files if tid not in pid_for_tid]
    gaps += [{"code": "python_ident_to_native_tid_unverified"}, {"code": "python_operation_to_torch_rf_unverified"},
             {"code": "source_world_effect_correspondence_unverified"}, {"code": "collector_completeness_remains_declared_partial"},
             {"code": "process_thread_observation_intervals_incomplete"}]
    if environment is not None:
        gaps.append({"code": "function_environment_event_to_canonical_entry_unverified"})
    if dispatch is not None:
        gaps.append({"code": "dispatch_observation_to_canonical_source_ports_unverified"})
    collector_declarations = [("calls", calls), ("operands", operands)]
    if environment is not None:
        collector_declarations.append(("function_environments", environment))
    if dispatch is not None:
        collector_declarations.append(("dispatch_observations", dispatch))
    if physical is not None:
        collector_declarations.append(("tensor_physical_observations", physical))
        if (physical.get("traversal_completed") is not True
                or physical.get("marker_ordered_slot_correspondence_established") is not True
                or physical.get("allocation_receipt_traversal_complete") is not True):
            gaps.append({"code": "tensor_physical_observations_incomplete"})
    for family, declaration in collector_declarations:
        if (declaration.get("dropped_events", 0) or declaration.get("errors") or declaration.get("io_failed")
                or declaration.get("unknown_exits", 0) or declaration.get("gaps", 0)):
            gaps.append({"code": "collector_declared_incomplete_observations", "collector": family})
    report = {"schema": "scar.capture-coordinates", "schema_version": 1, "profile": _PROFILE,
        "run": encode(run), "processes": encode(tuple(process_rows.values())), "threads": encode(tuple(thread_rows.values())),
        "target_process": encode(target.id), "membership": membership, "evidence": proofs,
        "original_root": str(original_root), "local_root": str(root), "seed": seed, "open": gaps,
        "conditions": ["caller supplied this capture directory; plain files retain exact original relative names"
            if archive is None else "caller bound this retained directory to its explicit lossless archive manifest",
            "fixed collector writes its declared artifacts and manifests without external tampering",
            "retained strace files belong to the supplied single capture; missing process actors remain OPEN",
            "Kineto CPU host-thread lookup explicitly uses Linux native TID; GPU lanes are a different namespace"],
        "counts": {"verified_raw_bytes": files.total, "artifact_members": len(membership),
                   "os_artifacts": len(os_files), "os_lines": line_count, "processes": len(process_rows), "threads": len(thread_rows)},
        "collector_completeness": native.get("completeness", {}), "collector_gaps": native.get("gaps", []),
        "call_collector_declaration": calls, "operand_collector_declaration": operands,
        "function_environment_collector_declaration": environment,
        "dispatch_collector_declaration": dispatch,
        "tensor_physical_collector_declaration": physical,
        "retention": {"mode": "plain" if archive is None else "lossless_archive",
                      "archive_sha256": seed["archive_sha256"], "gzip_names_inferred": False},
        "python_torch_correspondence_established": False, "world_effects_established": False,
        "source_operation_correspondence_established": False, "logical_value_identity_established": False,
        "callable_environment_binding_established": False,
        "resource_readiness_established": False,
        "whole_model_established": False, "transformation_authorized": False}
    if native.get('configuration', {}).get('os_capture_intent') is not None:
        from scar.trace.os_capture_launch import bind_os_capture_provider
        archive_receipt = None if archive_payload is None else {
            'uri': str(archive_path), 'sha256': sha256(archive_payload).hexdigest(),
            'size_bytes': len(archive_payload), 'schema': archive['schema']}
        binding, os_gaps = bind_os_capture_provider(root, run=encode(run.id), native=native,
            native_artifact=encode(native_artifact), command=command, archive=archive_receipt,
            publish=publish_os_profile, allow_plain_preflight=allow_plain_owned_capture)
        report['os_capture_provider'] = binding
        report['open'].extend(os_gaps)
    if native_input_membership is not None:
        report['native_tensor_input_membership'] = native_input_membership
        report['open'].append({'code': 'native_tensor_input_port_join_unverified',
                               'source': native_input_membership['manifest']})
    if python_target_membership is not None:
        report['python_call_target_membership'] = python_target_membership
        report['open'].append({'code': 'python_target_event_to_canonical_call_ports_unverified',
                               'source': python_target_membership['manifest']})
    if lean_plan_membership is not None:
        report['lean_capture_plan_membership'] = lean_plan_membership
        report['open'].append({'code': 'lean_unplanned_bodies_and_interfaces_remain_unexpanded',
                               'source': lean_plan_membership['plan']})
    if stream_membership is not None:
        report['stream_interface_membership'] = stream_membership
        report['open'].append({'code': 'stream_interface_source_contents_and_backing_resources_unverified',
                               'source': stream_membership['manifest']})
    if collector_membership is not None:
        report['collector_execution_membership']=collector_membership
        report['open'].append({'code':'collector_process_birth_requires_explicit_witness_binder',
                               'source':collector_membership['manifest']})
    payload = _canonical(report)
    artifact = ProviderArtifact(profile_uri or "memory:scar.capture-coordinates:" + sha256(payload).hexdigest(),
                                sha256(payload).hexdigest(), len(payload), report["schema"])
    return CaptureCoordinates(run, tuple(process_rows.values()), tuple(thread_rows.values()), target,
                              artifact, payload, report, process_members, os_threads, native_keys)


__all__ = ["CaptureCoordinates", "bind_capture_coordinates"]
