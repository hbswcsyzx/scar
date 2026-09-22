"""Explicit, bounded, bitwise tensor checkpoints for at-time evidence.

The caller must exclude concurrent writes for enrollment/comparison. EXACT is
an observation about these captures, not proof of future stability, provenance,
purity, or valid reuse. Full payloads stay in owned CPU memory and are never
included in reports. Nothing reads Tensor._version.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import threading
import time
from typing import Any
import uuid

import torch


class ComparisonStatus(str, Enum):
    EXACT = "EXACT"
    DIFFERENT = "DIFFERENT"
    NEEDS_VERIFICATION = "NEEDS_VERIFICATION"


class CheckpointBudgetExceeded(ValueError):
    """Explicit enrollment exceeds the retained snapshot byte budget."""


class CheckpointUnsupported(ValueError):
    """The requested tensor or synchronization policy is unsupported."""


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    status: ComparisonStatus
    method: str
    duration_ns: int
    reason: str
    checked_bytes: int = 0
    synchronized_cuda: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status.value, "method": self.method,
                "duration_ns": self.duration_ns, "reason": self.reason,
                "checked_bytes": self.checked_bytes,
                "synchronized_cuda": self.synchronized_cuda}


@dataclass(slots=True)
class _Checkpoint:
    shape: tuple[int, ...]
    dtype: torch.dtype
    element_size: int
    numel: int
    payload: torch.Tensor
    enrollment_duration_ns: int


class CheckpointStore:
    """Enroll once, compare on demand, release explicitly.

    ``max_bytes`` bounds retained CPU payloads. Temporary work is chunked; it
    includes bounded index buffers for strided inputs and a CPU byte staging
    buffer, rather than a full per-comparison clone. Prefix equality only
    triggers full comparison. CUDA is disabled unless ``allow_cuda=True``;
    that opt-in includes device synchronization and all transfer time in cost.
    Byte limits describe tensor payloads, excluding allocator bookkeeping and
    cached device memory. Unsupported minimum working sets are rejected.
    """

    def __init__(self, max_bytes: int, prefix_elements: int = 8,
                 allow_cuda: bool = False, *, chunk_bytes: int = 64 * 1024,
                 max_entries: int = 1024):
        for name, value, minimum in (("max_bytes", max_bytes, 0),
                                     ("prefix_elements", prefix_elements, 0),
                                     ("chunk_bytes", chunk_bytes, 64),
                                     ("max_entries", max_entries, 1)):
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        if type(allow_cuda) is not bool:
            raise ValueError("allow_cuda must be bool")
        self.max_bytes = max_bytes
        self.prefix_elements = prefix_elements
        self.allow_cuda = allow_cuda
        self.chunk_bytes = chunk_bytes
        self.max_entries = max_entries
        self._checkpoints: dict[str, _Checkpoint] = {}
        self._namespace = uuid.uuid4().hex
        self._bytes = 0
        self._next_id = 0
        self._lock = threading.RLock()

    @property
    def bytes_used(self) -> int:
        with self._lock:
            return self._bytes

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._checkpoints)

    def describe(self, checkpoint_id: str) -> dict[str, Any]:
        """Describe retained evidence without returning payloads or tensors."""
        with self._lock:
            checkpoint = self._checkpoints[checkpoint_id]
            return {"checkpoint_id": checkpoint_id, "shape": list(checkpoint.shape),
                    "dtype": str(checkpoint.dtype), "nbytes": checkpoint.payload.numel(),
                    "enrollment_duration_ns": checkpoint.enrollment_duration_ns,
                    "storage_device": "cpu", "validity": "capture only; write exclusion required"}

    def _unsupported(self, tensor) -> str | None:
        # Tensor subclasses can intercept indexing/copy and perform arbitrary
        # stateful work; they need an explicit future collector contract.
        if type(tensor) not in (torch.Tensor, torch.nn.Parameter):
            return "requires an ordinary Tensor or Parameter"
        if tensor.layout is not torch.strided or tensor.is_quantized:
            return "sparse, non-strided and quantized tensors need verification"
        if tensor.device.type not in ("cpu", "cuda"):
            return f"device {tensor.device.type} needs verification"
        if tensor.device.type == "cuda" and not self.allow_cuda:
            return "CUDA checkpointing requires explicit allow_cuda=True synchronization"
        if tensor.is_conj() or tensor.is_neg():
            return "conjugate/negative view interpretation needs verification"
        return None

    def _chunk_elements(self, tensor) -> int:
        # Advanced indexing holds one coordinate vector per dimension; leave
        # room for the flat index, remainder and byte staging buffers too.
        bytes_per_element = tensor.element_size() * 2 + 8 * (tensor.ndim + 3)
        if bytes_per_element > self.chunk_bytes:
            raise CheckpointUnsupported("chunk budget is too small for one logical element and indexing buffers")
        return self.chunk_bytes // bytes_per_element

    @staticmethod
    def _chunk(tensor, start: int, stop: int) -> torch.Tensor:
        """Read a bounded interval in logical row-major order as CPU bytes."""
        source = tensor.detach()
        if source.is_contiguous():
            selected = source.view(-1)[start:stop]
        else:
            remaining = torch.arange(start, stop, dtype=torch.int64, device=source.device)
            coordinates = []
            for dimension in reversed(source.shape):
                coordinates.append(torch.remainder(remaining, dimension))
                remaining = torch.div(remaining, dimension, rounding_mode="floor")
            selected = source[tuple(reversed(coordinates))]
        # uint8 comparison preserves NaN payloads and signed zero. Only a
        # bounded gathered chunk is made contiguous for a strided input.
        bits = selected.contiguous().view(torch.uint8).reshape(-1)
        return bits.to(device="cpu", non_blocking=False)

    def enroll(self, tensor: torch.Tensor) -> str:
        """Store one independent checkpoint or raise without consuming budget."""
        started = time.perf_counter_ns()
        with self._lock, torch.no_grad():
            unsupported = self._unsupported(tensor)
            if unsupported:
                raise CheckpointUnsupported(unsupported)
            nbytes = tensor.numel() * tensor.element_size()
            if nbytes > self.max_bytes - self._bytes or len(self._checkpoints) >= self.max_entries:
                raise CheckpointBudgetExceeded("checkpoint payload/entry budget exceeded")
            step = self._chunk_elements(tensor)
            if tensor.device.type == "cuda":
                torch.cuda.synchronize(tensor.device)
            payload = torch.empty(nbytes, dtype=torch.uint8, device="cpu")
            try:
                for start in range(0, tensor.numel(), step):
                    stop = min(start + step, tensor.numel())
                    payload[start * tensor.element_size():stop * tensor.element_size()].copy_(
                        self._chunk(tensor, start, stop))
            except (RuntimeError, TypeError, NotImplementedError) as error:
                raise CheckpointUnsupported(f"bitwise capture unavailable: {error}") from error
            self._next_id += 1
            identifier = f"checkpoint:{self._namespace}:{self._next_id}"
            self._checkpoints[identifier] = _Checkpoint(
                tuple(tensor.shape), tensor.dtype, tensor.element_size(), tensor.numel(),
                payload, time.perf_counter_ns() - started)
            self._bytes += nbytes
            return identifier

    def compare(self, checkpoint_id: str, tensor: torch.Tensor) -> ComparisonResult:
        started = time.perf_counter_ns()
        checked, synchronized = 0, False

        def result(status, method, reason):
            return ComparisonResult(status, method, time.perf_counter_ns() - started,
                                    reason, checked, synchronized)

        with self._lock, torch.no_grad():
            checkpoint = self._checkpoints.get(checkpoint_id)
            if checkpoint is None:
                return result(ComparisonStatus.NEEDS_VERIFICATION, "unavailable", "checkpoint missing or released")
            unsupported = self._unsupported(tensor)
            if unsupported:
                return result(ComparisonStatus.NEEDS_VERIFICATION, "unavailable", unsupported)
            if tuple(tensor.shape) != checkpoint.shape or tensor.dtype != checkpoint.dtype:
                return result(ComparisonStatus.DIFFERENT, "shape_dtype", "shape or dtype changed")
            try:
                if tensor.device.type == "cuda":
                    torch.cuda.synchronize(tensor.device)
                    synchronized = True
                prefix = min(self.prefix_elements, checkpoint.numel, self._chunk_elements(tensor))
                if prefix:
                    captured = self._chunk(tensor, 0, prefix)
                    checked += captured.numel()
                    if not torch.equal(checkpoint.payload[:checked], captured):
                        return result(ComparisonStatus.DIFFERENT, "prefix", "bounded prefix differs")
                step = self._chunk_elements(tensor)
                for start in range(prefix, checkpoint.numel, step):
                    stop = min(start + step, checkpoint.numel)
                    captured = self._chunk(tensor, start, stop)
                    first, last = start * checkpoint.element_size, stop * checkpoint.element_size
                    checked += captured.numel()
                    if not torch.equal(checkpoint.payload[first:last], captured):
                        return result(ComparisonStatus.DIFFERENT, "bitwise_full", "full comparison found different bits")
            except (RuntimeError, TypeError, NotImplementedError, CheckpointUnsupported) as error:
                return result(ComparisonStatus.NEEDS_VERIFICATION, "unavailable", f"bitwise comparison unavailable: {error}")
            return result(ComparisonStatus.EXACT, "bitwise_full",
                          "all logical element bits match at comparison; future validity unproven")

    def release(self, checkpoint_id: str) -> bool:
        with self._lock:
            checkpoint = self._checkpoints.pop(checkpoint_id, None)
            if checkpoint is None:
                return False
            self._bytes -= checkpoint.payload.numel()
            return True


__all__ = ["CheckpointStore", "ComparisonResult", "ComparisonStatus",
           "CheckpointBudgetExceeded", "CheckpointUnsupported"]
