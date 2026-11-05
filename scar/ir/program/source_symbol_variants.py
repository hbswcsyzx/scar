"""Context-qualified official symbol views; native scope/AST joins stay open."""
from dataclasses import dataclass

from .source_compiled_values import EffectiveCompileContext
from .source_references import SourceArtifactLocator
from .source_symbols import SourceSymbolsMaterial
from .source_text import TextOpenInterpretation


@dataclass(frozen=True, slots=True)
class SymbolAdapterReceipt:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class SymbolSourceParent:
    name: str
    source: SourceArtifactLocator
    document_sha256: str


@dataclass(frozen=True, slots=True)
class SymbolTextInput:
    source: SourceArtifactLocator
    f0_document_sha256: str
    raw_sha256: str
    raw_bytes: int
    interpretation: TextOpenInterpretation
    text_utf8_sha256: str
    characters: int
    conditions: tuple[str, ...]
    obligations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SymbolContextRequest:
    text_utf8_sha256: str
    characters: int
    filename: str
    mode: str
    requested_flags: int
    dont_inherit: bool
    inherited_future_flags: int
    effective_flags: int
    caller_flag_merging: str = 'EXPLICIT_ONLY_NO_PYTHON_CALLER_INHERITANCE'
    optimize_policy: str = 'OFFICIAL_SYMTABLE_BEFORE_OPTIMIZATION_NO_OPTIMIZE_ARGUMENT'


@dataclass(frozen=True, slots=True)
class SourceSymbolVariant:
    namespace: str
    source_unit: str
    context_document_sha256: str
    context_material_sha256: str
    context: EffectiveCompileContext
    parents: tuple[SymbolSourceParent, ...]
    text_inputs: tuple[SymbolTextInput, ...]
    request: SymbolContextRequest
    adapter: SymbolAdapterReceipt
    material: SourceSymbolsMaterial
    discharged: tuple[str, ...] = ('CONTEXT_QUALIFIED_NATIVE_SYMBOL_VIEW_NOT_CAPTURED',)
    obligations: tuple[str, ...] = (
        'CONTEXT_QUALIFIED_DECLARATIONS_AND_BINDINGS_NOT_BUILT',
        'CONTEXT_QUALIFIED_SYMBOL_AST_CORRESPONDENCE_NOT_ESTABLISHED',
        'CONTEXT_QUALIFIED_F4_BODY_NOT_BUILT',
    )
    schema: str = 'scar.source-symbol-variant'
    schema_version: int = 1

    def __post_init__(self):
        if (self.schema != 'scar.source-symbol-variant' or self.schema_version != 1
                or self.material.status != 'CAPTURED' or not self.text_inputs
                or self.material.authority != 'PUBLIC_COMPILER_VIEW'
                or self.material.ast_join != 'UNJOINED'
                or self.material.complete_lexical_scopes):
            raise ValueError('context symbol variant must remain a captured unjoined compiler view')
