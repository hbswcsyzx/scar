"""Prepared real full-domain gate. Run only after root confirms this freeze."""
from dataclasses import replace
from functools import lru_cache
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
write('gate-started.json', {'status': 'ONE_REAL_FULL_DOMAIN_GATE_STARTED', 'freeze_sha256': sha256((OUT / 'freeze.json').read_bytes()).hexdigest()})
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
    from scar.ir.execution.native_port_protocol import _make_evidence, NativePortOrderError, replay_interfaces, _native_port_order_errors
    from scar.ir.execution.content import NativeInputRef
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
    assert report['source_domain_complete'] and report['status'] == 'SOURCE_DOMAIN_ACCOUNTED', report['status']
    assert report['declared_dispatch_attempts'] == report['enumerated_begin_rows'] == report['enumerated_dispatch_groups']
    assert report['qualified_dispatches'] + report['frontier_dispatches'] == report['declared_dispatch_attempts']
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
    order_errors = _native_port_order_errors(wrong_program, wrong_model, replay_interfaces(owned.source())[0],
        first.execution.runs[0].id.value, definition_signatures=owned.definitions())
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
    write('negative-checks.json', negative)
    for row in freeze['dependencies'] + freeze['read_only_metadata']:
        raw = (BASE / row['path']).read_bytes()
        assert sha256(raw).hexdigest() == row['sha256'] and len(raw) == row['bytes'], row['path']
    actual_imported = check_imported_sources()
    summary = {'status': 'PASS_SOURCE_DOMAIN_ACCOUNTING_WITH_FRONTIERS', 'batch_report': report,
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
    emit({'stage': 'complete', 'status': summary['status'], 'qualified': report['qualified_dispatches'], 'frontier': report['frontier_dispatches']})
except BaseException as error:
    write('gate-failure.json', {'status': 'FAILED', 'phase': phase, 'error_type': type(error).__name__,
          'message': str(error), 'traceback': traceback.format_exc(), 'wall_seconds': time.monotonic() - START})
    emit({'stage': 'failed', 'phase': phase, 'error_type': type(error).__name__, 'message': str(error)})
    raise
finally:
    signal.alarm(0)
    write('actual-io.json', [{'phase': p, 'path': path, 'kind': kind, 'bytes': n} for (p, path, kind), n in sorted(reads.items())])
    progress_file.close()
