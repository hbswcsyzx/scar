"""Static deferred-object and iterator-driver relations, not runtime frames."""
from dataclasses import dataclass

from . import normal_links as F, normal_targets as T, source_productions as P
from .suspension_interfaces import StepWitness
from scar.ir.literals import PythonLiteral


@dataclass(frozen=True, slots=True)
class DeferredOrigin:
    result: T.Endpoint | None
    source_callable: T.GlobalPort
    receiver: T.Endpoint | None
    class_receiver: T.GlobalPort | None
    world: T.Endpoint
    environment: tuple[T.Endpoint, ...] = ()


@dataclass(frozen=True, slots=True)
class DeferredCreation:
    origin: DeferredOrigin
    kind: P.DeferredBodyKind
    body_scope: F.CodeScopeWitness
    connection: T.FunctionConnection
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GeneratorIterator:
    origin: DeferredOrigin
    iteration: StepWitness
    result: T.GlobalPort
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GeneratorYield:
    suspension: StepWitness
    exported: T.GlobalPort
    item: T.GlobalPort
    world: T.GlobalPort
    result_world: T.GlobalPort
    sent: T.GlobalPort
    resume_world: T.GlobalPort
    sent_literal: PythonLiteral
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GeneratorExhaustion:
    value: T.GlobalPort | None
    world: T.GlobalPort | None
    exception: T.GlobalPort | None
    result_world: T.GlobalPort | None
    # A protocol transformation, never a value-to-item or value-to-exception alias.
    semantics: str = 'NORMAL_RETURN_AS_STOP_ITERATION_VALUE'
    conditions: tuple[str, ...] = ('GENERATOR_COMPLETES_NORMALLY',)


@dataclass(frozen=True, slots=True)
class GeneratorAdvance:
    origin: DeferredOrigin
    iteration: StepWitness
    connection: T.FunctionConnection
    yielded: tuple[GeneratorYield, ...]
    exhaustion: GeneratorExhaustion | None
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeferredDriverObligation:
    origin: DeferredOrigin
    iteration: StepWitness | None
    reason: str
    site: T.Endpoint | None = None
    conditions: tuple[str, ...] = ('DRIVER_OR_INTERFACE_NOT_CONNECTED',)
