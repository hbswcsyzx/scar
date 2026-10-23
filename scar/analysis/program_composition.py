"""Reference-only composition of the existing source and canonical body graphs.

Containment, source control, conditional dispatch and canonical data/state are
different projections.  This index makes them queryable together without
inventing a root activation or a second producer/state graph.  A frontier is
retained wherever one of those projections is not connected.
"""
from __future__ import annotations

import argparse
from collections import Counter, OrderedDict
from copy import deepcopy
from dataclasses import dataclass, replace
import gzip
import hashlib
from io import BytesIO
import json
from pathlib import Path
from typing import Any

from scar.analysis.source_layers import SourceLayerView, load_source_layers
from scar.analysis.source_attachments import SourceAttachments, SourceAttachmentBudget
from scar.analysis.inventory_partitions import InventoryPartitions
from scar.ir.program.codec import loads as load_graph
from scar.ir.program.ids import OperationID, RegionID
from scar.ir.program.inventory import (
    CallInventory, CoverageEntry, DefinitionInventory, SourceContextDigest,
)
from scar.ir.program.model import ProgramGraph
from scar.ir.program.source import LoweringMetadata
from scar.ir.program.source_references import SourceDefinitionReference
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


def _at(locator: dict, suffix: str) -> dict:
    return {**locator, "pointer": locator["pointer"] + suffix}


class _InventorySource:
    """Storage adapter only; canonical source/body records remain untouched."""

    def __init__(self, path, *, max_input_bytes, max_record_bytes):
        path = Path(path)
        if path.is_dir():
            path = path / "manifest.json"
        document, self.receipt = _read(path, max_input_bytes)
        self.partitions = None
        self.document = None
        self._files = OrderedDict()
        if document.get("schema") == "scar.partitioned-program-inventory":
            self.partitions = InventoryPartitions(path, max_shard_bytes=max_record_bytes)
            self.format = "PARTITIONED"
            self.file_count = len(self.partitions.manifest["files"])
        elif document.get("schema") == "scar.program-inventory" and type(document.get("files")) is list:
            self.document, self.format = document, "MONOLITHIC"
            self.file_count = len(document["files"])
        else:
            raise ValueError("unsupported program inventory storage schema")

    def file(self, index):
        if self.partitions is None:
            return self.document["files"][index]
        if index not in self._files:
            self._files[index] = self.partitions.file(index)
            while len(self._files) > 2:
                self._files.popitem(last=False)
        self._files.move_to_end(index)
        return self._files[index]

    def body(self, file_index, body_index):
        return (self.partitions.body_record(file_index, body_index) if self.partitions is not None
                else self.document["files"][file_index]["bodies"][body_index])

    def component(self, name):
        return self.partitions.component(name) if self.partitions is not None else self.document.get(name)

    def _artifact(self, ref):
        uri = ref["uri"] if ref["external"] else str(self.partitions.root / ref["uri"])
        return {"uri": uri, **{name: ref[name] for name in
            ("physical_sha256", "physical_bytes", "decoded_sha256", "decoded_bytes", "representation")}}

    def file_locator(self, index, pointer=""):
        if self.partitions is None:
            return {"artifact": self.receipt, "pointer": f"#/files/{index}" + pointer}
        return {"artifact": self._artifact(self.partitions.manifest["files"][index]),
                "pointer": "#/file" + pointer}

    def component_locator(self, name, pointer=""):
        if self.partitions is None:
            return {"artifact": self.receipt, "pointer": "#/" + name + pointer}
        return {"artifact": self._artifact(self.partitions.manifest["components"][name]),
                "pointer": "#/value" + pointer}

    def body_locators(self, file_index, body_index, graph_document=None):
        header = self.file_locator(file_index, f"/bodies/{body_index}")
        if self.partitions is None:
            return {"inventory_locator": header, "graph_locator": _at(header, "/graph"),
                    "metadata_locator": _at(header, "/metadata"), "namespace": None}
        row = self.file(file_index)["bodies"][body_index]
        ref = row["checkpoint"]
        if ref is not None and ref["representation"] == "scar.body-construction-checkpoint/2":
            actual = self.partitions.body_field_locators(file_index, body_index)
            return {"inventory_locator": header, "graph_locator": actual["graph_locator"],
                "metadata_locator": actual["metadata_locator"],
                "namespace": actual["graph_locator"]["namespace"],
                "language_locator": actual["language_locator"],
                "source_program_locator": actual["source_program_locator"]}
        graph_locator = metadata_locator = namespace = None
        if ref is not None:
            artifact = self._artifact(ref)
            metadata_locator = {"artifact": artifact, "pointer": "#/metadata"}
            if graph_document is not None:
                namespace = {"artifact": {"uri": ref["uri"], "decoded_sha256": ref["decoded_sha256"]},
                    "representation": "scar.program-graph/" + str(graph_document["schema_version"]),
                    "record_pointer": "#/graph", "body": ref["body_identity"]}
                graph_locator = {"artifact": artifact, "pointer": "#/graph", "namespace": namespace}
        return {"inventory_locator": header, "graph_locator": graph_locator,
                "metadata_locator": metadata_locator, "namespace": namespace}


def _definition_key(snapshot, identity):
    return snapshot["path"], snapshot["fingerprint"], identity.wire


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
                     view: SourceLayerView, *, locators=None) -> dict:
    definition = decode(OperationDefinitionID, raw["definition"])
    if definition not in view.semantic.definitions:
        raise ValueError("body definition is absent from the semantic graph")
    pointer = f"#/files/{file_index}/bodies/{body_index}" if locators is None else None
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
    if locators is not None:
        result.update(locators)
    metadata = (decode(LoweringMetadata, raw["metadata"])
                if raw.get("metadata") is not None else None)
    if metadata is not None and metadata.source != view.snapshot:
        raise ValueError("body metadata belongs to a different source snapshot")
    if raw.get("graph") is None:
        if status == "LOWERED_WITH_GAPS":
            raise ValueError("lowered body has no canonical graph")
        frontier = {
            "kind": "BODY_" + status, "inventory_pointer": pointer,
            "detail": raw.get("reason", "body was not recovered"),
        }
        if locators is not None:
            frontier["inventory_locator"] = locators["inventory_locator"]
        result["frontiers"].append(frontier)
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
        frontier = {
            "kind": "BODY_" + gap.kind.value,
            "inventory_pointer": pointer + f"/metadata/gaps/{index}" if pointer is not None else None,
            "detail": gap.detail,
        }
        if locators is not None:
            frontier["inventory_locator"] = _at(locators["metadata_locator"], f"/gaps/{index}")
        result["frontiers"].append(frontier)
    if any(not operation.effects_complete for operation in graph.operations):
        frontier = {
            "kind": "INCOMPLETE_OPERATION_EFFECTS", "inventory_pointer": pointer + "/graph" if pointer is not None else None,
            "detail": "operation effects_complete flags remain authoritative in the original graph",
        }
        if locators is not None:
            frontier["inventory_locator"] = locators["graph_locator"]
        result["frontiers"].append(frontier)
    return result


def _compose_file(raw: dict, index: int, view: SourceLayerView,
                  definition_files: dict, *, inventory_source=None) -> dict:
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
    bodies = []
    for body_index, header in enumerate(raw["bodies"]):
        body = inventory_source.body(index, body_index) if inventory_source is not None else header
        locators = (inventory_source.body_locators(index, body_index, body.get("graph"))
                    if inventory_source is not None and inventory_source.partitions is not None else None)
        bodies.append(_body_attachment(body, index, body_index, view, locators=locators))
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
            if inventory_source is not None and inventory_source.partitions is not None:
                destinations = {definition_files.get((w.target_source.path, w.target_source.fingerprint, candidate.wire))
                    for w in call.candidate_witnesses if w.definition == candidate}
                if None in destinations or len(destinations) != 1:
                    raise ValueError("conditional target lacks one exact source-qualified definition")
                destination = next(iter(destinations))
            else:
                destination = definition_files.get(candidate.wire)
            if destination is None:
                raise ValueError("conditional call target has no inventory definition")
            targets.append({"file_index": destination, "definition": candidate.wire})
        record = {
            "operation": call.operation.wire, "owner": call.execution_owner.wire,
            "inventory_pointer": f"#/files/{index}/calls/{call_index}" if inventory_source is None or inventory_source.partitions is None else None,
            "target_definitions": targets,
            "status": "CONDITIONAL" if targets else "UNRESOLVED",
            "actual_formal_return_connected": False,
        }
        if inventory_source is not None and inventory_source.partitions is not None:
            record["inventory_locator"] = inventory_source.file_locator(index, f"/calls/{call_index}")
        call_links.append(record)
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
                    max_output_bytes: int = 256_000_000, progress=None) -> dict:
    """Automatically index every supplied inventory file; never execute it.

    Existing source-layer validation and canonical ProgramGraph validation run
    once per file/body.  Missing archives remain visible; contradictory bound
    graphs raise rather than silently turning into a successful coverage row.
    """
    if type(max_files) is not int or max_files < 1:
        raise ValueError("max_files must be a positive exact integer")
    inventory = _InventorySource(inventory_path, max_input_bytes=max_input_bytes,
                                 max_record_bytes=max_record_bytes)
    artifact = inventory.receipt
    if inventory.file_count > max_files:
        raise ValueError("inventory file budget exceeded")
    layers = Path(source_layers_dir).resolve()
    manifest, source_artifact = _read(layers / "index.json", 32_000_000)
    if manifest.get("schema") != "scar.source-layers":
        raise ValueError("unsupported source-layer manifest")
    source_rows = {row["source_path"]: row for row in manifest["files"]}
    if len(source_rows) != len(manifest["files"]):
        raise ValueError("duplicate source-layer file")
    definition_files = {}
    seen_files = set()
    denominators = Counter(files=inventory.file_count)
    for index in range(inventory.file_count):
        raw = inventory.file(index)
        path = decode(SourceSnapshot, raw["snapshot"]).path
        if path in seen_files:
            raise ValueError("duplicate inventory source path")
        seen_files.add(path)
        denominators.update({"definitions": len(raw["definitions"]), "coverage_entries": len(raw["coverage"]),
                             "calls": len(raw["calls"]), "bodies": len(raw["bodies"])})
        for definition in decode(tuple[DefinitionInventory, ...], raw["definitions"]):
            key = (_definition_key(raw["snapshot"], definition.id)
                   if inventory.partitions is not None else definition.id.wire)
            if key in definition_files:
                raise ValueError("duplicate source definition identity")
            definition_files[key] = index
    rows = []
    for index in range(inventory.file_count):
        raw = inventory.file(index)
        path = raw["snapshot"]["path"]
        if progress is not None:
            progress({"stage": "source_file", "status": "BEGIN", "file_index": index, "path": path})
        source_row = source_rows.get(path)
        if source_row is None or source_row.get("status") != "STORED":
            rows.append({"file_index": index, "snapshot": raw["snapshot"], "status": "GAP",
                         "frontiers": [{"kind": "SOURCE_ARCHIVE_UNAVAILABLE", "detail": source_row.get("gap") if source_row else None}],
                         "counts": {}, "bodies": [], "calls": []})
            if progress is not None:
                progress({"stage": "source_file", "status": "GAP", "file_index": index, "path": path})
            continue
        view = load_source_layers(layers, path, max_record_bytes=max_record_bytes)
        rows.append(_compose_file(raw, index, view, definition_files, inventory_source=inventory))
        if progress is not None:
            progress({"stage": "source_file", "status": "END", "file_index": index,
                      "path": path, "counts": rows[-1]["counts"]})
    counts, frontier_counts = Counter(), Counter()
    for row in rows:
        counts.update(row["counts"])
        frontier_counts.update(item["kind"] for item in row["frontiers"])
        for body in row["bodies"]:
            frontier_counts.update(item["kind"] for item in body["frontiers"])
    document = {
        "schema": "scar.program-composition", "schema_version": 2 if inventory.partitions is not None else 1,
        "inventory": artifact, "source_layers": {**source_artifact, "directory": str(layers)},
        "files_total": len(rows), "files_indexed": sum(row["status"] != "GAP" for row in rows),
        "summary": {"inventory_denominators": dict(denominators),
                    "counts": dict(sorted(counts.items())),
                    "frontiers": dict(sorted(frontier_counts.items())), "first_stage_complete": False},
        "files": rows, **_AUTHORITY,
    }
    if inventory.partitions is not None:
        document["inventory_format"] = "PARTITIONED"
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


def compose_source_publication(base_composition, inventory_manifest, out_dir, *,
                               max_record_bytes=128_000_000, max_output_bytes=256_000_000,
                               progress=None):
    """Re-index changed source files; retain every other original projection.

    This is an explicit partition2/composition3 path. It neither changes legacy
    compose_program nor rebuilds source layers or canonical graph producers.
    """
    import tempfile
    if type(base_composition) is not CompositionIndex or not base_composition.partitioned:
        raise TypeError("delta composition requires an original partitioned CompositionIndex")
    inventory = _InventorySource(inventory_manifest, max_input_bytes=4_000_000,
                                 max_record_bytes=max_record_bytes)
    if inventory.partitions is None or inventory.partitions.version != 2:
        raise ValueError("delta composition requires an explicit source publication partition2")
    publication = inventory.component("publication")
    if (publication["base_inventory"] != base_composition.document["inventory"]
            or publication["base_composition"] != base_composition.index_receipt
            or publication["base_composition_canonical_sha256"] != base_composition._original_document_sha256):
        raise ValueError("publication differs from its actual parent composition/inventory")
    base_composition.source_inputs()  # Includes original document immutability check.
    CompositionIndex._verify_parent_composition(publication["base_composition"],
        canonical_sha256=publication["base_composition_canonical_sha256"])
    if inventory.partitions.code_source_origin() != base_composition.original_code_source_origin():
        raise ValueError("publication changed the original compiler/source evidence origin")
    if publication.get("schema_version") == 2:
        from scar.analysis.source_program_publication import validate_body_revision_publication
        validate_body_revision_publication(base_composition, inventory.partitions)
    changed = publication["changed_files"]
    if (type(changed) is not list or changed != sorted(set(changed))
            or inventory.file_count != base_composition.inventory_file_count
            or any(type(index) is not int or not 0 <= index < inventory.file_count for index in changed)):
        raise ValueError("publication source-file denominator or changed-file set differs")
    original = base_composition.inventory
    changed_components = {"header", "interfaces", "structured", "call_source_scope", "publication", "producer", "inputs"}
    for name, ref in original.manifest["components"].items():
        if name not in changed_components and inventory.partitions.external_reference(inventory.partitions.manifest["components"][name]) != original.external_reference(ref):
            raise ValueError("publication changed an undeclared original component")
    definitions, denominators = {}, Counter(files=inventory.file_count)
    for index in range(inventory.file_count):
        if index not in changed and inventory.partitions.external_reference(inventory.partitions.manifest["files"][index]) != original.external_reference(original.manifest["files"][index]):
            raise ValueError("publication changed an undeclared source shard")
        raw = inventory.file(index)  # Source headers only, no canonical graphs.
        original_header = original.file(index)
        if raw["snapshot"] != original_header["snapshot"] or raw["context"] != original_header["context"]:
            raise ValueError("source publication changed an original source snapshot/context")
        denominators.update(definitions=len(raw["definitions"]), coverage_entries=len(raw["coverage"]),
                            calls=len(raw["calls"]), bodies=len(raw["bodies"]))
        for definition in decode(tuple[DefinitionInventory, ...], raw["definitions"]):
            key = _definition_key(raw["snapshot"], definition.id)
            if key in definitions:
                raise ValueError("duplicate qualified source definition")
            definitions[key] = index
    actual_changes = set()
    for change in publication["changed_bodies"]:
        fi, bi = change["file_index"], change["body_index"]
        if (fi, bi) in actual_changes or fi not in changed:
            raise ValueError("duplicate or out-of-file source body publication")
        actual_changes.add((fi, bi))
        typed = inventory.partitions.typed_body(fi, bi)
        if (typed.language is None or not typed.public_language_structure_validated
                or typed.body.definition != decode(OperationDefinitionID, change["definition"])
                or typed.body.metadata.source != decode(SourceSnapshot, change["snapshot"])
                or typed.structured.source != decode(type(typed.structured.source), change["source"])):
            raise ValueError("new canonical body differs from its published source-language admission")
    if {key[0] for key in actual_changes} != set(changed):
        raise ValueError("changed file has no exact changed-body admission")
    rows = deepcopy(base_composition.document["files"])
    for index in changed:
        if progress is not None:
            progress({"stage": "compose_changed_file", "status": "BEGIN", "file_index": index})
        raw = inventory.file(index)
        rows[index] = _compose_file(raw, index, base_composition.source(index), definitions,
                                    inventory_source=inventory)
        if progress is not None:
            progress({"stage": "compose_changed_file", "status": "END", "file_index": index})
    counts, frontiers = Counter(), Counter()
    for row in rows:
        counts.update(row["counts"])
        frontiers.update(item["kind"] for item in row["frontiers"])
        for body in row["bodies"]:
            frontiers.update(item["kind"] for item in body["frontiers"])
    document = {"schema": "scar.program-composition", "schema_version": 3,
        "inventory_format": "PARTITIONED", "inventory": inventory.receipt,
        "parent_composition": deepcopy(base_composition.index_receipt),
        "source_layers": deepcopy(base_composition.document["source_layers"]),
        "files_total": len(rows), "files_indexed": sum(row["status"] != "GAP" for row in rows),
        "summary": {"inventory_denominators": dict(denominators), "counts": dict(sorted(counts.items())),
                    "frontiers": dict(sorted(frontiers.items())), "first_stage_complete": False},
        "files": rows, **_AUTHORITY}
    payload = _canonical(document)
    if type(max_output_bytes) is not int or max_output_bytes < 1 or len(payload) > max_output_bytes:
        raise ValueError("composition publication output budget exceeded")
    output = Path(out_dir).resolve()
    if output.exists():
        raise ValueError("composition output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".scar-composition-", dir=output.parent))
    try:
        with (temporary / "index.json.gz").open("xb") as stream:
            with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as zipped:
                zipped.write(payload)
        summary = {key: document[key] for key in ("schema", "schema_version", "files_total", "files_indexed", "summary")}
        (temporary / "summary.json").write_bytes(_canonical(summary))
        temporary.rename(output)
        return summary
    except BaseException as error:
        (temporary / "failure.json").write_text(json.dumps({"status": "BUILDING_FAILED_RETAINED",
            "error_type": type(error).__name__, "detail": str(error),
            "building_directory": str(temporary), "intended_output": str(output)}, indent=2) + "\n")
        error.add_note("composition BUILDING artifacts retained at " + str(temporary))
        raise


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
                 max_record_bytes: int = 128_000_000, cached_files: int = 2,
                 source_attachments=(), attachment_budget=SourceAttachmentBudget()):
        if type(cached_files) is not int or cached_files < 1:
            raise ValueError("cached_files must be positive")
        self.document, self.index_receipt = _read(Path(index_path), max_input_bytes)
        self._original_document_sha256 = hashlib.sha256(_canonical(self.document)).hexdigest()
        if self.document.get("schema") != "scar.program-composition" or self.document.get("schema_version") not in (1, 2, 3):
            raise ValueError("unsupported composition index")
        for key, value in _AUTHORITY.items():
            if self.document.get(key) is not value:
                raise ValueError("composition index overstates its authority")
        self._inventory = _InventorySource(self.document["inventory"]["path"],
            max_input_bytes=max_input_bytes, max_record_bytes=max_record_bytes)
        if self._inventory.receipt != self.document["inventory"]:
            raise ValueError("inventory differs from bound composition input")
        expected_partitioned = self.document["schema_version"] in (2, 3)
        if expected_partitioned != (self._inventory.partitions is not None):
            raise ValueError("composition version differs from its explicit inventory storage schema")
        if expected_partitioned and self.document.get("inventory_format") != "PARTITIONED":
            raise ValueError("partitioned composition requires its explicit storage format")
        if self.document["schema_version"] == 3:
            if self._inventory.partitions.version != 2:
                raise ValueError("composition3 requires the explicit source publication partition2")
            publication = self._inventory.component("publication")
            if publication["base_composition"] != self.document["parent_composition"]:
                raise ValueError("composition3 and publication parent receipts differ")
            self._verify_parent_composition(self.document["parent_composition"],
                canonical_sha256=publication["base_composition_canonical_sha256"])
            self._inventory.partitions.code_source_origin()
            if publication.get("schema_version") == 2:
                from scar.analysis.source_program_publication import validate_body_revision_publication
                parent = CompositionIndex(self.document["parent_composition"]["path"],
                    max_input_bytes=max_input_bytes, max_record_bytes=max_record_bytes, cached_files=cached_files)
                validate_body_revision_publication(parent, self._inventory.partitions)
        elif expected_partitioned and self._inventory.partitions.version != 1:
            raise ValueError("legacy composition2 cannot contain source publication partition2")
        if self._inventory.file_count != len(self.document["files"]):
            raise ValueError("composition/inventory source file denominator differs")
        # Kept for legacy clients only. New clients use the explicit accessors;
        # a partition reader never masquerades as a giant dict/list document.
        self.inventory = self._inventory.partitions or self._inventory.document
        self.partitioned = expected_partitioned
        self.layers = Path(self.document["source_layers"]["directory"])
        _, layer_receipt = _read(self.layers / "index.json", 32_000_000)
        if {**layer_receipt, "directory": str(self.layers)} != self.document["source_layers"]:
            raise ValueError("source-layer manifest differs from bound composition input")
        self.max_record_bytes, self.cached_files = max_record_bytes, cached_files
        self._views: OrderedDict[int, SourceLayerView] = OrderedDict()
        self._bodies: OrderedDict[tuple[int, int], tuple[ProgramGraph, LoweringMetadata]] = OrderedDict()
        if type(source_attachments) is not tuple or type(attachment_budget) is not SourceAttachmentBudget:
            raise TypeError("explicit source attachment tuples and typed independent budget required")
        self._attachments = []
        if source_attachments:
            if not self.partitioned:
                raise ValueError("formal source attachments require the explicit partitioned composition namespace")
            discovery = self.inventory_component("discovery")
            if type(discovery) is not dict or type(discovery.get("project_root")) is not str:
                raise ValueError("source attachments require the original project-root declaration")
            for declaration in source_attachments:
                if type(declaration) is not tuple or len(declaration) != 2:
                    raise ValueError("each source attachment requires its exact (report path, SHA256)")
                self._attachments.append(SourceAttachments(declaration[0], expected_report_sha256=declaration[1],
                    project_root=discovery["project_root"], budget=attachment_budget))
        self._project_definition_refs = {}
        self._project_definitions = {}
        self._project_snapshot_indexes = {_canonical(row["snapshot"]): index
                                          for index, row in enumerate(self.document["files"])}
        self._static_source_proof = None

    @staticmethod
    def _verify_parent_composition(receipt, *, canonical_sha256=None):
        path = Path(receipt["path"])
        if path.is_symlink() or not path.is_file():
            raise ValueError("publication parent composition is not its immutable artifact")
        digest, count = hashlib.sha256(), 0
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block); count += len(block)
                if count > receipt["raw_bytes"]:
                    raise ValueError("parent composition size differs")
        if count != receipt["raw_bytes"] or digest.hexdigest() != receipt["raw_sha256"]:
            raise ValueError("parent composition stored SHA/size differs")
        if canonical_sha256 is not None:
            decoded, size = hashlib.sha256(), 0
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    decoded.update(block); size += len(block)
                    if size > receipt["decoded_bytes"]:
                        raise ValueError("parent composition decoded byte budget differs")
            if size != receipt["decoded_bytes"] or decoded.hexdigest() != canonical_sha256:
                raise ValueError("publication parent must be the exact original canonical composition artifact")

    def publication_header(self):
        header = self.inventory_component("header")
        extended = self.document["schema_version"] == 3
        if extended:
            publication = self.inventory_component("publication")
            if (header.get("schema") != "scar.partitioned-inventory-header" or header.get("schema_version") != 2
                    or header.get("capabilities") not in (["SOURCE_PROGRAM5_ADMISSION_V1"],
                        ["SOURCE_PROGRAM5_ADMISSION_V1", "SOURCE_BODY_REVISION_V1"])
                    or header.get("capabilities") != self._inventory.partitions.manifest["capabilities"]
                    or publication["base_composition"] != self.document["parent_composition"]):
                raise ValueError("source publication header/capability/parent differs")
            canonical = publication["base_composition_canonical_sha256"]
            parent_inventory = publication["base_inventory"]
            keys = deepcopy(publication["changed_bodies"])
        else:
            if header.get("schema") != "scar.program-inventory":
                raise ValueError("legacy inventory header schema differs")
            canonical, parent_inventory, keys = self._original_document_sha256, self.document["inventory"], []
        return {"header_schema": header["schema"], "header_version": header["schema_version"],
            "profile": header["profile"], "supported_call_abi": "STRUCTURED_ENV_V1" if header["profile"] == "STRUCTURED_ENV_V1" else None,
            "capabilities": deepcopy(header.get("capabilities", [])),
            "base_inventory_receipt": deepcopy(parent_inventory),
            "base_composition_receipt": deepcopy(self.document["parent_composition"] if extended else self.index_receipt),
            "base_composition_canonical_sha256": canonical, "changed_body_keys": keys}

    def original_code_source_origin(self):
        if self.partitioned:
            return self._inventory.partitions.code_source_origin()
        return {"inventory": deepcopy(self.document["inventory"]),
                "call_sources": self.inventory_component_locator("call_sources")}

    def code_source_origin(self):
        return self.original_code_source_origin()

    def install_static_source_proof(self, proof):
        from scar.analysis.current_source_evidence import SameRunSourceProof
        if type(proof) is not SameRunSourceProof:
            raise TypeError("static source proof requires the checked same-Run proof reader")
        proof.require_composition(self)
        if self._static_source_proof is not None:
            raise ValueError("same-Run static source proof is already installed")
        self._static_source_proof = proof

    def static_source_proof_receipt(self):
        return deepcopy(self._static_source_proof.receipt()) if self._static_source_proof is not None else None

    @property
    def has_source_attachments(self):
        return bool(self._attachments)

    def source_inputs(self):
        """Explicit input receipts; the original composition document stays intact."""
        if hashlib.sha256(_canonical(self.document)).hexdigest() != self._original_document_sha256:
            raise ValueError("composition document changed after its bound original receipt")
        return {"composition_canonical_sha256": self._original_document_sha256,
                "inventory": deepcopy(self.document["inventory"]),
                "attachments": [attachment.receipts() for attachment in self._attachments]}

    def verify_source_attachments(self, scanned, groups):
        return [attachment.verify_capture(scanned, groups) for attachment in self._attachments]

    def source_attachment_reuse_checks(self, scanned, groups):
        return [attachment.current_scope_receipt(scanned, groups) for attachment in self._attachments]

    def static_code_witness(self, captured, *, compilation_profile, captured_python_build):
        found = [attachment.static_code_witness(captured, compilation_profile=compilation_profile,
                    captured_python_build=captured_python_build) for attachment in self._attachments]
        found = [witness for witness in found if witness is not None]
        verified = [witness for witness in found if witness["status"] == "SOURCE_VERIFIED"]
        selected = verified or found
        if not selected:
            return None
        first = selected[0]
        if any(witness["captured_code"] != first["captured_code"]
               or witness["code_source_link"] != first["code_source_link"] for witness in selected[1:]):
            raise ValueError("attachments contain ambiguous complete static code/source witnesses")
        return first

    def static_definition_reference(self, witness):
        if self._static_source_proof is not None:
            reference = self._static_source_proof.definition_reference(witness)
            if reference is not None:
                return reference
        for attachment in self._attachments:
            if witness["record_locator"]["artifact"] == attachment.receipts()["report"]["artifact"]:
                return attachment.static_definition_reference(witness)
        raise ValueError("static source witness has no explicitly bound original attachment")

    @staticmethod
    def current_source_guard(snapshot, index, checks):
        """Validate a producer's explicit current guard, without refreshing it."""
        if type(index) is not int or not 0 <= index < len(checks):
            raise ValueError("current source guard has no exact report index")
        check = checks[index]
        if (check["path"] != snapshot.path or check["expected_fingerprint"] != snapshot.fingerprint
                or check["method"] != "tokenize.open decoded text, universal newlines, UTF-8 SHA256"):
            raise ValueError("current source guard belongs to a different source snapshot/method")
        if check["status"] == "FINGERPRINT_MATCH" and (
                check["actual_fingerprint"] != snapshot.fingerprint or check["frontier"] is not None):
            raise ValueError("current source guard success contradicts its fingerprint")
        if check["status"] not in ("FINGERPRINT_MATCH", "UNRESOLVED") or (
                check["status"] == "UNRESOLVED" and type(check["frontier"]) is not str):
            raise ValueError("current source guard has an unsupported outcome or no frontier")
        return deepcopy(check)

    def validate_static_source_binding(self, binding, *, compilation_profile,
                                       captured_python_build, current_source_checks):
        """Shared source-only proof query for dispatch and SourceBodyAccess.

        Dynamic rows are supplied by their current raw readers. This validates
        original static evidence and the declared guard, adding no producer.
        """
        from scar.ir.program.call_edges import CodeCapture, CodeSourceLink, CallLinkStatus
        capture = decode(CodeCapture, binding["code_capture"])
        if capture.process_id != binding["process_id"] or capture.code.key != binding["code"]:
            raise ValueError("static binding differs from its current captured descriptor")
        witness = self.static_code_witness(capture.code, compilation_profile=compilation_profile,
            captured_python_build=captured_python_build)
        if witness is None or witness["status"] != "SOURCE_VERIFIED":
            raise ValueError("source-only binding has no complete original static code witness")
        link = decode(CodeSourceLink, witness["code_source_link"])
        if link.status is not CallLinkStatus.VERIFIED:
            raise ValueError("static source link is not verified")
        reference = self.static_definition_reference(witness)
        index = binding["current_source_check"]
        check = self.current_source_guard(link.snapshot, index, current_source_checks)
        usable = witness["context_guard"]["status"] == "MATCH" and check["status"] == "FINGERPRINT_MATCH"
        expected_witness = {"static_witness": witness,
            "historical_definition": encode(reference) if reference is not None else None,
            "current_guard_scope": "CURRENT_REUSED_CODE_SOURCE_FINGERPRINT", "current_guard_index": index}
        expected_ref = encode(reference) if usable and reference is not None else None
        if (binding.get("attachment_witness") != expected_witness
                or binding["definition"] != expected_ref
                or binding["definition_locator"] != (encode(reference.graph) if expected_ref is not None else None)
                or binding["snapshot"] != (encode(link.snapshot) if usable else None)
                or binding["source"] != (encode(link.source) if usable else None)
                or binding["body"] is not None or binding.get("composition_element") is not None
                or binding["complete_descriptor_match"] is not True
                or binding["witness_status"] != "VERIFIED" or binding["witness_issues"] != encode(link.issues)
                or binding["source_verification"] != "REUSED_HISTORICAL_CODE_SOURCE_WITNESS"
                or binding["status"] != ("SOURCE_LINKED_REUSED_WITNESS"
                    if usable and reference is not None else "UNRESOLVED")):
            raise ValueError("current source-only binding changed its original static proof/guard")
        for name in ("descriptor_witness_pointer", "code_source_witness_pointer", "admission_pointer",
                     "descriptor_witness_locator", "code_source_witness_locator", "admission_locator"):
            if binding.get(name) is not None:
                raise ValueError("source-only static binding acquired a project/dynamic admission")
        if binding.get("static_body_witness_pointers") != [] or binding.get("static_body_witness_locators") != []:
            raise ValueError("external static source binding acquired typed body witnesses")
        result = {"source_usable": usable, "reference": reference,
                  "code_source_link": link, "static_witness": witness, "current_source_guard": check}
        if self._static_source_proof is not None:
            result["reference_membership_proof"] = self._static_source_proof.reference_membership_proof(reference)
        return result

    def attachment_capture_declarations(self):
        return [attachment.capture_declaration() for attachment in self._attachments]

    def attached_code_witness(self, process_id, code):
        found = [(attachment, attachment.code_witness(process_id, code)) for attachment in self._attachments]
        found = [(attachment, witness) for attachment, witness in found if witness is not None]
        verified = [(attachment, witness) for attachment, witness in found
                    if witness["record"]["status"] == "SOURCE_VERIFIED"]
        chosen = verified or found
        if not chosen:
            return None
        first = chosen[0][1]
        for _, witness in chosen[1:]:
            if (witness["record"]["captured_code"] != first["record"]["captured_code"]
                    or witness["record"]["code_source_link"] != first["record"]["code_source_link"]):
                raise ValueError("source attachments contain contradictory full code/source witnesses")
        return first

    def attached_definition_reference(self, process_id, code):
        references = [attachment.definition_reference(process_id, code) for attachment in self._attachments]
        references = [reference for reference in references if reference is not None]
        if any(reference.identity_key() != references[0].identity_key() for reference in references[1:]):
            raise ValueError("source attachments disagree on the original source-qualified definition")
        return references[0] if references else None

    def definition_reference(self, file_index, definition_id):
        """Reference an original project definition; file_index remains an internal view."""
        key = file_index, definition_id
        if key in self._project_definition_refs:
            return self._project_definition_refs[key]
        self._project_definition_references(file_index, (definition_id,))
        return self._project_definition_refs[key]

    def prefetch_definition_references(self, requests):
        """Batch only demanded original project definitions by source file.

        This is an internal frontend read optimization, not source compilation
        or a new graph producer. Each requested definition still receives all
        original graph/snapshot/source-atom checks before a compact record is
        retained. No whole source graphs are pinned beyond the normal LRU.
        """
        grouped = {}
        for file_index, definition_id in requests:
            if type(file_index) is not int or type(definition_id) is not OperationDefinitionID:
                raise TypeError("exact source-file index and original definition ID required")
            if (file_index, definition_id) not in self._project_definition_refs:
                grouped.setdefault(file_index, set()).add(definition_id)
        for file_index in sorted(grouped):
            self._project_definition_references(file_index, tuple(grouped[file_index]))

    def _project_definition_references(self, file_index, definition_ids):
        raw = self.inventory_file(file_index)
        definitions = decode(tuple[DefinitionInventory, ...], raw["definitions"])
        indexed = {definition.id: definition for definition in definitions}
        if len(indexed) != len(definitions) or any(identity not in indexed for identity in definition_ids):
            raise ValueError("definition is not one original inventory/source record")
        view = self.source(file_index)
        if view.artifact_locator is None or view.snapshot != decode(SourceSnapshot, raw["snapshot"]):
            raise ValueError("source view has no exact original artifact/snapshot locator")
        indexes = {item.id: index for index, item in enumerate(view.semantic.definitions.values())}
        root = replace(view.artifact_locator, pointer="#/source/context/namespace_root")
        providers = (replace(view.artifact_locator, pointer="#/metadata"),)
        for definition_id in definition_ids:
            definition = indexed[definition_id]
            semantic = view.semantic.definitions.get(definition_id)
            atom = view.semantic.source_atoms.get(definition.source.atom_id)
            if (semantic is None or atom is None or atom.reference != definition.source
                    or definition.source.atom_id not in semantic.source_atoms):
                raise ValueError("project definition/source differs from the original semantic graph")
            graph = replace(view.artifact_locator, pointer=f"#/payload/semantic/definitions/{indexes[definition_id]}")
            reference = SourceDefinitionReference(root, providers, graph, view.snapshot, view.context,
                                                   definition_id, definition.source)
            self._project_definition_refs[file_index, definition_id] = reference
            self._project_definitions[_canonical(encode(reference))] = deepcopy(semantic)

    def _project_reference_view(self, reference):
        file_index = self._project_snapshot_indexes.get(_canonical(encode(reference.snapshot)))
        if file_index is None:
            return None
        expected = self.definition_reference(file_index, reference.definition)
        if expected != reference:
            raise ValueError("formal project definition locator differs from the bound original")
        return self.source(file_index)

    def resolve_definition(self, reference):
        if type(reference) is not SourceDefinitionReference:
            raise TypeError("formal source definition reference required")
        reference.__post_init__()
        key = _canonical(encode(reference))
        if key in self._project_definitions:
            return deepcopy(self._project_definitions[key])
        view = self._project_reference_view(reference)
        if view is not None:
            return deepcopy(view.semantic.definitions[reference.definition])
        for attachment in self._attachments:
            if attachment.owns_reference(reference):
                return attachment.resolve_definition(reference)
        raise ValueError("formal definition has no bound original source attachment")

    def source_view(self, reference):
        if type(reference) is not SourceDefinitionReference:
            raise TypeError("formal source definition reference required")
        view = self._project_reference_view(reference)
        if view is not None:
            return deepcopy(view)
        for attachment in self._attachments:
            if attachment.owns_reference(reference):
                return attachment.source_view(reference)
        raise ValueError("formal source graph has no exact bound attachment")

    @property
    def inventory_file_count(self):
        return self._inventory.file_count

    def inventory_file(self, index):
        return self._inventory.file(index)

    def inventory_body(self, file_index, body_index):
        return self._inventory.body(file_index, body_index)

    def inventory_component(self, name):
        return self._inventory.component(name)

    def inventory_file_locator(self, index, pointer=""):
        return self._inventory.file_locator(index, pointer)

    def inventory_component_locator(self, name, pointer=""):
        return self._inventory.component_locator(name, pointer)

    def inventory_body_locators(self, file_index, body_index, graph_document=None):
        return self._inventory.body_locators(file_index, body_index, graph_document)

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
            raw = self.inventory_body(file_index, body_index)
            if raw["definition"]["wire"] != attachment["definition"]:
                raise ValueError("body definition differs from composition reference")
            payload = _canonical(raw["graph"])
            if hashlib.sha256(payload).hexdigest() != attachment["program_canonical_sha256"]:
                raise ValueError("body graph differs from composition reference")
            if self.partitioned:
                locators = self.inventory_body_locators(file_index, body_index, raw["graph"])
                if any(attachment.get(name) != locator for name, locator in locators.items()):
                    raise ValueError("body locator/namespace differs from its original source shard and checkpoint")
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
            coverage = self.inventory_file(reference.file_index)["coverage"]
            result["coverage_records"] = tuple(decode(CoverageEntry, coverage[owner[3]])
                                                for owner in result["execution_owners"])
            for owner, item in zip(result["execution_owners"], result["coverage_records"]):
                if item.status.value != "CONNECTED":
                    frontier = {"kind": "COVERAGE_" + item.status.value,
                        "inventory_pointer": f"#/files/{reference.file_index}/coverage/{owner[3]}" if not self.partitioned else None,
                        "detail": item.reason}
                    if self.partitioned:
                        frontier["inventory_locator"] = self.inventory_file_locator(reference.file_index, f"/coverage/{owner[3]}")
                    result["frontiers"].append(frontier)
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
        calls = decode(tuple[CallInventory, ...], self.inventory_file(reference.file_index)["calls"])
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


__all__ = ["CompositionIndex", "ElementReference", "compose_program", "compose_source_publication"]
