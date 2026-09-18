"""Typed identities for the SCAR IR v2.

The types are deliberately small and serializable.  A typed ID prevents a
storage allocation, a logical value and an operation instance from being
accidentally used as the same identity merely because both are strings.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class Identifier:
    value: str
    prefix: ClassVar[str] = "id"

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value:
            raise ValueError("identifier value must be a non-empty string")

    @property
    def wire(self) -> str:
        return f"{self.prefix}:{self.value}"

    def __str__(self) -> str:
        return self.wire

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.prefix, "value": self.value, "wire": self.wire}


class LogicalValueID(Identifier):
    prefix = "lv"


class ProvenanceID(Identifier):
    prefix = "prov"


class ObjectID(Identifier):
    prefix = "object"


class StorageAllocationID(Identifier):
    prefix = "alloc"


class StorageRegionID(Identifier):
    prefix = "region"


class MaterializationID(Identifier):
    prefix = "mat"


class OperationDefinitionID(Identifier):
    prefix = "opdef"


class OperationInstanceID(Identifier):
    prefix = "opinst"


class ControlRegionID(Identifier):
    prefix = "ctrl"


class OptimizationRegionID(Identifier):
    prefix = "optregion"


@dataclass(frozen=True, slots=True)
class ValueVersionID:
    """A semantic version independent of object identity and storage."""

    logical_value: LogicalValueID
    version: int

    def __post_init__(self) -> None:
        if not isinstance(self.logical_value, LogicalValueID):
            raise TypeError("logical_value must be LogicalValueID")
        if not isinstance(self.version, int) or self.version < 0:
            raise ValueError("version must be a non-negative integer")

    @property
    def wire(self) -> str:
        return f"{self.logical_value.wire}@v{self.version}"

    def as_dict(self) -> dict:
        return {
            "logical_value": self.logical_value.as_dict(),
            "version": self.version,
            "wire": self.wire,
        }


__all__ = [
    "Identifier", "LogicalValueID", "ProvenanceID", "ObjectID",
    "StorageAllocationID", "StorageRegionID", "MaterializationID",
    "OperationDefinitionID", "OperationInstanceID", "ControlRegionID",
    "OptimizationRegionID", "ValueVersionID",
]
