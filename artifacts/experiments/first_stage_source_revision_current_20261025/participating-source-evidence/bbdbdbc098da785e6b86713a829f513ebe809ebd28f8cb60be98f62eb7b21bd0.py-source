"""Interpretations of original ordinary-except matching operations.

These records produce no Values and assert no runtime builtin identity. A
dynamic handler retains its real operand; a fixed intrinsic invents no operand.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from .ids import OperationID, UseID
from .protocol_connections import ExpectedSourcePort, ExactResultPort, _expected_source, _exact_result, _state_sites
from .protocols import StaticGapReason, StaticProtocolGap
from .providers import ProviderFactReference
from .state_addresses import ExistingAccess, InvokeStateOperand


class BuiltinExceptionCategory(str, Enum):
    ATTRIBUTE_ERROR = 'ATTRIBUTE_ERROR'
    STOP_ITERATION = 'STOP_ITERATION'
    STOP_ASYNC_ITERATION = 'STOP_ASYNC_ITERATION'
    GENERATOR_EXIT = 'GENERATOR_EXIT'
    EXCEPTION = 'EXCEPTION'
    BASE_EXCEPTION = 'BASE_EXCEPTION'


@dataclass(frozen=True, slots=True)
class FixedBuiltinHandler:
    category: BuiltinExceptionCategory
    applicability: ProviderFactReference | StaticProtocolGap

    def __post_init__(self):
        if type(self.category) is not BuiltinExceptionCategory:
            raise TypeError('fixed handler requires an exact builtin category')
        if type(self.applicability) not in (ProviderFactReference, StaticProtocolGap):
            raise TypeError('fixed handler applicability requires a fact reference or explicit gap')
        self.applicability.__post_init__()


@dataclass(frozen=True, slots=True)
class ExceptionHandlerOperand:
    use: UseID
    source: ExpectedSourcePort
    interpretation: FixedBuiltinHandler | StaticProtocolGap = StaticProtocolGap(
        StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)

    def __post_init__(self):
        if type(self.use) is not UseID:
            raise TypeError('handler operand requires an exact original UseID')
        self.use.__post_init__()
        _expected_source(self.source, 'handler independent source')
        if type(self.interpretation) not in (FixedBuiltinHandler, StaticProtocolGap):
            raise TypeError('handler interpretation requires a fixed builtin declaration or explicit gap')
        self.interpretation.__post_init__()


@dataclass(frozen=True, slots=True)
class ExceptionMatcher:
    operation: OperationID
    input_use: UseID
    source: ExpectedSourcePort
    handler: FixedBuiltinHandler | ExceptionHandlerOperand
    normal_result: ExactResultPort | None
    raise_result: ExactResultPort | None
    branch: OperationID | None
    state_sites: tuple[ExistingAccess | InvokeStateOperand, ...]

    def __post_init__(self):
        if type(self.operation) is not OperationID or type(self.input_use) is not UseID:
            raise TypeError('exception matcher requires exact original operation and input UseID')
        self.operation.__post_init__()
        self.input_use.__post_init__()
        _expected_source(self.source, 'matcher independent source')
        if type(self.handler) not in (FixedBuiltinHandler, ExceptionHandlerOperand):
            raise TypeError('matcher handler requires an exact fixed or operand handler')
        self.handler.__post_init__()
        if self.normal_result is None and self.raise_result is None:
            raise ValueError('matcher must retain at least one original completion')
        for port in (self.normal_result, self.raise_result):
            if port is not None:
                _exact_result(port, 'matcher own completion result')
        if self.branch is not None:
            if type(self.branch) is not OperationID:
                raise TypeError('matcher branch requires an exact original operation')
            self.branch.__post_init__()
        if (self.normal_result is None) != (self.branch is None):
            raise ValueError('matcher NORMAL bool and branch must be present together')
        _state_sites(self.state_sites, 'matcher original state sites')


EXCEPTION_MATCH_RECORD_TAGS = MappingProxyType({
    FixedBuiltinHandler: ('kind', 'FIXED_BUILTIN_EXCEPTION_HANDLER'),
    ExceptionHandlerOperand: ('kind', 'EXCEPTION_HANDLER_OPERAND'),
    ExceptionMatcher: ('kind', 'EXCEPTION_MATCHER'),
})


__all__ = ['BuiltinExceptionCategory', 'FixedBuiltinHandler', 'ExceptionHandlerOperand',
           'ExceptionMatcher', 'EXCEPTION_MATCH_RECORD_TAGS']
