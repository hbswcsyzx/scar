"""Lazy access to original source/body fragments for existing call consumers.

No ProgramInventory is reconstructed. Existing canonical IDs, producers,
interfaces and overlays remain in their checksum-bound source/CP artifacts.
The source-binding report supplies code provenance, while the current operand
reader independently supplies every dynamic invocation and original manifest.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace

from scar.analysis.code_witness import CodeWitnessStore, CodeWitnessUnavailable
from scar.analysis.program_composition import CompositionIndex
from scar.ir.execution.coordinates import ExecutionRun
from scar.ir.program.call_edges import (
    CapturedCode, CodeCapture, CodeSourceLink, CallLinkStatus, CallEdgeIssue, CallEdgeIssueKind,
)
from scar.ir.program.functions import BodyLoweringProfile, FunctionSignature
from scar.ir.program.inventory import CallInventory, CoverageEntry, DefinitionInventory
from scar.ir.program.source_references import SourceDefinitionReference
from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.ids import OperationDefinitionID
from scar.trace.capture_coordinates import CaptureCoordinates


def _need(condition, detail):
    if not condition:
        raise ValueError("source/body access: " + detail)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _document(path, limit):
    path = Path(path)
    _need(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit,
          "input must be a bounded regular document")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    _need(len(raw) <= limit, "input document byte budget exceeded")
    value = strict_loads(raw.decode("utf-8"))
    _need(type(value) is dict, "input document must be an object")
    return value, {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


@dataclass(frozen=True)
class _SourceProjection:
    snapshot: SourceSnapshot
    definitions: tuple
    calls: tuple
    coverage: tuple


class _BodyMap(Mapping):
    """A view of original records; membership does not materialize a body."""
    def __init__(self, access, field):
        self.access, self.field = access, field

    def __iter__(self):
        return iter(self.access.selected)

    def __len__(self):
        return len(self.access.selected)

    def __contains__(self, key):
        return key in self.access.selected

    def __getitem__(self, key):
        if key not in self.access.selected:
            raise KeyError(key)
        bundle = self.access.bundle(key)
        if self.field == "core":
            return self.access.cores[key]
        return getattr(bundle, self.field)


class SourceBodyAccess:
    """Regular partitioned source accessor, never a ProgramInventory impersonator.

    Constructor reads compact references and signatures, not canonical graphs.
    ``bind_scan`` must check a fresh current raw scan before any provenance or
    canonical body can be used. Source invocation JSONL rows are not consumed:
    dynamic observations are independently rebuilt from raw frames, and their
    manifests/groups/counts are compared to the verified source report.
    """
    def __init__(self, composition, source_bindings, coordinates, code_witnesses,
                 *, max_document_bytes=32_000_000):
        _need(type(composition) is CompositionIndex and composition.partitioned,
              "new path requires a regular partitioned CompositionIndex")
        _need(type(coordinates) is CaptureCoordinates and type(code_witnesses) is CodeWitnessStore,
              "shared coordinates and CodeWitnessStore must be explicit")
        _need(type(max_document_bytes) is int and max_document_bytes > 0, "invalid input ceiling")
        self.composition, self.coordinates, self.code_witnesses = composition, coordinates, code_witnesses
        self.report_root = Path(source_bindings).resolve()
        report, self.report_receipt = _document(self.report_root / "report.json", max_document_bytes)
        self.report = report
        _need(report.get("schema") == "scar.source-invocations" and report.get("schema_version") in (2, 3),
              "source input must be a completed supported source binding report")
        self.formal = report["schema_version"] == 3
        _need(report.get("current_capture_raw_scan_verified") is True
              and report.get("old_capture_dynamic_facts_used_for_current_run") is False
              and report.get("transformation_authorized") is False
              and report.get("first_stage_complete") is False, "unsupported source report authority")
        _need(report["inventory"] == composition.document["inventory"]
              and report["composition_canonical_sha256"] == _hash(composition.document),
              "source report composition/inventory receipt differs")
        _need(decode(ExecutionRun, report["run"]) == coordinates.run, "source/current Run differs")
        _need(report["witness_mode"] in ("same_capture", "reused_code"), "unknown source witness mode")
        if self.formal:
            _need(report.get("source_definition_reference_format") == "scar.source-definition-reference.v1"
                  and report.get("source_inputs") == composition.source_inputs(),
                  "formal source inputs/qualified definition format differ")
            if report["witness_mode"] == "reused_code":
                _need(report.get("attachment_source_match_rule") == "EXACT_CAPTURED_CODE_STATIC_REUSE_V1"
                      and not code_witnesses.writable and not code_witnesses.compile_missing,
                      "current static reuse requires its explicit rule and a read-only CodeWitnessStore")
        _need(report.get("source_compilation_profile") == "RECORDED_FUTURE_FLAGS_V1",
              "source witness must retain the recorded compiler-context profile")
        declaration = report["bindings"]
        _need(declaration["path"] == "bindings.json", "binding document must be a local fixed filename")
        document, self.bindings_receipt = _document(self.report_root / "bindings.json", max_document_bytes)
        _need(self.bindings_receipt["sha256"] == declaration["raw_sha256"]
              and self.bindings_receipt["bytes"] == declaration["raw_bytes"], "binding SHA/size differs")
        _need(document.get("schema") == "scar.source-invocation-bindings"
              and document.get("schema_version") == report["schema_version"] and document.get("witness_mode") == report["witness_mode"]
              and document.get("transformation_authorized") is False, "binding document header differs")
        if self.formal:
            _need(document.get("source_inputs") == report["source_inputs"]
                  and document.get("source_definition_reference_format") == report["source_definition_reference_format"]
                  and document.get("attachment_source_match_rule") == report.get("attachment_source_match_rule"),
                  "formal binding receipts/reuse rule differ from source report")
        self.rows = document["bindings"]
        _need(type(self.rows) is list, "binding rows must be a list")
        _need(len(self.rows) == report["summary"]["entered_code_groups"]
              and dict(Counter(row["status"] for row in self.rows)) == report["summary"]["source_binding_statuses"],
              "source group/status denominators differ from the completed report")
        self.by_group = {}
        for index, row in enumerate(self.rows):
            key = row["process_id"], row["code"]
            _need(row["binding_index"] == index and key not in self.by_group,
                  "duplicate or misnumbered process/code group")
            self.by_group[key] = row
        header = composition.inventory_component("header")
        self.schema_version = header["schema_version"]
        self.profile = decode(BodyLoweringProfile, header["profile"])
        self.interfaces = SimpleNamespace(profile=self.profile)
        self.root = Path(composition.inventory_component("discovery")["project_root"])
        self.inventory_sha256 = report["inventory"]["raw_sha256"]
        _need(self.profile is BodyLoweringProfile.STRUCTURED_ENV and self.schema_version == 8,
              "partition path requires the original structured environment inventory")
        source_model = composition.inventory_component("call_sources")["model"]
        self.original_links = tuple(decode(CodeSourceLink, row) for row in source_model["code_links"])
        self.original_captures = tuple(decode(CodeCapture, row) for row in source_model["codes"])
        self.original_links_raw = source_model["code_links"]
        self.selected, self.collisions, candidates = {}, set(), defaultdict(set)
        self.paths = {}
        # Header scan only: do not parse/revalidate every canonical graph.
        for file_index, row in enumerate(composition.document["files"]):
            snapshot = decode(SourceSnapshot, row["snapshot"])
            _need(snapshot.path not in self.paths, "duplicate source snapshot path")
            self.paths[snapshot.path] = file_index
            for body_index, body in enumerate(row["bodies"]):
                definition = OperationDefinitionID(body["definition"].split(":", 1)[1])
                candidates[definition].add((snapshot.path, snapshot.fingerprint, file_index, body_index))
        self.collisions = {key for key, rows in candidates.items() if len(rows) != 1}
        for row in self.rows:
            if row["body"] is None:
                continue
            element = row["composition_element"] if self.formal else row["definition"]
            _need(element is not None, "canonical body has no original project composition view")
            definition = decode(OperationDefinitionID, element["identity"])
            if self.formal:
                reference = decode(SourceDefinitionReference, row["definition"])
                _need(reference.definition == definition and encode(reference.snapshot) == row["snapshot"],
                      "qualified definition differs from original project body/source")
            if definition in self.collisions:
                continue
            ref = row["body"]["reference"]
            file_index, body_index = ref["file_index"], ref["body_index"]
            _need(type(file_index) is int and type(body_index) is int
                  and 0 <= file_index < len(composition.document["files"])
                  and 0 <= body_index < len(composition.document["files"][file_index]["bodies"]),
                  "canonical body reference must carry exact file/body indices")
            attachment = composition.document["files"][file_index]["bodies"][body_index]
            _need(attachment["definition"] == definition.wire and attachment["root"] == ref["identity"]["wire"]
                  and attachment["program_canonical_sha256"] == row["body"]["program_canonical_sha256"],
                  "binding body definition/root/canonical SHA differs from composition")
            _need(row["snapshot"] == composition.document["files"][file_index]["snapshot"]
                  and (row["snapshot"]["path"], row["snapshot"]["fingerprint"], file_index, body_index)
                  in candidates[definition], "qualified body/source differs")
            for name, source_name in (("canonical_locator", "graph_locator"),
                    ("inventory_locator", "inventory_locator"), ("metadata_locator", "metadata_locator"),
                    ("namespace", "namespace")):
                _need(row["body"][name] == attachment[source_name], "binding CP locator/namespace differs")
            previous = self.selected.get(definition)
            _need(previous is None or previous == (file_index, body_index), "ambiguous bare body identity")
            self.selected[definition] = file_index, body_index
        self.signatures = {}
        for raw in composition.inventory_component("interfaces")["signatures"]:
            definition = decode(OperationDefinitionID, raw["definition"])
            if definition not in self.selected:
                continue
            fi, _ = self.selected[definition]
            snapshot = composition.document["files"][fi]["snapshot"]
            _need(raw["source"]["path"] == snapshot["path"]
                  and raw["source"]["fingerprint"] == snapshot["fingerprint"],
                  "formal signature is not source-qualified to its body")
            _need(definition not in self.signatures, "duplicate qualified body signature")
            self.signatures[definition] = decode(FunctionSignature, raw)
        _need(set(self.signatures) == set(self.selected), "selected body has no unique original signature")
        self.bundles, self.cores, self.projections, self.asts, self.views = {}, {}, {}, {}, {}
        self.bodies, self.ports = _BodyMap(self, "body"), _BodyMap(self, "interface")
        self.frames, self.structured, self.core = (_BodyMap(self, "frame"),
            _BodyMap(self, "structured"), _BodyMap(self, "core"))
        self.links, self.descriptors, self.witness_references, self.frontiers = {}, {}, {}, {}
        self.unavailable_generation = {}
        self.bound = False

    def bind_scan(self, scan, entries, exits):
        """Bind current independent frame scan, conserving all original groups."""
        from scar.analysis.source_invocations import _Members
        _need(not self.bound and str(self.root) == self.report["collection_metadata"][0]["project_root"],
              "source accessor already bound or project root differs")
        current = sorted((row.process_id, row.family, row.path, row.raw_sha256, row.raw_bytes, row.lines)
                         for row in scan.files)
        old = sorted((row["process_id"], row["family"], row["path"], row["raw_sha256"], row["raw_bytes"], row["lines"])
                     for row in self.report["trace_files"])
        _need(current == old, "current raw file SHA/size/path/count differs from source binding capture")
        _need(list(scan.metadata) == self.report["collection_metadata"], "current collector metadata differs")
        _need(all(meta["python"] == self.code_witnesses.document["runtime"]["python"] for meta in scan.metadata),
              "captured Python build differs from the CodeWitness build")
        groups = Counter((entry.invocation.process_id, entry.code) for entry in entries)
        _need(set(groups) == set(self.by_group)
              and all(groups[key] == row["entered_invocations"] for key, row in self.by_group.items()),
              "source process/code group denominator differs from current raw entries")
        statuses = Counter()
        for key, row in self.by_group.items():
            statuses[row["status"]] += groups[key]
        _need(dict(statuses) == self.report["summary"]["invocation_statuses"],
              "source invocation status denominators differ from independent entries")
        _need(len(entries) == self.report["summary"]["invocations"] == self.report["invocations"]["rows"]
              and len(exits) == self.report["summary"]["exits"]
              and len(scan.captures) == self.report["summary"]["code_captures"],
              "source invocation/exit/code denominator differs")
        members = _Members(self.coordinates, Path(scan.directory))
        members.bind(scan.files)
        self.members = members
        self.unbound_processes = {pid for pid, family in members.processes
                                  if members.processes[pid, family] is None}
        captures = {(row.process_id, row.code.key): row for row in scan.captures}
        for key, row in self.by_group.items():
            capture = captures.get(key)
            _need(capture is not None and encode(capture) == row["code_capture"],
                  "source binding captured descriptor/anchor differs from current raw code")
            previous = self.descriptors.get(capture.code.key)
            _need(previous is None or previous == capture.code, "one code fingerprint has different descriptors")
            self.descriptors[capture.code.key] = capture.code
            if self.formal and row.get("source_origin") == "SOURCE_ATTACHMENT":
                if self.report["witness_mode"] == "reused_code":
                    outcome = self.composition.validate_static_source_binding(row,
                        compilation_profile=self.report["source_compilation_profile"],
                        captured_python_build=next(meta["python"] for meta in scan.metadata
                                                  if meta["process_id"] == capture.process_id),
                        current_source_checks=self.report["current_source_checks"])
                    if outcome["source_usable"]:
                        self.links[capture.code.key] = outcome["code_source_link"]
                    else:
                        self.frontiers[capture.code.key] = "CURRENT_STATIC_SOURCE_GUARD_UNAVAILABLE"
                else:
                    witness = self.composition.attached_code_witness(*key)
                    _need(witness is not None and witness["record"]["captured_code"] == encode(capture.code)
                          and witness["record"]["descriptor_anchor"] == encode(capture.anchor)
                          and witness["record"]["entered_invocations"] == groups[key],
                          "same-capture external source witness differs from current group")
                    link = decode(CodeSourceLink, witness["record"]["code_source_link"])
                    reference = self.composition.attached_definition_reference(*key)
                    _need(link.status is CallLinkStatus.VERIFIED
                          and row["definition"] == (encode(reference) if reference is not None else None)
                          and row["snapshot"] == encode(link.snapshot) and row["source"] == encode(link.source)
                          and row["body"] is None and row["composition_element"] is None,
                          "same-capture external qualified source identity differs")
                    self.links[capture.code.key] = link
                continue
            if self.formal and self.report["witness_mode"] == "reused_code":
                witness = self.composition.static_code_witness(capture.code,
                    compilation_profile=self.report["source_compilation_profile"],
                    captured_python_build=next(meta["python"] for meta in scan.metadata
                                              if meta["process_id"] == capture.process_id))
                _need(row["definition"] is None or witness is not None,
                      "project current definition has no complete static compiler/build context witness")
                if witness is not None:
                    _need(row.get("source_context_guard") == witness["context_guard"],
                          "project source/compiler build guard differs")
                    if row["definition"] is not None:
                        reference = decode(SourceDefinitionReference, row["definition"])
                        guard = self.composition.current_source_guard(reference.snapshot,
                            row["current_source_check"], self.report["current_source_checks"])
                        _need(witness["context_guard"]["status"] == "MATCH" and guard["status"] == "FINGERPRINT_MATCH",
                              "project qualified source passed a failed current guard")
            locator = row["code_source_witness_locator"]
            descriptor_locator = row["descriptor_witness_locator"]
            if locator is None or descriptor_locator is None:
                continue
            match = re.fullmatch(r"#/value/model/code_links/([0-9]+)", locator["pointer"])
            other = re.fullmatch(r"#/value/model/codes/([0-9]+)/code", descriptor_locator["pointer"])
            _need(match is not None and other is not None, "source witness component pointer differs")
            i, j = int(match[1]), int(other[1])
            _need(0 <= i < len(self.original_links) and 0 <= j < len(self.original_captures),
                  "source witness component index is outside its original record")
            _need(locator == self.composition.inventory_component_locator("call_sources", f"/model/code_links/{i}")
                  and descriptor_locator == self.composition.inventory_component_locator("call_sources", f"/model/codes/{j}/code"),
                  "source witness locator differs from its original component")
            _need(self.original_captures[j].code == capture.code, "complete descriptor witness differs")
            link = self.original_links[i]
            _need(link.code == capture.code.key and row.get("witness_status") == link.status.value,
                  "code/source status differs from original exact witness")
            if link.status is CallLinkStatus.VERIFIED:
                if row["snapshot"] is None:
                    # Explicit reused_code guard rejection is a local frontier,
                    # never a claim that the old source witness was unverified.
                    self.frontiers[link.code] = "CURRENT_SOURCE_GUARD_UNAVAILABLE"
                    continue
                _need(encode(link.snapshot) == row["snapshot"], "verified source snapshot differs")
                if row["definition"] is not None:
                    element = row["composition_element"] if self.formal else row["definition"]
                    _need(encode(link.definition) == element["identity"]
                          and encode(link.source) == row["source"], "original definition/source witness differs")
                    if self.formal:
                        reference = decode(SourceDefinitionReference, row["definition"])
                        expected = self.composition.definition_reference(element["file_index"], link.definition)
                        _need(reference == expected, "formal project definition differs from original source graph")
            previous = self.links.get(link.code)
            _need(previous is None or previous == link, "ambiguous source link for a complete code descriptor")
            self.links[link.code] = link
        self.scan_counts = {"code_captures": len(scan.captures), "entered_code_groups": len(groups),
                            "invocations": len(entries), "exits": len(exits)}
        self.bound = True

    def code_link(self, captured):
        _need(self.bound, "a fresh raw scan must bind before source use")
        link = self.links.get(captured.key)
        if self.descriptors.get(captured.key) != captured or link is None:
            return CodeSourceLink(captured.key, CallLinkStatus.INCOMPLETE,
                issues=(CallEdgeIssue(CallEdgeIssueKind.SOURCE_BOUNDARY, "NO_MATCHING_CODE_SOURCE_WITNESS"),))
        return link

    def code_object(self, captured, link):
        if link.status is not CallLinkStatus.VERIFIED:
            return None
        eligible = link.definition in self.selected
        generation = len(self.code_witnesses.document["modules"])
        if self.unavailable_generation.get(captured.key) == generation:
            return None
        try:
            code, reference = self.code_witnesses.resolve(captured, link.snapshot, link.optimize_levels,
                                                        allow_compile=eligible)
        except CodeWitnessUnavailable as error:
            self.frontiers[captured.key] = str(error)
            self.unavailable_generation[captured.key] = len(self.code_witnesses.document["modules"])
            return None
        self.unavailable_generation.pop(captured.key, None)
        self.frontiers.pop(captured.key, None)
        self.witness_references[captured.key] = reference
        return code

    def projection(self, filename):
        _need(self.bound and filename in self.paths, "source is outside the bound composition")
        if filename not in self.projections:
            fi = self.paths[filename]
            raw = self.composition.inventory_file(fi)
            view = self.composition.source(fi)
            _need(raw["snapshot"] == encode(view.snapshot) and raw["context"] == encode(view.context),
                  "source shard snapshot/context differs from original archive")
            self.views[filename] = view
            self.projections[filename] = _SourceProjection(view.snapshot,
                decode(tuple[DefinitionInventory, ...], raw["definitions"]),
                decode(tuple[CallInventory, ...], raw["calls"]),
                decode(tuple[CoverageEntry, ...], raw["coverage"]))
        return self.projections[filename]

    def source_context(self, filename):
        projection = self.projection(filename)
        text = self.code_witnesses.text(projection.snapshot)
        if filename not in self.asts:
            self.asts[filename] = ast.parse(text, filename=filename)
        return projection, text, self.asts[filename]

    def bundle(self, definition):
        _need(self.bound, "canonical body access requires the current raw binding")
        if definition not in self.selected:
            raise KeyError(definition)
        if definition not in self.bundles:
            from scar.analysis.function_interfaces import validate_body_interface
            from scar.analysis.structured_lowering import require_valid_structured_body
            fi, bi = self.selected[definition]
            self.code_witnesses._notify("SOURCE_BODY_LOAD_BEGIN", file_index=fi, body_index=bi,
                                        definition=definition.wire)
            attachment = self.composition.document["files"][fi]["bodies"][bi]
            projection = self.projection(self.composition.document["files"][fi]["snapshot"]["path"])
            bundle = self.composition.inventory.typed_body(fi, bi)
            raw = self.composition.inventory_body(fi, bi)
            locators = self.composition.inventory_body_locators(fi, bi, raw["graph"])
            _need(all(attachment.get(name) == value for name, value in locators.items())
                  and _hash(raw["graph"]) == attachment["program_canonical_sha256"]
                  and bundle.namespace == attachment["namespace"], "original body graph/locator namespace differs")
            _need(bundle.body.definition == definition and bundle.body.graph is not None
                  and bundle.body.graph.root.wire == attachment["root"]
                  and bundle.body.metadata.source == projection.snapshot,
                  "typed body definition/root/snapshot differs")
            view = self.views[projection.snapshot.path]
            require_valid_structured_body(bundle.structured, bundle.body.graph, bundle.interface,
                bundle.body.metadata, semantic=view.semantic, control=view.control)
            validate_body_interface(bundle.body, bundle.interface, self.signatures[definition])
            self.bundles[definition] = bundle
            graph = bundle.body.graph
            self.cores[definition] = (bundle.body,
                {operation.id: operation for operation in graph.operations},
                {use.id: use for operation in graph.operations for use in operation.uses},
                {block.id: block for region in graph.regions for block in region.blocks})
            self.code_witnesses._notify("SOURCE_BODY_LOAD_END", file_index=fi, body_index=bi,
                definition=definition.wire, operations=len(graph.operations), values=len(graph.values))
        return self.bundles[definition]

    def receipt(self):
        namespaces = {}
        for definition, (fi, bi) in self.selected.items():
            body = self.composition.document["files"][fi]["bodies"][bi]
            namespaces[definition.wire] = {"file_index": fi, "body_index": bi,
                "namespace": body["namespace"], "inventory_locator": body["inventory_locator"],
                "graph_locator": body["graph_locator"], "metadata_locator": body["metadata_locator"]}
        return {"schema": "scar.call-source-body-access", "schema_version": 1,
            "inventory": self.composition.document["inventory"],
            "composition_canonical_sha256": _hash(self.composition.document),
            "source_report": self.report_receipt, "source_bindings": self.bindings_receipt,
            "source_witness_mode": self.report["witness_mode"], "run": encode(self.coordinates.run),
            "current_raw_scan_verified": self.bound, "raw_counts": getattr(self, "scan_counts", {}),
            "unbound_processes": sorted(getattr(self, "unbound_processes", ())),
            "source_invocation_rows_consumed": False,
            "namespaces": namespaces, "bare_definition_conflicts": sorted(value.wire for value in self.collisions),
            "code_witness_store": self.code_witnesses.receipt(),
            "code_witness_references": dict(self.witness_references),
            "code_witness_frontiers": dict(self.frontiers),
            "loaded_bodies": len(self.bundles), "parsed_source_files": len(self.asts),
            "source_producer_conditions": self.report["conditions"],
            "source_prepared": False, "canonical_producers_copied": False,
            "whole_program_established": False, "transformation_authorized": False}


__all__ = ["SourceBodyAccess"]
