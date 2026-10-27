"""Program23 await declarations over original ports, without identity authority.

Local contracts retain the original producer and selected result.  The global
body link declares a semantic correspondence; it never makes wrapper W a copy
of its held body B.  Graph ownership, current state and source checks belong to
the shared protocol resolver, not these record constructors.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from types import MappingProxyType
from typing import Any, TypeAlias

from .ids import BlockID, OperationID, ProtocolScopeID, UseID
from .protocols import (
    OwnedUse, ProtocolClause, ProtocolProfile, StaticProtocolGap,
    _identifier,
)
from .protocol_connections import (
    ProtocolOperationRef, _exact_result, _expected_source, _state_sites,
)
from .state_addresses import ExistingAccess, InvokeStateOperand
from .structured import ControlEdgeReference
from scar.ir.v2.ids import Identifier


# Filled only after model's canonical ports and connection aliases are bound.
ExpectedSourcePort: TypeAlias = Any
ProtocolResultPort: TypeAlias = Any
_PORTS_BOUND = False


def _strict_ids(value: object) -> None:
    """Recheck legacy nested IDs too; a frozen parent may have been tampered."""
    if isinstance(value, Identifier):
        if type(value) not in (BlockID, OperationID, ProtocolScopeID, UseID):
            raise TypeError("await references require canonical exact identifier classes")
        _identifier(value, type(value), "await nested identifier")
    elif is_dataclass(value):
        for member in fields(value):
            _strict_ids(getattr(value, member.name))
    elif type(value) is tuple:
        for item in value:
            _strict_ids(item)


def _record(value: object, expected: type, name: str) -> None:
    if type(value) is not expected:
        raise TypeError(f"{name} must be exact {expected.__name__}")
    value.__post_init__()
    _strict_ids(value)


def _source(value: object, name: str) -> None:
    _expected_source(value, name)
    _strict_ids(value)


def _result(value: object, name: str) -> None:
    # These declarations always name an existing own result, not an uncaptured
    # result gap. Gaps are supported at expansion/projection boundaries instead.
    _exact_result(value, name)
    _strict_ids(value)


def _sites(value: object, name: str) -> None:
    _state_sites(value, name)
    _strict_ids(value)


def _invoke_result(value: object, name: str) -> None:
    _result(value, name)
    from .model import InvokeLiteralResult
    if type(value) is not InvokeLiteralResult:
        raise TypeError(f"{name} must be an exact INVOKE result")


def _variant(value: object, choices: tuple[type, ...], name: str) -> None:
    if type(value) not in choices:
        raise TypeError(f"{name} has an unsupported exact variant")
    value.__post_init__()
    _strict_ids(value)


@dataclass(frozen=True, slots=True)
class ExpandedAwaitCallee:
    lookup: ProtocolOperationRef
    call: ProtocolOperationRef | StaticProtocolGap
    qualification: ProtocolOperationRef | StaticProtocolGap

    def __post_init__(self) -> None:
        _record(self.lookup, ProtocolOperationRef, "expanded await lookup")
        _variant(self.call, (ProtocolOperationRef, StaticProtocolGap), "expanded await call")
        _variant(self.qualification, (ProtocolOperationRef, StaticProtocolGap),
                 "expanded await qualification")


@dataclass(frozen=True, slots=True)
class AwaitAcquisition:
    operand_use: UseID
    expected: ExpectedSourcePort
    result: ProtocolResultPort
    state_sites: tuple[ExistingAccess | InvokeStateOperand, ...]
    expansion: ExpandedAwaitCallee | StaticProtocolGap

    def __post_init__(self) -> None:
        _identifier(self.operand_use, UseID, "await operand Use")
        _source(self.expected, "await independently expected operand")
        _invoke_result(self.result, "await acquisition own result")
        _sites(self.state_sites, "await acquisition state sites")
        _variant(self.expansion, (ExpandedAwaitCallee, StaticProtocolGap), "await expansion")


@dataclass(frozen=True, slots=True)
class AwaitIteratorQualification:
    input_use: UseID
    expected: ExpectedSourcePort
    result: ProtocolResultPort
    state_sites: tuple[ExistingAccess | InvokeStateOperand, ...]
    branch: OperationID | None
    accepts_true: bool | None

    def __post_init__(self) -> None:
        _identifier(self.input_use, UseID, "qualification input Use")
        _source(self.expected, "qualification expected candidate")
        _result(self.result, "qualification own result")
        _sites(self.state_sites, "qualification state sites")
        from .model import InvokeLiteralResult, OperationResult
        if self.branch is None:
            if self.accepts_true is not None or type(self.result) is not InvokeLiteralResult:
                raise ValueError("INVOKE qualification requires no branch/polarity and an INVOKE result")
        else:
            _identifier(self.branch, OperationID, "qualification original branch")
            if type(self.accepts_true) is not bool or type(self.result) is not OperationResult:
                raise TypeError("branch qualification requires an ordinary result and exact bool polarity")


@dataclass(frozen=True, slots=True)
class CoroutineAwaitWrapper:
    body_use: UseID
    expected_body: ExpectedSourcePort
    result: ProtocolResultPort
    state_sites: tuple[ExistingAccess | InvokeStateOperand, ...]

    def __post_init__(self) -> None:
        _identifier(self.body_use, UseID, "wrapper constructor body Use")
        _source(self.expected_body, "wrapper independently expected body")
        _invoke_result(self.result, "wrapper constructor own result")
        _sites(self.state_sites, "wrapper constructor state sites")


@dataclass(frozen=True, slots=True)
class WrapperHeldBody:
    constructor: ProtocolOperationRef
    expected_body: ExpectedSourcePort
    body: OwnedUse
    wrapper_read: OwnedUse
    body_result: ProtocolResultPort
    state_sites: tuple[ExistingAccess | InvokeStateOperand, ...]

    def __post_init__(self) -> None:
        _record(self.constructor, ProtocolOperationRef, "wrapper constructor reference")
        _source(self.expected_body, "held-body expected source")
        _record(self.body, OwnedUse, "wrapper original body Use")
        _record(self.wrapper_read, OwnedUse, "wrapper getter W input")
        _result(self.body_result, "wrapper getter own B result")
        _sites(self.state_sites, "wrapper getter state sites")


@dataclass(frozen=True, slots=True)
class AwaitBodyLink:
    source: ProtocolOperationRef
    advance: ProtocolOperationRef
    drive: OperationID
    projection: WrapperHeldBody | StaticProtocolGap | None
    guard: ControlEdgeReference | None

    def __post_init__(self) -> None:
        _record(self.source, ProtocolOperationRef, "await body source")
        _record(self.advance, ProtocolOperationRef, "await body advance")
        _identifier(self.drive, OperationID, "await body Drive")
        if self.projection is not None:
            _variant(self.projection, (WrapperHeldBody, StaticProtocolGap), "await body projection")
        if self.guard is not None:
            _record(self.guard, ControlEdgeReference, "await body guard")

    @property
    def scope(self) -> ProtocolScopeID:
        return self.source.scope


AWAIT_ACQUISITION_RECORD_TAGS = MappingProxyType({
    ExpandedAwaitCallee: ("kind", "EXPANDED_AWAIT_CALLEE"),
    AwaitAcquisition: ("kind", "AWAIT_ACQUISITION"),
    AwaitIteratorQualification: ("kind", "AWAIT_ITERATOR_QUALIFICATION"),
    CoroutineAwaitWrapper: ("kind", "COROUTINE_AWAIT_WRAPPER"),
    WrapperHeldBody: ("kind", "WRAPPER_HELD_BODY"),
    AwaitBodyLink: ("kind", "AWAIT_BODY_LINK"),
})
AWAIT_ACQUISITION_PROFILES = frozenset({
    ProtocolProfile.AWAIT_ACQUISITION_V1,
    ProtocolProfile.AWAIT_METHOD_IMPLEMENTATION_V1,
    ProtocolProfile.COROUTINE_WRAPPER_CONSTRUCTION_V1,
})
AWAIT_ACQUISITION_CLAUSES = frozenset({
    ProtocolClause.AWAIT_ACQUISITION,
    ProtocolClause.AWAIT_ITERATOR_QUALIFICATION,
    ProtocolClause.WRAPPER_CONSTRUCTION,
})


def _bind_await_records() -> None:
    global ExpectedSourcePort, ProtocolResultPort, _PORTS_BOUND
    from . import protocol_connections, protocols
    from .model import BlockArgument, InvokeLiteralResult, OperationResult
    if protocols._MODEL_PORT_CLASSES != (OperationResult, InvokeLiteralResult):
        raise RuntimeError("canonical protocol ports must bind before await records")
    if protocol_connections._MODEL_PORT_CLASSES != (OperationResult, InvokeLiteralResult, BlockArgument):
        raise RuntimeError("canonical connection ports must bind before await records")
    if _PORTS_BOUND:
        return
    ExpectedSourcePort = protocol_connections.ExpectedSourcePort
    ProtocolResultPort = protocols.ProtocolResultPort
    protocols._bind_await_contract_types(
        AwaitAcquisition, AwaitIteratorQualification, CoroutineAwaitWrapper)
    protocol_connections._bind_await_binding_type(AwaitBodyLink)
    _PORTS_BOUND = True


def has_await_acquisition_capability(graph: object) -> bool:
    """Detect typed Program23 uses, including new enums inside old records.

    Ordinary strings (labels, names, literals and provider locators) are never
    capability switches. Do not follow derived properties such as link.scope.
    """
    pending = [getattr(graph, name, ()) for name in (
        "protocol_scopes", "protocol_operations", "protocol_call_inputs",
        "protocol_result_consumers", "protocol_bindings", "exception_matches",
    )]
    seen = set()
    while pending:
        item = pending.pop()
        if type(item) in AWAIT_ACQUISITION_RECORD_TAGS:
            return True
        if type(item) is ProtocolProfile and item in AWAIT_ACQUISITION_PROFILES:
            return True
        if type(item) is ProtocolClause and item in AWAIT_ACQUISITION_CLAUSES:
            return True
        if is_dataclass(item):
            if id(item) in seen:
                continue
            seen.add(id(item))
            pending.extend(getattr(item, member.name) for member in fields(item))
        elif type(item) is tuple:
            pending.extend(item)
    return False


__all__ = [
    "AwaitAcquisition", "ExpandedAwaitCallee", "AwaitIteratorQualification",
    "CoroutineAwaitWrapper", "AwaitBodyLink", "WrapperHeldBody",
    "AWAIT_ACQUISITION_RECORD_TAGS", "AWAIT_ACQUISITION_PROFILES",
    "AWAIT_ACQUISITION_CLAUSES", "has_await_acquisition_capability",
]
