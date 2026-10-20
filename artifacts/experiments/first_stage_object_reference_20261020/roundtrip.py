"""Read the actual capability-versioned bundle back through the public codec."""
import gzip
from hashlib import sha256
import json
from pathlib import Path

from scar.ir.v2 import bundle_from_dict, canonical_json

root = Path(__file__).resolve().parent
payload = gzip.decompress((root / "evidence-bundle.json.gz").read_bytes())
bundle = bundle_from_dict(json.loads(payload))
assert bundle.assert_valid()["valid"]
assert canonical_json(bundle).encode() == payload
report = {"schema": "scar.object-reference-codec-replay", "valid": True,
          "bundle_sha256": sha256(payload).hexdigest(),
          "objects": len(bundle.values.objects), "logical_versions": len(bundle.values.versions),
          "whole_model_established": False, "canonical_bytes_preserved": True}
(root / "roundtrip-result.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
