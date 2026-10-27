"""Recount inventory facts; this does not validate the recovered dependencies.

Uses only the standard library and never imports/executes the target program.
The existing source inventory remains the canonical fact source.
"""
import collections
import gzip
import hashlib
import json
from pathlib import Path
import sys


def main():
    source, output = map(Path, sys.argv[1:])
    if source.resolve() == output.resolve() or output.exists():
        raise ValueError("audit output must be a fresh path distinct from input")
    if source.stat().st_size > 256_000_000:
        raise ValueError("compressed inventory exceeds audit ceiling")
    opener = gzip.open if source.suffix == ".gz" else open
    with opener(source, "rb") as stream:
        raw = stream.read(256_000_001)
    if len(raw) > 256_000_000:
        raise ValueError("decompressed inventory exceeds audit ceiling")
    document = json.loads(raw)
    if document.get("schema") != "scar.program-inventory":
        raise ValueError("input is not a program inventory")
    statuses, reasons, definitions, atoms, discovery = (collections.Counter() for _ in range(5))
    body_gaps = collections.Counter()
    rows = []
    for file in document["files"]:
        by_id = {json.dumps(row["id"], sort_keys=True): row for row in file["definitions"]}
        definitions.update(row["kind"] for row in file["definitions"])
        atoms.update((row["status"], row["ast_kind"]) for row in file["coverage"])
        for body in file["bodies"]:
            statuses[body["status"]] += 1
            if body["status"] != "LOWERED_WITH_GAPS":
                reasons[(body["status"], body["reason"])] += 1
            metadata = body.get("metadata") or {}
            body_gaps.update(row["kind"] for row in metadata.get("gaps", []))
            definition = by_id[json.dumps(body["definition"], sort_keys=True)]
            rows.append({"path": file["snapshot"]["path"], "definition": definition["qualname"],
                         "kind": definition["kind"], "status": body["status"], "reason": body["reason"]})
    for gap in document["discovery"]["gaps"]:
        discovery[gap["kind"]] += 1
    summary = document["summary"]
    if dict(statuses) != summary["body_statuses"]:
        raise ValueError("body records disagree with inventory summary")
    if sum(definitions.values()) != summary["definitions"]:
        raise ValueError("definition records disagree with inventory summary")
    with source.open("rb") as stream:
        input_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    result = {"schema": "scar.first-stage-inventory-audit", "schema_version": 1,
              "input": str(source.resolve()), "input_sha256": input_sha256,
              "scope": "recount of existing automatic inventory; not dependency or whole-model verification",
              "target_executed": False, "whole_model_established": False,
              "summary": summary, "definition_kinds": dict(sorted(definitions.items())),
              "body_statuses_recounted": dict(sorted(statuses.items())),
              "first_failure_or_not_attempted_reasons": [
                  {"status": status, "reason": reason, "count": count}
                  for (status, reason), count in reasons.most_common()],
              "body_gap_kinds": dict(sorted(body_gaps.items())),
              "coverage_by_ast_status": [{"status": status, "ast_kind": kind, "count": count}
                                         for (status, kind), count in sorted(atoms.items())],
              "discovery_gap_kinds": dict(sorted(discovery.items())), "bodies": rows}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"audit": str(output), "body_statuses": result["body_statuses_recounted"],
                      "first_failure_or_not_attempted_reasons": result["first_failure_or_not_attempted_reasons"],
                      "whole_model_established": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
