"""Bind captured Python invocations to existing source/body references.

This adapter reuses the inventory's complete code/source witness; it never
compiles, prepares source, invents a program root, or duplicates value/state
producers.  Raw scan callbacks remain provisional until the complete manifest,
collector metadata and entered-code groups have been independently matched.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import tokenize

from scar.analysis.call_seeds import CallSourceSeedReport
from scar.analysis.call_trace_reader import scan_call_trace
from scar.analysis.program_composition import CompositionIndex, ElementReference, QualifiedSourceBodyReference
from scar.ir.execution.common import EvidencePoint
from scar.ir.execution.coordinates import RegionActivation
from scar.ir.execution.ids import RegionActivationID
from scar.ir.program.call_demand import CallSourceAdmissionStatus, CallSourceScope
from scar.ir.program.call_edges import (
    CallEdgeBudget, CallLinkStatus, CallRecordAnchor, CapturedSite, FrameCompletion,
    FrameEntry, FrameExit, InvocationKey,
)
from scar.ir.program.call_seeds import EnteredCodeGroup, SeedCollectionMetadata
from scar.ir.program.ids import RegionID
from scar.ir.program.inventory import DefinitionInventory
from scar.ir.program.source_references import SourceDefinitionReference
from scar.ir.v2.ids import OperationDefinitionID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import SourceSnapshot
from scar.trace.capture_coordinates import CaptureCoordinates


_PATTERN = re.compile(r"call-(codes|events|meta)\.([1-9][0-9]*)\.(jsonl|json)(?:\.gz)?$")
_AUTHORITY = {
    "target_executed_by_binder": False,
    "source_recompiled_by_binder": False,
    "source_reprepared_by_binder": False,
    "actual_formal_routing_established": False,
    "return_value_routing_established": False,
    "function_environment_established": False,
    "state_versions_established": False,
    "effects_established": False,
    "canonical_control_completion_established": False,
    "python_torch_correspondence_established": False,
    "execution_model_established": False,
    "whole_program_graph_established": False,
    "first_stage_complete": False,
    "transformation_authorized": False,
}
_INTERFACE_FRONTIERS = (
    "ACTUAL_FORMAL_ROUTING_UNVERIFIED", "RETURN_VALUE_ROUTING_UNVERIFIED",
    "FUNCTION_ENVIRONMENT_UNVERIFIED", "STATE_EFFECTS_UNVERIFIED",
    "CANONICAL_CONTROL_COMPLETION_UNVERIFIED",
)


def _need(condition, detail):
    if not condition:
        raise ValueError("source invocation binding: " + detail)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _logical(path):
    return str(path.with_suffix("")) if path.suffix == ".gz" else str(path)


def _anchor_key(anchor):
    return anchor.line_number, anchor.line_sha256, anchor.index


def _manifest_key(file):
    return file.process_id, file.family, file.raw_sha256, file.raw_bytes, file.lines


@dataclass(slots=True)
class _Entry:
    anchor: CallRecordAnchor
    invocation: InvocationKey
    code: str
    caller: CapturedSite | None
    caller_invocation: InvocationKey | None
    ancestor_invocation: InvocationKey | None
    last_path_code: str | None
    path_length: int
    path_complete: bool
    suspended: bool
    expected_parent: InvocationKey | None
    parameters_count: int
    parameters_complete: bool
    caller_locals_count: int
    caller_locals_complete: bool


@dataclass(slots=True)
class _Exit:
    anchor: CallRecordAnchor
    invocation: InvocationKey
    code: str
    return_site: CapturedSite
    completion: FrameCompletion
    locals_count: int
    locals_complete: bool


class _Sink:
    """Keep coordinates and interval facts; reference vectors remain in raw rows."""

    def __init__(self):
        self.entries, self.exits, self.groups = {}, {}, {}
        self.active = defaultdict(list)
        self.invalid_intervals = set()

    def entry(self, value: FrameEntry):
        _need(value.invocation not in self.entries, "duplicate invocation entry")
        stack = self.active[value.invocation.process_id, value.invocation.thread_id]
        self.entries[value.invocation] = _Entry(
            value.anchor, value.invocation, value.code, value.caller,
            value.caller_invocation, value.ancestor_invocation,
            value.path[-1].code if value.path else None, len(value.path), value.path_complete,
            value.suspended, stack[-1] if stack else None,
            len(value.parameters), value.parameters_complete,
            len(value.caller_locals), value.caller_locals_complete,
        )
        stack.append(value.invocation)
        key = value.invocation.process_id, value.code
        old = self.groups.get(key)
        self.groups[key] = EnteredCodeGroup(
            *key, old.count + 1 if old is not None else 1,
            old.first_invocation if old is not None else value.invocation, value.invocation,
            old.first_anchor if old is not None else value.anchor, value.anchor,
        )

    def exit(self, value: FrameExit):
        _need(value.invocation not in self.exits, "duplicate invocation exit")
        self.exits[value.invocation] = _Exit(value.anchor, value.invocation, value.code,
            value.return_site, value.completion, len(value.locals), value.locals_complete)
        stack = self.active[value.invocation.process_id, value.invocation.thread_id]
        if stack and stack[-1] == value.invocation:
            stack.pop()
        elif value.invocation in stack:
            position = stack.index(value.invocation)
            self.invalid_intervals.update(stack[position:])
            stack.pop(position)

    def abort(self):
        self.entries.clear()
        self.exits.clear()
        self.groups.clear()
        self.active.clear()
        self.invalid_intervals.clear()


class _Members:
    """Use exact retained names and bytes, then the shared coordinate API."""

    def __init__(self, coordinates: CaptureCoordinates, directory: Path):
        self.coordinates = coordinates
        _need(type(coordinates) is CaptureCoordinates, "coordinates must be CaptureCoordinates")
        _need(coordinates.artifact.sha256 == hashlib.sha256(coordinates.payload).hexdigest()
              and coordinates.artifact.size_bytes == len(coordinates.payload),
              "coordinate payload differs from its artifact")
        _need(_canonical(coordinates.report) == coordinates.payload,
              "coordinate report differs from its canonical payload")
        self.members = coordinates.report["membership"]
        self.selected = {}
        for path in directory.iterdir():
            match = _PATTERN.fullmatch(path.name)
            if match is None:
                continue
            family, process, suffix = match.groups()
            _need((family == "meta") == (suffix == "json") and not path.is_symlink() and path.is_file(),
                  "call artifact is not an ordinary supported file")
            key = int(process), family
            _need(key not in self.selected, "ambiguous plain/gzip call artifact")
            self.selected[key] = path.resolve()
        self.files, self.artifacts, self.processes, self.member_rows = {}, {}, {}, {}

    def _member(self, actual, logical):
        # Gzip-to-logical mapping is the existing call reader's naming protocol.
        # Original capture relocation additionally uses the explicit membership
        # logical_path.  Basename-only or PID-only matching is not accepted.
        rows = []
        for row in self.members:
            if "local_path" in row:
                if row["local_path"] != str(actual):
                    continue
                _need(row["artifact"]["uri"] == row["logical_path"]
                      and _logical(Path(row["local_path"])) == logical,
                      "coordinate logical URI/local retention path is inconsistent")
                rows.append(row)
            elif (row["artifact"]["uri"] == str(actual)
                  and (row["logical_path"] == logical
                       or _logical(Path(row["artifact"]["uri"])) == logical)):
                # Compatibility is restricted to the old report protocol,
                # whose artifact URI was its exact verified physical path.
                rows.append(row)
        _need(len(rows) <= 1, "ambiguous coordinate membership for a call artifact")
        return rows[0] if rows else None

    def bind(self, files):
        for file in files:
            key = file.process_id, file.family
            actual = self.selected.get(key)
            _need(actual is not None and _logical(actual) == file.path,
                  "scanner manifest differs from the selected actual call file")
            row = self._member(actual, file.path)
            artifact = ProviderArtifact(str(actual), file.raw_sha256, file.raw_bytes,
                "scar.call-edge-" + file.family + ".v1")
            process = None
            if row is not None:
                declared = decode(ProviderArtifact, row["artifact"])
                _need((declared.sha256, declared.size_bytes) == (file.raw_sha256, file.raw_bytes),
                      "call bytes differ from coordinate membership")
                process = self.coordinates.process_for(declared, file.process_id)
                _need(process is not None and process.run == self.coordinates.run.id
                      and encode(process.id) == row["process"],
                      "coordinate API does not reproduce the call member's process")
                artifact = declared
                self.member_rows[key] = row
            self.files[key], self.artifacts[key], self.processes[key] = file, artifact, process
        for pid, _ in self.files:
            present = [self.processes[pid, family] for family in ("codes", "events", "meta")]
            bound = [process for process in present if process is not None]
            _need(not bound or len(bound) == 3 and all(process == bound[0] for process in bound),
                  "call families have inconsistent coordinate process membership")

    def matches_path(self, path, key):
        file = self.files.get(key)
        if file is None:
            return False
        if path == file.path:
            return True
        row = self.member_rows.get(key)
        return row is not None and path == row["logical_path"]

    def fact(self, anchor, process_id, family="events"):
        key = process_id, family
        file = self.files[key]
        _need(self.matches_path(anchor.path, key) and anchor.line_number <= file.lines,
              "record anchor is outside its exact scanned call artifact")
        return ProviderFactReference(self.artifacts[key], "#/lines/" + str(anchor.line_number))

    def point(self, anchor, process_id, family="events"):
        source = self.fact(anchor, process_id, family)
        key = process_id, family
        process = self.processes[key]
        # An unbound input artifact remains a raw fact.  Assigning even an
        # unknown-process EvidencePoint would assert membership of this run.
        return EvidencePoint(self.coordinates.run.id, process.id, source) if process is not None else None


def _verify_seed_model(model, scanned, sink, members):
    expected = {(file.process_id, file.family): file for file in model.files}
    actual = {(file.process_id, file.family): file for file in scanned.files}
    _need(set(expected) == set(actual), "source witness and raw scan have different process/file families")
    for key, file in expected.items():
        _need(_manifest_key(file) == _manifest_key(actual[key]) and members.matches_path(file.path, key),
              "source witness is from different call bytes or an unbound path")
    captures = {(capture.process_id, capture.code.key): capture for capture in scanned.captures}
    expected_captures = {(capture.process_id, capture.code.key): capture for capture in model.codes}
    _need(set(captures) == set(expected_captures), "source witness captured-code denominator differs")
    for key, capture in expected_captures.items():
        observed = captures[key]
        _need(capture.code == observed.code and _anchor_key(capture.anchor) == _anchor_key(observed.anchor)
              and members.matches_path(capture.anchor.path, (capture.process_id, "codes")),
              "source witness code/descriptor/raw anchor differs from the current capture")
    groups = {(group.process_id, group.code): group for group in model.groups}
    _need(set(groups) == set(sink.groups), "source witness entered-code denominator differs")
    for key, group in groups.items():
        observed = sink.groups[key]
        _need(group.count == observed.count and group.first_invocation == observed.first_invocation
              and group.last_invocation == observed.last_invocation
              and _anchor_key(group.first_anchor) == _anchor_key(observed.first_anchor)
              and _anchor_key(group.last_anchor) == _anchor_key(observed.last_anchor)
              and members.matches_path(group.first_anchor.path, (group.process_id, "events"))
              and members.matches_path(group.last_anchor.path, (group.process_id, "events")),
              "source witness invocation counts/endpoints differ from the current capture")
    metadata = tuple(SeedCollectionMetadata.from_metadata(meta) for meta in scanned.metadata)
    _need(metadata == model.collection_metadata, "source witness collector metadata differs from raw replay")


class _SourceGuard:
    """Read decoded source once per witness snapshot; never parse or compile it."""

    def __init__(self, budget):
        self.budget = budget
        self.cache, self.records = {}, []
        self.raw_bytes = self.decoded_bytes = 0

    def check(self, snapshot):
        key = snapshot.path, snapshot.fingerprint, snapshot.python_version, snapshot.encoding
        if key in self.cache:
            return self.cache[key], self.records[self.cache[key]]
        result = {"path": snapshot.path, "expected_fingerprint": snapshot.fingerprint,
                  "actual_fingerprint": None, "raw_bytes": 0, "decoded_utf8_bytes": 0,
                  "status": "UNRESOLVED", "frontier": None,
                  "method": "tokenize.open decoded text, universal newlines, UTF-8 SHA256"}
        if len(self.records) >= self.budget.max_source_files:
            result["frontier"] = "CURRENT_SOURCE_FILE_BUDGET_EXCEEDED"
        elif self.decoded_bytes >= self.budget.max_source_bytes:
            result["frontier"] = "CURRENT_SOURCE_BYTE_BUDGET_EXCEEDED"
        else:
            path = Path(snapshot.path)
            try:
                _need(path.is_absolute() and str(path.resolve(strict=True)) == snapshot.path
                      and path.is_file(), "current source path is missing or noncanonical")
                before = path.stat()
                if before.st_size > self.budget.max_source_bytes - self.raw_bytes:
                    result["frontier"] = "CURRENT_SOURCE_BYTE_BUDGET_EXCEEDED"
                else:
                    digest, decoded = hashlib.sha256(), 0
                    self.raw_bytes += before.st_size
                    result["raw_bytes"] = before.st_size
                    with tokenize.open(str(path)) as source:
                        opened = os.fstat(source.fileno())
                        _need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                              == (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns),
                              "current source changed before its guarded read")
                        while text := source.read(65536):
                            payload = text.encode("utf-8")
                            decoded += len(payload)
                            self.decoded_bytes += len(payload)
                            if self.decoded_bytes > self.budget.max_source_bytes:
                                result["frontier"] = "CURRENT_SOURCE_BYTE_BUDGET_EXCEEDED"
                                break
                            digest.update(payload)
                        after = os.fstat(source.fileno())
                    result["decoded_utf8_bytes"] = decoded
                    current = path.stat()
                    _need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                          == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                          == (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns),
                          "current source changed during its guarded read")
                    if result["frontier"] is None:
                        result["actual_fingerprint"] = "sha256:" + digest.hexdigest()
                        if result["actual_fingerprint"] == snapshot.fingerprint:
                            result["status"] = "FINGERPRINT_MATCH"
                        else:
                            result["frontier"] = "CURRENT_SOURCE_DRIFT"
            except (OSError, UnicodeError, LookupError, RuntimeError, SyntaxError, ValueError) as error:
                result["frontier"] = "CURRENT_SOURCE_UNAVAILABLE_OR_CHANGED"
                result["detail"] = type(error).__name__ + ": " + str(error)
        index = len(self.records)
        self.records.append(result)
        self.cache[key] = index
        return index, result


def _static_admission_key(admission):
    # The old process/code origin is deliberately excluded: this is only a
    # source/body receipt, never an observation of the current process.
    return _canonical({"status": admission.status.value, "snapshot": encode(admission.snapshot),
        "definition": encode(admission.definition), "source": encode(admission.source),
        "core_region": encode(admission.core_region)})


def _source_key(snapshot, definition):
    return snapshot.path, snapshot.fingerprint, definition.wire


def _source_tables(composition):
    definitions, body_refs, snapshots = {}, {}, {}
    rows = composition.document["files"]
    _need(len(rows) == composition.inventory_file_count, "composition/inventory file denominator differs")
    for file_index in range(composition.inventory_file_count):
        raw = composition.inventory_file(file_index)
        snapshot = decode(SourceSnapshot, raw["snapshot"])
        _need(snapshot.path not in snapshots, "duplicate inventory source snapshot")
        snapshots[snapshot.path] = file_index, snapshot
        row = rows[file_index]
        _need(row["file_index"] == file_index and row["snapshot"] == raw["snapshot"],
              "composition file reference differs from original inventory")
        for definition_index, definition in enumerate(decode(tuple[DefinitionInventory, ...], raw["definitions"])):
            key = _source_key(snapshot, definition.id)
            _need(key not in definitions, "duplicate source-qualified definition identity in composition")
            definitions[key] = file_index, definition, definition_index
        for body_index, body in enumerate(row["bodies"]):
            original = composition.inventory_body(file_index, body_index)
            _need(body["definition"] == original["definition"]["wire"],
                  "composition body definition differs from its inventory pointer")
            if body["root"] is not None:
                _need(original["graph"] is not None
                      and original["graph"]["root"]["wire"] == body["root"]
                      and _sha(original["graph"]) == body["program_canonical_sha256"],
                      "composition body root/hash differs from original canonical graph")
                reference = {
                    "reference": encode(ElementReference(file_index,
                        RegionID(body["root"].split(":", 1)[1]), body_index)),
                    "inventory_pointer": body["inventory_pointer"] + "/graph" if not composition.partitioned else None,
                    "program_canonical_sha256": body["program_canonical_sha256"],
                    "program_schema_version": body["program_schema_version"],
                }
                if composition.partitioned:
                    locators = composition.inventory_body_locators(file_index, body_index, original["graph"])
                    _need(all(body.get(name) == value for name, value in locators.items()),
                          "composition body locator/namespace differs from original source shard/checkpoint")
                    reference.update({"canonical_locator": locators["graph_locator"],
                        "inventory_locator": locators["inventory_locator"],
                        "metadata_locator": locators["metadata_locator"], "namespace": locators["namespace"]})
                elif composition.has_source_entry_publication:
                    locators = composition.qualified_inventory_body_locators(file_index, body_index, original["graph"])
                    reference.update({"canonical_locator": locators["graph_locator"],
                        "inventory_locator": locators["inventory_locator"],
                        "metadata_locator": locators["metadata_locator"], "namespace": locators["namespace"]})
                body_refs[(snapshot.path, snapshot.fingerprint, body["definition"])] = reference
    return definitions, body_refs, snapshots


def _binding_rows(composition, model, scope, sink, captures, members, witness_mode, source_guard):
    definitions, bodies, snapshots = _source_tables(composition)
    links = {link.code: (index, link) for index, link in enumerate(model.code_links)} if model is not None else {}
    admissions = {(item.origin.process_id, item.origin.code): (index, item)
                  for index, item in enumerate(scope.admissions)} if scope is not None else {}
    descriptors, descriptor_pointers, descriptor_locators, static_admissions = {}, {}, {}, defaultdict(list)
    if model is not None:
        for index, old_capture in enumerate(model.codes):
            previous = descriptors.get(old_capture.code.key)
            _need(previous is None or previous == old_capture.code,
                  "stored descriptor witnesses disagree for one complete code key")
            descriptors[old_capture.code.key] = old_capture.code
            if composition.partitioned:
                descriptor_locators.setdefault(old_capture.code.key,
                    composition.inventory_component_locator("call_sources", f"/model/codes/{index}/code"))
            else:
                descriptor_pointers.setdefault(old_capture.code.key, f"#/call_sources/model/codes/{index}/code")
    for index, admission in enumerate(scope.admissions if scope is not None else ()):
        static_admissions[admission.origin.code].append((index, admission))
    rows, indexes = [], {}
    for key in sorted(sink.groups):
        pid, code = key
        capture = captures.get(key)
        linked = links.get(code)
        admitted = admissions.get(key)
        static_candidates, admission_conflict = [], False
        descriptor_match = capture is not None and descriptors.get(code) == capture.code
        if witness_mode == "reused_code":
            if not descriptor_match:
                linked = None
            admitted = None
            if linked is not None:
                static_candidates = static_admissions.get(code, [])
                if len({_static_admission_key(item) for _, item in static_candidates}) > 1:
                    admission_conflict = True
                elif static_candidates:
                    admitted = static_candidates[0]
        row = {"binding_index": len(rows), "process_id": pid, "code": code,
               "entered_invocations": sink.groups[key].count, "status": "UNRESOLVED",
               "source_verification": "REUSED_CODE_SOURCE_WITNESS" if linked is not None else None,
               "witness_mode": witness_mode, "complete_descriptor_match": descriptor_match,
               "code_capture": encode(capture) if capture is not None else None,
               "descriptor_witness_pointer": descriptor_pointers.get(code) if descriptor_match else None,
               "code_source_witness_pointer": f"#/call_sources/model/code_links/{linked[0]}" if linked and not composition.partitioned else None,
               "admission_pointer": f"#/call_source_scope/admissions/{admitted[0]}" if admitted and witness_mode == "same_capture" and not composition.partitioned else None,
               "static_body_witness_pointers": [f"#/call_source_scope/admissions/{index}" for index, _ in static_candidates] if not composition.partitioned else [],
               "current_source_check": None,
               "snapshot": None, "source": None, "definition": None, "body": None,
               "interface_frontiers": list(_INTERFACE_FRONTIERS), "frontiers": []}
        if composition.partitioned:
            row.update({"descriptor_witness_locator": descriptor_locators.get(code) if descriptor_match else None,
                "code_source_witness_locator": composition.inventory_component_locator(
                    "call_sources", f"/model/code_links/{linked[0]}") if linked else None,
                "admission_locator": composition.inventory_component_locator(
                    "call_source_scope", f"/admissions/{admitted[0]}") if admitted and witness_mode == "same_capture" else None,
                "static_body_witness_locators": [composition.inventory_component_locator(
                    "call_source_scope", f"/admissions/{index}") for index, _ in static_candidates],
                "definition_locator": None})
        if capture is None:
            row["frontiers"].append("MISSING_PROCESS_CODE_CAPTURE")
        if linked is None:
            row["frontiers"].append("NO_MATCHING_CODE_WITNESS" if witness_mode == "reused_code"
                                    else "MISSING_CODE_SOURCE_WITNESS")
        elif capture is not None:
            link = linked[1]
            row["witness_status"] = link.status.value
            row["witness_issues"] = encode(link.issues)
            if link.status is not CallLinkStatus.VERIFIED:
                row["frontiers"].append("CODE_SOURCE_" + link.status.value)
            else:
                _need(link.snapshot is not None and capture.code.filename == link.snapshot.path,
                      "verified code/source witness changes the captured code filename")
                if witness_mode == "reused_code":
                    check_index, check = source_guard.check(link.snapshot)
                    row["current_source_check"] = check_index
                    if check["status"] != "FINGERPRINT_MATCH":
                        row["frontiers"].append(check["frontier"])
                        if members.processes[pid, "events"] is None:
                            row["frontiers"].append("CAPTURE_PROCESS_MEMBERSHIP_UNRESOLVED")
                        indexes[key] = len(rows)
                        rows.append(row)
                        continue
                row["snapshot"] = encode(link.snapshot)
                if link.definition is None or link.source is None:
                    row["frontiers"].append("VERIFIED_CODE_WITHOUT_DEFINITION_WITNESS")
                else:
                    located = snapshots.get(link.snapshot.path)
                    found = definitions.get(_source_key(link.snapshot, link.definition))
                    if located is None:
                        row["frontiers"].append("SOURCE_NOT_IN_COMPOSITION")
                    elif located[1] != link.snapshot:
                        row["frontiers"].append("SOURCE_SNAPSHOT_MISMATCH")
                    elif found is None or found[0] != located[0] or found[1].source != link.source:
                        row["frontiers"].append("DEFINITION_SOURCE_WITNESS_MISMATCH")
                    elif composition.document["files"][located[0]]["status"] == "GAP":
                        row["frontiers"].append("SOURCE_COMPOSITION_UNAVAILABLE")
                    else:
                        file_index, definition, definition_index = found
                        row["source"] = encode(link.source)
                        row["definition"] = encode(ElementReference(file_index, definition.id))
                        if composition.partitioned:
                            row["definition_locator"] = composition.inventory_file_locator(
                                file_index, f"/definitions/{definition_index}")
                        row["status"] = "SOURCE_LINKED_REUSED_WITNESS"
                        if admitted is None:
                            row["frontiers"].append("STATIC_BODY_WITNESS_CONFLICT" if admission_conflict
                                                    else "MISSING_FINAL_SOURCE_ADMISSION")
                        else:
                            admission = admitted[1]
                            if admission.status in (CallSourceAdmissionStatus.UNAVAILABLE, CallSourceAdmissionStatus.MISMATCH):
                                row["frontiers"].append("FINAL_ADMISSION_" + admission.status.value)
                                row["admission_reason"] = admission.reason
                            else:
                                _need(admission.snapshot == link.snapshot and admission.definition == link.definition
                                      and admission.source == link.source,
                                      "final source admission contradicts the exact code/source witness")
                                body = bodies.get(_source_key(link.snapshot, definition.id))
                                if admission.status is CallSourceAdmissionStatus.CORE_LINKED:
                                    _need(body is not None and body["reference"]["identity"]["wire"] == admission.core_region.wire,
                                          "final source admission points at a different/missing canonical body")
                                    row["body"] = body
                                    row["status"] = "BODY_LINKED_REUSED_WITNESS"
                                else:
                                    _need(body is None, "indexed-only source admission contradicts an emitted body")
                                    row["frontiers"].append("CANONICAL_BODY_UNAVAILABLE")
                                    row["admission_reason"] = admission.reason
        if members.processes[pid, "events"] is None:
            row["frontiers"].append("CAPTURE_PROCESS_MEMBERSHIP_UNRESOLVED")
        indexes[key] = len(rows)
        rows.append(row)
    return rows, indexes


def _formal_binding_rows(composition, bindings, captures, members, *, witness_mode="same_capture"):
    """Use one shared original-definition resolver; no new inventory or body."""
    composition.prefetch_definition_references((
        (row["definition"]["file_index"], decode(OperationDefinitionID, row["definition"]["identity"]))
        for row in bindings if row["definition"] is not None))
    for row in bindings:
        row["source_origin"] = "INVENTORY"
        row["composition_element"] = row["definition"]
        row["attachment_witness"] = None
        row["attachment_frontiers"] = []
        key = row["process_id"], row["code"]
        attached = composition.attached_code_witness(*key) if witness_mode == "same_capture" else None
        if attached is not None and attached["record"]["status"] != "PROGRAM_SCOPE_RETAINED":
            row["attachment_frontiers"] = [gap["code"] for gap in attached["record"]["frontiers"]]
        if attached is not None and attached["record"]["status"] == "SOURCE_VERIFIED":
            record = attached["record"]
            capture = captures.get(key)
            _need(attached["capture_verified"] is True and capture is not None
                  and record["captured_code"] == encode(capture.code)
                  and record["descriptor_anchor"] == encode(capture.anchor)
                  and record["entered_invocations"] == row["entered_invocations"],
                  "attached source witness has no exact current-capture descriptor/group proof")
            _need(row["definition"] is None and row["body"] is None,
                  "attachment contradicts an already bound project definition/body")
            link = record["code_source_link"]
            reference = composition.attached_definition_reference(*key)
            row.update(source_origin="SOURCE_ATTACHMENT", composition_element=None,
                complete_descriptor_match=True, source_verification="REUSED_HISTORICAL_CODE_SOURCE_WITNESS",
                witness_status="VERIFIED", witness_issues=link["issues"],
                snapshot=link["snapshot"], source=link["source"],
                definition=encode(reference) if reference is not None else None, body=None,
                definition_locator=encode(reference.graph) if reference is not None else None,
                descriptor_witness_pointer=None, code_source_witness_pointer=None, admission_pointer=None,
                static_body_witness_pointers=[], descriptor_witness_locator=None,
                code_source_witness_locator=None, admission_locator=None, static_body_witness_locators=[],
                current_source_check=None, frontiers=list(row["attachment_frontiers"]))
            row["attachment_witness"] = {
                "record_locator": encode(attached["record_locator"]),
                "descriptor_locator": encode(attached["descriptor_locator"]),
                "code_source_locator": encode(attached["code_source_locator"]),
                "code_source_link": link, "witness_scope": attached["witness_scope"],
                "source_compiler_witness_reused": record["source_compiler_witness_reused"],
                "source_compiler_matching_performed": record["source_compiler_matching_performed"],
                "guard_scope": attached["guard_scope"], "guard": attached["guard"],
                "guard_locator": encode(attached["guard_locator"]) if attached["guard_locator"] is not None else None,
            }
            if reference is not None:
                row["status"] = "SOURCE_LINKED_REUSED_WITNESS"
                qualified = composition.body_reference(reference) if composition.has_source_entry_publication else None
                if qualified is None:
                    row["frontiers"].append("CANONICAL_BODY_NOT_MODELLED_BY_SOURCE_ATTACHMENT")
                else:
                    admission = composition.entry_body_admission(*key, qualified)
                    _need(admission["origin"]["process_id"] == key[0] and admission["origin"]["code"] == key[1]
                          and admission["status"] == CallSourceAdmissionStatus.CORE_LINKED.value
                          and admission["snapshot"] == row["snapshot"]
                          and admission["definition"] == encode(reference.definition)
                          and admission["source"] == row["source"]
                          and admission["core_region"] == encode(qualified.identity),
                          "qualified body admission contradicts the exact current code/source witness")
                    row["body"] = composition.qualified_body_record(qualified)
                    row["qualified_body_admission"] = admission
                    row["status"] = "BODY_LINKED_REUSED_WITNESS"
            else:
                row["status"] = "UNRESOLVED"
                row["frontiers"].append("VERIFIED_CODE_WITHOUT_DEFINITION_WITNESS")
            if members.processes[key[0], "events"] is None:
                row["frontiers"].append("CAPTURE_PROCESS_MEMBERSHIP_UNRESOLVED")
        else:
            for frontier in row["attachment_frontiers"]:
                if frontier not in row["frontiers"]:
                    row["frontiers"].append(frontier)
            if row["definition"] is not None:
                element = row["definition"]
                reference = composition.definition_reference(element["file_index"],
                    decode(OperationDefinitionID, element["identity"]))
                _need(encode(reference.snapshot) == row["snapshot"] and encode(reference.source) == row["source"],
                      "formal project definition differs from its original code/source witness")
                row["definition"] = encode(reference)
    return bindings


def _reused_attachment_rows(composition, bindings, captures, scanned, source_guard, profile):
    """Current dynamics + exact historical static proof, with distinct guards."""
    builds = {meta["process_id"]: meta["python"] for meta in scanned.metadata}
    for row in bindings:
        capture = captures.get((row["process_id"], row["code"]))
        if capture is None:
            continue
        witness = composition.static_code_witness(capture.code, compilation_profile=profile,
            captured_python_build=builds[row["process_id"]])
        if witness is None:
            if row.get("witness_status") != "VERIFIED":
                row["frontiers"].append("NO_MATCHING_STATIC_CODE_SOURCE_WITNESS")
            continue
        if witness["status"] != "SOURCE_VERIFIED":
            row["source_context_guard"] = witness["context_guard"]
            for gap in witness["historical_frontiers"]:
                if gap["code"] not in row["frontiers"]:
                    row["frontiers"].append(gap["code"])
            if witness["context_guard"]["status"] != "MATCH":
                row["historical_definition"] = row["definition"]
                row.update(definition=None, composition_element=None, definition_locator=None,
                           snapshot=None, source=None, body=None, status="UNRESOLVED")
                row["frontiers"].extend(witness["context_guard"]["frontiers"])
            continue
        _need(row["definition"] is None and row["body"] is None,
              "external static source witness contradicts an existing project definition")
        link = witness["code_source_link"]
        reference = composition.static_definition_reference(witness)
        check_index, check = source_guard.check(decode(SourceSnapshot, link["snapshot"]))
        usable = witness["context_guard"]["status"] == "MATCH" and check["status"] == "FINGERPRINT_MATCH"
        gaps = list(witness["context_guard"]["frontiers"])
        if "CAPTURE_PROCESS_MEMBERSHIP_UNRESOLVED" in row["frontiers"]:
            gaps.append("CAPTURE_PROCESS_MEMBERSHIP_UNRESOLVED")
        if check["frontier"] is not None:
            gaps.append(check["frontier"])
        row.update(source_origin="SOURCE_ATTACHMENT", composition_element=None,
            complete_descriptor_match=True, source_verification="REUSED_HISTORICAL_CODE_SOURCE_WITNESS",
            witness_status="VERIFIED", witness_issues=link["issues"],
            snapshot=link["snapshot"] if usable else None,
            source=link["source"] if usable else None,
            definition=encode(reference) if usable and reference is not None else None, body=None,
            definition_locator=encode(reference.graph) if usable and reference is not None else None,
            descriptor_witness_pointer=None, code_source_witness_pointer=None, admission_pointer=None,
            static_body_witness_pointers=[], descriptor_witness_locator=None,
            code_source_witness_locator=None, admission_locator=None, static_body_witness_locators=[],
            current_source_check=check_index, attachment_frontiers=gaps, frontiers=list(gaps),
            attachment_witness={"static_witness": witness,
                "historical_definition": encode(reference) if reference is not None else None,
                "current_guard_scope": "CURRENT_REUSED_CODE_SOURCE_FINGERPRINT",
                "current_guard_index": check_index})
        if usable and reference is not None:
            row["status"] = "SOURCE_LINKED_REUSED_WITNESS"
            row["frontiers"].append("CANONICAL_BODY_NOT_MODELLED_BY_SOURCE_ATTACHMENT")
        else:
            row["status"] = "UNRESOLVED"
            if usable:
                row["frontiers"].append("VERIFIED_CODE_WITHOUT_DEFINITION_WITNESS")
    return bindings


def _parent(entry, sink, incomplete_processes):
    direct = entry.caller_invocation
    ancestor = entry.ancestor_invocation
    relation = "DIRECT_RECORDED_PARENT" if direct is not None else (
        "RETAINED_ANCESTOR" if ancestor is not None else "NO_RECORDED_PARENT")
    result = {"relation": relation, "caller_invocation": encode(direct) if direct else None,
              "ancestor_invocation": encode(ancestor) if ancestor else None,
              "retained_stack_parent": encode(entry.expected_parent) if entry.expected_parent else None,
              "path_length": entry.path_length, "path_complete": entry.path_complete,
              "qualification": "UNRESOLVED", "direct_callsite_established": False, "frontiers": []}
    if entry.invocation.process_id in incomplete_processes:
        result["frontiers"].append("COLLECTION_PARTIAL")
    if not entry.path_complete:
        result["frontiers"].append("PATH_INCOMPLETE")
    if entry.suspended:
        result["frontiers"].append("SUSPENDABLE_FRAME_OBSERVATION")
    parent_id = direct if direct is not None else ancestor
    if parent_id is None:
        if entry.expected_parent is not None:
            result["frontiers"].append("ACTIVE_RETAINED_PARENT_NOT_IDENTIFIED")
        else:
            result["frontiers"].append("NO_PARENT_ENTRY_WITNESS")
        return result
    parent = sink.entries.get(parent_id)
    own_exit, parent_exit = sink.exits.get(entry.invocation), sink.exits.get(parent_id)
    if parent is None:
        result["frontiers"].append("PARENT_ENTRY_MISSING")
        return result
    if parent_id != entry.expected_parent or parent_id == entry.invocation:
        result["frontiers"].append("RETAINED_STACK_PARENT_MISMATCH")
    expected_code = entry.caller.code if direct is not None and entry.caller else entry.last_path_code
    if expected_code is None or parent.code != expected_code:
        result["frontiers"].append("PARENT_CODE_MISMATCH")
    if direct is not None and not (direct == ancestor and entry.path_length == 1 and entry.caller is not None):
        result["frontiers"].append("DIRECT_PATH_NOT_ESTABLISHED")
    if entry.invocation in sink.invalid_intervals or parent_id in sink.invalid_intervals:
        result["frontiers"].append("FRAME_INTERVAL_CONFLICT")
    if own_exit is None or parent_exit is None:
        result["frontiers"].append("FRAME_EXIT_MISSING")
    elif (own_exit.code != entry.code or own_exit.return_site.code != entry.code
          or parent_exit.code != parent.code or parent_exit.return_site.code != parent.code
          or not parent.anchor.index < entry.anchor.index < own_exit.anchor.index < parent_exit.anchor.index):
        result["frontiers"].append("FRAME_INTERVAL_MISMATCH")
    if not result["frontiers"]:
        result["qualification"] = "RECORDED_FRAME_INTERVAL_MATCH"
    return result


def _completion(exit_record, members):
    if exit_record is None:
        return {"status": "MISSING", "canonical_exit_connected": False}
    point = members.point(exit_record.anchor, exit_record.invocation.process_id)
    return {"status": "COLLECTOR_OBSERVATION", "kind": exit_record.completion.value,
            "anchor": encode(exit_record.anchor),
            "point": encode(point) if point is not None else None,
            "raw_source": encode(members.fact(exit_record.anchor, exit_record.invocation.process_id)),
            "return_site": encode(exit_record.return_site),
            "raw_fields": ["return_ref", "locals"],
            "locals_count": exit_record.locals_count, "locals_complete": exit_record.locals_complete,
            "canonical_exit_connected": False}


def _write_rows(path, rows):
    digest, count, raw_bytes = hashlib.sha256(), 0, 0
    with path.open("xb") as stream:
        with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as zipped:
            for row in rows:
                payload = _canonical(row) + b"\n"
                zipped.write(payload)
                digest.update(payload)
                raw_bytes += len(payload)
                count += 1
    return {"path": path.name, "rows": count, "raw_sha256": digest.hexdigest(),
            "raw_bytes": raw_bytes, "compressed_bytes": path.stat().st_size}


def bind_source_invocations(composition: CompositionIndex, coordinates: CaptureCoordinates,
                            trace_directory, out_dir, *, call_budget=CallEdgeBudget(),
                            witness_mode="same_capture", seed_verification_budget=None):
    """Independently read raw frames through the unchanged public contract."""
    return _bind_source_invocations(composition, coordinates, trace_directory, out_dir,
        call_budget=call_budget, witness_mode=witness_mode, seed_verification_budget=seed_verification_budget)


def _bind_source_invocations_owned(owner, composition, coordinates, trace_directory, out_dir, **kwargs):
    from scar.analysis.current_source_evidence import _OwnedCurrent
    _need(type(owner) is _OwnedCurrent, "owned source reader must be created by current orchestration")
    return _bind_source_invocations(composition, coordinates, trace_directory, out_dir, _owner=owner, **kwargs)


def _bind_source_invocations(composition: CompositionIndex, coordinates: CaptureCoordinates,
                             trace_directory, out_dir, *, call_budget=CallEdgeBudget(),
                             witness_mode="same_capture", seed_verification_budget=None, _owner=None):
    """Reuse exact source witnesses and bind every recorded invocation.

    There is no target execution or compiler/source replay.  With an inventory
    seed report, same_capture requires all raw files/codes/groups/metadata to
    reproduce that capture.  Explicit reused_code mode reuses only matching
    complete code/source witnesses plus current source fingerprint guards;
    dynamic facts always come from the current scan and coordinates.
    """
    _need(type(composition) is CompositionIndex, "composition must be CompositionIndex")
    _need(type(call_budget) is CallEdgeBudget, "call_budget must be CallEdgeBudget")
    _need(type(witness_mode) is str and witness_mode in ("same_capture", "reused_code"),
          "witness_mode must be same_capture or reused_code")
    source_version = (4 if composition.has_source_entry_publication else
                      3 if composition.has_source_attachments else 2 if composition.partitioned else 1)
    _need(source_version != 4 or witness_mode == "same_capture",
          "qualified entry publication currently requires the ordinary exact same-capture binder")
    _need(seed_verification_budget is None or source_version == 4
          and type(seed_verification_budget) is CallEdgeBudget,
          "independent seed metadata budget requires the explicit v4 contract")
    call_budget.__post_init__()
    seed_budget = call_budget if seed_verification_budget is None else seed_verification_budget
    seed_budget.__post_init__()
    output = Path(out_dir).resolve()
    _need(not output.exists() and not output.is_symlink(), "output directory already exists")
    directory = Path(trace_directory).resolve()
    _need(directory.is_dir(), "trace directory is missing")
    discovery = composition.inventory_component("discovery")
    _need(type(discovery) is dict and type(discovery.get("project_root")) is str,
          "inventory lacks its original project root")
    root = discovery["project_root"]
    seed_document = composition.inventory_component("call_sources")
    seed_model = (CallSourceSeedReport._decode_replay_input(seed_document, verification_budget=seed_budget)
                  if seed_document is not None else None)
    if seed_model is not None:
        _need(seed_model.project_root == root, "source witness project root differs from inventory discovery")
    scope_document = composition.inventory_component("call_source_scope")
    scope = decode(CallSourceScope, scope_document) if scope_document is not None else None
    _need(seed_model is not None or scope is None, "source admissions have no bound seed model")
    if seed_model is not None and scope is not None:
        eligible = {(group.process_id, group.code) for group in seed_model.eligible_groups()}
        admitted = {(item.origin.process_id, item.origin.code) for item in scope.admissions}
        _need(admitted == eligible, "final admission denominator differs from eligible code/source groups")
    members = _Members(coordinates, directory)
    if _owner is None:
        sink = _Sink()
        scanned = scan_call_trace(directory, root, call_budget, sink=sink)
    else:
        _need(witness_mode == "reused_code" and _owner.proof is not None,
              "owned current source path requires exact retained static proof")
        scanned, sink = _owner.source_inputs(directory, root, call_budget, coordinates)
    members.bind(scanned.files)
    if seed_model is not None and witness_mode == "same_capture":
        _verify_seed_model(seed_model, scanned, sink, members)
    attachment_capture_checks = (composition.verify_source_attachments(scanned, tuple(sink.groups.values()))
        if witness_mode == "same_capture" else composition.source_attachment_reuse_checks(scanned, tuple(sink.groups.values())))
    captures = {(capture.process_id, capture.code.key): capture for capture in scanned.captures}
    source_guard = ((_owner.proof.guards() if _owner is not None else _SourceGuard(call_budget))
                    if witness_mode == "reused_code" else None)
    bindings, binding_indexes = _binding_rows(composition, seed_model, scope, sink, captures,
                                             members, witness_mode, source_guard)
    if composition.has_source_attachments:
        if witness_mode == "reused_code":
            _need(seed_model is not None and all(declaration["trace_files"] == encode(seed_model.files)
                  for declaration in composition.attachment_capture_declarations()),
                  "project static witness and attachment historical raw origins differ")
        bindings = _formal_binding_rows(composition, bindings, captures, members, witness_mode=witness_mode)
        if witness_mode == "reused_code":
            profile = CallSourceSeedReport._compilation_profile(seed_document).value
            bindings = _reused_attachment_rows(composition, bindings, captures, scanned, source_guard, profile)
    incomplete = {meta["process_id"] for meta in scanned.metadata if meta["dropped_events"]
                  or meta["dropped_codes"] or meta["errors"] or meta.get("io_failed")}
    incomplete.update(invocation.process_id for invocation in sink.exits if invocation not in sink.entries)
    counts, frontiers, parent_relations, qualifications = Counter(), Counter(), Counter(), Counter()
    output.parent.mkdir(parents=True, exist_ok=True)

    def invocation_rows():
        for invocation, entry in sorted(sink.entries.items(), key=lambda item: (item[0].process_id, item[1].anchor.index)):
            key = invocation.process_id, entry.code
            binding_index = binding_indexes[key]
            binding = bindings[binding_index]
            point = members.point(entry.anchor, invocation.process_id)
            parent = _parent(entry, sink, incomplete)
            exit_record = sink.exits.get(invocation)
            missing = list(binding["frontiers"])
            if entry.suspended:
                missing.append("FRAME_RESUMPTION_CONTINUITY_UNRECOVERED")
            if exit_record is None:
                missing.append("FRAME_EXIT_MISSING")
            elif (exit_record.code != entry.code or exit_record.return_site.code != entry.code
                  or exit_record.anchor.index <= entry.anchor.index):
                missing.append("FRAME_EXIT_CODE_OR_ORDER_MISMATCH")
            if invocation.process_id in incomplete:
                missing.append("COLLECTION_PARTIAL")
            activation = None
            if binding["body"] is not None and point is not None and not entry.suspended:
                if binding["body"].get("kind") == "QUALIFIED_SOURCE_BODY":
                    _need(source_version == 4, "qualified body acquired a legacy binding schema")
                    qualified = decode(QualifiedSourceBodyReference, binding["body"]["reference"])
                    _need(encode(qualified.definition) == binding["definition"],
                          "invocation body belongs to a different qualified definition")
                    region = qualified.identity
                else:
                    region = decode(RegionID, binding["body"]["reference"]["identity"])
                identity = RegionActivationID(coordinates.run.id.value + ":source-frame:" + _sha({
                    "process": encode(point.process), "invocation": encode(invocation),
                    "entry": encode(point.source)}))
                activation = RegionActivation(identity, region, point.process, point)
            counts[binding["status"]] += 1
            parent_relations[parent["relation"]] += 1
            qualifications[parent["qualification"]] += 1
            frontiers.update(missing)
            frontiers.update("PARENT_" + reason for reason in parent["frontiers"])
            row = {"kind": "INVOCATION", "invocation": encode(invocation),
                   "code": entry.code, "source_binding_index": binding_index,
                   "anchor": encode(entry.anchor), "point": encode(point) if point is not None else None,
                   "raw_source": encode(members.fact(entry.anchor, invocation.process_id)),
                   "host_thread": encode(coordinates.thread_for(members.artifacts[invocation.process_id, "events"],
                                               invocation.thread_id, "python_ident")) if point is not None else None,
                   "region_activation": encode(activation) if activation is not None else None,
                   "parent": parent, "completion": _completion(exit_record, members),
                   "suspended": entry.suspended,
                   "raw_entry_fields": ["parameters", "caller_locals", "caller", "path"],
                   "parameters_count": entry.parameters_count, "parameters_complete": entry.parameters_complete,
                   "caller_locals_count": entry.caller_locals_count,
                   "caller_locals_complete": entry.caller_locals_complete,
                   "status": binding["status"], "frontiers": missing,
                   "actual_formal_return_connected": False, "environment_state_connected": False}
            if composition.partitioned or source_version == 4:
                row["region_namespace"] = binding["body"]["namespace"] if binding["body"] is not None else None
            yield row

    def orphan_rows():
        for invocation, exit_record in sorted(sink.exits.items(), key=lambda item: (item[0].process_id, item[1].anchor.index)):
            if invocation not in sink.entries:
                frontiers["EXIT_WITHOUT_ENTRY"] += 1
                yield {"kind": "ORPHAN_EXIT", "invocation": encode(invocation), "code": exit_record.code,
                       "completion": _completion(exit_record, members), "frontiers": ["EXIT_WITHOUT_ENTRY"]}

    with tempfile.TemporaryDirectory(prefix=".source-invocations-", dir=output.parent) as temporary:
        stage = Path(temporary)
        invocation_file = _write_rows(stage / "invocations.jsonl.gz", invocation_rows())
        orphan_file = _write_rows(stage / "orphan-exits.jsonl.gz", orphan_rows())
        binding_document = {"schema": "scar.source-invocation-bindings", "schema_version": source_version,
                            "witness_mode": witness_mode, "bindings": bindings, **_AUTHORITY}
        if source_version in (3, 4):
            binding_document.update(source_definition_reference_format="scar.source-definition-reference.v1",
                                    source_inputs=composition.source_inputs())
            if witness_mode == "reused_code":
                binding_document["attachment_source_match_rule"] = "EXACT_CAPTURED_CODE_STATIC_REUSE_V1"
            if source_version == 4:
                binding_document["source_body_reference_format"] = "scar.qualified-source-body-reference.v1"
                binding_document.update(source_seed_verification_budget=encode(seed_budget), call_budget=encode(call_budget),
                    budget_roles={"source_seed_verification_budget": "original seed metadata decode ceiling only; no raw/source I/O grant",
                                  "call_budget": "actual fresh raw scan and current source guards"},
                    actual_call_scan={"raw_bytes": sum(file.raw_bytes for file in scanned.files),
                                      "lines": sum(file.lines for file in scanned.files),
                                      "captured_codes": len(scanned.captures), "entered_groups": len(sink.groups)})
        if _owner is not None:
            binding_document.update(raw_reader_rule="OWNED_CURRENT_OPERAND_FRAME_SCAN_V1",
                same_run_source_proof=_owner.proof.receipt())
        binding_payload = _canonical(binding_document)
        (stage / "bindings.json").write_bytes(binding_payload)
        (stage / "capture-coordinates.json").write_bytes(coordinates.payload)
        _need(invocation_file["rows"] == sum(group.count for group in sink.groups.values())
              == sum(meta["invocations"] for meta in scanned.metadata),
              "published invocation denominator differs from complete raw replay")
        report = {
            "schema": "scar.source-invocations", "schema_version": source_version,
            "scope": "observed frame entries to original source/body; reused code/source witness",
            "inventory": composition.document["inventory"],
            "composition_canonical_sha256": _sha(composition.document),
            "coordinate_binding": encode(coordinates.artifact), "run": encode(coordinates.run),
            "witness_mode": witness_mode,
            "source_witness_present": seed_model is not None,
            "source_witness_raw_manifest_replayed": seed_model is not None and witness_mode == "same_capture",
            "old_capture_dynamic_facts_used_for_current_run": False,
            "current_capture_raw_scan_verified": True,
            "current_source_checks": source_guard.records if source_guard is not None else [],
            "source_compilation_profile": CallSourceSeedReport._compilation_profile(seed_document).value
                                          if seed_document is not None else None,
            "trace_files": encode(scanned.files), "collection_metadata": list(scanned.metadata),
            "raw_scan_issues": encode(scanned.issues),
            "call_budget": encode(call_budget),
            "bindings": {"path": "bindings.json", "raw_sha256": hashlib.sha256(binding_payload).hexdigest(),
                         "raw_bytes": len(binding_payload)},
            "invocations": invocation_file, "orphan_exits": orphan_file,
            "summary": {"processes": len(scanned.metadata), "code_captures": len(scanned.captures),
                        "coordinate_bound_processes": sum(members.processes[meta["process_id"], "events"] is not None
                                                          for meta in scanned.metadata),
                        "entered_code_groups": len(sink.groups), "invocations": len(sink.entries),
                        "exits": len(sink.exits), "orphan_exits": orphan_file["rows"],
                        "source_binding_statuses": dict(sorted(Counter(row["status"] for row in bindings).items())),
                        "invocation_statuses": dict(sorted(counts.items())),
                        "parent_relations": dict(sorted(parent_relations.items())),
                        "parent_qualifications": dict(sorted(qualifications.items())),
                        "complete_descriptor_matches": sum(row["complete_descriptor_match"] for row in bindings),
                        "current_source_check_statuses": dict(sorted(Counter(check["status"]
                            for check in (source_guard.records if source_guard is not None else ())).items())),
                        "unconnected_interfaces": {name: len(sink.entries) for name in _INTERFACE_FRONTIERS},
                        "frontiers": dict(sorted(frontiers.items()))},
            "conditions": [
                "source association reuses the bound inventory producer's exact code/source witness",
                "this adapter does not independently repeat its compiler/source matching",
                "collector and retained artifact producer follow their declared capture protocols",
                "source and canonical body references are fragments, not a merged ProgramSnapshot",
                "a recorded frame parent interval is not an actual/formal/return, environment, effect or ATen callsite proof",
            ], **_AUTHORITY,
        }
        if source_version in (3, 4):
            report.update(source_definition_reference_format="scar.source-definition-reference.v1",
                source_inputs=composition.source_inputs(), attachment_capture_checks=attachment_capture_checks,
                attachment_scope="original source fragments; no added inventory files or typed bodies")
            if source_version == 4:
                report.update(source_body_reference_format="scar.qualified-source-body-reference.v1",
                    attachment_scope="original qualified source/body fragments; unchanged project inventory",
                    body_association_scope="complete current captured code to original source definition and admitted body; no callable/environment proof")
                report.update({name: binding_document[name] for name in
                    ("source_seed_verification_budget", "budget_roles", "actual_call_scan")})
            if witness_mode == "reused_code":
                report["attachment_source_match_rule"] = "EXACT_CAPTURED_CODE_STATIC_REUSE_V1"
        if _owner is not None:
            report.update(raw_reader_rule="OWNED_CURRENT_OPERAND_FRAME_SCAN_V1",
                raw_frames_read_by="shared owned operand/frame reader",
                same_run_source_proof=_owner.proof.receipt(),
                source_guard_scope="REUSED_COMPLETED_CURRENT_CAPTURE_AT_RECORDED_BINDING_NOT_FRESH_LIVE",
                current_source_guards_refreshed=False)
        (stage / "report.json").write_bytes(_canonical(report))
        # All scanning, cross-input checking and row creation have succeeded.
        # Reserve the caller's destination exclusively, publish data first, and
        # publish report.json last as the completion receipt.
        output.mkdir(exist_ok=False)
        for name in ("capture-coordinates.json", "bindings.json", "invocations.jsonl.gz", "orphan-exits.jsonl.gz", "report.json"):
            os.rename(stage / name, output / name)
    return report


__all__ = ["bind_source_invocations"]
