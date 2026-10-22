"""Automatically revisit actual terminal blocker families, never execute target.

This is a bounded diagnostic cohort, not a replacement for whole inventory or
an optimization detector. Input is the immediately preceding real inventory.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path

from scar.analysis.program_lowering import prepare_source
from scar.ir.program.codec import dumps
from scar.ir.record_codec import decode, encode
from scar.ir.v2.common import SourceReference


DETAILS = {
    "structured heap/global/destructuring writes require their own typed protocol",
    "structured expression protocol still required for BoolOp",
    "structured expression protocol still required for IfExp",
}


def main():
    from scar.ir.program.functions import BodyLoweringProfile
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(exist_ok=False)
    with gzip.open(args.inventory, "rt") as stream:
        document = json.load(stream)
    assert document["schema_version"] == 8
    groups = defaultdict(list)
    for file in document["files"]:
        definitions = {row["id"]["wire"]: row for row in file["definitions"]}
        for body in file["bodies"]:
            terminal = [gap for gap in (body["metadata"] or {}).get("gaps", ())
                        if gap["kind"] in {"UNSUPPORTED_SYNTAX", "UNSUPPORTED_SIGNATURE", "SOURCE_MAPPING", "BUDGET"}]
            if body["status"] == "UNSUPPORTED" and terminal and terminal[-1]["detail"] in DETAILS:
                groups[file["snapshot"]["path"]].append((file, definitions[body["definition"]["wire"]], terminal[-1]["detail"]))
    counts, reasons, families, rows = Counter(), Counter(), Counter(), []
    with gzip.open(args.out / "bodies.jsonl.gz", "wt") as archive:
        for path, requests in groups.items():
            namespace = requests[0][0]["context"]["namespace_root"]
            context = prepare_source(path, project_root=namespace)
            for file, definition, detail in requests:
                row = {"path": path, "definition": definition["qualname"], "original_terminal": detail}
                try:
                    assert context.semantics.sources[path].fingerprint == file["snapshot"]["fingerprint"]
                    body = context.lower(definition["qualname"], source=decode(SourceReference, definition["source"]),
                        max_operations=10000, expand_candidates=False, profile=BodyLoweringProfile.STRUCTURED_ENV)
                    row.update(status="LOWERED_WITH_GAPS" if body.graph else "UNSUPPORTED",
                               construction_operations=body.operations_emitted,
                               gaps=[{"kind": gap.kind.value, "detail": gap.detail} for gap in body.metadata.gaps])
                    archive.write(json.dumps(dict(row, graph=json.loads(dumps(body.graph)) if body.graph else None,
                        metadata=encode(body.metadata), interface=encode(body.interface), structured=encode(body.structured))) + "\n")
                    terminal = [gap for gap in row["gaps"] if gap["kind"] in
                        {"UNSUPPORTED_SYNTAX", "UNSUPPORTED_SIGNATURE", "SOURCE_MAPPING", "BUDGET"}]
                    row["next_terminal"] = terminal[-1]["detail"] if terminal else None
                except (ValueError, TypeError, KeyError, AttributeError, SyntaxError, RecursionError) as error:
                    row.update(status="ERROR", error=type(error).__name__ + ": " + str(error), next_terminal=str(error))
                counts[row["status"]] += 1
                families[detail] += 1
                reasons[row["next_terminal"] or row["status"]] += 1
                rows.append(row)
                print(json.dumps({key: row.get(key) for key in ("path", "definition", "status", "next_terminal")}), flush=True)
    result = {"scope": "automatic diagnostic cohort from three observed terminal families; not whole-program inventory",
              "source_files": len(groups), "selected_bodies": len(rows), "families": dict(families),
              "counts": dict(counts), "next_terminals": dict(reasons), "bodies": rows,
              "max_operations_per_body": 10000, "target_executed": False,
              "whole_program_graph_established": False, "runtime_environments_verified": False,
              "transformation_authorized": False}
    (args.out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
