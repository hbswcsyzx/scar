"""Small saved-declaration and synthetic-source checks; no original raw read."""
import ast
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

from scar.ir.execution.codec import loads as load_execution
from scar.ir.execution.content import NativeInputRef
from scar.ir.execution.native_port_protocol import _native_port_order_errors
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import validate
from scar.ir.program.codec import loads as load_program
from scar.ir.program.model import ReferenceValue
from scar.ir.program.providers import ProviderArtifact
from scar.ir.v2.codec import values_from_dict, evidence_from_dict
from scar.trace.native_capture_batch import NativeCaptureBatchBudget, _SourceIndex, _unavailable_physical
from scar.trace.native_protocol import NativeProtocolWindow

BASE = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SAVED = Path('/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_native_protocol_bridge_attempt03_20261023/result')

checks = []
for name in ('scar/trace/native_capture_batch.py', 'scar/ir/execution/native_port_protocol.py'):
    ast.parse((BASE / name).read_text())
checks.append('new producer and order module AST')
for kwargs in ({'first_sequence': 2}, {'max_sequences': 17}):
    try:
        NativeProtocolWindow(**kwargs)
    except ValueError:
        pass
    else:
        raise AssertionError('old prefix limit changed')
checks.append('old prefix start and size rejection preserved')
program = load_program((SAVED / 'program.json').read_text())
original = load_execution((SAVED / 'execution.json').read_text())
signatures = json.loads((SAVED / 'native-interface.json').read_text())['interfaces']
activation = next(a for a in original.activations if a.id.value.endswith(':9'))
segments = tuple(s for s in original.segments if s.activation == activation.id)
segment_ids = {s.id for s in segments}
visits = tuple(v for v in original.visits if v.segment in segment_ids)
visit_ids = {v.id for v in visits}
operations = tuple(o for o in original.operations if o.visit in visit_ids)
operation_ids = {o.id for o in operations}
values = tuple(v for v in original.values if v.origin in visit_ids)
value_ids = {v.id for v in values}
model = replace(original, activations=(activation,), segments=segments, visits=visits, operations=operations,
    values=values, uses=tuple(u for u in original.uses if u.operation in operation_ids),
    transfers=tuple(t for t in original.transfers if t.operation in operation_ids),
    evidence_bindings=tuple(b for b in original.evidence_bindings if b.operation in operation_ids),
    denotations=tuple(d for d in original.denotations if d.value in value_ids))
sig = activation.region.value.removeprefix('aten-interface:')
interfaces = [{'signature_id': sig, 'sequence': 9, 'signature': signatures[sig]}]
assert not _native_port_order_errors(program, model, interfaces, model.runs[0].id.value, definition_signatures=signatures)
assert any(e[0] == 'definition_artifact' for e in _native_port_order_errors(program, model, interfaces, model.runs[0].id.value))
checks.append('one actual activation validates against shared four-signature catalog')
definitions = {v.id: v for v in program.values}
boundary = next(b for b in program.native_boundaries if b.region == activation.region and len(b.inputs) >= 2
    and all(type(definitions[s.port.value]) is ReferenceValue for s in b.inputs[:2]))
slots = list(boundary.inputs)
slots[0] = replace(slots[0], port=boundary.inputs[1].port)
slots[1] = replace(slots[1], port=boundary.inputs[0].port)
wrong_boundary = replace(boundary, inputs=tuple(slots))
wrong_program = replace(program, native_boundaries=tuple(wrong_boundary if b.id == boundary.id else b for b in program.native_boundaries))
denotations = []
for d in model.denotations:
    b = d.basis
    if type(b) is NativeInputRef and b.boundary == boundary.id and b.position in (0, 1):
        formal = wrong_boundary.inputs[b.position].port.value
        actual = next(v for v in model.values if v.origin == b.entry and v.value == formal)
        d = replace(d, value=actual.id)
    denotations.append(d)
wrong_model = replace(model, snapshot=snapshot_for(wrong_program, 'memory:batch-api-counterexample'), denotations=tuple(denotations))
vg = values_from_dict(json.loads((SAVED / 'source-values.json').read_text()))
eg = evidence_from_dict(json.loads((SAVED / 'source-evidence.json').read_text()))
report = json.loads((SAVED / 'report.json').read_text())
kwargs = {'value_graphs': {report['artifacts']['values_projection']['sha256']: vg},
          'evidence_graphs': {report['artifacts']['evidence_projection']['sha256']: eg}}
assert validate(model, program, **kwargs).valid
assert validate(wrong_model, wrong_program, **kwargs).valid
errors = _native_port_order_errors(wrong_program, wrong_model, interfaces, model.runs[0].id.value, definition_signatures=signatures)
assert sum(e[0] == 'native_core_order' for e in errors) == 2
assert sum(e[0] == 'actual_native_order' for e in errors) == 2
checks.append('new own snapshot generic-valid permutation has two static and two actual order errors')
tiny = OUT / 'synthetic-source-check'
tiny.mkdir()
owner = _SourceIndex(tiny, NativeCaptureBatchBudget(), None)
def attrs(**items):
    return [{'name': k, 'value': v} for k, v in items.items()]
nodes = [{'id': 2, 'ctrl_deps': 3, 'name': 'child', 'attrs': attrs(rf_id=2)},
         {'id': 3, 'ctrl_deps': 1, 'name': 'later-parent', 'attrs': attrs(rf_id=3)},
         {'id': 1, 'ctrl_deps': 1, 'name': '[pytorch|profiler|execution_trace|process]', 'attrs': attrs(rf_id=0, tid=0, scope=7)}]
raw = json.dumps({'schema': '1.1.1-chakra.0.0.4', 'pid': 11, 'nodes': nodes}).encode()
path = tiny / 'tiny-eto.json'
path.write_bytes(raw)
artifact = ProviderArtifact('memory:tiny-eto', sha256(raw).hexdigest(), len(raw), 'pytorch.execution-trace.v1')
owner.read_eto(artifact, path, 11)
assert owner.node_ordinals[1] == 2 and owner.parents[2] == 3
checks.append('full synthetic ETO parser handles later parents and final root')
rows = [{'index': 1, 'process_id': 11, 'sequence': 2, 'kind': 'DISPATCH_BEGIN', 'operator': 'synthetic'},
        {'index': 2, 'process_id': 11, 'sequence': 4, 'kind': 'DISPATCH_END', 'outcome': 'RAISED'}]
raw = b''.join(json.dumps(r).encode() + b'\n' for r in rows)
path = tiny / 'tiny-dispatch.jsonl'
path.write_bytes(raw)
artifact = ProviderArtifact('memory:tiny-dispatch', sha256(raw).hexdigest(), len(raw), 'scar.dispatch-observation.events.v1')
owner.read_lines('dispatch', artifact, path, 11)
owner.base = {'artifacts': {'dispatch': {'uri': artifact.uri, 'sha256': artifact.sha256, 'size_bytes': artifact.size_bytes, 'schema': artifact.schema}}}
assert set(owner.groups) == {2, 4}
assert owner.inventory(2)['outcome'] is None and owner.inventory(4)['operator'] is None
checks.append('inventory retains actual sparse sequences and missing actual roles without fabricated rows')
row = owner.db.execute("SELECT payload FROM records WHERE kind='node' AND key='2'").fetchone()[0]
owner.db.execute("UPDATE records SET payload=? WHERE kind='node' AND key='2'", (b'{}',))
try:
    owner.get('node', 2)
except ValueError:
    pass
else:
    raise AssertionError('modified navigation envelope accepted')
owner.db.execute("UPDATE records SET payload=? WHERE kind='node' AND key='2'", (row,))
owner.db.commit()
owner.db.close()
checks.append('live private navigation seal rejects changed payload')
print(json.dumps({'status': 'SMALL_API_CHECK_PASS', 'checks': checks,
    'counterexample_order_errors': errors, 'original_raw_reads': 0, 'new_runtime_owned_evidence_created': False,
    'target_executions': 0, 'full_gate_run': False}, sort_keys=True, indent=2))
