"""Source-derived compiler symbol provenance in one compilation namespace."""
from dataclasses import dataclass
import re

from .compiler_symbols import CompilerSymbolsMaterial


@dataclass(frozen=True, slots=True)
class SourceCompilerSymbolVariant:
    namespace: str
    context_variant_sha256: str
    context_material_sha256: str
    binding_variant_sha256: str
    binding_material_sha256: str
    native_variant_sha256: str
    topology_variant_sha256: str
    material: CompilerSymbolsMaterial
    schema: str = 'scar.source-compiler-symbol-variant'
    schema_version: int = 1
    discharges: tuple[str, ...] = (
        'CONTEXT_QUALIFIED_SYMBOL_ORIGIN_AND_PARAMETER_PROJECTION_NOT_BUILT',
    )
    obligations: tuple[str, ...] = ('CONTEXT_QUALIFIED_F4_BODY_NOT_BUILT',)

    def __post_init__(self):
        digests = (self.namespace, self.context_variant_sha256, self.context_material_sha256,
            self.binding_variant_sha256, self.binding_material_sha256,
            self.native_variant_sha256, self.topology_variant_sha256)
        if (any(type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None for value in digests)
                or self.schema != 'scar.source-compiler-symbol-variant'
                or type(self.schema_version) is not int or self.schema_version != 1
                or self.material.status != 'PROJECTED'
                or self.material.input.c1_document_sha256 != self.context_material_sha256):
            raise ValueError('compiler symbol variant requires a complete context-qualified projection')
