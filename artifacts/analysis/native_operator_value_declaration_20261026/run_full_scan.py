#!/usr/bin/env python3
"""Receipt-validate all retained native ports; persist only a compact declaration index."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scar.ir.record_codec import decode
from scar.ir.v2.evidence import OperationInstance
from scar.store.bundle_partitions import BundlePartitions
from scar.trace.native_port_sidecar import read_native_port_index
from scar.trace.native_reference_flow import read_native_reference_flow_index
from scar.trace.native_operator_value_interface import (
    build_native_operator_value_declaration_publication,
    load_native_operator_value_source_catalog,
    query_native_operator_value_port_from_declaration,
    read_native_operator_value_declaration_index,
)


MAIN = Path("/home/zyf/AAA/scar-worktrees/structured-program-model")
IMPORT = MAIN / "artifacts/experiments/native_inputs_full_20261026/native-import/native"
BUNDLE = IMPORT / "bundle-partitions"
PORT_PUBLICATION = ROOT / "artifacts/analysis/native_port_sidecar_full_20261026/publication"
FLOW_PUBLICATION = ROOT / "artifacts/analysis/native_reference_flow_20261026/publication"
OUTPUT = ROOT / "artifacts/analysis/native_operator_value_declaration_20261026/publication"
REPORT = ROOT / "artifacts/analysis/native_operator_value_declaration_20261026/report.json"
PORT_INDEX_SHA = "54f9dfbcc8a4e3cfc720c2dfb0c377d61707cde3f70c1360f1f68fd54cbf17b2"
FLOW_INDEX_SHA = "63030af42af9adfb883d9b2a04e2289800b08caa95bed0f443f4e118a8f1e6ca"
QUERY_ORDINAL = 21686


def file_sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    started = time.perf_counter()
    partitions = BundlePartitions(BUNDLE)
    catalog_start = time.perf_counter()
    catalog = load_native_operator_value_source_catalog(partitions)
    catalog_seconds = time.perf_counter() - catalog_start

    port_index = read_native_port_index(PORT_PUBLICATION,
                                        expected_sha256=PORT_INDEX_SHA)
    flow_index, flow_index_sha = read_native_reference_flow_index(
        FLOW_PUBLICATION, expected_sha256=FLOW_INDEX_SHA)
    if sum(shard.operation_rows for shard in port_index.shards) != port_index.operation_rows:
        raise ValueError("retained native port shard rows do not rebuild the full-source denominator")
    if (flow_index.operation_rows != port_index.operation_rows
            or flow_index.source_nodes != port_index.source_nodes
            or flow_index.native_ports != port_index.input_ports + port_index.output_ports):
        raise ValueError("retained reference-flow and native-port source scopes disagree")
    source_classes = port_index.classification_counts
    if (sum(source_classes.values()) != port_index.source_nodes
            or source_classes.get("REGISTERED_SCHEMA_OPERATION", 0)
            + source_classes.get("UNSCHEMATIZED_CPU_OPERATION", 0) != port_index.operation_rows):
        raise ValueError("original provider-category counts do not partition native source nodes")

    build_start = time.perf_counter()
    index, index_sha = build_native_operator_value_declaration_publication(
        PORT_PUBLICATION, partitions, FLOW_PUBLICATION, OUTPUT,
        expected_native_port_index_sha256=PORT_INDEX_SHA,
        expected_reference_flow_index_sha256=FLOW_INDEX_SHA,
        catalog=catalog)
    full_build_seconds = time.perf_counter() - build_start

    decoded_index, decoded_sha = read_native_operator_value_declaration_index(
        OUTPUT, expected_sha256=index_sha)
    if decoded_sha != index_sha or decoded_index != index:
        raise ValueError("compact declaration index does not roundtrip identically")
    if (index.operations_with_schema != source_classes.get("REGISTERED_SCHEMA_OPERATION", 0)
            or index.operations_without_schema != source_classes.get("UNSCHEMATIZED_CPU_OPERATION", 0)):
        raise ValueError("full scan schema qualification differs from original provider-category counts")

    source_instance = partitions.selected_records(
        "evidence", "instances", (QUERY_ORDINAL,))[0]
    instance = decode(OperationInstance, source_instance["record"])
    query_start = time.perf_counter()
    interface, binding, graph = query_native_operator_value_port_from_declaration(
        OUTPUT, instance, "input", (0,), expected_index_sha256=index_sha,
        catalog=catalog)
    query_seconds = time.perf_counter() - query_start
    if binding.value_version is None or not graph.validate()["valid"]:
        raise ValueError("on-demand original operator query did not derive a valid ValueGraph fragment")
    output_bindings = [item for item in interface.outputs if item.kind == "TENSOR"]
    result_versions = tuple(item.value_version for item in output_bindings)
    if not result_versions:
        raise ValueError("on-demand original operator has no Tensor result to connect")
    result_record = graph.provenance[graph.versions[result_versions[0]].provenance_id]
    if (interface.label != "aten::add_" or result_record.producer != interface.instance
            or len(result_record.inputs) != 2):
        raise ValueError("on-demand result provenance is not restricted to this add_ instance's two Tensor inputs")

    port_index_path = (PORT_PUBLICATION / "index.json").resolve()
    flow_index_path = (FLOW_PUBLICATION / "index.json").resolve()
    index_path = OUTPUT / "index.json"
    total_port_stored = sum(item.source.stored_bytes for item in index.shard_summaries)
    total_port_decoded = sum(item.source.decoded_bytes for item in index.shard_summaries)
    report = {
        "schema": "scar.native-operator-value-declaration-full-scan-report",
        "schema_version": 1,
        "terminal_status": index.terminal_status,
        "source": {
            "bundle_manifest_uri": index.bundle_manifest.uri,
            "bundle_manifest_sha256": index.bundle_manifest.sha256,
            "native_port_index_uri": index.native_port_index.uri,
            "native_port_index_sha256": index.native_port_index.sha256,
            "reference_flow_index_uri": index.reference_flow_index.uri,
            "reference_flow_index_sha256": index.reference_flow_index.sha256,
            "original_eto_uri": index.eto_source.uri,
            "original_eto_sha256": index.eto_source.sha256,
            "source_range": [index.source_first_ordinal, index.source_stop_ordinal],
        },
        "validation": {
            "original_port_index_source_nodes": index.source_nodes,
            "native_port_source_range_reaches_eof": index.source_stop_ordinal == index.source_nodes,
            "operation_rows_joined_to_original_evidence_records": index.operation_rows,
            "raw_eto_bytes_reparsed_in_this_pass": False,
            "source_node_classification_from_original_native_port_index": source_classes,
            "source_nodes_without_operation_interface": index.source_nodes - index.operation_rows,
            "annotations_and_unknown_provider_roots_get_no_fabricated_operation": True,
            "original_native_operation_instances_verified": index.operation_rows,
            "original_ordered_ports": index.input_ports + index.output_ports,
            "input_ports": index.input_ports,
            "output_ports": index.output_ports,
            "tensor_input_ports": index.tensor_input_ports,
            "tensor_output_ports": index.tensor_output_ports,
            "endpoint_symbols_derived_on_demand": index.tensor_input_ports + index.tensor_output_ports,
            "output_provenance_records_derived_on_demand": index.output_interface_provenance_records,
            "same_instance_input_versions_per_operator_interface": index.output_interface_input_versions,
            "cross_instance_reference_flow_used_as_parent": False,
            "schema_may_write_boundaries": index.declared_may_write_boundaries,
            "schema_may_alias_boundaries": index.schema_may_alias_boundaries,
            "operations_with_schema": index.operations_with_schema,
            "operations_without_schema": index.operations_without_schema,
            "schema_alias_inventory_incomplete_operations": index.schema_alias_inventory_incomplete_operations,
            "tensor_ports_with_descriptor_and_device": index.tensor_ports_with_provider_descriptor,
            "tensor_ports_with_unknown_descriptor_or_device": index.tensor_ports_without_provider_descriptor,
            "tensor_ports_without_original_instance_tensor_slot": index.tensor_ports_without_instance_tensor_slot,
            "formal_ports_resolved": index.formal_ports_resolved,
            "formal_ports_unresolved": index.formal_ports_unresolved,
            "shared_reference_flow_ports": index.reference_flow_ports,
            "reference_flow_ports_with_one_original_edge": index.reference_flow_ports_with_one_original_edge,
            "reference_flow_ports_without_one_original_edge": index.reference_flow_ports_without_one_original_edge,
            "all_original_native_port_shards_verified": len(index.shard_summaries),
            "all_original_operation_rows_resolved": sum(item.original_instances_verified for item in index.shard_summaries),
        },
        "source_bytes_read": {
            "original_native_port_shards_stored": total_port_stored,
            "original_native_port_shards_decoded": total_port_decoded,
            "original_operation_instance_chunks_stored_once": index.instance_chunks_stored_bytes,
            "original_operation_instance_chunks_decoded_once": index.instance_chunks_decoded_bytes,
            "shared_semantic_and_provider_catalog_stored": index.catalog_stored_bytes,
            "shared_semantic_and_provider_catalog_decoded": index.catalog_decoded_bytes,
            "native_port_index_json": port_index_path.stat().st_size,
            "reference_flow_index_json_only": flow_index_path.stat().st_size,
            "reference_flow_data_shards_read": 0,
            "original_eto_full_source_read": False,
            "new_LeWM_import_or_capture": False,
        },
        "shared_catalog": {
            "operation_definitions": index.catalog_definitions,
            "value_slots": index.catalog_slots,
            "effect_summaries": index.catalog_effects,
            "provider_references": index.catalog_provider_references,
            "persisted_catalog_descriptions": 0,
            "catalog_lifetime": "one-process in-memory lookup maps; source bundle remains authority",
        },
        "declaration_index": {
            "path": str(index_path.resolve()),
            "sha256": index_sha,
            "bytes": index_path.stat().st_size,
            "persisted_operator_symbols": index.persisted_operator_symbols,
            "persisted_value_graph_records": 0,
            "persisted_per_operation_interface_records": 0,
            "derivation_profile": index.id_derivation_profile,
            "id_recipe": {
                "payload_scope_fields_in_order": [
                    "profile_version=1", "bundle_manifest.uri", "bundle_manifest.sha256",
                    "native_port_index.uri", "native_port_index.sha256", "eto_source.uri",
                    "eto_source.sha256", "original_instance.wire", "original_definition.wire",
                    "source_ordinal", "direction", "ordered_path", "source_locator",
                    "formal_slot.wire|null", "provider_reference|null", "descriptor_id|null",
                ],
                "digest": "sha256(UTF-8 JSON, ensure_ascii=true, separators=(',',':'), allow_nan=false)",
                "logical_value_and_provenance_id": "native-port-payload:<digest>",
                "version_id": "ValueVersionID(LogicalValueID, revision=0)",
                "materialization_id": "native-port-payload:<digest>",
                "operator_provenance_id": "sha256(original_instance.wire + NUL + 'reported-argument-interface')",
                "distinct_endpoint_ids_do_not_claim_distinct_numeric_contents": True,
            },
            "producer_source_sha256": index.producer_source_sha256,
            "per_source_shard_receipts_and_counts_in_index": len(index.shard_summaries),
        },
        "on_demand_query": {
            "instance": interface.instance.wire,
            "source_ordinal": interface.source_ordinal,
            "operation": interface.label,
            "queried_port": binding.port_id,
            "queried_formal_slot": binding.formal_slot.wire if binding.formal_slot else None,
            "queried_payload_symbol": binding.value_version.wire,
            "queried_original_edge": binding.original_edge.edge if binding.original_edge else None,
            "tensor_input_ports": sum(item.kind == "TENSOR" for item in interface.inputs),
            "tensor_output_ports": sum(item.kind == "TENSOR" for item in interface.outputs),
            "result_provenance_input_versions": len(result_record.inputs),
            "state_boundaries": [item.relation for item in interface.state_boundaries],
            "inferred_only": True,
            "query_seconds": round(query_seconds, 3),
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "catalog_load_seconds": round(catalog_seconds, 3),
        "full_receipt_validation_and_index_build_seconds": round(full_build_seconds, 3),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "terminal_status": report["terminal_status"],
        "report": str(REPORT.resolve()),
        "index": str(index_path.resolve()),
        "index_sha256": index_sha,
        "index_bytes": index_path.stat().st_size,
        "source_nodes": index.source_nodes,
        "operation_rows": index.operation_rows,
        "ordered_ports": index.input_ports + index.output_ports,
        "tensor_ports": index.tensor_input_ports + index.tensor_output_ports,
        "verified_source_shards": len(index.shard_summaries),
        "elapsed_seconds": report["elapsed_seconds"],
        "query_seconds": round(query_seconds, 3),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
