"""Opt-in v2 targets for observed Python calls; no user getter/target execution."""
from __future__ import annotations
from dataclasses import dataclass
import dis,hashlib,inspect,json,os,sys,threading,types,weakref
from scar.ir.program.python_call_targets import (
    PythonTargetKind as Kind,PythonCodeScope as Scope,ReceiverRole,ReceiverCondition,BoundReceiver,
    PythonCallTarget,PythonEntryBinding,PythonTargetGap,target_record,
)
from scar.ir.program.call_edges import InvocationKey
from scar.ir.record_codec import encode
from scar.trace.code_snapshot import describe_code,site

@dataclass(frozen=True,slots=True)
class PythonTargetBudget:
    max_records:int=100_000
    max_bytes:int=32_000_000
    max_selected_codes:int=4096
    def __post_init__(self):
        if not all(type(x) is int and x>0 for x in (self.max_records,self.max_bytes,self.max_selected_codes)):
            raise ValueError('positive independent Python target budgets required')

class PythonTargetObserver:
    def __init__(self,operand,budget=PythonTargetBudget()):
        if type(budget) is not PythonTargetBudget:raise TypeError('typed PythonTargetBudget required')
        if sys.implementation.name!='cpython' or sys.version_info[:3]!=(3,14,7):raise RuntimeError('PYTHON_CALL_TARGETS_V2 requires the fixed CPython 3.14.7 CALL contract')
        budget.__post_init__();self.operand=operand;self.recorder=operand.recorder;self.budget=budget
        self.path=self.recorder.out/f'python-call-targets.{self.recorder.pid}.jsonl'
        self.meta=self.recorder.out/f'python-call-target-meta.{self.recorder.pid}.json'
        self.fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        self.pending={};self.codes={};self.records=self.bytes=0;self.closed=self.stopped=False
        self.counts={'TARGET':0,'ENTRY':0,'GAP':0};self.digest=hashlib.sha256()
        self.legacy_inputs=None
    def emit(self,kind,value):
        if self.closed or self.stopped:return
        raw=(json.dumps(target_record(kind,value),ensure_ascii=True,separators=(',',':'),allow_nan=False)+'\n').encode('ascii')
        if self.records>=self.budget.max_records or self.bytes+len(raw)>self.budget.max_bytes:
            self.stopped=True;return
        offset=0
        while offset<len(raw):
            n=os.write(self.fd,raw[offset:])
            if n<=0:raise OSError('Python target sidecar made no write progress')
            offset+=n
        self.digest.update(raw);self.bytes+=len(raw);self.records+=1;self.counts[kind]+=1
    def gap(self,attempt,reason):self.emit('GAP',PythonTargetGap(attempt,reason))
    def observed_code(self,code):
        ref=self.codes.get(id(code));return ref is not None and ref() is code
    def select_code(self,code,attempt):
        if self.observed_code(code):return True
        self.codes={k:v for k,v in self.codes.items() if v() is not None}
        if len(self.codes)>=self.budget.max_selected_codes:
            self.gap(attempt,'OBSERVED_PYTHON_CODE_SCOPE_BUDGET');return False
        self.codes[id(code)]=weakref.ref(code);return True
    def on_call(self,callable_object,arg0,arg0_missing,caller_code,owner,call_site,attempt,reference,layout):
        key=threading.get_ident(),owner
        old=self.pending.pop(key,None)
        if old is not None:self.gap(old['attempt'],'PYTHON_TARGET_DID_NOT_ENTER_BEFORE_NEXT_CALL')
        func=receiver=None;kind=Kind.OTHER_UNCLASSIFIED
        if type(callable_object) is types.FunctionType:func=callable_object;kind=Kind.FUNCTION
        elif type(callable_object) is types.MethodType:
            candidate=callable_object.__func__
            if type(candidate) is types.FunctionType:func=candidate;receiver=callable_object.__self__;kind=Kind.BOUND_METHOD
        elif type(callable_object) is types.BuiltinFunctionType:kind=Kind.NATIVE_BUILTIN
        elif type(callable_object) is types.MethodWrapperType:kind=Kind.NATIVE_WRAPPER
        call_ref=reference(callable_object)
        if func is None:
            self.emit('TARGET',PythonCallTarget(attempt,InvocationKey(self.recorder.pid,key[0],owner),kind,call_ref,None,None,None,None,Scope.NO_PYTHON_CODE));return
        code=func.__code__;code_key=describe_code(code)['key'];function_ref=reference(func)
        if kind is Kind.FUNCTION and not arg0_missing:
            instruction=next((i for i in dis.get_instructions(caller_code) if i.offset==call_site['offset']),None)
            unsupported=inspect.CO_VARARGS|inspect.CO_VARKEYWORDS|inspect.CO_GENERATOR|inspect.CO_COROUTINE|inspect.CO_ASYNC_GENERATOR
            # CPython3.14 expands PyMethod before _MONITOR_CALL. CALL n
            # excludes the implicit first parameter. Under this exact finite
            # no-default/nonvariadic ABI a successful matching entry needs n+1.
            if (instruction is not None and instruction.opname=='CALL'
                    and type(instruction.arg) is int and code.co_argcount==instruction.arg+1
                    and code.co_kwonlyargcount==0 and not code.co_flags & unsupported
                    and func.__defaults__ is None):
                kind=Kind.NORMALIZED_RECEIVER_FUNCTION;receiver=arg0
        receiver_ref=None if receiver is None else reference(receiver)
        scope=Scope.PROJECT if self.operand._code_inside(code) else Scope.OBSERVED_EXTERNAL_PYTHON if os.path.isabs(code.co_filename) else Scope.NONFILESYSTEM_PYTHON
        role=None if receiver is None else (BoundReceiver(ReceiverRole.IMPLICIT_CALL_RECEIVER,receiver_ref,instruction.arg,(ReceiverCondition.NO_INTERVENING_CALL_LAYOUT_MUTATION,)) if kind is Kind.NORMALIZED_RECEIVER_FUNCTION else BoundReceiver(ReceiverRole.BOUND_METHOD_RECEIVER,receiver_ref))
        target=PythonCallTarget(attempt,InvocationKey(self.recorder.pid,key[0],owner),kind,call_ref,function_ref,code_key,layout(code),role,scope)
        self.emit('TARGET',target)
        if not self.select_code(code,attempt):return
        try:receiver_weak=None if receiver is None else weakref.ref(receiver)
        except TypeError:receiver_weak=None
        try:method_weak=weakref.ref(callable_object) if kind is Kind.BOUND_METHOD else None
        except TypeError:method_weak=None
        self.pending[key]={'attempt':attempt,'caller':target.caller,'function':weakref.ref(func),'code':weakref.ref(code),'code_key':code_key,'site':call_site,'receiver':receiver_weak,'method':method_weak,'receiver_ref':receiver_ref,'kind':kind,'defaults_none':func.__defaults__ is None}
    def pending_for(self,frame):
        parent=frame.f_back
        state=self.operand._base_state(parent) if parent is not None else None
        if state is None:return None
        pending=self.pending.get((threading.get_ident(),state[0]))
        if pending is None:return None
        func,code=pending['function'](),pending['code']()
        if func is None or code is None or frame.f_code is not code or func.__code__ is not code:return None
        try:matched=site(parent.f_code,parent.f_lasti)==pending['site']
        except (TypeError,ValueError):matched=False
        return pending if matched else None
    def accepts_frame(self,frame):return self.pending_for(frame) is not None
    def on_frame_enter(self,frame):
        pending=self.pending_for(frame)
        if pending is None:return False
        state=self.operand._base_state(frame)
        if state is None:
            self.gap(pending['attempt'],'PYTHON_ENTRY_NOT_RETAINED_BY_FRAME_RECORDER');return False
        key=threading.get_ident(),pending['caller'].invocation_id
        self.pending.pop(key,None)
        receiver_index=receiver_ref=None
        if pending['kind'] in (Kind.BOUND_METHOD,Kind.NORMALIZED_RECEIVER_FUNCTION):
            receiver=pending['receiver']() if pending['receiver'] is not None else None
            method=pending['method']() if pending['method'] is not None else None
            if receiver is None and type(method) is types.MethodType:receiver=method.__self__
            code=frame.f_code
            if pending['kind'] is Kind.NORMALIZED_RECEIVER_FUNCTION and pending['function']().__defaults__ is not None:
                self.gap(pending['attempt'],'CALL_RECEIVER_DEFAULT_STATE_CHANGED');return True
            if receiver is None:
                self.gap(pending['attempt'],'BOUND_RECEIVER_CONTINUITY_UNAVAILABLE');return True
            if code.co_argcount<1 or not code.co_varnames or frame.f_locals.get(code.co_varnames[0]) is not receiver:
                self.gap(pending['attempt'],'BOUND_RECEIVER_FIRST_FORMAL_MISMATCH');return True
            receiver_index=0;receiver_ref=pending['receiver_ref']
        # Project exact-function entry authority remains the original v1
        # ENTRY_HANDSHAKE. v2 adds entries only for methods/external code.
        if pending['kind'] is Kind.FUNCTION and self.operand._code_inside(frame.f_code):return True
        self.emit('ENTRY',PythonEntryBinding(pending['attempt'],pending['caller'],InvocationKey(self.recorder.pid,threading.get_ident(),state[0]),self.recorder.index,pending['code_key'],receiver_index,receiver_ref))
        return True
    def close(self):
        if self.closed:return
        for pending in tuple(self.pending.values()):self.gap(pending['attempt'],'PYTHON_TARGET_NO_IMMEDIATE_ENTRY_RETAINED')
        self.pending.clear();os.close(self.fd);self.closed=True
        document={'schema':'scar.python-call-target-collection','schema_version':2,'capabilities':['PYTHON_CALL_TARGETS_V2','OBSERVED_PYTHON_CALLEE_SCOPE_V1'],'process_id':self.recorder.pid,'project_root':self.recorder.root,'scope_policy':'OBSERVED_EXACT_PYTHON_CALLEES_V1','budget':encode(self.budget),'counts':self.counts,'stopped':self.stopped,'file':{'path':str(self.path),'bytes':self.bytes,'sha256':self.digest.hexdigest(),'rows':self.records},'legacy_inputs':encode(self.legacy_inputs),'receiver_is_separate_from_monitoring_arg0':True,'contents_state_ready_or_complete_program_established':False}
        with self.meta.open('x') as stream:json.dump(document,stream,indent=2);stream.write('\n')
