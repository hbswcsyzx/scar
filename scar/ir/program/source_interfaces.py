"""Local interfaces projected from sealed F4/F5 inputs, not runtime facts."""
from dataclasses import dataclass

from . import suspension_interfaces as S
from .normal_targets import GlobalPort
from .source_template_links import SourceTemplateKey


@dataclass(frozen=True, slots=True)
class IterationInterface:
    fact: int
    site: S.IterationSite


@dataclass(frozen=True, slots=True)
class DeferredInterface:
    fact: int
    site: S.DeferredBodySite


@dataclass(frozen=True, slots=True)
class MappingMergeInterface:
    witness: S.StepWitness
    callee: GlobalPort
    target: GlobalPort
    source: GlobalPort
    world: GlobalPort
    completions: tuple[S.CompletionPorts, ...]
    target_index: int | None
    source_index: int | None


@dataclass(frozen=True, slots=True)
class MappingTemplateInterface:
    template: SourceTemplateKey
    plan_sha256: str
    straight_line: bool
    merges: tuple[MappingMergeInterface, ...]


@dataclass(frozen=True, slots=True)
class UnitSourceInterfaces:
    unit: str
    iterations: tuple[IterationInterface, ...]
    bodies: tuple[DeferredInterface, ...]
    mappings: tuple[MappingTemplateInterface, ...]
