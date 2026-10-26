"""Stream original ETO boxed ports into indexed shards referencing the evidence bundle."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import gzip
import io
import json
from pathlib import Path

from scar.ir.record_codec import decode, encode, loads
from scar.ir.v2.evidence import OperationInstance
from scar.ir.v2.ids import OperationDefinitionID, OperationInstanceID, ValueSlotID
from scar.store.bundle_partitions import BundlePartitions


_FRAGMENT_SCHEMA = "scar.native-boxed-port-fragment"
_SHARD_SCHEMA = "scar.native-boxed-port-shard"
_INDEX_SCHEMA = "scar.native-boxed-port-index"
_VERSION = 1
_SHARD_VERSION = 1
_INDEX_VERSION = 2
_MAX_RAW_BYTES = 600_000_000
_MAX_STORED_BYTES = 64_000_000
_MAX_NODE_BYTES = 4_000_000
_MAX_SHARD_BYTES = 64_000_000


@dataclass(frozen=True, slots=True)
class NativeBoxedPort:
    direction: str
    path: tuple[int, ...]
    provider_type: str | None
    kind: str
    source_locator: str
    formal_slot: ValueSlotID | None
    formal_status: str
    provider_reference: str | None = None
    descriptor_id: str | None = None

    def __post_init__(self) -> None:
        if self.direction not in ("input", "output"):
            raise ValueError("port direction must be input or output")
        if type(self.path) is not tuple or not self.path or any(type(n) is not int or n < 0 for n in self.path):
            raise ValueError("port path must be a nonempty ordered integer tuple")
        if self.provider_type is not None and type(self.provider_type) is not str:
            raise TypeError("provider type must be text or None")
        if type(self.kind) is not str or not self.kind or type(self.formal_status) is not str:
            raise ValueError("port kind and formal status are required")
        group = "inputs" if self.direction == "input" else "outputs"
        expected = "/" + group + "/values/" + "/".join(str(n) for n in self.path)
        if self.source_locator != expected:
            raise ValueError("port path/source locator disagree")
        if self.formal_slot is not None and not isinstance(self.formal_slot, ValueSlotID):
            raise TypeError("formal slot must be an existing ValueSlot ID")
        if self.provider_reference is None and self.descriptor_id is not None:
            raise ValueError("descriptor ID needs an existing provider reference")


@dataclass(frozen=True, slots=True)
class NativeInstancePorts:
    instance: OperationInstanceID
    definition: OperationDefinitionID
    source_ordinal: int
    input_status: str
    output_status: str
    ports: tuple[NativeBoxedPort, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.instance, OperationInstanceID) or not isinstance(self.definition, OperationDefinitionID):
            raise TypeError("port row must reuse original operation/definition IDs")
        if type(self.source_ordinal) is not int or self.source_ordinal < 0:
            raise ValueError("invalid original ETO node ordinal")
        if type(self.ports) is not tuple or any(type(port) is not NativeBoxedPort for port in self.ports):
            raise TypeError("ports must be a tuple of NativeBoxedPort records")
        if len({(port.direction, port.path) for port in self.ports}) != len(self.ports):
            raise ValueError("duplicate ordered direction/path port")


@dataclass(frozen=True, slots=True)
class NativePortFragment:
    """Standalone arbitrary range convenience; full builds use shared-index shards below."""
    source_uri: str
    source_sha256: str
    source_stored_sha256: str
    source_raw_bytes: int
    source_stored_bytes: int
    evidence_manifest_sha256: str
    evidence_manifest_schema_version: int
    evidence_bundle_schema_version: int
    evidence_graph_schema_version: int
    first_source_ordinal: int
    stop_source_ordinal: int
    rows: tuple[NativeInstancePorts, ...]

    def __post_init__(self) -> None:
        _digest(self.source_sha256, "source SHA")
        _digest(self.source_stored_sha256, "stored source SHA")
        _digest(self.evidence_manifest_sha256, "evidence manifest SHA")
        if type(self.source_uri) is not str or not self.source_uri:
            raise ValueError("source URI is required")
        if any(type(n) is not int or n <= 0 for n in (self.source_raw_bytes, self.source_stored_bytes,
                self.evidence_manifest_schema_version, self.evidence_bundle_schema_version,
                self.evidence_graph_schema_version)):
            raise ValueError("fragment sizes and versions must be positive integers")
        if type(self.first_source_ordinal) is not int or type(self.stop_source_ordinal) is not int or not (
                0 <= self.first_source_ordinal < self.stop_source_ordinal):
            raise ValueError("invalid source ordinal range")
        if type(self.rows) is not tuple or any(type(row) is not NativeInstancePorts for row in self.rows):
            raise TypeError("fragment rows must be NativeInstancePorts")
        if any(not self.first_source_ordinal <= row.source_ordinal < self.stop_source_ordinal for row in self.rows):
            raise ValueError("fragment row is outside its source range")


@dataclass(frozen=True, slots=True)
class NativePortShard:
    first_source_ordinal: int
    stop_source_ordinal: int
    rows: tuple[NativeInstancePorts, ...]

    def __post_init__(self) -> None:
        if type(self.first_source_ordinal) is not int or type(self.stop_source_ordinal) is not int or not (
                0 <= self.first_source_ordinal < self.stop_source_ordinal):
            raise ValueError("invalid shard source range")
        if type(self.rows) is not tuple or any(type(row) is not NativeInstancePorts for row in self.rows):
            raise TypeError("shard rows must be NativeInstancePorts")
        if len({row.instance for row in self.rows}) != len(self.rows):
            raise ValueError("shard repeats an existing operation instance")
        if any(not self.first_source_ordinal <= row.source_ordinal < self.stop_source_ordinal for row in self.rows):
            raise ValueError("shard row is outside its source range")


@dataclass(frozen=True, slots=True)
class NativePortShardReference:
    path: str
    compression: str
    stored_sha256: str
    stored_bytes: int
    decoded_sha256: str
    decoded_bytes: int
    first_source_ordinal: int
    stop_source_ordinal: int
    operation_rows: int
    ports: int

    def __post_init__(self) -> None:
        _digest(self.stored_sha256, "stored shard SHA")
        _digest(self.decoded_sha256, "decoded shard SHA")
        if self.compression != "gzip":
            raise ValueError("shard compression must be deterministic gzip")
        if type(self.path) is not str or not self.path or self.path.startswith("/") or ".." in Path(self.path).parts:
            raise ValueError("shard path must be relative to its publication")
        if any(type(n) is not int or n < 0 for n in
               (self.stored_bytes, self.decoded_bytes, self.first_source_ordinal,
                self.stop_source_ordinal, self.operation_rows, self.ports)):
            raise ValueError("shard counters must be nonnegative exact integers")
        if (self.stored_bytes <= 0 or self.decoded_bytes <= 0
                or self.stop_source_ordinal <= self.first_source_ordinal):
            raise ValueError("shard range must be nonempty")


@dataclass(frozen=True, slots=True)
class NativePortIndex:
    source_uri: str
    source_sha256: str
    source_stored_sha256: str
    source_raw_bytes: int
    source_stored_bytes: int
    evidence_manifest_sha256: str
    evidence_manifest_schema_version: int
    evidence_bundle_schema_version: int
    evidence_graph_schema_version: int
    first_source_ordinal: int
    stop_source_ordinal: int
    source_nodes: int
    operation_rows: int
    input_ports: int
    output_ports: int
    classification_counts: dict[str, int]
    shards: tuple[NativePortShardReference, ...]

    def __post_init__(self) -> None:
        for digest, label in ((self.source_sha256, "source SHA"),
                              (self.source_stored_sha256, "stored source SHA"),
                              (self.evidence_manifest_sha256, "evidence manifest SHA")):
            _digest(digest, label)
        if type(self.source_uri) is not str or not self.source_uri:
            raise ValueError("shared source URI is required")
        if any(type(n) is not int or n <= 0 for n in (self.source_raw_bytes, self.source_stored_bytes,
                self.evidence_manifest_schema_version, self.evidence_bundle_schema_version,
                self.evidence_graph_schema_version, self.source_nodes)):
            raise ValueError("source sizes, versions and node count must be positive exact integers")
        if (type(self.first_source_ordinal) is not int or type(self.stop_source_ordinal) is not int
                or self.first_source_ordinal < 0 or self.stop_source_ordinal <= self.first_source_ordinal
                or self.stop_source_ordinal > self.source_nodes):
            raise ValueError("invalid published source range")
        if any(type(n) is not int or n < 0 for n in (self.operation_rows, self.input_ports, self.output_ports)):
            raise ValueError("port index counters must be nonnegative exact integers")
        if type(self.classification_counts) is not dict or any(type(k) is not str or type(v) is not int or v < 0
                                                               for k, v in self.classification_counts.items()):
            raise ValueError("classification summary is malformed")
        if type(self.shards) is not tuple or any(type(item) is not NativePortShardReference for item in self.shards):
            raise TypeError("index shards must be NativePortShardReference")
        cursor = self.first_source_ordinal
        for shard in self.shards:
            if shard.first_source_ordinal != cursor:
                raise ValueError("shard ranges must cover the indexed range contiguously")
            cursor = shard.stop_source_ordinal
        if cursor != self.stop_source_ordinal:
            raise ValueError("shards do not cover the published source range")
        if sum(shard.operation_rows for shard in self.shards) != self.operation_rows:
            raise ValueError("shard operation counts do not rebuild the index")
        if sum(shard.ports for shard in self.shards) != self.input_ports + self.output_ports:
            raise ValueError("shard port counts do not rebuild the index")


@dataclass(frozen=True, slots=True)
class _DefinitionInfo:
    label: str
    schema_present: bool
    input_slots: frozenset[ValueSlotID]
    output_slots: frozenset[ValueSlotID]


class _DecodedHashReader:
    def __init__(self, stream):
        self.stream, self.digest, self.size = stream, sha256(), 0

    def read(self, size: int) -> bytes:
        data = self.stream.read(size)
        self.size += len(data)
        if self.size > _MAX_RAW_BYTES:
            raise ValueError("decoded ETO source exceeds bounded hash budget")
        self.digest.update(data)
        return data

    def finish(self) -> tuple[str, int]:
        while self.read(1_048_576):
            pass
        return self.digest.hexdigest(), self.size


def _digest(value: str, label: str) -> None:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(label + " must be lowercase SHA-256")


def _typed_id(expected, value):
    if type(value) is not dict or set(value) != {"kind", "value", "wire"}:
        raise ValueError("invalid existing typed identity")
    result = expected(value["value"])
    if value["kind"] != result.prefix or value["wire"] != result.wire:
        raise ValueError("existing identifier namespace/wire mismatch")
    return result


def _read_source_receipt(eto_path: Path, archive_index_path: Path, expected_archive_sha256: str):
    if not archive_index_path.is_file() or archive_index_path.is_symlink() or archive_index_path.stat().st_size > 4_000_000:
        raise ValueError("retained archive index is missing, unsafe, or exceeds metadata budget")
    if not eto_path.is_file() or eto_path.is_symlink():
        raise ValueError("retained ETO source is missing or unsafe")
    archive_bytes = archive_index_path.read_bytes()
    _digest(expected_archive_sha256, "expected archive-index SHA")
    if sha256(archive_bytes).hexdigest() != expected_archive_sha256:
        raise ValueError("retained archive index differs from its capture-coordinates reference")
    archive = loads(archive_bytes.decode("utf-8"))
    if (type(archive) is not dict or archive.get("schema") != "scar.lossless-capture-archive"
            or archive.get("verified_roundtrip") is not True or type(archive.get("files")) is not list):
        raise ValueError("archive lacks a verified roundtrip receipt")
    source_path = eto_path.resolve()
    matches = [item for item in archive["files"] if type(item) is dict and type(item.get("actual_path")) is str
               and Path(item["actual_path"]).resolve() == source_path]
    if len(matches) != 1:
        raise ValueError("ETO path has no unique original archive receipt")
    receipt = matches[0]
    required = ("logical_path", "raw_sha256", "raw_bytes", "gzip_sha256", "compressed_bytes")
    if any(key not in receipt for key in required):
        raise ValueError("ETO archive receipt is incomplete")
    _digest(receipt["raw_sha256"], "raw ETO SHA")
    _digest(receipt["gzip_sha256"], "stored ETO SHA")
    if any(type(receipt[key]) is not int or receipt[key] <= 0 for key in ("raw_bytes", "compressed_bytes")):
        raise ValueError("ETO archive receipt lacks exact byte counts")
    if receipt["raw_bytes"] > _MAX_RAW_BYTES or receipt["compressed_bytes"] > _MAX_STORED_BYTES:
        raise ValueError("ETO source exceeds bounded byte budget")
    digest, size = sha256(), 0
    with source_path.open("rb") as stream:
        for part in iter(lambda: stream.read(1_048_576), b""):
            digest.update(part)
            size += len(part)
            if size > _MAX_STORED_BYTES:
                raise ValueError("stored ETO source exceeds bounded hash budget")
    if size != receipt["compressed_bytes"] or digest.hexdigest() != receipt["gzip_sha256"]:
        raise ValueError("stored ETO source differs from its archive receipt")
    return receipt, digest.hexdigest(), size


def _walk_eto_nodes(eto_path: Path, receipt: dict, on_node) -> tuple[int, str, int]:
    from scar.trace.native_capture_batch import _JSONStream

    with gzip.open(eto_path, "rb") as raw_stream:
        reader = _DecodedHashReader(raw_stream)
        parser = _JSONStream(reader, _MAX_NODE_BYTES)
        parser.take("{")
        found_nodes = False
        node_count = 0
        while parser.peek() not in ("", "}"):
            key = parser.value()
            if type(key) is not str:
                raise ValueError("ETO object key is not text")
            parser.take(":")
            if key != "nodes":
                parser.value()
                if parser.peek() == ",":
                    parser.take(",")
                elif parser.peek() != "}":
                    raise ValueError("malformed ETO top-level object")
                continue
            found_nodes = True
            parser.take("[")
            while parser.peek() != "]":
                if node_count:
                    parser.take(",")
                node = parser.value()
                if type(node) is not dict:
                    raise ValueError("ETO node is not an object")
                on_node(node_count, node)
                node_count += 1
            parser.take("]")
            break
        if not found_nodes:
            raise ValueError("ETO nodes array is absent")
        decoded_sha256, decoded_bytes = reader.finish()
    if decoded_sha256 != receipt["raw_sha256"] or decoded_bytes != receipt["raw_bytes"]:
        raise ValueError("complete decoded ETO hash/size differs from the archive receipt")
    return node_count, decoded_sha256, decoded_bytes


def _definition_info(record: dict) -> tuple[OperationDefinitionID, _DefinitionInfo]:
    identifier = _typed_id(OperationDefinitionID, record.get("id"))
    label, metadata = record.get("label"), record.get("metadata", {})
    if type(label) is not str or type(metadata) is not dict:
        raise ValueError("original semantic definition is malformed")
    schema = metadata.get("op_schema")
    if schema is not None and type(schema) is not str:
        raise ValueError("original definition schema text is malformed")
    inputs, outputs = record.get("input_slots", ()), record.get("output_slots", ())
    if type(inputs) is not list or type(outputs) is not list:
        raise ValueError("original definition interface is malformed")
    info = _DefinitionInfo(label, bool(schema),
        frozenset(_typed_id(ValueSlotID, item) for item in inputs),
        frozenset(_typed_id(ValueSlotID, item) for item in outputs))
    return identifier, info


def _definitions(partitions: BundlePartitions, wanted: set[OperationDefinitionID] | None) -> dict[OperationDefinitionID, _DefinitionInfo]:
    found: dict[OperationDefinitionID, _DefinitionInfo] = {}
    for envelope in partitions.iter_records("semantic", "definitions"):
        identifier, info = _definition_info(envelope["record"])
        if wanted is None or identifier in wanted:
            found[identifier] = info
        if wanted is not None and found.keys() >= wanted:
            break
    if wanted is not None and found.keys() != wanted:
        raise ValueError("original semantic definition table lacks an ETO definition")
    return found


def _tree_ports(node: dict, role: str):
    record = node.get(role)
    if record is None:
        return "ABSENT", ()
    if type(record) is not dict or type(record.get("values")) is not list or type(record.get("types")) is not list:
        return "MALFORMED", ()
    values, types = record["values"], record["types"]
    status = "COMPLETE" if len(values) == len(types) else "PARTIAL"
    from scar.trace.native_import import _element_types

    result = []

    def descend(value, provider_type, path, depth=0):
        if depth > 64:
            raise ValueError("ETO boxed value nesting exceeds depth bound")
        if type(provider_type) is not str:
            result.append((tuple(path), None, "UNKNOWN", None))
            return
        children = _element_types(provider_type)
        if children is not None:
            if type(value) is not list:
                result.append((tuple(path), provider_type, "CONTAINER", None))
                return
            if len(children) == 1:
                children *= len(value)
            if len(children) != len(value):
                result.append((tuple(path), provider_type, "CONTAINER", None))
                return
            if not value:
                result.append((tuple(path), provider_type, "EMPTY_CONTAINER", None))
                return
            for index, (child, child_type) in enumerate(zip(value, children)):
                descend(child, child_type, (*path, index), depth + 1)
            return
        tensor = provider_type == "Tensor" or provider_type.startswith("Tensor(")
        token = None
        if tensor:
            if (type(value) is not list or len(value) != 6 or any(type(part) is not int or part < 0 for part in value[:5])
                    or type(value[5]) is not str or not value[5]):
                raise ValueError("Tensor leaf lacks the original six-field ETO descriptor")
            token = value[0]
        result.append((tuple(path), provider_type, "TENSOR" if tensor else "SCALAR_OR_OPAQUE", token))

    for index, value in enumerate(values):
        provider_type = types[index] if index < len(types) else None
        descend(value, provider_type, (index,))
    return status, tuple(result)


def _port_rows(instance: OperationInstance, definition: _DefinitionInfo, node: dict,
               provider_expectations: dict[str, dict[str, str]],
               slot_expectations: dict[ValueSlotID, tuple[OperationDefinitionID, str]]):
    rows, statuses = [], {}
    for role, direction in (("inputs", "input"), ("outputs", "output")):
        status, observed = _tree_ports(node, role)
        statuses[role] = status
        for path, provider_type, kind, tensor_token in observed:
            matches = [slot for slot in instance.metadata.get("tensor_slots", ())
                       if slot.get("role") == role and slot.get("ordered_path") == list(path)]
            if len(matches) > 1:
                raise ValueError("original instance has ambiguous Tensor references at one ETO path")
            provider_reference = descriptor_id = None
            formal_slot = None
            if kind == "TENSOR":
                if not matches:
                    formal_status = "UNRESOLVED_TENSOR_DESCRIPTOR"
                else:
                    slot = matches[0]
                    provider_reference, descriptor_id = slot.get("provider_reference"), slot.get("descriptor_id")
                    if type(provider_reference) is not str or type(descriptor_id) is not str:
                        raise ValueError("existing Tensor slot lacks its provider/descriptor reference")
                    if ":eto:" not in instance.id.value:
                        raise ValueError("ETO instance ID does not expose its provider scope")
                    expected_ref = instance.id.value.rsplit(":eto:", 1)[0] + ":tensor-token:" + str(tensor_token)
                    if provider_reference != expected_ref:
                        raise ValueError("ETO Tensor tuple token differs from its original ProviderReference")
                    binding = slot.get("native_schema_binding")
                    if type(binding) is dict and type(binding.get("formal_slot")) is dict:
                        formal_slot = _typed_id(ValueSlotID, binding["formal_slot"])
                        declared = definition.output_slots if direction == "output" else definition.input_slots
                        if formal_slot not in declared:
                            raise ValueError("existing formal slot is outside its original definition interface")
                        expected = (instance.definition, direction)
                        if formal_slot in slot_expectations and slot_expectations[formal_slot] != expected:
                            raise ValueError("formal ValueSlot reference has conflicting definition owners")
                        slot_expectations[formal_slot] = expected
                        formal_status = binding.get("status", "EXISTING_BINDING_STATUS_UNAVAILABLE")
                    else:
                        formal_status = "UNRESOLVED_EXISTING_SCHEMA_BINDING"
                    refs = provider_expectations.setdefault(provider_reference, {})
                    prior = refs.get(descriptor_id)
                    if prior is not None and prior != provider_type:
                        raise ValueError("one original Tensor descriptor has conflicting observed types")
                    refs[descriptor_id] = provider_type
            else:
                if matches:
                    raise ValueError("ETO non-Tensor path conflicts with an existing Tensor slot")
                formal_status = ("UNRESOLVED_NON_TENSOR_FORMAL_PATH" if definition.schema_present
                                 else "NO_REGISTERED_SCHEMA")
            pointer = "/" + role + "/values/" + "/".join(str(part) for part in path)
            rows.append(NativeBoxedPort(direction, path, provider_type, kind, pointer,
                                        formal_slot, formal_status, provider_reference, descriptor_id))
    return statuses["inputs"], statuses["outputs"], tuple(rows)


def _manifest_identity(partitions: BundlePartitions) -> tuple[str, int, int, int]:
    manifest = partitions.manifest
    return (partitions.manifest_receipt["physical_sha256"], manifest["schema_version"],
            manifest["bundle"]["schema_version"], manifest["graphs"]["evidence"]["schema_version"])


def _identity_from_values(index: NativePortIndex) -> tuple[str, int, int, int]:
    return (index.evidence_manifest_sha256, index.evidence_manifest_schema_version,
            index.evidence_bundle_schema_version, index.evidence_graph_schema_version)


def _validate_provider_references(partitions: BundlePartitions, expected: dict[str, dict[str, str]]) -> None:
    pending = {reference: dict(descriptors) for reference, descriptors in expected.items()}
    for envelope in partitions.iter_records("evidence", "provider_references"):
        record = envelope["record"]
        reference = record.get("reference_id")
        wanted = pending.get(reference)
        if wanted is None:
            continue
        descriptors = record.get("metadata", {}).get("descriptors", ())
        for descriptor in descriptors:
            descriptor_id = descriptor.get("descriptor_id")
            if descriptor_id not in wanted:
                continue
            if descriptor.get("type") != wanted[descriptor_id]:
                raise ValueError("ETO Tensor path/type differs from its original provider descriptor")
            del wanted[descriptor_id]
        if not wanted:
            del pending[reference]
        if not pending:
            break
    if pending:
        raise ValueError("original ProviderReference table lacks a port descriptor")


def _validate_value_slots(partitions: BundlePartitions,
                          expected: dict[ValueSlotID, tuple[OperationDefinitionID, str]]) -> None:
    pending = dict(expected)
    for envelope in partitions.iter_records("semantic", "slots"):
        record = envelope["record"]
        identifier = _typed_id(ValueSlotID, record.get("slot_id"))
        wanted = pending.get(identifier)
        if wanted is None:
            continue
        owner = _typed_id(OperationDefinitionID, record.get("owner")) if record.get("owner") is not None else None
        if owner != wanted[0] or record.get("direction") != wanted[1]:
            raise ValueError("existing semantic ValueSlot owner/direction differs from a port reference")
        del pending[identifier]
        if not pending:
            break
    if pending:
        raise ValueError("original semantic table lacks a formal ValueSlot reference")


def _encode_document(schema: str, value, *, version: int = _VERSION) -> bytes:
    return json.dumps({"schema": schema, "schema_version": version, "value": encode(value)},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _decode_document(payload: bytes, schema: str, expected, *, version: int = _VERSION):
    document = loads(payload.decode("utf-8"))
    if (type(document) is not dict or set(document) != {"schema", "schema_version", "value"}
            or document["schema"] != schema or document["schema_version"] != version):
        raise ValueError("unsupported native port codec envelope")
    return decode(expected, document["value"])


def _publish_new(path: Path, payload: bytes) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
    return sha256(payload).hexdigest(), len(payload)


def _gzip_bytes(payload: bytes) -> bytes:
    stream = io.BytesIO()
    with gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0, compresslevel=6) as compressed:
        compressed.write(payload)
    return stream.getvalue()


def _write_shard(root: Path, first: int, stop: int, rows: tuple[NativeInstancePorts, ...]) -> NativePortShardReference:
    shard = NativePortShard(first, stop, rows)
    decoded = _encode_document(_SHARD_SCHEMA, shard, version=_SHARD_VERSION)
    if len(decoded) > _MAX_SHARD_BYTES:
        raise ValueError("one fixed source-range shard exceeds the 64MB output bound")
    payload = _gzip_bytes(decoded)
    filename = f"shards/nodes-{first:09d}-{stop:09d}.json.gz"
    stored_sha256, stored_bytes = _publish_new(root / filename, payload)
    return NativePortShardReference(filename, "gzip", stored_sha256, stored_bytes,
                                    sha256(decoded).hexdigest(), len(decoded), first, stop, len(rows),
                                    sum(len(row.ports) for row in rows))


def _build_rows_for_node(ordinal: int, node: dict, evidence_iter, definitions,
                         source_sha256: str, provider_expectations, slot_expectations):
    try:
        envelope = next(evidence_iter)
    except StopIteration as error:
        raise ValueError("original ETO source has more nodes than its evidence instance table") from error
    if envelope["ordinal"] != ordinal:
        raise ValueError("ETO source ordinal differs from its existing evidence record ordinal")
    instance = decode(OperationInstance, envelope["record"])
    metadata = instance.metadata
    if metadata.get("provider") != "ETO":
        raise ValueError("an extra synthetic/evidence instance was interleaved into original ETO ordinals")
    if metadata.get("raw_reference") != f"sha256:{source_sha256}#/nodes/{ordinal}":
        raise ValueError("existing instance rawRef differs from original ETO source SHA/ordinal")
    if node.get("id") != metadata.get("node_id") or node.get("ctrl_deps") != metadata.get("ctrl_deps"):
        raise ValueError("original ETO node ID/parent differs from its OperationInstance")
    definition = definitions.get(instance.definition)
    if definition is None or node.get("name") != definition.label:
        raise ValueError("original ETO node does not resolve to its existing semantic definition")
    category = metadata.get("category")
    if category == "user_annotation":
        return None, "USER_ANNOTATION", 0, 0
    if category != "cpu_op" and not definition.schema_present:
        return None, "UNKNOWN_NATIVE_BOUNDARY", 0, 0
    input_status, output_status, ports = _port_rows(instance, definition, node,
        provider_expectations, slot_expectations)
    return (NativeInstancePorts(instance.id, instance.definition, ordinal, input_status, output_status, ports),
            "REGISTERED_SCHEMA_OPERATION" if definition.schema_present else "UNSCHEMATIZED_CPU_OPERATION",
            sum(port.direction == "input" for port in ports), sum(port.direction == "output" for port in ports))


def build_native_port_publication(eto_path: str | Path, archive_index_path: str | Path,
                                  expected_archive_sha256: str, bundle_partitions: str | Path,
                                  output_dir: str | Path, *, shard_size: int = 4096,
                                  first: int = 0, stop: int | None = None) -> NativePortIndex:
    """Parse every original ETO node once; publish the requested range as fixed-size shards."""
    if (type(shard_size) is not int or shard_size <= 0 or type(first) is not int or first < 0
            or (stop is not None and (type(stop) is not int or stop <= first))):
        raise ValueError("invalid source range or fixed shard size")
    source_path = Path(eto_path).resolve()
    receipt, source_stored_sha256, source_stored_bytes = _read_source_receipt(
        source_path, Path(archive_index_path).resolve(), expected_archive_sha256)
    partitions = BundlePartitions(bundle_partitions)
    evidence_identity = _manifest_identity(partitions)
    output = Path(output_dir).resolve()
    if output.exists():
        raise ValueError("native port publication needs a fresh directory")
    output.mkdir(parents=True)
    (output / "shards").mkdir()

    definitions = _definitions(partitions, None)
    evidence_iter = partitions.iter_records("evidence", "instances")
    provider_expectations: dict[str, dict[str, str]] = {}
    slot_expectations: dict[ValueSlotID, tuple[OperationDefinitionID, str]] = {}
    shard_refs, current_rows = [], []
    classifications, input_ports, output_ports, operation_rows = Counter(), 0, 0, 0
    current_first = first

    def on_node(ordinal, node):
        nonlocal current_first, input_ports, output_ports, operation_rows
        row, classification, inputs, outputs = _build_rows_for_node(
            ordinal, node, evidence_iter, definitions, receipt["raw_sha256"],
            provider_expectations, slot_expectations)
        if not first <= ordinal or (stop is not None and ordinal >= stop):
            return
        classifications[classification] += 1
        if row is not None:
            current_rows.append(row)
            operation_rows += 1
            input_ports += inputs
            output_ports += outputs
        if ordinal + 1 - current_first >= shard_size:
            shard_refs.append(_write_shard(output, current_first, ordinal + 1, tuple(current_rows)))
            current_rows.clear()
            current_first = ordinal + 1

    source_nodes, decoded_sha256, decoded_bytes = _walk_eto_nodes(source_path, receipt, on_node)
    if stop is not None and source_nodes < stop:
        raise ValueError("requested source range ends after the actual ETO nodes array")
    selected_stop = source_nodes if stop is None else stop
    if selected_stop <= first:
        raise ValueError("selected source range is empty")
    if current_first < selected_stop:
        shard_refs.append(_write_shard(output, current_first, selected_stop, tuple(current_rows)))
    evidence_iter.close()

    _validate_provider_references(partitions, provider_expectations)
    _validate_value_slots(partitions, slot_expectations)
    index = NativePortIndex(receipt["logical_path"], decoded_sha256, source_stored_sha256,
        decoded_bytes, source_stored_bytes, evidence_identity[0], evidence_identity[1],
        evidence_identity[2], evidence_identity[3], first, selected_stop, source_nodes,
        operation_rows, input_ports, output_ports, dict(sorted(classifications.items())), tuple(shard_refs))
    _publish_new(output / "index.json", _encode_document(_INDEX_SCHEMA, index, version=_INDEX_VERSION))
    return index


def read_native_port_index(path: str | Path, *, expected_sha256: str | None = None) -> NativePortIndex:
    root = Path(path)
    index_path = root / "index.json" if root.is_dir() else root
    if not index_path.is_file() or index_path.is_symlink() or index_path.stat().st_size > 16_000_000:
        raise ValueError("native port index is absent, unsafe, or exceeds its bound")
    payload = index_path.read_bytes()
    if expected_sha256 is not None:
        _digest(expected_sha256, "expected index SHA")
        if sha256(payload).hexdigest() != expected_sha256:
            raise ValueError("native port index differs from its expected SHA")
    return _decode_document(payload, _INDEX_SCHEMA, NativePortIndex, version=_INDEX_VERSION)


def _read_shard(root: Path, reference: NativePortShardReference) -> NativePortShard:
    path = root
    relative = Path(reference.path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("shard path escapes its publication")
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("shard path traverses a symlink")
    if not path.is_file() or path.stat().st_size != reference.stored_bytes:
        raise ValueError("published port shard is missing or has changed size")
    payload = path.read_bytes()
    if sha256(payload).hexdigest() != reference.stored_sha256:
        raise ValueError("published stored port shard digest changed")
    if reference.decoded_bytes > _MAX_SHARD_BYTES:
        raise ValueError("published decoded port shard exceeds its bounded read budget")
    with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as compressed:
        decoded = compressed.read(_MAX_SHARD_BYTES + 1)
        if len(decoded) > _MAX_SHARD_BYTES or compressed.read(1):
            raise ValueError("published compressed port shard exceeds its decoded bound")
    if (len(decoded) != reference.decoded_bytes
            or sha256(decoded).hexdigest() != reference.decoded_sha256):
        raise ValueError("published decoded port shard receipt mismatch")
    shard = _decode_document(decoded, _SHARD_SCHEMA, NativePortShard, version=_SHARD_VERSION)
    if (shard.first_source_ordinal, shard.stop_source_ordinal, len(shard.rows)) != (
            reference.first_source_ordinal, reference.stop_source_ordinal, reference.operation_rows):
        raise ValueError("published shard content differs from its shared index reference")
    if sum(len(row.ports) for row in shard.rows) != reference.ports:
        raise ValueError("published shard port count differs from its shared index reference")
    return shard


def query_native_ports(instance: OperationInstance, publication: str | Path,
                       bundle_partitions: str | Path, *,
                       expected_index_sha256: str | None = None) -> NativeInstancePorts:
    """Query through an original instance ID and verify source ordinal plus bundle identity."""
    if type(instance) is not OperationInstance:
        raise TypeError("query starts from an existing OperationInstance")
    root = Path(publication).resolve()
    index = read_native_port_index(root, expected_sha256=expected_index_sha256)
    partitions = BundlePartitions(bundle_partitions)
    if _manifest_identity(partitions) != _identity_from_values(index):
        raise ValueError("query bundle manifest/schema versions differ from the port index")
    prefix = "sha256:" + index.source_sha256 + "#/nodes/"
    raw_reference = instance.metadata.get("raw_reference")
    if type(raw_reference) is not str or not raw_reference.startswith(prefix):
        raise ValueError("query instance does not reference the indexed original ETO source")
    suffix = raw_reference[len(prefix):]
    if not suffix.isdecimal():
        raise ValueError("query rawRef lacks an exact ETO node ordinal")
    ordinal = int(suffix)
    if not index.first_source_ordinal <= ordinal < index.stop_source_ordinal:
        raise ValueError("query instance source ordinal is outside the indexed range")
    original = partitions.selected_records("evidence", "instances", (ordinal,))[0]["record"]
    if decode(OperationInstance, original) != instance:
        raise ValueError("query instance differs from the full original evidence record")
    refs = [ref for ref in index.shards if ref.first_source_ordinal <= ordinal < ref.stop_source_ordinal]
    if len(refs) != 1:
        raise ValueError("source ordinal is not covered by exactly one shard")
    shard = _read_shard(root, refs[0])
    rows = [row for row in shard.rows if row.source_ordinal == ordinal and row.instance == instance.id]
    if len(rows) != 1 or rows[0].definition != instance.definition:
        raise KeyError("existing operation has no port row in its source-range shard")
    return rows[0]


# Arbitrary small range API retained for focused diagnostics. Full production
# coverage uses build_native_port_publication so source/definition/ref tables
# are read once rather than once per fragment.
def build_port_fragment(eto_path: str | Path, archive_index_path: str | Path,
                        expected_archive_sha256: str, bundle_partitions: str | Path, *,
                        first: int = 0, stop: int = 128) -> NativePortFragment:
    if type(first) is not int or type(stop) is not int or first < 0 or stop <= first:
        raise ValueError("invalid original ETO source range")
    source_path = Path(eto_path).resolve()
    receipt, stored_sha, stored_bytes = _read_source_receipt(
        source_path, Path(archive_index_path).resolve(), expected_archive_sha256)
    partitions = BundlePartitions(bundle_partitions)
    identity = _manifest_identity(partitions)
    # The range helper remains useful for small diagnostics; default to all source
    # ordinals and select originals lazily as nodes arrive, without a 128-row cap.
    source_record_count = partitions.manifest["graphs"]["evidence"]["tables"]["instances"]["records"]
    selected_stop = stop
    if selected_stop > source_record_count:
        raise ValueError("requested source range exceeds the original evidence instance table")
    original_records = partitions.selected_records("evidence", "instances", tuple(range(first, selected_stop)))
    wanted = {_typed_id(OperationDefinitionID, row["record"]["definition"]) for row in original_records}
    definitions = _definitions(partitions, wanted)
    provider_expectations, slot_expectations = {}, {}
    rows = []

    def on_node(ordinal, node):
        if ordinal < first or ordinal >= stop:
            return
        record = original_records[ordinal - first]["record"]
        instance = decode(OperationInstance, record)
        if instance.metadata.get("raw_reference") != f"sha256:{receipt['raw_sha256']}#/nodes/{ordinal}":
            raise ValueError("original instance source SHA/ordinal differs from ETO")
        if node.get("id") != instance.metadata.get("node_id") or node.get("ctrl_deps") != instance.metadata.get("ctrl_deps"):
            raise ValueError("original ETO node differs from its existing instance")
        definition = definitions[instance.definition]
        if node.get("name") != definition.label:
            raise ValueError("original ETO node name differs from its semantic definition")
        category = instance.metadata.get("category")
        if category == "user_annotation" or (category != "cpu_op" and not definition.schema_present):
            return
        input_status, output_status, ports = _port_rows(instance, definition, node,
            provider_expectations, slot_expectations)
        rows.append(NativeInstancePorts(instance.id, instance.definition, ordinal,
                                         input_status, output_status, ports))

    node_count, raw_sha, raw_bytes = _walk_eto_nodes(source_path, receipt, on_node)
    if selected_stop > node_count:
        raise ValueError("requested range exceeds the original ETO nodes array")
    _validate_provider_references(partitions, provider_expectations)
    _validate_value_slots(partitions, slot_expectations)
    return NativePortFragment(receipt["logical_path"], raw_sha, stored_sha, raw_bytes, stored_bytes,
        identity[0], identity[1], identity[2], identity[3], first, selected_stop, tuple(rows))


def encode_fragment(fragment: NativePortFragment) -> bytes:
    if type(fragment) is not NativePortFragment:
        raise TypeError("expected NativePortFragment")
    return _encode_document(_FRAGMENT_SCHEMA, fragment)


def decode_fragment(payload: bytes | str) -> NativePortFragment:
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    return _decode_document(raw, _FRAGMENT_SCHEMA, NativePortFragment)


def ports_for_instance(instance: OperationInstance, fragment: NativePortFragment,
                       bundle_partitions: str | Path) -> NativeInstancePorts:
    if type(instance) is not OperationInstance or type(fragment) is not NativePortFragment:
        raise TypeError("range query requires an existing OperationInstance and NativePortFragment")
    partitions = BundlePartitions(bundle_partitions)
    expected_identity = (fragment.evidence_manifest_sha256, fragment.evidence_manifest_schema_version,
                         fragment.evidence_bundle_schema_version, fragment.evidence_graph_schema_version)
    if _manifest_identity(partitions) != expected_identity:
        raise ValueError("query bundle manifest/version differs from range fragment")
    raw_ref = instance.metadata.get("raw_reference")
    prefix = "sha256:" + fragment.source_sha256 + "#/nodes/"
    if type(raw_ref) is not str or not raw_ref.startswith(prefix) or not raw_ref[len(prefix):].isdecimal():
        raise ValueError("query instance lacks the fragment's exact source ordinal")
    ordinal = int(raw_ref[len(prefix):])
    if not fragment.first_source_ordinal <= ordinal < fragment.stop_source_ordinal:
        raise ValueError("query instance source ordinal is outside the fragment")
    original = partitions.selected_records("evidence", "instances", (ordinal,))[0]["record"]
    if decode(OperationInstance, original) != instance:
        raise ValueError("query instance differs from its full original evidence record")
    rows = [row for row in fragment.rows if row.source_ordinal == ordinal and row.instance == instance.id]
    if len(rows) != 1 or rows[0].definition != instance.definition:
        raise KeyError("instance has no port row in the range fragment")
    return rows[0]


__all__ = ["NativeBoxedPort", "NativeInstancePorts", "NativePortFragment", "NativePortShard",
           "NativePortShardReference", "NativePortIndex", "build_port_fragment",
           "build_native_port_publication", "read_native_port_index", "query_native_ports",
           "decode_fragment", "encode_fragment", "ports_for_instance"]
