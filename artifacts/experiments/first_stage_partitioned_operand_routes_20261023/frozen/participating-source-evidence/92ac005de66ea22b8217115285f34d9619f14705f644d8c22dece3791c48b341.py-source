"""State and resource entities in the SCAR IR."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import product
from typing import Any, Literal

from .ids import LogicalVersion, ObjectID, StorageID


@dataclass(slots=True)
class Region:
    storage: StorageID
    offset: int
    shape: tuple[int, ...]
    strides: tuple[int, ...]
    dtype: str
    device: str
    logical_version: LogicalVersion

    def overlap(self, other: "Region", max_elements: int = 4096) -> Literal[
        "EXACT", "PARTIAL", "DISJOINT", "UNKNOWN"]:
        """Classify physical storage overlap conservatively.

        Small strided regions are expanded to element offsets, which handles
        views, slices, transposes, and zero-stride ``expand`` views.  Large
        regions use bounding intervals only to prove disjointness; an
        intersecting interval remains ``UNKNOWN`` rather than being called
        overlapping without enough evidence.
        """
        if self.storage != other.storage or self.device != other.device:
            return "DISJOINT"
        if self.dtype != other.dtype:
            return "UNKNOWN"
        left_count = _numel(self.shape)
        right_count = _numel(other.shape)
        if left_count == 0 or right_count == 0:
            return "DISJOINT"
        left_bounds = _bounds(self)
        right_bounds = _bounds(other)
        if left_bounds[1] < right_bounds[0] or right_bounds[1] < left_bounds[0]:
            return "DISJOINT"
        if left_count > max_elements or right_count > max_elements:
            return "UNKNOWN"
        left = _offsets(self)
        right = _offsets(other)
        if left == right:
            return "EXACT"
        return "PARTIAL" if left & right else "DISJOINT"

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["storage"] = asdict(self.storage)
        d["logical_version"] = asdict(self.logical_version)
        return d


def _numel(shape: tuple[int, ...]) -> int:
    result = 1
    for size in shape:
        if size <= 0:
            return 0
        result *= size
    return result


def _bounds(region: Region) -> tuple[int, int]:
    lo = hi = region.offset
    for size, stride in zip(region.shape, region.strides):
        if size <= 0:
            return (0, -1)
        end = (size - 1) * stride
        lo += min(0, end)
        hi += max(0, end)
    return lo, hi


def _offsets(region: Region) -> set[int]:
    if not region.shape:
        return {region.offset}
    return {
        region.offset + sum(index * stride for index, stride in zip(indices, region.strides))
        for indices in product(*(range(size) for size in region.shape))
    }


def classify_region_overlap(left: Region, right: Region) -> str:
    """Public convenience wrapper for alias analyses."""
    return left.overlap(right)


@dataclass(slots=True)
class Materialization:
    logical_version: LogicalVersion
    storage: StorageID
    device: str
    representation: str
    producer: str
    ready: str = "unknown"


@dataclass(slots=True)
class ObjectEntity:
    object_id: ObjectID
    type_name: str
    storage: StorageID | None = None
    regions: list[Region] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)


def tensor_entity(tensor, version: int = 0, storage_epoch: int = 0) -> ObjectEntity:
    """Extract metadata without using ``Tensor._version`` as a cache criterion.

    ``storage_epoch`` and ``version`` are supplied by the observer.  Keeping
    them outside PyTorch's private version counter lets a recorder account for
    writes that arrive through NumPy or other aliases.
    """
    try:
        ptr = int(tensor.untyped_storage().data_ptr())
        storage = StorageID(f"storage:{ptr:x}", int(storage_epoch))
        shape = tuple(int(x) for x in tensor.shape)
        strides = tuple(int(x) for x in tensor.stride())
        offset = int(tensor.storage_offset())
        dtype = str(tensor.dtype)
        device = str(tensor.device)
        region = Region(storage, offset, shape, strides, dtype, device,
                        LogicalVersion(f"{storage.value}@{storage.epoch}:v{version}"))
    except Exception:
        storage = None
        region = None
    return ObjectEntity(ObjectID.of(tensor), type(tensor).__qualname__, storage,
                        [] if region is None else [region])
