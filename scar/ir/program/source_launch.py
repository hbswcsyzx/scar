"""Declared script inputs and compilation context over original source IDs.

These records describe entry assumptions, not a process observation. Mutable
argv/environment are input locations with initial contents, never immutable
tuple/dict objects. Compilation alone does not activate a source body.
"""
from dataclasses import dataclass

from scar.ir.literals import PythonLiteral
from .normal_links import CodeScopeWitness, Namespace
from .normal_targets import GlobalPort
from .source_bytes import SourceBytesProfile


@dataclass(frozen=True, slots=True)
class EntrySourceSnapshot:
    unit: str
    path: str
    model: str
    manifest_sha256: str
    f0_document_sha256: str
    f2_document_sha256: str
    raw_sha256: str
    raw_bytes: int
    runtime: SourceBytesProfile


@dataclass(frozen=True, slots=True)
class SourceCompilationContext:
    filename: str
    mode: str
    requested_flags: int
    dont_inherit: bool
    inherited_future_flags: int | None
    source_future_flags: int
    optimize: int | None

    def __post_init__(self):
        if self.mode not in ('exec', 'eval', 'single'):
            raise ValueError('an executable compilation mode is required')
        if (type(self.requested_flags) is not int or self.requested_flags < 0
                or type(self.source_future_flags) is not int or self.source_future_flags < 0
                or type(self.dont_inherit) is not bool
                or self.inherited_future_flags is not None and (
                    type(self.inherited_future_flags) is not int or self.inherited_future_flags < 0)
                or self.optimize is not None and (
                    type(self.optimize) is not int or self.optimize not in (0, 1, 2))):
            raise ValueError('invalid compilation fields; None means an unresolved field')

    @property
    def effective_flags(self):
        if not self.dont_inherit and self.inherited_future_flags is None:
            return None
        inherited = 0 if self.dont_inherit else self.inherited_future_flags
        return self.requested_flags | self.source_future_flags | inherited


@dataclass(frozen=True, slots=True)
class InitialEnvironmentEntry:
    name: str
    value: str | None
    # None is explicitly absent. Unlisted names are unknown unless the
    # enclosing launch declares its environment complete.


@dataclass(frozen=True, slots=True)
class ScriptLaunchInputs:
    cwd: str
    argv: tuple[str, ...]
    environment: tuple[InitialEnvironmentEntry, ...] = ()
    environment_complete: bool = False
    executable: str | None = None
    argv_mutable: bool = True
    environment_mutable: bool = True

    def __post_init__(self):
        if (type(self.argv) is not tuple or not self.argv
                or any(type(a) is not str for a in self.argv)
                or type(self.environment) is not tuple
                or any(type(e) is not InitialEnvironmentEntry for e in self.environment)
                or len({e.name for e in self.environment}) != len(self.environment)
                or not self.argv_mutable or not self.environment_mutable):
            raise ValueError('script input locations require explicit initial contents')


@dataclass(frozen=True, slots=True)
class EntryGlobalBinding:
    namespace: Namespace
    literal: PythonLiteral
    reads: tuple[GlobalPort, ...]
    semantics: str = 'CONDITIONAL_INITIAL_NAMESPACE_CONTENT'


@dataclass(frozen=True, slots=True)
class ScriptEntryContract:
    source: EntrySourceSnapshot
    root: CodeScopeWitness
    compilation: SourceCompilationContext
    inputs: ScriptLaunchInputs
    globals: tuple[EntryGlobalBinding, ...]
    source_future_features: tuple[str, ...]
    future_catalog_sha256: str
    conditions: tuple[str, ...] = (
        'DECLARED_SCRIPT_LAUNCH_INPUTS',
        'STANDARD_SCRIPT_LAUNCH_INITIALIZATION',
        'NO_STARTUP_MUTATION_OF_ENTRY_GLOBALS',
        'ORIGINAL_SOURCE_VERSION_SELECTED',
    )
    semantics: str = 'STATIC_ENTRY_CONTRACT_NOT_RUNTIME_CAPTURE'
