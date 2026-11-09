"""Conditional source selector paths, never runtime addresses or content equality."""
from dataclasses import dataclass
from enum import Enum

from scar.ir.literals import PythonLiteral
from .normal_targets import GlobalPort
from .providers import ProviderFactReference


class AddressRootKind(str, Enum):
    FUNCTION_PARAMETER = 'FUNCTION_PARAMETER'
    CALL_RESULT = 'CALL_RESULT'
    SOURCE_LITERAL = 'SOURCE_LITERAL'
    CLASS_DEFINITION = 'CLASS_DEFINITION'
    FUNCTION_DEFINITION = 'FUNCTION_DEFINITION'
    OPEN_PRODUCER = 'OPEN_PRODUCER'


@dataclass(frozen=True, slots=True)
class FieldSelector:
    name: str


@dataclass(frozen=True, slots=True)
class ItemSelector:
    key: PythonLiteral | GlobalPort


AddressSelector = FieldSelector | ItemSelector


@dataclass(frozen=True, slots=True)
class AddressPath:
    root: GlobalPort
    root_kind: AddressRootKind
    selectors: tuple[AddressSelector, ...]
    evidence: tuple[ProviderFactReference, ...]
    conditions: tuple[str, ...]
    frontier: str | None = None
    semantics: str = 'CONDITIONAL_SOURCE_SELECTOR_PATH_NOT_RUNTIME_ADDRESS_OR_CONTENT_EQUALITY'
