"""Address refinements attached to existing canonical state effects.

These immutable declarations do not add a state carrier or prove aliasing,
effect completeness, physical storage, or runtime/source correspondence.
Selectors point to the original operation's owned Uses.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from scar.ir.program.ids import OperationID, ResourceRequirementID, UseID
from scar.ir.program.providers import ProviderFactReference
from scar.ir.program.state_modes import AccessMode


def _exact(value, expected, name):
    if type(value) is not expected:
        raise TypeError(f"{name} must be {expected.__name__}")


def _record(value, expected, name):
    _exact(value, expected, name)
    value.__post_init__()


def _records(values, expected, name, *, nonempty=False):
    _exact(values, tuple, name)
    if nonempty and not values:
        raise ValueError(f"{name} must be nonempty")
    for value in values:
        _record(value, expected, name + " item")


def _text(value, name):
    _exact(value, str, name)
    if not value:
        raise ValueError(f"{name} must be nonempty")


def _index(value, name):
    _exact(value, int, name)
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


@dataclass(frozen=True, slots=True)
class ExistingAccess:
    operation: OperationID
    index: int

    def __post_init__(self):
        _exact(self.operation, OperationID, "state address access operation")
        _index(self.index, "state address access index")


@dataclass(frozen=True, slots=True)
class InvokeStateOperand:
    operation: OperationID
    state_use: UseID

    def __post_init__(self):
        _exact(self.operation, OperationID, "state address invoke operation")
        _exact(self.state_use, UseID, "state address invoke state Use")


StateAddressSite: TypeAlias = ExistingAccess | InvokeStateOperand


@dataclass(frozen=True, slots=True)
class DomainOwner:
    """The existing state domain, with no extra owner identity."""

    def __post_init__(self):
        return None


@dataclass(frozen=True, slots=True)
class ReferenceOwner:
    use: UseID

    def __post_init__(self):
        _exact(self.use, UseID, "address reference owner Use")


@dataclass(frozen=True, slots=True)
class ResourceOwner:
    requirement: ResourceRequirementID

    def __post_init__(self):
        _exact(self.requirement, ResourceRequirementID, "address resource requirement")


@dataclass(frozen=True, slots=True)
class UnknownOwner:
    reason: str
    operands: tuple[UseID, ...] = ()

    def __post_init__(self):
        _text(self.reason, "unknown address owner reason")
        _exact(self.operands, tuple, "unknown address owner operands")
        for item in self.operands:
            _exact(item, UseID, "unknown address owner operand")


AddressOwner: TypeAlias = DomainOwner | ReferenceOwner | ResourceOwner | UnknownOwner


@dataclass(frozen=True, slots=True)
class WholeOwner:
    def __post_init__(self):
        return None


@dataclass(frozen=True, slots=True)
class NamespaceKey:
    key: UseID

    def __post_init__(self):
        _exact(self.key, UseID, "namespace key Use")


@dataclass(frozen=True, slots=True)
class ObjectField:
    name: str

    def __post_init__(self):
        _text(self.name, "object field name")


@dataclass(frozen=True, slots=True)
class DynamicField:
    name: UseID

    def __post_init__(self):
        _exact(self.name, UseID, "dynamic field-name Use")


@dataclass(frozen=True, slots=True)
class CellContent:
    def __post_init__(self):
        return None


@dataclass(frozen=True, slots=True)
class Element:
    index: UseID

    def __post_init__(self):
        _exact(self.index, UseID, "element index Use")


@dataclass(frozen=True, slots=True)
class Slice:
    start: UseID | None = None
    stop: UseID | None = None
    step: UseID | None = None

    def __post_init__(self):
        for name in ("start", "stop", "step"):
            value = getattr(self, name)
            if value is not None:
                _exact(value, UseID, "slice " + name + " Use")


class AddressUnit(str, Enum):
    BYTE = "BYTE"
    ELEMENT = "ELEMENT"
    ABSTRACT = "ABSTRACT"


@dataclass(frozen=True, slots=True)
class StorageRange:
    unit: AddressUnit
    start: UseID
    count: UseID

    def __post_init__(self):
        _exact(self.unit, AddressUnit, "storage range unit")
        _exact(self.start, UseID, "storage range start Use")
        _exact(self.count, UseID, "storage range count Use")


@dataclass(frozen=True, slots=True)
class UnknownSelection:
    reason: str
    operands: tuple[UseID, ...] = ()

    def __post_init__(self):
        _text(self.reason, "unknown selection reason")
        _exact(self.operands, tuple, "unknown selection operands")
        for item in self.operands:
            _exact(item, UseID, "unknown selection operand")


AddressSelector: TypeAlias = (
    WholeOwner | NamespaceKey | ObjectField | DynamicField | CellContent | Element
    | Slice | StorageRange | UnknownSelection
)


@dataclass(frozen=True, slots=True)
class AddressEffect:
    owner: AddressOwner
    path: tuple[AddressSelector, ...]
    mode: AccessMode
    stage: int | None = None

    def __post_init__(self):
        owner_types = (DomainOwner, ReferenceOwner, ResourceOwner, UnknownOwner)
        if type(self.owner) not in owner_types:
            raise TypeError("address effect owner must be a typed address owner")
        self.owner.__post_init__()
        _exact(self.path, tuple, "address selector path")
        if not self.path:
            raise ValueError("address selector path must be nonempty")
        selector_types = (WholeOwner, NamespaceKey, ObjectField, DynamicField, CellContent,
                          Element, Slice, StorageRange, UnknownSelection)
        for selector in self.path:
            if type(selector) not in selector_types:
                raise TypeError("address path contains an invalid selector")
            selector.__post_init__()
        _exact(self.mode, AccessMode, "address effect mode")
        if self.stage is not None:
            _index(self.stage, "address effect stage")


class AddressCoverage(str, Enum):
    PARTIAL = "PARTIAL"
    DECLARED_COMPLETE = "DECLARED_COMPLETE"


@dataclass(frozen=True, slots=True)
class StateAddressRefinement:
    site: StateAddressSite
    effects: tuple[AddressEffect, ...]
    coverage: AddressCoverage
    protocol: ProviderFactReference | None = None

    def __post_init__(self):
        if type(self.site) not in (ExistingAccess, InvokeStateOperand):
            raise TypeError("state address site must be ExistingAccess or InvokeStateOperand")
        self.site.__post_init__()
        _records(self.effects, AddressEffect, "state address effects", nonempty=True)
        _exact(self.coverage, AddressCoverage, "state address coverage")
        if self.protocol is not None:
            _record(self.protocol, ProviderFactReference, "state address protocol")


def selector_uses(selector: AddressSelector) -> tuple[UseID, ...]:
    """Return the selector's owned-Use operands in semantic path order.

    This is a projection only. It does not deduplicate repeated Uses or infer
    conversions, types, address ranges, or runtime identity.
    """
    if type(selector) is NamespaceKey:
        return (selector.key,)
    if type(selector) is DynamicField:
        return (selector.name,)
    if type(selector) is Element:
        return (selector.index,)
    if type(selector) is Slice:
        return tuple(item for item in (selector.start, selector.stop, selector.step)
                     if item is not None)
    if type(selector) is StorageRange:
        return (selector.start, selector.count)
    if type(selector) in (WholeOwner, ObjectField, CellContent, UnknownSelection):
        return selector.operands if type(selector) is UnknownSelection else ()
    raise TypeError("selector must be an exact AddressSelector")


def address_effect_uses(effect: AddressEffect) -> tuple[UseID, ...]:
    """Return path operand Uses, in order and with duplicates preserved."""
    if type(effect) is not AddressEffect:
        raise TypeError("effect must be an exact AddressEffect")
    effect.__post_init__()
    return tuple(use for selector in effect.path for use in selector_uses(selector))


STATE_ADDRESS_RECORD_TAGS = {
    ExistingAccess: ("kind", "EXISTING_ACCESS"),
    InvokeStateOperand: ("kind", "INVOKE_STATE_OPERAND"),
    DomainOwner: ("kind", "DOMAIN_OWNER"),
    ReferenceOwner: ("kind", "REFERENCE_OWNER"),
    ResourceOwner: ("kind", "RESOURCE_OWNER"),
    UnknownOwner: ("kind", "UNKNOWN_OWNER"),
    WholeOwner: ("kind", "WHOLE_OWNER"),
    NamespaceKey: ("kind", "NAMESPACE_KEY"),
    ObjectField: ("kind", "OBJECT_FIELD"),
    DynamicField: ("kind", "DYNAMIC_FIELD"),
    CellContent: ("kind", "CELL_CONTENT"),
    Element: ("kind", "ELEMENT"),
    Slice: ("kind", "SLICE"),
    StorageRange: ("kind", "STORAGE_RANGE"),
    UnknownSelection: ("kind", "UNKNOWN_SELECTION"),
}


__all__ = [
    "AddressCoverage", "AddressEffect", "AddressOwner", "AddressSelector", "AddressUnit",
    "CellContent", "DomainOwner", "DynamicField", "Element", "ExistingAccess",
    "InvokeStateOperand", "NamespaceKey", "ObjectField", "ReferenceOwner", "ResourceOwner",
    "Slice", "StateAddressRefinement", "StateAddressSite", "StorageRange",
    "UnknownOwner", "UnknownSelection", "WholeOwner", "STATE_ADDRESS_RECORD_TAGS",
    "address_effect_uses", "selector_uses",
]
