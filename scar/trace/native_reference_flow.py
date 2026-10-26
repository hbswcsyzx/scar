"""Sharded reference-recurrence adjacency over original native Tensor ports.

These records connect earlier observed output references to later observed
input references sharing the same provider token and descriptor. They are
candidate reference-flow links only; they create no logical value, content
version, unique producer, write, alias, or readiness claim.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from hashlib import sha256
import gzip
import json
from pathlib import Path
import re
import tempfile
from typing import Any

from scar.ir.execution.content import EvidenceEdgeRef
from scar.ir.execution.ids import ValueOccurrenceID
from scar.ir.program.providers import ProviderArtifact
from scar.ir.v2.evidence import EvidenceStatus, OperationInstance
from scar.ir.v2.ids import OperationDefinitionID, OperationInstanceID, ValueSlotID
from scar.ir.record_codec import decode, encode, loads
from scar.store.bundle_partitions import BundlePartitions
from .native_port_sidecar import (
    NativeBoxedPort, NativeInstancePorts, NativePortIndex, NativePortShardReference,
    _identity_from_values, _manifest_identity, _read_shard, read_native_port_index,
    query_native_ports,
)


_INDEX_SCHEMA = "scar.native-reference-flow-index"
_SHARD_SCHEMA = "scar.native-reference-flow-shard"
_VERSION = 2
_SHARD_VERSION = 2
_BUCKETS = 128
_MAX_QUERY_CANDIDATES = 256
_MAX_INDEX_BYTES = 8_000_000
_MAX_SHARD_BYTES = 64_000_000
_EDGE_RELATIONS = {"input_reference": "input", "output_reference": "output"}
_FLOW_UNKNOWN = (
    "same_provider_reference_does_not_establish_same_tensor_contents",
    "source_ordinal_is_an_ordered_locator_not_happens_before_or_completion_proof",
    "unique_producer_and_causal_def_use_are_not_proved",
    "logical_value_or_content_version_is_not_created",
    "schema_alias_write_and_native_effects_are_not_resolved_as_edge_proofs",
    "storage_region_and_device_readiness_are_unknown",
)


def _text(value: object, name: str) -> None:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be nonempty text")


def _exact_id(value: object, kind: type, name: str) -> None:
    if type(value) is not kind:
        raise TypeError(f"{name} must be {kind.__name__}")
    value.__post_init__()


def _path(value: object) -> None:
    if (type(value) is not tuple or not value
            or any(type(item) is not int or item < 0 for item in value)):
        raise ValueError("native port path must be a nonempty ordered tuple of indices")


def _port_id(ordinal: int, direction: str, path: tuple[int, ...]) -> str:
    return f"eto:{ordinal}:{direction}:" + "/".join(str(item) for item in path)


def _group_key(provider_reference: str, descriptor_id: str) -> str:
    return sha256((provider_reference + "\0" + descriptor_id).encode("utf-8")).hexdigest()


def _bucket(provider_reference: str, count: int) -> int:
    value = int.from_bytes(sha256(provider_reference.encode("utf-8")).digest()[:8], "big")
    return value % count


@dataclass(frozen=True, slots=True)
class NativeReferencePortOccurrence:
    port_id: str
    instance: OperationInstanceID
    definition: OperationDefinitionID
    source_ordinal: int
    direction: str
    path: tuple[int, ...]
    source_locator: str
    formal_slot: ValueSlotID | None
    formal_status: str
    kind: str
    provider_type: str | None
    provider_reference: str
    descriptor_id: str
    evidence_edge_id: str

    def __post_init__(self) -> None:
        _text(self.port_id, "native port occurrence ID")
        _exact_id(self.instance, OperationInstanceID, "native operation instance")
        _exact_id(self.definition, OperationDefinitionID, "native operation definition")
        if type(self.source_ordinal) is not int or self.source_ordinal < 0:
            raise ValueError("native source ordinal must be nonnegative")
        if self.direction not in ("input", "output"):
            raise ValueError("native reference direction must be input or output")
        _path(self.path)
        expected = "/" + ("inputs" if self.direction == "input" else "outputs") + "/values/" + "/".join(map(str, self.path))
        if self.source_locator != expected or self.port_id != _port_id(self.source_ordinal, self.direction, self.path):
            raise ValueError("native port ID/source locator differs from its exact ordered path")
        if self.formal_slot is not None:
            _exact_id(self.formal_slot, ValueSlotID, "formal schema slot")
        for name in ("formal_status", "kind", "provider_reference", "descriptor_id", "evidence_edge_id"):
            _text(getattr(self, name), name)
        if self.provider_type is not None and type(self.provider_type) is not str:
            raise TypeError("provider type must be text or None")


@dataclass(frozen=True, slots=True)
class NativeReferenceFlow:
    relation: str
    status: EvidenceStatus
    output: NativeReferencePortOccurrence
    input: NativeReferencePortOccurrence
    output_edge: EvidenceEdgeRef
    input_edge: EvidenceEdgeRef
    provider_reference: str
    descriptor_id: str
    ordering_basis: str = "ETO_SOURCE_ORDINAL_ONLY"
    schema_annotation_basis: str = "ORIGINAL_DEFINITION_AND_FORMAL_SLOT_REFERENCES"
    content_identity: str = "NOT_ASSERTED"
    logical_version: None = None
    alias_boundary: str = "UNKNOWN"
    write_boundary: str = "UNKNOWN"
    effects_boundary: str = "UNKNOWN"
    readiness_boundary: str = "UNKNOWN"
    unknowns: tuple[str, ...] = _FLOW_UNKNOWN

    def __post_init__(self) -> None:
        if self.relation != "reference_flow_candidate" or self.status is not EvidenceStatus.INFERRED:
            raise ValueError("same-token recurrence must remain an inferred reference-flow candidate")
        if (type(self.output) is not NativeReferencePortOccurrence
                or type(self.input) is not NativeReferencePortOccurrence):
            raise TypeError("reference flow endpoints must be original native port occurrences")
        self.output.__post_init__()
        self.input.__post_init__()
        if (self.output.direction != "output" or self.input.direction != "input"
                or self.output.source_ordinal >= self.input.source_ordinal):
            raise ValueError("reference flow must point from an earlier output to a later input")
        if ((self.output.provider_reference, self.output.descriptor_id)
                != (self.input.provider_reference, self.input.descriptor_id)
                or self.provider_reference != self.output.provider_reference
                or self.descriptor_id != self.output.descriptor_id):
            raise ValueError("reference-flow endpoints must reuse one exact provider token/descriptor")
        if type(self.output_edge) is not EvidenceEdgeRef or type(self.input_edge) is not EvidenceEdgeRef:
            raise TypeError("reference flow must point to the original input/output EvidenceEdges")
        self.output_edge.__post_init__()
        self.input_edge.__post_init__()
        if (self.output_edge.edge != self.output.evidence_edge_id
                or self.input_edge.edge != self.input.evidence_edge_id):
            raise ValueError("reference-flow edge refs differ from original endpoint EvidenceEdge IDs")
        if (self.content_identity != "NOT_ASSERTED" or self.logical_version is not None
                or self.ordering_basis != "ETO_SOURCE_ORDINAL_ONLY"
                or self.schema_annotation_basis != "ORIGINAL_DEFINITION_AND_FORMAL_SLOT_REFERENCES"
                or self.alias_boundary != "UNKNOWN" or self.write_boundary != "UNKNOWN"
                or self.effects_boundary != "UNKNOWN" or self.readiness_boundary != "UNKNOWN"
                or self.unknowns != _FLOW_UNKNOWN):
            raise ValueError("reference-flow relation may not assert contents, writes, aliases, effects, or readiness")


@dataclass(frozen=True, slots=True)
class NativeReferenceFlowShardRef:
    bucket: int
    path: str
    stored_sha256: str
    stored_bytes: int
    decoded_sha256: str
    decoded_bytes: int
    groups: int
    input_ports: int
    output_ports: int

    def __post_init__(self) -> None:
        if type(self.bucket) is not int or self.bucket < 0:
            raise ValueError("bucket must be nonnegative")
        if type(self.path) is not str or not self.path or Path(self.path).is_absolute() or ".." in Path(self.path).parts:
            raise ValueError("flow shard path must be relative")
        for name in ("stored_sha256", "decoded_sha256"):
            digest = getattr(self, name)
            if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(f"{name} must be lowercase SHA-256")
        for name in ("stored_bytes", "decoded_bytes", "groups", "input_ports", "output_ports"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a nonnegative exact integer")
        if self.stored_bytes <= 0 or self.decoded_bytes <= 0:
            raise ValueError("published flow shard must be nonempty")


@dataclass(frozen=True, slots=True)
class NativeReferenceFlowIndex:
    native_port_index: ProviderArtifact
    evidence_bundle_manifest: ProviderArtifact
    eto_source: ProviderArtifact
    bucket_count: int
    source_nodes: int
    operation_rows: int
    native_ports: int
    reference_ports: int
    input_reference_ports: int
    output_reference_ports: int
    ports_with_one_original_edge: int
    ports_without_one_original_edge: int
    evidence_edge_rows_scanned: int
    indexed_reference_edge_rows: int
    groups_with_input_and_output: int
    shards: tuple[NativeReferenceFlowShardRef, ...]

    def __post_init__(self) -> None:
        for value in (self.native_port_index, self.evidence_bundle_manifest, self.eto_source):
            if type(value) is not ProviderArtifact:
                raise TypeError("reference-flow index source references must be ProviderArtifact")
            value.__post_init__()
        if type(self.bucket_count) is not int or self.bucket_count <= 0:
            raise ValueError("bucket count must be positive")
        for name in ("source_nodes", "operation_rows", "native_ports", "reference_ports",
                     "input_reference_ports", "output_reference_ports", "ports_with_one_original_edge",
                     "ports_without_one_original_edge", "evidence_edge_rows_scanned",
                     "indexed_reference_edge_rows", "groups_with_input_and_output"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a nonnegative exact integer")
        if type(self.shards) is not tuple or any(type(item) is not NativeReferenceFlowShardRef for item in self.shards):
            raise TypeError("reference-flow shards must be typed shard references")
        buckets = [item.bucket for item in self.shards]
        if len(set(buckets)) != len(buckets) or any(bucket >= self.bucket_count for bucket in buckets):
            raise ValueError("flow shard bucket references are duplicate or out of range")
        if self.ports_with_one_original_edge + self.ports_without_one_original_edge != self.reference_ports:
            raise ValueError("original edge-resolution counts do not cover every reference port")
        if sum(item.input_ports + item.output_ports for item in self.shards) != self.ports_with_one_original_edge:
            raise ValueError("flow shard endpoint totals differ from original edge matches")


def _compact_port(row: NativeInstancePorts, port: NativeBoxedPort) -> dict[str, Any]:
    return {
        "port_id": _port_id(row.source_ordinal, port.direction, port.path),
        "instance": row.instance.as_dict(),
        "definition": row.definition.as_dict(),
        "source_ordinal": row.source_ordinal,
        "direction": port.direction,
        "path": list(port.path),
        "source_locator": port.source_locator,
        "formal_slot": None if port.formal_slot is None else port.formal_slot.as_dict(),
        "formal_status": port.formal_status,
        "kind": port.kind,
        "provider_type": port.provider_type,
        "provider_reference": port.provider_reference,
        "descriptor_id": port.descriptor_id,
    }


def _endpoint(raw: dict[str, Any], edge_id: str) -> NativeReferencePortOccurrence:
    return decode(NativeReferencePortOccurrence, {
        "port_id": raw["port_id"],
        "instance": raw["instance"],
        "definition": raw["definition"],
        "source_ordinal": raw["source_ordinal"],
        "direction": raw["direction"],
        "path": raw["path"],
        "source_locator": raw["source_locator"],
        "formal_slot": raw["formal_slot"],
        "formal_status": raw["formal_status"],
        "kind": raw["kind"],
        "provider_type": raw["provider_type"],
        "provider_reference": raw["provider_reference"],
        "descriptor_id": raw["descriptor_id"],
        "evidence_edge_id": edge_id,
    })


def _parse_original_edge_reference(record: dict[str, Any], source_sha256: str):
    if (set(record) != {"edge_id", "relation", "source", "target", "evidence"}
            or type(record.get("edge_id")) is not str):
        return None
    relation = record.get("relation")
    direction = _EDGE_RELATIONS.get(relation)
    source, target, evidence = record.get("source"), record.get("target"), record.get("evidence")
    if (direction is None or type(source) is not dict or type(target) is not dict
            or source.get("kind") != "operation_instance"
            or target.get("kind") != "provider_reference"
            or type(evidence) is not dict or type(evidence.get("references")) is not list):
        return None
    source_ref = source.get("reference")
    if type(source_ref) is not dict or type(source_ref.get("wire")) is not str:
        return None
    provider = target.get("reference")
    if type(provider) is not str or not provider:
        return None
    prefix = f"sha256:{source_sha256}#/nodes/"
    for pointer in evidence["references"]:
        if type(pointer) is not str or not pointer.startswith(prefix):
            continue
        tail = pointer[len(prefix):]
        pieces = tail.split("/")
        if len(pieces) < 4 or not pieces[0].isdecimal() or pieces[1] not in ("inputs", "outputs") or pieces[2] != "values":
            continue
        if pieces[1] != direction + "s" or any(not item.isdecimal() for item in pieces[3:]):
            continue
        ordinal = int(pieces[0])
        locator = "/" + "/".join(pieces[1:])
        path = tuple(int(item) for item in pieces[3:])
        return {
            "provider_reference": provider,
            "instance": source_ref["wire"],
            "source_ordinal": ordinal,
            "direction": direction,
            "path": list(path),
            "source_locator": locator,
            "edge_id": record["edge_id"],
        }
    return None


def _write_line(stream, value: dict[str, Any]) -> None:
    stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")


def build_native_reference_flow_publication(
        native_port_publication: str | Path, bundle_partitions: str | Path,
        output_dir: str | Path, *, expected_native_port_index_sha256: str,
        bucket_count: int = _BUCKETS) -> NativeReferenceFlowIndex:
    """Build token/descriptor buckets once from the complete existing port index and evidence table."""
    if type(bucket_count) is not int or bucket_count <= 0 or bucket_count > 1024:
        raise ValueError("bucket count must be in 1..1024")
    port_root = Path(native_port_publication).resolve()
    port_index_path = port_root / "index.json"
    port_index = read_native_port_index(port_index_path, expected_sha256=expected_native_port_index_sha256)
    partitions = BundlePartitions(bundle_partitions)
    if _manifest_identity(partitions) != _identity_from_values(port_index):
        raise ValueError("native port index and evidence bundle manifest differ")
    port_index_payload = port_index_path.read_bytes()
    port_index_artifact = ProviderArtifact(
        str(port_index_path), sha256(port_index_payload).hexdigest(), len(port_index_payload),
        "scar.native-boxed-port-index")
    manifest_receipt = partitions.manifest_receipt
    evidence_manifest = ProviderArtifact(
        manifest_receipt["path"], manifest_receipt["physical_sha256"],
        manifest_receipt["physical_bytes"], partitions.manifest["schema"])
    eto_source = ProviderArtifact(
        port_index.source_uri, port_index.source_sha256, port_index.source_raw_bytes,
        "pytorch.execution-trace.v1")
    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError(f"reference-flow publication needs a fresh directory: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    spool_root = Path(tempfile.mkdtemp(prefix=".native-reference-flow-", dir=output.parent))
    port_paths = [spool_root / f"ports-{bucket:03d}.jsonl" for bucket in range(bucket_count)]
    edge_paths = [spool_root / f"edges-{bucket:03d}.jsonl" for bucket in range(bucket_count)]
    native_ports = reference_ports = reference_inputs = reference_outputs = 0
    edge_records = 0
    evidence_edge_rows_scanned = 0

    try:
        with ExitStack() as stack:
            port_streams = {}
            for shard_ref in port_index.shards:
                shard = _read_shard(port_root, shard_ref)
                for row in shard.rows:
                    native_ports += len(row.ports)
                    for port in row.ports:
                        if port.provider_reference is None or port.descriptor_id is None:
                            continue
                        if port.kind != "TENSOR":
                            continue
                        bucket = _bucket(port.provider_reference, bucket_count)
                        stream = port_streams.get(bucket)
                        if stream is None:
                            stream = stack.enter_context(port_paths[bucket].open("ab"))
                            port_streams[bucket] = stream
                        _write_line(stream, _compact_port(row, port))
                        reference_ports += 1
                        if port.direction == "input":
                            reference_inputs += 1
                        else:
                            reference_outputs += 1

        with ExitStack() as stack:
            edge_streams = {}
            for envelope in partitions.iter_records("evidence", "edges"):
                evidence_edge_rows_scanned += 1
                parsed = _parse_original_edge_reference(envelope["record"], port_index.source_sha256)
                if parsed is None:
                    continue
                bucket = _bucket(parsed["provider_reference"], bucket_count)
                stream = edge_streams.get(bucket)
                if stream is None:
                    stream = stack.enter_context(edge_paths[bucket].open("ab"))
                    edge_streams[bucket] = stream
                _write_line(stream, parsed)
                edge_records += 1

        shard_refs = []
        ports_with_edge = ports_without_edge = groups_total = groups_with_both_total = 0
        for bucket in range(bucket_count):
            if not port_paths[bucket].exists():
                continue
            ports_by_address = {}
            group_ports = {}
            with port_paths[bucket].open("rb") as stream:
                for line in stream:
                    raw = loads(line)
                    address = (raw["provider_reference"], raw["instance"]["wire"], raw["source_ordinal"],
                               raw["direction"], raw["source_locator"])
                    if address in ports_by_address:
                        raise ValueError("duplicate native port endpoint in one provider bucket")
                    ports_by_address[address] = raw
                    key = _group_key(raw["provider_reference"], raw["descriptor_id"])
                    group_ports.setdefault(key, {"provider_reference": raw["provider_reference"],
                                                  "descriptor_id": raw["descriptor_id"],
                                                  "inputs": [], "outputs": []})[
                        "inputs" if raw["direction"] == "input" else "outputs"].append(raw)

            edge_by_address = {}
            if edge_paths[bucket].exists():
                with edge_paths[bucket].open("rb") as stream:
                    for line in stream:
                        raw = loads(line)
                        address = (raw["provider_reference"], raw["instance"], raw["source_ordinal"],
                                   raw["direction"], raw["source_locator"])
                        if address in ports_by_address:
                            edge_by_address.setdefault(address, []).append(raw["edge_id"])

            groups = {}
            bucket_inputs = bucket_outputs = 0
            for key, group in group_ports.items():
                for direction in ("inputs", "outputs"):
                    group[direction].sort(key=lambda row: (row["source_ordinal"], row["path"]))
                    cleaned = []
                    for raw in group[direction]:
                        address = (raw["provider_reference"], raw["instance"]["wire"], raw["source_ordinal"],
                                   raw["direction"], raw["source_locator"])
                        edge_ids = edge_by_address.get(address, ())
                        if len(edge_ids) == 1:
                            raw["evidence_edge_id"] = edge_ids[0]
                            ports_with_edge += 1
                            cleaned.append(raw)
                        else:
                            ports_without_edge += 1
                    group[direction] = cleaned
                if not group["inputs"] or not group["outputs"]:
                    # Keep one-sided observations too: they are useful for finding
                    # original occurrences, but cannot produce an adjacency candidate.
                    groups[key] = group
                    bucket_inputs += len(group["inputs"])
                    bucket_outputs += len(group["outputs"])
                    continue
                bucket_inputs += len(group["inputs"])
                bucket_outputs += len(group["outputs"])
                groups_with_both_total += 1
                groups[key] = group
            if not groups:
                continue
            groups_total += len(groups)
            document = {"schema": _SHARD_SCHEMA, "schema_version": _SHARD_VERSION,
                        "bucket": bucket, "groups": groups}
            decoded = json.dumps(document, sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=True).encode("utf-8") + b"\n"
            if len(decoded) > _MAX_SHARD_BYTES:
                raise ValueError("one native reference bucket exceeds the fixed 64MB shard bound")
            stored = gzip.compress(decoded, compresslevel=6, mtime=0)
            relative = f"shards/reference-{bucket:03d}.json.gz"
            shard_path = output / relative
            shard_path.parent.mkdir(parents=True, exist_ok=True)
            with shard_path.open("xb") as stream:
                stream.write(stored)
            shard_refs.append(NativeReferenceFlowShardRef(
                bucket, relative, sha256(stored).hexdigest(), len(stored),
                sha256(decoded).hexdigest(), len(decoded), len(groups),
                bucket_inputs, bucket_outputs))
        if ports_with_edge + ports_without_edge != reference_ports:
            raise ValueError("reference-port edge resolution summary does not cover every selected port")
        if reference_ports and not ports_with_edge:
            raise ValueError("no provider-reference port resolved to an original EvidenceEdge")
        flow_index = NativeReferenceFlowIndex(
            port_index_artifact, evidence_manifest, eto_source, bucket_count,
            port_index.source_nodes, port_index.operation_rows, native_ports,
            reference_ports, reference_inputs, reference_outputs,
            ports_with_edge, ports_without_edge, evidence_edge_rows_scanned,
            edge_records, groups_with_both_total,
            tuple(sorted(shard_refs, key=lambda item: item.bucket)))
        payload = json.dumps({"schema": _INDEX_SCHEMA, "schema_version": _VERSION,
                              "value": encode(flow_index)}, sort_keys=True,
                             separators=(",", ":"), ensure_ascii=True).encode("utf-8") + b"\n"
        if len(payload) > _MAX_INDEX_BYTES:
            raise ValueError("native reference-flow index exceeds its fixed 8MB limit")
        with (output / "index.json").open("xb") as stream:
            stream.write(payload)
        return flow_index
    finally:
        import shutil
        shutil.rmtree(spool_root, ignore_errors=True)


def read_native_reference_flow_index(publication: str | Path, *,
                                     expected_sha256: str | None = None
                                     ) -> tuple[NativeReferenceFlowIndex, str]:
    root = Path(publication).resolve()
    index_path = root / "index.json"
    if not index_path.is_file() or index_path.is_symlink():
        raise ValueError("reference-flow index must be a retained regular file")
    raw = index_path.read_bytes()
    if len(raw) > _MAX_INDEX_BYTES:
        raise ValueError("native reference-flow index exceeds its fixed byte limit")
    digest = sha256(raw).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("native reference-flow index SHA-256 mismatch")
    document = loads(raw)
    if (type(document) is not dict or set(document) != {"schema", "schema_version", "value"}
            or document["schema"] != _INDEX_SCHEMA or type(document["schema_version"]) is not int
            or document["schema_version"] != _VERSION):
        raise ValueError("unsupported native reference-flow index schema/version")
    index = decode(NativeReferenceFlowIndex, document["value"])
    if tuple(item.bucket for item in index.shards) != tuple(sorted(item.bucket for item in index.shards)):
        raise ValueError("native reference-flow shard references are not ordered")
    return index, digest


def _read_flow_shard(root: Path, reference: NativeReferenceFlowShardRef) -> dict[str, Any]:
    path = root / reference.path
    if not path.is_file() or path.is_symlink():
        raise ValueError("reference-flow shard is missing or not a regular file")
    stored = path.read_bytes()
    if len(stored) != reference.stored_bytes or sha256(stored).hexdigest() != reference.stored_sha256:
        raise ValueError("reference-flow shard stored receipt mismatch")
    with gzip.GzipFile(fileobj=__import__("io").BytesIO(stored), mode="rb") as stream:
        decoded = stream.read(_MAX_SHARD_BYTES + 1)
    if (len(decoded) != reference.decoded_bytes or len(decoded) > _MAX_SHARD_BYTES
            or sha256(decoded).hexdigest() != reference.decoded_sha256):
        raise ValueError("reference-flow shard decoded receipt mismatch")
    document = loads(decoded)
    if (type(document) is not dict or set(document) != {"schema", "schema_version", "bucket", "groups"}
            or document["schema"] != _SHARD_SCHEMA or document["schema_version"] != _SHARD_VERSION
            or document["bucket"] != reference.bucket or type(document["groups"]) is not dict):
        raise ValueError("reference-flow shard schema/header mismatch")
    if len(document["groups"]) != reference.groups:
        raise ValueError("reference-flow shard group count mismatch")
    return document


def query_native_reference_flow_upstream(
        publication: str | Path, native_port_publication: str | Path,
        bundle_partitions: str | Path, consumer_instance: OperationInstance,
        consumer_path: tuple[int, ...], *,
        expected_flow_index_sha256: str | None = None,
        expected_native_port_index_sha256: str | None = None,
        max_candidates: int = _MAX_QUERY_CANDIDATES
        ) -> tuple[NativeReferenceFlow, ...]:
    """Query one original operation input through a single provider-reference bucket."""
    _path(consumer_path)
    if type(max_candidates) is not int or max_candidates < 1 or max_candidates > 4096:
        raise ValueError("max_candidates must be a bounded exact integer in 1..4096")
    if type(consumer_instance) is not OperationInstance:
        raise TypeError("reference-flow query starts from an original OperationInstance")
    index, _ = read_native_reference_flow_index(
        publication, expected_sha256=expected_flow_index_sha256)
    port_index_path = Path(native_port_publication).resolve() / "index.json"
    if str(port_index_path) != index.native_port_index.uri:
        raise ValueError("query native port publication differs from the reference-flow index source")
    if (expected_native_port_index_sha256 is not None
            and expected_native_port_index_sha256 != index.native_port_index.sha256):
        raise ValueError("query native port index SHA differs from the flow index source")
    port_row = query_native_ports(
        consumer_instance, native_port_publication, bundle_partitions,
        expected_index_sha256=index.native_port_index.sha256)
    consumers = [port for port in port_row.ports if port.direction == "input" and port.path == consumer_path]
    if len(consumers) != 1:
        raise KeyError("original operation has no unique native input at this ordered path")
    consumer = consumers[0]
    if consumer.provider_reference is None or consumer.descriptor_id is None or consumer.kind != "TENSOR":
        return ()
    bucket = _bucket(consumer.provider_reference, index.bucket_count)
    references = [item for item in index.shards if item.bucket == bucket]
    if not references:
        return ()
    root = Path(publication).resolve()
    shard = _read_flow_shard(root, references[0])
    group = shard["groups"].get(_group_key(consumer.provider_reference, consumer.descriptor_id))
    if group is None:
        return ()
    if (group.get("provider_reference") != consumer.provider_reference
            or group.get("descriptor_id") != consumer.descriptor_id):
        raise ValueError("provider/descriptor group digest collision or corruption")

    def matches(raw):
        return (raw.get("instance", {}).get("wire") == port_row.instance.wire
                and raw.get("source_ordinal") == port_row.source_ordinal
                and raw.get("direction") == "input"
                and raw.get("path") == list(consumer.path)
                and raw.get("source_locator") == consumer.source_locator)

    selected = [raw for raw in group["inputs"] if matches(raw)]
    if len(selected) != 1:
        raise ValueError("consumer input does not resolve to one stored original endpoint")
    if selected[0].get("definition", {}).get("wire") != port_row.definition.wire:
        raise ValueError("stored consumer endpoint definition differs from the original port row")
    endpoint_artifact = index.evidence_bundle_manifest
    input_ref = _endpoint(selected[0], selected[0]["evidence_edge_id"])
    flows = []
    possible_outputs = [raw for raw in group["outputs"]
                        if raw.get("source_ordinal", -1) < port_row.source_ordinal]
    if len(possible_outputs) > max_candidates:
        raise ValueError(f"{len(possible_outputs)} reference candidates exceed query bound {max_candidates}")
    for raw in possible_outputs:
        output_ref = _endpoint(raw, raw["evidence_edge_id"])
        flows.append(NativeReferenceFlow(
            "reference_flow_candidate", EvidenceStatus.INFERRED,
            output_ref, input_ref,
            EvidenceEdgeRef(endpoint_artifact, output_ref.evidence_edge_id),
            EvidenceEdgeRef(endpoint_artifact, input_ref.evidence_edge_id),
            consumer.provider_reference, consumer.descriptor_id))
    return tuple(flows)


__all__ = [
    "NativeReferencePortOccurrence", "NativeReferenceFlow",
    "NativeReferenceFlowShardRef", "NativeReferenceFlowIndex",
    "build_native_reference_flow_publication", "read_native_reference_flow_index",
    "query_native_reference_flow_upstream",
]
