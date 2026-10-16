"""Bounded metadata-only Python call recording, without retaining application values."""
from __future__ import annotations

import atexit
from itertools import islice
import json
import os
from pathlib import Path
import sys
import threading
import time
import weakref

from scar.trace.code_snapshot import describe_code, site


class CallEdgeRecorder:
    def __init__(self, out, project_root, *, max_events=100000, max_bytes=64000000,
                 max_codes=4096, max_values=64, max_path=16, max_references=8192):
        limits = dict(max_events=max_events,max_bytes=max_bytes,max_codes=max_codes,
                      max_values=max_values,max_path=max_path,max_references=max_references)
        if any(type(v) is not int or v < 1 for v in limits.values()):
            raise ValueError("call recorder budgets must be positive exact integers")
        self.out = Path(out).resolve()
        self.out.mkdir(parents=True,exist_ok=True)
        self.root = str(Path(project_root).resolve())
        self.root_prefix = self.root.rstrip(os.sep)+os.sep
        self.observer_files = {CallEdgeRecorder.profile.__code__.co_filename,describe_code.__code__.co_filename}
        self.pid = os.getpid()
        self.limits = limits
        self.lock = threading.RLock()
        self.active, self.codes, self.references = {}, set(), {}
        self.invocation = self.index = self.epoch = self.bytes = self.written = 0
        self.entered = self.unclosed_written = 0
        self.dropped = self.codes_dropped = self.unknown_exits = self.suspended_exits = 0
        self.path_gaps = 0
        self.errors = []
        # Optional metadata-only operand observer. The historical writer and
        # its schema remain independent of the sidecar's evidence and budgets.
        self.operand_observer = None
        self.previous_profile_present = False
        self.closed = False
        self.io_failed = False
        self.started = time.perf_counter_ns()
        self.event_path = self.out/f"call-events.{self.pid}.jsonl"
        self.code_path = self.out/f"call-codes.{self.pid}.jsonl"
        # Fresh output is required: append-only IDs from two runs cannot mix.
        self.events_fd = os.open(self.event_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            self.codes_fd = os.open(self.code_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except BaseException:
            os.close(self.events_fd)
            raise

    def _inside(self, frame):
        if frame is None:
            return False
        filename = frame.f_code.co_filename
        return os.path.isabs(filename) and (filename == self.root or filename.startswith(self.root_prefix))

    def _write(self, fd, row):
        data = (json.dumps(row,ensure_ascii=True,separators=(",",":"),allow_nan=False)+"\n").encode()
        if self.bytes + len(data) > self.limits['max_bytes']:
            return False
        position = 0
        try:
            while position < len(data):
                written = os.write(fd,data[position:])
                if written <= 0:
                    raise OSError('call trace write made no progress')
                position += written
                self.bytes += written
        except OSError:
            # A partial JSON row is invalid evidence. Stop this recorder;
            # retries must not append uncharged fragments or fabricate rows.
            self.io_failed = True
            raise
        return True

    def _code(self, code):
        description = describe_code(code)
        key = description['key']
        if key not in self.codes:
            if len(self.codes) >= self.limits['max_codes'] or not self._write(self.codes_fd,description):
                self.codes_dropped += 1
                raise ValueError("call code/byte budget exceeded")
            self.codes.add(key)
        return key

    def _site(self, frame):
        self._code(frame.f_code)
        return site(frame.f_code,frame.f_lasti)

    def _reference(self, value, seen):
        address = id(value)
        previous = seen.get(address)
        if previous is not None and previous[0] is value:
            return previous[1]
        existing = self.references.get(address)
        if existing is not None and existing[0]() is value:
            token = existing[1]
        else:
            self.epoch += 1
            token = f"weak:{self.pid}:{self.epoch}"
            try:
                def forgotten(reference, address=address, token=token):
                    current = self.references.get(address)
                    if current is not None and current[0] is reference and current[1] == token:
                        self.references.pop(address,None)
                if len(self.references) >= self.limits['max_references']:
                    raise TypeError('weak reference budget exhausted')
                reference = weakref.ref(value,forgotten)
            except TypeError:
                token = f"snapshot:{self.pid}:{self.index}:{self.epoch}"
            else:
                self.references[address] = reference,token
        # Only hold the bounded snapshot during this profiler callback.
        seen[address] = value,token
        return token

    def _bindings(self, mapping, seen, names=None):
        names = list(islice(mapping,self.limits['max_values']+1)) if names is None else names
        selected = names[:self.limits['max_values']]
        result, complete = [], len(names) <= len(selected)
        for name in selected:
            if type(name) is not str or name not in mapping:
                complete = False
                continue
            result.append({'name':name,'ref':self._reference(mapping[name],seen)})
        return result,complete

    def profile(self, frame, event, arg):
        if self.closed or self.io_failed or os.getpid() != self.pid or event not in ('call','return'):
            return
        if frame.f_code.co_filename in self.observer_files:
            return
        with self.lock:
            try:
                if event == 'call':
                    caller = frame.f_back
                    if not self._inside(frame) and not self._inside(caller):
                        return
                    if self.index >= self.limits['max_events']:
                        self.dropped += 1
                        return
                    self.index += 1
                    self.invocation += 1
                    invocation = self.invocation
                    thread = threading.get_ident()
                    code = self._code(frame.f_code)
                    names = describe_code(frame.f_code)['parameters']
                    seen = {}
                    parameters, complete = self._bindings(frame.f_locals,seen,names)
                    direct = self.active.get((thread,id(caller))) if caller is not None else None
                    path, ancestor, walker, path_failed = [], None, caller, False
                    while walker is not None and len(path) < self.limits['max_path']:
                        try:
                            path.append(self._site(walker))
                        except (ValueError, TypeError):
                            self.path_gaps += 1
                            path_failed = True
                            break
                        active = self.active.get((thread,id(walker)))
                        if active is not None:
                            ancestor = active[0]
                            break
                        walker = walker.f_back
                    path_complete = not path_failed and (walker is None or ancestor is not None)
                    caller_locals, locals_complete = self._bindings(caller.f_locals,seen) if caller is not None else ([],True)
                    suspended = bool(frame.f_code.co_flags & (0x20|0x80|0x200))
                    row = dict(index=self.index,kind='call_enter',process_id=self.pid,thread_id=thread,
                        invocation_id=invocation,code=code,parameters=parameters,parameters_complete=complete,
                        caller=path[0] if path else None,caller_invocation_id=direct[0] if direct else None,
                        ancestor_invocation_id=ancestor,path=path,path_complete=path_complete,
                        caller_locals=caller_locals,caller_locals_complete=locals_complete,suspended=suspended)
                    if self._write(self.events_fd,row):
                        self.written += 1
                        self.entered += 1
                        self.unclosed_written += 1
                        self.active[thread,id(frame)] = invocation,code,suspended
                    else:
                        self.dropped += 1
                else:
                    thread = threading.get_ident()
                    active = self.active.pop((thread,id(frame)),None)
                    if active is None:
                        return
                    if self.index >= self.limits['max_events']:
                        self.dropped += 1
                        return
                    self.index += 1
                    invocation, code, suspended = active
                    position = self._site(frame)
                    completion = ('SUSPENDED' if suspended else 'NORMAL'
                                  if position['opname'] in ('RETURN_VALUE','RETURN_CONST') else 'UNKNOWN')
                    seen = {}
                    returned = self._reference(arg,seen)
                    values,complete = self._bindings(frame.f_locals,seen)
                    row = dict(index=self.index,kind='call_exit',process_id=self.pid,thread_id=thread,
                        invocation_id=invocation,code=code,return_site=position,completion=completion,
                        return_ref=returned,locals=values,locals_complete=complete)
                    if self._write(self.events_fd,row):
                        self.written += 1
                        self.unclosed_written -= 1
                        self.unknown_exits += completion == 'UNKNOWN'
                        self.suspended_exits += completion == 'SUSPENDED'
                    else:
                        self.dropped += 1
            except Exception as error:
                self.dropped += 1
                if len(self.errors) < 16:
                    self.errors.append(type(error).__name__)

    def close(self):
        with self.lock:
            if self.closed or os.getpid() != self.pid:
                return
            self.closed = True
            os.close(self.events_fd)
            os.close(self.codes_fd)
            metadata = dict(schema='scar.call-edge-trace',schema_version=1,process_id=self.pid,
                project_root=self.root,python=sys.version,limits=self.limits,events=self.written,event_attempts=self.index,
                invocations=self.entered,invocation_attempts=self.invocation,codes=len(self.codes),bytes=self.bytes,
                dropped_events=self.dropped,dropped_codes=self.codes_dropped,
                unknown_exits=self.unknown_exits,suspended_exits=self.suspended_exits,
                open_invocations=self.unclosed_written,active_frames=len(self.active),errors=self.errors,
                path_gaps=self.path_gaps,
                io_failed=self.io_failed,
                wall_ns=time.perf_counter_ns()-self.started,
                scope='initial process and newly profiled threads; native calls/child processes/existing threads not complete',
                reference_contents_observed=False,callable_environment_established=False)
            (self.out/f"call-meta.{self.pid}.json").write_text(json.dumps(metadata,indent=2)+'\n')


def install(out, project_root):
    owner = os.environ.get('SCAR_CALL_TRACE_OWNER_PID')
    if owner is not None and owner != str(os.getpid()):
        return None
    recorder = CallEdgeRecorder(out,project_root,
        max_events=int(os.environ.get('SCAR_CALL_MAX_EVENTS',100000)),
        max_bytes=int(os.environ.get('SCAR_CALL_MAX_BYTES',64000000)))
    os.environ['SCAR_CALL_TRACE_OWNER_PID'] = str(os.getpid())
    main_thread = threading.get_ident()
    previous, previous_thread = sys.getprofile(),threading.getprofile()
    recorder.previous_profile_present = previous is not None or previous_thread is not None
    def profile(frame,event,arg):
        observer = recorder.operand_observer
        if observer is None:
            recorder.profile(frame,event,arg)
        else:
            # Keep the newly retained entry and its sidecar handshake atomic
            # across threads. Monitoring callbacks use this same outer lock.
            with recorder.lock:
                recorder.profile(frame,event,arg)
                observer.profile(frame,event,arg)
        old = previous if threading.get_ident() == main_thread else previous_thread
        if old is not None:
            old(frame,event,arg)
    sys.setprofile(profile)
    threading.setprofile(profile)
    sampler = None
    if os.environ.get('SCAR_RESOURCE_SAMPLER') == '1':
        from scar.trace.resources import ResourceSampler
        sampler = ResourceSampler(recorder.out,interval_s=float(os.environ.get('SCAR_RESOURCE_INTERVAL','0.1')))
        sampler.start()
    def finish():
        if os.getpid() != recorder.pid:
            return
        observer = recorder.operand_observer
        if observer is not None:
            observer.stop()
        if sys.getprofile() is profile:
            sys.setprofile(previous)
        if threading.getprofile() is profile:
            threading.setprofile(previous_thread)
        recorder.close()
        if observer is not None:
            observer.close()
        if sampler is not None:
            sampler.stop()
    def forked():
        if recorder.closed:
            return
        observer = recorder.operand_observer
        if observer is not None:
            observer.after_fork()
        sys.setprofile(previous)
        threading.setprofile(previous_thread)
        for fd in (recorder.events_fd,recorder.codes_fd):
            os.close(fd)
        recorder.closed = True
    if hasattr(os,'register_at_fork'):
        os.register_at_fork(after_in_child=forked)
    atexit.register(finish)
    return recorder
