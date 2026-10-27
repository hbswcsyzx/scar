from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scar.ir.program.codec import dumps
from tests.fixtures.program_continuation_graphs import (
    continuation_site_program,
    with_continuation_connections,
)


graph, details = continuation_site_program(
    kind="delegate", request="send", exhaustion=True
)
graph, _ = with_continuation_connections(graph, details)
wire = dumps(graph)
document = json.loads(wire)
assert document["schema_version"] == 19
assert document["protocol_call_inputs"]
assert document["protocol_result_consumers"]
assert document["protocol_bindings"]
root = Path(__file__).resolve().parent
payload_path = root / "program_graph_v19_frozen.json"
payload_path.write_bytes(wire.encode("ascii"))
print(json.dumps({
    "schema_version": document["schema_version"],
    "bytes": len(wire.encode("ascii")),
    "sha256": hashlib.sha256(wire.encode("ascii")).hexdigest(),
    "path": payload_path.name,
}, sort_keys=True))
