"""Local template interfaces; bodies remain in their sealed source materials.

All identities are qualified by the graph's original source input. These are
static call sites and port bindings, never runtime activations or canonical IR.
"""
from dataclasses import dataclass
from enum import Enum

from .source_productions import (ProductionPurpose, ProductionRegionID,
    ProductionStepID, ProductionValue, ProductionCompletion, SourceProductionProfile,
    ProductionInput)
from .signature_patterns import GroundType


class SourceMaterialDomain(str, Enum):
    EXPRESSIONS = 'expressions'
    STATEMENTS = 'statements'
    ROOTS = 'roots'


@dataclass(frozen=True, slots=True)
class SourceTemplateKey:
    occurrence: int
    purpose: ProductionPurpose

    def __post_init__(self):
        if type(self.occurrence) is not int or self.occurrence < 0 or type(self.purpose) is not ProductionPurpose:
            raise ValueError('template key requires an original occurrence and exact evaluation purpose')


@dataclass(frozen=True, slots=True)
class SourceTemplateOrigin:
    domain: SourceMaterialDomain
    line: int
    plan_sha256: str


@dataclass(frozen=True, slots=True)
class SourceTemplateNode:
    key: SourceTemplateKey
    root: ProductionRegionID
    parameters: tuple[GroundType, ...]
    completions: tuple[ProductionCompletion, ...]
    origin: SourceTemplateOrigin


@dataclass(frozen=True, slots=True)
class SourceTemplateLink:
    """Argument ordinal binds the same callee parameter ordinal.

    Completion ports bind by (kind, control target, ordinal); the caller may
    advertise a conservative superset. The step also identifies the existing
    compilation-context qualification edge. No template body is copied.
    """
    caller: SourceTemplateKey
    step: ProductionStepID
    callee: SourceTemplateKey
    arguments: tuple[ProductionValue, ...]


@dataclass(frozen=True, slots=True)
class SourceTemplateGraph:
    unit: str
    input: ProductionInput
    profile: SourceProductionProfile
    templates: tuple[SourceTemplateNode, ...]
    links: tuple[SourceTemplateLink, ...]
    schema: str = 'scar.source-template-links'
    schema_version: int = 1
    authority: str = 'SOURCE_TEMPLATE_INTERFACES_ONLY'
