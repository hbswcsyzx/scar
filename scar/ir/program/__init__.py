"""Canonical immutable program-graph record types.

Graph-wide validation and queries are available from ``program.validation``
and ``program.queries``. Typed records remain independently importable.
"""
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, DataValue, ExitKind, ExitPort,
    Footprint, FootprintKind, LiteralOrigin, Operation, OperationResult, OrderEdge,
    ProgramGraph, ReferenceValue, Region, Stability, StateAccess, StateLocation,
    StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseRole,
    Value, ValueKind, ValueType, value_type,
)
from scar.ir.program.codec import SCHEMA, SCHEMA_VERSION, dumps, loads


__all__ = [
    "AccessMode", "Behavior", "Block", "BlockArgument", "BlockID", "DataValue",
    "ExitKind", "ExitPort", "Footprint", "FootprintKind", "LiteralOrigin",
    "LocationID", "Operation", "OperationID", "OperationResult", "OrderEdge",
    "ProgramGraph", "ReferenceValue", "Region", "RegionID", "SCHEMA",
    "SCHEMA_VERSION", "Stability", "StateAccess", "StateLocation",
    "StateVersionValue", "Successor", "Terminator", "TerminatorKind", "Use",
    "UseID", "UseRole", "Value", "ValueID", "ValueKind", "ValueType",
    "dumps", "loads", "value_type",
]
