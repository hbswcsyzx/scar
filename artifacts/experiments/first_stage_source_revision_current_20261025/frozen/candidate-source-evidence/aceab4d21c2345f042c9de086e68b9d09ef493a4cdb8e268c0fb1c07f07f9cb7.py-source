"""Runtime hooks for arbitrary Python/PyTorch child processes.

This module deliberately has no workload imports. It only observes the Python
and torch runtime and writes the generic SCAR IR.
"""
from __future__ import annotations

import atexit
import builtins
import os
import sys
import threading
import time
from functools import wraps

from .session import TraceSession
from scar.ir import CodeID

SESSION: TraceSession | None = None
_old_profile = None
_old_trace = None
_old_thread_profile = None
_old_thread_trace = None
_torch_patched = False
_torch_patching = False
_profiler = None
_dispatch_mode = None


def _profile(frame, event, arg):
    if SESSION is not None:
        if event == "call":
            SESSION.python_call(frame)
        elif event == "exception":
            SESSION.python_exception(frame, arg)
        elif event == "c_call":
            SESSION.c_call(frame, arg)
        elif event == "return":
            SESSION.python_return(frame, arg)
    if _old_profile is not None:
        try:
            _old_profile(frame, event, arg)
        except Exception:
            pass


def _trace_lines(frame, event, arg):
    """Optional line tracer used for loop-instance evidence."""
    if SESSION is not None:
        if event == "line":
            SESSION.python_line(frame)
        elif event == "return":
            SESSION.python_line_return(frame)
    return _trace_lines


def _patch_torch(torch):
    global _torch_patched, _torch_patching
    if _torch_patched or _torch_patching:
        return
    # The import hook can call this while ``torch`` is only partially
    # initialized.  Do not mark the patch complete until every dependency and
    # assignment below succeeds; install() will then retry after torch.nn is
    # available.
    _torch_patching = True
    try:
        import torch.nn  # force the module namespace before patching
        module_cls = torch.nn.Module
        original_call = module_cls._call_impl
        if getattr(original_call, "_scar_module_hook", False):
            _torch_patched = True
            return

        @wraps(original_call)
        def call_impl(self, *args, **kwargs):
            captured_inputs = None
            if SESSION is not None:
                try:
                    captured_inputs = SESSION.module_inputs(self, args, kwargs)
                except Exception:
                    if os.environ.get("SCAR_TRACE_DEBUG"):
                        import traceback
                        traceback.print_exc()
            started = time.perf_counter_ns()
            result = original_call(self, *args, **kwargs)
            if SESSION is not None:
                try:
                    code = getattr(self.forward, "__code__", None)
                    code_id = None if code is None else CodeID.from_code(code).key()
                    SESSION.module_call(self, args, kwargs, result,
                                        time.perf_counter_ns() - started, code_id,
                                        captured_inputs=captured_inputs)
                except Exception:
                    if os.environ.get("SCAR_TRACE_DEBUG"):
                        import traceback
                        traceback.print_exc()
            return result

        module_cls._call_impl = call_impl
        call_impl._scar_module_hook = True
        for name in ("to", "cuda", "cpu"):
            original = getattr(torch.Tensor, name, None)
            if original is None or getattr(original, "_scar_wrapped", False):
                continue

            @wraps(original)
            def transfer(self, *args, __original=original, __name=name, **kwargs):
                started = time.perf_counter_ns()
                result = __original(self, *args, **kwargs)
                if SESSION is not None:
                    try:
                        SESSION.transfer(__name, self, result, time.perf_counter_ns() - started)
                    except Exception:
                        if os.environ.get("SCAR_TRACE_DEBUG"):
                            import traceback
                            traceback.print_exc()
                return result
            transfer._scar_wrapped = True
            setattr(torch.Tensor, name, transfer)
        _torch_patched = True
    finally:
        _torch_patching = False


def _install_torch_import_hook():
    original_import = builtins.__import__

    @wraps(original_import)
    def importing(name, globals=None, locals=None, fromlist=(), level=0):
        result = original_import(name, globals, locals, fromlist, level)
        if name == "torch" or name.startswith("torch."):
            try:
                import torch
                _patch_torch(torch)
            except Exception:
                pass
        return result
    builtins.__import__ = importing


def install(out: str | None = None) -> TraceSession:
    global SESSION, _old_profile, _old_trace, _old_thread_profile
    global _old_thread_trace, _profiler, _dispatch_mode
    SESSION = TraceSession(out or os.environ["SCAR_TRACE_DIR"])
    _old_profile = sys.getprofile()
    _old_trace = sys.gettrace()
    _old_thread_profile = threading.getprofile()
    _old_thread_trace = threading.gettrace()
    sys.setprofile(_profile)
    # ``sys.setprofile`` only affects the current thread.  Install the same
    # observer as the default for threads created by the workload so worker
    # control/actions remain in the process graph.  Existing threads cannot
    # be retroactively instrumented by CPython's public API.
    threading.setprofile(_profile)
    if os.environ.get("SCAR_TRACE_LINES", "0") == "1":
        sys.settrace(_trace_lines)
        threading.settrace(_trace_lines)
    try:
        import torch
        import torch.nn
        _patch_torch(torch)
        # PyTorch's supported profiler is the source of operator and CUDA
        # runtime evidence; SCAR does not reimplement CUPTI.
        if os.environ.get("SCAR_TORCH_PROFILER", "1") != "0":
            try:
                _profiler = torch.profiler.profile(record_shapes=True, profile_memory=True,
                                                   with_stack=False)
                _profiler.__enter__()
            except Exception:
                _profiler = None
        if os.environ.get("SCAR_TORCH_DISPATCH", "0") == "1":
            try:
                from torch.utils._python_dispatch import TorchDispatchMode

                class RecorderMode(TorchDispatchMode):
                    def __torch_dispatch__(self, func, types, args=(), kwargs=None):
                        started = time.perf_counter_ns()
                        result = func(*args, **(kwargs or {}))
                        if SESSION is not None:
                            SESSION.torch_dispatch(str(func), args, kwargs or {}, result,
                                                    time.perf_counter_ns() - started)
                        return result

                _dispatch_mode = RecorderMode()
                _dispatch_mode.__enter__()
            except Exception as exc:
                if os.environ.get("SCAR_TRACE_DEBUG"):
                    print(f"SCAR dispatch recorder disabled: {exc}", flush=True)
    except Exception:
        pass

    def close():
        if _dispatch_mode is not None:
            try:
                _dispatch_mode.__exit__(None, None, None)
            except Exception:
                pass
        if _profiler is not None and SESSION is not None:
            try:
                _profiler.__exit__(None, None, None)
                profiler_path = SESSION.out / f"torch-profiler.{SESSION.process_id}.json"
                _profiler.export_chrome_trace(str(profiler_path))
                from .cuda import correlate_transfer_states, profiler_activities
                activities = list(profiler_activities(profiler_path, SESSION.process_id))
                correlate_transfer_states(SESSION.transfer_records, activities)
                for activity in activities:
                    SESSION._emit(activity)
                for item in _profiler.key_averages():
                    key = str(item.key)
                    if key.startswith("ProfilerStep"):
                        continue
                    from scar.ir import Effect, Event, Knowledge
                    SESSION._emit(Event(kind="torch_op", code_id=key,
                                        # key_averages() is an aggregate, not
                                        # one dynamic InvocationID.  Keep the
                                        # count as measurement metadata and
                                        # leave invocation_id unset so the IR
                                        # cannot confuse it with a call.
                                        invocation_id=None,
                                        duration_ns=int(item.self_cpu_time_total * 1000),
                                        labels=["VAL", "OPAQUE"],
                                        effect=Effect(rng_effect=Knowledge.UNKNOWN,
                                                       may_raise=Knowledge.UNKNOWN,
                                                       external_effect=Knowledge.UNKNOWN,
                                                       ordering_effect=Knowledge.UNKNOWN),
                                        resource={"count": int(item.count),
                                                  "cuda_time_total_us": float(getattr(item, "device_time_total", 0.0)),
                                                  "cpu_memory_usage": int(getattr(item, "cpu_memory_usage", 0)),
                                                  "self_cpu_memory_usage": int(getattr(item, "self_cpu_memory_usage", 0)),
                                                  "device_memory_usage": int(getattr(item, "device_memory_usage", 0)),
                                                  "self_device_memory_usage": int(getattr(item, "self_device_memory_usage", 0)),
                                                  "device_type": str(getattr(item, "device_type", "unknown"))},
                                        metadata={"aggregate": True}))
            except Exception as exc:
                if os.environ.get("SCAR_TRACE_DEBUG"):
                    print(f"SCAR torch profiler export failed: {exc}", flush=True)
        if SESSION is not None:
            SESSION.close()
        sys.setprofile(_old_profile)
        sys.settrace(_old_trace)
        threading.setprofile(_old_thread_profile)
        threading.settrace(_old_thread_trace)
    atexit.register(close)
    return SESSION
