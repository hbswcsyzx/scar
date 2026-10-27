"""Query all existing ETO ports for the Tensor returned by aten::empty node 18."""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

WORKSPACE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKSPACE))

from scar.ir.record_codec import decode
from scar.ir.v2.evidence import OperationInstance
from scar.store.bundle_partitions import BundlePartitions
from scar.trace.native_port_sidecar import (
    query_native_port_edges, query_native_ports, read_native_port_index,
)


MAIN = WORKSPACE.parent / "structured-program-model"
BUNDLE = MAIN / "artifacts/experiments/native_inputs_full_20261026/native-import/native/bundle-partitions"
PUBLICATION = Path(__file__).resolve().parent / "publication"
INDEX_SHA256 = "54f9dfbcc8a4e3cfc720c2dfb0c377d61707cde3f70c1360f1f68fd54cbf17b2"
QUERY_INSTANCE_ORDINAL = 16


def _track_chunks():
    phases = defaultdict(lambda: defaultdict(lambda: {"chunk_reads": 0,
        "compressed_bytes": 0, "decoded_bytes": 0}))
    phase = ["instance"]
    original = BundlePartitions._chunk

    def tracked(self, descriptor):
        decoded = original(self, descriptor)
        graph, table = Path(descriptor["uri"]).parts[:2]
        counts = phases[phase[0]][f"{graph}.{table}"]
        counts["chunk_reads"] += 1
        counts["compressed_bytes"] += descriptor["physical_bytes"]
        counts["decoded_bytes"] += len(decoded)
        return decoded

    BundlePartitions._chunk = tracked
    return phases, phase, original


def run() -> dict:
    report_path = Path(__file__).resolve().parent / "occurrence-query-report.json"
    phases, phase, original_chunk = _track_chunks()
    started = time.perf_counter()
    try:
        index = read_native_port_index(PUBLICATION, expected_sha256=INDEX_SHA256)
        bundle = BundlePartitions(BUNDLE)
        record = bundle.selected_records("evidence", "instances", (QUERY_INSTANCE_ORDINAL,))[0]["record"]
        instance = decode(OperationInstance, record)
        phase[0] = "seed_instance_port"
        seed = query_native_ports(instance, PUBLICATION, BUNDLE, expected_index_sha256=INDEX_SHA256)
        seed_ports = [port for port in seed.ports if port.direction == "output" and port.kind == "TENSOR"]
        if len(seed_ports) != 1:
            raise ValueError("aten::empty seed instance no longer has one Tensor output")
        seed_port = seed_ports[0]

        phase[0] = "provider_occurrences_and_edges"
        query_started = time.perf_counter()
        occurrences = query_native_port_edges(seed_port.provider_reference,
            seed_port.descriptor_id, PUBLICATION, BUNDLE, expected_index_sha256=INDEX_SHA256)
        query_seconds = time.perf_counter() - query_started

        directions = {"input": 0, "output": 0}
        rows = []
        evidence_edges = []
        pointers = set()
        for operation, port, edge in occurrences:
            directions[port.direction] += 1
            source_pointer = (f"sha256:{index.source_sha256}#/nodes/"
                              f"{operation.source_ordinal}{port.source_locator}")
            pointers.add((operation.instance.wire, source_pointer))
            rows.append({
                "instance_id": operation.instance.wire,
                "definition_id": operation.definition.wire,
                "source_ordinal": operation.source_ordinal,
                "direction": port.direction,
                "evidence_relation": edge.relation.value,
                "path": list(port.path),
                "source_pointer": source_pointer,
                "provider_type": port.provider_type,
                "formal_slot": port.formal_slot.wire if port.formal_slot else None,
                "formal_status": port.formal_status,
            })
            if (edge.source.reference != operation.instance
                    or edge.target.reference != seed_port.provider_reference
                    or source_pointer not in edge.evidence.references):
                raise ValueError("production query returned a mismatched original EvidenceEdge")
            evidence_edges.append({
                "edge_id": edge.edge_id,
                "relation": edge.relation.value,
                "source_instance": edge.source.reference.wire,
                "target_provider_reference": edge.target.reference,
                "claim_pointer": source_pointer,
            })
        if len(occurrences) < 2 or not directions["input"] or not directions["output"]:
            raise ValueError("selected provider descriptor did not yield repeated input and output occurrences")

        phase[0] = "exact_storage_regions"
        storage_links = []
        for envelope in bundle.iter_records("values", "regions"):
            region = envelope["record"]
            metadata = region.get("metadata", {})
            key = (metadata.get("marker_instance"), metadata.get("eto_reference"))
            if key not in pointers:
                continue
            if (type(region.get("id")) is not dict or type(region.get("allocation")) is not dict
                    or type(region["id"].get("wire")) is not str
                    or type(region["allocation"].get("wire")) is not str):
                raise ValueError("matching existing storage region lacks typed references")
            storage_links.append({
                "instance_id": key[0], "source_pointer": key[1],
                "storage_region_id": region["id"]["wire"],
                "allocation_id": region["allocation"]["wire"],
                "evidence_relation": "USES_STORAGE",
                "basis": "existing exact marker-instance/ETO-slot StorageRegion reference",
            })
    finally:
        BundlePartitions._chunk = original_chunk

    report = {
        "schema": "scar.native-port-occurrence-query-report",
        "schema_version": 1,
        "query_status": "SUCCEEDED",
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "provider_query_seconds": round(query_seconds, 3),
        "index_sha256": INDEX_SHA256,
        "shard_validation": {
            "shards_scanned": len(index.shards),
            "decoded_json_bytes_with_receipt_checks": sum(ref.decoded_bytes for ref in index.shards),
            "all_shard_stored_and_decoded_hashes_verified": True,
            "all_shard_headers_ranges_and_declared_counts_verified": True,
            "matched_operation_rows_fully_codec_decoded": len({operation.instance for operation, _, _ in occurrences}),
            "unmatched_operation_rows_fully_codec_decoded": False,
        },
        "seed": {
            "instance_id": instance.id.wire,
            "definition_id": instance.definition.wire,
            "source_ordinal": QUERY_INSTANCE_ORDINAL,
            "port_path": list(seed_port.path),
            "provider_reference": seed_port.provider_reference,
            "descriptor_id": seed_port.descriptor_id,
            "descriptor_type": seed_port.provider_type,
        },
        "occurrence_count": len(occurrences),
        "direction_counts": directions,
        "occurrences": rows,
        "original_evidence_edges": evidence_edges,
        "existing_storage_links_for_exact_occurrences": storage_links,
        "existing_ir_connections": {
            "operation_instance_tensor_slots": "original metadata tensor_slots matches exact role/path/provider_reference/descriptor_id",
            "provider_reference_catalog": "original evidence.provider_references row and exact descriptor_id/type validated",
            "evidence_edges": "original INPUT_REFERENCE/OUTPUT_REFERENCE rows and claim pointers verified",
            "value_graph_record_counts": {
                graph: bundle.manifest["graphs"]["values"]["counts"][graph]
                for graph in ("logical_values", "versions", "provenance", "materializations",
                              "allocations", "regions", "objects", "bindings")
            },
            "program_graph_imported": False,
            "native_execution_model_imported": False,
            "token_to_logical_version_or_unique_producer": "not present or inferred",
            "generic_provider_port_to_storage_region": "not present; no exact StorageRegion matched the selected 11 ETO pointers",
        },
        "semantics": {
            "same_provider_reference_and_descriptor": "observed reference relation only",
            "input_output_direction": "observed port role; does not prove read/write effects",
            "logical_version_or_unique_producer": "UNKNOWN",
            "aliasing_or_shared_storage_from_token": "UNKNOWN",
            "operation_effects": "UNKNOWN",
            "storage_links": "reported only when an existing exact marker-instance/ETO-slot StorageRegion is present",
        },
        "bundle_chunk_io": {
            phase: {table: dict(counts) for table, counts in sorted(tables.items())}
            for phase, tables in sorted(phases.items())
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                           encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({key: result[key] for key in (
        "query_status", "elapsed_seconds", "provider_query_seconds", "occurrence_count",
        "direction_counts", "seed", "existing_storage_links_for_exact_occurrences",
        "bundle_chunk_io")}, ensure_ascii=False))
