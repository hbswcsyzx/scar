"""Source-derived Python return wrapping; no object or storage identity claim."""
from dataclasses import dataclass
from enum import Enum


class ReceiverMode(str,Enum):
    FUNCTION='FUNCTION'
    BOUND='BOUND'
    UNBOUND='UNBOUND'

class ValueShapeKind(str,Enum):
    TENSOR='TENSOR'
    SCALAR='SCALAR'
    OBJECT='OBJECT'
    NONE='NONE'
    OPEN='OPEN'
    TUPLE='TUPLE'
    NAMED_TUPLE='NAMED_TUPLE'
    SEQUENCE='SEQUENCE'
    OPTIONAL='OPTIONAL'
    UNION='UNION'
    ITERATOR='ITERATOR'
    ARGUMENT='ARGUMENT'
    SELF='SELF'


@dataclass(frozen=True,slots=True)
class ValueShape:
    kind: ValueShapeKind
    items: tuple['ValueShape',...]=()
    element: 'ValueShape | None'=None
    fields: tuple[str | None,...]=()
    container: str | None=None
    native_ordinal: int | None=None
    native_name: str | None=None
    python_type: str | None=None
    parser_index: int | None=None


@dataclass(frozen=True,slots=True)
class SchemaType:
    text: str
    kind: str
    name: str | None=None
    element: 'SchemaType | None'=None
    size: int | None=None


@dataclass(frozen=True,slots=True)
class NativeReturnSlot:
    ordinal: int
    name: str | None
    type: SchemaType
    annotation: str | None


