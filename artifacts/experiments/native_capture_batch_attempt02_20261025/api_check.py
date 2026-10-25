"""Pure declaration/profile checks; old SQLite is diagnosis-only, never owner."""
import ast
import copy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

from scar.ir.execution.codec import dumps as execution_dumps
from scar.ir.execution.common import Unresolved, EvidencePoint
from scar.ir.execution.content import NativeInputRef, ObjectIdentity
from scar.ir.execution.ids import RunID
from scar.ir.v2.ids import OperationInstanceID
from scar.ir.execution.native_port_protocol import (
    PROFILE_V2, replay_batch_interfaces, replay_interfaces, _native_port_order_errors,
    _require_native_port_order, NativePortOrderError,
)
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import validate
from scar.ir.program.providers import ProviderFactReference
from scar.ir.execution.codec import loads as load_execution
from scar.ir.program.model import ReferenceValue
from scar.trace.native_capture_batch import NativeCaptureBatchBudget, _write_inventory
from scar.trace.native_protocol import _build_program, _build_execution, _prepare_projection, _artifact, NativeProtocolWindow
from scar.ir.record_codec import encode

BASE = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
OLD = BASE / 'artifacts/experiments/native_capture_batch_20261025'
DIAG = BASE / 'artifacts/analysis/native_capture_batch_failure01_20261025/evidence.json'
SAVED = Path('/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_native_protocol_bridge_attempt03_20261023/result')
evidence = json.loads(DIAG.read_text())
records = {(r['kind'], r['key']): {'ordinal': r['ordinal'], 'record': r['record']} for r in evidence['selected_sqlite_rows']}
db = OLD / 'result/private/navigation.sqlite'
before = (db.stat().st_size, db.stat().st_mtime_ns)
c = sqlite3.connect('file:' + str(db.resolve()) + '?mode=ro&immutable=1', uri=True)
for kind, keys in [('node', [1, 2, 5, 6, 7]), ('archive:instances', [1, 2, 5, 6, 7]), ('dispatch', [1, 2, 3]), ('physical', [9685])]:
    for key in keys:
        ordinal, raw = c.execute('select ordinal,payload from records where kind=? and key=?', (kind, str(key))).fetchone()
        records[kind, str(key)] = {'ordinal': ordinal, 'record': json.loads(raw)}
c.close()
assert before == (db.stat().st_size, db.stat().st_mtime_ns)
raw_artifacts = {row['artifact']['schema']: row['artifact'] for row in evidence['raw_source_artifacts_from_terminal_receipt']}
model0 = load_execution((SAVED / 'execution.json').read_text())
target = next(p for p in model0.processes if p.pid == 369749)
coordinates = SimpleNamespace(run=model0.runs[0], processes=model0.processes, threads=model0.threads,
    target_process=target, thread_for=lambda *args: model0.segments[0].host_thread)
object_record = records['archive:objects', 'weak:369749:354301']['record']['record']
native_scope = records['archive:instances', '24616']['record']['record']['id']['value'].rsplit(':eto:', 1)[0]
allocation = next(row['record']['record'] for (kind, key), row in records.items() if kind == 'archive:allocations')
source = {'reference_profile': PROFILE_V2, 'provider_revision': 'cf30153c4c131c8164ee7798e5022d810682e2cb',
    'run': coordinates.run.id.value, 'pid': 369749, 'nonce': '72816598bfa183a810428fe30a7873ff',
    'owner_native_tid': 369749, 'owner_python_ident': 134637364963136,
    'native_scope': native_scope, 'physical_scope': allocation['lifetime_scope'],
    'physical_profile': 'scar.tensor-physical-event-tree-v1', 'first_sequence': 3182, 'max_sequences': 1,
    'artifacts': {'eto': raw_artifacts['pytorch.execution-trace.v1'], 'dispatch': raw_artifacts['scar.dispatch-observation.events.v1'],
                  'physical': raw_artifacts['scar.tensor-physical-observation.v1']},
    'nodes': [records['node', str(i)]['record'] for i in (1, 2, 24611, 24614, 24615, 24616, 24625)],
    'dispatch': [records['dispatch', str(i)]['record'] for i in (9544, 9545, 9546)],
    'physical': [r['record'] for (kind, key), r in records.items() if kind == 'physical' and key != '9685'],
    'node_ordinals': {key: r['ordinal'] for (kind, key), r in records.items() if kind == 'node'},
    'object_records': {'weak:369749:354301': object_record}, 'geometry_records': {}}
checks = []
interfaces, frontiers = replay_batch_interfaces(source)
assert not frontiers and len(interfaces) == 1
ports = interfaces[0]['ports']
assert len(ports['inputs']) == 2 and ports['inputs'][0].get('object_record') == object_record
assert ports['inputs'][1].get('object_record') is None and ports['outputs'][0].get('object_record') == object_record
assert all(p['geometry']['status'] == 'UNPROVED' for ps in ports.values() for p in ps if p['tensor'])
checks.append('3182 has all native ports, two held identities and a native-only input; missing C does not erase B')
try:
    legacy = {k: v for k, v in source.items() if k != 'reference_profile'}
    replay_interfaces(legacy)
except ValueError as error:
    assert 'native Tensor leaf lacks held-reference correspondence' in str(error)
else:
    raise AssertionError('V1 bijection was weakened')
checks.append('V1 still rejects 3182 non-bijection')
for kwargs in ({'first_sequence': 2}, {'max_sequences': 17}):
    try: NativeProtocolWindow(**kwargs)
    except ValueError: pass
    else: raise AssertionError('V1 prefix bound weakened')
checks.append('V1 prefix/16 limits preserved')
sig = interfaces[0]['signature_id']
doc = {'schema': 'scar.pinned-torch-protocol-interface', 'schema_version': 1, 'profile': PROFILE_V2,
       'interfaces': {sig: interfaces[0]['signature']}, 'effect_contract': 'UNKNOWN outside partial provider schema annotations',
       'content_version_claimed': False}
canonical = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
interface_artifact = _artifact(OUT / 'memory-interface.json', canonical(doc), doc['schema'])
program, layouts = _build_program(interfaces, source, interface_artifact)
projection_selected = {('evidence', 'instances'): [r['record'] for (kind, key), r in records.items() if kind == 'archive:instances' and int(key) not in (5, 6, 7)],
    ('values', 'objects'): [records['archive:objects', 'weak:369749:354301']['record']], ('values', 'regions'): [], ('values', 'allocations'): []}
values, eeg, va, ea, geometry, payloads = _prepare_projection(source, interfaces, projection_selected, OUT / 'pure-projection', NativeCaptureBatchBudget())
assert not geometry and len(values.objects) == 1 and not values.allocations and not values.regions
assert not (OUT / 'pure-projection').exists()
checks.append('B-only ordinary ValueGraph projection closes without geometry and prepares no files')
snapshot = snapshot_for(program, 'memory:v2-api-program')
model = _build_execution(program, layouts, interfaces, source, coordinates, snapshot.artifact, va, ea)
assert len(model.denotations) == 3 and sum(type(d.identity) is Unresolved for d in model.denotations) == 1
kwargs = {'definition_signatures': doc['interfaces'], 'profile': PROFILE_V2, 'source': source, 'value_artifact': va, 'evidence_artifact': ea}
assert not _native_port_order_errors(program, model, interfaces, source['run'], **kwargs)
catalogs = {'value_graphs': {va.sha256: values}, 'evidence_graphs': {ea.sha256: eeg}, 'artifact_bytes': {interface_artifact.sha256: canonical(doc)}}
assert validate(model, program, **catalogs).valid
checks.append('all three exact native basis/source/occurrences validate with existing Unresolved IR')
unknown = next(d for d in model.denotations if type(d.identity) is Unresolved)
known = next(d for d in model.denotations if type(d.identity) is ObjectIdentity and type(d.basis) is NativeInputRef)
def changed(d):
    return replace(model, denotations=tuple(d if item.id == d.id else item for item in model.denotations))
def rejected(candidate, code):
    assert any(e[0] == code for e in _native_port_order_errors(program, candidate, interfaces, source['run'], **kwargs)), code
rejected(changed(replace(unknown, basis=Unresolved('missing basis', unknown.identity.point))), 'actual_native_order')
rejected(changed(replace(unknown, source=known.source)), 'native_source')
rejected(changed(replace(unknown, identity=replace(unknown.identity, point=replace(unknown.identity.point, run=RunID('wrong-run'))))), 'native_unresolved_source')
rejected(changed(replace(unknown, identity=replace(unknown.identity, point=replace(unknown.identity.point, process=None)))), 'native_unresolved_source')
rejected(changed(replace(unknown, identity=known.identity)), 'native_identity_unresolved')
rejected(changed(replace(known, identity=Unresolved('erased held identity', unknown.identity.point))), 'native_object_identity')
rejected(replace(model, denotations=tuple(d for d in model.denotations if d.id != unknown.id)), 'actual_native_denotation')
checks.append('unknown basis/source/Run/process, borrowed ObjectID, erased known identity and missing denotation all reject independently')
rejected(replace(model, evidence_bindings=()), 'native_producer_binding')
wrong_binding = replace(model.evidence_bindings[0], source=unknown.source)
rejected(replace(model, evidence_bindings=(wrong_binding, *model.evidence_bindings[1:])), 'native_producer_binding')
wrong_binding = replace(model.evidence_bindings[0], legacy=replace(model.evidence_bindings[0].legacy,
    instance=OperationInstanceID(source['native_scope'] + ':eto:24611')))
wrong_producer = replace(model, evidence_bindings=(wrong_binding, *model.evidence_bindings[1:]))
assert validate(wrong_producer, program, **catalogs).valid
rejected(wrong_producer, 'native_producer_binding')
rejected(replace(model, evidence_bindings=model.evidence_bindings[:1]), 'native_producer_binding')
checks.append('producer binding and original node ordinal are independently required regardless of B identity')
boundary = program.native_boundaries[0]
slots = list(boundary.inputs)
slots[0], slots[1] = replace(slots[0], port=slots[1].port), replace(slots[1], port=slots[0].port)
wrong_program = replace(program, native_boundaries=(replace(boundary, inputs=tuple(slots)),))
denotations = []
for d in model.denotations:
    if type(d.basis) is NativeInputRef:
        formal = slots[d.basis.position].port.value
        actual = next(v for v in model.values if v.origin == d.basis.entry and v.value == formal)
        d = replace(d, value=actual.id)
    denotations.append(d)
wrong_model = replace(model, snapshot=snapshot_for(wrong_program, 'memory:v2-newly-sealed-wrong-order'), denotations=tuple(denotations))
assert validate(wrong_model, wrong_program, **catalogs).valid
try:
    _require_native_port_order(wrong_program, wrong_model, interfaces, source['run'], **kwargs)
except NativePortOrderError:
    pass
else:
    raise AssertionError('newly sealed wrong order accepted')
checks.append('new snapshot generic-valid consistent permutation raises NativePortOrderError including unknown port')
empty = copy.deepcopy(source)
for node in empty['nodes']:
    if node['id'] in (24615, 24625): boxes = [node['inputs']]
    elif node['id'] == 24616: boxes = [node['inputs'], node['outputs']]
    else: continue
    for box in boxes:
        box['values'][0] = [24607, 0, 0, 0, 4, 'cpu'];box['shapes'][0] = [0];box['strides'][0] = [1]
empty['physical'] = []
ep, _ = replay_batch_interfaces(empty)
assert ep[0]['ports']['inputs'][0].get('object_record') is not None
assert ep[0]['ports']['inputs'][0]['geometry']['status'] == 'UNPROVED'
checks.append('synthetic empty CPU Tensor keeps held identity while geometry remains missing')
with_geometry = copy.deepcopy(source)
with_geometry['physical'].append(records['physical', '9685']['record'])
for (kind, key), wrapper in records.items():
    if kind != 'archive:regions': continue
    original = wrapper['record']
    line = original['record']['metadata']['physical_observation'].split('#line/')[1].split('/')[0]
    ordinal = original['record']['metadata']['argument_ordinal']
    with_geometry['geometry_records'][line + ':' + str(ordinal)] = {
        'region': original,
        'allocation': next(r['record'] for (k, _), r in records.items() if k == 'archive:allocations')}
gp, gf = replay_batch_interfaces(with_geometry)
assert not gf and sum(p['geometry']['status'] == 'QUALIFIED' for ps in gp[0]['ports'].values() for p in ps if p['tensor']) == 2
assert gp[0]['ports']['inputs'][1].get('object_record') is None
bad_geometry = copy.deepcopy(with_geometry)
next(iter(bad_geometry['geometry_records'].values()))['region']['record']['offset'] += 1
try: replay_batch_interfaces(bad_geometry)
except ValueError as error: assert 'region contradicts' in str(error)
else: raise AssertionError('known geometry contradiction became a missing-evidence gap')
checks.append('actual saved geometry/birth qualifies independently; contradictory known region rejects')
geometry_selected = {**projection_selected,
    ('values','regions'): [r['record'] for (kind, key), r in records.items() if kind == 'archive:regions'],
    ('values','allocations'): [r['record'] for (kind, key), r in records.items() if kind == 'archive:allocations']}
gv, ge, _, _, points, _ = _prepare_projection(with_geometry, gp, geometry_selected, OUT / 'pure-C-projection', NativeCaptureBatchBudget())
assert len(gv.objects) == 1 and len(gv.regions) == 2 and len(gv.allocations) == 1 and len(points) == 2
assert gp[0]['signature_id'] == interfaces[0]['signature_id']
no_objects = copy.deepcopy(source)
no_objects['object_records'] = {}
op, _ = replay_batch_interfaces(no_objects)
assert op[0]['signature_id'] == sig and all(p.get('object_record') is None for ps in op[0]['ports'].values() for p in ps if p['tensor'])
checks.append('B and C dynamic qualifications change neither static signature nor native function; C projection reuses only original records')
custom = copy.deepcopy(source)
custom.update(first_sequence=1, nodes=[records['node', str(i)]['record'] for i in (1, 2, 5, 6, 7)],
    dispatch=[records['dispatch', str(i)]['record'] for i in (1, 2, 3)], physical=[], object_records={}, geometry_records={})
cp, cf = replay_batch_interfaces(custom)
assert not cf and cp[0]['operator'] == 'torchvision._cuda_version.default' and cp[0]['ports']['outputs'][0]['type'] == 'Int'
assert replay_interfaces(custom)[1][0]['reason'] == 'OUTSIDE_PINNED_ATEN_SCHEMA_DOMAIN'
checks.append('observed registered non-ATen schema qualifies same A ABI; V1 domain stays unchanged')
none = copy.deepcopy(custom)
none['dispatch'][0]['operator'] = 'example.optional.default'
node = next(n for n in none['nodes'] if n['id'] == 6)
node['name'] = 'example::optional'
next(a for a in node['attrs'] if a['name'] == 'op_schema')['value'] = 'example::optional(Tensor? x=None, int[] dims=[]) -> Tensor?'
node['inputs'] = {'values': ['<None>', []], 'types': ['None', 'GenericList[]'], 'shapes': [[], []], 'strides': [[], []]}
node['outputs'] = {'values': ['<None>'], 'types': ['None'], 'shapes': [[]], 'strides': [[]]}
np, nf = replay_batch_interfaces(none)
assert not nf and [p['type'] for p in np[0]['ports']['inputs']] == ['None', 'GenericList[]']
assert not any(p['tensor'] for ps in np[0]['ports'].values() for p in ps)
checks.append('None/default/empty container tags preserve native structure and create no fabricated Tensor reference')
def publish(path, raw, maximum):
    assert len(raw) <= maximum
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream: stream.write(raw)
artifact, manifest = _write_inventory(OUT / ('chunk-check-' + (sys.argv[1] if len(sys.argv)>1 else 'once')), ({'sequence': i + 1, 'begin_count': 1, 'source_locator': '#line/' + str(i + 1)} for i in range(2501)),
    NativeCaptureBatchBudget(), publish, role='synthetic-transport')
assert [c['rows'] for c in manifest['chunks']] == [1000, 1000, 501]
assert all(c['artifact']['size_bytes'] <= 8_000_000 for c in manifest['chunks'])
checks.append('2501 transport rows split 1000/1000/501 under 8MB with original sequence preserved')
print(json.dumps({'status': 'V2_SMALL_API_CHECK_PASS', 'checks': checks, 'runtime_owned_authority_recreated': False,
                  'original_raw_reads': 0, 'archive_chunk_reads': 0, 'full_gate_run': False,
                  'sqlite_read_only_diagnostic_rows_only': True,
                  'producer_files': {str(p): sha256((BASE/p).read_bytes()).hexdigest() for p in
                    ('scar/trace/native_capture_batch.py','scar/trace/native_protocol.py','scar/ir/execution/native_port_protocol.py')}},sort_keys=True,indent=2))
