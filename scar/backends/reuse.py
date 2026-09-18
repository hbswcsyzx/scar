"""Exact, guarded reuse backend for explicitly proven pure-like callables."""
from __future__ import annotations

import copy
import functools
import struct
from dataclasses import dataclass
from typing import Any, Callable


_MODULE_INTERNAL_STATE = frozenset({
    "training", "_parameters", "_buffers", "_non_persistent_buffers_set",
    "_backward_pre_hooks", "_backward_hooks", "_is_full_backward_hook",
    "_forward_hooks", "_forward_hooks_with_kwargs", "_forward_hooks_always_called",
    "_forward_pre_hooks", "_forward_pre_hooks_with_kwargs", "_state_dict_hooks",
    "_state_dict_pre_hooks", "_load_state_dict_pre_hooks",
    "_load_state_dict_post_hooks", "_modules", "_compiled_call_impl",
})


def pure(fn: Callable) -> Callable:
    """Declare a contract that the detector can use as evidence.

    The annotation does not make an impure function pure; validation and
    runtime guards still apply. It is useful for a user-owned region whose
    effects have been reviewed.
    """
    fn.scar_pure = True
    return fn


def _key(value):
    import torch
    if type(value) is dict:
        if any(type(k) not in (str, bytes, int, float, bool, type(None)) for k in value):
            raise TypeError("mutable or opaque dictionary key")
        return ("dict", tuple((_key(k), _key(v)) for k, v in value.items()))
    if type(value) in (tuple, list):
        return (type(value).__name__, tuple(_key(v) for v in value))
    if type(value) in (torch.Tensor, torch.nn.Parameter):
        if value.layout != torch.strided or value.is_quantized or value.device.type not in {"cpu", "cuda"}:
            raise TypeError("unsupported tensor representation")
        # SCAR's own storage/logical token is the default guard.  A caller may
        # provide ``scar_version`` when it has a stronger application-level
        # invalidation source.  Tensor._version is intentionally not used.
        version = getattr(value, "scar_version", None)
        if version is None:
            from scar.ir import storage_version
            version = storage_version(value)
        return ("tensor", version, int(value.data_ptr()), tuple(value.shape),
                tuple(value.stride()), str(value.dtype), str(value.device),
                value.is_conj(), value.is_neg())
    if type(value) is float:
        return ("float", struct.pack("!d", value))
    if type(value) in (str, bytes, int, bool, type(None)):
        return (type(value).__qualname__, value)
    raise TypeError("opaque values require a separate contract and guard")


def _tensors(value):
    import torch
    if isinstance(value, torch.Tensor):
        yield value
    elif type(value) in (tuple, list):
        for item in value:
            yield from _tensors(item)
    elif type(value) is dict:
        for key, item in value.items():
            yield from _tensors(key)
            yield from _tensors(item)


def _bytes_view(tensor):
    # Bitwise equality preserves signed zero and NaN payloads. torch.equal on
    # floating values alone would equate +0 and -0 despite different results
    # for e.g. reciprocal. This also catches writes outside Torch dispatch.
    import torch
    return tensor.detach().resolve_conj().resolve_neg().contiguous().reshape(-1).view(torch.uint8)


_QUICK_SAMPLE_ELEMENTS = 8


def _quick_fingerprint(tensor, sample_elements: int = _QUICK_SAMPLE_ELEMENTS):
    """Return a cheap guard before a retained byte snapshot is consulted.

    The guard deliberately records metadata and only a tiny logical prefix.
    It never retains a per-iteration copy of the tensor.  If this fingerprint
    matches the cache entry, ``_guard_matches`` performs the exact byte check
    against the one snapshot retained for that entry.  This two-stage design
    catches foreign writes (for example NumPy aliases) without making a full
    device-to-host copy on every call.
    """
    import torch
    if not isinstance(tensor, torch.Tensor):
        raise TypeError("quick fingerprint requires a tensor")
    shape = tuple(int(x) for x in tensor.shape)
    metadata = (shape, tuple(int(x) for x in tensor.stride()),
                int(tensor.storage_offset()), str(tensor.dtype),
                str(tensor.device), bool(tensor.is_conj()), bool(tensor.is_neg()))
    if tensor.numel() == 0 or sample_elements <= 0:
        sample = b""
    else:
        count = min(int(tensor.numel()), int(sample_elements))
        # ``reshape`` is zero-copy for the common contiguous case.  For a
        # view, gather at most eight logical elements rather than materializing
        # the entire view.
        if tensor.is_contiguous():
            values = tensor.detach().reshape(-1)[:count]
        else:
            coordinates = []
            for flat in range(count):
                remainder = flat
                coordinate = [0] * tensor.ndim
                for axis in range(tensor.ndim - 1, -1, -1):
                    extent = int(tensor.shape[axis])
                    coordinate[axis] = remainder % extent if extent else 0
                    remainder //= extent if extent else 1
                coordinates.append(tuple(coordinate))
            values = torch.stack([tensor.detach()[coordinate] for coordinate in coordinates])
        sample = bytes(_bytes_view(values).detach().cpu().tolist())
    return metadata + (sample,)


def _guard_matches(tensors, quick_guards, snapshots) -> bool:
    """Use the expensive exact check only after quick guards agree."""
    if len(tensors) != len(quick_guards) or len(tensors) != len(snapshots):
        return False
    try:
        if any(_quick_fingerprint(tensor) != guard
               for tensor, guard in zip(tensors, quick_guards)):
            return False
    except (RuntimeError, TypeError, ValueError):
        return False
    return _unchanged(tensors, snapshots)


def _unchanged(tensors, snapshots):
    import torch
    return len(tensors) == len(snapshots) and all(
        torch.equal(_bytes_view(tensor), snapshot)
        for tensor, snapshot in zip(tensors, snapshots))


def _storage(tensor):
    return str(tensor.device), int(tensor.untyped_storage()._cdata)


def _container_ids(value):
    if type(value) in (tuple, list, dict):
        yield id(value)
        children = value.values() if type(value) is dict else value
        for child in children:
            yield from _container_ids(child)


def _copyable_output(result, inputs):
    try:
        _key(result)  # Reject unsupported custom objects before copying them.
    except (TypeError, RuntimeError, RecursionError):
        return False
    input_storages = {_storage(t) for t in _tensors(inputs)}
    if any(not t.is_contiguous() or t.is_conj() or t.is_neg() for t in _tensors(result)):
        return False
    output_storages = [_storage(t) for t in _tensors(result)]
    if input_storages.intersection(output_storages) or len(output_storages) != len(set(output_storages)):
        return False
    containers = list(_container_ids(result))
    return not set(containers).intersection(_container_ids(inputs)) and len(containers) == len(set(containers))


def _safe_copy(value):
    """Copy independent outputs while preserving inference-tensor status."""
    import torch
    if isinstance(value, torch.Tensor):
        with torch.inference_mode(value.is_inference()):
            return value.detach().clone()
    if isinstance(value, tuple):
        return tuple(_safe_copy(x) for x in value)
    if isinstance(value, list):
        return [_safe_copy(x) for x in value]
    if isinstance(value, dict):
        return {k: _safe_copy(v) for k, v in value.items()}
    return copy.deepcopy(value)


def _equal_value(left, right) -> bool:
    """Compare cached and probe outputs without weakening tensor semantics."""
    import torch
    if isinstance(left, torch.Tensor) and isinstance(right, torch.Tensor):
        try:
            return (left.shape == right.shape and left.dtype == right.dtype
                    and left.device == right.device
                    and torch.equal(_bytes_view(left), _bytes_view(right)))
        except (RuntimeError, TypeError):
            return False
    if type(left) is not type(right):
        return False
    if type(left) in (tuple, list):
        return len(left) == len(right) and all(_equal_value(a, b) for a, b in zip(left, right))
    if type(left) is dict:
        return (list(left.keys()) == list(right.keys())
                and all(_equal_value(left[key], right[key]) for key in left))
    return left == right


def _module_state(module):
    """Return registered and custom module state consumed by the strict key."""
    modules = tuple(module.modules())
    custom = []
    for module_name, child in module.named_modules():
        attributes = tuple(
            (name, value) for name, value in sorted(child.__dict__.items())
            if name not in _MODULE_INTERNAL_STATE
        )
        custom.append((module_name, attributes))
    return (tuple(module.named_parameters()), tuple(module.named_buffers()),
            tuple(child.training for child in modules), tuple(custom))


def _rng_fingerprint(tensors):
    """Fingerprint CPU and relevant CUDA RNG states for strict reuse."""
    import torch

    cpu = bytes(torch.random.get_rng_state().tolist())
    cuda_devices = sorted({
        int(tensor.device.index if tensor.device.index is not None
            else torch.cuda.current_device())
        for tensor in tensors if tensor.device.type == "cuda"
    })
    cuda = tuple((device, bytes(torch.cuda.get_rng_state(device).tolist()))
                 for device in cuda_devices)
    return cpu, cuda


@dataclass
class ExactReuse:
    fn: Callable
    max_entries: int = 128
    max_bytes: int = 256 * 1024 * 1024
    # A reviewed library contract may authorize reuse without a user-level
    # ``scar_pure`` annotation.  This flag is never enabled by the ordinary
    # ``exact_reuse`` decorator; the runtime optimizer supplies the contract.
    allow_inferred: bool = False
    # Runtime hooks must invoke the original implementation directly to avoid
    # recursively entering the hook that owns this wrapper.
    invoke: Callable[..., Any] | None = None
    # Inferred runtime contracts validate the first repeated key by executing
    # the original once and comparing its value/effects.  This supplies a
    # steady-state cost sample and catches deterministic-contract violations.
    validate_once: bool = False
    validate_repeats: int = 1
    # Keep one module-state snapshot per wrapper instead of duplicating large
    # parameter/buffer byte copies in every cache entry.  This is used by the
    # inferred PyTorch contract; explicit user contracts retain the stricter
    # per-entry representation by default.
    deduplicate_state_snapshots: bool = False
    # ``bytes`` is the strict default. The inferred PyTorch contract can use
    # SCAR's own storage epochs after its write observer is installed.
    state_guard: str = "bytes"

    def __post_init__(self):
        if self.max_entries < 1 or self.max_bytes < 1:
            raise ValueError("cache entry and byte limits must be positive")
        if self.validate_repeats < 1:
            raise ValueError("validate_repeats must be positive")
        self.cache: dict[Any, Any] = {}
        self.hits = 0
        self.misses = 0
        self.retained_bytes = 0
        self.guard_kind = "bitwise_input+module_state+rng_snapshot"
        self.last_fallback = None
        self.probed_keys: set[Any] = set()
        self.validated_probes = 0
        self.last_probe_compute_ns = 0
        self.state_snapshots: list[Any] | None = None
        self.last_call_kind = "fallback"
        self.quick_guard_checks = 0
        self.deep_guard_checks = 0
        self.quick_guard_rejects = 0

    def _fallback(self, args, kwargs, reason):
        self.misses += 1
        self.last_fallback = reason
        self.last_call_kind = "fallback"
        return self._invoke(args, kwargs)

    def _invoke(self, args, kwargs):
        if self.invoke is not None:
            return self.invoke(*args, **kwargs)
        return self.fn(*args, **kwargs)

    def __call__(self, *args, **kwargs):
        import torch
        # Exact reuse is opt-in.  Without an explicit contract annotation we
        # cannot prove hidden state, RNG, callbacks, exceptions, or external
        # effects, so the original execution is the safe no-op backend.
        if (not (getattr(self.fn, "scar_pure", False) or self.allow_inferred)
                or torch.is_grad_enabled()):
            return self._fallback(args, kwargs, "missing purity contract or gradients enabled")
        try:
            _key((args, kwargs))
            if any(t.requires_grad for t in _tensors((args, kwargs))):
                return self._fallback(args, kwargs, "gradient-bearing input")
        except (TypeError, RuntimeError, RecursionError):
            return self._fallback(args, kwargs, "input guard unavailable")
        state = ()
        if isinstance(self.fn, torch.nn.Module):
            hook_state = torch.nn.modules.module
            if any(getattr(hook_state, name, {}) for name in
                   ("_global_forward_hooks", "_global_forward_pre_hooks", "_global_backward_hooks")):
                return self._fallback(args, kwargs, "global module hooks are outside the reuse contract")
            modules = tuple(torch.nn.Module.modules(self.fn))
            if any(m._forward_hooks or m._forward_pre_hooks or m._backward_hooks for m in modules):
                return self._fallback(args, kwargs, "module hooks are outside the reuse contract")
            state = _module_state(self.fn)
        try:
            state_tensors = list(_tensors((args, kwargs, state)))
            rng = _rng_fingerprint(state_tensors)
            inputs = (args, kwargs, state, rng)
            key = _key(inputs)
            if self.deduplicate_state_snapshots and isinstance(self.fn, torch.nn.Module):
                module_state_tensors = list(_tensors(state))
                if self.state_guard == "version":
                    from scar.ir import storage_version
                    current_state_snapshots = [storage_version(tensor)
                                               for tensor in module_state_tensors]
                    unchanged = (self.state_snapshots is None
                                 or current_state_snapshots == self.state_snapshots)
                else:
                    current_state_snapshots = [
                        _bytes_view(tensor).clone() for tensor in module_state_tensors]
                    unchanged = (self.state_snapshots is None
                                 or _unchanged(module_state_tensors, self.state_snapshots))
                if (self.state_snapshots is not None
                        and not unchanged):
                    self.clear()
                    self.last_fallback = "module state changed; cache invalidated"
                self.state_snapshots = current_state_snapshots
                # RNG is represented by immutable bytes in ``key`` and does
                # not belong in the byte snapshot list. Only dynamic inputs
                # are retained with each output entry.
                tensors = list(_tensors((args, kwargs)))
            else:
                tensors = list(_tensors(inputs))
            quick_guards = [_quick_fingerprint(tensor) for tensor in tensors]
            entry = self.cache.get(key)
            if entry is not None:
                self.quick_guard_checks += 1
            if entry is not None and _guard_matches(tensors, entry[0], entry[1]):
                self.deep_guard_checks += 1
                if self.validate_once and key not in self.probed_keys:
                    self.probed_keys.add(key)
                    probe_result = None
                    probe_durations = []
                    for _ in range(self.validate_repeats):
                        probe_started = __import__("time").perf_counter_ns()
                        probe_result = self._invoke(args, kwargs)
                        probe_durations.append(__import__("time").perf_counter_ns() - probe_started)
                        try:
                            state_after = (_module_state(self.fn)
                                           if isinstance(self.fn, torch.nn.Module) else ())
                            rng_after = _rng_fingerprint(
                                list(_tensors((args, kwargs, state_after))))
                            probe_key = _key((args, kwargs, state_after, rng_after))
                        except (TypeError, RuntimeError, RecursionError):
                            probe_key = None
                        if (probe_key != key or not _guard_matches(tensors, entry[0], entry[1])
                                or not _equal_value(probe_result, entry[2])):
                            self.clear()
                            self.last_fallback = "repeated probe changed effects or output"
                            self.last_call_kind = "probe_failed"
                            return probe_result
                    self.last_probe_compute_ns = min(probe_durations)
                    self.validated_probes += 1
                    self.last_call_kind = "probe"
                    # Return the freshly computed value for the probe. Future
                    # calls may use the cached copy after validation.
                    return probe_result
                self.hits += 1
                self.last_call_kind = "hit"
                return _safe_copy(entry[2])
            elif entry is not None:
                self.quick_guard_rejects += 1
            snapshots = [_bytes_view(tensor).clone() for tensor in tensors]
        except (TypeError, RuntimeError, RecursionError):
            return self._fallback(args, kwargs, "input guard unavailable")
        self.misses += 1
        self.last_call_kind = "miss"
        result = self._invoke(args, kwargs)
        try:
            state_after = _module_state(self.fn) if isinstance(self.fn, torch.nn.Module) else ()
            rng_after = _rng_fingerprint(list(_tensors((args, kwargs, state_after))))
            post_key = _key((args, kwargs, state_after, rng_after))
        except (TypeError, RuntimeError, RecursionError):
            post_key = None
        if (post_key != key or not _guard_matches(tensors, quick_guards, snapshots)
                or not _copyable_output(result, inputs)):
            self.clear()
            self.last_fallback = (
                "input, module state, RNG, or output alias/representation contract not satisfied")
            return result
        size = sum(t.numel() * t.element_size() for t in snapshots)
        size += sum(t.numel() * t.element_size() for t in _tensors(result))
        if key in self.cache:
            self.retained_bytes -= self.cache.pop(key)[3]
        if size > self.max_bytes:
            self.last_fallback = "entry exceeds cache byte budget"
            return result
        while self.cache and (len(self.cache) >= self.max_entries or self.retained_bytes + size > self.max_bytes):
            self.retained_bytes -= self.cache.pop(next(iter(self.cache)))[3]
        self.cache[key] = (quick_guards, snapshots, _safe_copy(result), size)
        self.retained_bytes += size
        return result

    def clear(self):
        self.cache.clear()
        self.retained_bytes = 0
        self.probed_keys.clear()


def exact_reuse(fn: Callable | None = None, *, max_entries: int = 128,
                max_bytes: int = 256 * 1024 * 1024):
    if fn is None:
        return lambda f: exact_reuse(f, max_entries=max_entries, max_bytes=max_bytes)
    wrapped = ExactReuse(fn, max_entries=max_entries, max_bytes=max_bytes)
    functools.update_wrapper(wrapped, fn)
    return wrapped


def inferred_exact_reuse(fn: Callable, invoke: Callable[..., Any], *,
                         max_entries: int = 128,
                         max_bytes: int = 256 * 1024 * 1024) -> ExactReuse:
    """Create a wrapper for a separately reviewed library purity contract.

    This helper is intentionally not part of the user-facing decorator path:
    arbitrary Python functions remain opt-in through :func:`pure`.
    """
    return ExactReuse(fn, max_entries=max_entries, max_bytes=max_bytes,
                      allow_inferred=True, invoke=invoke, validate_once=True,
                      validate_repeats=2,
                      deduplicate_state_snapshots=True, state_guard="version")


__all__ = ["ExactReuse", "exact_reuse", "inferred_exact_reuse", "pure"]
