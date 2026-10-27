"""Metadata equivalence only: no hook installation, target or capture."""
import dataclasses
import dis
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

from scar.trace import code_snapshot as current
from scar.trace.call_operands import _layout
from scar.trace.python_call_targets import PythonTargetObserver, PythonTargetBudget
from scar.ir.program.call_operands import FunctionLayout
from scar.ir.record_codec import encode

HERE = Path(__file__).resolve().parent
BASE = 'b5c1c3cc'

def candidate(self):
    return None

def replacement(self, extra):
    return extra

def caller():
    return some_receiver.method()

class Receiver:
    pass

def legacy_layout(code):
    count=code.co_argcount+code.co_kwonlyargcount+bool(code.co_flags&4)+bool(code.co_flags&8)
    return FunctionLayout(code.co_argcount,code.co_posonlyargcount,code.co_kwonlyargcount,
                          code.co_flags,code.co_varnames[:count])

with tempfile.TemporaryDirectory(prefix='call-metadata-') as directory:
    temp=Path(directory)
    loaded=[]
    for name,source in [('_before_snapshot','scar/trace/code_snapshot.py'),
                        ('_before_targets','scar/trace/python_call_targets.py')]:
        path=temp/(name+'.py')
        path.write_bytes(subprocess.check_output(['git','show',BASE+':'+source]))
        spec=importlib.util.spec_from_file_location(name,path)
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
        loaded.append(module)
    before,old_target=loaded
    code=candidate.__code__; new_code=replacement.__code__
    expected=before.describe_code(code)
    assert current.describe_code(code)==expected
    assert current.code_parameters(code)==tuple(expected['parameters'])
    assert encode(_layout(code))==encode(legacy_layout(code))
    mutable=current.describe_code(code);mutable['parameters'].append('corrupted')
    assert current.describe_code(code)==expected
    try:
        _layout(code).argcount=900
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError('cached layout must remain frozen')
    offsets=[i.offset for i in dis.get_instructions(caller.__code__) if i.opname=='CALL']
    offset=offsets[0]
    site=before.site(caller.__code__,offset)
    assert current.site(caller.__code__,offset)==site
    changed=current.site(caller.__code__,offset);changed['position'][0]=-900
    assert current.site(caller.__code__,offset)==site
    # A structural metadata-only CodeType with EXTENDED_ARG+CALL257. It is
    # never executed or used as a modeled source/captured runtime fact.
    cache_units=dis._inline_cache_entries.get('CALL',0)
    raw=bytes([dis.opmap['RESUME'],0,dis.opmap['EXTENDED_ARG'],1,dis.opmap['CALL'],1]
              +[0,0]*cache_units+[dis.opmap['RETURN_VALUE'],0])
    extended=caller.__code__.replace(co_code=raw)
    instruction=next(i for i in dis.get_instructions(extended) if i.opname=='CALL')
    assert instruction.arg==257
    assert current.call_instruction(extended,instruction.offset)==('CALL',257)
    scans=0;original=dis.get_instructions
    def counted(*args,**kwargs):
        global scans
        scans+=1
        return original(*args,**kwargs)
    dis.get_instructions=counted
    try:
        for _ in range(8):current.call_instruction(caller.__code__,offset)
    finally:
        dis.get_instructions=original
    assert scans==1
    alternate=code.replace(co_filename=code.co_filename+'.replacement')
    assert current.code_key(alternate)!=current.code_key(code)
    limit=current._MAX_BYTES;current._MAX_BYTES=1
    try:
        for check in [lambda:current.code_parameters(code),lambda:_layout(code),
                      lambda:current.call_instruction(caller.__code__,offset)]:
            try:check()
            except ValueError:pass
            else:raise AssertionError('strict changed limits must reject warm cache')
    finally:
        current._MAX_BYTES=limit
    receiver=Receiver()
    def records(cls,directory,layout,budget_class):
        candidate.__code__=code;candidate.__defaults__=None
        directory.mkdir()
        operand=SimpleNamespace(recorder=SimpleNamespace(out=directory,pid=os.getpid(),root=str(HERE)),
                                _code_inside=lambda code:False)
        observer=cls(operand,budget_class(max_records=30,max_bytes=100000,max_selected_codes=4))
        tokens={}
        def reference(value):
            return tokens.setdefault(id(value),f'weak:{os.getpid()}:{len(tokens)+1}')
        for attempt in (1,2,3):
            if attempt==2:candidate.__defaults__=(None,)
            if attempt==3:candidate.__defaults__=None;candidate.__code__=new_code
            observer.on_call(candidate,receiver,False,caller.__code__,1,site,attempt,reference,layout)
        observer.close()
        return observer.path.read_bytes()
    old_raw=records(old_target.PythonTargetObserver,temp/'old',legacy_layout,old_target.PythonTargetBudget)
    new_raw=records(PythonTargetObserver,temp/'new',_layout,PythonTargetBudget)
    assert old_raw==new_raw
    candidate.__code__=code;candidate.__defaults__=None
    rows=[json.loads(x) for x in new_raw.splitlines()]
    kinds=[x['value']['kind'] for x in rows if x['kind']=='TARGET']

result=dict(status='STATIC_CACHE_AND_DYNAMIC_TARGET_METADATA_EQUIVALENT',base_commit=BASE,
    target_rows=len(rows),serialized_bytes=len(new_raw),serialized_sha256=hashlib.sha256(new_raw).hexdigest(),
    byte_identical_to_before=True,observed_target_kinds=kinds,
    repeated_call_site_requests=8,actual_disassembly_scans=scans,extended_call_arg=257,
    mutable_return_isolation=True,changed_code_and_stricter_limits_not_reused=True,
    dynamic_defaults_and_code_observed_each_event=True,
    hook_installed=False,capture_started=False,target_executed=False,runtime_speedup_measured=False)
with (HERE/'RESULT.json').open('x') as stream:json.dump(result,stream,indent=2)
print(json.dumps(result))
