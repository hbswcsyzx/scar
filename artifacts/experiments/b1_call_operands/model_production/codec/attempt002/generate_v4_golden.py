from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
assert root.is_dir()
sys.path.insert(0, str(root))
from scar.ir.execution.codec import SCHEMA_VERSION, dumps
from tests.fixtures.execution_content_graphs import content_connection_fixture
assert SCHEMA_VERSION == 4
program, model, value_graphs, evidence_graphs, details = content_connection_fixture(
    consumer="work", duplicate_use=True, observation=True)
for name, module in tuple(sys.modules.items()):
    if name == "scar" or name.startswith(("scar.", "tests.fixtures")):
        path = getattr(module, "__file__", None)
        if path is not None:
            assert Path(path).resolve().is_relative_to(root), (name, path)
payload = dumps(model).encode("utf-8")
Path(sys.argv[2]).write_bytes(payload)
loaded = json.loads(payload)
assert loaded["schema_version"] == 4
modules = {}
for name, module in sorted(sys.modules.items()):
    path = getattr(module, "__file__", None)
    if path is None:
        continue
    resolved = Path(path).resolve()
    if resolved.is_relative_to(root):
        relative = resolved.relative_to(root).as_posix()
        modules[relative] = hashlib.sha256(resolved.read_bytes()).hexdigest()
Path(sys.argv[3]).write_text(json.dumps({
    "loaded_modules": modules,
    "factory": "content_connection_fixture(consumer='work', duplicate_use=True, observation=True)",
    "payload_sha256": hashlib.sha256(payload).hexdigest(),
    "payload_size_bytes": len(payload),
    "schema_version": 4,
}, sort_keys=True, indent=2) + "\n")
