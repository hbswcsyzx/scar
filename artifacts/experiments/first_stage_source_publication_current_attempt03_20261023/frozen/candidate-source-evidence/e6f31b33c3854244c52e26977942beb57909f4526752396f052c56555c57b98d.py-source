"""SCAR-owned storage and logical epochs.

The registry is deliberately independent of ``Tensor._version``.  Runtime
observers call :func:`mark_storage_write` when a write is known; backends use
the resulting token as an invalidation guard.  A changed allocator token
starts a new storage epoch, so pointer reuse cannot resurrect an old value.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StorageVersionRegistry:
    storage_tokens: dict[int, int] = field(default_factory=dict)
    storage_epochs: dict[int, int] = field(default_factory=dict)
    logical_epochs: dict[tuple[int, int], int] = field(default_factory=dict)
    # ptr -> (allocation byte size, allocator token).  This lets an external
    # NumPy view identify a tensor allocation by an interior data pointer.
    storage_spans: dict[int, tuple[int, int]] = field(default_factory=dict)

    @staticmethod
    def _identity(value) -> tuple[int, int]:
        if hasattr(value, "untyped_storage"):
            storage = value.untyped_storage()
            ptr = int(storage.data_ptr())
            token = int(getattr(storage, "_cdata", ptr))
            return ptr, token
        interface = getattr(value, "__array_interface__", None)
        if interface is not None:
            data = interface.get("data", (0, False))
            ptr = int(data[0])
            # A NumPy array has no allocator epoch that SCAR can trust.  The
            # registry resolves it to a known tensor span when possible;
            # otherwise identity is intentionally conservative and local.
            base = getattr(value, "base", None)
            return ptr, id(base) if base is not None else id(value)
        raise TypeError("value has no tensor storage or array interface")

    @staticmethod
    def _nbytes(value) -> int:
        try:
            return int(value.untyped_storage().nbytes())
        except Exception:
            try:
                return int(value.nbytes)
            except Exception:
                return 0

    def _resolve_external_ptr(self, ptr: int) -> tuple[int, int] | None:
        for start, (size, token) in self.storage_spans.items():
            if start <= ptr < start + max(size, 1):
                return start, token
        return None

    def observe(self, value) -> tuple[int, int, int]:
        ptr, token = self._identity(value)
        if not hasattr(value, "untyped_storage"):
            resolved = self._resolve_external_ptr(ptr)
            if resolved is not None:
                ptr, token = resolved
        else:
            self.storage_spans[ptr] = (self._nbytes(value), token)
        previous = self.storage_tokens.get(ptr)
        if previous is not None and previous != token:
            self.storage_epochs[ptr] = self.storage_epochs.get(ptr, 0) + 1
        self.storage_tokens[ptr] = token
        epoch = self.storage_epochs.get(ptr, 0)
        logical = self.logical_epochs.get((ptr, epoch), 0)
        return ptr, epoch, logical

    def mark_write(self, value) -> tuple[int, int, int]:
        ptr, epoch, _ = self.observe(value)
        key = (ptr, epoch)
        self.logical_epochs[key] = self.logical_epochs.get(key, 0) + 1
        return ptr, epoch, self.logical_epochs[key]

    def mark_external_write(self, value) -> tuple[int, int, int]:
        """Advance a token after a write through a foreign buffer/view.

        This API is intentionally explicit: SCAR cannot infer arbitrary
        NumPy or ctypes writes merely by seeing memory.  Callers that know a
        foreign operation mutated a shared allocation can invalidate it
        without consulting ``Tensor._version``.
        """
        return self.mark_write(value)

    def token(self, value) -> str:
        ptr, epoch, logical = self.observe(value)
        return f"storage:{ptr:x}:e{epoch}:v{logical}"


_DEFAULT_REGISTRY = StorageVersionRegistry()


def storage_version(value) -> str:
    """Return the current SCAR version token for a tensor-like value."""
    return _DEFAULT_REGISTRY.token(value)


def mark_storage_write(value) -> str:
    """Advance the default registry after an observed in-place write."""
    ptr, epoch, logical = _DEFAULT_REGISTRY.mark_write(value)
    return f"storage:{ptr:x}:e{epoch}:v{logical}"


def mark_external_write(value) -> str:
    """Advance the default registry after an observed foreign-buffer write."""
    ptr, epoch, logical = _DEFAULT_REGISTRY.mark_external_write(value)
    return f"storage:{ptr:x}:e{epoch}:v{logical}"


def default_registry() -> StorageVersionRegistry:
    return _DEFAULT_REGISTRY
