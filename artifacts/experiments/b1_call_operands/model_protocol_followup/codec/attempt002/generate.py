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
encoded = wire.encode("ascii")
payload_path = Path(__file__).resolve().parents[1] / "oracle-v19" / "program_graph_v19_frozen.json"
payload_path.write_bytes(encoded)
print(json.dumps({
    "schema_version": document["schema_version"],
    "bytes": len(encoded),
    "sha256": hashlib.sha256(encoded).hexdigest(),
    "connection_tables": [
        name for name in ("protocol_call_inputs", "protocol_result_consumers", "protocol_bindings")
        if document[name]
    ],
    "path": str(payload_path),
}, sort_keys=True))
