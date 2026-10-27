"""Source-declared Lambda creation/capture and expression-body interfaces.

These records connect existing ProgramGraph ports. They neither execute a
body at creation nor establish a runtime callable, alias or captured value.
"""
from dataclasses import dataclass
from enum import Enum

from scar.ir.program.functions import BodyEntryInterface, BodyLoweringProfile, BindingCondition
from scar.ir.program.ids import EnvironmentInterfaceID, OperationID, UseID, ValueID
from scar.ir.v2.common import SourceReference


class LambdaEnvironmentField(str, Enum):
    """Initialized by the original creation, not a target-program field read."""
    BUILTINS = '__builtins__'
    DEFAULTS = '__defaults__'
    KEYWORD_DEFAULTS = '__kwdefaults__'


@dataclass(frozen=True, slots=True)
class LambdaCapture:
    formal: ValueID
    source_use: UseID | None = None
    normal_result: int | None = None
    created_field: LambdaEnvironmentField | None = None

    def __post_init__(self):
        if type(self.formal) is not ValueID:
            raise TypeError('Lambda capture formal must be its original entry ValueID')
        if (sum(x is not None for x in (self.source_use,self.normal_result,self.created_field)) != 1
                or self.source_use is not None and type(self.source_use) is not UseID
                or self.normal_result is not None and (type(self.normal_result) is not int or self.normal_result < 0)
                or self.created_field is not None and type(self.created_field) is not LambdaEnvironmentField):
            raise ValueError('Lambda capture requires one exact creation Use, NORMAL result or initialized-field summary')


@dataclass(frozen=True, slots=True)
class LambdaBodyDefinition:
    creation: OperationID
    source: SourceReference
    code_constant: OperationID
    body: BodyEntryInterface
    environment: EnvironmentInterfaceID
    captures: tuple[LambdaCapture, ...]
    conditions: tuple[BindingCondition, ...] = tuple(BindingCondition)

    def __post_init__(self):
        if (type(self.creation) is not OperationID or type(self.code_constant) is not OperationID
                or type(self.source) is not SourceReference or type(self.body) is not BodyEntryInterface
                or self.body.profile is not BodyLoweringProfile.STRUCTURED_ENV
                or type(self.environment) is not EnvironmentInterfaceID):
            raise TypeError('Lambda definition requires original typed creation/source/body/environment ports')
        if (type(self.captures) is not tuple or any(type(c) is not LambdaCapture for c in self.captures)
                or len({c.formal for c in self.captures}) != len(self.captures)):
            raise ValueError('Lambda captures must name unique original entry references')
        if self.conditions != tuple(BindingCondition):
            raise ValueError('Lambda entry keeps every ordinary source/call/default/frame binding condition unproved')


__all__ = ['LambdaCapture', 'LambdaBodyDefinition', 'LambdaEnvironmentField']
