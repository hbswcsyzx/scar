#!/home/zyf/miniconda3/envs/lewm/bin/python
"""Verify the first published 256-op native declaration fragment against metadata."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scar.analysis.native_declaration_inputs import NativeDeclarationInputSession
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode

FRAGMENT_URI = "/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/native_declaration_full_20261027/attempt01/shards/000000/000000/manifest.json"
FRAGMENT_SHA256 = "a6af356b4888f093388fae9a6b18bfc29f89f923d2388fd6920b7a1363cb9b4b"
NAVIGATION_URI = "/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/native_inputs_full_20261026/attempt05/port-navigation/manifest.json"
NAVIGATION_SHA256 = "4436b171be0dec2782e7843bc097227d675efa5e33155a6e8a2bf2408b4b6f72"


def artifact(uri, digest, schema):
    path = Path(uri).resolve(strict=True)
    return ProviderArtifact(str(path), digest, path.stat().st_size, schema)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(Path(__file__).parent / "attempt04"))
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    fragment = artifact(FRAGMENT_URI, FRAGMENT_SHA256, "scar.native-declaration-fragment")
    navigation = artifact(NAVIGATION_URI, NAVIGATION_SHA256, "scar.native-input-port-navigation")
    started = time.monotonic()
    with NativeDeclarationInputSession(navigation) as session:
        joined = session.read_fragment(fragment)
        elapsed = time.monotonic() - started
        pair_counts = Counter()
        status_counts = Counter()
        examples = {}
        for item in joined.input_ports:
            status_counts[item.status] += 1
            pair = (item.prior_canonical_status, item.prior_metadata_association)
            pair_counts[pair] += 1
            if item.status == "MATCHED_EXACT_INPUT_PATH":
                examples.setdefault(pair, {
                    "canonical_status": item.prior_canonical_status,
                    "metadata_association": item.prior_metadata_association,
                    "source": encode(item.original_input),
                    "native_instance": encode(item.native_instance),
                    "native_input": encode(item.input),
                    "metadata_leaf": encode(item.metadata_leaf),
                    "provider_epoch_status": item.provider_epoch_status,
                })
        result = {
            "schema": "scar.native-declaration-input-mixed-status-readback",
            "schema_version": 1,
            "status": "PASS" if joined.view.validation.valid else "FAIL",
            "fragment": encode(fragment),
            "navigation": encode(navigation),
            "metadata_index": encode(joined.metadata_index),
            "source_scope": {
                "original_eto": encode(joined.view.occurrences[0].completion.point.source.artifact),
                "operation_rows": len(joined.view.occurrences),
                "source_shard": 0,
            },
            "counts": {
                "operation_rows": len(joined.view.occurrences),
                "input_ports": len(joined.input_ports),
                "metadata_join_statuses": dict(sorted(status_counts.items())),
                "canonical_and_leaf_disposition_pairs": [
                    {"canonical_status": canonical, "metadata_association": association,
                     "count": count}
                    for (canonical, association), count in sorted(
                        pair_counts.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))
                ],
                "matched_examples": list(examples.values()),
                "normal_validation_valid": joined.view.validation.valid,
                "normal_validation_issue_count": len(joined.view.validation.issues),
            },
            "metadata_scan": joined.measurements,
            "declaration_read": joined.view.measurements,
            "elapsed_seconds": elapsed,
            "claims": {
                "canonical_status_and_leaf_association_are_independent": True,
                "old_metadata_rows_or_canonical_status_changed": False,
                "logical_content_identity_established": False,
                "alias_established": False,
                "normal_completion_established": False,
                "resource_ready_established": False,
            },
        }
        raw = json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2).encode() + b"\n"
        (out / "RESULT.json").write_bytes(raw)
        report = [
            "# Native declaration mixed-status readback",
            "",
            "This readback normally validated the first 256-operation native declaration fragment, then joined its input ports to the retained metadata index. It did not rebuild the native declaration publication or reread the raw ETO.",
            "",
            f"- Fragment SHA256: `{fragment.sha256}`",
            f"- Operation rows / input ports: {len(joined.view.occurrences)} / {len(joined.input_ports)}",
            f"- Normal execution validation: `{joined.view.validation.valid}` with {len(joined.view.validation.issues)} issues",
            f"- Metadata scan: {joined.measurements['metadata_rows']} rows, {joined.measurements['metadata_leaves']} leaves, {joined.measurements['decoded_bytes']} decoded bytes, {joined.measurements['elapsed_seconds']:.3f}s",
            f"- Total elapsed: {elapsed:.3f}s",
            "",
            "## Original status dimensions",
            "",
        ]
        for (canonical, association), count in sorted(pair_counts.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
            report.append(f"- canonical status `{canonical}` / leaf association `{association}`: {count}")
        report.extend([
            "",
            "The canonical boundary status is the original row-level result. The metadata association is the original leaf-level result. Valid pairs follow `NativeInputIndex.finalize`: an available canonical boundary requires `ASSOCIATED`; an unavailable boundary may have `ASSOCIATED` or `CANONICAL_NATIVE_BOUNDARY_UNAVAILABLE` leaves. The join preserves both fields. It makes no content, alias, completion, or readiness claim.",
        ])
        (out / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
        print(json.dumps({"status": result["status"], "result": str(out / "RESULT.json"),
                          "operation_rows": len(joined.view.occurrences),
                          "input_ports": len(joined.input_ports),
                          "pairs": result["counts"]["canonical_and_leaf_disposition_pairs"],
                          "elapsed_seconds": elapsed}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
