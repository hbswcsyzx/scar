"""Exact abstract contents and unverified definition-source declarations.

These records neither produce Python objects nor replace canonical producers.
Source spans and code-record slots are declarations, not replayed evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from scar.ir.literals import PythonLiteral
from scar.ir.program.providers import ProviderFactReference
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import SourceAtomID


def _text(value, name):
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be exact nonempty str")


@dataclass(frozen=True, slots=True)
class SourceExpression:
    source: SourceReference

    def __post_init__(self):
        if type(self.source) is not SourceReference:
            raise TypeError("SourceExpression.source must be exact SourceReference")
        source = self.source
        if type(source.atom_id) is not SourceAtomID:
            raise TypeError("source atom must be exact SourceAtomID")
        _text(source.atom_id.value, "source atom ID")
        for name in ("path", "fingerprint"):
            _text(getattr(source, name), "source " + name)
        for name in ("start_line", "end_line", "start_column"):
            if type(getattr(source, name)) is not int:
                raise TypeError("source positions must be exact integers")
        if source.end_column is not None and type(source.end_column) is not int:
            raise TypeError("source end_column must be exact int or None")
        source.__post_init__()


@dataclass(frozen=True, slots=True)
class CodeConstant:
    """Fact points at a code/const-pool record; index selects its co_consts slot."""

    fact: ProviderFactReference
    index: int

    def __post_init__(self):
        if type(self.fact) is not ProviderFactReference:
            raise TypeError("CodeConstant.fact must be exact ProviderFactReference")
        self.fact.__post_init__()
        if type(self.index) is not int or self.index < 0:
            raise ValueError("constant slot index must be exact nonnegative int")


@dataclass(frozen=True, slots=True)
class UnlocatedLiteral:
    reason: str = "literal definition is unlocated"

    def __post_init__(self):
        _text(self.reason, "unlocated literal reason")


LiteralDefinition: TypeAlias = SourceExpression | CodeConstant | UnlocatedLiteral


def require_definition(value):
    if type(value) not in (SourceExpression, CodeConstant, UnlocatedLiteral):
        raise TypeError("literal definition must be an exact typed declaration")
    value.__post_init__()


@dataclass(frozen=True, slots=True)
class UninterpretedConstant:
    reason: str

    def __post_init__(self):
        _text(self.reason, "uninterpreted constant reason")


@dataclass(frozen=True, slots=True)
class ExactLiteralOrigin:
    """Abstract immutable Data content only; never a Python object identity."""

    literal: PythonLiteral
    definition: LiteralDefinition = UnlocatedLiteral()

    def __post_init__(self):
        from scar.ir.literals import require_exact_literal

        if type(self.literal) is not PythonLiteral:
            raise TypeError("ExactLiteralOrigin.literal must be exact PythonLiteral")
        require_exact_literal(self.literal)
        require_definition(self.definition)


LITERAL_SOURCE_RECORD_TAGS = {
    ExactLiteralOrigin: ("kind", "EXACT_LITERAL_ORIGIN"),
    SourceExpression: ("kind", "SOURCE_EXPRESSION"),
    CodeConstant: ("kind", "CODE_CONSTANT"),
    UnlocatedLiteral: ("kind", "UNLOCATED_LITERAL"),
    UninterpretedConstant: ("kind", "UNINTERPRETED_CONSTANT"),
}

__all__ = ["SourceExpression", "CodeConstant", "UnlocatedLiteral", "LiteralDefinition",
           "UninterpretedConstant", "ExactLiteralOrigin", "LITERAL_SOURCE_RECORD_TAGS"]
