"""One synthetic typed API check; never acquires or claims native authority."""
import ast
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
TREE = HERE.parents[3]
paths = [TREE / "scar/trace/native_work_bridge.py", TREE / "scar/ir/execution/native_work_protocol.py", HERE / "gate.py"]
pins = []
for path in paths:
    data = path.read_bytes(); ast.parse(data, filename=str(path))
    pins.append({"path": str(path), "bytes": len(data), "sha256": sha256(data).hexdigest()})
from scar.trace.native_work_bridge import NativeWorkBudget
from scar.ir.execution.native_work_protocol import make_records
from scar.ir.execution.ids import RunID, ProcessInstanceID
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode, decode

run, process = RunID("synthetic-api"), ProcessInstanceID("synthetic-api:process")
artifact = ProviderArtifact("/synthetic-api/evidence.json", "0" * 64, 1, "scar.ir.v2.evidence")
records = make_records(run, process, artifact, 0, {"id": {"value": "synthetic-original"}},
                       {"reference": "synthetic-original-source"})
for record in records:
    if decode(type(record), encode(record)) != record:
        raise ValueError("existing typed record codec roundtrip differs")
if records[0].origin.point == records[2].observed_at:
    raise ValueError("start/end points were collapsed")
report = {"status": "SYNTAX_AND_TYPED_API_ONLY", "sources": pins,
    "existing_typed_records": [type(record).__name__ for record in records],
    "distinct_start_end_sources": True, "budgets": vars(NativeWorkBudget()),
    "torch_imported": "torch" in sys.modules, "raw_reads": 0,
    "owner_acquisitions": 0, "target_executions": 0, "native_qualification_granted": False}
with (HERE / "syntax-api.json").open("xb") as stream:
    stream.write(json.dumps(report, sort_keys=True, indent=2).encode() + b"\n")
print(json.dumps({key: report[key] for key in ("status", "torch_imported", "raw_reads")}))
