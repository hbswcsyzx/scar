"""Root-run, ordinary schema3 publication of every successful saved external SP5."""
from collections import Counter
import cProfile
import pstats
from functools import wraps
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
        self.phase = 'setup'
        self.family = 'metadata'
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
        key = self.phase+'::'+self.family+'::'+kind
        self.actual[key] += amount
        self.reads[key] += 1
        need(sum(self.actual.values()) + self.pending <= self.limit, 'actual input ceiling exceeded')
        self.check()
    def report(self):
        return {'ceiling': self.limit, 'actual_reader_returned_bytes': dict(self.actual),
            'actual_stored_plus_decoded_bytes': sum(self.actual.values()),
            'pending_reservations_not_actual': self.pending, 'read_calls': dict(self.reads),
            'budget_refusal': self.refused, 'whole_elapsed_s': time.monotonic() - START,
            'scope': 'actual normal input reads by phase::family::view; metadata=composition/inventory/manifest/header, graph=source graphs/SP5/CP1/CP2, code=archived text/module/source receipts; source/control SHA separately measured',
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


@contextmanager
def role(meter, family):
    previous = meter.family
    meter.family = family
    try:
        yield
    finally:
        meter.family = previous


@contextmanager
def instrument_families(meter, sp5_paths):
    """Tag delegated reader calls without changing results or checks."""
    from scar.analysis import source_attachments as sa, source_layers as sl
    from scar.analysis import source_program_publication as pub
    from scar.analysis.inventory_partitions import InventoryPartitions
    from scar.analysis.code_witness import CodeWitnessStore
    changed = []
    def install(owner, name, choose):
        original = getattr(owner,name)
        @wraps(original)
        def wrapped(*args,**kwargs):
            with role(meter, choose(*args,**kwargs)):
                return original(*args,**kwargs)
        setattr(owner,name,wrapped)
        changed.append((owner,name,original))
    install(CodeWitnessStore,'_read',lambda self,relative,limit: 'metadata' if relative=='manifest.json' else 'code')
    install(sa.SourceAttachments,'_aux',lambda self,locator,source_root,family: 'code' if family=='sources' else 'metadata')
    install(sa,'load_source_graph_artifact',lambda *args,**kw:'graph')
    install(sl,'_read_bounded',lambda *args,**kw:'graph')
    install(InventoryPartitions,'_read',lambda self,ref: 'graph' if ref['representation'].startswith(('scar.source-program/','scar.body-construction-checkpoint/')) else 'metadata')
    install(pub,'_read_receipt',lambda path,**kw: 'graph' if str(Path(path)) in sp5_paths else 'metadata')
    try:
        yield
    finally:
        for owner,name,original in reversed(changed):
            setattr(owner,name,original)


def check_closure(config):
    p=Path(config['static_closure']['path'])
    need(receipt(p)==config['static_closure'],'static closure receipt changed')
    doc=json.loads(p.read_bytes())
    for row in doc['bound_static_references']:
        path=Path(row['path']);s=path.stat()
        need(path.is_file() and not path.is_symlink() and path.resolve(strict=True)==path
             and [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]==row['stat'],
             'prepared original static ancestor changed: '+str(path))


def take_profile(name, function, meter):
    meter.phase=name
    profiler=cProfile.Profile()
    before=dict(meter.actual)
    wall=time.monotonic();cpu=time.process_time();ok=False
    try:
        profiler.enable()
        value=function()
        profiler.disable()
        ok=True
        return value
    finally:
        profiler.disable()
        elapsed=time.monotonic()-wall;cpu_elapsed=time.process_time()-cpu
        stats=pstats.Stats(profiler)
        rows=[]
        for (filename,line,func),(primitive,total,self_s,cumulative,callers) in stats.stats.items():
            rows.append({'filename':filename,'line':line,'function':func,'primitive_calls':primitive,
                         'total_calls':total,'self_seconds':self_s,'cumulative_seconds':cumulative})
        rows.sort(key=lambda x:(-x['cumulative_seconds'],x['filename'],x['line'],x['function']))
        delta={key:value-before.get(key,0) for key,value in meter.actual.items() if value!=before.get(key,0)}
        save(name+'.json',{'schema':'scar.external-entry-publication-profile/1','phase':name,'completed':ok,
             'wall_s':elapsed,'process_cpu_s':cpu_elapsed,'total_calls':stats.total_calls,
             'primitive_calls':stats.prim_calls,'total_profile_self_s':stats.total_tt,
             'function_aggregates':rows,'actual_input_delta':delta,
             'scope':'one original public call; cProfile overhead included; no locals/source/tensor values/call payloads saved'})
        meter.check()


def main():
    config=json.loads((HERE/'inputs.json').read_bytes())
    frozen=json.loads((HERE/'freeze.json').read_bytes())
    meter=Meter(config['budgets']);control_reads=0;stop_signal=None
    def check_freeze():
        nonlocal control_reads
        for row in frozen['sources']+frozen['control_inputs']:
            r=receipt(row['path']);control_reads+=r['bytes']
            need(r==row,'frozen source/control changed: '+row['path'])
        need(control_reads<=config['budgets']['source_and_control_hash_bytes'],'source/control SHA ceiling exceeded')
    def progress(stage,**kw):
        with (HERE/'progress.jsonl').open('a') as stream:
            stream.write((canonical({'stage':stage,'whole_elapsed_s':time.monotonic()-START,**kw})+b'\n').decode())
        meter.check()
    def terminate(signum,frame):
        nonlocal stop_signal
        stop_signal=signum
        raise TimeoutError('profiling root/worker termination; preserve partials')
    signal.signal(signal.SIGTERM,terminate)
    signal.signal(signal.SIGALRM,terminate)
    try:
        need(not (HERE/'started.json').exists(),'profile gate must be fresh')
        save('started.json',{'status':'RUNNING','freeze':receipt(HERE/'freeze.json')})
        check_freeze()
        signal.alarm(config['budgets']['worker_seconds'])
        resource.setrlimit(resource.RLIMIT_AS,(config['budgets']['address_space_bytes'],)*2)
        setup_begin=time.monotonic();setup_cpu=time.process_time()
        with measured_reads(meter,tuple(Path(x) for x in config['artifact_read_roots']),config['budgets']['max_record_bytes']):
            from scar.analysis.code_witness import CodeWitnessBudget
            from scar.analysis.compiler_witness_archives import CompilerArchiveBudget,CompilerWitnessArchives
            from scar.analysis.source_attachments import SourceAttachments,SourceAttachmentBudget
            from scar.analysis.source_entry_catalog import SourceEntryCatalog
            from scar.analysis.program_composition import CompositionIndex
            from scar.analysis.program_lowering import SourceProgram
            from scar.analysis.source_language import SourceCodeEvidence
            from scar.analysis import source_program_publication as pub
            from scar.ir.record_codec import encode
            paths=set(config['historical_SP5_paths']+[config['first_success']['program']['uri']])
            with instrument_families(meter,paths):
                check_closure(config)
                attempts=[json.loads(x) for x in Path(config['worker_attempts']['path']).read_text().splitlines() if x]
                good=[x for x in attempts if x['status']=='SUCCEEDED']
                need(good and good[0]==config['first_success'],'mechanical first successful original entry changed')
                owner=SourceAttachments(config['continuation']['path'],expected_report_sha256=config['continuation']['sha256'],
                    project_root=config['project_root'],budget=SourceAttachmentBudget(max_report_bytes=8_000_000,
                    max_files=256,max_codes=8192,max_roots=8,max_artifact_bytes=512_000_000,max_record_bytes=128_000_000,cached_files=2))
                archives=CompilerWitnessArchives(tuple((x['directory'],x['manifest']['sha256']) for x in config['archives']),
                    store_budget=CodeWitnessBudget(max_compile_keys=64,max_source_files=64,max_source_bytes=2_000_000,
                       max_module_bytes=32_000_000,max_archive_bytes=64_000_000,max_manifest_bytes=8_000_000),
                    budget=CompilerArchiveBudget(max_archives=3,max_total_modules=64,max_total_sources=64,max_declared_payload_bytes=64_000_000))
                project=CompositionIndex(config['plain858']['path'],max_input_bytes=128_000_000,max_record_bytes=128_000_000)
                need(project.index_receipt['raw_sha256']==config['plain858']['sha256']
                     and project.index_receipt['raw_bytes']==config['plain858']['bytes'],'original plain858 changed')
                catalog=SourceEntryCatalog(admissions=(owner,),projects=(project,),archives=archives,
                    max_groups=8192,max_candidates=8192,max_selected_decode_bytes=512_000_000)
                metadata=catalog.metadata()
                need(metadata['entered_code_groups']==817 and metadata['entered_invocations']==100438,'original catalog denominator differs')
                entry=catalog.resolve(good[0]['entry_key'])
                need(encode(entry.reference)==good[0]['entry_reference'],'genuine first entry reference differs')
                setup={'wall_s':time.monotonic()-setup_begin,'process_cpu_s':time.process_time()-setup_cpu,
                    'input_IO':meter.report(),'genuine_project_and_catalog':True,
                    'bound_project_decoded_bytes':project.index_receipt['decoded_bytes'],
                    'scope':'normal setup, original ancestors and only first selected external definition; not cProfile phase attribution'}
                save('setup.json',setup);progress('genuine_setup_complete',setup_wall_s=setup['wall_s'])
                first=take_profile('source_inputs_first',project.source_inputs,meter)
                progress('profile_source_inputs_first_complete')
                second=take_profile('source_inputs_repeat',project.source_inputs,meter)
                need(first==second,'same owned project source_inputs changed')
                progress('profile_source_inputs_repeat_complete')
                meter.phase='context_and_SP5_read'
                before=dict(meter.actual);beg=time.monotonic();cpu=time.process_time()
                expected=good[0]['program']
                # Exactly one normal reader call for this original selected SP5.
                doc,actual=pub._read_receipt(expected['uri'],limit=config['budgets']['max_record_bytes'])
                need(all(actual[key]==expected[key] for key in actual),'original SP5 physical/decoded receipt changed')
                need(pub._entry_canonical(doc,actual),'original SP5 canonical payload changed')
                context=catalog.prepare(entry)
                evidence=SourceCodeEvidence.from_entry(catalog,entry)
                need(doc['language']['code_evidence']==evidence.to_dict(),'original source/compiler evidence differs')
                save('context-and-read.json',{'wall_s':time.monotonic()-beg,'process_cpu_s':time.process_time()-cpu,
                    'actual_input_delta':{k:v-before.get(k,0) for k,v in meter.actual.items() if v!=before.get(k,0)},
                    'original_selected_program':expected,'normal_SP5_reader_calls':1,
                    'text_retained_from':'genuine catalog.prepare using archived CodeWitness/source context',
                    'source_text_or_code_payload_saved':False})
                progress('genuine_context_SP5_ready')
                program=take_profile('read_structure',lambda:SourceProgram.read_structure(doc,max_operations=10000,
                    source_texts={entry.reference.snapshot.path:context.text}),meter)
                need(program.metadata.source==entry.reference.snapshot and program.interface.definition==entry.reference.definition
                     and program.structured.definition==entry.reference.definition,'typed structure changed original definition')
                progress('profile_read_structure_complete')
                counts=[dict(archives.store_for(row).counts) for row in archives.receipts()]
                need(all(x['compile_attempts']==0 and x['source_bytes_read']==0 for x in counts),'archive compiled/read live source')
                check_closure(config)
        imported=[];pinned={x['path']:x for x in frozen['sources']}
        for name,module in sorted(sys.modules.items()):
            if name=='scar' or name.startswith('scar.'):
                path=str(Path(getattr(module,'__file__','')).resolve())
                need(path in pinned,'SCAR import outside frozen main tree: '+path)
                imported.append({'module':name,**pinned[path]})
        save('imports.json',{'tree':str(TREE),'modules':imported,'count':len(imported)})
        check_freeze()
        size=sum(p.stat().st_size for p in HERE.rglob('*') if p.is_file())
        need(size<=config['budgets']['output_bytes'],'profile output ceiling exceeded')
        save('result.json',{'status':'ACTUAL_BOUNDED_PROFILE_ONLY','setup':setup,
             'source_inputs_profiles':2,'read_structure_profiles':1,'selected_original_entry_key':entry.key,
             'original_successes':len(good),'profile_output':'function aggregates only; no tensor/source/locals values',
             'source_inputs_results_equal':True,'normal_SP5_reader_calls':1,'readonly_archive_counts':counts,
             'input_IO':meter.report(),'separate_source_control_hash_bytes':control_reads,'output_bytes_before_result':size,
             'main_import_count':len(imported),'whole_elapsed_s':time.monotonic()-START,
             'target_executed':False,'source_relowered':False,'new_publication':False,'current369749_binding':'NOT_RUN',
             'first_stage_complete':False,'whole26_cost_fraction':'NOT_MEASURED_BY_SINGLE_ENTRY_PROFILE'})
        print(json.dumps({'status':'ACTUAL_BOUNDED_PROFILE_ONLY','whole_elapsed_s':time.monotonic()-START,
                          'input_IO':meter.report()}),flush=True)
    except BaseException as error:
        save('failure.json',{'status':'FAILED_RETAINED','type':type(error).__name__,'detail':str(error),
            'traceback':traceback.format_exc(),'input_IO':meter.report(),'separate_source_control_hash_bytes':control_reads,
            'stop_signal':stop_signal,'whole_elapsed_s':time.monotonic()-START})
        raise
    finally:
        signal.alarm(0)


if __name__=='__main__':main()
