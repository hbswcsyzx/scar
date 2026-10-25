"""Small-metadata preflight and immutable preparation; never builds navigation."""
from hashlib import sha256
import importlib
import json
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import threading
import time
import traceback
import zlib

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
ISO = Path('/home/zyf/AAA/scar-worktrees/native-scalar-model')
SOURCE = ROOT / 'artifacts/experiments/first_stage_source_revision_current_20261025/result/connections'
NATIVE = ISO / 'artifacts/experiments/native_capture_batch_attempt03_20261025'


def raw(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode()


def read(path, maximum=32_000_000):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.resolve() != path or path.stat().st_size > maximum:
        raise ValueError('unsafe/oversized preparation file: ' + str(path))
    return path.read_bytes()


def publish(path, value):
    payload = value if type(value) is bytes else raw(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(payload)


def receipt(path):
    data = read(path, 128_000_000)
    return {'path': str(path), 'bytes': len(data), 'sha256': sha256(data).hexdigest()}


def stat_receipt(path):
    s = path.stat()
    return {'path': str(path), 'bytes': s.st_size, 'inode': s.st_ino, 'device': s.st_dev,
            'mtime_ns': s.st_mtime_ns, 'ctime_ns': s.st_ctime_ns}


def main():
    if (BASE / 'freeze.json').exists():
        raise FileExistsError('preparation already frozen')
    from scar.analysis.source_native_composition import NativeContextInputs, NavigationBudget, NativeContextQueryBudget, _Roots, _Meter
    from scar.ir.program.providers import ProviderArtifact
    from scar.ir.record_codec import decode, encode
    from scar.ir.execution.native_port_protocol import flat_native
    # Load the lazy query dependency entry modules without any model/data I/O.
    for name in ('scar.ir.execution.codec', 'scar.ir.program.codec', 'scar.store.bundle_partitions'):
        importlib.import_module(name)
    started = time.monotonic()
    source_path, dispatch_path, native_path = SOURCE / 'source/report.json', SOURCE / 'dispatch/report.json', NATIVE / 'result/report.json'
    s, d, n = (json.loads(read(p)) for p in (source_path, dispatch_path, native_path))
    ledger_path = ROOT / 'artifacts/experiments/modeling_scope_retained_gate_20261025/attempt01/ledger/manifest.json'
    ledger = json.loads(read(ledger_path))
    def artifact(path, schema):
        r = receipt(path)
        return ProviderArtifact(str(path), r['sha256'], r['bytes'], schema)
    inputs = NativeContextInputs(decode(ProviderArtifact, d['source_report']),
        artifact(dispatch_path, 'scar.dispatch-source-associations'), artifact(native_path, 'scar.native-capture-batch'),
        ProviderArtifact(n['source_manifest']['path'], n['source_manifest']['physical_sha256'], n['source_manifest']['physical_bytes'], 'scar.partitioned-ir-bundle'),
        decode(ProviderArtifact, s['coordinate_binding']), decode(ProviderArtifact, n['coordinates']),
        artifact(ledger_path, 'scar.partitioned-modeling-scope-ledger'), ledger['scope']['record']['revision'])
    build_budget, query_budget = NavigationBudget(), NativeContextQueryBudget()
    meter = _Meter(build_budget)
    roots = _Roots(inputs, meter)
    for row in d['examples'].values():
        roots.source_row(row)
    selected = {}
    for status in ('RETAINED_BODY_LINKED', 'RETAINED_SOURCE_LINKED', 'UNRESOLVED', 'RETAINED_INVOCATION_LINKED'):
        row = d['examples'][status]
        selected.setdefault(row['sequence'], {'sequence': row['sequence'], 'roles': [], 'selection': []})
        selected[row['sequence']]['roles'].append(status)
        selected[row['sequence']]['selection'].append({'artifact': encode(inputs.dispatch_source_report), 'pointer': '#/examples/' + status})
    supporting = []
    negative_path = NATIVE / 'negative-checks.json'
    negative = json.loads(read(negative_path))
    case = negative['native_only_and_producer_cases']['unknown_basis_erased']
    seqs = sorted(set(map(int, re.findall('native-port:' + re.escape(n['run']) + r':([0-9]+):(?:inputs|outputs)', case['message']))))
    if case['rejected'] is True and len(seqs) == 1:
        seq = seqs[0]
        if not any(seq in sh['sequences'] and sh['unresolved_object_ports'] > 0 for sh in n['shards']):
            raise ValueError('saved native-only selection is absent from final partial-reference shard')
        selected.setdefault(seq, {'sequence': seq, 'roles': [], 'selection': []})
        selected[seq]['roles'].append('NATIVE_ONLY_FROM_FINAL_GATE_NEGATIVE')
        selected[seq]['selection'].append({'metadata': receipt(negative_path), 'pointer': '#/native_only_and_producer_cases/unknown_basis_erased'})
        supporting.append(negative_path)
    domain_path = ISO / 'artifacts/experiments/native_capture_batch_attempt02_20261025/domain-observation.json'
    domain = json.loads(read(domain_path))
    zero = []
    for example in domain['cases']:
        nodes = [r['node'] for r in example['native_records'] if any(a['name'] == 'op_schema' and a['value'] for a in r['node']['attrs'])]
        if len(nodes) == 1 and not any(p['tensor'] for p in (*flat_native(nodes[0]['inputs']), *flat_native(nodes[0]['outputs']))):
            zero.append(example['sequence'])
    if zero:
        seq = next((v for v in zero if v in selected), zero[0])
        if seq not in roots.sequences:
            raise ValueError('saved zero-Tensor selection is absent from final native inventory declaration')
        selected.setdefault(seq, {'sequence': seq, 'roles': [], 'selection': []})
        selected[seq]['roles'].append('ZERO_TENSOR_FROM_SAVED_NATIVE_DECLARATION')
        selected[seq]['selection'].append({'metadata': receipt(domain_path), 'pointer': '#/cases'})
        supporting.append(domain_path)
    # Names/stat only: neither original gzip nor native inventory data is opened.
    stream_stats = [stat_receipt(roots.association_path), stat_receipt(SOURCE / 'dispatch' / d['index']['path'])]
    native_inventory_stats = [stat_receipt(Path(c['artifact']['uri'])) for c in roots.inventory['chunks']]
    publish(BASE / 'inputs.json', {'schema': 'scar.native-context-gate-inputs', 'schema_version': 1, 'inputs': encode(inputs)})
    preflight = {'status': 'REAL_TYPED_ROOTS_AND_SAVED_EXAMPLES_PASS', 'costs': dict(meter.costs),
        'native_final_root': encode(inputs.native_final_batch_report), 'native_dispatches': n['enumerated_dispatch_groups'],
        'native_shards': len(n['shards']), 'native_interfaces': n['static_interfaces'], 'native_frontiers': n['unmodeled_frontier_dispatches'],
        'source_association_declaration': d['observations'], 'samples': list(selected.values()),
        'source_stream_stat_only': stream_stats, 'native_inventory_stat_only': native_inventory_stats,
        'raw_capture_reads': 0, 'association_stream_opens': 0, 'native_inventory_data_opens': 0,
        'archive_chunk_reads': 0, 'sqlite_reads': 0, 'target_executions': 0, 'builder_runs': 0,
        'sample_selection_is_not_query_verification': True, 'wall_seconds': time.monotonic() - started}
    publish(BASE / 'metadata-preflight.json', preflight)
    # A conservative current-main SCAR snapshot covers lazy imports too. This
    # freezes analysis code, not historical collector execution provenance.
    source_rows = []
    source_paths = sorted((ROOT / 'scar').rglob('*.py'))
    source_paths.extend((ROOT / 'sitecustomize.py', ROOT / 'tests/unit/test_source_native_context.py'))
    for path in source_paths:
        row = receipt(path)
        snapshot = BASE / 'frozen-sources' / path.relative_to(ROOT)
        publish(snapshot, read(path))
        source_rows.append({**row, 'snapshot': str(snapshot)})
    runtime = []
    runtime_paths = {Path(sys.executable).resolve(), Path('/usr/bin/time')}
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename:
            path = Path(filename).resolve()
            if path.is_file() and not path.is_relative_to(ROOT) and path.suffix in ('.py', '.so'):
                runtime_paths.add(path)
    for path in sorted(runtime_paths):
        row = receipt(path)
        snapshot = BASE / 'frozen-runtime' / row['sha256']
        if not snapshot.exists(): publish(snapshot, read(path, 128_000_000))
        runtime.append({**row, 'snapshot': str(snapshot)})
    metadata_paths = {Path(getattr(inputs, f).uri) for f in inputs.__dataclass_fields__ if f != 'scope_revision'}
    metadata_paths.add(Path(n['dispatch_inventory']['uri']))
    metadata_paths.add(Path(s['inventory']['path']))
    metadata_paths.update(supporting)
    metadata_paths.update((NATIVE / 'terminal-result.json', ROOT / 'artifacts/experiments/native_capture_batch_applied_20261025/receipt.json'))
    metadata_rows = [receipt(p) for p in sorted(metadata_paths)]
    runners = [receipt(BASE / name) for name in ('prepare.py', 'run_gate.py', 'run.sh', 'README.md', 'inputs.json', 'metadata-preflight.json')]
    frozen = {'schema': 'scar.native-context-gate-freeze', 'schema_version': 1, 'status': 'PREPARED_NOT_EXECUTED',
        'inputs': encode(inputs), 'build_budget': encode(build_budget), 'query_budget': encode(query_budget),
        'source_files': source_rows, 'runtime_files': runtime, 'metadata_files': metadata_rows, 'runner_files': runners,
        'stream_stats': stream_stats, 'native_inventory_stats': native_inventory_stats,
        'samples': list(selected.values()), 'fixed_attempt': str(BASE / 'attempt01'), 'outer_wall_seconds': 240,
        'heartbeat_seconds': 20, 'python': sys.version, 'executable': str(Path(sys.executable).resolve()),
        'zlib_version': zlib.ZLIB_RUNTIME_VERSION, 'historical_collector_implementation_assumption_retained': True,
        'source_dependency_scope': 'all current main scar Python sources, startup sitecustomize and the approved tiny test; actual imported SCAR/startup paths must be contained',
        'runtime_scope': 'current imported external module files including runner resource/signal/subprocess/threading/traceback dependencies, plus Python/time executables; no claim of a complete linked OS library attestation',
        'whole_program_model': 'OPEN', 'raw_or_target_allowed': False, 'association_full_pass_allowed_only_in_explicit_actual_gate': True}
    publish(BASE / 'freeze.json', frozen)
    print(json.dumps({'status': frozen['status'], 'freeze': receipt(BASE / 'freeze.json'),
        'source_files': len(source_rows), 'runtime_files': len(runtime), 'metadata_files': len(metadata_rows),
        'source_bytes': sum(r['bytes'] for r in source_rows), 'runtime_bytes': sum(r['bytes'] for r in runtime),
        'metadata_preflight_costs': preflight['costs'], 'samples': [{'sequence': r['sequence'], 'roles': r['roles']} for r in selected.values()]}))


if __name__ == '__main__': main()
