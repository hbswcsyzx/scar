"""Owned current raw reading and exact reuse of completed same-Run source proof.

A public orchestration opens the raw reader itself. Retained proof is provenance
for exact source-reference membership, not a manufactured definition record or a
new live source guard. Existing public independent replay entry points stay raw.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import gzip
import hashlib
from pathlib import Path
import sys

from scar.ir.program.call_edges import CapturedCode, CodeSourceLink, CallLinkStatus
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceDefinitionReference
from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.ir.semantics_v2 import SourceSnapshot

_KEY = object()
_RULE = "OWNED_CURRENT_OPERAND_FRAME_SCAN_V1"
_PROOF_RULE = "SAME_RUN_STATIC_SOURCE_MEMBERSHIP_ANCESTRY_V2"
_GUARD_SCOPE = "REUSED_COMPLETED_CURRENT_CAPTURE_AT_RECORDED_BINDING_NOT_FRESH_LIVE"


def _need(value, detail):
    if not value:
        raise ValueError("current source evidence: " + detail)


def _canonical(value):
    from json import dumps
    return dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path, expected_sha, *, limit=64_000_000, schema="scar.retained-source-proof-input.v1"):
    path = Path(path)
    _need(path.is_absolute() and path.resolve(strict=True) == path and not path.is_symlink()
          and path.is_file(), "proof input is not an exact ordinary canonical file")
    before = path.stat()
    _need(before.st_size <= limit, "proof input byte bound exceeded")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    after = path.stat()
    _need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
          == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
          and len(raw) == before.st_size <= limit and _digest(raw) == expected_sha,
          "retained proof bytes changed or differ from their fixed receipt")
    value = strict_loads(raw.decode("utf-8"))
    _need(type(value) is dict, "proof document must be an object")
    return value, ProviderArtifact(str(path), expected_sha, len(raw), schema)


class _RetainedGuards:
    def __init__(self, proof):
        self.records = deepcopy(proof._report["current_source_checks"])
        self._keys = {}
        for row in proof._rows.values():
            if row["snapshot"] is not None and type(row["current_source_check"]) is int:
                snapshot = decode(SourceSnapshot, row["snapshot"])
                self._keys[snapshot] = row["current_source_check"]
        self.raw_bytes = self.decoded_bytes = 0

    def check(self, snapshot):
        index = self._keys.get(snapshot)
        if index is None:
            record = {"path": snapshot.path, "expected_fingerprint": snapshot.fingerprint,
                "actual_fingerprint": None, "raw_bytes": 0, "decoded_utf8_bytes": 0,
                "status": "UNRESOLVED", "frontier": "RETAINED_CURRENT_SOURCE_GUARD_UNAVAILABLE",
                "method": "tokenize.open decoded text, universal newlines, UTF-8 SHA256"}
            index = len(self.records); self.records.append(record); self._keys[snapshot] = index
        return index, self.records[index]


class SameRunSourceProof:
    """An exact immutable-reference proof, privately created after a raw read."""
    def __init__(self, key, owner, directory, report_sha, bindings_sha,
                 previous_producer, previous_participating_producer, composition):
        _need(key is _KEY and type(owner) is _OwnedCurrent and owner._key is _KEY,
              "source proof can only be built by the owned raw orchestration")
        self._owner = owner
        directory = Path(directory).resolve(strict=True)
        self._report, self._report_artifact = _read(directory / "report.json", report_sha,
            schema="scar.source-invocations")
        self._binding_document, self._binding_artifact = _read(directory / "bindings.json", bindings_sha,
            schema="scar.source-invocation-bindings")
        report, document = self._report, self._binding_document
        _need(report.get("schema") == "scar.source-invocations" and report.get("schema_version") == 3
              and document.get("schema") == "scar.source-invocation-bindings" and document.get("schema_version") == 3
              and report.get("witness_mode") == document.get("witness_mode") == "reused_code"
              and report.get("attachment_source_match_rule") == document.get("attachment_source_match_rule")
                  == "EXACT_CAPTURED_CODE_STATIC_REUSE_V1"
              and report.get("source_definition_reference_format") == document.get("source_definition_reference_format")
                  == "scar.source-definition-reference.v1"
              and report.get("current_capture_raw_scan_verified") is True
              and report.get("old_capture_dynamic_facts_used_for_current_run") is False
              and report.get("first_stage_complete") is False and report.get("transformation_authorized") is False,
              "unsupported completed source-proof contract")
        _need(report["bindings"]["path"] == "bindings.json"
              and (report["bindings"]["raw_sha256"], report["bindings"]["raw_bytes"])
                  == (self._binding_artifact.sha256, self._binding_artifact.size_bytes)
              and document["source_inputs"] == report["source_inputs"], "source proof header/receipt differs")
        self._verify_producer(previous_producer, previous_participating_producer)
        self._rows = {(row["process_id"], row["code"]): row for row in document["bindings"]}
        _need(len(self._rows) == len(document["bindings"]), "duplicate retained source binding")
        self._references, self._witnesses = {}, {}
        self._source_inputs = deepcopy(report["source_inputs"])
        self.require_composition(composition)
        self._verify_current_scan(owner)
        for index, row in enumerate(document["bindings"]):
            _need(row["binding_index"] == index, "retained binding index differs")
            if row.get("source_origin") != "SOURCE_ATTACHMENT" or row["definition"] is None:
                continue
            reference = decode(SourceDefinitionReference, row["definition"])
            witness = row["attachment_witness"]["static_witness"]
            link = decode(CodeSourceLink, witness["code_source_link"])
            _need(link.status is CallLinkStatus.VERIFIED and link.definition == reference.definition
                  and encode(link.snapshot) == row["snapshot"] == encode(reference.snapshot)
                  and encode(link.source) == row["source"] == encode(reference.source)
                  and row["code_capture"]["code"] == witness["captured_code"]
                  and row["body"] is None and row["composition_element"] is None,
                  "retained source-only definition contradicts its original full witness")
            current = composition.static_code_witness(decode(CapturedCode,
                witness["captured_code"]), compilation_profile=report["source_compilation_profile"],
                captured_python_build=owner.builds[row["process_id"]])
            _need(current == witness, "retained full static/compiler/build witness differs from bound original inputs")
            guard = composition.current_source_guard(reference.snapshot, row["current_source_check"],
                                                     report["current_source_checks"])
            _need(guard["status"] == "FINGERPRINT_MATCH" and witness["context_guard"]["status"] == "MATCH",
                  "retained reference has no successful recorded binding-scope guard")
            encoded = _canonical(encode(reference))
            provenance = {"rule": _PROOF_RULE, "rule_version": 2,
                "source_membership_ancestry_sha256": _digest(_canonical(self._source_membership_ancestry)),
                "static_membership_only": True, "old_body_or_activation_reused": False,
                "reference_sha256": _digest(encoded),
                "source_report": encode(self._report_artifact), "source_bindings": encode(self._binding_artifact),
                "definition_pointer": f"#/bindings/{index}/definition", "run": report["run"],
                "producer": encode(self._producer_artifact), "participating_producer": encode(self._participating_artifact),
                "original_graph": encode(reference.graph), "graph_replayed_in_this_analysis": False}
            self._references[encoded] = (reference, provenance)
            witness_key = _canonical(witness)
            _need(witness_key not in self._witnesses or self._witnesses[witness_key] == reference,
                  "one complete retained static witness has contradictory qualified references")
            self._witnesses[witness_key] = reference
        self._guards = _RetainedGuards(self)

    def _verify_producer(self, producer_declaration, participating_declaration):
        _need(type(producer_declaration) is tuple and len(producer_declaration) == 2
              and type(participating_declaration) is tuple and len(participating_declaration) == 2,
              "exact prior producer and post-import receipts are required")
        frozen, self._producer_artifact = _read(*producer_declaration)
        post, self._participating_artifact = _read(*participating_declaration)
        _need(type(frozen.get("modules")) is list and type(post.get("checked")) is list
              and type(post.get("actual_imports")) is list and post["actual_imports"],
              "prior producer has no participating source archive")
        originals = {row["path"]: row for row in frozen["modules"]}
        checked = {row["path"]: row for row in post["checked"]}
        _need(len(originals) == len(frozen["modules"]) and len(checked) == len(post["checked"])
              and set(post["actual_imports"]).issubset(checked), "prior producer module denominator differs")
        folder = Path(participating_declaration[0]).parent / "participating-source-evidence"
        total = 0
        for name, row in checked.items():
            _need(originals.get(name) == row, "participating source receipt differs from the original producer freeze")
            artifact = folder / (row["sha256"] + ".py-source")
            _need(artifact.is_file() and not artifact.is_symlink()
                  and artifact.stat().st_size <= 32_000_000 - total,
                  "participating producer source bytes are unavailable or exceed the archive budget")
            raw = artifact.read_bytes(); total += len(raw)
            _need(len(raw) == row["bytes"] and _digest(raw) == row["sha256"] and total <= 32_000_000,
                  "participating producer archive digest/byte bound differs")
        required = ("/scar/analysis/source_invocations.py", "/scar/analysis/source_attachments.py",
                    "/scar/analysis/source_layers.py", "/scar/analysis/program_composition.py")
        _need(all(any(path.endswith(suffix) for path in post["actual_imports"]) for suffix in required),
              "prior proof lacks the actual source-reference producer/validator archive")
        fixed = frozen["fixed_inputs"]
        inputs, self._fixed_input_manifest = _read(fixed["path"], fixed["sha256"])
        _need(self._fixed_input_manifest.size_bytes == fixed["bytes"]
              and type(inputs.get("inputs")) is list, "producer has no fixed raw/input scope")
        self._fixed_inputs = {row["path"]: row for row in inputs["inputs"]}
        _need(len(self._fixed_inputs) == len(inputs["inputs"]), "duplicate original fixed input path")
        self._producer_archive_bytes = total

    def _verify_current_scan(self, owner):
        report, scan = self._report, owner.operands.frame_scan
        _need(report["run"] == encode(owner.coordinates.run)
              and report["coordinate_binding"] == encode(owner.coordinates.artifact)
              and _canonical(owner.coordinates.report) == owner.coordinates.payload
              and _digest(owner.coordinates.payload) == owner.coordinates.artifact.sha256
              and len(owner.coordinates.payload) == owner.coordinates.artifact.size_bytes
              and report["call_budget"] == encode(owner.operands.frame_budget)
              and encode(scan.files) == report["trace_files"]
              and list(scan.metadata) == report["collection_metadata"]
              and encode(scan.issues) == report["raw_scan_issues"],
              "retained source proof belongs to a different Run, raw scope or coordinate receipt")
        groups = Counter((entry.invocation.process_id, entry.code) for entry in owner.operands.entries)
        captures = {(capture.process_id, capture.code.key): capture for capture in scan.captures}
        _need(set(groups) == set(self._rows)
              and len(scan.captures) == report["summary"]["code_captures"]
              and len(owner.operands.entries) == report["summary"]["invocations"]
              and len(owner.operands.exits) == report["summary"]["exits"], "same-Run current raw denominator changed")
        for key, count in groups.items():
            row = self._rows[key]
            _need(count == row["entered_invocations"] and encode(captures[key]) == row["code_capture"],
                  "same-Run descriptor/anchor/group weight differs")
        _need(all(build == sys.version for build in owner.builds.values()), "current Python build differs from reader")
        current_artifacts = {row["artifact"]["uri"]: row["artifact"]
                             for row in owner.coordinates.report["membership"]}
        for file in scan.files + owner.operands.files:
            artifact = current_artifacts.get(file.path)
            _need(artifact is not None and (artifact["sha256"], artifact["size_bytes"])
                  == (file.raw_sha256, file.raw_bytes), "raw family has no exact current coordinate member")
            _need(owner.coordinates.process_for(decode(ProviderArtifact, artifact), file.process_id) is not None,
                  "owned raw family has no bound original process membership")

    def require_composition(self, composition):
        origin = composition.original_code_source_origin()
        ancestry = composition.require_source_membership_ancestor(
            self._report["composition_canonical_sha256"], self._report["inventory"])
        _need(origin["inventory"] == self._report["inventory"]
              and composition.source_inputs()["attachments"] == self._source_inputs["attachments"]
              and composition.inventory_component("discovery")["project_root"]
                  == self._report["collection_metadata"][0]["project_root"],
              "publication changed the prior static source/compiler proof basis")
        previous = getattr(self, "_source_membership_ancestry", None)
        _need(previous is None or previous == ancestry, "source proof is already bound to a different current snapshot")
        self._source_membership_ancestry = ancestry

    def definition_reference(self, witness):
        return self._witnesses.get(_canonical(witness))

    def reference_membership_proof(self, reference):
        if reference is None:
            return None
        result = self._references.get(_canonical(encode(reference)))
        return deepcopy(result[1]) if result is not None and result[0] == reference else None

    def guards(self):
        return self._guards

    def receipt(self):
        return {"rule": _PROOF_RULE, "rule_version": 2,
            "source_membership_ancestry": deepcopy(self._source_membership_ancestry),
            "static_membership_only": True, "old_body_or_activation_reused": False,
            "source_report": encode(self._report_artifact),
            "source_bindings": encode(self._binding_artifact), "producer": encode(self._producer_artifact),
            "participating_producer": encode(self._participating_artifact),
            "run": self._report["run"], "guard_scope": _GUARD_SCOPE,
            "participating_producer_source_bytes_rehashed": self._producer_archive_bytes,
            "prior_fixed_input_manifest": encode(self._fixed_input_manifest),
            "prior_fixed_input_declarations": len(self._fixed_inputs),
            "prior_fixed_artifact_payloads_rehashed_here": False,
            "exact_source_references_reused": len(self._references), "full_definition_records_fabricated": False,
            "source_graph_replayed_here": False, "current_raw_scope_independently_checked": True}


class _OwnedCurrent:
    def __init__(self, key, operands, coordinates):
        _need(key is _KEY, "owned reader state cannot be supplied by a public caller")
        self._key, self.operands, self.coordinates = key, operands, coordinates
        self.builds = {meta["process_id"]: meta["python"] for meta in operands.frame_scan.metadata}
        self.proof = None
        self._bound_source_access = None

    def require(self, trace, root, frame_budget, operand_budget=None, coordinates=None):
        _need(self._key is _KEY and self.operands.directory == str(Path(trace).resolve())
              and self.operands.project_root == str(Path(root).resolve())
              and self.operands.frame_budget == frame_budget
              and (operand_budget is None or self.operands.budget == operand_budget)
              and (coordinates is None or coordinates is self.coordinates),
              "owned current reader scope/root/budget/coordinates differ")
        return self.operands

    def source_inputs(self, trace, root, budget, coordinates):
        operands = self.require(trace, root, budget, coordinates=coordinates)
        from scar.analysis.source_invocations import _Sink
        sink = _Sink()
        sequence = [(entry.anchor.index, True, entry) for entry in operands.entries]
        sequence += [(exit.anchor.index, False, exit) for exit in operands.exits]
        for _, entered, row in sorted(sequence, key=lambda item: (item[2].invocation.process_id, item[0])):
            (sink.entry if entered else sink.exit)(row)
        return operands.frame_scan, sink

    def checked_source_access(self, composition, source_directory, coordinates, code_witnesses):
        access = self._bound_source_access
        if access is not None:
            _need(access.bound and access.composition is composition and access.coordinates is coordinates
                  and access.code_witnesses is code_witnesses
                  and access.report_root == Path(source_directory).resolve(),
                  "owned checkpoint accessor differs from this exact continuation scope")
        return access


def _require_owned_source_report(composition, report, bindings):
    """An output declaration cannot grant the installed proof's authority."""
    markers = (report.get("raw_reader_rule"), bindings.get("raw_reader_rule"))
    proofs = (report.get("same_run_source_proof"), bindings.get("same_run_source_proof"))
    if any(value is not None for value in markers + proofs):
        installed = composition.static_source_proof_receipt()
        _need(markers == (_RULE, _RULE) and installed is not None
              and proofs == (installed, installed)
              and report.get("source_guard_scope") == _GUARD_SCOPE
              and report.get("current_source_guards_refreshed") is False,
              "owned source report has no identical installed checked proof")
        return installed
    return None


def _checkpoint_stream(directory, declaration, *, max_bytes=1_000_000_000):
    """Check retained output bytes/rows, without claiming to replay their meaning."""
    name = declaration["path"]
    _need(name in ("invocations.jsonl.gz", "orphan-exits.jsonl.gz")
          and all(type(declaration[field]) is int and 0 <= declaration[field] <= max_bytes
                  for field in ("raw_bytes", "compressed_bytes", "rows")),
          "checkpoint stream declaration exceeds the supported bounded profile")
    path = directory / name
    _need(path.is_file() and not path.is_symlink(), "checkpoint stream is not an ordinary file")
    before = path.stat()
    _need(before.st_size == declaration["compressed_bytes"], "checkpoint compressed stream size differs")
    digest, size, rows = hashlib.sha256(), 0, 0
    with gzip.open(path, "rb") as stream:
        while True:
            block = stream.read(min(1_048_576, declaration["raw_bytes"] - size + 1))
            if not block:
                break
            size += len(block); rows += block.count(b"\n"); digest.update(block)
            _need(size <= declaration["raw_bytes"], "checkpoint decoded stream exceeds its exact declaration")
    after = path.stat()
    _need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
          == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
          and (digest.hexdigest(), size, rows)
              == (declaration["raw_sha256"], declaration["raw_bytes"], declaration["rows"]),
          "checkpoint output stream SHA/bytes/rows changed")
    return {"path": str(path), "compressed_bytes": before.st_size,
            "raw_sha256": digest.hexdigest(), "raw_bytes": size, "rows": rows,
            "semantic_row_replay_performed_here": False}


def _resume_source(owner, composition, directory, report_sha, bindings_sha, code_witnesses):
    from scar.analysis.source_body_access import SourceBodyAccess
    directory = Path(directory).resolve(strict=True)
    report, report_ref = _read(directory / "report.json", report_sha, schema="scar.source-invocations")
    bindings, binding_ref = _read(directory / "bindings.json", bindings_sha,
                                  schema="scar.source-invocation-bindings")
    _need(_require_owned_source_report(composition, report, bindings) == owner.proof.receipt(),
          "completed checkpoint has no identical installed original same-Run source proof")
    _need(report["coordinate_binding"] == encode(owner.coordinates.artifact)
          and report["call_budget"] == encode(owner.operands.frame_budget)
          and report["raw_scan_issues"] == encode(owner.operands.frame_scan.issues)
          and report["current_source_checks"] == owner.proof.guards().records,
          "completed checkpoint changed coordinates, reader budget/issues or recorded guard scope")
    access = SourceBodyAccess(composition, directory, owner.coordinates, code_witnesses)
    _need(access.report_receipt["sha256"] == report_ref.sha256
          and access.report_receipt["bytes"] == report_ref.size_bytes
          and access.bindings_receipt["sha256"] == binding_ref.sha256
          and access.bindings_receipt["bytes"] == binding_ref.size_bytes,
          "checkpoint documents changed between exact receipt and public accessor validation")
    access.bind_scan(owner.operands.frame_scan, owner.operands.entries, owner.operands.exits)
    streams = [_checkpoint_stream(directory, report[name]) for name in ("invocations", "orphan_exits")]
    owner._bound_source_access = access
    return report, {"rule": "EXACT_COMPLETED_SOURCE_CHECKPOINT_V1",
        "source_report": encode(report_ref), "source_bindings": encode(binding_ref),
        "streams": streams, "current_raw_scan_repeated_independently": True,
        "source_binder_reexecuted": False, "same_run_source_proof": owner.proof.receipt(),
        "source_body_accessor_rebound_to_current_owned_scan": True,
        "guards_refreshed": False, "transformation_authorized": False}


def connect_current_capture(composition, coordinates, trace_directory, out_dir, *,
                            previous_source_directory, previous_report_sha256, previous_bindings_sha256,
                            previous_producer, previous_participating_producer, code_witnesses,
                            dispatch_bridge=None, frame_budget=None, operand_budget=None, route_budget=None,
                            include_environments=True, progress=None,
                            resume_source_directory=None, resume_source_report_sha256=None,
                            resume_source_bindings_sha256=None):
    """Open/verify current raw once, then privately share it across source/SBA."""
    from scar.analysis.call_operand_reader import read_call_operands
    from scar.analysis.call_operands import _link_call_operands_owned
    from scar.analysis.source_invocations import _bind_source_invocations_owned
    from scar.analysis.dispatch_sources import bind_dispatch_sources
    from scar.ir.program.call_edges import CallEdgeBudget
    from scar.ir.program.call_operands import CallOperandBudget
    from scar.ir.program.call_operand_routes import OperandRouteBudget
    from scar.analysis.program_composition import CompositionIndex
    from scar.analysis.code_witness import CodeWitnessStore
    from scar.trace.capture_coordinates import CaptureCoordinates
    frame_budget = CallEdgeBudget() if frame_budget is None else frame_budget
    operand_budget = CallOperandBudget() if operand_budget is None else operand_budget
    route_budget = OperandRouteBudget() if route_budget is None else route_budget
    _need(type(composition) is CompositionIndex and composition.partitioned
          and type(coordinates) is CaptureCoordinates
          and type(code_witnesses) is CodeWitnessStore and not code_witnesses.writable
          and not code_witnesses.compile_missing,
          "orchestration requires original composition/coordinates and a read-only CodeWitnessStore")
    _need(type(frame_budget) is CallEdgeBudget and type(operand_budget) is CallOperandBudget
          and type(route_budget) is OperandRouteBudget and type(include_environments) is bool,
          "orchestration requires exact typed reader budgets and environment selection")
    _need(progress is None or callable(progress), "progress must be callable")
    resume_fields = (resume_source_directory, resume_source_report_sha256, resume_source_bindings_sha256)
    _need(all(value is None for value in resume_fields) or all(value is not None for value in resume_fields),
          "completed source checkpoint requires its explicit directory and both exact document SHAs")
    output = Path(out_dir).resolve()
    _need(not output.exists(), "orchestration output must be fresh")
    root = composition.inventory_component("discovery")["project_root"]
    if progress is not None: progress({"stage": "OWNED_RAW_READ_BEGIN"})
    operands = read_call_operands(trace_directory, root, budget=operand_budget, frame_budget=frame_budget)
    owner = _OwnedCurrent(_KEY, operands, coordinates)
    proof = SameRunSourceProof(_KEY, owner, previous_source_directory,
        previous_report_sha256, previous_bindings_sha256, previous_producer,
        previous_participating_producer, composition)
    owner.proof = proof
    composition.install_static_source_proof(proof)
    output.mkdir(exist_ok=False)
    if progress is not None: progress({"stage": "OWNED_RAW_READ_VERIFIED", "proof_reuse": proof.receipt()})
    checkpoint = None
    source_directory = output / "source"
    if resume_source_directory is None:
        source = _bind_source_invocations_owned(owner, composition, coordinates, trace_directory,
            source_directory, call_budget=frame_budget, witness_mode="reused_code")
    else:
        source_directory = Path(resume_source_directory).resolve(strict=True)
        source, checkpoint = _resume_source(owner, composition, source_directory,
            resume_source_report_sha256, resume_source_bindings_sha256, code_witnesses)
        if progress is not None: progress({"stage": "COMPLETED_SOURCE_CHECKPOINT_VERIFIED", "checkpoint": checkpoint})
    dispatch = (bind_dispatch_sources(source_directory, dispatch_bridge, coordinates,
        output / "dispatch", composition_index=composition) if dispatch_bridge is not None else None)
    report = _link_call_operands_owned(owner, trace_directory, root, composition=composition,
        source_bindings=source_directory, coordinates=coordinates, code_witnesses=code_witnesses,
        frame_budget=frame_budget, operand_budget=operand_budget, route_budget=route_budget,
        include_environments=include_environments, progress=progress)
    counts = {"frame_scans": 1, "operand_scans": 1, "environment_scans": int(include_environments),
        "captured_codes": len(operands.frame_scan.captures), "entries": len(operands.entries),
        "exits": len(operands.exits), "operand_events": len(operands.events)}
    return {"source_report": source, "dispatch_report": dispatch, "operand_report": report,
            "source_directory": str(source_directory), "source_checkpoint": checkpoint,
            "reader_counts": {**counts, "source_binder_runs": int(checkpoint is None),
                              "completed_source_checkpoints": int(checkpoint is not None)},
            "proof_reuse": proof.receipt()}


__all__ = ["connect_current_capture", "SameRunSourceProof"]
