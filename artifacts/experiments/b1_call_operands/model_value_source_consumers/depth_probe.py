"""Check the default bound including detached public output, on frozen sources."""
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback

from scripts.run_gate import fingerprint
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.stored_value_projection import _DEPTH_LIMIT
from tests.fixtures.execution_value_sources import layered_value_sources_execution

label = sys.argv[1]
out = Path(__file__).with_name('depth-probe-' + label + '.json')
assert not out.exists()
before, sources = fingerprint()
start = time.monotonic()
record = {'analysis_depth_limit': _DEPTH_LIMIT, 'length': 40, 'budget_limit': 2097152,
          'native_target_executions': 0, 'transformation_authorized': False}
try:
    graph, model, details = layered_value_sources_execution(mode='owner-chain', length=40, instances=1)
    example = details['examples'][0]
    view = ExecutionIndex(model, graph).value_source_pair(example['source'].id, example['target'].id,
                                                       budget=record['budget_limit'])
    assert view['match'] is None and view['budget']['truncated'] and view['cursor']
    assert len(view['read_inventory']) == len(view['write_inventory']) == 40
    record.update(returncode=0, outcome='BOUNDED_UNKNOWN_WITH_DETACHED_PUBLIC_OUTPUT',
                  match=view['match'], budget=view['budget'], cursor_present=True)
except Exception as exc:
    record.update(returncode=1, outcome='FAILED', error_type=type(exc).__name__,
                  error=str(exc), traceback=traceback.format_exc())
after, final = fingerprint()
record.update(source_sha256_before=before, source_sha256_after=after,
              source_unchanged=sources == final, source_files=len(sources), sources=sources,
              duration_seconds=time.monotonic() - start,
              script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
out.write_text(json.dumps(record, indent=2) + '\n')
assert sources == final
print(json.dumps({key: value for key, value in record.items() if key not in ('sources', 'traceback')}))
raise SystemExit(record['returncode'])
