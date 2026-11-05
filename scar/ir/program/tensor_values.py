"""Conditional return/projection types, distinct from objects and storage."""
from dataclasses import dataclass
from enum import Enum

from scar.ir.literals import PythonLiteral
from .normal_targets import GlobalPort
from .providers import ProviderFactReference
from .python_bindings import PythonBindingID,SourceCallSite


from .binding_returns import ValueShapeKind,ValueShape,SchemaType,NativeReturnSlot,ReceiverMode


class ProjectionKind(str,Enum):
    INDEX='INDEX'
    ELEMENT='ELEMENT'
    OPTIONAL='OPTIONAL'
    ALTERNATIVE='ALTERNATIVE'


@dataclass(frozen=True,slots=True)
class ReturnProjection:
    kind: ProjectionKind
    index: int | None=None


@dataclass(frozen=True,slots=True)
class ReturnTypeEvidence:
    origin: GlobalPort
    target: GlobalPort
    projection: tuple[ReturnProjection,...]
    shape: ValueShapeKind
    source: ProviderFactReference
    conditions: tuple[str,...]
    identity_proven: bool=False


@dataclass(frozen=True,slots=True)
class DeclaredMemberCall:
    site: SourceCallSite
    receiver: GlobalPort | None
    member: str
    declaration: ProviderFactReference
    conditions: tuple[str,...]
    native_selector: str | None=None
    receiver_mode: ReceiverMode=ReceiverMode.BOUND


@dataclass(frozen=True,slots=True)
class DeclaredProtocolCall:
    receiver: GlobalPort
    member: str
    argument: GlobalPort | PythonLiteral
    result: GlobalPort | None
    world: GlobalPort
    result_world: GlobalPort
    declaration: ProviderFactReference
    conditions: tuple[str,...]
    assigned: GlobalPort | None=None
