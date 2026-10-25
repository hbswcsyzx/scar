"""One existing public plan -> worker batch. --prepare never plans or lowers."""
from __future__ import annotations
import ast
import builtins
from collections import Counter
import gzip
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import pickle  # Freeze this lazy stdlib dependency, including _compat_pickle.
import resource
import signal
import sys
import sysconfig
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EX = HERE.parent
sys.path.insert(0, str(ROOT))
OLD = EX / 'first_stage_source_frontend_automatic_20261023'
BASE = EX / 'first_stage_source_body_revision_20261023/result/composition/index.json.gz'
SOURCE = EX / 'first_stage_source_revision_current_20261025/result/connections/source'
TARGET = EX / 'source_call_kwargs_publication_20261025/result/publication/manifest.json'
STORE = EX / 'first_stage_partitioned_operand_routes_20261023/result/code-witnesses'
LAYERS = EX / 'first_stage_source_context_20261022/result/source-layers/index.json'
BUDGET = dict(max_dispatch_bodies=65, max_source_files=13, max_operations_per_body=4000,
    max_total_operations=24000, max_elapsed_seconds=180, max_record_bytes=128_000_000,
    max_output_bytes=128_000_000)
CAPS = ('PYTHON_FIXED_LOCAL_UNPACK_V1', 'PYTHON_SLICE_KEYS_314_V1',
        'PYTHON_LEXICAL_LOCALS_314_V1', 'PYTHON_CALL_KWARGS_314_V1')

def need(value, detail):
    if not value:
        raise ValueError(detail)

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()

def receipt(path):
    path = Path(path).resolve()
    digest, count = sha256(), 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            digest.update(block); count += len(block)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': count}

def load(path, limit=16_000_000):
    path = Path(path)
    need(path.stat().st_size <= limit, 'metadata stored budget exceeded')
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rb') as stream:
        raw = stream.read(limit + 1)
    need(len(raw) <= limit, 'metadata decoded budget exceeded')
    return json.loads(raw)

def save(name, document):
    with (HERE / name).open('xb') as stream:
        stream.write(canonical(document) + b'\n')

def refpath(ref, root):
    return Path(ref['uri']) if ref['external'] else root / ref['uri']

def selection():
    manifest = load(OLD / 'plan/manifest.json')
    tables = {}
    inputs = {OLD / 'plan/manifest.json', OLD / 'worker/attempts.jsonl', TARGET}
    for name, ref in manifest['tables'].items():
        path = refpath(ref, OLD / 'plan')
        actual = receipt(path)
        need((actual['sha256'], actual['bytes']) == (ref['physical_sha256'], ref['physical_bytes']), 'old plan table differs')
        tables[name] = load(path)['rows']; inputs.add(path)
    need(sha256(canonical({'document': manifest['document'], **tables})).hexdigest() == manifest['plan_sha256'],
         'original complete plan digest differs')
    bodies, groups = tables['bodies'], tables['groups']
    need(len(bodies) == 2217 and len(groups) == 817 and sum(row['current_calls'] for row in groups) == 100438,
         'original complete denominator differs')
    bykey = {row['body_key']: row for row in bodies}
    attempts = [json.loads(line) for line in (OLD / 'worker/attempts.jsonl').read_text().splitlines()]
    tried = set()
    for row in attempts:
        body = bykey[row['body_key']]; inp = row['work_input']
        need(inp['snapshot'] == body['snapshot'] and inp['context'] == body['context']
             and inp['definition'] == body['definition']['id']
             and inp['captured'] == body['code_variants'][0]['captured'], 'old attempted qualified identity differs')
        need(row['status'] in ('SUCCEEDED', 'UNSUPPORTED', 'FAILED', 'CODE_WITNESS_UNAVAILABLE', 'SOURCE_CONTEXT_UNAVAILABLE'),
             'old nonterminal record cannot exclude work')
        tried.add(row['body_key'])
    published, publication_refs = set(), []
    path = TARGET
    while True:
        inv = load(path); inputs.add(path)
        if inv['schema_version'] != 2:
            break
        ref = inv['components']['publication']; pubpath = refpath(ref, path.parent)
        actual = receipt(pubpath)
        need((actual['sha256'], actual['bytes']) == (ref['physical_sha256'], ref['physical_bytes']), 'publication delta differs')
        pub = load(pubpath)['value']; inputs.add(pubpath)
        for row in pub['changed_bodies']:
            matches = [body for body in bodies if body['snapshot'] == row['snapshot']
                and body['definition']['id'] == row['definition']
                and body['definition']['source'] == row['source']]
            need(len(matches) == 1, 'publication does not identify one original qualified body')
            identity = (row['snapshot']['path'], row['snapshot']['fingerprint'],
                matches[0]['context']['namespace_root'], row['definition']['wire'])
            published.add(identity)
            publication_refs.append({'identity': identity, 'publication': actual})
        path = refpath(inv['parent_inventory'], path.parent)
    pending = [row for row in bodies if row['metadata_status'] == 'PENDING_CODE_RESOLVE']
    chosen = []
    for row in pending:
        identity = (row['snapshot']['path'], row['snapshot']['fingerprint'], row['context']['namespace_root'], row['definition']['id']['wire'])
        need(row['body_key'] == sha256(canonical({'snapshot': row['snapshot'], 'context': row['context'],
             'definition': row['definition']['id']})).hexdigest(), 'original qualified body key differs')
        if row['body_key'] not in tried and identity not in published:
            chosen.append(row)
    chosen.sort(key=lambda row: (-row['current_calls'], row['body_key']))
    need(len(pending) == 77 and len(tried) == 12 and len(chosen) == 65
         and sum(row['current_calls'] for row in chosen) == 1713
         and len({row['file_index'] for row in chosen}) == 13, 'mechanical window differs from approved scope')
    return {'keys': [row['body_key'] for row in chosen], 'rows': chosen,
        'old_plan_sha256': manifest['plan_sha256'], 'old_pending': len(pending),
        'old_attempted': sorted(tried), 'published_exclusions': publication_refs,
        'calls': sum(row['current_calls'] for row in chosen)}, inputs

class OuterDeadline(BaseException):
    pass

def process_io():
    # Linux process counters contain read syscalls, not gzip-decoded bytes.
    return {key: int(value) for key, value in
        (line.split(':', 1) for line in Path('/proc/self/io').read_text().splitlines())}

def imports():
    from scar.analysis.code_witness import CodeWitnessBudget, CodeWitnessStore
    from scar.analysis.program_composition import CompositionIndex
    from scar.analysis.source_frontend_worklist import SourceFrontendBudget, plan_source_frontend, run_source_frontend
    from scar.ir.program.source_language import SourceLanguageCapability
    return CodeWitnessBudget, CodeWitnessStore, CompositionIndex, SourceFrontendBudget, plan_source_frontend, run_source_frontend, SourceLanguageCapability

def prepare():
    imports()
    selected, paths = selection()
    paths.update((BASE, SOURCE / 'report.json', SOURCE / 'bindings.json', LAYERS, STORE / 'manifest.json'))
    sources = [receipt(path) for path in sorted((ROOT / 'scar').rglob('*.py'))]
    # Pin stdlib source paths once, including dependencies lazily imported by
    # marshal/CodeWitness. No source or runtime payload copies are generated.
    runtime = {Path(sys.executable).resolve()}
    stdlib = Path(sysconfig.get_path('stdlib'))
    runtime.update(path for path in stdlib.rglob('*.py') if 'site-packages' not in path.parts and '__pycache__' not in path.parts)
    for module in tuple(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if name and Path(name).is_file() and not Path(name).resolve().is_relative_to(ROOT):
            runtime.add(Path(name).resolve())
    save('selection.json', {key: value for key, value in selected.items() if key != 'rows'})
    freeze = {'schema': 'scar.source-frontend-remainder-entry', 'schema_version': 1,
        'head_label_supplied_by_root': '5f0d4469', 'entry': receipt(__file__),
        'sources': sources, 'runtime': [receipt(path) for path in sorted(runtime)],
        'inputs': [receipt(path) for path in sorted(paths)], 'selection': receipt(HERE / 'selection.json'),
        'caps': CAPS, 'budget': BUDGET, 'outer_wall_seconds': 300, 'combined_read_allowance_bytes': 1 << 30,
        'planning_base': str(BASE), 'current_report': str(SOURCE / 'report.json'), 'publication_target': str(TARGET),
        'runtime_version': sys.version, 'source_snapshots_copied': 0,
        'io_accounting_status': 'OPEN_COMBINED_STORED_PLUS_DECODED_NOT_MEASURED',
        'combined_read_ceiling_verified': False,
        'plan_or_lower_executed_during_prepare': False}
    save('freeze.json', freeze)
    print(json.dumps({'status': 'READY_FOR_ROOT_REVIEW', 'freeze': receipt(HERE / 'freeze.json'),
        'sources': len(sources), 'runtime_files': len(runtime), 'eligible': len(selected['keys']), 'calls': selected['calls']}))

def run():
    api = imports()
    CodeWitnessBudget, CodeWitnessStore, CompositionIndex, SourceFrontendBudget, planner, worker, Capability = api
    started = time.perf_counter(); initial_io = process_io(); log = (HERE / 'progress.jsonl').open('x', buffering=1)
    def progress(row):
        log.write(json.dumps({'elapsed_s': time.perf_counter()-started,
            'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            **row})+'\n')
    def timer(signum, frame):
        if time.perf_counter()-started >= 300: raise OuterDeadline('outer300s exhausted')
        progress({'stage': 'HEARTBEAT'})
    signal.signal(signal.SIGALRM, timer); signal.setitimer(signal.ITIMER_REAL, 10, 10)
    selected = None
    try:
        freeze = load(HERE / 'freeze.json')
        need(receipt(__file__) == freeze['entry'] and sys.version == freeze['runtime_version'], 'entry/runtime identity changed')
        for category in ('sources', 'runtime', 'inputs'):
            for row in freeze[category]: need(receipt(row['path']) == row, 'frozen '+category+' changed: '+row['path'])
        need(receipt(HERE/'selection.json') == freeze['selection'], 'selection receipt changed')
        selected, _ = selection()
        need({key:value for key,value in selected.items() if key!='rows'} == load(HERE/'selection.json'), 'mechanical eligible window changed')
        store_before = [receipt(path) for path in sorted(STORE.iterdir()) if path.is_file()]
        store = CodeWitnessStore(STORE, budget=CodeWitnessBudget(max_compile_keys=20), create=False, compile_missing=False, progress=progress)
        budget = SourceFrontendBudget(**BUDGET)
        progress({'stage': 'PLAN', 'status': 'BEGIN'})
        composition = CompositionIndex(BASE)
        plan = planner(composition, SOURCE, store, budget=budget,
            capabilities=tuple(Capability(value) for value in CAPS), eligible_body_keys=tuple(selected['keys']),
            out_dir=HERE/'plan', progress=progress)
        summary = plan.document['summary']
        need(summary['bodies']==2217 and summary['current_groups']==817 and summary['current_calls']==100438,
             'full planning denominator changed')
        need(summary['body_statuses']['LOWERED_WITH_GAPS']==843 and len(plan.dispatch)==65,
             'planning base/window differs')
        progress({'stage': 'WORKER', 'status': 'BEGIN', 'plan_sha256': plan.digest})
        result = worker(plan, store, HERE/'worker', budget=budget, resume_from=(), progress=progress)
        need(store.counts['compile_attempts']==0, 'compile budget violated')
        need([receipt(path) for path in sorted(STORE.iterdir()) if path.is_file()]==store_before, 'readonly archive changed')
        frozen_sources={row['path']:row for row in freeze['sources']}
        frozen_runtime={row['path']:row for row in freeze['runtime']}
        for module in tuple(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename and Path(filename).is_file():
                path=Path(filename).resolve()
                if path.is_relative_to(ROOT/'scar'): need(receipt(path)==frozen_sources.get(str(path)), 'participating SCAR source changed')
                elif not path.is_relative_to(ROOT): need(receipt(path)==frozen_runtime.get(str(path)), 'participating runtime not frozen: '+str(path))
        result.update(planning_snapshot_bodies=843, publication_target_bodies=846,
            eligibility_count=65, eligibility_calls=1713, original_run_invocations=100438,
            io_accounting_status='OPEN_COMBINED_STORED_PLUS_DECODED_NOT_MEASURED',
            combined_read_allowance_bytes=1<<30, combined_read_ceiling_verified=False,
            process_io_delta={key: value-initial_io[key] for key,value in process_io().items()},
            io_scope='Linux process read syscall counters exclude decoded gzip bytes; manifest totals are declarations, not actual combined I/O',
            new_publication_performed=False, full_runtime_rebound=False,
            elapsed_outer_s=time.perf_counter()-started)
        save('result.json', result)
        progress({'stage':'FINISHED','status':'FINISHED_WITH_OPEN','counts':result['counts']})
        print(json.dumps({'status':'FINISHED_WITH_OPEN','counts':result['counts'],'io_accounting':result['io_accounting_status']}))
    except BaseException as error:
        # This receipt never causes a worker or input retry.
        save('failure.json', {'status':'FAILED_RETAINED_NO_RETRY','type':type(error).__name__, 'detail':str(error),
            'traceback':traceback.format_exc(),'elapsed_s':time.perf_counter()-started,
            'io_accounting_status':'OPEN_COMBINED_STORED_PLUS_DECODED_NOT_MEASURED',
            'process_io_delta':{key: value-initial_io[key] for key,value in process_io().items()}})
        progress({'stage':'FAILED','type':type(error).__name__,'detail':str(error)})
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        if selected is not None:
            attempted={}
            started_keys={json.loads(path.read_text())['body_key']
                for path in (HERE/'worker').glob('attempt-*/started.json')}
            index=HERE/'worker/attempts.jsonl'
            if index.exists():
                for line in index.read_text().splitlines():
                    row=json.loads(line); attempted[row['body_key']]=row['status']
            save('window-accounting.json', {'eligible':65,'eligible_calls':1713,'rows':[
                {'body_key':row['body_key'],'file_index':row['file_index'],'body_index':row['body_index'],
                 'current_calls':row['current_calls'],'prior_canonical_status':row['prior_status'],
                 'window_status':attempted.get(row['body_key'], 'STARTED_NO_TERMINAL'
                    if row['body_key'] in started_keys else 'NOT_ATTEMPTED_WINDOW_BUDGET_OR_FAILURE')}
                for row in selected['rows']], 'not_attempted_is_window_status_not_rewritten_canonical_status':True})
        log.close()

if __name__ == '__main__':
    prepare() if sys.argv[1:] == ['--prepare'] else run()
