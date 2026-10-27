"""Losslessly archive only this experiment's closed raw recorder files."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys


def digest(path, compressed=False):
    with (gzip.open(path, "rb") if compressed else path.open("rb")) as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


for argument in sys.argv[1:]:
    root = Path(argument).resolve()
    if not root.name.startswith("first_stage_lewm_capture_20261020"):
        raise ValueError("only this task's owned capture directories may be archived")
    index = root / "archive-index.json"
    if index.exists():
        raise ValueError("archive index already exists")
    selected = set((root / "os").glob("syscalls.*"))
    for pattern in ("call-*.jsonl", "execution-trace.*.json", "kineto.*.json"):
        selected.update((root / "trace").glob(pattern))
    rows = []
    for path in sorted(selected):
        if path.suffix == ".gz" or path.stat().st_size == 0:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("raw evidence must be a regular owned file")
        output = Path(str(path) + ".gz")
        before = path.stat()
        expected = digest(path)
        with output.open("xb") as stream:
            with gzip.GzipFile(filename="", fileobj=stream, mode="wb", compresslevel=3, mtime=0) as archive:
                with path.open("rb") as source:
                    shutil.copyfileobj(source, archive, 1024 * 1024)
        if digest(output, compressed=True) != expected:
            raise ValueError("archive roundtrip differs: " + str(path))
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("raw evidence changed while archiving")
        rows.append({"logical_path": str(path), "actual_path": str(output),
                     "raw_sha256": expected, "raw_bytes": before.st_size,
                     "compressed_bytes": output.stat().st_size,
                     "gzip_sha256": digest(output)})
        # Only the just-verified generated duplicate is removed. Readers use
        # the existing logical-path -> .gz resolver, with raw bytes unchanged.
        path.unlink()
    result = {"schema": "scar.lossless-capture-archive", "schema_version": 1,
              "verified_roundtrip": True, "files": rows,
              "raw_bytes": sum(row["raw_bytes"] for row in rows),
              "compressed_bytes": sum(row["compressed_bytes"] for row in rows)}
    index.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"root": str(root), "files": len(rows),
                      "raw_bytes": result["raw_bytes"], "compressed_bytes": result["compressed_bytes"]}))
