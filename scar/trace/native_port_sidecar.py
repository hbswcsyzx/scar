"""Ordered boxed ports attached to existing native OperationInstance IDs."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import gzip
import json
from pathlib import Path
from typing import Any

from scar.ir.record_codec import decode, encode, loads
from scar.ir.v2.evidence import OperationInstance, ProviderReference
from scar.ir.v2.ids import OperationDefinitionID, OperationInstanceID, ValueSlotID
from scar.ir.v2.semantic import OperationDefinition, ValueSlot
from scar.store.bundle_partitions import BundlePartitions


_SCHEMA = "scar.native-boxed-port-fragment"
_VERSION = 1
_MAX_RAW_BYTES = 600_000_000
_MAX_STORED_BYTES = 64_000_000
_MAX_NODE_BYTES = 4_000_000


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
        if type(self.source_locator) is not str or not self.source_locator.startswith("/"):
            raise ValueError("port source locator must be relative to its original ETO node")
        group = "inputs" if self.direction == "input" else "outputs"
        expected_locator = "/" + group + "/values/" + "/".join(str(n) for n in self.path)
        if self.source_locator != expected_locator:
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
            raise TypeError("port row must reuse existing operation/definition IDs")
        if type(self.source_ordinal) is not int or self.source_ordinal < 0:
            raise ValueError("invalid original ETO node ordinal")
        if type(self.ports) is not tuple or any(type(p) is not NativeBoxedPort for p in self.ports):
            raise TypeError("ports must be a tuple of NativeBoxedPort records")
        if len({(p.direction, p.path) for p in self.ports}) != len(self.ports):
            raise ValueError("duplicate ordered direction/path port")


@dataclass(frozen=True, slots=True)
class NativePortFragment:
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
        if type(self.source_uri) is not str or not self.source_uri:
            raise ValueError("shared ETO source reference is required")
        for digest in (self.source_sha256, self.source_stored_sha256, self.evidence_manifest_sha256):
            if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("fragment source/catalog references require lowercase SHA-256")
        if any(type(n) is not int or n <= 0 for n in
               (self.source_raw_bytes, self.source_stored_bytes, self.evidence_manifest_schema_version,
                self.evidence_bundle_schema_version, self.evidence_graph_schema_version)):
            raise ValueError("fragment source and evidence versions/sizes must be positive integers")
        if (type(self.first_source_ordinal) is not int or type(self.stop_source_ordinal) is not int
                or self.first_source_ordinal < 0 or self.stop_source_ordinal <= self.first_source_ordinal):
            raise ValueError("invalid original source range")
        if type(self.rows) is not tuple or any(type(r) is not NativeInstancePorts for r in self.rows):
            raise TypeError("fragment rows must be NativeInstancePorts")
        if len({r.instance for r in self.rows}) != len(self.rows):
            raise ValueError("duplicate existing OperationInstance reference")
        if any(not self.first_source_ordinal <= row.source_ordinal < self.stop_source_ordinal for row in self.rows):
            raise ValueError("fragment row lies outside its original source range")


class _DecodedHashReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = sha256()
        self.size = 0

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


def _typed_id(expected, value):
    if type(value) is not dict or set(value) != {"kind", "value", "wire"}:
        raise ValueError("invalid existing typed identity")
    result = expected(value["value"])
    if value["kind"] != result.prefix or value["wire"] != result.wire:
        raise ValueError("existing identifier namespace/wire mismatch")
    return result


def _read_source_receipt(eto_path: Path, archive_index_path: Path, expected_archive_sha256: str):
    if not archive_index_path.is_file() or archive_index_path.is_symlink():
        raise ValueError("retained archive index is missing or not a regular file")
    if archive_index_path.stat().st_size > 4_000_000:
        raise ValueError("retained archive index exceeds bounded metadata budget")
    if not eto_path.is_file() or eto_path.is_symlink():
        raise ValueError("retained ETO gzip is missing or not a regular file")
    archive_bytes = archive_index_path.read_bytes()
    if type(expected_archive_sha256) is not str or len(expected_archive_sha256) != 64:
        raise ValueError("expected archive-index SHA-256 is malformed")
    if sha256(archive_bytes).hexdigest() != expected_archive_sha256:
        raise ValueError("retained archive index differs from capture-coordinates receipt")
    archive = loads(archive_bytes.decode("utf-8"))
    if (type(archive) is not dict or archive.get("schema") != "scar.lossless-capture-archive"
            or archive.get("verified_roundtrip") is not True or type(archive.get("files")) is not list):
        raise ValueError("retained archive lacks its lossless roundtrip receipt")
    resolved = eto_path.resolve()
    matches = [row for row in archive["files"] if type(row) is dict
               and type(row.get("actual_path")) is str
               and Path(row["actual_path"]).resolve() == resolved]
    if len(matches) != 1:
        raise ValueError("ETO path has no unique retained archive receipt")
    receipt = matches[0]
    required = ("logical_path", "raw_sha256", "raw_bytes", "gzip_sha256", "compressed_bytes")
    if any(key not in receipt for key in required):
        raise ValueError("ETO archive receipt is incomplete")
    if type(receipt["raw_sha256"]) is not str or type(receipt["gzip_sha256"]) is not str:
        raise ValueError("ETO archive receipt lacks source hashes")
    if any(type(receipt[key]) is not int or receipt[key] <= 0 for key in ("raw_bytes", "compressed_bytes")):
        raise ValueError("ETO archive receipt lacks exact byte counts")
    if receipt["raw_bytes"] > _MAX_RAW_BYTES or receipt["compressed_bytes"] > _MAX_STORED_BYTES:
        raise ValueError("ETO source exceeds bounded sidecar hash budget")

    stored_hash, stored_bytes = sha256(), 0
    with resolved.open("rb") as stream:
        while True:
            part = stream.read(1_048_576)
            if not part:
                break
            stored_hash.update(part)
            stored_bytes += len(part)
            if stored_bytes > _MAX_STORED_BYTES:
                raise ValueError("stored ETO source exceeds bounded hash budget")
    if (stored_bytes != receipt["compressed_bytes"] or stored_hash.hexdigest() != receipt["gzip_sha256"]):
        raise ValueError("retained ETO stored bytes differ from original receipt")
    return receipt, stored_hash.hexdigest(), stored_bytes


def _selected_nodes(eto_path: Path, stop: int, receipt: dict) -> tuple[list[dict], str, int]:
    # Use the existing bounded incremental JSON tokenizer; all decompressed
    # bytes pass through a hashing reader, while only nodes[0:stop] are parsed.
    from scar.trace.native_capture_batch import _JSONStream

    try:
        stream = gzip.open(eto_path, "rb")
    except OSError as error:
        raise ValueError("retained ETO gzip cannot be opened") from error
    with stream:
        reader = _DecodedHashReader(stream)
        parser = _JSONStream(reader, _MAX_NODE_BYTES)
        parser.take("{")
        nodes = None
        while parser.peek() not in ("", "}"):
            key = parser.value()
            if type(key) is not str:
                raise ValueError("ETO top-level keys must be text")
            parser.take(":")
            if key == "nodes":
                parser.take("[")
                selected = []
                for ordinal in range(stop):
                    if ordinal:
                        parser.take(",")
                    node = parser.value()
                    if type(node) is not dict:
                        raise ValueError("selected ETO node must be an object")
                    selected.append(node)
                nodes = selected
                break
            parser.value()
            if parser.peek() == ",":
                parser.take(",")
            elif parser.peek() != "}":
                raise ValueError("malformed ETO top-level object")
        if nodes is None:
            raise ValueError("ETO nodes array is missing")
        decoded_sha256, decoded_bytes = reader.finish()
    if decoded_bytes != receipt["raw_bytes"] or decoded_sha256 != receipt["raw_sha256"]:
        raise ValueError("retained ETO decoded bytes differ from original receipt")
    return nodes, decoded_sha256, decoded_bytes


def _definitions(partitions: BundlePartitions, wanted: set[OperationDefinitionID]) -> dict[OperationDefinitionID, OperationDefinition]:
    found: dict[OperationDefinitionID, OperationDefinition] = {}
    for envelope in partitions.iter_records("semantic", "definitions"):
        record = envelope["record"]
        identifier = _typed_id(OperationDefinitionID, record.get("id"))
        if identifier in wanted:
            found[identifier] = decode(OperationDefinition, record)
            if found.keys() >= wanted:
                break
    if found.keys() != wanted:
        raise ValueError("original semantic definition table lacks a selected ETO definition")
    return found


def _provider_references(partitions: BundlePartitions, wanted: set[str]) -> dict[str, ProviderReference]:
    found: dict[str, ProviderReference] = {}
    for envelope in partitions.iter_records("evidence", "provider_references"):
        record = envelope["record"]
        identifier = record.get("reference_id")
        if identifier in wanted:
            found[identifier] = decode(ProviderReference, record)
            if found.keys() >= wanted:
                break
    if found.keys() != wanted:
        raise ValueError("original provider-reference table lacks a selected tensor token")
    return found


def _value_slots(partitions: BundlePartitions, wanted: dict[ValueSlotID, tuple[OperationDefinitionID, str]]) -> None:
    found: set[ValueSlotID] = set()
    for envelope in partitions.iter_records("semantic", "slots"):
        record = envelope["record"]
        identifier = _typed_id(ValueSlotID, record.get("slot_id"))
        expected = wanted.get(identifier)
        if expected is None:
            continue
        slot = decode(ValueSlot, record)
        if (slot.slot_id != identifier or slot.owner != expected[0] or slot.direction != expected[1]):
            raise ValueError("existing formal ValueSlot owner/direction differs from its port reference")
        found.add(identifier)
        if found == wanted.keys():
            break
    if found != wanted.keys():
        raise ValueError("existing formal ValueSlot reference is absent from the semantic table")


def _tree_ports(node: dict, role: str) -> tuple[str, tuple[tuple[tuple[int, ...], str | None, str], ...]]:
    record = node.get(role)
    if record is None:
        return "ABSENT", ()
    if type(record) is not dict or type(record.get("values")) is not list or type(record.get("types")) is not list:
        return "MALFORMED", ()
    values, types = record["values"], record["types"]
    if len(values) != len(types):
        return "PARTIAL", ()
    from scar.trace.native_import import _element_types

    result: list[tuple[tuple[int, ...], str | None, str]] = []

    def emit(path, provider_type, kind):
        result.append((tuple(path), provider_type, kind))

    def descend(value, provider_type, path, depth=0):
        if depth > 64:
            raise ValueError("ETO boxed value nesting exceeds bound")
        if type(provider_type) is not str:
            emit(path, None, "UNKNOWN")
            return
        children = _element_types(provider_type)
        if children is not None:
            if type(value) is not list:
                emit(path, provider_type, "CONTAINER")
                return
            if len(children) == 1:
                children *= len(value)
            if len(children) != len(value):
                emit(path, provider_type, "CONTAINER")
                return
            if not value:
                emit(path, provider_type, "EMPTY_CONTAINER")
                return
            for index, (child, child_type) in enumerate(zip(value, children)):
                descend(child, child_type, (*path, index), depth + 1)
            return
        tensor = provider_type == "Tensor" or provider_type.startswith("Tensor(")
        if tensor and (type(value) is not list or len(value) != 6):
            raise ValueError("observed Tensor port lacks the pinned six-field ETO descriptor")
        emit(path, provider_type, "TENSOR" if tensor else "SCALAR_OR_OPAQUE")

    for index, (value, provider_type) in enumerate(zip(values, types)):
        descend(value, provider_type, (index,))
    return "COMPLETE", tuple(result)


def _port_rows(instance: OperationInstance, definition: OperationDefinition, node: dict):
    schema = definition.metadata.get("op_schema")
    has_schema = type(schema) is str and bool(schema)
    rows, statuses = [], {}
    for role, direction in (("inputs", "input"), ("outputs", "output")):
        status, observed = _tree_ports(node, role)
        statuses[role] = status
        for path, provider_type, kind in observed:
            matches = [slot for slot in instance.metadata.get("tensor_slots", ())
                       if slot.get("role") == role and slot.get("ordered_path") == list(path)]
            if len(matches) > 1:
                raise ValueError("original evidence has ambiguous tensor references for one ETO path")
            provider_reference = descriptor_id = None
            formal_slot = None
            if kind == "TENSOR":
                if not matches:
                    formal_status = "UNRESOLVED_TENSOR_DESCRIPTOR"
                else:
                    slot = matches[0]
                    provider_reference, descriptor_id = slot["provider_reference"], slot["descriptor_id"]
                    binding = slot.get("native_schema_binding")
                    if type(binding) is dict and type(binding.get("formal_slot")) is dict:
                        formal_slot = _typed_id(ValueSlotID, binding["formal_slot"])
                        declared = definition.output_slots if direction == "output" else definition.input_slots
                        if formal_slot not in declared:
                            raise ValueError("existing tensor schema binding is not owned by its definition interface")
                        formal_status = binding.get("status", "EXISTING_BINDING_STATUS_UNAVAILABLE")
                    else:
                        formal_status = "UNRESOLVED_EXISTING_SCHEMA_BINDING"
            else:
                if matches:
                    raise ValueError("ETO type/path disagrees with existing tensor-slot evidence")
                formal_status = ("UNRESOLVED_NON_TENSOR_FORMAL_PATH" if has_schema
                                 else "NO_REGISTERED_SCHEMA")
            pointer = "/" + role + "/values/" + "/".join(str(part) for part in path)
            rows.append(NativeBoxedPort(direction, path, provider_type, kind, pointer, formal_slot,
                                        formal_status, provider_reference, descriptor_id))
    return statuses["inputs"], statuses["outputs"], tuple(rows)


def _manifest_identity(partitions: BundlePartitions) -> tuple[str, int, int, int]:
    manifest = partitions.manifest
    evidence = manifest["graphs"]["evidence"]
    return (partitions.manifest_receipt["physical_sha256"], manifest["schema_version"],
            manifest["bundle"]["schema_version"], evidence["schema_version"])


def build_port_fragment(eto_path: str | Path, archive_index_path: str | Path,
                        expected_archive_sha256: str, bundle_partitions: str | Path, *,
                        first: int = 0, stop: int = 128) -> NativePortFragment:
    """Hash the retained source fully, parse only the requested original ETO node range."""
    if type(first) is not int or type(stop) is not int or first < 0 or stop <= first or stop > 128:
        raise ValueError("bounded sidecar accepts a nonempty range within original ordinals 0..127")
    eto_path = Path(eto_path).resolve()
    receipt, stored_sha256, stored_bytes = _read_source_receipt(
        eto_path, Path(archive_index_path).resolve(), expected_archive_sha256)
    all_nodes, decoded_sha256, decoded_bytes = _selected_nodes(eto_path, stop, receipt)
    partitions = BundlePartitions(bundle_partitions)
    identities = _manifest_identity(partitions)
    original_records = partitions.selected_records("evidence", "instances", tuple(range(first, stop)))
    definitions_by_id = {_typed_id(OperationDefinitionID, row["record"].get("definition"))
                         for row in original_records}
    definitions = _definitions(partitions, definitions_by_id)
    rows = []
    for ordinal, envelope in zip(range(first, stop), original_records):
        node = all_nodes[ordinal]
        record = envelope["record"]
        instance = decode(OperationInstance, record)
        raw_reference = instance.metadata.get("raw_reference")
        expected_reference = "sha256:" + decoded_sha256 + "#/nodes/" + str(ordinal)
        if raw_reference != expected_reference:
            raise ValueError("original instance source hash/ordinal differs from retained ETO node")
        if node.get("id") != instance.metadata.get("node_id") or node.get("ctrl_deps") != instance.metadata.get("ctrl_deps"):
            raise ValueError("original ETO node identity/parent differs from retained OperationInstance")
        definition = definitions[instance.definition]
        if node.get("name") != definition.label:
            raise ValueError("original ETO node name differs from its existing semantic definition")
        category = instance.metadata.get("category")
        schema_text = definition.metadata.get("op_schema")
        # Provider category and schema availability remain independent axes.
        # User annotations stay in original evidence and are never port rows.
        if category == "user_annotation":
            continue
        if category != "cpu_op" and not (type(schema_text) is str and bool(schema_text)):
            continue
        input_status, output_status, ports = _port_rows(instance, definition, node)
        rows.append(NativeInstancePorts(instance.id, instance.definition, ordinal,
                                        input_status, output_status, ports))
    referenced = {port.provider_reference for row in rows for port in row.ports
                  if port.provider_reference is not None}
    if referenced:
        providers = _provider_references(partitions, referenced)
        for row in rows:
            for port in row.ports:
                if port.provider_reference is None:
                    continue
                descriptors = [item for item in providers[port.provider_reference].metadata.get("descriptors", ())
                               if item.get("descriptor_id") == port.descriptor_id]
                if len(descriptors) != 1 or descriptors[0].get("type") != port.provider_type:
                    raise ValueError("ETO tensor path/type differs from its existing provider descriptor")
    formal_slots = {}
    for row in rows:
        for port in row.ports:
            if port.formal_slot is None:
                continue
            expected = (row.definition, port.direction)
            if port.formal_slot in formal_slots and formal_slots[port.formal_slot] != expected:
                raise ValueError("one formal ValueSlot reference has conflicting operation owners")
            formal_slots[port.formal_slot] = expected
    if formal_slots:
        _value_slots(partitions, formal_slots)
    return NativePortFragment(receipt["logical_path"], decoded_sha256, stored_sha256,
        decoded_bytes, stored_bytes, identities[0], identities[1], identities[2], identities[3],
        first, stop, tuple(rows))


def encode_fragment(fragment: NativePortFragment) -> bytes:
    if type(fragment) is not NativePortFragment:
        raise TypeError("expected NativePortFragment")
    return json.dumps({"schema": _SCHEMA, "schema_version": _VERSION, "value": encode(fragment)},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def decode_fragment(payload: bytes | str) -> NativePortFragment:
    document = loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
    if (type(document) is not dict or set(document) != {"schema", "schema_version", "value"}
            or document["schema"] != _SCHEMA or document["schema_version"] != _VERSION):
        raise ValueError("unsupported native boxed-port fragment codec envelope")
    return decode(NativePortFragment, document["value"])


def ports_for_instance(instance: OperationInstance, fragment: NativePortFragment,
                       bundle_partitions: str | Path) -> NativeInstancePorts:
    """Query from an original instance after checking its source ordinal and bundle manifest."""
    if type(instance) is not OperationInstance or type(fragment) is not NativePortFragment:
        raise TypeError("query requires an existing OperationInstance and NativePortFragment")
    partitions = BundlePartitions(bundle_partitions)
    if _manifest_identity(partitions) != (fragment.evidence_manifest_sha256,
            fragment.evidence_manifest_schema_version, fragment.evidence_bundle_schema_version,
            fragment.evidence_graph_schema_version):
        raise ValueError("query bundle manifest/version differs from this port fragment")
    prefix = "sha256:" + fragment.source_sha256 + "#/nodes/"
    raw_reference = instance.metadata.get("raw_reference")
    if type(raw_reference) is not str or not raw_reference.startswith(prefix):
        raise ValueError("query instance does not reference this fragment's original ETO source")
    suffix = raw_reference[len(prefix):]
    if not suffix.isdecimal():
        raise ValueError("query instance raw locator has no exact original node ordinal")
    ordinal = int(suffix)
    if not fragment.first_source_ordinal <= ordinal < fragment.stop_source_ordinal:
        raise ValueError("query instance source ordinal is outside this fragment")
    original = partitions.selected_records("evidence", "instances", (ordinal,))[0]["record"]
    imported = decode(OperationInstance, original)
    if imported != instance:
        raise ValueError("query instance differs from its original retained evidence record")
    matches = [row for row in fragment.rows if row.source_ordinal == ordinal and row.instance == instance.id]
    if len(matches) != 1 or matches[0].definition != instance.definition:
        raise KeyError("existing operation has no matching boxed-port row")
    return matches[0]


__all__ = ["NativeBoxedPort", "NativeInstancePorts", "NativePortFragment", "build_port_fragment",
           "decode_fragment", "encode_fragment", "ports_for_instance"]
