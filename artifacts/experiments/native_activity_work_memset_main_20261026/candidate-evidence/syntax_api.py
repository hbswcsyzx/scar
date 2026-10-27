"""Synthetic metadata and existing typed codec API only; no acquisition."""
import ast
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
TREE = HERE.parents[3]
sources = []
for name in ("scar/trace/native_work_bridge.py", "scar/ir/execution/native_work_protocol.py"):
    path = TREE / name; payload = path.read_bytes(); ast.parse(payload, filename=str(path))
    sources.append({"path": str(path), "bytes": len(payload), "sha256": sha256(payload).hexdigest()})

from scar.trace.native_work_bridge import _reason, NativeWorkBudget
from scar.ir.execution.native_work_protocol import activity_actor, make_records
from scar.ir.execution.ids import RunID, ProcessInstanceID
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode, encode
from scar.ir.v2.common import Completeness

event = {"cat": "gpu_memset", "ph": "X", "ts": 1.0, "dur": 0.1, "pid": 0, "tid": 7,
         "args": {"device": 0, "context": 1, "stream": 7, "bytes": 16}}
if _reason(event) is not None or activity_actor(event) != (0, 1, 7):
    raise ValueError("Memset4 metadata admission/actor API differs")
artifact = ProviderArtifact("/synthetic-metadata-only/source.evidence.json", "0" * 64, 1, "scar.ir.v2.evidence")
rows = make_records(RunID("synthetic-only"), ProcessInstanceID("synthetic-only:process"),
    artifact, 0, {"id": {"value": "synthetic-only-original"}},
    {"reference": "synthetic-only-original-source"})
for row in rows:
    if decode(type(row), encode(row)) != row:
        raise ValueError("existing typed record codec roundtrip differs")
if rows[0].origin.point == rows[2].observed_at or rows[0].effects_coverage is not Completeness.UNKNOWN:
    raise ValueError("endpoint separation/UNKNOWN coverage changed")
report = {"status": "SYNTAX_AND_SYNTHETIC_TYPED_API_ONLY", "sources": sources,
    "memset_metadata_admission": True, "distinct_start_end_sources": True,
    "existing_typed_records": [type(row).__name__ for row in rows],
    "effects_coverage": rows[0].effects_coverage.value, "budgets_unchanged": vars(NativeWorkBudget()),
    "owner_acquisitions": 0, "raw_reads": 0, "target_executions": 0,
    "torch_imported": "torch" in sys.modules, "native_qualification_granted": False}
with (HERE / "syntax-api.json").open("xb") as stream:
    stream.write(json.dumps(report, sort_keys=True, indent=2).encode() + b"\n")
print(json.dumps({key: report[key] for key in ("status", "memset_metadata_admission", "torch_imported")}))
