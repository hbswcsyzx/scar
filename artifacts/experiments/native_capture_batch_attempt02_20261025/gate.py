"""Prepared real full-domain gate. Run only after root confirms this freeze."""
from dataclasses import replace
from functools import lru_cache
from itertools import zip_longest
from hashlib import sha256
from pathlib import Path
import builtins
import gzip
import io
import json
import resource
import shutil
import signal
import sys
import time
import traceback

BASE = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
ORIGINAL = Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
CAPTURE = ORIGINAL / 'artifacts/experiments/first_stage_lewm_physical_20261023'
NATIVE = ORIGINAL / 'artifacts/experiments/first_stage_joined_physical_20261023/result'
MANIFEST = NATIVE / 'native/bundle-partitions/manifest.json'
MODEL = NATIVE / 'capture-model.json'
START = time.monotonic()
phase, reads = 'imports', {}


def write(name, data):
    with (OUT / name).open('x') as stream:
        json.dump(data, stream, sort_keys=True, indent=2)
        stream.write('\n')


freeze = json.loads((OUT / 'freeze.json').read_text())
for row in freeze['dependencies'] + freeze['runner_files'] + freeze['read_only_metadata']:
    path = BASE / row['path']
    raw = path.read_bytes()
    assert len(raw) == row['bytes'] and sha256(raw).hexdigest() == row['sha256'], row['path']


def check_imported_sources():
    frozen = {row['path']: row for row in freeze['dependencies']}
    imported = []
    for name, module in tuple(sys.modules.items()):
        if name != 'scar' and not name.startswith('scar.'):
            continue
        filename = getattr(module, '__file__', None)
        if filename is None:
            continue
        path = Path(filename).resolve()
        if path.suffix == '.pyc':
            from importlib.util import source_from_cache
            path = Path(source_from_cache(str(path))).resolve()
        assert path.is_relative_to(BASE), ('SCAR import escaped isolated tree', name, str(path))
        relative = str(path.relative_to(BASE))
        assert relative not in freeze['excluded_unrelated_modules'], ('unrelated scope module imported', relative)
        assert relative in frozen, ('actually imported source is not frozen', relative)
        raw = path.read_bytes()
        assert sha256(raw).hexdigest() == frozen[relative]['sha256'] and len(raw) == frozen[relative]['bytes'], relative
        imported.append(relative)
    return sorted(set(imported))
assert not (OUT / 'result').exists()
assert shutil.disk_usage(OUT).free >= 16_000_000_000
write('gate-started.json', {'status': 'ONE_REAL_V2_FULL_DOMAIN_GATE_STARTED', 'freeze_sha256': sha256((OUT / 'freeze.json').read_bytes()).hexdigest()})
progress_file = (OUT / 'progress.jsonl').open('x')


def emit(row):
    row = {'whole_elapsed_s': time.monotonic() - START, **row}
    text = json.dumps(row, sort_keys=True)
    progress_file.write(text + '\n')
    progress_file.flush()
    print(text, flush=True)


def alarm(*_):
    raise TimeoutError('whole real gate 1800s alarm')


signal.signal(signal.SIGALRM, alarm)
signal.alarm(1800)
original_open, original_io_open = builtins.open, io.open
original_gread, original_gline = gzip.GzipFile.read, gzip.GzipFile.readline


@lru_cache(maxsize=1024)
def source_path(path):
    try:
        return Path(path).resolve()
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1024)
def tracked(path):
    p = source_path(path)
    return p is not None and (p.is_relative_to(CAPTURE) or p.is_relative_to(NATIVE / 'native/bundle-partitions') or p == MODEL)


def add(path, kind, count):
    if count:
        key = (phase, str(source_path(path)), kind)
        reads[key] = reads.get(key, 0) + count


class FileRead:
    def __init__(self, stream):
        self._f = stream
    def __getattr__(self, key):
        return getattr(self._f, key)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return self._f.__exit__(*args)
    def __iter__(self):
        return self
    def __next__(self):
        value = self.readline()
        if not value:
            raise StopIteration
        return value
    def _count(self, value):
        add(self.name, 'stored', len(value))
        if not str(self.name).endswith('.gz'):
            add(self.name, 'decoded', len(value))
        return value
    def read(self, *args):
        return self._count(self._f.read(*args))
    def readline(self, *args):
        return self._count(self._f.readline(*args))
    def readinto(self, buffer):
        count = self._f.readinto(buffer)
        add(self.name, 'stored', count or 0)
        if not str(self.name).endswith('.gz'):
            add(self.name, 'decoded', count or 0)
        return count


def opened(original):
    def wrapper(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        mode = args[0] if args else kwargs.get('mode', 'r')
        return FileRead(stream) if tracked(path) and 'r' in mode and 'b' in mode else stream
    return wrapper


depth = {}


def gzip_read(original):
    def wrapper(stream, *args, **kwargs):
        key, old = id(stream), depth.get(id(stream), 0)
        depth[key] = old + 1
        try:
            value = original(stream, *args, **kwargs)
        finally:
            depth[key] = old
        if old == 0 and tracked(getattr(stream, 'name', None)):
            add(stream.name, 'decoded', len(value))
        return value
    return wrapper


builtins.open, io.open = opened(original_open), opened(original_io_open)
gzip.GzipFile.read, gzip.GzipFile.readline = gzip_read(original_gread), gzip_read(original_gline)
try:
    from scar.trace.capture_coordinates import bind_capture_coordinates
    from scar.trace.native_capture_batch import bind_native_capture_batches, NativeCaptureBatchBudget
    from scar.ir.execution.native_port_protocol import _make_evidence, NativePortOrderError, replay_batch_interfaces, _native_port_order_errors, PROFILE_V2
    from scar.ir.execution.content import NativeInputRef, ObjectIdentity
    from scar.ir.execution.common import Unresolved
    from scar.ir.v2.ids import OperationInstanceID
    from scar.ir.execution.ids import RunID
    from scar.ir.execution.snapshot import snapshot_for
    from scar.ir.execution.validation import validate
    from scar.ir.execution.codec import dumps as execution_dumps
    from scar.ir.program.model import ReferenceValue
    from scar.ir.program.providers import ProviderArtifact
    from scar.ir.record_codec import decode
    check_imported_sources()
    phase = 'coordinate_scope'
    emit({'stage': phase})
    coordinates = bind_capture_coordinates(CAPTURE, max_bytes=1_200_000_000, max_lines=1_100_000,
                                          profile_uri=str(OUT / 'native-coordinates.json'))
    with (OUT / 'native-coordinates.json').open('xb') as stream:
        stream.write(coordinates.payload)
    phase = 'native_capture_batches'
    emit({'stage': phase})
    result = bind_native_capture_batches(coordinates, CAPTURE, MANIFEST, OUT / 'result',
        expected_manifest_sha256=freeze['native_manifest_sha256'], capture_model_path=MODEL,
        expected_capture_model_sha256=freeze['capture_model_sha256'], budget=NativeCaptureBatchBudget(), progress=emit)
    report = result.report
    assert report['source_domain_complete'] and report['status'] == 'SOURCE_DOMAIN_ACCOUNTED_WITH_PORT_GAPS', report['status']
    assert report['declared_dispatch_attempts'] == report['enumerated_begin_rows'] == report['enumerated_dispatch_groups']
    assert report['structurally_modeled_dispatches'] + report['unmodeled_frontier_dispatches'] == report['declared_dispatch_attempts']
    assert report['unvisited_declared_sequences'] == 0
    phase = 'critical_fresh_owned_order_negative'
    first = result.first_shard
    assert first is not None
    core_values = {v.id: v for v in result.program.values}
    active = {a.region for a in first.execution.activations}
    boundary = next(b for b in result.program.native_boundaries if b.region in active and len(b.inputs) >= 2
                    and all(type(core_values[s.port.value]) is ReferenceValue for s in b.inputs[:2]))
    slots = list(boundary.inputs)
    slots[0] = replace(slots[0], port=boundary.inputs[1].port)
    slots[1] = replace(slots[1], port=boundary.inputs[0].port)
    changed = replace(boundary, inputs=tuple(slots))
    wrong_program = replace(result.program, native_boundaries=tuple(changed if b.id == boundary.id else b for b in result.program.native_boundaries))
    denotations = []
    for d in first.execution.denotations:
        b = d.basis
        if type(b) is NativeInputRef and b.boundary == boundary.id and b.position in (0, 1):
            formal = changed.inputs[b.position].port.value
            actual = next(v for v in first.execution.values if v.origin == b.entry and v.value == formal)
            d = replace(d, value=actual.id)
        denotations.append(d)
    wrong_model = replace(first.execution, snapshot=snapshot_for(wrong_program, 'memory:fresh-batch-order-counterexample'), denotations=tuple(denotations))
    va = decode(ProviderArtifact, first.report['values_projection'])
    ea = decode(ProviderArtifact, first.report['evidence_projection'])
    catalogs = {'value_graphs': {va.sha256: first.values}, 'evidence_graphs': {ea.sha256: first.evidence}}
    generic = validate(wrong_model, wrong_program, **catalogs)
    assert generic.valid, generic.issues
    try:
        _make_evidence(first.native_port_evidence._owned, wrong_program, wrong_model, va, ea)
    except NativePortOrderError as error:
        failure = str(error)
    else:
        raise AssertionError('new source-owned constructor accepted newly sealed wrong order')
    owned = first.native_port_evidence._owned
    order_errors = _native_port_order_errors(wrong_program, wrong_model, replay_batch_interfaces(owned.source())[0],
        first.execution.runs[0].id.value, definition_signatures=owned.definitions(), profile=PROFILE_V2, source=owned.source(), value_artifact=va, evidence_artifact=ea)
    assert any(e[0] == 'native_core_order' for e in order_errors) and any(e[0] == 'actual_native_order' for e in order_errors)
    assert 'native_port_scope' not in failure
    no_proof = validate(first.execution, result.program, **catalogs)
    assert any(g.code == 'content_native_correspondence_unverified' for g in no_proof.gaps)
    wrong_run = replace(first.execution, runs=(replace(first.execution.runs[0], id=RunID('deliberately-wrong-batch-run')),))
    run_check = validate(wrong_run, result.program, native_port_evidence=first.native_port_evidence, **catalogs)
    assert any(i.code == 'native_port_scope' for i in run_check.issues)
    negative = {'generic_execution_issues': len(generic.issues), 'fresh_same_run_owned_constructor_used': True,
        'failure_kind': 'NativePortOrderError', 'message': failure, 'order_errors': order_errors,
        'own_program_snapshot_sha256': wrong_model.snapshot.artifact.sha256,
        'own_execution_sha256': sha256(execution_dumps(wrong_model).encode()).hexdigest(),
        'old_scope_hash_rejection_used': False, 'legacy_gap_retained': True, 'wrong_run_rejected': True}
    # Fresh constructors use genuine leases from this actual acquisition.
    # Unresolved is not permission to lose the original source/producer join.
    partial = result.first_partial_shard
    assert partial is not None, 'fixture expected an observed native-only Tensor port'
    pva = decode(ProviderArtifact, partial.report['values_projection'])
    pea = decode(ProviderArtifact, partial.report['evidence_projection'])
    unknown = next(d for d in partial.execution.denotations if type(d.identity) is Unresolved)
    known = next((d for d in partial.execution.denotations if type(d.identity) is ObjectIdentity), None)
    pcatalogs = {'value_graphs': {pva.sha256: partial.values}, 'evidence_graphs': {pea.sha256: partial.evidence}}
    def replace_denotation(d):
        return replace(partial.execution, denotations=tuple(d if old.id == d.id else old for old in partial.execution.denotations))
    candidates = {
        'unknown_basis_erased': replace_denotation(replace(unknown, basis=Unresolved('basis erased', unknown.identity.point))),
        'unknown_wrong_run': replace_denotation(replace(unknown, identity=replace(unknown.identity,
            point=replace(unknown.identity.point, run=RunID('wrong-native-only-run'))))),
        'unknown_wrong_process': replace_denotation(replace(unknown, identity=replace(unknown.identity,
            point=replace(unknown.identity.point, process=None)))),
        'unknown_missing_denotation': replace(partial.execution, denotations=tuple(d for d in partial.execution.denotations if d.id != unknown.id)),
        'all_producer_bindings_erased': replace(partial.execution, evidence_bindings=()),
    }
    if known is not None:
        candidates['unknown_borrowed_object'] = replace_denotation(replace(unknown, identity=known.identity))
        candidates['known_identity_erased'] = replace_denotation(replace(known,
            identity=Unresolved('held identity erased', replace(unknown.identity.point, source=known.source))))
        candidates['unknown_wrong_source'] = replace_denotation(replace(unknown, source=known.source))
    changed_binding = partial.execution.evidence_bindings[0]
    another = next(b.legacy.instance for b in partial.execution.evidence_bindings if b.legacy.instance != changed_binding.legacy.instance)
    candidates['producer_changed_same_run'] = replace(partial.execution,
        evidence_bindings=(replace(changed_binding, legacy=replace(changed_binding.legacy, instance=another)), *partial.execution.evidence_bindings[1:]))
    cases = {}
    for name, candidate in candidates.items():
        generic_candidate = validate(candidate, result.program, **pcatalogs)
        try:
            _make_evidence(partial.native_port_evidence._owned, result.program, candidate, pva, pea)
        except NativePortOrderError as error:
            message = str(error)
        else:
            raise AssertionError('fresh V2 owned constructor accepted: ' + name)
        cases[name] = {'rejected': True, 'failure_kind': 'NativePortOrderError',
                       'generic_issue_count': len(generic_candidate.issues), 'message': message}
    negative['native_only_and_producer_cases'] = cases
    assert report['native_tensor_ports'] == report['held_object_ports'] + report['unresolved_object_ports']
    assert report['native_tensor_ports'] == report['geometry_qualified_ports'] + report['geometry_gap_ports']
    assert report['structurally_modeled_dispatches'] == report['modeled_complete_reference_dispatches'] + report['modeled_partial_reference_dispatches']
    assert not report['implementation_code_identity_established']
    assert report['observed_execution_instrumented'] and not report['target_observer_work_attribution_established']
    def table_rows(artifact):
        path = Path(artifact['uri'])
        raw = path.read_bytes()
        assert sha256(raw).hexdigest() == artifact['sha256'] and len(raw) == artifact['size_bytes']
        manifest = json.loads(raw)
        assert manifest['profile'] == PROFILE_V2
        count = 0
        for chunk in manifest['chunks']:
            a = chunk['artifact']; data = Path(a['uri']).read_bytes()
            assert len(data) <= 8_000_000 and len(data) == a['size_bytes'] and sha256(data).hexdigest() == a['sha256']
            rows = [json.loads(line) for line in data.splitlines()]
            assert len(rows) == chunk['rows'] <= 1000
            count += len(rows)
            yield from rows
        assert count == manifest['rows']
    inventory_count = 0
    preserved = ('sequence', 'source_rows', 'operator', 'outcome', 'begin_count', 'end_count')
    for final_row, original_row, sequence in zip_longest(table_rows(report['dispatch_inventory']),
            table_rows(report['observed_dispatch_inventory']), report['actual_sequence_ids']):
        assert final_row is not None and original_row is not None and sequence is not None
        assert final_row['sequence'] == original_row['sequence'] == sequence
        assert all(final_row[key] == original_row[key] for key in preserved)
        assert final_row['state'] in ('MODELED_COMPLETE_REFERENCE', 'MODELED_PARTIAL_REFERENCE', 'FRONTIER')
        inventory_count += 1
    assert inventory_count == report['declared_dispatch_attempts']
    port_count = 0
    for shard in report['shards']:
        for row in table_rows(shard['port_qualifications']):
            port_count += 1
            assert row['A'] == 'QUALIFIED_NATIVE_PORT' and row['D'] == 'CONTENT_STATE_READY_UNPROVED'
    assert port_count == report['native_tensor_ports']

    write('negative-checks.json', negative)
    for row in freeze['dependencies'] + freeze['read_only_metadata']:
        raw = (BASE / row['path']).read_bytes()
        assert sha256(raw).hexdigest() == row['sha256'] and len(raw) == row['bytes'], row['path']
    actual_imported = check_imported_sources()
    summary = {'status': 'PASS_V2_SOURCE_ACCOUNTING_WITH_EXPLICIT_PORT_GAPS', 'batch_report': report,
        'critical_negative': negative, 'wall_seconds': time.monotonic() - START,
        'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'path_API_IO_by_phase': {p: {k: sum(n for (ph, _, kind), n in reads.items() if ph == p and kind == k)
            for k in ('stored', 'decoded')} for p in sorted({key[0] for key in reads})},
        'additional_verified_BytesIO_chunk_decoded_bytes': sum(r['decoded_bytes'] for r in report['archive_reads']),
        'private_SQLite_counter_scope': 'payload bytes returned by owned navigation get; not physical SQLite disk I/O',
        'source_files_unchanged': True, 'target_executions': 0, 'prepare_calls': 0, 'compiler_witness_calls': 0,
        'actual_imported_SCAR_sources': actual_imported,
        'logical_contents_established': False, 'complete_state_effects_established': False,
        'resource_readiness_established': False, 'whole_model_established': False, 'transformation_authorized': False}
    write('summary.json', summary)
    emit({'stage': 'complete', 'status': summary['status'], 'modeled': report['structurally_modeled_dispatches'], 'frontier': report['unmodeled_frontier_dispatches']})
except BaseException as error:
    write('gate-failure.json', {'status': 'FAILED', 'phase': phase, 'error_type': type(error).__name__,
          'message': str(error), 'traceback': traceback.format_exc(), 'wall_seconds': time.monotonic() - START})
    emit({'stage': 'failed', 'phase': phase, 'error_type': type(error).__name__, 'message': str(error)})
    raise
finally:
    signal.alarm(0)
    write('actual-io.json', [{'phase': p, 'path': path, 'kind': kind, 'bytes': n} for (p, path, kind), n in sorted(reads.items())])
    progress_file.close()
