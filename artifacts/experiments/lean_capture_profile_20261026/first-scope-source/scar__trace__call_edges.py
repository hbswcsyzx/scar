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
                 max_codes=4096, max_values=64, max_path=16, max_references=8192, lean_plan=None):
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
        self.lean_plan = lean_plan
        self.lean_plan_artifact = None
        if lean_plan is not None:
            from scar.trace.lean_capture import LeanCapturePlan
            if type(lean_plan) is not LeanCapturePlan or lean_plan.namespace_root != self.root:
                raise ValueError('lean capture needs its exact typed namespace plan')
            self.lean_plan_artifact = lean_plan.publish(self.out, self.pid)
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
        # Bytes only: no application references and no destructor that could
        # flush a parent's buffered records after a raw fork.
        self._buffers = {self.events_fd: bytearray(), self.codes_fd: bytearray()}
        self._buffer_limit = 65536

    def _inside(self, frame):
        if frame is None:
            return False
        filename = frame.f_code.co_filename
        return os.path.isabs(filename) and (filename == self.root or filename.startswith(self.root_prefix))

    def _observe_entry(self, frame):
        if self.lean_plan is not None:
            # Rooted planned activations keep thin real ancestry. Seen target
            # code alone never expands its implementation or monitoring mask.
            return (self.lean_plan.candidate(frame.f_code) is not None or
                    (threading.get_ident(), id(frame.f_back)) in self.active)
        if self._inside(frame) or self._inside(frame.f_back):
            return True
        observer = self.operand_observer
        targets = getattr(observer, 'python_targets', None) if observer is not None else None
        # Local monitoring masks belong to CodeType, not one invocation.
        # Once v2 selects an external code, retain all its later real entries,
        # including entry through an unobserved wrapper. This supplies a base
        # frame; only the separate exact pending-call rule can give a handshake.
        return targets is not None and (targets.observed_code(frame.f_code)
                                        or targets.accepts_frame(frame))

    def _write(self, fd, row):
        data = (json.dumps(row,ensure_ascii=True,separators=(",",":"),allow_nan=False)+"\n").encode()
        if self.bytes + len(data) > self.limits['max_bytes']:
            return False
        try:
            buffer = self._buffers[fd]
            self.bytes += len(data)
            if len(buffer) + len(data) > self._buffer_limit:
                self._flush(fd)
            if len(data) >= self._buffer_limit:
                self._write_all(fd, data)
            else:
                buffer.extend(data)
        except OSError:
            # A partial JSON row is invalid evidence. Stop this recorder;
            # retries must not append uncharged fragments or fabricate rows.
            self.io_failed = True
            raise
        return True

    def _write_all(self, fd, data):
        if os.getpid() != self.pid:
            raise OSError("forked process cannot flush parent call records")
        position = 0
        while position < len(data):
            written = os.write(fd, data[position:])
            if written <= 0:
                raise OSError("call trace write made no progress")
            position += written

    def _flush(self, fd):
        buffer = self._buffers[fd]
        if buffer:
            self._write_all(fd, buffer)
            buffer.clear()

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

    def observe_dispatch(self, frame, tensor_slots, *, max_frames=32, max_slots=1024):
        """Observe current retained ancestry and exact Tensor reference slots.

        This is not a direct-call correspondence, content version or effect
        receipt. The caller must keep the same tensors alive through its marker
        start callback. Only bounded transient references are held here.
        """
        if any(type(limit) is not int or limit < 1 for limit in (max_frames, max_slots)):
            raise ValueError("dispatch observation limits must be positive integers")
        with self.lock:
            if self.closed or self.io_failed or os.getpid() != self.pid:
                return None
            ident = threading.get_ident()
            context, traversed = None, 0
            while frame is not None and traversed < max_frames:
                retained = self.active.get((ident, id(frame)))
                if retained is not None:
                    position = site(frame.f_code, frame.f_lasti)
                    if position["code"] != retained[1]:
                        raise ValueError("retained dispatch frame/code mismatch")
                    context = {"invocation": retained[0], "code": retained[1],
                               "source_file": frame.f_code.co_filename,
                               "bytecode_offset": frame.f_lasti,
                               "site": position,
                               "kind": "retained ancestor context, not a proven direct caller"}
                    break
                frame = frame.f_back
                traversed += 1
            seen, references = {}, []
            try:
                if len(tensor_slots) > min(max_slots, self.limits["max_references"]):
                    raise ValueError("dispatch Tensor slot budget exceeded")
                for path, tensor in tensor_slots:
                    token = self._reference(tensor, seen)
                    references.append({"path": list(path), "ref": token,
                                       "identity_qualified": token.startswith("weak:")})
            finally:
                seen.clear()
            return {"process_id": self.pid, "python_ident": ident,
                    "native_tid": threading.get_native_id(), "call_event_index": self.index,
                    "context": context, "ancestry_complete": frame is None or context is not None,
                    "tensor_references": references}

    def profile(self, frame, event, arg):
        if self.closed or self.io_failed or event not in ('call','return'):
            return
        if frame.f_code.co_filename in self.observer_files:
            return
        if event == 'call':
            if not self._observe_entry(frame):
                return
        else:
            # No observation is produced for an unretained return. Read only
            # under the original lock; do not block on an inherited raw-fork
            # lock before checking that we are still the installing process.
            locked = self.lock.acquire(blocking=False)
            if locked:
                try:
                    if (threading.get_ident(), id(frame)) not in self.active:
                        return
                finally:
                    self.lock.release()
            elif os.getpid() != self.pid:
                return
        if os.getpid() != self.pid:
            return
        witness = getattr(self, 'collector_witness', None)
        if witness is not None and not witness.guard('calls', sys._getframe().f_code):
            return
        with self.lock:
            try:
                if event == 'call':
                    caller = frame.f_back
                    if not self._observe_entry(frame):
                        return
                    if self.index >= self.limits['max_events']:
                        self.dropped += 1
                        return
                    self.index += 1
                    self.invocation += 1
                    invocation = self.invocation
                    thread = threading.get_ident()
                    code = self._code(frame.f_code)
                    seen = {}
                    targets = getattr(self.operand_observer, 'python_targets', None)
                    detailed = (self.lean_plan is None or self.lean_plan.match(frame.f_code) is not None
                                or targets is not None and targets.accepts_frame(frame))
                    names = describe_code(frame.f_code)['parameters'] if detailed else ()
                    parameters, complete = (self._bindings(frame.f_locals,seen,names)
                                            if detailed else ([],False))
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
                    caller_locals, locals_complete = (([],False) if self.lean_plan is not None else
                        self._bindings(caller.f_locals,seen) if caller is not None else ([],True))
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
                    values,complete = (([],False) if self.lean_plan is not None else self._bindings(frame.f_locals,seen))
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
            for fd in (self.events_fd, self.codes_fd):
                try:
                    if not self.io_failed:
                        self._flush(fd)
                except OSError as error:
                    self.io_failed = True
                    if len(self.errors) < 16:
                        self.errors.append(type(error).__name__)
                finally:
                    self._buffers[fd].clear()
                    os.close(fd)
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
            if self.lean_plan is not None:
                from scar.ir.record_codec import encode
                from scar.trace.lean_capture import PROFILE
                metadata.update(capture_profile=PROFILE, capture_plan=encode(self.lean_plan_artifact),
                    unplanned_bodies_expanded=False)
            (self.out/f"call-meta.{self.pid}.json").write_text(json.dumps(metadata,indent=2)+'\n')


def install(out, project_root, *, lean_plan=None):
    owner = os.environ.get('SCAR_CALL_TRACE_OWNER_PID')
    if owner is not None and owner != str(os.getpid()):
        return None
    recorder = CallEdgeRecorder(out,project_root,
        max_events=int(os.environ.get('SCAR_CALL_MAX_EVENTS',100000)),
        max_bytes=int(os.environ.get('SCAR_CALL_MAX_BYTES',64000000)), lean_plan=lean_plan)
    os.environ['SCAR_CALL_TRACE_OWNER_PID'] = str(os.getpid())
    recorder.collector_witness = None
    if os.environ.get('SCAR_COLLECTOR_EXECUTION_WITNESS') == '1':
        from scar.trace.collector_execution_witness import CollectorExecutionWitness
        recorder.collector_witness = CollectorExecutionWitness(recorder)
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
    if recorder.collector_witness is not None:
        recorder.collector_witness.register_profile(profile)
    sampler = None
    if os.environ.get('SCAR_RESOURCE_SAMPLER') == '1':
        from scar.trace.resources import ResourceSampler
        sampler = ResourceSampler(recorder.out,interval_s=float(os.environ.get('SCAR_RESOURCE_INTERVAL','0.1')))
        sampler.start()
    def finish():
        if os.getpid() != recorder.pid:
            return
        observer = recorder.operand_observer
        if recorder.collector_witness is not None:
            recorder.collector_witness.before_close()
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
        if recorder.collector_witness is not None:
            recorder.collector_witness.close()
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
    recorder._collector_finish = finish
    return recorder
