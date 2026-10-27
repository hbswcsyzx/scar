"""Immutable, reference-only storage for an existing ProgramInventory.

This is an archive/lookup adapter, not a second program graph. Canonical body
records remain in their original checksum-bound construction checkpoints.
The public monolithic inventory codec and replay contract are unchanged.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
import gzip
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any

from scar.ir.record_codec import decode, encode, loads as strict_loads


SCHEMA = "scar.partitioned-program-inventory"
VERSION = 1
CHECKPOINT_SCHEMA = "scar.body-construction-checkpoint"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _file_hash(path):
    digest, size = sha256(), 0
    with Path(path).open("rb") as stream:
        for piece in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(piece)
            size += len(piece)
    return digest.hexdigest(), size


def _read_receipt(path, *, limit):
    path = Path(path)
    _require(path.is_file() and not path.is_symlink(), "archive input must be an existing regular file")
    _require(path.stat().st_size <= limit, "archive physical byte budget exceeded")
    physical_hash, physical_size = _file_hash(path)
    _require(physical_size <= limit, "archive physical byte budget exceeded")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        payload = stream.read(limit + 1)
    _require(len(payload) <= limit, "archive decoded byte budget exceeded")
    document = strict_loads(payload.decode("utf-8"))
    _require(type(document) is dict, "archive record must be a JSON object")
    return document, {"physical_sha256": physical_hash, "physical_bytes": physical_size,
        "decoded_sha256": sha256(payload).hexdigest(), "decoded_bytes": len(payload)}


def checkpoint_reference(path, *, decoded_sha256, decoded_bytes):
    """Verify an original materialized-return receipt, retaining its artifact URI."""
    path = Path(path).resolve()
    document, receipt = _read_receipt(path, limit=decoded_bytes)
    _require(receipt["decoded_sha256"] == decoded_sha256
             and receipt["decoded_bytes"] == decoded_bytes, "original checkpoint receipt mismatch")
    _require(document.get("schema") == CHECKPOINT_SCHEMA and document.get("schema_version") == 1
             and document.get("whole_program_established") is False, "unsupported checkpoint schema/authority")
    return {"uri": str(path), "external": True,
        "representation": CHECKPOINT_SCHEMA + "/1", **receipt}


@dataclass(frozen=True)
class MaterializedBodySource:
    """Archive provenance of the exact original lowerer return, not an IR node."""
    result: Any
    checkpoint: dict
    sequence: int


def _write_shard(root, relative, document, *, limit):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    digest, size = sha256(), 0
    with path.open("xb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as stream:
            pending = bytearray()
            for text in json.JSONEncoder(sort_keys=True, ensure_ascii=False,
                    allow_nan=False, separators=(",", ":")).iterencode(document):
                data = text.encode("utf-8")
                size += len(data)
                _require(size + 1 <= limit, "partition independently exceeds its decoded byte budget")
                digest.update(data)
                pending.extend(data)
                if len(pending) >= 65536:
                    stream.write(pending)
                    pending.clear()
            digest.update(b"\n")
            size += 1
            pending.extend(b"\n")
            stream.write(pending)
    physical_hash, physical_size = _file_hash(path)
    return {"uri": relative, "external": False, "representation": document["schema"] + "/1",
        "physical_sha256": physical_hash, "physical_bytes": physical_size,
        "decoded_sha256": digest.hexdigest(), "decoded_bytes": size}


def publish_partitioned_inventory(inventory, out_dir, *, materialized_bodies,
                                  producer, inputs, max_shard_bytes=128_000_000):
    """Archive original records without calling ProgramInventory.to_dict().

    ``materialized_bodies`` maps identity of the original returned metadata to
    MaterializedBodySource. Object identity checks prevent a changed graph or
    metadata record from borrowing a checkpoint's provenance. The caller must
    have performed public graph/overlay validation on every restored return.
    """
    from scar.analysis.program_inventory import ProgramInventory
    from scar.ir.program.functions import BodyLoweringProfile
    _require(type(inventory) is ProgramInventory, "partition writer needs an original ProgramInventory")
    _require(inventory.profile is BodyLoweringProfile.STRUCTURED_ENV,
             "first partition archive supports the existing structured environment inventory profile")
    _require(type(max_shard_bytes) is int and max_shard_bytes > 0, "invalid per-shard byte budget")
    inventory._check_profile()
    out_dir = Path(out_dir).resolve()
    _require(not out_dir.exists(), "partition output already exists")
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".scar-inventory-", dir=out_dir.parent))
    refs, interface_refs, structured_refs, frame_refs = [], {}, {}, {}
    seen_sources, qualified_definitions = set(), set()
    checkpoint_count = graph_count = not_attempted = 0
    try:
        for file_index, file in enumerate(inventory.files):
            _require(file.snapshot.path not in seen_sources, "duplicate source inventory file")
            seen_sources.add(file.snapshot.path)
            bodies = []
            for body_index, body in enumerate(file.bodies):
                # Bare local identifiers are not globally reinterpreted. This
                # tuple qualifies a definition in this source representation.
                qualified = (file.snapshot.path, file.snapshot.fingerprint, body.definition.wire)
                _require(qualified not in qualified_definitions, "duplicate qualified source body")
                qualified_definitions.add(qualified)
                row = {"definition": encode(body.definition), "status": body.status.value,
                    "reason": body.reason, "construction_operations": body.construction_operations,
                    "checkpoint": None, "metadata_without_checkpoint": None}
                if body.metadata is not None:
                    materialized = materialized_bodies.get(id(body.metadata))
                    _require(type(materialized) is MaterializedBodySource,
                             "body metadata lacks its original materialized return")
                    result = materialized.result
                    _require(result.metadata is body.metadata and result.graph is body.graph
                             and result.operations_emitted == body.construction_operations,
                             "body no longer holds its original checkpoint-bound fields")
                    _require(result.metadata.source == file.snapshot, "body checkpoint/source snapshot mismatch")
                    ref = {**materialized.checkpoint, "sequence": materialized.sequence,
                        "body_identity": {"definition": encode(body.definition),
                            "source": encode(result.structured.source) if result.structured is not None else None,
                            "entry": result.metadata.entry},
                        "graph_pointer": "#/graph", "metadata_pointer": "#/metadata",
                        "interface_pointer": "#/interface", "frame_pointer": "#/frame",
                        "structured_pointer": "#/structured"}
                    row["checkpoint"] = ref
                    checkpoint_count += 1
                    if body.graph is not None:
                        _require(result.interface is not None and result.interface.definition == body.definition,
                                 "body checkpoint/interface definition mismatch")
                        interface_refs[id(result.interface)] = ref
                        if result.structured is not None:
                            structured_refs[id(result.structured)] = ref
                        if result.frame is not None:
                            frame_refs[id(result.frame)] = ref
                        graph_count += 1
                else:
                    _require(body.graph is None, "graph without original metadata cannot be archived")
                    if body.status.value == "NOT_ATTEMPTED":
                        not_attempted += 1
                bodies.append(row)
            document = {"schema": "scar.partitioned-file-inventory", "schema_version": 1,
                "file_index": file_index, "file": {"snapshot": encode(file.snapshot),
                    "context": encode(file.context), "definitions": encode(file.definitions),
                    "calls": encode(file.calls), "coverage": encode(file.coverage),
                    "gaps": encode(file.gaps), "implicit_invocations": encode(file.implicit_invocations),
                    "bodies": bodies}}
            refs.append(_write_shard(temporary, f"sources/{file_index:05d}.json.gz", document,
                                     limit=max_shard_bytes))

        def component(name, value):
            return _write_shard(temporary, f"components/{name}.json.gz", {
                "schema": "scar.inventory-component", "schema_version": 1,
                "name": name, "value": value}, limit=max_shard_bytes)

        interfaces = None
        if inventory.interfaces is not None:
            interfaces = {"profile": inventory.interfaces.profile.value,
                "signatures": encode(inventory.interfaces.signatures),
                "bindings": encode(inventory.interfaces.bindings), "issues": encode(inventory.interfaces.issues),
                "bodies": [interface_refs[id(body)] for body in inventory.interfaces.bodies]}
        components = {}
        header = {"schema": "scar.program-inventory", "schema_version":
            8 if inventory.profile.value == "STRUCTURED_ENV_V1" else
            7 if inventory.profile.value == "STRUCTURED_BODY_V1" else 6,
            "scope": "source-discovered candidate files, scoped interfaces and bounded automatic body lowering",
            "budget": encode(inventory.budget), "profile": inventory.profile.value,
            "summary": inventory.summary(), "target_executed": False, "transformation_authorized": False}
        for name, value in {
            "header": header, "discovery": encode(inventory.discovery),
            "expansion": encode(inventory.expansion), "runtime_scope": encode(inventory.runtime_scope),
            "call_sources": inventory.call_sources.to_dict() if inventory.call_sources is not None else None,
            "call_source_scope": encode(inventory.call_source_scope), "interfaces": interfaces,
            "structured": [structured_refs[id(model)] for model in inventory.structured],
            "frames": [frame_refs[id(model)] for model in inventory.frames],
            "analysis_measurements": encode(inventory.analysis_measurements),
            "source_analysis_measurements": inventory.source_analysis_measurements,
            "producer": producer, "inputs": inputs,
        }.items():
            components[name] = component(name, value)
        manifest = {"schema": SCHEMA, "schema_version": VERSION,
            "storage": "immutable shards and original materialized-body references",
            "identity": "artifact(uri, decoded_sha256)/representation/body/kind/local_id",
            "files": refs, "components": components,
            "counts": {"source_files": len(refs), "checkpoint_returns": checkpoint_count,
                "graph_bodies": graph_count, "not_attempted_bodies": not_attempted},
            "public_source_replay_performed": False, "fresh_body_lowering_performed": False,
            "whole_program_graph_established": False, "transformation_authorized": False}
        (temporary / "manifest.json").write_text(json.dumps(manifest, sort_keys=True,
            ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        temporary.rename(out_dir)
        return manifest
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


@dataclass(frozen=True)
class TypedBodyPartition:
    body: Any
    interface: Any
    frame: Any
    structured: Any
    namespace: dict | None
    public_graph_validated: bool
    public_source_overlay_validated: bool
    source_replay_performed: bool = False


class InventoryPartitions:
    """Bounded lazy archive reader. No giant document is reconstructed."""
    def __init__(self, manifest, *, max_shard_bytes=128_000_000, cache_entries=2):
        path = Path(manifest).resolve()
        if path.is_dir():
            path = path / "manifest.json"
        self.root = path.parent
        self.manifest, self.manifest_receipt = _read_receipt(path, limit=4_000_000)
        _require(self.manifest.get("schema") == SCHEMA and self.manifest.get("schema_version") == VERSION,
                 "partition manifest schema mismatch")
        _require(self.manifest.get("whole_program_graph_established") is False
                 and self.manifest.get("transformation_authorized") is False,
                 "partition archive cannot raise program authority")
        _require(type(cache_entries) is int and cache_entries > 0, "invalid partition cache budget")
        self.max_shard_bytes, self.cache_entries = max_shard_bytes, cache_entries
        self._cache = OrderedDict()

    def _read(self, ref):
        key = (ref["uri"], ref["physical_sha256"], ref["decoded_sha256"])
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        if ref["external"]:
            path = Path(ref["uri"])
            _require(path.is_absolute(), "external evidence URI must be absolute")
        else:
            relative = Path(ref["uri"])
            _require(not relative.is_absolute() and ".." not in relative.parts,
                     "internal shard URI must remain within the archive")
            path = self.root / relative
        _require(ref["decoded_bytes"] <= self.max_shard_bytes
                 and ref["physical_bytes"] <= self.max_shard_bytes,
                 "reference exceeds reader independent shard budget")
        document, receipt = _read_receipt(path, limit=self.max_shard_bytes)
        _require(all(receipt[name] == ref[name] for name in receipt), "partition SHA/size mismatch")
        _require(ref["representation"] == document["schema"] + "/" + str(document["schema_version"]),
                 "partition representation mismatch")
        self._cache[key] = document
        while len(self._cache) > self.cache_entries:
            self._cache.popitem(last=False)
        return document

    def component(self, name):
        document = self._read(self.manifest["components"][name])
        _require(document.get("name") == name, "partition component name mismatch")
        return deepcopy(document["value"])

    def file(self, index):
        _require(type(index) is int and 0 <= index < len(self.manifest["files"]), "source index out of range")
        document = self._read(self.manifest["files"][index])
        _require(document.get("file_index") == index, "source shard ordinal mismatch")
        return deepcopy(document["file"])

    def iter_files(self):
        for index in range(len(self.manifest["files"])):
            yield self.file(index)

    def checkpoint(self, ref):
        document = self._read(ref)
        _require(document.get("schema") == CHECKPOINT_SCHEMA
                 and document.get("whole_program_established") is False,
                 "body reference does not identify an original construction checkpoint")
        return deepcopy(document)

    def body_record(self, file_index, body_index):
        """Return one original BodyInventory wire record, reading just its shard."""
        row = self.file(file_index)["bodies"][body_index]
        checkpoint = self.checkpoint(row["checkpoint"]) if row["checkpoint"] is not None else None
        if checkpoint is not None:
            identity = row["checkpoint"]["body_identity"]
            _require(identity["definition"] == row["definition"]
                     and identity["entry"] == checkpoint["entry"]
                     and checkpoint["operations_emitted"] == row["construction_operations"],
                     "source body/header differs from its original materialized-return reference")
            actual_source = checkpoint["structured"]["source"] if checkpoint["structured"] is not None else None
            _require(identity["source"] == actual_source, "qualified body source differs from checkpoint")
        return {"definition": row["definition"], "status": row["status"], "reason": row["reason"],
            "construction_operations": row["construction_operations"],
            "graph": checkpoint["graph"] if checkpoint is not None else None,
            "metadata": checkpoint["metadata"] if checkpoint is not None else row["metadata_without_checkpoint"]}

    def qualified_reference(self, file_index, body_index, *, kind, local_id):
        ref = self.file(file_index)["bodies"][body_index]["checkpoint"]
        _require(ref is not None, "an unattempted body has no canonical-body namespace")
        _require(type(kind) is str and kind, "qualified reference requires an explicit kind")
        graph = self.checkpoint(ref)["graph"]
        _require(graph is not None and graph.get("schema") == "scar.program-graph",
                 "an unsupported materialized return has no canonical-body namespace")
        return {"namespace": {"artifact": {"uri": ref["uri"], "decoded_sha256": ref["decoded_sha256"]},
            "representation": "scar.program-graph/" + str(graph["schema_version"]),
            "record_pointer": "#/graph", "body": ref["body_identity"]},
            "kind": kind, "local_id": encode(local_id)}

    def typed_body(self, file_index, body_index, *, source_layers=None):
        """Use existing public validators, optionally including original source layers.

        Without source_layers only canonical graph validation is claimed. With
        it, original source snapshot/context and structured overlay/formals are
        checked; this still does not replay source construction or raw calls.
        """
        from scar.ir.program.codec import loads as load_graph
        from scar.ir.program.frames import FrameModel
        from scar.ir.program.functions import BodyEntryInterface, FunctionSignature
        from scar.ir.program.ids import RegionID
        from scar.ir.program.inventory import BodyInventory, BodyStatus, SourceContextDigest
        from scar.ir.program.source import LoweringMetadata
        from scar.ir.program.structured import StructuredBodyModel
        from scar.ir.semantics_v2 import SourceSnapshot
        from scar.ir.v2.ids import OperationDefinitionID
        file = self.file(file_index)
        row = file["bodies"][body_index]
        checkpoint = self.checkpoint(row["checkpoint"]) if row["checkpoint"] is not None else None
        raw = self.body_record(file_index, body_index)
        graph = load_graph(json.dumps(raw["graph"], allow_nan=False)) if raw["graph"] is not None else None
        metadata = decode(LoweringMetadata, raw["metadata"]) if raw["metadata"] is not None else None
        body = BodyInventory(decode(OperationDefinitionID, raw["definition"]),
            decode(BodyStatus, raw["status"]), graph, metadata, raw["reason"], raw["construction_operations"])
        interface = decode(BodyEntryInterface, checkpoint["interface"]) if checkpoint is not None and checkpoint["interface"] is not None else None
        frame = FrameModel.from_dict(checkpoint["frame"]) if checkpoint is not None and checkpoint["frame"] is not None else None
        structured = decode(StructuredBodyModel, checkpoint["structured"]) if checkpoint is not None and checkpoint["structured"] is not None else None
        if metadata is not None:
            _require(metadata.source == decode(SourceSnapshot, file["snapshot"]), "checkpoint/source snapshot mismatch")
        if graph is None:
            _require(body.status is not BodyStatus.LOWERED_WITH_GAPS
                     and interface is None and structured is None and frame is None,
                     "null graph has a contradictory status or overlay")
        else:
            _require(body.status is BodyStatus.LOWERED_WITH_GAPS and interface is not None
                     and interface.definition == body.definition and interface.region == graph.root,
                     "canonical body definition/status/interface mismatch")
        overlay_checked = False
        if source_layers is not None and graph is not None:
            from scar.analysis.function_interfaces import validate_body_interface
            from scar.analysis.source_layers import load_source_layers
            from scar.analysis.structured_lowering import require_valid_structured_body
            view = load_source_layers(source_layers, file["snapshot"]["path"],
                                      max_record_bytes=self.max_shard_bytes)
            _require(view.snapshot == decode(SourceSnapshot, file["snapshot"])
                     and view.context == decode(SourceContextDigest, file["context"]),
                     "partitioned source inventory differs from the original source archive")
            require_valid_structured_body(structured, graph, interface, metadata,
                                          semantic=view.semantic, control=view.control)
            signatures = self.component("interfaces")["signatures"]
            matching = [decode(FunctionSignature, signature) for signature in signatures
                        if signature["definition"] == raw["definition"]
                        and signature["source"]["path"] == file["snapshot"]["path"]
                        and signature["source"]["fingerprint"] == file["snapshot"]["fingerprint"]]
            _require(len(matching) == 1, "body must identify one original signature")
            validate_body_interface(body, interface, matching[0])
            overlay_checked = True
        namespace = self.qualified_reference(file_index, body_index, kind="Region", local_id=graph.root)["namespace"] if graph is not None else None
        return TypedBodyPartition(body, interface, frame, structured, namespace,
                                  graph is not None, overlay_checked)


__all__ = ["InventoryPartitions", "MaterializedBodySource", "TypedBodyPartition",
           "checkpoint_reference", "publish_partitioned_inventory"]
