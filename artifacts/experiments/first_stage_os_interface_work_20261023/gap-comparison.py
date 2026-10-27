"""Reproduce metadata-only gap comparison; never import original OS/native."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

base = Path(__file__).resolve().parent
old_report = json.loads((base.parent / "first_stage_joined_physical_20261023/resource-frontiers.json").read_bytes())
path = Path(old_report["source"]["path"])
digest, size = hashlib.sha256(), 0
with path.open("rb") as stream:
    while part := stream.read(1_048_576):
        digest.update(part); size += len(part)
assert (digest.hexdigest(), size) == (old_report["source"]["stored_sha256"], old_report["source"]["stored_bytes"])
with gzip.open(path, "rb") as stream:
    text = stream.read(1_000_000).decode("ascii")
decoder, first = json.JSONDecoder(), '{"artifacts":'
assert text.startswith(first)
_, end = decoder.raw_decode(text, len(first))
key = ',"gaps":'
assert text[end:].startswith(key)
gaps, end = decoder.raw_decode(text, end + len(key))
old_groups = Counter(row["code"] for row in gaps)
old_occurrences = Counter()
for row in gaps:
    old_occurrences[row["code"]] += row["occurrences"]
new = json.loads((base / "audit-attempt03-summary.json").read_bytes())
rows = [{"code": key, "old_groups": old_groups[key], "new_groups": new["gap_groups"].get(key, 0),
         "old_occurrences": old_occurrences[key], "new_occurrences": new["gap_occurrences"].get(key, 0)}
        for key in sorted(set(old_groups) | set(new["gap_groups"]))]
result = {"scope": "old published metadata gaps prefix only; no OS/native reimport",
    "old_stored_receipt": {"path": str(path), "bytes": size, "sha256": digest.hexdigest()},
    "decoded_prefix_limit": 1_000_000, "gaps_parse_end": end, "rows": rows,
    "old_groups": sum(old_groups.values()), "new_groups": sum(new["gap_groups"].values()),
    "old_occurrences": sum(old_occurrences.values()), "new_occurrences": sum(new["gap_occurrences"].values()),
    "changes": {"fd_argument_open": "25 failed exec PATH-search returns no longer treated as FD arguments (SCAR importer defect).",
                "fd_binding_open": "3 observed close ends plus1 IO binding now have actual FD producer receipts; no shared-table closure."},
    "whole_model_established": False}
(base / "gap-comparison.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
