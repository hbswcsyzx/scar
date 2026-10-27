"""Root-run, ordinary schema3 publication of every successful saved external SP5."""
from collections import Counter
from contextlib import contextmanager
import builtins
import gzip
import hashlib
import io
import json
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
TREE = HERE.parents[2]
START = time.monotonic()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def need(value, detail):
    if not value:
        raise ValueError(detail)


def receipt(path):
    path = Path(path)
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def save(name, value):
    path = HERE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(value) + b'\n'
    need(len(raw) <= 16_000_000, 'gate metadata record exceeds16MB')
    with path.open('xb') as stream:
        stream.write(raw)


class Meter:
    def __init__(self, limits):
        self.limit = limits['input_stored_plus_decoded_bytes']
        self.seconds = limits['worker_seconds']
        self.actual = Counter()
        self.pending = 0
        self.reads = Counter()
        self.refused = False
    def check(self):
        need(time.monotonic() - START <= self.seconds, 'whole publication wall budget exceeded')
    def begin(self, amount):
        self.check()
        if sum(self.actual.values()) + self.pending + amount > self.limit:
            self.refused = True
            raise ValueError('stored+decoded ceiling refuses the next bounded reader call')
        self.pending += amount
        return amount
    def end(self, token, kind, amount):
        self.pending -= token
        self.actual[kind] += amount
        self.reads[kind] += 1
        need(sum(self.actual.values()) + self.pending <= self.limit, 'actual input ceiling exceeded')
        self.check()
    def report(self):
        return {'ceiling': self.limit, 'actual_reader_returned_bytes': dict(self.actual),
            'actual_stored_plus_decoded_bytes': sum(self.actual.values()),
            'pending_reservations_not_actual': self.pending, 'read_calls': dict(self.reads),
            'budget_refusal': self.refused, 'whole_elapsed_s': time.monotonic() - START,
            'scope': 'all normal artifact file reads, repeated hash/read/guards, gzip decoded returns, missing Git blob recovery; source/control SHA checks separately recorded',
            'plain_accounting': 'plain bytes count once stored and once decoded, including repeated normal guards',
            'partial_failed_read': 'pending is not claimed as completed or verified IO'}


@contextmanager
def measured_reads(meter, roots, max_record_bytes):
    """Transparent stream counters; every ordinary producer/check remains in place."""
    old_builtin, old_io = builtins.open, io.open
    old_read, old_read1, old_decompress = gzip.GzipFile.read, gzip.GzipFile.read1, gzip.decompress
    depth = 0
    def selected(path):
        return isinstance(path, (str, bytes, Path)) and any(Path(path).resolve().is_relative_to(r) for r in roots)
    class Counted:
        def __init__(self, stream, compressed):
            self.stream, self.compressed = stream, compressed
        def __getattr__(self, key):
            return getattr(self.stream, key)
        def _invoke(self, name, *args):
            size = args[0] if args and type(args[0]) is int else -1
            amount = size if size >= 0 else 0
            if size < 0:
                # stat/tell do not advance the ordinary reader.
                amount = max(0, __import__('os').fstat(self.stream.fileno()).st_size - self.stream.tell())
            token = meter.begin(amount * (1 if self.compressed else 2))
            value = getattr(self.stream, name)(*args)
            n = len(value.encode('utf-8')) if isinstance(value, str) else len(value)
            meter.end(token, 'stored_gzip' if self.compressed else 'stored_and_decoded_plain', n * (1 if self.compressed else 2))
            return value
        def read(self, *args):
            return self._invoke('read', *args)
        def readline(self, *args):
            return self._invoke('readline', *args)
        def readinto(self, buffer):
            token = meter.begin(len(buffer) * (1 if self.compressed else 2))
            n = self.stream.readinto(buffer)
            meter.end(token, 'stored_gzip' if self.compressed else 'stored_and_decoded_plain', (n or 0) * (1 if self.compressed else 2))
            return n
        def __iter__(self):
            return self
        def __next__(self):
            row = self.readline()
            if not row:
                raise StopIteration
            return row
        def __enter__(self):
            self.stream.__enter__()
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
    def opened(original):
        def wrapper(file, mode='r', *args, **kwargs):
            stream = original(file, mode, *args, **kwargs)
            if selected(file) and not any(x in mode for x in 'wax+'):
                return Counted(stream, str(file).endswith('.gz'))
            return stream
        return wrapper
    def decoded(original):
        def wrapper(stream, size=-1):
            nonlocal depth
            if depth:
                return original(stream, size)
            token = meter.begin(size if size >= 0 else max_record_bytes)
            depth += 1
            try:
                value = original(stream, size)
            finally:
                depth -= 1
            meter.end(token, 'decoded_gzip', len(value))
            return value
        return wrapper
    def decompressed(data):
        token = meter.begin(max_record_bytes)
        value = old_decompress(data)
        meter.end(token, 'decoded_gzip_memory', len(value))
        return value
    builtins.open, io.open = opened(old_builtin), opened(old_io)
    gzip.GzipFile.read, gzip.GzipFile.read1, gzip.decompress = decoded(old_read), decoded(old_read1), decompressed
    try:
        yield
    finally:
        builtins.open, io.open = old_builtin, old_io
        gzip.GzipFile.read, gzip.GzipFile.read1, gzip.decompress = old_read, old_read1, old_decompress


def check_static_closure(config):
    path = Path(config['static_closure_receipt']['path'])
    need(receipt(path) == config['static_closure_receipt'], 'prepared static closure metadata changed')
    document = json.loads(path.read_bytes())
    for row in document['bound_static_references']:
        p = Path(row['path'])
        need(p.is_file() and not p.is_symlink() and p.resolve(strict=True) == p,
             'declared static ancestor is unavailable or relocated: '+str(p))
        s = p.stat()
        need([s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns] == row['stat'],
             'declared static ancestor changed after exact availability preflight: '+str(p))


def restore_missing(config, meter):
    """Recover only exact previously declared static artifacts at original URIs."""
    rows = []
    for row in config['missing_static_restoration_whitelist']:
        path = Path(row['path'])
        if path.exists():
            continue
        need(not path.is_symlink(), 'restoration refuses a symlink')
        relative = path.relative_to(TREE)
        token = meter.begin(row['bytes'])
        raw = subprocess.run(['git', 'show', config['recovery_commit'] + ':' + str(relative)], cwd=TREE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
        meter.end(token, 'git_missing_static_stored', len(raw))
        need(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'],
             'original Git blob does not match source858 receipt: ' + str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw)
        rows.append(row)
    save('restored-missing-static.json', {'source': config['plain858_inputs_receipt'], 'commit': config['recovery_commit'],
        'rows': rows, 'bytes': sum(x['bytes'] for x in rows), 'replacement': False, 'URI_relocation': False})


def main():
    config = json.loads((HERE / 'inputs.json').read_bytes())
    frozen = json.loads((HERE / 'freeze.json').read_bytes())
    meter = Meter(config['budgets'])
    # Actual preparation IO is distinct from runtime, but consumes this same ceiling.
    meter.actual.update(config['preparation_actual_input_bytes'])
    control_reads = 0
    def check_freeze():
        nonlocal control_reads
        for row in frozen['sources'] + frozen['control_inputs']:
            actual = receipt(row['path'])
            control_reads += actual['bytes']
            need(actual == row, 'frozen source/control changed: ' + row['path'])
        need(control_reads <= config['budgets']['source_and_control_hash_bytes'], 'separate source/control hash ceiling exceeded')
    def progress(stage, **kwargs):
        with (HERE / 'progress.jsonl').open('a') as stream:
            stream.write((canonical({'stage': stage, 'elapsed_s': time.monotonic()-START, **kwargs}) + b'\n').decode())
        meter.check()
    def terminate(signum, frame):
        raise TimeoutError('root/outer termination; originals and partial publication retained')
    signal.signal(signal.SIGTERM, terminate)
    try:
        need(not (HERE / 'started.json').exists(), 'publication gate must be fresh')
        save('started.json', {'status': 'RUNNING', 'freeze': receipt(HERE / 'freeze.json')})
        check_freeze()
        resource.setrlimit(resource.RLIMIT_AS, (config['budgets']['address_space_bytes'],)*2)
        roots = tuple(Path(x) for x in config['artifact_read_roots'])
        with measured_reads(meter, roots, config['budgets']['max_record_bytes']):
            restore_missing(config, meter)
            check_static_closure(config)
            w = Path(config['worker_root'])
            final = json.loads((w/'worker/manifest.json').read_bytes())
            outer = json.loads((w/'result.json').read_bytes())
            accounting = json.loads((w/'window-accounting.json').read_bytes())
            window = json.loads((w/'metadata-window.json').read_bytes())['dispatch_entries']
            attempts = [json.loads(x) for x in (w/'worker/attempts.jsonl').read_text().splitlines() if x]
            need(outer['worker'] == final and final['publication'] == 'NOT_RUN', 'saved worker terminal differs')
            need(len(window) == final['window'] == len(accounting['entries']) == 50, 'original window denominator changed')
            need(final['original_current_groups'] == 817 and final['original_current_calls'] == 100438,
                 'original group/call denominator changed')
            window_keys = [x['entry_key'] for x in window]
            by_key = {x['entry_key']: x for x in attempts}
            need(len(by_key) == len(attempts) and list(by_key) == window_keys[:len(attempts)], 'terminal rows are not the original ordered dispatch prefix')
            for i, row in enumerate(attempts, 1):
                terminal = json.loads((w/f'worker/attempt-{i:05d}/result.json').read_bytes())
                need(row == terminal, 'attempt stream differs from original terminal')
            status = Counter(x['status'] for x in attempts)
            need(dict(status) == final['counts'], 'worker terminal counts differ')
            expected_accounting = [{'entry_key': x['entry_key'], 'source_calls': x['calls'],
                'status': by_key[x['entry_key']]['status'] if x['entry_key'] in by_key else 'NOT_ATTEMPTED'} for x in window]
            need(accounting['entries'] == expected_accounting, 'full window status reconciliation differs')
            good = [x for x in attempts if x['status'] == 'SUCCEEDED']
            need([x['entry_key'] for x in good] == [x['entry_key'] for x in config['successes']], 'all-success selection changed')
            requests = tuple({'entry_key': x['entry_key'], 'source_program': x['program']} for x in good)
            for original, selected in zip(good, config['successes']):
                need(original == selected, 'success terminal/program/reference changed')
            progress('saved_worker_reconciled', counts=dict(status), not_attempted=final['unattempted_window_entries'])
            from scar.analysis.code_witness import CodeWitnessBudget
            from scar.analysis.compiler_witness_archives import CompilerArchiveBudget, CompilerWitnessArchives
            from scar.analysis.source_attachments import SourceAttachments, SourceAttachmentBudget
            from scar.analysis.source_entry_catalog import SourceEntryCatalog
            from scar.analysis.program_composition import CompositionIndex
            from scar.analysis.source_program_publication import plan_source_entry_publication, publish_source_entries
            from scar.ir.program.source_references import SourceDefinitionReference
            from scar.ir.record_codec import decode, encode
            attachment_budget = SourceAttachmentBudget(max_report_bytes=8_000_000, max_files=256, max_codes=8192,
                max_roots=8, max_artifact_bytes=512_000_000, max_record_bytes=128_000_000, cached_files=2)
            owner = SourceAttachments(config['continuation']['path'], expected_report_sha256=config['continuation']['sha256'],
                                      project_root=config['project_root'], budget=attachment_budget)
            archives = CompilerWitnessArchives(tuple((x['directory'], x['manifest']['sha256']) for x in config['archives']),
                store_budget=CodeWitnessBudget(max_compile_keys=64,max_source_files=64,max_source_bytes=2_000_000,
                    max_module_bytes=32_000_000,max_archive_bytes=64_000_000,max_manifest_bytes=8_000_000),
                budget=CompilerArchiveBudget(max_archives=3,max_total_modules=64,max_total_sources=64,max_declared_payload_bytes=64_000_000))
            project = CompositionIndex(config['plain858']['path'], max_input_bytes=128_000_000,max_record_bytes=128_000_000)
            need(project.index_receipt['raw_sha256'] == config['plain858']['sha256']
                 and project.index_receipt['raw_bytes'] == config['plain858']['bytes'], 'original plain858 receipt changed')
            catalog = SourceEntryCatalog(admissions=(owner,),projects=(project,),archives=archives,
                max_groups=8192,max_candidates=8192,max_selected_decode_bytes=512_000_000)
            metadata = catalog.metadata()
            need(metadata['entered_code_groups'] == 817 and metadata['entered_invocations'] == 100438, 'catalog original denominators differ')
            for row in good:
                need(encode(catalog.resolve(row['entry_key']).reference) == row['entry_reference'], 'normal source definition differs from worker')
            progress('ordinary_catalog_ready', groups=metadata['entered_code_groups'])
            plan = plan_source_entry_publication(project,catalog,requests,max_programs=len(requests),publication_version=3)
            save('publication-plan.json', {'document': plan.document, 'sha256': plan.sha256})
            need(all(x['owner_kind'] == 'DEPENDENCY_ADMISSION' and x['expected_parent_body']['project_slot'] is None
                     for x in plan.document['expectations']), 'external entry acquired project fi/bi')
            published = publish_source_entries(project,catalog,requests,HERE/'publication',plan=plan,max_programs=len(requests),
                max_operations_per_body=10000,max_record_bytes=128_000_000,progress=lambda row: progress('publish',event=row))
            need(published['body_count'] == len(good) and published['schema_version'] == 3, 'publication omitted a successful program')
            progress('publication_complete', bodies=len(good))
            # Independent ordinary factory, not the producer catalog or a JSON-created owner.
            reopened = CompositionIndex.from_source_entry_publication(published['manifest'],expected_sha256=published['sha256'],
                archives=archives,max_input_bytes=128_000_000,max_record_bytes=128_000_000,max_programs=len(good),
                max_operations_per_body=10000,max_catalog_groups=8192,max_catalog_entries=8192,
                max_selected_decode_bytes=512_000_000,attachment_budget=attachment_budget,max_parent_depth=4)
            queries = []
            for row in good:
                definition = decode(SourceDefinitionReference,row['entry_reference'])
                reference = reopened.body_reference(definition)
                need(reference is not None and reference.definition == definition, 'normal query lost original qualified definition')
                record = reopened.qualified_body_record(reference)
                need(record['kind'] == 'QUALIFIED_SOURCE_BODY'
                     and reference.source_program.artifact.uri == row['program']['uri']
                     and reference.source_program.decoded_sha256 == row['program']['decoded_sha256'], 'ordinary query changes original SP5/namespace')
                queries.append({'entry_key':row['entry_key'],'historical_call_weight':row['source_calls'],
                    'reference':encode(reference),'record':record,'current_body_calls':None})
                progress('ordinary_query',entry_key=row['entry_key'])
            save('queries.json', {'schema':'scar.external-source-entry-normal-queries/1','bodies':queries})
            counts = [dict(archives.store_for(row).counts) for row in archives.receipts()]
            need(all(x['compile_attempts'] == 0 and x['source_bytes_read'] == 0 for x in counts), 'readonly compiler archive compiled/read live source')
            save('window-accounting.json',accounting)
            check_static_closure(config)
        imported = []
        declared = {x['path']:x for x in frozen['sources']}
        for name,module in sorted(sys.modules.items()):
            file = getattr(module,'__file__',None)
            if name == 'scar' or name.startswith('scar.'):
                need(file is not None, 'SCAR imported module has no source file')
                path = str(Path(file).resolve())
                need(path in declared, 'SCAR import outside frozen main source set: '+path)
                imported.append({'module':name,**declared[path]})
        save('imports.json',{'tree':str(TREE),'modules':imported,'import_count':len(imported)})
        check_freeze()
        output_bytes = sum(x.stat().st_size for x in HERE.rglob('*') if x.is_file())
        need(output_bytes <= config['budgets']['output_bytes'], 'publication output ceiling exceeded; partials retained')
        save('result.json',{'status':'ACTUAL_SCHEMA3_PUBLICATION_WITH_OPEN','publication':published,'queried':len(queries),
            'worker_status_counts':dict(status),'not_attempted':final['unattempted_window_entries'],
            'original_window':50,'original_groups':817,'original_calls':100438,'window_historical_call_weight':sum(x['calls'] for x in window),
            'new_dynamic_body_calls':None,'source_programs_relowered':False,'target_executed':False,'current369749_binding':'NOT_RUN',
            'sameRun_static_guard_upgraded':False,'first_stage_complete':False,'readonly_archive_counts':counts,
            'ordinary_catalog_measurements':catalog.measurements(),'input_IO':meter.report(),
            'preparation_actual_input_bytes':config['preparation_actual_input_bytes'],
            'prior_failed_root_session':49787,'prior_failed_exit_code':1,
            'separate_source_control_hash_bytes':control_reads,'post_stage_directory_bytes':output_bytes,
            'actual_import_count':len(imported),'whole_elapsed_s':time.monotonic()-START})
        print(json.dumps({'status':'ACTUAL_SCHEMA3_PUBLICATION_WITH_OPEN','queried':len(queries),'input_IO':meter.report()}),flush=True)
    except BaseException as error:
        save('failure.json',{'status':'FAILED_RETAINED','type':type(error).__name__,'detail':str(error),
            'traceback':traceback.format_exc(),'input_IO':meter.report(),'separate_source_control_hash_bytes':control_reads,
            'whole_elapsed_s':time.monotonic()-START})
        raise


if __name__ == '__main__':
    main()
