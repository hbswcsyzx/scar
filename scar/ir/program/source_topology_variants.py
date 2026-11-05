"""Compiler/source scope correspondence in one compilation namespace."""
from dataclasses import dataclass

from .compiler_topology import CompilerTopologyMaterial


@dataclass(frozen=True, slots=True)
class SourceTopologyVariant:
    namespace: str
    context_material_sha256: str
    native_variant_sha256: str
    material: CompilerTopologyMaterial
    schema: str = 'scar.source-topology-variant'
    schema_version: int = 1
    discharges: tuple[str, ...] = ('CONTEXT_QUALIFIED_SYMBOL_AST_CORRESPONDENCE_NOT_ESTABLISHED',)
    obligations: tuple[str, ...] = (
        'CONTEXT_QUALIFIED_SYMBOL_ORIGIN_AND_PARAMETER_PROJECTION_NOT_BUILT',
        'CONTEXT_QUALIFIED_F4_BODY_NOT_BUILT',
    )
