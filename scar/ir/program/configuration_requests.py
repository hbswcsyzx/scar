"""Conditional library input requests anchored to original program ports."""
from dataclasses import dataclass

from scar.ir.literals import PythonLiteral
from .normal_targets import GlobalPort
from .source_frame_bindings import ContextEndpoint
from .providers import ProviderArtifact,ProviderFactReference


@dataclass(frozen=True,slots=True)
class ConfigurationLiteralCandidate:
    source: ContextEndpoint
    literal: PythonLiteral
    derivation: str
    alias_rows: tuple[int,...] = ()


@dataclass(frozen=True,slots=True)
class ConfigurationParameter:
    name: str
    formal: GlobalPort
    actuals: tuple[ContextEndpoint,...]
    candidates: tuple[ConfigurationLiteralCandidate,...]
    obligation: str | None


@dataclass(frozen=True,slots=True)
class ConfigurationOption:
    option: str
    candidate: ConfigurationLiteralCandidate
    argv_index: int


@dataclass(frozen=True,slots=True)
class ConfigurationSourceCandidate:
    protocol: str
    root: str | None
    name: str | None
    resource: str | None
    code_filename: str
    conditions: tuple[str,...]


@dataclass(frozen=True,slots=True)
class ConfigurationTaskAssociation:
    task_creation: GlobalPort
    decorator_result: GlobalPort
    factory_to_callee_alias_rows: tuple[int,...]
    task_to_argument_alias_rows: tuple[int,...]


@dataclass(frozen=True,slots=True)
class ConfigurationRequest:
    id: str
    protocol: str
    api: GlobalPort
    api_source: ProviderArtifact
    api_function_ast_sha256: str
    factory_result: GlobalPort
    call_reference: ProviderFactReference
    parameters: tuple[ConfigurationParameter,...]
    task_associations: tuple[ConfigurationTaskAssociation,...]
    initial_options: tuple[ConfigurationOption,...]
    sources: tuple[ConfigurationSourceCandidate,...]
    conditions: tuple[str,...]
    obligations: tuple[str,...]
    semantics: str = 'CONDITIONAL_REQUEST_CANDIDATES_NOT_CURRENT_ARGV_OR_COMPOSED_CFG'
