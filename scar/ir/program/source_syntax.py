"""F2 official AST occurrences; no control, binding or execution claims."""
from dataclasses import dataclass

from scar.ir.literals import PythonLiteral
from .source_bytes import SourceBytesProfile
from .source_tokens import SourceTokenError, SourceTokenWarning


@dataclass(frozen=True, slots=True)
class AstTypeSchema:
    kind: str
    name: str | None
    items: tuple['AstTypeSchema', ...]


@dataclass(frozen=True, slots=True)
class AstFieldSchema:
    name: str
    type: AstTypeSchema


@dataclass(frozen=True, slots=True)
class AstClassSchema:
    name: str
    bases: tuple[str, ...]
    abstract: bool
    fields: tuple[str, ...]
    attributes: tuple[str, ...]
    field_types: tuple[AstFieldSchema, ...]


@dataclass(frozen=True, slots=True)
class SourceSyntaxProfile:
    runtime: SourceBytesProfile
    api: str
    flags: int
    dont_inherit: bool
    optimize: int
    feature_version: int
    int_max_str_digits: int
    recursion_limit: int
    coordinate_basis: str
    warning_policy: str
    ast_sha256: str
    parser_origin: str
    parser_binary: str
    parser_sha256: str
    ast_schema: tuple[AstClassSchema, ...]
    literal_policy: str
    literal_code_sha256: str
    literal_max_depth: int
    literal_max_nodes: int
    literal_payload_bytes: int
    literal_int_decimal_digits: int
    literal_int_bit_length: int


@dataclass(frozen=True, slots=True)
class SourceSyntaxInput:
    f0_document_sha256: str
    f1_document_sha256: str
    path: str
    raw_sha256: str
    view_sha256: str | None
    f1_status: str


@dataclass(frozen=True, slots=True)
class AstValue:
    kind: str
    reference: int | None
    items: tuple['AstValue', ...]
    scalar: PythonLiteral | None

    def __post_init__(self):
        if self.kind == 'NODE':
            valid = type(self.reference) is int and self.reference >= 0 and not self.items and self.scalar is None
        elif self.kind == 'LIST':
            valid = self.reference is None and self.scalar is None
        elif self.kind == 'SCALAR':
            valid = self.reference is None and not self.items and type(self.scalar) is PythonLiteral
        else:
            valid = self.kind == 'ABSENT' and self.reference is None and not self.items and self.scalar is None
        if not valid:
            raise ValueError('invalid F2 AST value variant')


@dataclass(frozen=True, slots=True)
class AstOccurrence:
    constructor: str
    fields: tuple[AstValue, ...]
    attributes: tuple[AstValue, ...]


@dataclass(frozen=True, slots=True)
class SyntaxFrontier:
    code: str
    path: str
    detail: str


@dataclass(frozen=True, slots=True)
class SourceSyntaxMaterial:
    input: SourceSyntaxInput
    profile: SourceSyntaxProfile
    mode: str
    max_nodes: int
    status: str
    root: int | None
    nodes: tuple[AstOccurrence, ...]
    frontiers: tuple[SyntaxFrontier, ...]
    error: SourceTokenError | None
    warnings: tuple[SourceTokenWarning, ...]
    schema: str = 'scar.source-syntax'
    schema_version: int = 1

    def __post_init__(self):
        if (self.schema != 'scar.source-syntax' or type(self.schema_version) is not int or self.schema_version != 1
                or self.mode not in ('exec', 'eval', 'single', 'func_type')
                or type(self.max_nodes) is not int or self.max_nodes < 0
                or self.status not in ('PARSED', 'PARSER_ERROR', 'PARSER_RESOURCE_ERROR', 'BUDGET_STOPPED', 'UPSTREAM_NOT_TOKENIZED')):
            raise ValueError('invalid F2 document envelope')
        if self.status == 'PARSED':
            valid = type(self.root) is int and 0 <= self.root < len(self.nodes) and not self.frontiers and self.error is None
        else:
            valid = self.root is None and not self.nodes
            if self.status == 'BUDGET_STOPPED':
                valid = valid and bool(self.frontiers) and self.error is None
            elif self.status in ('PARSER_ERROR', 'PARSER_RESOURCE_ERROR'):
                valid = valid and self.error is not None and not self.frontiers
            else:
                valid = valid and self.error is None and not self.frontiers and not self.warnings
        if not valid:
            raise ValueError('F2 status contradicts its recorded tree/diagnostics')
