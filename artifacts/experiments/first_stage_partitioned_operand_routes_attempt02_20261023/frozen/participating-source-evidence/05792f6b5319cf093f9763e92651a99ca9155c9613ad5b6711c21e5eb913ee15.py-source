"""Source inventory overlay: definitions and execution phases, not runtime facts."""
from dataclasses import dataclass
from enum import Enum

from scar.ir.program.model import ProgramGraph
from scar.ir.program.source import LoweringMetadata
from scar.ir.program.functions import ParameterKind
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import BindingUseID, OperationDefinitionID


class DefinitionKind(str, Enum):
    FUNCTION = "FUNCTION"
    ASYNC_FUNCTION = "ASYNC_FUNCTION"
    CLASS = "CLASS"
    LAMBDA = "LAMBDA"
    COMPREHENSION = "COMPREHENSION"


class ExecutionPhase(str, Enum):
    MODULE_INITIALIZATION = "MODULE_INITIALIZATION"
    FUNCTION_BODY = "FUNCTION_BODY"
    CLASS_BODY = "CLASS_BODY"
    COMPREHENSION_BODY = "COMPREHENSION_BODY"
    ANNOTATION = "ANNOTATION"


class DefinitionInputRole(str, Enum):
    DEFAULT = "DEFAULT"
    KEYWORD_DEFAULT = "KEYWORD_DEFAULT"
    DECORATOR = "DECORATOR"
    ANNOTATION = "ANNOTATION"
    BASE = "BASE"
    METACLASS = "METACLASS"
    CLASS_KEYWORD = "CLASS_KEYWORD"


class CoverageStatus(str, Enum):
    CONNECTED = "CONNECTED"
    INVENTORY_ONLY = "INVENTORY_ONLY"
    UNSUPPORTED = "UNSUPPORTED"


class BodyStatus(str, Enum):
    LOWERED_WITH_GAPS = "LOWERED_WITH_GAPS"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


class CandidateCondition(str, Enum):
    SOURCE_BINDING_REACHES_READ = "SOURCE_BINDING_REACHES_READ"
    SOURCE_BODY_MATCHES_LIVE_CALLABLE = "SOURCE_BODY_MATCHES_LIVE_CALLABLE"
    LOADER_AND_PACKAGE_CONTEXT = "LOADER_AND_PACKAGE_CONTEXT"
    EXPORT_NAMESPACE = "EXPORT_NAMESPACE"
    ATTRIBUTE_LOOKUP = "ATTRIBUTE_LOOKUP"
    NO_EXTERNAL_NAMESPACE_MUTATION = "NO_EXTERNAL_NAMESPACE_MUTATION"


@dataclass(frozen=True, slots=True)
class DefinitionInput:
    role: DefinitionInputRole
    index: int
    source: SourceReference


@dataclass(frozen=True, slots=True)
class ParameterInventory:
    name: str
    kind: ParameterKind
    source: SourceReference
    default: SourceReference | None = None
    annotation: SourceReference | None = None


@dataclass(frozen=True, slots=True)
class DefinitionInventory:
    id: OperationDefinitionID
    source: SourceReference
    name: str
    qualname: str
    kind: DefinitionKind
    lexical_owner: OperationDefinitionID | None
    parameters: tuple[ParameterInventory, ...] = ()
    definition_inputs: tuple[DefinitionInput, ...] = ()
    body_supported: bool = False


@dataclass(frozen=True, slots=True)
class ImportBindingWitness:
    source: SourceReference
    bound_name: str
    requested: str
    symbol: str | None
    asname: str | None = None


@dataclass(frozen=True, slots=True)
class CallCandidateWitness:
    definition: OperationDefinitionID
    target_source: SourceReference
    through_imports: tuple[SourceReference, ...]
    conditions: tuple[CandidateCondition, ...]


@dataclass(frozen=True, slots=True)
class CallInventory:
    operation: OperationDefinitionID
    source: SourceReference
    execution_owner: OperationDefinitionID
    phase: ExecutionPhase
    candidates: tuple[OperationDefinitionID, ...] = ()
    semantic_operation: OperationDefinitionID | None = None
    callee_binding: BindingUseID | None = None
    import_bindings: tuple[ImportBindingWitness, ...] = ()
    attribute_path: tuple[str, ...] = ()
    candidate_witnesses: tuple[CallCandidateWitness, ...] = ()


@dataclass(frozen=True, slots=True)
class ImplicitInvocation:
    """Interfaces with no standalone ast.Call; actual target/effects unverified."""
    source: SourceReference
    definition: OperationDefinitionID
    execution_owner: OperationDefinitionID
    phase: ExecutionPhase
    role: str


@dataclass(frozen=True, slots=True)
class CoverageEntry:
    source: SourceReference
    owner: OperationDefinitionID
    phase: ExecutionPhase
    ast_kind: str
    status: CoverageStatus
    reason: str


@dataclass(frozen=True, slots=True)
class BodyInventory:
    definition: OperationDefinitionID
    status: BodyStatus
    graph: ProgramGraph | None
    metadata: LoweringMetadata | None
    reason: str
    construction_operations: int = 0


@dataclass(frozen=True, slots=True)
class InventoryIssue:
    path: str
    detail: str
    source: SourceReference | None = None


@dataclass(frozen=True, slots=True)
class SourceContextDigest:
    namespace_root: str
    semantic_sha256: str
    semantics_sha256: str
    control_sha256: str


@dataclass(frozen=True, slots=True)
class FileInventory:
    snapshot: SourceSnapshot
    definitions: tuple[DefinitionInventory, ...]
    calls: tuple[CallInventory, ...]
    coverage: tuple[CoverageEntry, ...]
    bodies: tuple[BodyInventory, ...]
    gaps: tuple[InventoryIssue, ...]
    context: SourceContextDigest | None = None
    implicit_invocations: tuple[ImplicitInvocation, ...] = ()


@dataclass(frozen=True, slots=True)
class InventoryBudget:
    max_files: int = 128
    max_bytes: int = 8_000_000
    max_directories: int = 4096
    max_lowered_bodies: int = 256
    max_operations: int = 10000
    max_call_witnesses: int = 4096
