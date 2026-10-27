from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from scar.analysis.retained_source_call_publication import (
    read_retained_source_call_publication,
    read_retained_source_call_shard,
)


def load_publication(path: str, expected_sha256: str):
    started = perf_counter()
    index = read_retained_source_call_publication(
        path, expected_manifest_sha256=expected_sha256
    )
    bindings = {}
    stored_bytes = decoded_bytes = 0
    for ref in index.shard_refs:
        shard = read_retained_source_call_shard(index, ref.shard_index)
        stored_bytes += Path(shard.path).stat().st_size
        decoded_bytes += next(
            item.decoded_bytes for item in index.shard_refs
            if item.shard_index == ref.shard_index
        )
        for binding in shard.model.bindings:
            attempt = binding.target.attempt_index
            if attempt in bindings:
                raise ValueError(f"duplicate selected attempt index: {attempt}")
            bindings[attempt] = binding
    return index, bindings, {
        "shards_read": len(index.shard_refs),
        "bindings_read": len(bindings),
        "shard_stored_bytes": stored_bytes,
        "shard_decoded_bytes": decoded_bytes,
        "normal_reader_seconds": perf_counter() - started,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--new-manifest", required=True)
    parser.add_argument("--new-sha256", required=True)
    parser.add_argument("--old-manifest", required=True)
    parser.add_argument("--old-sha256", required=True)
    parser.add_argument("--local-result", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    new_index, new_bindings, new_cost = load_publication(
        args.new_manifest, args.new_sha256
    )
    old_index, old_bindings, old_cost = load_publication(
        args.old_manifest, args.old_sha256
    )
    old_missing = sorted(set(old_bindings) - set(new_bindings))
    old_changed = sorted(
        attempt for attempt, prior in old_bindings.items()
        if attempt in new_bindings and prior != new_bindings[attempt]
    )

    local = json.loads(Path(args.local_result).read_text("utf-8"))
    local_attempts = sorted(
        row["attempt_index"] for row in local["local_bindings"]
    )
    added_present = sorted(set(local_attempts) & set(new_bindings))
    added_missing = sorted(set(local_attempts) - set(new_bindings))
    totals = new_index.manifest["totals"]
    issues = new_index.manifest["candidate_issues"]

    result = {
        "schema": "scar.source-call-port-publication-reconcile",
        "schema_version": 1,
        "status": "PASS_ALL_SHARD_READBACK_AND_PRIOR_PRESERVATION"
        if not old_missing and not old_changed and not added_missing
        else "READBACK_WITH_DIFFERENCES",
        "new_publication": {
            "manifest_path": str(Path(args.new_manifest).absolute()),
            "manifest_sha256": new_index.manifest_sha256,
            "candidate_coverage_complete": new_index.candidate_coverage_complete,
            "candidate_totals": totals,
            "candidate_issues": issues,
            "readback": new_cost,
        },
        "old_publication": {
            "manifest_path": str(Path(args.old_manifest).absolute()),
            "manifest_sha256": old_index.manifest_sha256,
            "readback": old_cost,
        },
        "prior_binding_preservation": {
            "old_binding_count": len(old_bindings),
            "missing_attempt_count": len(old_missing),
            "changed_binding_count": len(old_changed),
            "missing_attempt_indices": old_missing,
            "changed_attempt_indices": old_changed,
        },
        "abi11_inclusion": {
            "local_case_count": len(local_attempts),
            "included_count": len(added_present),
            "missing_count": len(added_missing),
            "included_attempt_indices": added_present,
            "missing_attempt_indices": added_missing,
        },
        "whole_program_complete": False,
        "full_attempt_coverage_established": False,
        "body_replay_performed": False,
    }
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False) + "\n"
    out = Path(args.out).absolute()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as stream:
        stream.write(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result["status"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
