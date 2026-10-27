"""Root-run, ordinary schema3 publication of every successful saved external SP5."""
from collections import Counter
import cProfile
import argparse
import types
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
            'scope': 'actual normal input reads by phase::family::view; source_control SHA reads included in same512MB total; metadata=archive manifest/control results, graph=SP5, code=archived exact text; Python import IO excluded',
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


def checked_pins(frozen,meter):
    previous=meter.family
    meter.family='source_control'
    try:
        for row in frozen['sources']+frozen['control_inputs']:
            token=meter.begin(row['bytes'])
            actual=receipt(row['path'])
            meter.end(token,'pin_hash_stored',actual['bytes'])
            need(actual==row,'frozen source/control changed: '+row['path'])
    finally:
        meter.family=previous


def aggregates(profiler):
    stats=pstats.Stats(profiler);rows=[]
    for (filename,line,fn),(primitive,total,self_s,cumulative,callers) in stats.stats.items():
        rows.append({'filename':filename,'line':line,'function':fn,'primitive_calls':primitive,
                     'total_calls':total,'self_seconds':self_s,'cumulative_seconds':cumulative})
    rows.sort(key=lambda x:(-x['cumulative_seconds'],x['filename'],x['line'],x['function']))
    return {'function_aggregates':rows,'total_calls':stats.total_calls,'primitive_calls':stats.prim_calls,
            'total_profile_self_s':stats.total_tt,'cProfile_overhead':'included; compare clean children for wall/CPU'}


def child(mode,allowance,seconds):
    global HERE
    top=HERE
    config=json.loads((top/'inputs.json').read_bytes());frozen=json.loads((top/'freeze.json').read_bytes())
    limits=dict(config['budgets']);limits['input_stored_plus_decoded_bytes']=allowance;limits['worker_seconds']=seconds
    meter=Meter(limits);HERE=top/mode;HERE.mkdir(exist_ok=False)
    def terminated(sig,frame):raise TimeoutError('bounded comparison child termination')
    signal.signal(signal.SIGTERM,terminated);signal.signal(signal.SIGALRM,terminated);signal.alarm(seconds)
    try:
        resource.setrlimit(resource.RLIMIT_AS,(config['budgets']['address_space_bytes'],)*2)
        checked_pins(frozen,meter)
        # Baseline is ONLY a benchmark override of the private recursive helper.
        # Current global type/schema plans and every ordinary caller/check stay intact.
        import scar.ir.v2._validation as live
        if mode=='baseline_clean':
            p=Path(config['baseline_source']['path']);raw=p.read_bytes()
            token=meter.begin(len(raw));meter.end(token,'baseline_benchmark_source_stored',len(raw))
            need(hashlib.sha256(raw).hexdigest()==config['baseline_source']['sha256'],'baseline source SHA differs')
            old=types.ModuleType('_benchmark_old_validation');old.__package__='scar.ir.v2'
            exec(compile(raw,str(p),'exec'),old.__dict__)
            live._record_errors=types.FunctionType(old._record_errors.__code__,live.__dict__,
                old._record_errors.__name__,old._record_errors.__defaults__,old._record_errors.__closure__)
        dispatch=live._record_errors.__code__.co_filename
        with measured_reads(meter,tuple(Path(x) for x in config['artifact_read_roots']),128_000_000):
            from scar.analysis.code_witness import CodeWitnessStore,CodeWitnessBudget
            from scar.analysis.inventory_partitions import _read_receipt
            from scar.analysis import program_lowering as lowering
            from scar.ir.record_codec import decode
            from scar.ir.semantics_v2 import SourceSnapshot
            meter.phase='input_preparation';meter.family='metadata'
            store=CodeWitnessStore(config['archive_directory'],budget=CodeWitnessBudget(max_compile_keys=64,
                max_source_files=64,max_source_bytes=2_000_000,max_module_bytes=32_000_000,
                max_archive_bytes=64_000_000,max_manifest_bytes=8_000_000))
            need(store.receipt()==config['archive_store'],'exact original readonly archive differs')
            snapshot=decode(SourceSnapshot,config['snapshot'])
            meter.family='code';text=store.text(snapshot)
            meter.family='graph';doc,raw_receipt=_read_receipt(config['program']['uri'],limit=128_000_000)
            need(all(raw_receipt[k]==config['program'][k] for k in raw_receipt),'normal SP5 receipt differs')
            need(doc['metadata']['source']==config['snapshot'],'original SP5 source snapshot differs')
            input_preparation_wall=time.monotonic()-START
            # Observe bytes already made by the ordinary internal codec check.
            # No extra result.to_dict or serialization pass is added.
            canonical_impl=lowering._canonical;seen=[];digest_wall=0.0
            def canonical_observed(value):
                nonlocal digest_wall
                data=canonical_impl(value)
                if type(value) is dict and value.get('schema')=='scar.source-program' and value.get('schema_version')==5:
                    beg=time.monotonic();digest=hashlib.sha256(data).hexdigest();digest_wall+=time.monotonic()-beg
                    seen.append({'role':'input' if value is doc else 'output','sha256':digest,'bytes':len(data)})
                return data
            lowering._canonical=canonical_observed
            profiler=cProfile.Profile() if mode=='candidate_profile' else None
            meter.phase='read_structure';meter.family='metadata';before=dict(meter.actual)
            wall=time.monotonic();cpu=time.process_time()
            try:
                if profiler:profiler.enable()
                program=lowering.SourceProgram.read_structure(doc,max_operations=10000,source_texts={snapshot.path:text})
            finally:
                if profiler:profiler.disable()
                elapsed=time.monotonic()-wall;cpu_elapsed=time.process_time()-cpu
                lowering._canonical=canonical_impl
            need(program.metadata.source==snapshot and program.graph is not None and program.interface is not None,
                 'normal structural result differs')
            inputs=[x for x in seen if x['role']=='input'];outputs=[x for x in seen if x['role']=='output']
            need(inputs and outputs and all(x['sha256']==inputs[0]['sha256'] and x['bytes']==inputs[0]['bytes'] for x in seen),
                 'ordinary internal canonical codec output/input identities differ')
            need(store.counts['compile_attempts']==0 and store.counts['source_bytes_read']==0 and not store.writable,
                 'readonly text lookup compiled/read live source')
            if profiler:save('profile.json',aggregates(profiler))
            structure_identity={'canonical_sha256':outputs[0]['sha256'],'canonical_bytes':outputs[0]['bytes'],
                'structure_valid':True,'basis':'actual bytes observed during normal SourceProgram.from_dict canonical result/input equality; no extra to_dict/encode'}
            phase_IO={k:v-before.get(k,0) for k,v in meter.actual.items() if v!=before.get(k,0)}
        checked_pins(frozen,meter)
        need('scar.analysis.source_frontend_worklist' not in sys.modules,'unrelated changed worklist module imported into comparison')
        pinned={x['path']:x for x in frozen['sources']};imports=[]
        for name,module in sorted(sys.modules.items()):
            if name=='scar' or name.startswith('scar.'):
                p=str(Path(getattr(module,'__file__','')).resolve());need(p in pinned,'SCAR imported outside frozen main')
                imports.append({'module':name,**pinned[p]})
        save('imports.json',{'modules':imports,'baseline_override_file':dispatch if mode=='baseline_clean' else None})
        save('result.json',{'status':'BENCHMARK_STRUCTURE_ONLY','mode':mode,'wall_s':elapsed,'process_cpu_s':cpu_elapsed,
             'input_preparation_wall_s':input_preparation_wall,'ordinary_codec_digest_observer_wall_s':digest_wall,
             'digest_observer':'same SHA-only observation of normal canonical bytes in all3 children; included in timed region',
             'structure_identity':structure_identity,'normal_canonical_observations':len(seen),
             'validation_dispatch_file':dispatch,'archive_counts':dict(store.counts),'input_IO':meter.report(),
             'read_structure_actual_input_delta':phase_IO,'current_runtime_or_CodeWitness_qualification':False,
             'new_graph_or_model_produced':False,'target_executed':False})
    except BaseException as error:
        save('failure.json',{'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc(),
             'input_IO':meter.report(),'whole_elapsed_s':time.monotonic()-START})
        raise
    finally:signal.alarm(0)


def parent():
    config=json.loads((HERE/'inputs.json').read_bytes());frozen=json.loads((HERE/'freeze.json').read_bytes())
    meter=Meter(config['budgets']);children=[]
    def terminate(sig,frame):raise TimeoutError('comparison parent root/wall termination')
    signal.signal(signal.SIGTERM,terminate);signal.signal(signal.SIGALRM,terminate)
    try:
        need(not (HERE/'started.json').exists(),'comparison gate must be fresh')
        save('started.json',{'freeze':receipt(HERE/'freeze.json'),'status':'RUNNING'})
        signal.alarm(config['budgets']['worker_seconds'])
        resource.setrlimit(resource.RLIMIT_AS,(config['budgets']['address_space_bytes'],)*2)
        checked_pins(frozen,meter)
        for mode in ('baseline_clean','candidate_clean','candidate_profile'):
            remaining=config['budgets']['input_stored_plus_decoded_bytes']-sum(meter.actual.values())
            seconds=max(1,int(config['budgets']['worker_seconds']-(time.monotonic()-START)))
            with (HERE/(mode+'-stdout.txt')).open('xb') as out,(HERE/(mode+'-stderr.txt')).open('xb') as err:
                completed=subprocess.run([sys.executable,str(HERE/'run.py'),'--child',mode,'--allowance',str(remaining),
                    '--seconds',str(seconds)],cwd=TREE,stdout=out,stderr=err,timeout=seconds+5)
            p=HERE/mode/('result.json' if completed.returncode==0 else 'failure.json')
            raw=p.read_bytes();token=meter.begin(len(raw)*2);meter.end(token,'child_metadata_read_stored_and_decoded',len(raw)*2)
            value=json.loads(raw);n=value['input_IO']['actual_stored_plus_decoded_bytes']
            token=meter.begin(n);meter.end(token,mode+'::all_child_actual_input_including_pins',n)
            children.append({'mode':mode,'actual_exit':completed.returncode,'result':value})
            save(mode+'-terminal.json',{'actual_child_exit':completed.returncode,'result_path':str(p),
                'input_IO':value['input_IO']})
            need(completed.returncode==0,'child failed; retain original failure: '+mode)
            with (HERE/'progress.jsonl').open('a') as f:f.write((canonical({'mode':mode,'actual_child_exit':0,
                'whole_elapsed_s':time.monotonic()-START,'structure_wall_s':value['wall_s']})+b'\n').decode())
        identities=[x['result']['structure_identity'] for x in children]
        need(all(x==identities[0] for x in identities),'old/new clean/profile structural output hash differs')
        checked_pins(frozen,meter)
        size=sum(p.stat().st_size for p in HERE.rglob('*') if p.is_file())
        need(size<=config['budgets']['output_bytes'],'comparison output ceiling exceeded')
        save('result.json',{'status':'ACTUAL_SAME_SP5_STRUCTURE_COMPARISON_ONLY','children':[
          {'mode':x['mode'],'actual_exit':x['actual_exit'],'wall_s':x['result']['wall_s'],
           'process_cpu_s':x['result']['process_cpu_s'],'digest_observer_wall_s':x['result']['ordinary_codec_digest_observer_wall_s']}
          for x in children],'structure_identity':identities[0],'equal_output_hash_and_structure':True,
          'input_IO':meter.report(),'output_bytes_before_result':size,'whole_elapsed_s':time.monotonic()-START,
          'cProfile_speedup_claim':False,'new_model_runtime_or_CodeWitness_qualification':False,
          'full26_speedup_or_publication_claim':False})
        print(json.dumps({'status':'ACTUAL_SAME_SP5_STRUCTURE_COMPARISON_ONLY','children':[
            {'mode':x['mode'],'wall_s':x['result']['wall_s']} for x in children],'input_IO':meter.report()}),flush=True)
    except BaseException as error:
        save('failure.json',{'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc(),
            'completed_children':[x['mode'] for x in children],'input_IO':meter.report(),'whole_elapsed_s':time.monotonic()-START})
        raise
    finally:signal.alarm(0)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--child',choices=('baseline_clean','candidate_clean','candidate_profile'))
    parser.add_argument('--allowance',type=int);parser.add_argument('--seconds',type=int);args=parser.parse_args()
    if args.child:child(args.child,args.allowance,args.seconds)
    else:parent()
