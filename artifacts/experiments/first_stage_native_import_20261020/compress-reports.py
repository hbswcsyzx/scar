"""Compress only this experiment's generated duplicate text reports losslessly."""
import gzip
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
receipts = []
for name in ("cpu-native", "lewm-native"):
    path = root / name / "import-report.json"
    output = Path(str(path) + ".gz")
    raw = path.read_bytes()
    if output.exists():
        raise ValueError("refuse to overwrite compressed report")
    output.write_bytes(gzip.compress(raw, mtime=0))
    if gzip.decompress(output.read_bytes()) != raw:
        raise ValueError("compression verification failed")
    receipts.append({"logical_path": str(path), "actual_path": str(output),
                     "raw_bytes": len(raw), "gzip_bytes": output.stat().st_size,
                     "raw_sha256": hashlib.sha256(raw).hexdigest()})
    path.unlink()
(root / "report-archive.json").write_text(json.dumps(receipts, indent=2) + "\n")
print(json.dumps(receipts))
