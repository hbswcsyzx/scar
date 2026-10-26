"""Run the retained 0..127 sidecar and record bounded read accounting."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import sys
import time

WORKSPACE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKSPACE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scar.store.bundle_partitions import BundlePartitions
import run_readback
import scar.trace.native_port_sidecar as sidecar


_MANIFEST_READS = []
_CHUNK_READS = defaultdict(lambda: {"reads": 0, "stored_bytes": 0, "decoded_bytes": 0})


class _MeasuredBundlePartitions(BundlePartitions):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _MANIFEST_READS.append(self.manifest_receipt["physical_bytes"])

    def _chunk(self, descriptor):
        decoded = super()._chunk(descriptor)
        entry = _CHUNK_READS[descriptor["uri"]]
        entry["reads"] += 1
        entry["stored_bytes"] += descriptor["physical_bytes"]
        entry["decoded_bytes"] += descriptor["decoded_bytes"]
        return decoded


def run() -> dict:
    sidecar.BundlePartitions = _MeasuredBundlePartitions
    run_readback.BundlePartitions = _MeasuredBundlePartitions
    started = time.perf_counter()
    result = run_readback.run()
    elapsed = time.perf_counter() - started
    output = Path(__file__).resolve().parent
    fragment_path = output / "native-port-fragment-000000-000128.json"
    report_path = output / "readback-0-128.json"
    terminal = {key: result[key] for key in (
        "consumed_existing_instance_rows", "sidecar_operation_instance_refs", "sidecar_ordered_ports",
        "input_ports", "output_ports", "formal_status_counts", "bundle_reference_checks", "codec_roundtrip")}
    measurement = {
        "schema": "scar.native-boxed-port-run-measurement", "schema_version": 1,
        "command": "/home/zyf/miniconda3/envs/lewm/bin/python -B artifacts/analysis/native_port_sidecar_20261026/run_measured.py",
        "exit_status": 0, "elapsed_seconds": elapsed,
        "terminal_summary": terminal,
        "verified_source_reads": result["source_receipts"],
        "source_read_passes": {"stored_member_sha_passes": 1, "gzip_decode_and_raw_sha_passes": 1,
                               "archive_index_metadata_reads": 1},
        "archive_index_bytes": (run_readback.CAPTURE / "archive-index.json").stat().st_size,
        "bundle_manifest_reads": {"count": len(_MANIFEST_READS), "bytes_total": sum(_MANIFEST_READS)},
        "bundle_verified_chunk_reads": dict(sorted(_CHUNK_READS.items())),
        "bundle_chunk_totals": {
            "read_calls": sum(row["reads"] for row in _CHUNK_READS.values()),
            "stored_bytes": sum(row["stored_bytes"] for row in _CHUNK_READS.values()),
            "decoded_bytes": sum(row["decoded_bytes"] for row in _CHUNK_READS.values()),
        },
        "output_sizes": {"fragment_bytes": fragment_path.stat().st_size,
                         "readback_report_bytes": report_path.stat().st_size},
    }
    path = output / "run-measurement.json"
    path.write_text(json.dumps(measurement, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")
    return measurement


if __name__ == "__main__":
    summary = run()
    print(json.dumps({"exit_status": summary["exit_status"], "elapsed_seconds": summary["elapsed_seconds"],
                      "terminal_summary": summary["terminal_summary"],
                      "bundle_chunk_totals": summary["bundle_chunk_totals"],
                      "output_sizes": summary["output_sizes"]}, ensure_ascii=False))
