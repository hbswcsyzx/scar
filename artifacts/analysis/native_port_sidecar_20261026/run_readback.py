"""Rebuild and query the retained ETO node range 0..127."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKSPACE))

from scar.ir.record_codec import decode
from scar.ir.v2.evidence import OperationInstance, ProviderReference
from scar.ir.v2.ids import OperationDefinitionID, ValueSlotID
from scar.ir.v2.semantic import OperationDefinition, ValueSlot
from scar.store.bundle_partitions import BundlePartitions
from scar.trace.native_port_sidecar import (
    build_port_fragment, decode_fragment, encode_fragment, ports_for_instance,
)


MAIN = WORKSPACE.parent / "structured-program-model"
CAPTURE = MAIN / "artifacts/experiments/lewm_joint_capture_20261026/capture"
NATIVE = MAIN / "artifacts/experiments/native_inputs_full_20261026/native-import/native"
# Exact seed.archive_sha256 from the retained native-input capture-coordinates record.
ARCHIVE_INDEX_SHA256 = "2bb588b34bdca5838f14d470b14830b15b5f344785c638df62cbb6c168df88c8"
NODE_FIRST, NODE_STOP = 0, 128


def _typed(expected, raw):
    value = expected(raw["value"])
    if raw.get("kind") != value.prefix or raw.get("wire") != value.wire:
        raise ValueError("existing typed ID wire differs")
    return value


def _lookup(partitions, graph, table, key, wanted):
    for row in partitions.iter_records(graph, table):
        record = row["record"]
        if record.get(key) == wanted:
            return record
    raise ValueError(f"existing {graph}.{table} reference is missing: {wanted}")


def run() -> dict:
    output = Path(__file__).resolve().parent
    bundle_path = NATIVE / "bundle-partitions"
    eto_path = CAPTURE / "trace/execution-trace.1578961.adfc0475ed50cb37e1c0453142b5fa65.json.gz"
    fragment = build_port_fragment(eto_path, CAPTURE / "archive-index.json", ARCHIVE_INDEX_SHA256,
                                   bundle_path, first=NODE_FIRST, stop=NODE_STOP)
    fragment_bytes = encode_fragment(fragment)
    decoded = decode_fragment(fragment_bytes)
    fragment_path = output / "native-port-fragment-000000-000128.json"
    fragment_path.write_bytes(fragment_bytes)
    fragment_readback = decode_fragment(fragment_path.read_bytes())

    partitions = BundlePartitions(bundle_path)
    original_records = partitions.selected_records("evidence", "instances", tuple(range(NODE_FIRST, NODE_STOP)))
    instances = [decode(OperationInstance, row["record"]) for row in original_records]
    definition_ids = {_typed(OperationDefinitionID, row["record"]["definition"]) for row in original_records}
    definitions = {}
    for envelope in partitions.iter_records("semantic", "definitions"):
        raw = envelope["record"]
        identifier = _typed(OperationDefinitionID, raw["id"])
        if identifier in definition_ids:
            definitions[identifier] = decode(OperationDefinition, raw)
            if definitions.keys() >= definition_ids:
                break
    if definitions.keys() != definition_ids:
        raise ValueError("selected original semantic definitions are incomplete")

    categories = Counter()
    for instance in instances:
        category = instance.metadata.get("category")
        has_schema = type(definitions[instance.definition].metadata.get("op_schema")) is str and bool(
            definitions[instance.definition].metadata["op_schema"])
        if category == "user_annotation":
            categories["USER_ANNOTATION"] += 1
        elif category == "cpu_op" and has_schema:
            categories["REGISTERED_SCHEMA_OPERATION"] += 1
        elif category == "cpu_op":
            categories["UNSCHEMATIZED_CPU_OPERATION"] += 1
        else:
            categories["UNKNOWN_NATIVE_BOUNDARY"] += 1

    instance = next(item for item in instances if item.metadata.get("node_id") == 18)
    if definitions[instance.definition].label != "aten::empty":
        raise ValueError("fixed readback instance is no longer aten::empty")
    ports = ports_for_instance(instance, fragment_readback, bundle_path)
    if len(ports.ports) != 7:
        raise ValueError("aten::empty readback no longer has the observed 6+1 boxed ports")
    output_port = next(p for p in ports.ports if p.direction == "output" and p.path == (0,))
    if output_port.formal_slot is None or output_port.formal_status != "QUALIFIED":
        raise ValueError("aten::empty output lost its existing schema slot qualification")

    provider_raw = _lookup(partitions, "evidence", "provider_references", "reference_id",
                            output_port.provider_reference)
    provider = decode(ProviderReference, provider_raw)
    descriptors = [d for d in provider.metadata["descriptors"] if d["descriptor_id"] == output_port.descriptor_id]
    if len(descriptors) != 1:
        raise ValueError("existing shared provider descriptor is missing or ambiguous")
    descriptor = descriptors[0]
    slot_raw = _lookup(partitions, "semantic", "slots", "slot_id", output_port.formal_slot.as_dict())
    slot = decode(ValueSlot, slot_raw)
    if slot.owner != instance.definition or slot.direction != "output":
        raise ValueError("existing schema ValueSlot owner/direction differs")

    all_ports = [port for row in fragment_readback.rows for port in row.ports]
    directions = Counter(port.direction for port in all_ports)
    formal = Counter(port.formal_status for port in all_ports)
    provider_links = sum(port.provider_reference is not None for port in all_ports)
    value_slot_links = sum(port.formal_slot is not None for port in all_ports)
    report = {
        "schema": "scar.native-boxed-port-readback-report", "schema_version": 1,
        "source_range": {"first_source_ordinal": NODE_FIRST, "stop_source_ordinal": NODE_STOP,
                         "original_classification_counts": dict(sorted(categories.items()))},
        "source_receipts": {"archive_index_sha256": ARCHIVE_INDEX_SHA256,
            "stored_sha256": fragment.source_stored_sha256, "stored_bytes": fragment.source_stored_bytes,
            "decoded_sha256": fragment.source_sha256, "decoded_bytes": fragment.source_raw_bytes,
            "nodes_parsed_from_original_json": NODE_STOP,
            "decoded_remainder_hashed_without_json_parse": True},
        "port_derivation": "direct original ETO nodes[].inputs/outputs values+types; no intermediate observation shard",
        "consumed_existing_instance_rows": len(instances),
        "sidecar_operation_instance_refs": len(fragment_readback.rows),
        "sidecar_ordered_ports": len(all_ports),
        "input_ports": directions["input"], "output_ports": directions["output"],
        "formal_status_counts": dict(sorted(formal.items())),
        "bundle_reference_checks": {"provider_descriptor_type_links_verified": provider_links,
            "formal_value_slot_owner_direction_refs_verified": value_slot_links},
        "codec_roundtrip": {"typed_encode_decode": decoded == fragment,
            "persisted_file_readback": fragment_readback == fragment,
            "fragment_bytes": len(fragment_bytes), "fragment_sha256": sha256(fragment_bytes).hexdigest()},
        "existing_instance_query": {
            "instance_id": instance.id.wire, "definition_id": instance.definition.wire,
            "parent_id": instance.parent.wire if instance.parent else None,
            "category": instance.metadata.get("category"), "source": instance.metadata["raw_reference"],
            "ports_returned": len(ports.ports),
            "inputs": [{"path": list(p.path), "type": p.provider_type, "kind": p.kind,
                        "formal_status": p.formal_status}
                       for p in ports.ports if p.direction == "input"],
            "output": {"path": list(output_port.path), "type": output_port.provider_type,
                "kind": output_port.kind,
                "source_pointer": instance.metadata["raw_reference"] + output_port.source_locator,
                "formal_slot": output_port.formal_slot.wire, "formal_status": output_port.formal_status,
                "provider_reference": output_port.provider_reference,
                "descriptor_id": output_port.descriptor_id,
                "shared_descriptor": {"type": descriptor["type"], "shape": descriptor["shape"],
                    "strides": descriptor["strides"], "device": descriptor["tensor_tuple"][-1]},
                "existing_value_slot": {"id": slot.slot_id.wire, "name": slot.name,
                    "direction": slot.direction, "owner": slot.owner.wire}},
            "input_formal_mapping": "UNRESOLVED_NON_TENSOR_FORMAL_PATH for all six inputs",
        },
        "observational_limits": {"normal_outcome": "not represented", "effects": "not represented",
            "device_ready": "not represented", "content_or_alias_identity": "not represented",
            "tensor_values_saved": False,
            "user_annotation_rows_retained_only_in_original_evidence": categories["USER_ANNOTATION"]},
        "shared_catalog_references": {"source_uri": fragment.source_uri,
            "evidence_manifest_sha256": fragment.evidence_manifest_sha256,
            "bundle_schema_version": fragment.evidence_bundle_schema_version,
            "evidence_graph_schema_version": fragment.evidence_graph_schema_version},
    }
    (output / "readback-0-128.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({key: result[key] for key in (
        "consumed_existing_instance_rows", "sidecar_operation_instance_refs", "sidecar_ordered_ports",
        "input_ports", "output_ports", "formal_status_counts", "codec_roundtrip")}, ensure_ascii=False))
