"""One retained gate's I/O/activity budgets; no production authority adapter."""
import builtins
import gzip
import hashlib
import io
import os
from pathlib import Path
import symtable
import sys

class _InputFile:
    def __init__(self, wrapped, guard, row):
        self._wrapped,self._guard,self._row=wrapped,guard,row
        self._hash=hashlib.sha256();self._position=0;self._contiguous=True
    def __getattr__(self,name):return getattr(self._wrapped,name)
    def __enter__(self):self._wrapped.__enter__();return self
    def __exit__(self,*args):return self._wrapped.__exit__(*args)
    def __iter__(self):return self
    def __next__(self):
        value=self.readline()
        if not value:raise StopIteration
        return value
    def _read(self,name,*args,**kwargs):
        before=self._wrapped.tell();value=getattr(self._wrapped,name)(*args,**kwargs)
        data=value.encode('utf8') if isinstance(value,str) else bytes(value)
        self._guard.charge(len(data),'stored_bytes')
        if self._contiguous and before==self._position:
            self._hash.update(data);self._position+=len(data)
            if self._position==self._row['stored_bytes']:
                if self._hash.hexdigest()!=self._row['stored_sha256']:raise ValueError('input physical SHA differs: '+self._row['path'])
                self._guard.physical_verified.add(self._row['path'])
        else:self._contiguous=False
        return value
    def read(self,*args,**kwargs):return self._read('read',*args,**kwargs)
    def read1(self,*args,**kwargs):return self._read('read1',*args,**kwargs)
    def readline(self,*args,**kwargs):return self._read('readline',*args,**kwargs)
    def readinto(self,buffer):
        value=self.read(len(buffer));buffer[:len(value)]=value;return len(value)

class GateGuards:
    def __init__(self,freeze,selection,attempt):
        self.freeze,self.selection,self.attempt=freeze,selection,Path(attempt).resolve()
        self.inputs={r['path']:r for r in freeze['inputs']}
        self.by_sha={}
        for row in freeze['inputs']:self.by_sha.setdefault(row['stored_sha256'],[]).append(row)
        self.root=Path(freeze['production_sources'][0]['path']).parents[2]
        self.main=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
        self.namespaces=tuple(freeze['target_namespace_roots'])
        self.target_sources={row['source_path']:row['snapshot']['fingerprint'].removeprefix('sha256:') for row in selection['files'].values()}
        self.counts={'stored_bytes':0,'decoded_bytes':0,'actual_input_bytes':0,'target_executable_compile_attempts':0,
                     'target_exec_attempts':0,'source_prepare_attempts':0,'ast_only_compile_calls':0,
                     'symtable_calls':0,'target_analysis_compile_audit_events':0,'non_target_compile_audit_events':0}
        self.physical_verified=set();self.decoded_verified={};self.analysis=None
        self.original_open=builtins.open;self.original_io_open=io.open
        self.original_compile=builtins.compile;self.original_symtable=symtable.symtable
    def charge(self,n,kind):
        self.counts[kind]+=n;self.counts['actual_input_bytes']+=n
        if self.counts['actual_input_bytes']>self.freeze['limits']['total_input_bytes']:
            raise ValueError('retained actual stored+decoded input budget exceeded, including repeated reads')
    def target(self,filename):
        if not isinstance(filename,(str,bytes,os.PathLike)):return False
        name=os.fsdecode(filename)
        return any(name==root or name.startswith(root+'/') for root in self.namespaces)
    def check_input(self,path):
        path=Path(path)
        if path.is_symlink():raise ValueError('input became symlink')
        row=self.inputs.get(str(path.resolve()))
        if row is None:raise ValueError('unfrozen retained input read: '+str(path))
        s=path.stat()
        if (s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_ino,s.st_dev)!=(row['size'],row['mtime_ns'],row['ctime_ns'],row['inode'],row['device']):
            raise ValueError('frozen input stat changed: '+str(path))
        return row
    def wrap_open(self,original):
        def opened(file,*args,**kwargs):
            if isinstance(file,(str,bytes,os.PathLike)):
                path=Path(os.fsdecode(file)).absolute()
                if path.is_relative_to(self.main/'artifacts'):
                    row=self.check_input(path)
                    stream=original(file,*args,**kwargs)
                    return stream if isinstance(stream,_InputFile) else _InputFile(stream,self,row)
            return original(file,*args,**kwargs)
        return opened
    def _analysis_source(self,source,filename):
        data=source.encode('utf8') if isinstance(source,str) else bytes(source)
        if self.target_sources.get(os.fsdecode(filename))!=hashlib.sha256(data).hexdigest():
            raise ValueError('AST/symtable input is not exact archived source bytes')
    def audit(self,event,args):
        if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
            path=Path(os.fsdecode(args[0])).absolute();mode=args[1] or '';flags=args[2] or 0
            writing=any(x in mode for x in 'wax+') or bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
            if path.is_relative_to(self.main) or self.target(path):
                if writing:raise PermissionError('main/target input writes prohibited')
                if self.target(path):raise PermissionError('live target source reads prohibited; use exact retained UTF8')
                if path.is_relative_to(self.main/'artifacts'):self.check_input(path)
            if writing and path.is_relative_to(self.root) and not path.is_relative_to(self.attempt):
                raise PermissionError('gate writes must stay in fresh attempt directory')
        elif event=='compile':
            if self.target(args[1]):
                if self.analysis not in ('AST','SYMTABLE'):
                    self.counts['target_executable_compile_attempts']+=1
                    raise RuntimeError('target executable compilation prohibited')
                self._analysis_source(args[0],args[1]);self.counts['target_analysis_compile_audit_events']+=1
            else:self.counts['non_target_compile_audit_events']+=1
        elif event=='exec' and args and self.target(getattr(args[0],'co_filename',None)):
            self.counts['target_exec_attempts']+=1;raise RuntimeError('retained target CodeType execution prohibited')
    def install(self):
        builtins.open=self.wrap_open(self.original_open);io.open=self.wrap_open(self.original_io_open)
        def compile_checked(source,filename,mode,flags=0,dont_inherit=False,optimize=-1,**kwargs):
            if self.target(filename):
                if not flags & 1024:  # ast.PyCF_ONLY_AST; executable CodeType not permitted.
                    self.counts['target_executable_compile_attempts']+=1;raise RuntimeError('target executable compile prohibited')
                self._analysis_source(source,filename);old=self.analysis;self.analysis='AST'
                self.counts['ast_only_compile_calls']+=1
                try:return self.original_compile(source,filename,mode,flags,dont_inherit,optimize,**kwargs)
                finally:self.analysis=old
            return self.original_compile(source,filename,mode,flags,dont_inherit,optimize,**kwargs)
        builtins.compile=compile_checked
        def symtable_checked(source,filename,compile_type):
            if not self.target(filename):return self.original_symtable(source,filename,compile_type)
            self._analysis_source(source,filename);old=self.analysis;self.analysis='SYMTABLE';self.counts['symtable_calls']+=1
            try:return self.original_symtable(source,filename,compile_type)
            finally:self.analysis=old
        symtable.symtable=symtable_checked
        def no_prepare(*args,**kwargs):
            self.counts['source_prepare_attempts']+=1;raise RuntimeError('fresh source preparation/rebuild prohibited')
        for name,module in tuple(sys.modules.items()):
            if name.startswith('scar.'):
                for attr in ('prepare_source','_build_generated_source_layers'):
                    if callable(module.__dict__.get(attr)):setattr(module,attr,no_prepare)
        original_init=gzip.GzipFile.__init__;original_read=gzip.GzipFile.read
        def gzip_init(stream,*args,**kwargs):
            original_init(stream,*args,**kwargs);stream._gate_input_row=None
            name=getattr(stream,'name',None)
            if name and str(Path(name).absolute()) in self.inputs:stream._gate_input_row=self.inputs[str(Path(name).absolute())]
            fileobj=kwargs.get('fileobj')
            if stream._gate_input_row is None and isinstance(fileobj,io.BytesIO):
                candidates=self.by_sha.get(hashlib.sha256(fileobj.getvalue()).hexdigest(),[])
                if len(candidates)>1:raise ValueError('compressed budget origin ambiguous; do not merge namespaces')
                if candidates:stream._gate_input_row=candidates[0]
            stream._gate_decoded_hash=hashlib.sha256();stream._gate_decoded_count=0
        def gzip_read(stream,size=-1):
            data=original_read(stream,size)
            row=getattr(stream,'_gate_input_row',None)
            if row is not None:
                self.charge(len(data),'decoded_bytes');stream._gate_decoded_hash.update(data);stream._gate_decoded_count+=len(data)
                limit=self.freeze['limits']['composition_root_bytes'] if row['path'] in self.freeze['allowed_composition_roots'] else self.freeze['limits']['record_context_bytes']
                if stream._gate_decoded_count>limit:raise ValueError('independent composition/context decoded cap exceeded')
                if size<0 or len(data)<size:
                    if row['decoded_bytes'] is not None and stream._gate_decoded_count!=row['decoded_bytes']:raise ValueError('EOF decoded count differs: '+row['path'])
                    digest=stream._gate_decoded_hash.hexdigest()
                    if row['decoded_sha256'] is not None and digest!=row['decoded_sha256']:raise ValueError('EOF decoded SHA differs: '+row['path'])
                    self.decoded_verified[row['path']]={'bytes':stream._gate_decoded_count,'sha256':digest}
            return data
        gzip.GzipFile.__init__=gzip_init;gzip.GzipFile.read=gzip_read
        sys.addaudithook(self.audit)
    def receipt(self):
        return {'counts':dict(self.counts),'input_budget_scope':'actual retained physical plus gzip decoded reads, including repeats; producer/source hash checks separate',
                'physical_verified_paths':sorted(self.physical_verified),'decoded_eof_receipts':dict(self.decoded_verified),
                'raw_capture_reads':0,'new_episode':False,'source_prepare_guard_installed':True,
                'target_exec_and_compile_guards_installed':True,'ast_symtable_are_analysis_not_executable_compile':True}
