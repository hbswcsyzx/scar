"""Context-qualified source declarations and namespace templates."""
from dataclasses import dataclass

from .source_declarations import SourceDeclarationsMaterial
from .source_bindings import SourceBindingsMaterial


@dataclass(frozen=True, slots=True)
class SourceBindingVariant:
    namespace: str
    context_material_sha256: str
    declarations: SourceDeclarationsMaterial
    bindings: SourceBindingsMaterial
    schema: str = 'scar.source-binding-variant'
    schema_version: int = 1
    discharges: tuple[str, ...] = ('CONTEXT_QUALIFIED_DECLARATIONS_AND_BINDINGS_NOT_BUILT',)
    obligations: tuple[str, ...] = (
        'CONTEXT_QUALIFIED_NATIVE_SYMBOL_VIEW_NOT_CAPTURED',
        'CONTEXT_QUALIFIED_F4_BODY_NOT_BUILT',
    )
