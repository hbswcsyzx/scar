"""Guarded persistent materialization backend.

This backend caches a read-only materialization such as ``tensor.to(device)``.
It is deliberately opt-in: a transfer callable may have stream, ordering,
allocator, or external effects that cannot be inferred from its name.  The
contract marker therefore means that returning the same resident Tensor is
acceptable to the caller.  Source and resident byte snapshots still guard
against ordinary Torch and foreign-buffer writes; a mutated resident value
invalidates the entry and falls back to the original callable.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import Any, Callable

from .reuse import _bytes_view, _key, _storage, _tensors, _unchanged


def residency_safe(fn: Callable) -> Callable:
    """Declare that a materialization result may be reused read-only."""
    fn.scar_residency_safe = True
    return fn


@dataclass
class PersistentResidency:
    fn: Callable
    target_device: str | None = None
    max_entries: int = 128
    max_bytes: int = 256 * 1024 * 1024
    cache: dict = field(init=False, repr=False)
    hits: int = field(init=False, default=0)
    misses: int = field(init=False, default=0)
    retained_bytes: int = field(init=False, default=0)
    last_fallback: str | None = field(init=False, default=None)
    guard_kind: str = field(init=False, default="source_and_resident_bitwise_snapshot")

    def __post_init__(self):
        if self.max_entries < 1 or self.max_bytes < 1:
            raise ValueError("entry and byte limits must be positive")
        self.cache: dict[Any, tuple[list[Any], Any, list[Any], list[Any], int]] = {}
        self.hits = 0
        self.misses = 0
        self.retained_bytes = 0
        self.last_fallback: str | None = None
        self.guard_kind = "source_and_resident_bitwise_snapshot"

    def _fallback(self, args, kwargs, reason):
        self.misses += 1
        self.last_fallback = reason
        return self.fn(*args, **kwargs)

    def __call__(self, *args, **kwargs):
        import torch
        if not getattr(self.fn, "scar_residency_safe", False):
            return self._fallback(args, kwargs, "missing residency contract")
        if torch.is_grad_enabled():
            return self._fallback(args, kwargs, "gradients enabled")
        try:
            sources = list(_tensors((args, kwargs)))
            if not sources or any(t.requires_grad for t in sources):
                return self._fallback(args, kwargs, "no suitable source or gradient-bearing input")
            key = _key((args, kwargs))
            source_snapshots = [_bytes_view(t).clone() for t in sources]
        except (TypeError, RuntimeError, RecursionError):
            return self._fallback(args, kwargs, "source guard unavailable")

        entry = self.cache.get(key)
        if entry is not None:
            old_sources, resident, resident_tensors, resident_snapshots, _size = entry
            try:
                if (_unchanged(sources, old_sources) and
                        _unchanged(resident_tensors, resident_snapshots)):
                    self.hits += 1
                    return resident
            except (RuntimeError, TypeError):
                pass
            self.last_fallback = "source or resident snapshot changed"
            self.retained_bytes -= entry[-1]
            self.cache.pop(key, None)

        self.misses += 1
        result = self.fn(*args, **kwargs)
        try:
            residents = list(_tensors(result))
            if not residents:
                self.last_fallback = "materialization returned no Tensor"
                return result
            if self.target_device is not None:
                target = torch.device(self.target_device)
                if target.index is None:
                    on_target = all(t.device.type == target.type for t in residents)
                else:
                    on_target = all(t.device == target for t in residents)
            else:
                on_target = True
            if not on_target:
                self.last_fallback = "result is not on the requested target device"
                return result
            source_storages = {_storage(t) for t in sources}
            if source_storages.intersection(_storage(t) for t in residents):
                self.last_fallback = "resident result aliases source storage"
                return result
            if any(t.requires_grad for t in residents):
                self.last_fallback = "resident result carries gradients"
                return result
            resident_snapshots = [_bytes_view(t).clone() for t in residents]
            retained = (sum(snapshot.numel() for snapshot in source_snapshots) +
                        sum(snapshot.numel() for snapshot in resident_snapshots))
        except (TypeError, RuntimeError, RecursionError):
            self.last_fallback = "resident guard unavailable"
            return result

        if retained > self.max_bytes:
            self.last_fallback = "entry exceeds residency byte budget"
            return result
        while self.cache and (len(self.cache) >= self.max_entries or
                              self.retained_bytes + retained > self.max_bytes):
            _old_key, old_entry = self.cache.popitem()
            self.retained_bytes -= old_entry[-1]
        # Keep the original resident object. Returning it is the point of this
        # backend; the read-only contract and resident snapshot guard protect
        # it from silently serving a value changed by a caller.
        self.cache[key] = (source_snapshots, result, residents,
                           resident_snapshots, retained)
        self.retained_bytes += retained
        return result

    def clear(self):
        self.cache.clear()
        self.retained_bytes = 0


def persistent_residency(fn: Callable | None = None, *, target_device: str | None = None,
                         max_entries: int = 128,
                         max_bytes: int = 256 * 1024 * 1024):
    if fn is None:
        return lambda f: persistent_residency(
            f, target_device=target_device, max_entries=max_entries,
            max_bytes=max_bytes)
    wrapped = PersistentResidency(fn, target_device, max_entries, max_bytes)
    functools.update_wrapper(wrapped, fn)
    return wrapped


__all__ = ["PersistentResidency", "persistent_residency", "residency_safe"]
