"""Bounded production dispatch observations bound to real ETO marker slots.

No Tensor contents, versions, hashes or copies are observed. A callback scope
does not enclose the original dispatcher's already-started RecordFunction.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import threading

PRODUCTION_PROFILE = "scar.dispatch-marker-collector-v1"
PROVIDER_REVISION = "cf30153c4c131c8164ee7798e5022d810682e2cb"


class DispatchEvidence:
    def __init__(self, out, recorder, *, nonce, provider_revision,
                 max_events=400000, max_bytes=256000000, max_slots=1024,
                 max_depth=16, max_items=4096, max_frames=32):
        limits = dict(max_events=max_events, max_bytes=max_bytes, max_slots=max_slots,
                      max_depth=max_depth, max_items=max_items, max_frames=max_frames)
        if any(type(value) is not int or value < 1 for value in limits.values()):
            raise ValueError("dispatch budgets must be positive exact integers")
        if provider_revision != PROVIDER_REVISION or re.fullmatch(r"[0-9a-f]{32}", nonce) is None:
            raise ValueError("unsupported dispatch provider or nonce")
        self.pid, self.owner_ident = os.getpid(), threading.get_ident()
        self.owner_native_tid = threading.get_native_id()
        if recorder.pid != self.pid or recorder.closed:
            raise ValueError("dispatch recorder must be live in the owner process")
        self.out, self.recorder, self.nonce = Path(out).resolve(), recorder, nonce
        self.provider_revision, self.limits = provider_revision, limits
        self.event_path = self.out / f"dispatch-observations.{self.pid}.{nonce}.jsonl"
        self.meta_path = self.out / f"dispatch-meta.{self.pid}.{nonce}.json"
        if self.meta_path.exists() or self.meta_path.is_symlink():
            raise ValueError("dispatch output must be fresh")
        self.fd = os.open(self.event_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self._digest = hashlib.sha256()
        self._buffer = bytearray()
        self._buffer_limit = 65536
        self._lock = threading.RLock()
        self._mode = self._top_mode = self._torch = None
        self._enter = self._exit = None
        self._sequence = self._events = self._bytes = self._dropped = 0
        self._errors, self._gaps = [], []
        self._installed = self._closed = self._stopped = self._io_failed = False
        self._mode_popped = False
        self.recorder.observer_files.add(__file__)

    def _error(self, stage, error):
        if len(self._errors) < 16:
            self._errors.append({"stage": stage, "type": type(error).__name__})

    def _gap(self, code):
        if code not in self._gaps and len(self._gaps) < 32:
            self._gaps.append(code)

    def _emit(self, kind, fields):
        with self._lock:
            if self._closed or self._io_failed or os.getpid() != self.pid:
                return False
            if self._events >= self.limits["max_events"]:
                self._dropped += 1; self._stopped = True
                self._gap("event_budget_exceeded"); return False
            row = {"index": self._events + 1, "kind": kind, "process_id": self.pid, **fields}
            data = (json.dumps(row, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
            if len(data) > 2_000_000 or self._bytes + len(data) > self.limits["max_bytes"]:
                self._dropped += 1; self._stopped = True
                self._gap("byte_or_line_budget_exceeded"); return False
            try:
                self._bytes += len(data)
                self._digest.update(data)
                if len(self._buffer) + len(data) > self._buffer_limit:
                    self._flush()
                if len(data) >= self._buffer_limit:
                    self._write_all(data)
                else:
                    self._buffer.extend(data)
            except OSError as error:
                self._io_failed = self._stopped = True
                self._error("write", error); return False
            self._events += 1
            return True

    def _write_all(self, data):
        if os.getpid() != self.pid:
            raise OSError("forked process cannot flush parent dispatch records")
        offset = 0
        while offset < len(data):
            size = os.write(self.fd, data[offset:])
            if size <= 0:
                raise OSError("dispatch sidecar made no write progress")
            offset += size

    def _flush(self):
        if self._buffer:
            self._write_all(self._buffer)
            self._buffer.clear()

    def _leaves(self, value, prefix):
        leaves, gaps, seen_containers = [], [], set()
        items = 0
        def visit(item, path, depth):
            nonlocal items
            items += 1
            if items > self.limits["max_items"] or depth > self.limits["max_depth"]:
                raise ValueError("dispatch container budget exceeded")
            kind = type(item)
            if kind is self._torch.Tensor or kind is self._torch.nn.Parameter:
                if len(leaves) >= self.limits["max_slots"]:
                    raise ValueError("dispatch Tensor slot budget exceeded")
                leaves.append((path, item)); return
            if kind in (tuple, list, dict):
                if id(item) in seen_containers:
                    gaps.append({"path": list(path), "reason": "cyclic_container"}); return
                seen_containers.add(id(item))
                try:
                    if kind is dict:
                        for key, child in item.items():
                            if type(key) is not str:
                                gaps.append({"path": list(path), "reason": "non_string_mapping_key"}); continue
                            visit(child, (*path, key), depth + 1)
                    else:
                        for index, child in enumerate(item):
                            visit(child, (*path, index), depth + 1)
                finally:
                    seen_containers.remove(id(item))
            elif kind not in (type(None), bool, int, float, str, self._torch.dtype,
                               self._torch.device, self._torch.layout, self._torch.memory_format):
                gaps.append({"path": list(path), "reason": "unqualified_leaf_or_tensor_subclass"})
        visit(value, prefix, 0)
        return leaves, gaps

    def start(self, torch):
        if os.getpid() != self.pid or threading.get_ident() != self.owner_ident or self._installed:
            raise ValueError("dispatch mode start requires its installing process/thread")
        if getattr(torch.version, "git_version", None) != self.provider_revision:
            raise ValueError("dispatch provider revision mismatch")
        from torch.utils._python_dispatch import TorchDispatchMode, _get_current_dispatch_mode
        self._torch, self._top_mode = torch, _get_current_dispatch_mode
        self._enter = torch.autograd._record_function_with_args_enter
        self._exit = torch.autograd._record_function_with_args_exit
        if _get_current_dispatch_mode() is not None:
            self._gap("preexisting_foreign_dispatch_mode_not_instrumented")
            return False
        owner = self
        class Observe(TorchDispatchMode):
            supports_higher_order_operators = True
            @classmethod
            def _should_skip_dynamo(cls):
                return False
            def __torch_dispatch__(self, func, types, args=(), kwargs=None):
                return owner._dispatch(func, args, kwargs)
        self._mode = Observe()
        self._forward_adapter_code = Observe.__torch_dispatch__.__code__
        self._mode.__enter__()
        self._installed = True
        witness = getattr(self.recorder, 'collector_witness', None)
        if witness is not None:
            callbacks = ('_dispatch','_leaves','_call_target') if getattr(self.recorder,'process_ports',False) else ('_dispatch','_leaves')
            witness.register('dispatch', self, callbacks, hook=Observe.__torch_dispatch__)
        return True

    def _call_target(self, func, args, kwargs):
        token = None
        if getattr(self.recorder,'process_ports',False):
            try:
                frame = sys._getframe()
                adapter = frame.f_back
                while adapter is not None and adapter.f_code is not self._forward_adapter_code:
                    adapter = adapter.f_back
                if adapter is not None:
                    token = self.recorder._begin_target_forward(frame, 'DISPATCH', adapter_frame=adapter)
            except Exception as error:
                self._error('target_forward_begin', error)
            finally:
                frame = adapter = None  # No frame/Tensor lifetime extension through a frame-local cycle.
        try:
            # Exactly one original call, including on observation failure.
            return func(*args, **({} if kwargs is None else kwargs))
        finally:
            if token is not None:
                try:
                    self.recorder._end_target_forward(token)
                except Exception as error:
                    self._error('target_forward_end', error)

    def _dispatch(self, func, args, kwargs):
        if (self._stopped or self._closed or os.getpid() != self.pid
                or threading.get_ident() != self.owner_ident):
            if getattr(self.recorder,'process_ports',False):
                return self._call_target(func, args, kwargs)
            return func(*args, **({} if kwargs is None else kwargs))
        witness = getattr(self.recorder, 'collector_witness', None)
        if witness is not None and not witness.guard('dispatch', sys._getframe().f_code):
            self._stopped = True
            if getattr(self.recorder,'process_ports',False):
                return self._call_target(func, args, kwargs)
            return func(*args, **({} if kwargs is None else kwargs))
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
        span = f"scar-dispatch:{self.nonce}:{self.pid}:{sequence}:span"
        output_name = f"scar-dispatch:{self.nonce}:{self.pid}:{sequence}:output"
        handle = None
        input_leaves, output_leaves = [], []
        captured, input_gaps = None, []
        try:
            input_leaves, input_gaps = self._leaves((args, {} if kwargs is None else kwargs), ())
            captured = self.recorder.observe_dispatch(sys._getframe().f_back, input_leaves,
                max_frames=self.limits["max_frames"], max_slots=self.limits["max_slots"])
            if captured is None:
                self._gap("call_recorder_unavailable")
            else:
                operator = str(func) if type(func) is self._torch._ops.OpOverload else None
                if self._emit("DISPATCH_BEGIN", {"sequence": sequence, "marker": span,
                    "observation": captured, "slot_gaps": input_gaps, "operator": operator}):
                    handle = self._enter(span, *(tensor for _, tensor in input_leaves))
        except Exception as error:
            self._error("input_observation", error)
        try:
            if getattr(self.recorder,'process_ports',False):
                result = self._call_target(func, args, kwargs)
            else:
                result = func(*args, **({} if kwargs is None else kwargs))
        except BaseException:
            self._emit("DISPATCH_END", {"sequence": sequence, "outcome": "RAISED",
                       "span_enter_returned": handle is not None, "output_marker": None})
            raise
        else:
            output_entered = False
            if handle is not None:
                output_handle = None
                try:
                    output_leaves, output_gaps = self._leaves(result, ())
                    observation = self.recorder.observe_dispatch(sys._getframe().f_back, output_leaves,
                        max_frames=self.limits["max_frames"], max_slots=self.limits["max_slots"])
                    if observation is not None and self._emit("DISPATCH_OUTPUT", {
                        "sequence": sequence, "marker": output_name, "observation": observation,
                        "slot_gaps": output_gaps}):
                        output_handle = self._enter(output_name, *(tensor for _, tensor in output_leaves))
                        output_entered = True
                except Exception as error:
                    self._error("output_observation", error)
                finally:
                    if output_handle is not None:
                        try:
                            self._exit(output_handle)
                        except Exception as error:
                            self._error("output_marker_exit", error); self._stopped = True
            self._emit("DISPATCH_END", {"sequence": sequence, "outcome": "RETURNED",
                "span_enter_returned": handle is not None,
                "output_marker": output_name if output_entered else None})
            return result
        finally:
            if handle is not None:
                try:
                    self._exit(handle)
                except Exception as error:
                    self._error("span_exit", error); self._stopped = True
            input_leaves.clear(); output_leaves.clear()

    def stop(self):
        """Stop observations before the owning profiler stops; never pop foreign modes."""
        self._stopped = True
        if not self._installed or os.getpid() != self.pid:
            return
        if threading.get_ident() != self.owner_ident:
            self._gap("close_on_different_thread"); return
        if self._top_mode() is not self._mode:
            self._gap("foreign_top_mode_preserved_owned_mode_inert"); return
        try:
            self._mode.__exit__(None, None, None)
            self._installed = False; self._mode_popped = True
        except Exception as error:
            self._error("mode_exit", error)

    def close(self, *, native_manifest=None):
        if self._closed or os.getpid() != self.pid:
            return
        self.stop()
        with self._lock:
            self._closed = True
            try:
                if not self._io_failed:
                    self._flush()
            except OSError as error:
                self._io_failed = self._stopped = True
                self._error("flush", error)
            finally:
                self._buffer.clear()
            os.close(self.fd)
            native = None
            if native_manifest is not None:
                path = Path(native_manifest)
                try:
                    with path.open("rb") as stream:
                        payload = stream.read(2_000_001)
                    if len(payload) > 2_000_000:
                        raise OSError("native collector manifest exceeds metadata bound")
                    native = {"path": str(path), "raw_sha256": hashlib.sha256(payload).hexdigest(),
                              "raw_bytes": len(payload)}
                except OSError as error:
                    self._error("native_manifest", error)
            metadata = {"schema": "scar.dispatch-observation-trace", "schema_version": 1,
                "profile": PRODUCTION_PROFILE, "provider_revision": self.provider_revision,
                "process_id": self.pid, "owner_python_ident": self.owner_ident,
                "owner_native_tid": self.owner_native_tid, "nonce": self.nonce,
                "limits": self.limits, "events": self._events, "dispatch_attempts": self._sequence,
                "bytes": self._bytes, "dropped_events": self._dropped, "errors": self._errors,
                "gaps": self._gaps, "io_failed": self._io_failed, "mode_popped": self._mode_popped,
                "file": {"path": str(self.event_path), "raw_sha256": self._digest.hexdigest(),
                         "raw_bytes": self._bytes, "lines": self._events},
                "native_manifest": native,
                "scope": "owner process and installing thread dispatch callbacks only",
                "reference_contents_observed": False, "tensor_versions_observed": False,
                "direct_python_operator_correspondence_established": False,
                "logical_versions_established": False, "state_effects_established": False,
                "resource_readiness_established": False, "whole_model_established": False,
                "transformation_authorized": False}
            payload = (json.dumps(metadata, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
            fd = os.open(self.meta_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                offset = 0
                while offset < len(payload):
                    written = os.write(fd, payload[offset:])
                    if written <= 0:
                        raise OSError("dispatch metadata made no write progress")
                    offset += written
            finally:
                os.close(fd)


__all__ = ["DispatchEvidence", "PRODUCTION_PROFILE", "PROVIDER_REVISION"]
