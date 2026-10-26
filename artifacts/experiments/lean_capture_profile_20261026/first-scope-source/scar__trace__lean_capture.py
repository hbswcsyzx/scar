"""Explicit static capture selection, never a source/runtime proof authority."""
from __future__ import annotations
from dataclasses import dataclass
import dis,hashlib,json,os,sys
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
    def __post_init__(self):
        _need(type(self.namespace_root) is str and Path(self.namespace_root).is_absolute()
              and os.path.normpath(self.namespace_root)==self.namespace_root,'lean namespace root must be exact')
        _need(type(self.bodies) is tuple and 0<len(self.bodies)<=128,'lean plan body budget is 1..128')
        _need(all(type(b) is LeanBodyPlan for b in self.bodies),'lean bodies must be typed')
        _need(len({b.code.key for b in self.bodies})==len(self.bodies),'lean plan repeats a code identity')
        for b in self.bodies:b.__post_init__()
    @classmethod
    def from_codes(cls,namespace_root,codes):
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
        return cls(str(Path(namespace_root).resolve()),tuple(bodies))
    def candidate(self,code):
        return next((b for b in self.bodies if (b.code.filename,b.code.qualname,b.code.first_line)==
                     (code.co_filename,code.co_qualname,code.co_firstlineno)),None)
    def match(self,code):
        body=self.candidate(code)
        return body if body is not None and body.code.key==describe_code(code)['key'] else None
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
    def from_dict(cls,doc):
        _need(type(doc) is dict and set(doc)=={'schema','schema_version','profile','namespace_root','bodies','source_compiler_runtime_contents_proved'}
              and doc['schema']=='scar.lean-capture-plan' and type(doc['schema_version']) is int and doc['schema_version']==1
              and doc['profile']==PROFILE and doc['source_compiler_runtime_contents_proved'] is False,'unsupported lean plan schema')
        return cls(doc['namespace_root'],decode(tuple[LeanBodyPlan,...],doc['bodies']))
    def publish(self,directory,pid):
        self.verify_sources();raw=_raw(self.to_dict());path=Path(directory)/f'lean-plan.{pid}.json'
        with path.open('xb') as stream:stream.write(raw)
        return ProviderArtifact(str(path),hashlib.sha256(raw).hexdigest(),len(raw),'scar.lean-capture-plan/1')
