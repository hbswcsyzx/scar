"""F3-A official public compiler scope facts; AST correspondence is separate."""
from dataclasses import dataclass

from .source_bytes import SourceBytesProfile
from .source_tokens import SourceTokenError, SourceTokenWarning


@dataclass(frozen=True, slots=True)
class SymbolConstant:
    name: str
    value: int


@dataclass(frozen=True, slots=True)
class RawScopeMember:
    name: str
    value_type: str
    persistence: str


@dataclass(frozen=True, slots=True)
class SourceSymbolsProfile:
    runtime: SourceBytesProfile
    api: str
    abi_tag: str
    abiflags: str
    pointer_bits: int
    byteorder: str
    native_origin: str
    native_binary: str
    native_sha256: str
    symtable_sha256: str
    constants: tuple[SymbolConstant, ...]
    raw_members: tuple[RawScopeMember, ...]
    int_max_str_digits: int
    recursion_limit: int
    hash_randomization: int
    hash_context_sha256: str
    warning_policy: str
    source_view_policy: str
    caller_future_policy: str
    source_future_policy: str
    f2_relation: str
    identity_policy: str
    ordering_policy: str
    unknown_flags_policy: str


@dataclass(frozen=True, slots=True)
class SourceSymbolsInput:
    f0_document_sha256: str
    f1_document_sha256: str
    f2_document_sha256: str
    path: str
    view_sha256: str | None
    f2_status: str


@dataclass(frozen=True, slots=True)
class SourceSymbol:
    name: str
    flags: int

    def __post_init__(self):
        if type(self.name) is not str or type(self.flags) is not int or self.flags < 0:
            raise ValueError('invalid original compiler symbol name/flag word')


@dataclass(frozen=True, slots=True)
class SourceScope:
    type: int
    name: str
    lineno: int
    nested: int
    varnames: tuple[str, ...]
    symbols: tuple[SourceSymbol, ...]
    children: tuple[int, ...]

    def __post_init__(self):
        if (type(self.type) is not int or type(self.name) is not str
                or type(self.lineno) is not int or type(self.nested) is not int or self.nested not in (0, 1)
                or any(type(n) is not str for n in self.varnames)
                or any(type(s) is not SourceSymbol for s in self.symbols)
                or len({s.name for s in self.symbols}) != len(self.symbols)
                or any(type(ref) is not int or ref < 0 for ref in self.children)):
            raise ValueError('invalid public compiler scope row')


@dataclass(frozen=True, slots=True)
class SymbolFrontier:
    code: str
    scope: int | None
    path: tuple[int, ...]
    symbol: str | None
    raw_value: int | None
    detail: str


@dataclass(frozen=True, slots=True)
class SourceSymbolsMaterial:
    input: SourceSymbolsInput
    profile: SourceSymbolsProfile
    mode: str
    max_scopes: int
    max_symbols: int
    status: str
    root: int | None
    scopes: tuple[SourceScope, ...]
    frontiers: tuple[SymbolFrontier, ...]
    error: SourceTokenError | None
    warnings: tuple[SourceTokenWarning, ...]
    authority: str = 'PUBLIC_COMPILER_VIEW'
    ast_join: str = 'UNJOINED'
    complete_lexical_scopes: bool = False
    schema: str = 'scar.source-symbols'
    schema_version: int = 1

    def __post_init__(self):
        if (self.schema != 'scar.source-symbols' or type(self.schema_version) is not int or self.schema_version != 1
                or self.authority != 'PUBLIC_COMPILER_VIEW' or self.ast_join != 'UNJOINED'
                or type(self.complete_lexical_scopes) is not bool or self.complete_lexical_scopes
                or self.mode not in ('exec', 'eval', 'single', 'func_type')
                or any(type(n) is not int or n < 0 for n in (self.max_scopes, self.max_symbols))
                or self.status not in ('CAPTURED', 'UPSTREAM_NOT_PARSED', 'UNSUPPORTED_SYMTABLE_MODE',
                    'SYMBOL_TABLE_ERROR', 'RESOURCE_ERROR', 'BUDGET_STOPPED')):
            raise ValueError('invalid F3-A public scope envelope')
        if self.status == 'CAPTURED':
            valid = type(self.root) is int and self.root == 0 and bool(self.scopes) and self.error is None
        else:
            valid = self.root is None and not self.scopes
            if self.status == 'BUDGET_STOPPED':
                valid = valid and bool(self.frontiers) and self.error is None
            elif self.status in ('SYMBOL_TABLE_ERROR', 'RESOURCE_ERROR'):
                valid = valid and self.error is not None and not self.frontiers
            else:
                valid = valid and self.error is None and not self.frontiers and not self.warnings
        if not valid:
            raise ValueError('F3-A status contradicts scope facts/diagnostics')
