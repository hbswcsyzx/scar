"""Build and verify a complete port publication from the retained original ETO."""
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
from scar.trace.native_port_sidecar import build_native_port_publication, query_native_ports


MAIN = WORKSPACE.parent / "structured-program-model"
CAPTURE = MAIN / "artifacts/experiments/lewm_joint_capture_20261026/capture"
NATIVE = MAIN / "artifacts/experiments/native_inputs_full_20261026/native-import/native"
ETO_PATH = CAPTURE / "trace/execution-trace.1578961.adfc0475ed50cb37e1c0453142b5fa65.json.gz"
ARCHIVE_INDEX = CAPTURE / "archive-index.json"
BUNDLE_PARTITIONS = NATIVE / "bundle-partitions"
ARCHIVE_INDEX_SHA256 = "2bb588b34bdca5838f14d470b14830b15b5f344785c638df62cbb6c168df88c8"
SHARD_SIZE = 4096
QUERY_ORDINAL = 16


def _directory_bytes(path: Path) -> tuple[int, int]:
    files = [item for item in path.rglob("*") if item.is_file()]
    return len(files), sum(item.stat().st_size for item in files)


def _track_chunk_reads():
    phases = defaultdict(lambda: defaultdict(Counter))
    phase = ["build"]
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


def _plain_chunk_stats(phases) -> dict:
    return {
        phase: {
            table: {key: int(value) for key, value in sorted(counts.items())}
            for table, counts in sorted(tables.items())
        }
        for phase, tables in sorted(phases.items())
    }


def run() -> dict:
    output = Path(__file__).resolve().parent
    output.mkdir(parents=True, exist_ok=True)
    publication = output / "publication"
    if publication.exists():
        raise FileExistsError(f"publication output already exists: {publication}")
    archive_index_digest = sha256(ARCHIVE_INDEX.read_bytes()).hexdigest()
    if archive_index_digest != ARCHIVE_INDEX_SHA256:
        raise ValueError("retained archive-index SHA differs from the original capture reference")

    phases, phase, original_chunk = _track_chunk_reads()
    started = time.perf_counter()
    try:
        index = build_native_port_publication(
            ETO_PATH, ARCHIVE_INDEX, ARCHIVE_INDEX_SHA256, BUNDLE_PARTITIONS,
            publication, shard_size=SHARD_SIZE)
        phase[0] = "instance_lookup"
        partitions = BundlePartitions(BUNDLE_PARTITIONS)
        envelope = partitions.selected_records("evidence", "instances", (QUERY_ORDINAL,))[0]
        instance = decode(OperationInstance, envelope["record"])
        phase[0] = "instance_query"
        expected_index_sha256 = sha256((publication / "index.json").read_bytes()).hexdigest()
        ports = query_native_ports(instance, publication, BUNDLE_PARTITIONS,
                                   expected_index_sha256=expected_index_sha256)
    finally:
        BundlePartitions._chunk = original_chunk
    elapsed = time.perf_counter() - started

    if instance.metadata.get("raw_reference") != (
            f"sha256:{index.source_sha256}#/nodes/{QUERY_ORDINAL}"):
        raise ValueError("readback instance does not reference its original ETO node ordinal")
    if instance.metadata.get("node_id") != 18:
        raise ValueError("fixed aten::empty readback no longer resolves to ETO node 18")
    inputs = [port for port in ports.ports if port.direction == "input"]
    outputs = [port for port in ports.ports if port.direction == "output"]
    if len(inputs) != 6 or len(outputs) != 1 or len(ports.ports) != 7:
        raise ValueError("aten::empty readback did not resolve its original six inputs and one output")
    output_port = outputs[0]

    publication_files, publication_bytes = _directory_bytes(publication)
    report = {
        "schema": "scar.native-boxed-port-full-run-report",
        "schema_version": 1,
        "terminal_status": "SUCCEEDED",
        "elapsed_build_and_query_seconds": round(elapsed, 3),
        "source": {
            "uri": index.source_uri,
            "archive_index_sha256": ARCHIVE_INDEX_SHA256,
            "stored_sha256": index.source_stored_sha256,
            "stored_bytes": index.source_stored_bytes,
            "decoded_sha256": index.source_sha256,
            "decoded_bytes": index.source_raw_bytes,
            "actual_nodes_to_eof": index.source_nodes,
            "indexed_node_range": [index.first_source_ordinal, index.stop_source_ordinal],
            "stored_source_read_passes": 2,
            "stored_source_bytes_read": 2 * index.source_stored_bytes,
            "decoded_source_bytes_parsed_and_hashed": index.source_raw_bytes,
        },
        "bundle_reference": {
            "manifest_sha256": index.evidence_manifest_sha256,
            "bundle_schema_version": index.evidence_bundle_schema_version,
            "evidence_graph_schema_version": index.evidence_graph_schema_version,
        },
        "source_node_classifications": index.classification_counts,
        "source_node_classification_total": sum(index.classification_counts.values()),
        "unknown_native_boundary_audit": [
            {
                "source_ordinal": 0,
                "node_id": 2,
                "category": None,
                "definition_label": "[pytorch|profiler|execution_trace|thread]",
                "schema_present": False,
                "role": "ETO thread root",
                "existing_instance_id": "opinst:native:636fde61a45803f11712767bc1cbf0b0ea3de13b14e0b27edc2d6071daea1612:eto:2",
                "existing_parent_id": "opinst:native:636fde61a45803f11712767bc1cbf0b0ea3de13b14e0b27edc2d6071daea1612:eto:1",
                "port_row_created": False,
            },
            {
                "source_ordinal": 310411,
                "node_id": 1,
                "category": None,
                "definition_label": "[pytorch|profiler|execution_trace|process]",
                "schema_present": False,
                "role": "ETO process root",
                "existing_instance_id": "opinst:native:636fde61a45803f11712767bc1cbf0b0ea3de13b14e0b27edc2d6071daea1612:eto:1",
                "existing_parent_id": None,
                "port_row_created": False,
            },
        ],
        "existing_instance_rows_with_ports": index.operation_rows,
        "ordered_ports": {"input": index.input_ports, "output": index.output_ports,
                           "total": index.input_ports + index.output_ports},
        "fragment_publication": {
            "manifest_path": "publication/index.json",
            "manifest_sha256": sha256((publication / "index.json").read_bytes()).hexdigest(),
            "manifest_bytes": (publication / "index.json").stat().st_size,
            "shard_size_source_nodes": SHARD_SIZE,
            "shard_count": len(index.shards),
            "files": publication_files,
            "total_bytes": publication_bytes,
        },
        "bundle_chunk_io": _plain_chunk_stats(phases),
        "source_range_query": {
            "instance_id": instance.id.wire,
            "definition_id": instance.definition.wire,
            "parent_id": instance.parent.wire if instance.parent else None,
            "raw_reference": instance.metadata["raw_reference"],
            "node_id": instance.metadata["node_id"],
            "ports_returned": len(ports.ports),
            "inputs": [{"path": list(port.path), "source_locator": port.source_locator,
                        "type": port.provider_type, "kind": port.kind,
                        "formal_status": port.formal_status}
                       for port in inputs],
            "output": {"path": list(output_port.path), "source_locator": output_port.source_locator,
                       "type": output_port.provider_type, "kind": output_port.kind,
                       "formal_status": output_port.formal_status,
                       "formal_slot": output_port.formal_slot.wire if output_port.formal_slot else None,
                       "provider_reference": output_port.provider_reference,
                       "descriptor_id": output_port.descriptor_id},
        },
        "observational_limits": {
            "tensor_values_saved": False,
            "normal_or_ready_proof_added": False,
            "execution_or_instance_description_copied": False,
            "annotation_rows_created_as_operations": False,
            "extra_synthetic_instances_paired_to_eto_ordinals": False,
            "unresolved_non_tensor_formal_paths_are_explicit": True,
        },
    }
    report_path = output / "full-run-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                           encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "terminal_status": result["terminal_status"],
        "elapsed_build_and_query_seconds": result["elapsed_build_and_query_seconds"],
        "source_actual_nodes_to_eof": result["source"]["actual_nodes_to_eof"],
        "source_node_classifications": result["source_node_classifications"],
        "existing_instance_rows_with_ports": result["existing_instance_rows_with_ports"],
        "ordered_ports": result["ordered_ports"],
        "publication_files": result["fragment_publication"]["files"],
        "publication_bytes": result["fragment_publication"]["total_bytes"],
        "bundle_chunk_io": result["bundle_chunk_io"],
        "source_range_query": result["source_range_query"],
    }, ensure_ascii=False))
