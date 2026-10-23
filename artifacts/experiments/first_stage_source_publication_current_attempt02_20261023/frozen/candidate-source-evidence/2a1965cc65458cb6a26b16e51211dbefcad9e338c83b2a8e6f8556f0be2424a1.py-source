"""Opt-in runtime backends for generic deterministic PyTorch modules.

The optimizer is deliberately independent of any workload.  It installs a
small hook around ``torch.nn.Module._call_impl`` and uses the same exact reuse
guard as the explicit backend.  Only concrete PyTorch module classes with a
reviewed read-only forward contract are eligible.  Unknown or user-defined
modules always execute on the original path.

This is an execution backend, not a profiler.  It is enabled with
``SCAR_OPTIMIZE=1`` and writes counters to ``SCAR_OPTIMIZE_REPORT``.  The
report makes every hit, miss and fallback reason auditable.
"""
from __future__ import annotations

import atexit
import builtins
import collections
import json
import os
import sys
import threading
import time
from functools import wraps
from pathlib import Path
from typing import Any
import weakref

from . import session as _session_module
from scar.backends.reuse import inferred_exact_reuse
from scar.ir import mark_storage_write


_ORIGINAL_IMPORT = None
_ORIGINAL_CALL = None
_ORIGINAL_MODULE_CLASS = None
_PATCHED = False
_IMPORT_PATCHED = False
_CLOSED = False
_CONTROLLER = None
_DISPATCH_MODE = None


def _safe_module_types(torch):
    """Return exact classes whose forward is deterministic and read-only.

    This list is a library contract, not a guess based on a module name.  It
    excludes stochastic layers and training-state updates.  A subclass is not
    accepted because it may override ``forward`` or add hidden effects.
    """
    nn = torch.nn
    names = (
        "Linear", "Bilinear",
        "Conv1d", "Conv2d", "Conv3d", "ConvTranspose1d",
        "ConvTranspose2d", "ConvTranspose3d",
        "ReLU", "ReLU6", "GELU", "SiLU", "Mish", "ELU", "SELU",
        "CELU", "LeakyReLU", "PReLU", "Tanh", "Sigmoid", "Hardsigmoid",
        "Hardswish", "Softplus", "Softsign", "Tanhshrink", "Threshold",
        "LayerNorm", "GroupNorm", "RMSNorm",
        "Flatten", "Unflatten", "Identity",
        "AvgPool1d", "AvgPool2d", "AvgPool3d", "AdaptiveAvgPool1d",
        "AdaptiveAvgPool2d", "AdaptiveAvgPool3d", "MaxPool1d", "MaxPool2d",
        "MaxPool3d", "AdaptiveMaxPool1d", "AdaptiveMaxPool2d",
        "AdaptiveMaxPool3d", "Softmax", "LogSoftmax",
    )
    return frozenset(
        cls for name in names
        if (cls := getattr(nn, name, None)) is not None
    )


def _has_hooks(module, torch) -> bool:
    global_state = torch.nn.modules.module
    if any(getattr(global_state, name, {}) for name in (
            "_global_forward_hooks", "_global_forward_pre_hooks",
            "_global_backward_hooks")):
        return True
    return any(m._forward_hooks or m._forward_pre_hooks or m._backward_hooks
               for m in torch.nn.Module.modules(module))


class RuntimeOptimizer:
    """Own per-module inferred contracts and expose auditable counters."""

    def __init__(self, torch):
        self.torch = torch
        self.safe_types = _safe_module_types(torch)
        # Per-module defaults stay deliberately small: a neural module can
        # expose large parameter tensors, and retaining one copy per observed
        # input key must not compete with the workload's model memory.
        self.max_entries = max(1, int(os.environ.get("SCAR_OPTIMIZE_MAX_ENTRIES", "32")))
        self.max_bytes = max(1, int(os.environ.get(
            "SCAR_OPTIMIZE_MAX_BYTES", str(32 * 1024 * 1024))))
        self.wrappers = weakref.WeakKeyDictionary()
        self.counts = collections.Counter()
        self.fallbacks = collections.Counter()
        self.per_module: dict[str, dict[str, int | str]] = {}
        self.compute_ns: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        self.disabled: weakref.WeakSet = weakref.WeakSet()
        self._lock = threading.RLock()

    def eligible(self, module) -> tuple[bool, str]:
        torch = self.torch
        if type(module) not in self.safe_types:
            return False, "module class has no reviewed read-only contract"
        if torch.is_grad_enabled():
            return False, "gradients enabled"
        if _has_hooks(module, torch):
            return False, "module hook is outside inferred contract"
        # Training BatchNorm-like modules are intentionally absent from the
        # whitelist.  Keep a defensive check for future additions.
        if type(module).__name__.startswith(("BatchNorm", "SyncBatchNorm")) and module.training:
            return False, "training state update"
        try:
            if any(t.requires_grad for t in _session_module._flatten(module.__dict__.get("_parameters", {}))
                   if hasattr(t, "requires_grad")):
                # Parameters normally require grad even in inference mode;
                # this is not a reason to reject a no-grad call.  The check is
                # handled by ExactReuse for actual input tensors.
                pass
        except Exception:
            pass
        return True, "reviewed deterministic PyTorch module contract"

    def _wrapper(self, module, original_call):
        with self._lock:
            wrapper = self.wrappers.get(module)
            if wrapper is not None:
                return wrapper
            def invoke(*args, **kwargs):
                started = time.perf_counter_ns()
                result = original_call(module, *args, **kwargs)
                self.compute_ns[module] = time.perf_counter_ns() - started
                return result
            wrapper = inferred_exact_reuse(
                module, invoke, max_entries=self.max_entries,
                max_bytes=self.max_bytes)
            self.wrappers[module] = wrapper
            return wrapper

    def call(self, module, original_call, args, kwargs):
        with self._lock:
            ok, reason = self.eligible(module)
            name = f"{type(module).__module__}.{type(module).__qualname__}"
            self.counts["attempted"] += 1
            if not ok or module in self.disabled:
                self.counts["fallback"] += 1
                self.fallbacks[reason if ok else reason] += 1
                return original_call(module, *args, **kwargs)
            wrapper = self._wrapper(module, original_call)
            before_hits, before_misses = wrapper.hits, wrapper.misses
            before_probes = wrapper.validated_probes
            started = time.perf_counter_ns()
            result = wrapper(*args, **kwargs)
            call_kind = wrapper.last_call_kind
            elapsed_ns = time.perf_counter_ns() - started
            hits = wrapper.hits - before_hits
            misses = wrapper.misses - before_misses
            probes = wrapper.validated_probes - before_probes
            item_key = f"{type(module).__module__}.{type(module).__qualname__}"
            item = self.per_module.setdefault(item_key, {
                "class": item_key, "calls": 0, "hits": 0, "misses": 0,
                "retained_bytes": 0,
            })
            # CUDA launches are asynchronous. Measure only the first probe
            # and first real hit synchronously, so the cost gate compares the
            # completed original computation to completed cache materialization
            # without synchronizing every ordinary miss.
            if (call_kind in {"probe", "hit"}
                    and not bool(item.get("cost_decided", False))):
                if self.torch.cuda.is_available():
                    self.torch.cuda.synchronize()
                elapsed_ns = time.perf_counter_ns() - started
            self.counts["hit"] += hits
            self.counts["miss"] += misses
            self.counts["validation_probe"] += probes
            if hits:
                self.counts["transformed_calls"] += hits
            if misses and wrapper.last_fallback:
                self.fallbacks[wrapper.last_fallback] += 1
            item["calls"] = int(item["calls"]) + 1
            item["hits"] = int(item["hits"]) + hits
            item["misses"] = int(item["misses"]) + misses
            item["retained_bytes"] = int(wrapper.retained_bytes)
            if misses:
                item["last_miss_ns"] = int(elapsed_ns)
                item.setdefault("min_miss_ns", int(elapsed_ns))
                item["min_miss_ns"] = min(int(item["min_miss_ns"]), int(elapsed_ns))
                item["last_compute_ns"] = int(self.compute_ns.get(module, 0))
                if item["last_compute_ns"]:
                    item.setdefault("min_compute_ns", int(item["last_compute_ns"]))
                    item["min_compute_ns"] = min(
                        int(item["min_compute_ns"]), int(item["last_compute_ns"]))
            if probes:
                item["last_probe_compute_ns"] = int(elapsed_ns)
                item.setdefault("min_probe_compute_ns", int(elapsed_ns))
                item["min_probe_compute_ns"] = min(
                    int(item["min_probe_compute_ns"]), int(elapsed_ns))
            if hits:
                item["last_hit_ns"] = int(elapsed_ns)
                item.setdefault("max_hit_ns", 0)
                item["max_hit_ns"] = max(int(item["max_hit_ns"]), int(elapsed_ns))
                # A hit that costs at least as much as the cheapest observed
                # original call is not profitable for this module.  Disable
                # future entries and clear retained outputs; this is a
                # measured cost decision rather than a workload-specific
                # threshold.  One probe hit is allowed through so its exact
                # result remains part of validation evidence.
                compute_ns = int(item.get("min_probe_compute_ns", 0)
                                 or item.get("min_compute_ns", 0))
                if compute_ns > 0 and elapsed_ns >= compute_ns:
                    self.disabled.add(module)
                    wrapper.clear()
                    self.counts["unprofitable"] += 1
                    self.fallbacks["measured hit overhead >= original compute cost"] += 1
                    item["cost_decided"] = True
                elif compute_ns > 0:
                    # One synchronous comparison is enough for this module
                    # contract. The measured result is retained in the report
                    # while subsequent hits stay asynchronous for throughput.
                    item["cost_decided"] = True
            return result

    def report(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": "Observed",
                "backend": "inferred_exact_reuse",
                "contract": "exact built-in torch.nn module class; no hooks; no-grad; input/state/RNG/output guards",
                "safe_module_types": sorted(f"{x.__module__}.{x.__qualname__}" for x in self.safe_types),
                "limits": {"max_entries": self.max_entries, "max_bytes": self.max_bytes},
                "counts": dict(self.counts),
                "fallback_reasons": dict(self.fallbacks),
                "disabled_modules": sorted(
                    f"{type(x).__module__}.{type(x).__qualname__}"
                    for x in list(self.disabled)),
                "modules": sorted(self.per_module.values(), key=lambda x: str(x["class"])),
                "evidence": "Observed",
            }


def _patch_torch(torch):
    global _PATCHED, _ORIGINAL_CALL, _ORIGINAL_MODULE_CLASS, _CONTROLLER
    if _PATCHED:
        return
    module_cls = torch.nn.Module
    original_call = module_cls._call_impl
    if getattr(original_call, "_scar_runtime_optimizer", False):
        _PATCHED = True
        return
    _ORIGINAL_CALL = original_call
    _ORIGINAL_MODULE_CLASS = module_cls
    _CONTROLLER = RuntimeOptimizer(torch)

    @wraps(original_call)
    def call_impl(self, *args, **kwargs):
        return _CONTROLLER.call(self, original_call, args, kwargs)

    call_impl._scar_runtime_optimizer = True
    module_cls._call_impl = call_impl
    _PATCHED = True


def _install_write_observer(torch):
    """Observe PyTorch in-place/out writes without tracing every operator.

    The observer is intentionally narrow.  Ordinary reads and compute do not
    advance SCAR epochs; only mutating overloads and ``out=`` destinations do.
    Foreign writes remain covered by the quick fingerprint plus retained exact
    snapshot in the reuse backend.
    """
    global _DISPATCH_MODE
    if _DISPATCH_MODE is not None:
        return
    try:
        from torch.utils._python_dispatch import TorchDispatchMode
    except Exception:
        return

    def flatten(value):
        return [item for item in _session_module._flatten(value)
                if isinstance(item, torch.Tensor)]

    class WriteObserver(TorchDispatchMode):
        def __torch_dispatch__(self, func, types, args=(), kwargs=None):
            kwargs = kwargs or {}
            result = func(*args, **kwargs)
            name = getattr(func, "__name__", "") or str(func)
            base = name.rsplit(".", 1)[-1]
            mutating = base.endswith("_") or base in {
                "copy", "copy_", "resize", "resize_", "resize_as_", "set_",
                "as_strided_", "index_put", "index_put_",
            } or "out" in kwargs
            if mutating:
                for tensor in flatten(args) + flatten(kwargs.get("out")):
                    try:
                        mark_storage_write(tensor)
                    except (RuntimeError, TypeError):
                        pass
            return result

    try:
        _DISPATCH_MODE = WriteObserver()
        _DISPATCH_MODE.__enter__()
    except Exception:
        _DISPATCH_MODE = None


def _patch_import_hook():
    global _ORIGINAL_IMPORT, _IMPORT_PATCHED
    if _IMPORT_PATCHED:
        return
    _ORIGINAL_IMPORT = builtins.__import__

    @wraps(_ORIGINAL_IMPORT)
    def importing(name, globals=None, locals=None, fromlist=(), level=0):
        result = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
        if name == "torch" or name.startswith("torch."):
            try:
                import torch
                _patch_torch(torch)
            except Exception:
                pass
        return result

    builtins.__import__ = importing
    _IMPORT_PATCHED = True


def close() -> None:
    global _CLOSED, _DISPATCH_MODE
    if _CLOSED:
        return
    _CLOSED = True
    if _CONTROLLER is not None:
        report_path = os.environ.get("SCAR_OPTIMIZE_REPORT")
        if report_path:
            path = Path(report_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(_CONTROLLER.report(), indent=2) + "\n",
                            encoding="utf-8")
    if _ORIGINAL_MODULE_CLASS is not None and _ORIGINAL_CALL is not None:
        _ORIGINAL_MODULE_CLASS._call_impl = _ORIGINAL_CALL
    if _DISPATCH_MODE is not None:
        try:
            _DISPATCH_MODE.__exit__(None, None, None)
        finally:
            _DISPATCH_MODE = None
    if _IMPORT_PATCHED and _ORIGINAL_IMPORT is not None:
        builtins.__import__ = _ORIGINAL_IMPORT


def install() -> RuntimeOptimizer | None:
    """Install the backend before or after torch import."""
    if not os.environ.get("SCAR_OPTIMIZE"):
        return None
    _patch_import_hook()
    try:
        import torch
        import torch.nn
        _patch_torch(torch)
        _install_write_observer(torch)
    except Exception:
        return None
    atexit.register(close)
    return _CONTROLLER


__all__ = ["RuntimeOptimizer", "close", "install"]
