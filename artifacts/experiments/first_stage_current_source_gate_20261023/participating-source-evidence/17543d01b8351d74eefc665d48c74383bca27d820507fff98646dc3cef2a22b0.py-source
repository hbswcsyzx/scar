"""Thin native-port declarations and unproved cross-representation obligations.

Actual arguments, producers, value types and state remain exclusively in the
canonical core. Raw roles and artifact references are not interpreted here.
In particular, Export call_spec trees need not include lifted inputs, mutation
outputs or other flat graph slots. A tree reference establishes no leaf mapping.
Auxiliary artifacts are allowed; their relationship to the provider's primary
artifact is not verified by constructing these records.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from scar.ir.program.ids import (
    BoundaryRelationID, NativeBoundaryID, ProviderID, RegionID, ValueID,
)
from scar.ir.program.providers import ProviderCondition, ProviderFactReference


def _exact(value, expected, name):
    if type(value) is not expected:
        raise TypeError(f"{name} must be {expected.__name__}")


def _text(value, name):
    _exact(value, str, name)
    if not value:
        raise ValueError(f"{name} must be nonempty")


def _nonnegative(value, name):
    _exact(value, int, name)
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _record(value, expected, name):
    _exact(value, expected, name)
    value.__post_init__()


def _records(value, expected, name):
    _exact(value, tuple, name)
    for item in value:
        _record(item, expected, name + " item")


@dataclass(frozen=True, slots=True)
class EntryPortRef:
    region: RegionID
    value: ValueID

    def __post_init__(self):
        _exact(self.region, RegionID, "entry port region")
        _exact(self.value, ValueID, "entry port value")


@dataclass(frozen=True, slots=True)
class ExitPortRef:
    region: RegionID
    exit_name: str
    index: int

    def __post_init__(self):
        _exact(self.region, RegionID, "exit port region")
        _text(self.exit_name, "exit port name")
        _nonnegative(self.index, "exit port index")


@dataclass(frozen=True, slots=True)
class NativeInputSlot:
    position: int
    role: str
    evidence: ProviderFactReference
    port: EntryPortRef

    def __post_init__(self):
        _nonnegative(self.position, "native input position")
        _text(self.role, "native input raw role")
        _record(self.evidence, ProviderFactReference, "native input evidence")
        _record(self.port, EntryPortRef, "native input port")


@dataclass(frozen=True, slots=True)
class NativeOutputSlot:
    position: int
    role: str
    evidence: ProviderFactReference
    port: ExitPortRef

    def __post_init__(self):
        _nonnegative(self.position, "native output position")
        _text(self.role, "native output raw role")
        _record(self.evidence, ProviderFactReference, "native output evidence")
        _record(self.port, ExitPortRef, "native output port")


@dataclass(frozen=True, slots=True)
class CoreInputPort:
    port: EntryPortRef
    reason: str

    def __post_init__(self):
        _record(self.port, EntryPortRef, "core-only input port")
        _text(self.reason, "core-only input reason")


@dataclass(frozen=True, slots=True)
class CoreOutputPort:
    port: ExitPortRef
    reason: str

    def __post_init__(self):
        _record(self.port, ExitPortRef, "core-only output port")
        _text(self.reason, "core-only output reason")


@dataclass(frozen=True, slots=True)
class NativeBoundary:
    """A declared flat signature over canonical ports, not artifact replay.

    Slot order is native signature order, independent of core physical order.
    Region ownership and the native/core-only complete disjoint partition need
    graph validation. State and mutation-role semantics are not inferred here.
    """

    id: NativeBoundaryID
    provider: ProviderID
    region: RegionID
    signature: ProviderFactReference
    input_tree: ProviderFactReference | None
    output_tree: ProviderFactReference | None
    inputs: tuple[NativeInputSlot, ...]
    outputs: tuple[NativeOutputSlot, ...]
    core_inputs: tuple[CoreInputPort, ...]
    core_outputs: tuple[CoreOutputPort, ...]

    def __post_init__(self):
        _exact(self.id, NativeBoundaryID, "native boundary id")
        _exact(self.provider, ProviderID, "native boundary provider")
        _exact(self.region, RegionID, "native boundary region")
        _record(self.signature, ProviderFactReference, "native boundary signature")
        for name in ("input_tree", "output_tree"):
            if getattr(self, name) is not None:
                _record(getattr(self, name), ProviderFactReference, "native boundary " + name)
        _records(self.inputs, NativeInputSlot, "native inputs")
        _records(self.outputs, NativeOutputSlot, "native outputs")
        _records(self.core_inputs, CoreInputPort, "core-only inputs")
        _records(self.core_outputs, CoreOutputPort, "core-only outputs")
        for name in ("inputs", "outputs"):
            if tuple(slot.position for slot in getattr(self, name)) != tuple(range(len(getattr(self, name)))):
                raise ValueError(f"native {name} positions must be ordered consecutively from zero")


@dataclass(frozen=True, slots=True)
class BoundaryPortPair:
    left: EntryPortRef | ExitPortRef
    right: EntryPortRef | ExitPortRef
    evidence: ProviderFactReference

    def __post_init__(self):
        if type(self.left) not in (EntryPortRef, ExitPortRef):
            raise TypeError("boundary pair left port must be exact EntryPortRef or ExitPortRef")
        _record(self.left, type(self.left), "boundary pair left port")
        _record(self.right, type(self.left), "boundary pair right port")
        _record(self.evidence, ProviderFactReference, "boundary pair evidence")


class BoundaryDomain(str, Enum):
    NUMERICS = "NUMERICS"
    STATE_WRITES = "STATE_WRITES"
    ALIAS_IDENTITY_LIFETIME = "ALIAS_IDENTITY_LIFETIME"
    AUTOGRAD = "AUTOGRAD"
    RNG_MODES = "RNG_MODES"
    COMPLETION_EXCEPTIONS = "COMPLETION_EXCEPTIONS"
    EXTERNAL_HISTORY = "EXTERNAL_HISTORY"
    RESOURCE_ORDER_READY = "RESOURCE_ORDER_READY"


@dataclass(frozen=True, slots=True)
class BoundaryObligation:
    """An always-unproved obligation; evidence supplies context, not discharge."""

    domain: BoundaryDomain
    reason: str
    evidence: ProviderFactReference | None

    def __post_init__(self):
        _exact(self.domain, BoundaryDomain, "boundary obligation domain")
        _text(self.reason, "boundary obligation reason")
        if self.evidence is not None:
            _record(self.evidence, ProviderFactReference, "boundary obligation evidence")


@dataclass(frozen=True, slots=True)
class BoundaryRelation:
    """Partial/many-to-many declared correspondence, never equivalence authority."""

    id: BoundaryRelationID
    left: NativeBoundaryID
    right: NativeBoundaryID
    ports: tuple[BoundaryPortPair, ...]
    conditions: tuple[ProviderCondition, ...]
    obligations: tuple[BoundaryObligation, ...]
    rule: ProviderFactReference

    def __post_init__(self):
        _exact(self.id, BoundaryRelationID, "boundary relation id")
        _exact(self.left, NativeBoundaryID, "boundary relation left id")
        _exact(self.right, NativeBoundaryID, "boundary relation right id")
        if self.left == self.right:
            raise ValueError("boundary relation needs distinct boundary IDs")
        _records(self.ports, BoundaryPortPair, "boundary relation ports")
        endpoints = tuple((pair.left, pair.right) for pair in self.ports)
        if len(set(endpoints)) != len(endpoints):
            raise ValueError("boundary relation must not repeat a port pair")
        _records(self.conditions, ProviderCondition, "boundary relation conditions")
        _records(self.obligations, BoundaryObligation, "boundary relation obligations")
        if (len(self.obligations) != len(BoundaryDomain)
                or {item.domain for item in self.obligations} != set(BoundaryDomain)):
            raise ValueError("boundary relation needs exactly one obligation for every domain")
        _record(self.rule, ProviderFactReference, "boundary relation rule")


__all__ = [
    "BoundaryDomain", "BoundaryObligation", "BoundaryPortPair", "BoundaryRelation",
    "CoreInputPort", "CoreOutputPort", "EntryPortRef", "ExitPortRef", "NativeBoundary",
    "NativeInputSlot", "NativeOutputSlot",
]
