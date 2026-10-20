"""Compare original audit hashes with archives using canonical path keys."""
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
audit = json.loads((root / "capture-audit.json").read_text())
archive = json.loads((root / "archive-index.json").read_text())
indexed = {str(Path(row["logical_path"]).resolve()): row for row in archive["files"]}
checked = set()
sources = audit["sources"] + audit["os"]["files"] + audit["operands"]["base_manifest"]
for source in sources:
    key = str(Path(source.get("logical_path", source.get("path"))).resolve())
    if key in indexed:
        assert source["raw_sha256"] == indexed[key]["raw_sha256"]
        checked.add(key)
operand = str(root / f"trace/call-operands.{audit['pid']}.jsonl")
assert set(indexed) - checked == {operand}
assert indexed[operand]["raw_bytes"] == audit["operands"]["bytes"]
for row in archive["files"]:
    with Path(row["actual_path"]).open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == row["gzip_sha256"]
assert archive["verified_roundtrip"] is True
result = {"archive_matches_pre_archive_audit": True, "checked_file_hashes": len(checked),
          "operand_bytes_match_metadata": True, "verified_compressed_file_hashes": len(indexed),
          "os_trace_files": len(audit["os"]["files"]), "os_record_lines": audit["os"]["lines"],
          "raw_bytes": archive["raw_bytes"], "compressed_bytes": archive["compressed_bytes"],
          "whole_model_established": False,
          "initial_receipt_correction": "normalize relative audit paths before comparing to absolute archive keys"}
(root / "archive-audit-check.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
