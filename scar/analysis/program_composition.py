"""Reference-only composition of the existing source and canonical body graphs.

Containment, source control, conditional dispatch and canonical data/state are
different projections.  This index makes them queryable together without
inventing a root activation or a second producer/state graph.  A frontier is
retained wherever one of those projections is not connected.
"""
from __future__ import annotations

import argparse
from collections import Counter, OrderedDict
from dataclasses import dataclass
import gzip
import hashlib
from io import BytesIO
import json
from pathlib import Path
from typing import Any

from scar.analysis.source_layers import SourceLayerView, load_source_layers
from scar.ir.program.codec import loads as load_graph
from scar.ir.program.ids import OperationID, RegionID
from scar.ir.program.inventory import (
    CallInventory, CoverageEntry, DefinitionInventory, SourceContextDigest,
)
from scar.ir.program.model import ProgramGraph
from scar.ir.program.source import LoweringMetadata
from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.ids import (
    ControlFlowNodeID, ControlFlowSuiteID, ControlRegionID, Identifier,
    OperationDefinitionID, SourceAtomID,
)


_AUTHORITY = {
    "structural_projection_only": True,
    "target_executed": False,
    "whole_program_graph_established": False,
    "cross_function_dataflow_established": False,
    "fine_state_effects_established": False,
    "execution_model_established": False,
    "transformation_authorized": False,
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _read(path: Path, limit: int) -> tuple[dict, dict]:
    if type(limit) is not int or limit < 1:
        raise ValueError("byte budget must be a positive exact integer")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("input is missing, unsafe or exceeds its byte budget")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ValueError("input raw-byte budget exceeded")
    if path.suffix == ".gz":
        with gzip.GzipFile(fileobj=BytesIO(raw), mode="rb") as stream:
            payload = stream.read(limit + 1)
        if len(payload) > limit:
            raise ValueError("input decoded-byte budget exceeded")
    else:
        payload = raw
    document = strict_loads(payload.decode("utf-8"))
    if type(document) is not dict:
        raise ValueError("input must be a JSON object")
    return document, {
        "path": str(path.resolve()), "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw), "decoded_bytes": len(payload),
    }


def _wire(value: Identifier | None) -> str | None:
    return value.wire if value is not None else None


def _append(mapping: dict, key: Any, value: Any) -> None:
    rows = mapping.setdefault(key, [])
    if value not in rows:
        rows.append(value)


def _sort_mapping(mapping: dict) -> dict:
    return {key: sorted(rows) for key, rows in sorted(mapping.items())}


def _bound_file(raw: dict, view: SourceLayerView) -> tuple:
    snapshot = decode(SourceSnapshot, raw["snapshot"])
    context = decode(SourceContextDigest, raw["context"])
    if snapshot != view.snapshot or context != view.context:
        raise ValueError("inventory snapshot/context differs from the source archive")
    definitions = decode(tuple[DefinitionInventory, ...], raw["definitions"])
    coverage = decode(tuple[CoverageEntry, ...], raw["coverage"])
    calls = decode(tuple[CallInventory, ...], raw["calls"])
    for definition in definitions:
        if definition.id not in view.semantic.definitions:
            raise ValueError("inventory definition is absent from the semantic graph")
        atom = view.semantic.source_atoms.get(definition.source.atom_id)
        if atom is None or atom.reference != definition.source:
            raise ValueError("inventory definition source differs from the source archive")
    return definitions, coverage, calls


def _body_attachment(raw: dict, file_index: int, body_index: int,
                     view: SourceLayerView) -> dict:
    definition = decode(OperationDefinitionID, raw["definition"])
    if definition not in view.semantic.definitions:
        raise ValueError("body definition is absent from the semantic graph")
    pointer = f"#/files/{file_index}/bodies/{body_index}"
    status = raw.get("status")
    if status not in {"LOWERED_WITH_GAPS", "UNSUPPORTED", "NOT_ATTEMPTED"}:
        raise ValueError("unknown inventory body status")
    result = {
        "definition": definition.wire, "inventory_pointer": pointer,
        "status": status, "root": None, "program_schema_version": None,
        "program_canonical_sha256": None, "operation_links": {},
        "source_atom_links": {}, "regions": [], "counts": {},
        "frontiers": [],
    }
    metadata = (decode(LoweringMetadata, raw["metadata"])
                if raw.get("metadata") is not None else None)
    if metadata is not None and metadata.source != view.snapshot:
        raise ValueError("body metadata belongs to a different source snapshot")
    if raw.get("graph") is None:
        if status == "LOWERED_WITH_GAPS":
            raise ValueError("lowered body has no canonical graph")
        result["frontiers"].append({
            "kind": "BODY_" + status, "inventory_pointer": pointer,
            "detail": raw.get("reason", "body was not recovered"),
        })
        return result
    if status != "LOWERED_WITH_GAPS" or metadata is None:
        raise ValueError("canonical body graph lacks its lowered status/metadata")
    graph_document = raw["graph"]
    graph_payload = _canonical(graph_document)
    graph = load_graph(graph_payload.decode("utf-8"))
    operations = {operation.id for operation in graph.operations}
    values = {value.id for value in graph.values}
    uses = {(operation.id, use.id) for operation in graph.operations for use in operation.uses}
    for link in metadata.operation_links:
        if link.operation not in operations:
            raise ValueError("body operation source link references a missing operation")
        atom = view.semantic.source_atoms.get(link.source.atom_id)
        if atom is None or atom.reference != link.source:
            raise ValueError("body operation source link differs from source archive")
        if link.semantic_operation is not None:
            if link.semantic_operation not in view.semantic.definitions:
                raise ValueError("body semantic operation link is missing")
            _append(result["operation_links"], link.semantic_operation.wire,
                    link.operation.wire)
        _append(result["source_atom_links"], link.source.atom_id.wire,
                link.operation.wire)
    for link in metadata.value_links:
        if link.value not in values:
            raise ValueError("body value source link references a missing value")
        atom = view.semantic.source_atoms.get(link.source.atom_id)
        if atom is None or atom.reference != link.source:
            raise ValueError("body value source link differs from source archive")
    for link in metadata.use_links:
        if (link.operation, link.use) not in uses:
            raise ValueError("body use source link references a missing operation/use")
        atom = view.semantic.source_atoms.get(link.source.atom_id)
        if atom is None or atom.reference != link.source:
            raise ValueError("body use source link differs from source archive")
    result.update({
        "root": graph.root.wire,
        "program_schema_version": graph_document["schema_version"],
        "program_canonical_sha256": hashlib.sha256(graph_payload).hexdigest(),
        "regions": [region.id.wire for region in graph.regions],
        "counts": {"regions": len(graph.regions), "operations": len(graph.operations),
                   "values": len(graph.values), "locations": len(graph.locations),
                   "ordered_uses": sum(len(operation.uses) for operation in graph.operations)},
        "operation_links": _sort_mapping(result["operation_links"]),
        "source_atom_links": _sort_mapping(result["source_atom_links"]),
    })
    for index, gap in enumerate(metadata.gaps):
        result["frontiers"].append({
            "kind": "BODY_" + gap.kind.value,
            "inventory_pointer": pointer + f"/metadata/gaps/{index}",
            "detail": gap.detail,
        })
    if any(not operation.effects_complete for operation in graph.operations):
        result["frontiers"].append({
            "kind": "INCOMPLETE_OPERATION_EFFECTS", "inventory_pointer": pointer + "/graph",
            "detail": "operation effects_complete flags remain authoritative in the original graph",
        })
    return result


def _compose_file(raw: dict, index: int, view: SourceLayerView,
                  definition_files: dict[str, int]) -> dict:
    definitions, coverage, calls = _bound_file(raw, view)
    semantic, semantics, control = view.semantic, view.semantics, view.control
    children, controlled, control_children, atom_ops = {}, {}, {}, {}
    for operation in semantic.definitions.values():
        if operation.parent_id is not None:
            _append(children, operation.parent_id.wire, operation.id.wire)
        if operation.control_region is not None:
            _append(controlled, operation.control_region.wire, operation.id.wire)
        for atom in operation.source_atoms:
            _append(atom_ops, atom.wire, operation.id.wire)
    owned_controls = {}
    for region in semantic.controls.values():
        if region.parent_id is not None:
            _append(control_children, region.parent_id.wire, region.id.wire)
        if region.owner is not None:
            _append(owned_controls, region.owner.wire, region.id.wire)
    suites_by_scope, suites_by_owner, suite_children, nodes_by_suite, cfg_by_op = {}, {}, {}, {}, {}
    for suite in control.suites.values():
        _append(suites_by_scope, suite.scope.wire, suite.id.wire)
        if suite.owner is not None:
            _append(suites_by_owner, suite.owner.wire, suite.id.wire)
        if suite.parent is not None:
            _append(suite_children, suite.parent.wire, suite.id.wire)
    for node in control.nodes.values():
        _append(nodes_by_suite, node.suite.wire, node.id.wire)
        for operation in node.operations:
            _append(cfg_by_op, operation.wire, node.id.wire)
    atom_owners, frontier = {}, []
    for coverage_index, item in enumerate(coverage):
        atom = semantic.source_atoms.get(item.source.atom_id)
        if atom is None or atom.reference != item.source or item.owner not in semantic.definitions:
            raise ValueError("coverage atom/owner differs from the source graph")
        _append(atom_owners, item.source.atom_id.wire,
                (item.owner.wire, item.phase.value, item.status.value, coverage_index))
    for atom in semantic.source_atoms:
        if atom.wire not in atom_owners and atom.wire not in atom_ops:
            frontier.append({"kind": "SOURCE_ATOM_WITHOUT_OWNER", "subject": atom.wire})
    bodies = [_body_attachment(body, index, body_index, view)
              for body_index, body in enumerate(raw["bodies"])]
    body_by_definition = {body["definition"]: body_index for body_index, body in enumerate(bodies)}
    if len(body_by_definition) != len(bodies):
        raise ValueError("duplicate inventory body definition")
    for definition in definitions:
        if definition.id.wire not in body_by_definition:
            frontier.append({"kind": "DEFINITION_BODY_NOT_RECOVERED",
                             "subject": definition.id.wire,
                             "definition_kind": definition.kind.value})
    module_roots = []
    for module in semantic.modules.values():
        if module.initializer is not None:
            module_roots.append(module.initializer.wire)
            if module.initializer.wire not in body_by_definition:
                frontier.append({"kind": "MODULE_INITIALIZER_BODY_NOT_RECOVERED",
                                 "subject": module.initializer.wire})
    call_links = []
    for call_index, call in enumerate(calls):
        if call.operation not in semantic.definitions or call.execution_owner not in semantic.definitions:
            raise ValueError("call source/owner is absent from the semantic graph")
        targets = []
        for candidate in call.candidates:
            destination = definition_files.get(candidate.wire)
            if destination is None:
                raise ValueError("conditional call target has no inventory definition")
            targets.append({"file_index": destination, "definition": candidate.wire})
        call_links.append({
            "operation": call.operation.wire, "owner": call.execution_owner.wire,
            "inventory_pointer": f"#/files/{index}/calls/{call_index}",
            "target_definitions": targets,
            "status": "CONDITIONAL" if targets else "UNRESOLVED",
            "actual_formal_return_connected": False,
        })
    if calls:
        frontier.append({"kind": "CROSS_FUNCTION_BINDING_NOT_ESTABLISHED",
                         "subjects": len(calls),
                         "detail": "conditional source targets are not actual/formal/return or environment bindings"})
    frontier.extend({"kind": "SOURCE_SEMANTICS_GAP", "source_index": i}
                    for i in range(len(semantics.gaps)))
    frontier.extend({"kind": "SOURCE_CONTROL_GAP", "source_index": i}
                    for i in range(len(control.gaps)))
    return {
        "file_index": index, "snapshot": encode(view.snapshot), "context": encode(view.context),
        "source_archive_canonical_sha256": view.metadata["archive_sha256"],
        "status": "INDEXED_WITH_FRONTIERS", "module_roots": sorted(module_roots),
        "operation_children": _sort_mapping(children),
        "owned_controls": _sort_mapping(owned_controls),
        "control_children": _sort_mapping(control_children),
        "controlled_operations": _sort_mapping(controlled),
        "atom_operations": _sort_mapping(atom_ops),
        "atom_owners": {key: [list(row) for row in rows] for key, rows in sorted(atom_owners.items())},
        "suites_by_scope": _sort_mapping(suites_by_scope),
        "suites_by_owner": _sort_mapping(suites_by_owner),
        "suite_children": _sort_mapping(suite_children),
        "nodes_by_suite": _sort_mapping(nodes_by_suite),
        "cfg_by_operation": _sort_mapping(cfg_by_op),
        "bodies": bodies, "calls": call_links, "frontiers": frontier,
        "coverage_statuses": dict(sorted(Counter(item.status.value for item in coverage).items())),
        "counts": {"source_atoms": len(semantic.source_atoms),
                   "coverage_entries": len(coverage), "definitions": len(definitions),
                   "semantic_operations": len(semantic.definitions),
                   "control_regions": len(semantic.controls), "cfg_suites": len(control.suites),
                   "cfg_nodes": len(control.nodes), "cfg_edges": len(control.edges),
                   "bodies": len(bodies), "canonical_bodies": sum(body["root"] is not None for body in bodies),
                   "calls": len(calls), "conditional_call_targets": sum(len(call["target_definitions"]) for call in call_links)},
    }


def compose_program(inventory_path: str | Path, source_layers_dir: str | Path,
                    out_dir: str | Path, *, max_input_bytes: int = 512_000_000,
                    max_files: int = 256, max_record_bytes: int = 128_000_000,
                    max_output_bytes: int = 256_000_000) -> dict:
    """Automatically index every supplied inventory file; never execute it.

    Existing source-layer validation and canonical ProgramGraph validation run
    once per file/body.  Missing archives remain visible; contradictory bound
    graphs raise rather than silently turning into a successful coverage row.
    """
    if type(max_files) is not int or max_files < 1:
        raise ValueError("max_files must be a positive exact integer")
    inventory, artifact = _read(Path(inventory_path), max_input_bytes)
    if inventory.get("schema") != "scar.program-inventory" or type(inventory.get("files")) is not list:
        raise ValueError("unsupported program inventory")
    if len(inventory["files"]) > max_files:
        raise ValueError("inventory file budget exceeded")
    layers = Path(source_layers_dir).resolve()
    manifest, source_artifact = _read(layers / "index.json", 32_000_000)
    if manifest.get("schema") != "scar.source-layers":
        raise ValueError("unsupported source-layer manifest")
    source_rows = {row["source_path"]: row for row in manifest["files"]}
    if len(source_rows) != len(manifest["files"]):
        raise ValueError("duplicate source-layer file")
    definition_files: dict[str, int] = {}
    seen_files = set()
    for index, raw in enumerate(inventory["files"]):
        path = decode(SourceSnapshot, raw["snapshot"]).path
        if path in seen_files:
            raise ValueError("duplicate inventory source path")
        seen_files.add(path)
        for definition in decode(tuple[DefinitionInventory, ...], raw["definitions"]):
            if definition.id.wire in definition_files:
                raise ValueError("duplicate source definition identity")
            definition_files[definition.id.wire] = index
    rows = []
    for index, raw in enumerate(inventory["files"]):
        path = raw["snapshot"]["path"]
        source_row = source_rows.get(path)
        if source_row is None or source_row.get("status") != "STORED":
            rows.append({"file_index": index, "snapshot": raw["snapshot"], "status": "GAP",
                         "frontiers": [{"kind": "SOURCE_ARCHIVE_UNAVAILABLE", "detail": source_row.get("gap") if source_row else None}],
                         "counts": {}, "bodies": [], "calls": []})
            continue
        view = load_source_layers(layers, path, max_record_bytes=max_record_bytes)
        rows.append(_compose_file(raw, index, view, definition_files))
    counts, frontier_counts = Counter(), Counter()
    for row in rows:
        counts.update(row["counts"])
        frontier_counts.update(item["kind"] for item in row["frontiers"])
        for body in row["bodies"]:
            frontier_counts.update(item["kind"] for item in body["frontiers"])
    document = {
        "schema": "scar.program-composition", "schema_version": 1,
        "inventory": artifact, "source_layers": {**source_artifact, "directory": str(layers)},
        "files_total": len(rows), "files_indexed": sum(row["status"] != "GAP" for row in rows),
        "summary": {"inventory_denominators": {
                        "files": len(inventory["files"]),
                        "definitions": sum(len(file["definitions"]) for file in inventory["files"]),
                        "coverage_entries": sum(len(file["coverage"]) for file in inventory["files"]),
                        "calls": sum(len(file["calls"]) for file in inventory["files"]),
                        "bodies": sum(len(file["bodies"]) for file in inventory["files"])},
                    "counts": dict(sorted(counts.items())),
                    "frontiers": dict(sorted(frontier_counts.items())), "first_stage_complete": False},
        "files": rows, **_AUTHORITY,
    }
    payload = _canonical(document)
    if type(max_output_bytes) is not int or max_output_bytes < 1 or len(payload) > max_output_bytes:
        raise ValueError("composition output budget exceeded")
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=False)
    with (output / "index.json.gz").open("xb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as zipped:
            zipped.write(payload)
    summary = {key: document[key] for key in ("schema", "schema_version", "files_total", "files_indexed", "summary")}
    (output / "summary.json").write_bytes(_canonical(summary))
    return summary


@dataclass(frozen=True, slots=True)
class ElementReference:
    """An existing identity qualified by file and original body document."""

    file_index: int
    identity: Identifier
    body_index: int | None = None

    def __post_init__(self):
        if type(self.file_index) is not int or self.file_index < 0 or not isinstance(self.identity, Identifier):
            raise TypeError("element reference requires a nonnegative file index and existing typed ID")
        if self.body_index is not None and (type(self.body_index) is not int or self.body_index < 0):
            raise TypeError("body index must be a nonnegative exact integer")
        if isinstance(self.identity, (OperationID, RegionID)) != (self.body_index is not None):
            raise ValueError("canonical body identities require body qualification")


class CompositionIndex:
    """Bounded lazy queries over the original graphs, with no copied producers."""

    def __init__(self, index_path: str | Path, *, max_input_bytes: int = 512_000_000,
                 max_record_bytes: int = 128_000_000, cached_files: int = 2):
        if type(cached_files) is not int or cached_files < 1:
            raise ValueError("cached_files must be positive")
        self.document, _ = _read(Path(index_path), max_input_bytes)
        if self.document.get("schema") != "scar.program-composition" or self.document.get("schema_version") != 1:
            raise ValueError("unsupported composition index")
        for key, value in _AUTHORITY.items():
            if self.document.get(key) is not value:
                raise ValueError("composition index overstates its authority")
        self.inventory, receipt = _read(Path(self.document["inventory"]["path"]), max_input_bytes)
        if receipt != self.document["inventory"]:
            raise ValueError("inventory differs from bound composition input")
        self.layers = Path(self.document["source_layers"]["directory"])
        _, layer_receipt = _read(self.layers / "index.json", 32_000_000)
        if {**layer_receipt, "directory": str(self.layers)} != self.document["source_layers"]:
            raise ValueError("source-layer manifest differs from bound composition input")
        self.max_record_bytes, self.cached_files = max_record_bytes, cached_files
        self._views: OrderedDict[int, SourceLayerView] = OrderedDict()
        self._bodies: OrderedDict[tuple[int, int], tuple[ProgramGraph, LoweringMetadata]] = OrderedDict()

    def _row(self, index: int) -> dict:
        if type(index) is not int or not 0 <= index < len(self.document["files"]):
            raise ValueError("file index is outside the composition")
        row = self.document["files"][index]
        if row["file_index"] != index or row["status"] == "GAP":
            raise ValueError("file composition is unavailable")
        return row

    def source(self, file_index: int) -> SourceLayerView:
        row = self._row(file_index)
        if file_index not in self._views:
            view = load_source_layers(self.layers, row["snapshot"]["path"], max_record_bytes=self.max_record_bytes)
            if (view.metadata["archive_sha256"] != row["source_archive_canonical_sha256"]
                    or encode(view.snapshot) != row["snapshot"] or encode(view.context) != row["context"]):
                raise ValueError("source archive differs from composition reference")
            self._views[file_index] = view
            if len(self._views) > self.cached_files:
                self._views.popitem(last=False)
        self._views.move_to_end(file_index)
        return self._views[file_index]

    def typed_body(self, file_index: int, body_index: int) -> tuple[ProgramGraph, LoweringMetadata]:
        row = self._row(file_index)
        if type(body_index) is not int or not 0 <= body_index < len(row["bodies"]):
            raise ValueError("body index is outside the file composition")
        attachment = row["bodies"][body_index]
        if attachment["root"] is None:
            raise ValueError("body has an explicit recovery frontier")
        key = file_index, body_index
        if key not in self._bodies:
            raw = self.inventory["files"][file_index]["bodies"][body_index]
            payload = _canonical(raw["graph"])
            if hashlib.sha256(payload).hexdigest() != attachment["program_canonical_sha256"]:
                raise ValueError("body graph differs from composition reference")
            self._bodies[key] = (load_graph(payload.decode("utf-8")), decode(LoweringMetadata, raw["metadata"]))
            if len(self._bodies) > self.cached_files * 2:
                self._bodies.popitem(last=False)
        self._bodies.move_to_end(key)
        return self._bodies[key]

    def expand(self, reference: ElementReference) -> dict:
        """Return original containment/control/body references, never call them def-use."""
        row, identity = self._row(reference.file_index), reference.identity
        wire = identity.wire
        result = {"subject": reference, "children": [], "typed_regions": [],
                  "control_regions": [], "control_suites": [], "source_atoms": [],
                  "corresponding_operations": [], "frontiers": []}
        if reference.body_index is not None:
            graph, _ = self.typed_body(reference.file_index, reference.body_index)
            if isinstance(identity, RegionID):
                region = next((item for item in graph.regions if item.id == identity), None)
                if region is None:
                    raise ValueError("unknown canonical region")
                result["record"] = region
                for block in region.blocks:
                    result["children"].extend(ElementReference(reference.file_index, operation, reference.body_index)
                                              for operation in block.operations)
                result["children"].extend(ElementReference(reference.file_index, item.id, reference.body_index)
                                          for item in graph.regions if item.parent == identity)
            elif isinstance(identity, OperationID):
                operation = next((item for item in graph.operations if item.id == identity), None)
                if operation is None:
                    raise ValueError("unknown canonical operation")
                result["record"] = operation
                if operation.callee is not None:
                    result["typed_regions"].append(ElementReference(reference.file_index, operation.callee, reference.body_index))
            return result
        view = self.source(reference.file_index)
        groups = []
        if isinstance(identity, OperationDefinitionID):
            if identity not in view.semantic.definitions:
                raise ValueError("unknown semantic operation")
            result["record"] = view.semantic.definitions[identity]
            groups = [(row["operation_children"].get(wire, ()), OperationDefinitionID, "children"),
                      (row["owned_controls"].get(wire, ()), ControlRegionID, "control_regions"),
                      (row["suites_by_owner"].get(wire, ()), ControlFlowSuiteID, "control_suites")]
            result["source_atoms"].extend(ElementReference(reference.file_index,
                SourceAtomID(atom.split(":", 1)[1])) for atom, owners in row["atom_owners"].items()
                if any(owner[0] == wire for owner in owners))
            for body_index, body in enumerate(row["bodies"]):
                if body["definition"] == wire:
                    result["frontiers"].extend(body["frontiers"])
                    if body["root"] is not None:
                        result["typed_regions"].append(ElementReference(reference.file_index,
                            RegionID(body["root"].split(":", 1)[1]), body_index))
            # Root CFG suites belong to a callable activation scope, not its definition-time control.
            for suite_id in row["suites_by_scope"].get(wire, ()):
                suite = next(suite for suite in view.control.suites.values() if suite.id.wire == suite_id)
                if suite.parent is None:
                    groups.append(([suite_id], ControlFlowSuiteID, "control_suites"))
        elif isinstance(identity, ControlRegionID):
            if identity not in view.semantic.controls:
                raise ValueError("unknown source control region")
            result["record"] = view.semantic.controls[identity]
            groups = [(row["control_children"].get(wire, ()), ControlRegionID, "children"),
                      (row["controlled_operations"].get(wire, ()), OperationDefinitionID, "children")]
        elif isinstance(identity, ControlFlowSuiteID):
            if identity not in view.control.suites:
                raise ValueError("unknown source CFG suite")
            result["record"] = view.control.suites[identity]
            groups = [(row["suite_children"].get(wire, ()), ControlFlowSuiteID, "children"),
                      (row["nodes_by_suite"].get(wire, ()), ControlFlowNodeID, "children")]
        elif isinstance(identity, ControlFlowNodeID):
            if identity not in view.control.nodes:
                raise ValueError("unknown source CFG node")
            result["record"] = view.control.nodes[identity]
            result["corresponding_operations"].extend(ElementReference(reference.file_index, operation)
                                                      for operation in result["record"].operations)
        elif isinstance(identity, SourceAtomID):
            if identity not in view.semantic.source_atoms:
                raise ValueError("unknown source atom")
            result["record"] = view.semantic.source_atoms[identity]
            groups = [(row["atom_operations"].get(wire, ()), OperationDefinitionID, "corresponding_operations")]
            result["execution_owners"] = row["atom_owners"].get(wire, ())
            coverage = self.inventory["files"][reference.file_index]["coverage"]
            result["coverage_records"] = tuple(decode(CoverageEntry, coverage[owner[3]])
                                                for owner in result["execution_owners"])
            result["frontiers"].extend({"kind": "COVERAGE_" + item.status.value,
                "inventory_pointer": f"#/files/{reference.file_index}/coverage/{owner[3]}",
                "detail": item.reason} for owner, item in zip(result["execution_owners"], result["coverage_records"])
                if item.status.value != "CONNECTED")
        else:
            raise TypeError("identity has no structural expansion")
        for members, kind, projection in groups:
            result[projection].extend(ElementReference(reference.file_index, kind(member.split(":", 1)[1]))
                                     for member in members)
        result["frontiers"].extend(item for item in row["frontiers"] if item.get("subject") == wire)
        return result

    def dependencies(self, reference: ElementReference) -> dict:
        """Query original ordered operands, state, control and conditional calls.

        Returned records are the original graph records.  Source operands are
        source abstraction, not runtime values.  Conditional targets never
        turn into canonical CALLs or actual/formal equalities here.
        """
        row, identity = self._row(reference.file_index), reference.identity
        if reference.body_index is not None:
            graph, metadata = self.typed_body(reference.file_index, reference.body_index)
            if not isinstance(identity, OperationID):
                raise TypeError("canonical dependency query requires OperationID")
            operation = next((item for item in graph.operations if item.id == identity), None)
            if operation is None:
                raise ValueError("unknown canonical operation")
            values = {value.id: value for value in graph.values}
            return {"ordered_uses": operation.uses,
                    "input_values": tuple(values[use.value] for use in operation.uses),
                    "result_values": tuple(values[value] for value in operation.results),
                    "state_accesses": operation.accesses,
                    "effects_complete": operation.effects_complete,
                    "terminator": operation.terminator,
                    "conditional_calls": tuple(item for item in metadata.call_targets if item.operation == identity),
                    "frontiers": tuple(row["bodies"][reference.body_index]["frontiers"])}
        if not isinstance(identity, OperationDefinitionID):
            raise TypeError("source dependency query requires OperationDefinitionID")
        view = self.source(reference.file_index)
        operation = view.semantics.operations.get(identity)
        calls = decode(tuple[CallInventory, ...], self.inventory["files"][reference.file_index]["calls"])
        nodes = tuple(node for node in view.control.nodes.values() if identity in node.operations)
        node_ids = {node.id for node in nodes}
        canonical = []
        for body_index, body in enumerate(row["bodies"]):
            canonical.extend(ElementReference(reference.file_index,
                             OperationID(wire.split(":", 1)[1]), body_index)
                             for wire in body["operation_links"].get(identity.wire, ()))
        target_refs = []
        for call in row["calls"]:
            if call["operation"] == identity.wire:
                for target in call["target_definitions"]:
                    target_row = self.document["files"][target["file_index"]]
                    target_refs.append({"definition": ElementReference(target["file_index"],
                        OperationDefinitionID(target["definition"].split(":", 1)[1])),
                        "canonical_regions": tuple(ElementReference(target["file_index"],
                            RegionID(body["root"].split(":", 1)[1]), body_index)
                            for body_index, body in enumerate(target_row["bodies"])
                            if body["definition"] == target["definition"] and body["root"] is not None),
                        "status": call["status"], "actual_formal_return_connected": False})
        definition = view.semantic.definitions.get(identity)
        if definition is None:
            raise ValueError("unknown semantic operation")
        return {"source_semantics": operation,
                "ordered_operands": operation.operands if operation is not None else (),
                "state_effects_established": False,
                "control_nodes": nodes,
                "control_edges": tuple(edge for edge in view.control.edges.values()
                                       if edge.source in node_ids or edge.target in node_ids),
                "conditional_calls": tuple(call for call in calls if call.operation == identity),
                "conditional_target_regions": tuple(target_refs),
                "canonical_operations": tuple(canonical),
                "source_effect_summary": view.semantic.effects.get(definition.effect_summary),
                "semantic_gaps": tuple(gap for gap in view.semantics.gaps if gap.operation == identity),
                "control_gaps": tuple(gap for gap in view.control.gaps if gap.operation == identity)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--source-layers", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(json.dumps(compose_program(args.inventory, args.source_layers, args.out),
                     sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()


__all__ = ["CompositionIndex", "ElementReference", "compose_program"]
