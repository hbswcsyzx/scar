"""Conditional source-factory origins of existing function-entry references.

These records describe no CALL or invocation.  A factory site can create many
objects; selecting one source occurrence remains a condition, and neither the
set of entry origins nor the contents of a captured namespace is closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .environments import EnvironmentMember, EnvironmentRole
from .ids import EnvironmentInterfaceID, UseID, ValueID
from .source_call_bindings import SourceBodyNamespace
from .static_calls import StaticFunctionCreationRoute


class FactoryEntryOriginCondition(str, Enum):
    ENTRY_CALLABLE_FROM_THIS_FACTORY_OCCURRENCE = "ENTRY_CALLABLE_FROM_THIS_FACTORY_OCCURRENCE"
    FACTORY_COMPLETED_NORMALLY = "FACTORY_COMPLETED_NORMALLY"
    FUNCTION_CODE_MATCHES_CREATION = "FUNCTION_CODE_MATCHES_CREATION"


@dataclass(frozen=True, slots=True)
class StaticFactoryEntryOrigin:
    creator: SourceBodyNamespace
    creation: StaticFunctionCreationRoute
    body: SourceBodyNamespace
    environment: EnvironmentInterfaceID
    member: EnvironmentMember
    source_use: UseID | None
    source_value: ValueID
    conditions: tuple[FactoryEntryOriginCondition, ...] = tuple(FactoryEntryOriginCondition)

    def __post_init__(self):
        for value, expected in ((self.creator, SourceBodyNamespace), (self.creation, StaticFunctionCreationRoute),
                (self.body, SourceBodyNamespace), (self.environment, EnvironmentInterfaceID),
                (self.member, EnvironmentMember), (self.source_value, ValueID)):
            if type(value) is not expected:
                raise TypeError("factory entry origin needs exact " + expected.__name__)
            if hasattr(value, "__post_init__"):
                value.__post_init__()
        if (self.body.definition != self.creation.definition.definition
                or self.body.source != self.creation.definition.source):
            raise ValueError("factory origin changed its qualified source body")
        if self.member.role is EnvironmentRole.FUNCTION_OBJECT:
            if self.source_use is not None or self.source_value != self.creation.normal_value:
                raise ValueError("function-object origin must be the original normal factory reference")
        elif self.member.role is EnvironmentRole.GLOBALS_NAMESPACE:
            if type(self.source_use) is not UseID:
                raise TypeError("globals origin needs its original factory capture Use")
        else:
            raise ValueError("factory origins cover only FUNCTION_OBJECT and GLOBALS_NAMESPACE references")
        if (type(self.conditions) is not tuple or self.conditions != tuple(FactoryEntryOriginCondition)):
            raise ValueError("factory entry origin must retain every explicit source/selection condition")


__all__ = ["FactoryEntryOriginCondition", "StaticFactoryEntryOrigin"]
