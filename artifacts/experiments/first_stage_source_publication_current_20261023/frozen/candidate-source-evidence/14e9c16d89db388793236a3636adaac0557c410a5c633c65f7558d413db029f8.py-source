"""Canonical function environment interfaces over existing reference ports.

These records aggregate a region's entry references; they do not pack another
Value or record another set of call arguments.  Mutable contents remain in the
ordinary state domains.  Entry ownership, reference types, state availability
and code/source correspondence require graph validation and separate evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from scar.ir.program.functions import FormalPort
from scar.ir.program.ids import (
    EnvironmentInterfaceID, LocationID, RegionID, ValueID,
)
from scar.ir.v2.ids import OperationDefinitionID, ValueSlotID


class EnvironmentRole(str, Enum):
    FUNCTION_OBJECT = "FUNCTION_OBJECT"
    GLOBALS_NAMESPACE = "GLOBALS_NAMESPACE"
    BUILTINS_NAMESPACE = "BUILTINS_NAMESPACE"
    DEFAULTS = "DEFAULTS"
    KEYWORD_DEFAULTS = "KEYWORD_DEFAULTS"
    CAPTURED_CELL = "CAPTURED_CELL"


_PREFIX_ROLES = (
    EnvironmentRole.FUNCTION_OBJECT,
    EnvironmentRole.GLOBALS_NAMESPACE,
    EnvironmentRole.BUILTINS_NAMESPACE,
    EnvironmentRole.DEFAULTS,
    EnvironmentRole.KEYWORD_DEFAULTS,
)


@dataclass(frozen=True, slots=True)
class EnvironmentMember:
    """One canonical entry reference and its declared state dependency domains.

    Locations need not be disjoint across members: several members may depend
    on the same coarse world.  A captured cell reference denotes the cell's
    identity, not an immutable capture of its contents.  Missing defaults are
    represented by an ordinary reference to None, not by omitting the member.
    ``cell_slot`` is this body's free-variable interface slot (``co_freevars``),
    not the enclosing function's origin binding or a runtime cell identity.
    An own formal promoted to ``co_cellvars`` is not a captured environment slot.
    """

    role: EnvironmentRole
    reference: ValueID
    locations: tuple[LocationID, ...] = ()
    cell_slot: ValueSlotID | None = None
    cell_position: int | None = None

    def __post_init__(self) -> None:
        if type(self.role) is not EnvironmentRole:
            raise TypeError("environment member role must be EnvironmentRole")
        if type(self.reference) is not ValueID:
            raise TypeError("environment member reference must be ValueID")
        if type(self.locations) is not tuple or any(
                type(location) is not LocationID for location in self.locations):
            raise TypeError("environment locations must be a tuple of LocationID")
        if len(set(self.locations)) != len(self.locations):
            raise ValueError("environment member locations must not repeat")
        if self.role is EnvironmentRole.CAPTURED_CELL:
            if type(self.cell_slot) is not ValueSlotID:
                raise TypeError("captured cell must have a ValueSlotID")
            if type(self.cell_position) is not int:
                raise TypeError("captured cell position must be an exact integer")
            if self.cell_position < 0:
                raise ValueError("captured cell position must be nonnegative")
        elif self.cell_slot is not None or self.cell_position is not None:
            raise ValueError("only captured cells may have cell slot or position")


@dataclass(frozen=True, slots=True)
class EnvironmentInterface:
    """A complete ordered declaration of a function's environment entry ports.

    Distinct reference ValueIDs identify distinct ports, not distinct Python
    objects: actual argument references and captured cell identities may alias.
    The builtins member denotes the function's saved builtins namespace, which
    need not equal the current globals['__builtins__'] value.  Code definition is
    a static declaration; this record does not verify a runtime function binding.
    """

    id: EnvironmentInterfaceID
    region: RegionID
    code_definition: OperationDefinitionID
    members: tuple[EnvironmentMember, ...]

    def __post_init__(self) -> None:
        if type(self.id) is not EnvironmentInterfaceID:
            raise TypeError("environment interface must have EnvironmentInterfaceID")
        if type(self.region) is not RegionID:
            raise TypeError("environment interface region must be RegionID")
        if type(self.code_definition) is not OperationDefinitionID:
            raise TypeError("environment code definition must be OperationDefinitionID")
        if type(self.members) is not tuple or any(
                type(member) is not EnvironmentMember for member in self.members):
            raise TypeError("environment members must be a tuple of EnvironmentMember")
        prefix_length = len(_PREFIX_ROLES)
        if (len(self.members) < prefix_length
                or tuple(member.role for member in self.members[:prefix_length])
                != _PREFIX_ROLES):
            raise ValueError("environment must begin with the five ordered namespace roles")
        cells = self.members[prefix_length:]
        if any(member.role is not EnvironmentRole.CAPTURED_CELL for member in cells):
            raise ValueError("only captured cells may follow the five environment roles")
        if any(member.cell_position != position for position, member in enumerate(cells)):
            raise ValueError("captured cell positions must be consecutive from zero")
        if len({member.cell_slot for member in cells}) != len(cells):
            raise ValueError("captured cell slots must be distinct")
        if len({member.reference for member in self.members}) != len(self.members):
            raise ValueError("environment entry reference ValueIDs must be distinct")


@dataclass(frozen=True, slots=True)
class FunctionEntryLayout:
    """Explicit Python formals alongside an existing environment declaration.

    Parameters retain declared signature order, independently of the physical
    entry block's port order.  Region/code ownership comes from the referenced
    environment; actual arguments remain on canonical call/invoke operations.
    Graph validation checks entry reference types and the complete, disjoint
    partition of formals, environment references and state parameters.  Source
    signature coverage is a separate provenance/replay obligation.
    """

    environment: EnvironmentInterfaceID
    parameters: tuple[FormalPort, ...]

    def __post_init__(self) -> None:
        if type(self.environment) is not EnvironmentInterfaceID:
            raise TypeError("function entry layout needs EnvironmentInterfaceID")
        if type(self.parameters) is not tuple or any(
                type(parameter) is not FormalPort for parameter in self.parameters):
            raise TypeError("function entry parameters must be a tuple of FormalPort")
        if any(type(parameter.slot) is not ValueSlotID for parameter in self.parameters):
            raise TypeError("function entry formal slots must be ValueSlotID")
        if any(type(parameter.value) is not ValueID for parameter in self.parameters):
            raise TypeError("function entry formal values must be ValueID")
        if len({parameter.slot for parameter in self.parameters}) != len(self.parameters):
            raise ValueError("function entry formal slots must be distinct")
        if len({parameter.value for parameter in self.parameters}) != len(self.parameters):
            raise ValueError("function entry formal values must be distinct")


__all__ = ["EnvironmentInterface", "EnvironmentMember", "EnvironmentRole",
           "FunctionEntryLayout"]
