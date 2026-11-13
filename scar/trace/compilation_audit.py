"""Optional bounded compile/text and code-execution audit observations.

No builtins are replaced. Audit ``compile`` is only an attempt, and audit
``exec`` is emitted by eval too. These streams deliberately do not pair them
or claim original mode, flags, dont_inherit, optimize or namespace contents.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
from types import CodeType
import weakref

from scar.trace.code_snapshot import describe_code, site
from scar.trace.deferred_jsonl import DeferredJsonl, snapshot_transport_enabled


class _Stream:
    def __init__(self, path, limit):
        self.path, self.limit = Path(path), limit
        self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:self.writer = DeferredJsonl(self.path, max_bytes=limit) if snapshot_transport_enabled() else None
        except BaseException:
            os.close(self.fd)
            raise
        self.buffer = bytearray(); self.digest = hashlib.sha256()
        self.rows = self.bytes = 0
        self.io_failed = False

    def append(self, row):
        if self.writer is not None:
            if not self.writer.append(row): return False
            self.bytes = self.writer.accepted_bytes
        else:
            raw = (json.dumps(row, ensure_ascii=True, separators=(',', ':'), allow_nan=False)+'\n').encode('ascii')
            if len(raw)>2_000_000 or self.bytes+len(raw)>self.limit:return False
            if len(self.buffer)+len(raw)>65536:self.flush()
            self.buffer.extend(raw); self.digest.update(raw); self.bytes+=len(raw)
        self.rows+=1
        return True

    def flush(self):
        offset=0
        try:
            while offset<len(self.buffer):
                written=os.write(self.fd,memoryview(self.buffer)[offset:])
                if written<=0:raise OSError('compilation audit stream made no write progress')
                offset+=written
            self.buffer.clear()
        except OSError:
            self.io_failed=True
            raise

    def close(self):
        try:
            if self.writer is not None:
                output=self.writer.finalize()['output']
                return dict(path=str(self.path),bytes=output['raw_bytes'],sha256=output['sha256'],rows=output['lines'])
            self.flush()
            return dict(path=str(self.path),bytes=self.bytes,sha256=self.digest.hexdigest(),rows=self.rows)
        finally:
            if self.writer is not None:self.writer.close_capture()
            os.close(self.fd)


class CompilationAudit:
    def __init__(self, recorder, *, max_events=4096, max_sources=1024,
                 max_source_bytes=512_000, max_total_source_bytes=8_000_000,
                 max_stream_bytes=16_000_000):
        limits=dict(max_events=max_events,max_sources=max_sources,max_source_bytes=max_source_bytes,
            max_total_source_bytes=max_total_source_bytes,max_stream_bytes=max_stream_bytes)
        if any(type(v) is not int or v<1 for v in limits.values()):
            raise ValueError('compilation audit limits must be positive integers')
        if max_source_bytes>1_000_000:raise ValueError('compilation audit source record ceiling is 1000000 bytes')
        self.recorder=recorder;self.pid=os.getpid();self.root=recorder.root
        self.prefix=self.root.rstrip(os.sep)+os.sep;self.limits=limits
        self.sources=_Stream(recorder.out/f'compilation-sources.{self.pid}.jsonl',max_stream_bytes)
        try:self.events=_Stream(recorder.out/f'compilation-events.{self.pid}.jsonl',max_stream_bytes)
        except Exception:
            self.sources.close()
            raise
        self.seen=set();self.source_bytes=0;self.counts={'COMPILE':0,'CODE_EXECUTION':0,'GAP':0}
        self.ignored=0;self.errors=[];self.stopped=self.closed=self.io_failed=False
        self.hook_installed=False;self._install_marker=object()
        self.busy=set();self.lock=threading.RLock()
        self.meta=recorder.out/f'compilation-meta.{self.pid}.json'
        recorder.observer_files.add(__file__)
        owner=weakref.ref(self)
        def audited(event,args,owner_ref=owner):
            observer=owner_ref()
            if observer is not None:observer.on_audit(event,args)
        self.hook=audited

    def _context(self, filename, caller):
        # No frame/application object survives this callback. The first caller
        # position is diagnostic, not a fabricated CALL/compile-request link.
        inside=type(filename) is str and (filename==self.root or filename.startswith(self.prefix))
        dynamic=filename is None or type(filename) is str and not os.path.isabs(filename)
        current=caller
        for _ in range(64):
            if current is None:break
            path=current.f_code.co_filename
            if path==self.root or path.startswith(self.prefix):inside=True;break
            current=current.f_back
        if not (inside or dynamic):return False,None
        try:position=None if caller is None else site(caller.f_code,caller.f_lasti)
        except (ValueError,TypeError,RecursionError):position=None
        return True,position

    def _event(self, kind, fields, caller, tid):
        if self.events.rows>=self.limits['max_events']:
            self.stopped=True;return
        row=dict(schema='scar.compilation-audit-events',schema_version=1,index=self.events.rows+1,
            process_id=self.pid,thread_id=tid,kind=kind,caller_site=caller,**fields)
        if not self.events.append(row):self.stopped=True;return
        self.counts[kind]+=1

    def _gap(self, reason, filename, caller, tid):
        self._event('GAP',dict(reason=reason,filename=filename),caller,tid)

    def on_audit(self, event, args):
        if event=='scar.compilation_audit.install' and args and args[0] is self._install_marker:
            self.hook_installed=True;return
        if event not in ('compile','exec') or self.closed or self.stopped or os.getpid()!=self.pid:return
        tid=threading.get_ident()
        if tid in self.busy:return
        self.busy.add(tid)
        try:
            with self.lock:
                if self.closed or self.stopped:return
                value=args[0] if type(args) is tuple and args else None
                filename=(args[1] if event=='compile' and len(args)>1 else
                    value.co_filename if type(value) is CodeType else None)
                filename=filename if type(filename) is str else None
                caller=sys._getframe(1).f_back  # C entry may have no Python caller.
                selected,position=self._context(filename,caller)
                if not selected:self.ignored+=1;return
                if event=='exec':
                    if type(value) is not CodeType:
                        self._gap('CODE_EXECUTION_ARGUMENT_NOT_CODE',filename,position,tid);return
                    try:description=describe_code(value)
                    except (TypeError,ValueError,RecursionError) as error:
                        self._gap('CODE_DESCRIPTION_'+type(error).__name__,filename,position,tid);return
                    self._event('CODE_EXECUTION',dict(code=description),position,tid)
                    return
                if type(value) not in (str,bytes):
                    self._gap('UNSUPPORTED_COMPILE_SOURCE_TYPE',filename,position,tid);return
                if len(value)>self.limits['max_source_bytes']:
                    self._gap('SOURCE_RECORD_BYTE_BUDGET',filename,position,tid);return
                kind='TEXT' if type(value) is str else 'BYTES'
                raw=value.encode('utf-8','surrogatepass') if kind=='TEXT' else value
                if len(raw)>self.limits['max_source_bytes']:
                    self._gap('SOURCE_RECORD_BYTE_BUDGET',filename,position,tid);return
                digest=hashlib.sha256(raw).hexdigest();key=kind,digest
                if key not in self.seen:
                    if len(self.seen)>=self.limits['max_sources']:
                        self._gap('SOURCE_COUNT_BUDGET',filename,position,tid);return
                    if self.source_bytes+len(raw)>self.limits['max_total_source_bytes']:
                        self._gap('TOTAL_SOURCE_BYTE_BUDGET',filename,position,tid);return
                    row=dict(schema='scar.compilation-audit-sources',schema_version=1,index=self.sources.rows+1,
                        process_id=self.pid,sha256=digest,source_kind=kind,
                        encoding='utf-8-surrogatepass' if kind=='TEXT' else None,size_bytes=len(raw),
                        payload_base64=base64.b64encode(raw).decode('ascii'))
                    if not self.sources.append(row):self.stopped=True;return
                    self.seen.add(key);self.source_bytes+=len(raw)
                self._event('COMPILE',dict(filename=filename,source_sha256=digest,source_kind=kind),position,tid)
        except Exception as error:
            self.stopped=True
            self.io_failed=self.sources.io_failed or self.events.io_failed or isinstance(error,OSError)
            if len(self.errors)<8:self.errors.append(type(error).__name__)
        finally:self.busy.discard(tid)

    def close(self):
        if self.closed or os.getpid()!=self.pid:return
        with self.lock:
            if self.closed:return
            self.closed=True  # The permanent audit hook becomes a no-op.
            files={}
            for name,stream in (('sources',self.sources),('events',self.events)):
                try:files[name]=stream.close()
                except Exception as error:
                    self.io_failed=self.stopped=True
                    if len(self.errors)<8:self.errors.append(type(error).__name__)
            report=dict(schema='scar.compilation-audit-collection',schema_version=1,
                process_id=self.pid,project_root=self.root,python=sys.version,
                profile='BOUNDED_PASSIVE_COMPILE_CODE_AUDIT_V1',limits=self.limits,
                scope='NONFILESYSTEM_OR_PROJECT_SOURCE_OR_PROJECT_CALLER_ANCESTRY',
                counts=dict(self.counts,sources=self.sources.rows,events=self.events.rows,
                    unique_source_bytes=self.source_bytes,ignored_outside_scope=self.ignored),
                files=files,stopped=self.stopped,errors=self.errors,io_failed=self.io_failed,
                hook_installed=self.hook_installed,
                compile_events_are_attempts=True,code_execution_event_operation='EXEC_OR_EVAL_NOT_DISTINGUISHED',
                source_kind_semantics='AUDIT_ARGUMENT_TYPE_NOT_ORIGINAL_CALL_ARGUMENT_TYPE',
                original_compile_options_observed=False,
                unobserved_compile_fields=['mode','flags','dont_inherit','optimize'],
                execution_namespace_observed=False,source_code_pairing_performed=False,
                program_graph_constructed=False)
            with self.meta.open('x',encoding='utf-8') as stream:
                json.dump(report,stream,ensure_ascii=True,indent=2,allow_nan=False);stream.write('\n')


def install(recorder):
    """Install only in the traced process; no import compiles or executes code."""
    observer=None
    try:
        options={name:int(os.environ.get('SCAR_COMPILE_'+suffix,default)) for name,suffix,default in (
            ('max_events','MAX_EVENTS','4096'),('max_sources','MAX_SOURCES','1024'),
            ('max_source_bytes','MAX_SOURCE_BYTES','512000'),('max_total_source_bytes','MAX_TOTAL_SOURCE_BYTES','8000000'),
            ('max_stream_bytes','MAX_STREAM_BYTES','16000000'))}
        observer=CompilationAudit(recorder,**options)
        sys.addaudithook(observer.hook)
        sys.audit('scar.compilation_audit.install',observer._install_marker)
        if not observer.hook_installed:raise RuntimeError('compilation audit hook was not installed')
    except Exception as error:
        if observer is not None:
            observer.errors.append('AUDIT_HOOK_INSTALL_FAILED');observer.stopped=True
            try:observer.close()
            except Exception:pass
        try:
            marker=recorder.out/f'compilation-disabled.{os.getpid()}.json'
            with marker.open('x',encoding='utf-8') as stream:
                json.dump(dict(schema='scar.compilation-audit-disabled',schema_version=1,
                    process_id=os.getpid(),python=sys.version,disabled=True,
                    reason=type(error).__name__),stream,ensure_ascii=True);stream.write('\n')
        except Exception:
            # Even when the output filesystem is unusable the target must start.
            try:sys.__stderr__.write('SCAR compilation audit disabled: '+type(error).__name__+'\n')
            except Exception:pass
        raise
    return observer
