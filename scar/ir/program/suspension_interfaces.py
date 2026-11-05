"""Original deferred/iteration interfaces, without asserting driver execution."""
from dataclasses import dataclass
from enum import Enum
import re

from . import source_productions as P
from .control import LanguageCompletionKind
from .normal_links import CodeScopeRef, CodeScopeWitness
from .normal_targets import GlobalPort
from .protocol_signatures import ExceptionABI
from .source_template_links import SourceTemplateKey
from .structured import PythonProtocolKind


class WitnessSource(str, Enum):
    SEALED_TEMPLATE_STORE = 'SEALED_TEMPLATE_STORE'
    CONTROLLED_PLAN_PROVIDER = 'CONTROLLED_PLAN_PROVIDER'


class DriverObligation(str, Enum):
    NOT_SYNCHRONOUS_GENERATOR = 'NOT_SYNCHRONOUS_GENERATOR'
    YIELD_FROM_DRIVER_REQUIRED = 'YIELD_FROM_DRIVER_REQUIRED'
    AWAIT_DRIVER_REQUIRED = 'AWAIT_DRIVER_REQUIRED'
    ASYNC_GENERATOR_DRIVER_REQUIRED = 'ASYNC_GENERATOR_DRIVER_REQUIRED'


@dataclass(frozen=True, slots=True)
class StepWitness:
    unit: str
    template: SourceTemplateKey
    plan_sha256: str
    step: P.ProductionStepID
    region: P.ProductionRegionID
    owner: CodeScopeRef
    source: WitnessSource
    template_result_sha256: str | None = None
    model_manifest_sha256: str | None = None

    def __post_init__(self):
        if self.owner.unit != self.unit:
            raise ValueError('suspension witness owner belongs to another source unit')
        for digest in (self.plan_sha256, self.template_result_sha256, self.model_manifest_sha256):
            if digest is not None and re.fullmatch('[0-9a-f]{64}', digest) is None:
                raise ValueError('interface witness requires an exact SHA256')
        if type(self.source) is not WitnessSource:
            raise TypeError('interface witness source must be explicit')
        sealed = self.source is WitnessSource.SEALED_TEMPLATE_STORE
        if ((sealed and (self.template_result_sha256 is None or self.model_manifest_sha256 is None))
                or (not sealed and (self.template_result_sha256 is not None or self.model_manifest_sha256 is not None))):
            raise ValueError('only a sealed witness carries its model/template receipts')


@dataclass(frozen=True, slots=True)
class CompletionPorts:
    kind: LanguageCompletionKind | P.PatternCompletionKind
    target: P.ProductionControlTarget | None
    ports: tuple[GlobalPort, ...]
    world: GlobalPort | None

    def __post_init__(self):
        if self.world is not None and self.world not in self.ports:
            raise ValueError('completion world must be one of its original ports')


@dataclass(frozen=True, slots=True)
class IterationSite:
    witness: StepWitness
    protocol: PythonProtocolKind
    source: GlobalPort
    value: GlobalPort
    world: GlobalPort
    result_world: GlobalPort
    completions: tuple[CompletionPorts, ...]


@dataclass(frozen=True, slots=True)
class ResumeSite:
    kind: LanguageCompletionKind
    region: P.ProductionRegionID
    parameters: tuple[GlobalPort, ...]
    world: GlobalPort

    @property
    def sent(self):
        return self.parameters[0] if self.kind is LanguageCompletionKind.FALLTHROUGH else None


@dataclass(frozen=True, slots=True)
class SuspensionSite:
    witness: StepWitness
    kind: P.SuspensionKind
    exported: GlobalPort
    world: GlobalPort
    resumes: tuple[ResumeSite, ...]
    saved: tuple[GlobalPort, ...]
    delegate: GlobalPort | None
    completions: tuple[CompletionPorts, ...]
    exception_abi: ExceptionABI
    obligations: tuple[DriverObligation, ...] = ()


@dataclass(frozen=True, slots=True)
class DeferredBodySite:
    body_scope: CodeScopeWitness
    kind: P.DeferredBodyKind
    source_callable: GlobalPort
    parameters: tuple[GlobalPort, ...]
    completions: tuple[CompletionPorts, ...]
    suspensions: tuple[SuspensionSite, ...]
    obligations: tuple[DriverObligation, ...] = ()


__all__ = ['WitnessSource', 'DriverObligation', 'StepWitness', 'CompletionPorts',
           'IterationSite', 'ResumeSite', 'SuspensionSite', 'DeferredBodySite']
