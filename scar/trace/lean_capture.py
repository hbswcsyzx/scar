"""Explicit static capture selection, never a source/runtime proof authority."""
from __future__ import annotations
from dataclasses import dataclass,field
import dis,hashlib,json,os,sys,weakref
from pathlib import Path
from types import CodeType
from scar.ir.program.call_edges import CapturedCode
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode,encode
from scar.ir.semantics_v2 import SourceSnapshot
from scar.trace.code_snapshot import describe_code

PROFILE='SCAR_LEAN_PORTS_V1'

def _need(value,message):
    if not value:raise ValueError(message)

def _raw(value):
    return (json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(',',':'),allow_nan=False)+'\n').encode('ascii')

@dataclass(frozen=True,slots=True)
class LeanBodyPlan:
    source:SourceSnapshot
    code:CapturedCode
    call_offsets:tuple[int,...]
    unsupported_offsets:tuple[int,...]
    def __post_init__(self):
        _need(type(self.source) is SourceSnapshot and type(self.code) is CapturedCode,'lean plan needs original typed source/code')
        self.code.__post_init__()
        _need(self.source.path==self.code.filename and Path(self.source.path).is_absolute(),'lean code/source namespace differs')
        for offsets in (self.call_offsets,self.unsupported_offsets):
            _need(type(offsets) is tuple and tuple(sorted(set(offsets)))==offsets
                  and all(type(i) is int and i>=0 for i in offsets),'lean offsets must be sorted exact integers')
        _need(set(self.unsupported_offsets)<=set(self.call_offsets),'unsupported sites must remain in the plan denominator')

@dataclass(frozen=True,slots=True)
class LeanCapturePlan:
    namespace_root:str
    bodies:tuple[LeanBodyPlan,...]
    max_codes:int=4096
    _by_source:dict=field(default_factory=dict,init=False,repr=False,compare=False)
    _memo:dict=field(default_factory=dict,init=False,repr=False,compare=False)
    def __post_init__(self):
        _need(type(self.namespace_root) is str and Path(self.namespace_root).is_absolute()
              and os.path.normpath(self.namespace_root)==self.namespace_root,'lean namespace root must be exact')
        _need(type(self.max_codes) is int and self.max_codes>0,'lean plan needs an independent positive code budget')
        _need(type(self.bodies) is tuple and 0<len(self.bodies)<=self.max_codes,'lean plan code budget exceeded')
        _need(all(type(b) is LeanBodyPlan for b in self.bodies),'lean bodies must be typed')
        _need(len({b.code.key for b in self.bodies})==len(self.bodies),'lean plan repeats a code identity')
        for b in self.bodies:
            b.__post_init__()
            key=(b.code.filename,b.code.qualname,b.code.first_line)
            self._by_source.setdefault(key,[]).append(b)
        # One current source version per path for this filesystem-based API.
        # Archive-based multi-version plans need their actual retained locators.
        for path in {b.source.path for b in self.bodies}:
            _need(len({b.source.fingerprint for b in self.bodies if b.source.path==path})==1,
                  'conflicting source versions require an archive-qualified plan')
    @classmethod
    def from_codes(cls,namespace_root,codes,*,max_codes=4096):
        """Convenience selector from immutable codes; no compilation/source proof."""
        sources={};bodies=[]
        for code in codes:
            _need(type(code) is CodeType,'lean selector needs exact code objects')
            path=Path(code.co_filename)
            if str(path) not in sources:
                _need(path.is_file() and not path.is_symlink() and path.stat().st_size<=1_000_000,'bounded original UTF8 source required')
                text=path.read_text(encoding='utf-8')
                sources[str(path)]=SourceSnapshot(str(path),'sha256:'+hashlib.sha256(text.encode()).hexdigest(),'utf-8',f'{sys.version_info.major}.{sys.version_info.minor}')
            instructions=tuple(dis.get_instructions(code))
            calls=tuple(i.offset for i in instructions if i.opname.startswith('CALL'))
            unsupported=tuple(i.offset for i in instructions if i.opname.startswith('CALL') and i.opname!='CALL')
            bodies.append(LeanBodyPlan(sources[str(path)],decode(CapturedCode,describe_code(code)),calls,unsupported))
        return cls(str(Path(namespace_root).resolve()),tuple(bodies),max_codes)
    @classmethod
    def from_source_entry_plan(cls,plan,*,namespace_root,max_codes=4096):
        """Derive selectors from one live normal entry plan, not its JSON.

        Readonly CodeWitness supplies archived code identity. Neither source
        preparation/lowering nor target execution/current-source guessing is
        used. The result is still only a capture selection policy.
        """
        from scar.analysis.source_frontend_worklist import SourceEntryFrontendPlan
        from scar.analysis.source_language import SourceCodeEvidence
        _need(type(plan) is SourceEntryFrontendPlan,'a live normal source-entry plan is required')
        _need(type(max_codes) is int and max_codes>0,'lean plan needs an independent positive code budget')
        plan.require_unchanged()
        bodies={}
        for row in plan.dispatch:
            entry=plan.catalog.resolve(row['entry_key'])
            evidence=SourceCodeEvidence.from_entry(plan.catalog,entry)
            evidence.require_definition(entry.reference.snapshot,entry.reference.definition,entry.reference.source)
            code=evidence.code
            _need(describe_code(code)==encode(entry.captured),'readonly entry code descriptor changed')
            instructions=tuple(dis.get_instructions(code))
            body=LeanBodyPlan(entry.reference.snapshot,entry.captured,
                tuple(i.offset for i in instructions if i.opname.startswith('CALL')),
                tuple(i.offset for i in instructions if i.opname.startswith('CALL') and i.opname!='CALL'))
            previous=bodies.setdefault(body.code.key,body)
            _need(previous==body,'one selector key has conflicting source/code variants')
            _need(len(bodies)<=max_codes,'lean plan code budget exceeded')
        plan.require_unchanged()
        return cls(str(Path(namespace_root).resolve()),tuple(bodies.values()),max_codes)

    def candidate(self,code):
        bodies=self._by_source.get((code.co_filename,code.co_qualname,code.co_firstlineno),())
        return bodies[0] if bodies else None
    def match(self,code):
        identity=id(code);cached=self._memo.get(identity)
        if cached is not None and cached[0]() is code:return cached[1]
        bodies=self._by_source.get((code.co_filename,code.co_qualname,code.co_firstlineno),())
        if not bodies:return None
        key=describe_code(code)['key']
        body=next((b for b in bodies if b.code.key==key),None)
        if len(self._memo)<self.max_codes:
            def forgotten(reference,identity=identity):
                current=self._memo.get(identity)
                if current is not None and current[0] is reference:self._memo.pop(identity,None)
            self._memo[identity]=(weakref.ref(code,forgotten),body)
        return body
    def clear_runtime_cache(self):
        self._memo.clear()
    def verify_sources(self):
        for source in {b.source.path:b.source for b in self.bodies}.values():
            p=Path(source.path)
            _need(p.is_file() and not p.is_symlink() and p.stat().st_size<=1_000_000,'lean source changed or unavailable')
            _need('sha256:'+hashlib.sha256(p.read_text(encoding='utf-8').encode()).hexdigest()==source.fingerprint,'lean source version changed')
    def to_dict(self):
        return {'schema':'scar.lean-capture-plan','schema_version':1,'profile':PROFILE,
                'namespace_root':self.namespace_root,'bodies':encode(self.bodies),
                'source_compiler_runtime_contents_proved':False}
    @classmethod
    def from_dict(cls,doc,*,max_codes=4096):
        _need(type(doc) is dict and set(doc)=={'schema','schema_version','profile','namespace_root','bodies','source_compiler_runtime_contents_proved'}
              and doc['schema']=='scar.lean-capture-plan' and type(doc['schema_version']) is int and doc['schema_version']==1
              and doc['profile']==PROFILE and doc['source_compiler_runtime_contents_proved'] is False,'unsupported lean plan schema')
        return cls(doc['namespace_root'],decode(tuple[LeanBodyPlan,...],doc['bodies']),max_codes)
    def publish(self,directory,pid):
        self.verify_sources();raw=_raw(self.to_dict());path=Path(directory)/f'lean-plan.{pid}.json'
        with path.open('xb') as stream:stream.write(raw)
        return ProviderArtifact(str(path),hashlib.sha256(raw).hexdigest(),len(raw),'scar.lean-capture-plan/1')


def read_plan(path,*,expected_sha256,max_bytes=16_000_000,max_codes=4096):
    """Bounded immutable selector read; never restores a catalog/live owner."""
    import re
    _need(type(max_bytes) is int and max_bytes>0,'positive independent plan byte budget required')
    _need(type(expected_sha256) is str and re.fullmatch('[0-9a-f]{64}',expected_sha256),'exact plan SHA256 required')
    p=Path(path)
    _need(p.is_file() and not p.is_symlink(),'plan must be an existing regular file')
    stat=p.stat();before=(stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
    _need(0<stat.st_size<=max_bytes,'plan byte budget exceeded')
    with p.open('rb') as stream:raw=stream.read(max_bytes+1)
    _need(len(raw)<=max_bytes,'plan byte budget exceeded during read')
    stat=p.stat()
    _need(not p.is_symlink() and before==(stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
          and hashlib.sha256(raw).hexdigest()==expected_sha256,'plan input/SHA changed')
    def pairs(items):
        result={}
        for key,value in items:
            _need(key not in result,'duplicate lean plan JSON field');result[key]=value
        return result
    def invalid(value):raise ValueError('nonfinite lean plan number: '+value)
    document=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=invalid)
    plan=LeanCapturePlan.from_dict(document,max_codes=max_codes)
    # Current-source checks are only version guards against the original
    # snapshot. Code identity still comes from the original typed descriptor.
    plan.verify_sources()
    return plan
