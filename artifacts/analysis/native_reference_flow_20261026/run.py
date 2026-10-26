#!/usr/bin/env python3
"""Build one full reference-flow publication from retained native artifacts."""
from __future__ import annotations

import argparse
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
from scar.trace.native_reference_flow import (
    build_native_reference_flow_publication,
    query_native_reference_flow_upstream,
    read_native_reference_flow_index,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-port-publication", type=Path,
                        default=ROOT / "artifacts/analysis/native_port_sidecar_full_20261026/publication")
    parser.add_argument("--bundle-partitions", type=Path,
                        default=Path("/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/native_inputs_full_20261026/native-import/native/bundle-partitions"))
    parser.add_argument("--output", type=Path,
                        default=ROOT / "artifacts/analysis/native_reference_flow_20261026/publication")
    parser.add_argument("--report", type=Path,
                        default=ROOT / "artifacts/analysis/native_reference_flow_20261026/report.json")
    parser.add_argument("--consumer-source-ordinal", type=int, default=17)
    parser.add_argument("--consumer-input-path", type=int, nargs="+", default=[0])
    args = parser.parse_args()

    source_report_path = ROOT / "artifacts/analysis/native_port_sidecar_full_20261026/full-run-report.json"
    source_report = json.loads(source_report_path.read_text(encoding="utf-8"))
    if source_report.get("terminal_status") != "SUCCEEDED":
        raise SystemExit("retained native-port publication is not successful")
    expected_ports_sha = source_report["fragment_publication"]["manifest_sha256"]
    start = time.perf_counter()
    index = build_native_reference_flow_publication(
        args.native_port_publication, args.bundle_partitions, args.output,
        expected_native_port_index_sha256=expected_ports_sha)
    build_elapsed = time.perf_counter() - start

    flow_index, flow_index_sha = read_native_reference_flow_index(args.output)
    partitions = BundlePartitions(args.bundle_partitions)
    selected = partitions.selected_records(
        "evidence", "instances", (args.consumer_source_ordinal,))[0]["record"]
    consumer = decode(OperationInstance, selected)
    query_start = time.perf_counter()
    flows = query_native_reference_flow_upstream(
        args.output, args.native_port_publication, args.bundle_partitions,
        consumer, tuple(args.consumer_input_path),
        expected_flow_index_sha256=flow_index_sha,
        expected_native_port_index_sha256=expected_ports_sha)
    query_elapsed = time.perf_counter() - query_start
    if not flows:
        raise SystemExit("selected original native input resolved to no earlier reference candidate")

    file_bytes = sum(path.stat().st_size for path in args.output.rglob("*") if path.is_file())
    decoded_shard_bytes = sum(item.decoded_bytes for item in flow_index.shards)
    stored_shard_bytes = sum(item.stored_bytes for item in flow_index.shards)
    consumer_ordinal = flow_index.source_nodes
    raw_reference = consumer.metadata.get("raw_reference")
    prefix = f"sha256:{flow_index.eto_source.sha256}#/nodes/"
    if type(raw_reference) is not str or not raw_reference.startswith(prefix):
        raise SystemExit("selected operation is not qualified by the indexed ETO source")
    consumer_ordinal = int(raw_reference[len(prefix):])

    report = {
        "schema": "scar.native-reference-flow-full-run-report",
        "schema_version": 1,
        "terminal_status": "SUCCEEDED",
        "source": {
            "native_port_publication": str(args.native_port_publication.resolve()),
            "native_port_index_sha256": expected_ports_sha,
            "bundle_manifest": flow_index.evidence_bundle_manifest.uri,
            "bundle_manifest_sha256": flow_index.evidence_bundle_manifest.sha256,
            "eto_source_uri": flow_index.eto_source.uri,
            "eto_source_sha256": flow_index.eto_source.sha256,
        },
        "scope_counts": {
            "source_nodes_to_eof": flow_index.source_nodes,
            "existing_native_instances": flow_index.operation_rows,
            "native_ordered_ports": flow_index.native_ports,
            "provider_descriptor_ports": flow_index.reference_ports,
            "input_reference_ports": flow_index.input_reference_ports,
            "output_reference_ports": flow_index.output_reference_ports,
            "ports_with_exactly_one_original_evidence_edge": flow_index.ports_with_one_original_edge,
            "ports_without_exactly_one_original_evidence_edge": flow_index.ports_without_one_original_edge,
            "evidence_edge_rows_scanned": flow_index.evidence_edge_rows_scanned,
            "evidence_reference_edge_rows_qualified_by_eto_pointer": flow_index.indexed_reference_edge_rows,
            "provider_descriptor_groups_with_inputs_and_outputs": flow_index.groups_with_input_and_output,
        },
        "publication": {
            "path": str(args.output.resolve()),
            "index_sha256": flow_index_sha,
            "shards": len(flow_index.shards),
            "stored_shard_bytes": stored_shard_bytes,
            "decoded_shard_bytes": decoded_shard_bytes,
            "total_publication_file_bytes": file_bytes,
            "full_build_seconds": round(build_elapsed, 3),
            "single_input_query_seconds": round(query_elapsed, 3),
        },
        "query": {
            "consumer_instance_id": consumer.id.wire,
            "consumer_definition_id": consumer.definition.wire,
            "consumer_source_ordinal": consumer_ordinal,
            "input_path": list(args.consumer_input_path),
            "candidate_count_returned": len(flows),
            "candidates": [
                {
                    "relation": flow.relation,
                    "status": flow.status.value,
                    "ordering_basis": flow.ordering_basis,
                    "output_instance_id": flow.output.instance.wire,
                    "output_definition_id": flow.output.definition.wire,
                    "output_source_ordinal": flow.output.source_ordinal,
                    "output_path": list(flow.output.path),
                    "output_source_locator": flow.output.source_locator,
                    "output_formal_slot": None if flow.output.formal_slot is None else flow.output.formal_slot.wire,
                    "output_evidence_edge_id": flow.output_edge.edge,
                    "input_evidence_edge_id": flow.input_edge.edge,
                    "provider_reference": flow.provider_reference,
                    "descriptor_id": flow.descriptor_id,
                    "content_identity": flow.content_identity,
                    "logical_version": flow.logical_version,
                    "alias_boundary": flow.alias_boundary,
                    "write_boundary": flow.write_boundary,
                    "effects_boundary": flow.effects_boundary,
                    "readiness_boundary": flow.readiness_boundary,
                    "unknowns": list(flow.unknowns),
                }
                for flow in flows
            ],
            "truncation": "FAIL_CLOSED_IF_MORE_THAN_256_CANDIDATES",
        },
        "modeling_limits": {
            "stored_adjacency": "ordered provider-reference/descriptor occurrence groups; no expanded output-input Cartesian graph",
            "candidate_meaning": "same provider reference and descriptor, with ETO source ordinal preceding consumer; ordinal is not happens-before",
            "tensor_values_saved": False,
            "logical_values_or_content_versions_created": False,
            "alias_write_effect_and_readiness_proved": False,
            "original_operations_instances_definitions_and_evidence_edges_copied": False,
            "formal_schema_slot_references_preserved": True,
            "schema_contract_resolution": "follow original definition and formal-slot references in the retained bundle; native alias/write/effect boundary remains UNKNOWN here",
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "terminal_status": report["terminal_status"],
        "report": str(args.report.resolve()),
        "index_sha256": flow_index_sha,
        "source_nodes": flow_index.source_nodes,
        "operation_rows": flow_index.operation_rows,
        "reference_ports": flow_index.reference_ports,
        "ports_with_one_edge": flow_index.ports_with_one_original_edge,
        "ports_without_one_edge": flow_index.ports_without_one_original_edge,
        "groups_with_input_and_output": flow_index.groups_with_input_and_output,
        "build_seconds": round(build_elapsed, 3),
        "query_seconds": round(query_elapsed, 3),
        "candidate_outputs": [flow.output.source_ordinal for flow in flows],
        "publication_bytes": file_bytes,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
