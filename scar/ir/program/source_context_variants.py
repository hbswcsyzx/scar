"""C1 context namespaces over unchanged source and syntax materials."""
from dataclasses import dataclass

from .source_contexts import SourceContextsMaterial
from .source_compiled_values import EffectiveCompileContext


@dataclass(frozen=True, slots=True)
class SourceContextVariant:
    namespace: str
    source_unit: str
    context: EffectiveCompileContext
    text_utf8_sha256: str
    code_digest: str
    ast_correspondence_sha256: str
    material: SourceContextsMaterial
    schema: str = 'scar.source-context-variant'
    schema_version: int = 1
    obligations: tuple[str, ...] = (
        'CONTEXT_QUALIFIED_DECLARATIONS_AND_BINDINGS_NOT_BUILT',
        'CONTEXT_QUALIFIED_NATIVE_SYMBOL_VIEW_NOT_CAPTURED',
        'CONTEXT_QUALIFIED_F4_BODY_NOT_BUILT',
    )
