from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

from scar.analysis.call_operand_reader import read_call_operands
from scar.ir.program.call_edges import CallEdgeBudget
from scar.ir.program.call_operands import CallOperandBudget

HERE = Path(__file__).resolve().parent
trace = HERE/'capture/trace'
started = time.monotonic()
observed = read_call_operands(trace,HERE/'project',
    budget=CallOperandBudget(max_raw_bytes=64_000_000,max_metadata_bytes=8_000_000),
    frame_budget=CallEdgeBudget(max_raw_bytes=64_000_000))
meta = json.loads(next(trace.glob('call-meta.*.json')).read_bytes())
sources = json.loads(next(trace.glob('captured-source-meta.*.json')).read_bytes())
coordinates = json.loads((HERE/'capture/capture-coordinates.json').read_bytes())
archive = json.loads((HERE/'capture/archive-index.json').read_bytes())
qualnames = sorted({capture.code.qualname for capture in observed.frame_scan.captures})
assert {'main','transform','dedent'} <= set(qualnames)
assert meta['dropped_events'] == meta['dropped_codes'] == 0 and meta['errors'] == []
assert all(m.instructions == 0 for m in observed.metadata)
source_member = coordinates['captured_python_source_membership']
assert source_member['compiler_match'] == 'NOT_CHECKED' and source_member['loader_bytes_observed'] is False
source_rows = [x for x in archive['files'] if Path(x['logical_path']).name.startswith('captured-sources.')]
receipt = dict(status='ACTUAL_PROGRAM_PORTS_OPERAND_AND_COORDINATES_PASS_WITH_OPEN',
    elapsed_s=time.monotonic()-started, capture_exit=0,
    frame_entries=len(observed.entries),frame_exits=len(observed.exits),
    call_attempts=len(observed.attempts),instructions=sum(x.instructions for x in observed.metadata),
    ordinary_reader_issues=[asdict(x) for x in observed.issues],
    scoped_gaps=Counter(x.reason for x in observed.gaps),
    observed_qualnames=qualnames, source_membership=source_member,
    source_status=Counter(x['status'] for x in sources['files']),
    source_frontiers=Counter(x['frontier'] for x in sources['files'] if x['frontier'] is not None),
    source_raw_bytes_read=sources['source_raw_bytes_read'],
    source_normalized_bytes=sum(x.get('normalized_bytes',0) for x in sources['files']),
    source_encoded_jsonl_bytes=sources['file']['size_bytes'],source_archive=source_rows,
    coordinates_receipt=dict(uri=str(HERE/'capture/capture-coordinates.json'),
        sha256=hashlib.sha256((HERE/'capture/capture-coordinates.json').read_bytes()).hexdigest(),
        size_bytes=(HERE/'capture/capture-coordinates.json').stat().st_size),
    source_body_or_runtime_content_identity_established=False,whole_model_established=False)
with (HERE/'READBACK.json').open('x') as stream:
    json.dump(receipt,stream,indent=2)
print(json.dumps({k:receipt[k] for k in ('status','elapsed_s','frame_entries','frame_exits',
    'call_attempts','instructions','source_status','source_frontiers')}))
