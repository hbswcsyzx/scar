"""Small source-contract and SQLite-cap checks, without original raw input."""
import ast
import copy
from pathlib import Path
import json
import sqlite3
from scar.trace.native_capture_batch import (
    _SourceIndex, _check_group_identity, _unavailable_physical, NativeCaptureBatchBudget,
)

OUT = Path(__file__).resolve().parent
BASE = OUT.parents[2]
nonce, pid, seq = '0' * 32, 11, 2
span, output = (f'scar-dispatch:{nonce}:{pid}:{seq}:{phase}' for phase in ('span', 'output'))
obs = {'process_id': pid, 'native_tid': 11, 'python_ident': 22, 'tensor_references': []}
rows = [{'index': 1, 'process_id': pid, 'sequence': seq, 'kind': 'DISPATCH_BEGIN', 'marker': span,
         'observation': obs, 'operator': 'aten.copy_.default', 'slot_gaps': []},
        {'index': 2, 'process_id': pid, 'sequence': seq, 'kind': 'DISPATCH_OUTPUT', 'marker': output,
         'observation': obs, 'slot_gaps': []},
        {'index': 3, 'process_id': pid, 'sequence': seq, 'kind': 'DISPATCH_END', 'outcome': 'RETURNED',
         'span_enter_returned': True, 'output_marker': output}]
def attrs(**values):
    return [{'name': k, 'value': v} for k, v in values.items()]
nodes = [{'id': 2, 'ctrl_deps': 1, 'name': span, 'attrs': attrs(tid=7, rf_id=1)},
         {'id': 3, 'ctrl_deps': 2, 'name': output, 'attrs': attrs(tid=7, rf_id=2)},
         {'id': 4, 'ctrl_deps': 2, 'name': 'aten::copy_', 'attrs': attrs(tid=7, rf_id=3,
             op_schema='aten::copy_(Tensor(a!) self, Tensor src, bool non_blocking=False) -> Tensor(a!)')}]
source = {'pid': pid, 'nonce': nonce, 'owner_native_tid': 11, 'owner_python_ident': 22,
          'dispatch': rows, 'nodes': nodes, 'physical': []}
checks = []
def rejected(data):
    try:
        _check_group_identity(data)
    except ValueError:
        return
    raise AssertionError('known identity contradiction accepted')
bad = copy.deepcopy(source)
bad['dispatch'][0]['marker'] = span.replace(nonce, '1' * 32)
rejected(bad)
checks.append('wrong dispatch nonce rejects before missing physical frontier')
bad = copy.deepcopy(source)
bad['nodes'][1]['ctrl_deps'] = 99
rejected(bad)
checks.append('known output parent mismatch rejects without physical rows')
bad = copy.deepcopy(source)
bad['nodes'][2]['attrs'][0]['value'] = 8
rejected(bad)
checks.append('known matching native child thread mismatch rejects without physical rows')
bad = copy.deepcopy(source)
bad['physical'] = [{'kind': 'MARKER', 'marker': span, 'gaps': ['missing_slot'], 'dispatch_source_line': 99}]
rejected(bad)
checks.append('gapped physical marker cannot hide wrong original dispatch line')
assert _check_group_identity(source) is None
assert _unavailable_physical(source)['reason'] == 'PHYSICAL_MARKER_UNAVAILABLE'
checks.append('valid identities with no physical witness remain explicit absence')
missing = copy.deepcopy(source)
missing['nodes'].pop()
assert _check_group_identity(missing)['reason'] == 'DIRECT_SCHEMA_NATIVE_CHILD_UNAVAILABLE'
checks.append('zero matching native children is explicit absence')
bad = copy.deepcopy(source)
child = copy.deepcopy(bad['nodes'][-1])
child['id'] = 5
bad['nodes'].append(child)
rejected(bad)
checks.append('multiple matching native children reject')
tiny = OUT / 'page-cap-check'
tiny.mkdir()
budget = NativeCaptureBatchBudget(max_index_bytes=16_384)
owner = _SourceIndex(tiny, budget, None)
assert owner.db.execute('PRAGMA page_size').fetchone()[0] == 4096
assert owner.db.execute('PRAGMA max_page_count').fetchone()[0] == 4
try:
    owner.put('oversized-for-db', 'one', 0, {'payload': 'x' * 65_536})
except sqlite3.OperationalError as error:
    assert error.sqlite_errorcode == sqlite3.SQLITE_FULL
else:
    raise AssertionError('SQLite index grew beyond page cap')
owner.db.close()
assert owner.path.stat().st_size <= budget.max_index_bytes
checks.append('SQLite returns SQLITE_FULL before index grows beyond 16 KiB test cap')
tree = ast.parse((BASE / 'scar/trace/native_protocol.py').read_text())
prepared = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_prepare_projection')
assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == '_write' for n in ast.walk(prepared))
checks.append('projection preparation has no publication call')
print(json.dumps({'status': 'IDENTITY_AND_PREWRITE_BUDGET_CHECK_PASS', 'checks': checks,
                  'sqlite_version': sqlite3.sqlite_version,
                  'original_raw_reads': 0, 'archive_chunk_reads': 0, 'full_gate_run': False,
                  'sqlite_official_references': ['https://www.sqlite.org/pragma.html#pragma_max_page_count', 'https://www.sqlite.org/limits.html']},
                 sort_keys=True, indent=2))
