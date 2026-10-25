"""Proposed public API and record fields only; no runtime implementation.

Existing IR classes and IDs below retain their original codec/identity. New
dataclass union variants get fixed wire tags; record-schema.json lists them.
"""
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from typing import NewType, Protocol, TypeAlias

from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceDefinitionReference
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID
from scar.ir.execution.ids import RunID
from scar.ir.program.ids import (
    BlockID, LocationID, OperationID, RegionID, ResourceDefinitionID,
    ResourceRequirementID, UseID, ValueID,
)

Sha256 = NewType("Sha256", str)
ScopeID = NewType("ScopeID", str)
ScopeRevision = NewType("ScopeRevision", str)
ObligationID = NewType("ObligationID", str)
DenominatorID = NewType("DenominatorID", str)

class Encoding(str, Enum):
    JSON = "JSON"
    GZIP_JSON = "GZIP_JSON"
    JSONL = "JSONL"
    GZIP_JSONL = "GZIP_JSONL"
    TEXT = "TEXT"
    GZIP_TEXT = "GZIP_TEXT"

@dataclass(frozen=True)
class RetainedArtifact:
    original: ProviderArtifact
    decoded_sha256: Sha256
    decoded_bytes: int
    encoding: Encoding

@dataclass(frozen=True)
class JsonRecordRef:
    artifact: RetainedArtifact
    pointer: str

@dataclass(frozen=True)
class JsonlRecordRef:
    artifact: RetainedArtifact
    line: int
    line_sha256: Sha256
    pointer: str

@dataclass(frozen=True)
class PartitionRecordRef:
    manifest_chunk: JsonRecordRef
    table: str
    ordinal: int
    line: int
    line_sha256: Sha256
    pointer: str

@dataclass(frozen=True)
class TextRangeRef:
    artifact: RetainedArtifact
    first_line: int
    last_line: int
    range_sha256: Sha256

EvidenceLocator: TypeAlias = JsonRecordRef | JsonlRecordRef | PartitionRecordRef | TextRangeRef

# Exactly the existing namespace/qualified_reference shape; this helper only
# gives the existing public dictionary a type, without assigning another ID.
@dataclass(frozen=True)
class OriginalNamespaceArtifact:
    uri: str
    decoded_sha256: Sha256

@dataclass(frozen=True)
class OriginalBodyIdentity:
    definition: OperationDefinitionID
    source: SourceReference | None
    entry: str

@dataclass(frozen=True)
class OriginalGraphNamespace:
    artifact: OriginalNamespaceArtifact
    representation: str
    record_pointer: str
    body: OriginalBodyIdentity

CanonicalProgramID: TypeAlias = (
    BlockID | LocationID | OperationID | RegionID | ResourceDefinitionID |
    ResourceRequirementID | UseID | ValueID
)

@dataclass(frozen=True)
class QualifiedProgramReference:
    namespace: OriginalGraphNamespace
    kind: str
    local_id: CanonicalProgramID

class CollectionProfile(str, Enum):
    PARTITIONED_SOURCE_DEFINITIONS_V1_V2 = "PARTITIONED_SOURCE_DEFINITIONS_V1_V2"
    PARTITIONED_SOURCE_CONSTRUCTS_V1_V2 = "PARTITIONED_SOURCE_CONSTRUCTS_V1_V2"
    SOURCE_INVOCATION_ROWS_V1_V3 = "SOURCE_INVOCATION_ROWS_V1_V3"
    SOURCE_ORPHAN_EXIT_ROWS_V1_V3 = "SOURCE_ORPHAN_EXIT_ROWS_V1_V3"
    DISPATCH_MARKER_OBSERVATIONS_V1 = "DISPATCH_MARKER_OBSERVATIONS_V1"
    DISPATCH_GROUP_INVENTORY_V2 = "DISPATCH_GROUP_INVENTORY_V2"
    NATIVE_EVIDENCE_INSTANCES_V3_V6 = "NATIVE_EVIDENCE_INSTANCES_V3_V6"
    NATIVE_OBJECTS_V1_V2 = "NATIVE_OBJECTS_V1_V2"
    NATIVE_ALLOCATIONS_V1_V2 = "NATIVE_ALLOCATIONS_V1_V2"
    NATIVE_REGIONS_V1_V2 = "NATIVE_REGIONS_V1_V2"
    OS_INTERFACE_TABLE_V1 = "OS_INTERFACE_TABLE_V1"
    CAPTURE_MEMBERSHIP_V1 = "CAPTURE_MEMBERSHIP_V1"

@dataclass(frozen=True)
class CollectionLocator:
    record: JsonRecordRef
    profile: CollectionProfile

@dataclass(frozen=True)
class SourceDefinitionSubject:
    reference: SourceDefinitionReference

@dataclass(frozen=True)
class QualifiedEntitySubject:
    reference: QualifiedProgramReference
    record: EvidenceLocator

@dataclass(frozen=True)
class ArtifactRecordSubject:
    record: EvidenceLocator

@dataclass(frozen=True)
class CollectionSubject:
    collection: CollectionLocator

CoverageSubject: TypeAlias = (
    SourceDefinitionSubject | QualifiedEntitySubject | ArtifactRecordSubject |
    CollectionSubject
)

class ScopeFieldKind(str, Enum):
    ARGV = "ARGV"
    CWD = "CWD"
    CODE_VERSIONS = "CODE_VERSIONS"
    ENVIRONMENT = "ENVIRONMENT"
    CONFIGURATION = "CONFIGURATION"
    INPUT_IDENTITIES = "INPUT_IDENTITIES"
    RUN_MODE = "RUN_MODE"
    PROCESS_TREE = "PROCESS_TREE"
    CAPTURE_INTERVAL = "CAPTURE_INTERVAL"
    SOFTWARE_INTERFACES = "SOFTWARE_INTERFACES"
    HARDWARE_LAYERS = "HARDWARE_LAYERS"

class Availability(str, Enum):
    PRESENT = "PRESENT"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    CONFLICT = "CONFLICT"

class Coverage(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"

@dataclass(frozen=True)
class CoverageGap:
    code: str
    requirement_key: str
    source: EvidenceLocator
    reason: str
    missing_count: int | None

@dataclass(frozen=True)
class ScopeField:
    kind: ScopeFieldKind
    sources: tuple[EvidenceLocator, ...]
    availability: Availability
    gaps: tuple[CoverageGap, ...]

@dataclass(frozen=True)
class Observability:
    provider: str
    domain: str
    selection_source: EvidenceLocator | None
    window_source: EvidenceLocator | None
    loss_source: EvidenceLocator | None
    coverage: Coverage
    gaps: tuple[CoverageGap, ...]

@dataclass(frozen=True)
class RunBinding:
    coordinate_record: JsonRecordRef
    run: RunID

@dataclass(frozen=True)
class AnalysisScope:
    id: ScopeID
    revision: ScopeRevision
    parent: ScopeRevision | None
    contract: TextRangeRef
    policy: JsonRecordRef
    source: EvidenceLocator
    run: RunBinding
    fields: tuple[ScopeField, ...]
    observability: tuple[Observability, ...]
    denominators: tuple[DenominatorID, ...]

class Expansion(str, Enum):
    SOURCE_BODY = "SOURCE_BODY"
    PROVIDER_GRAPH = "PROVIDER_GRAPH"
    PROTOCOL_INTERFACE = "PROTOCOL_INTERFACE"
    PHYSICAL_DETAIL = "PHYSICAL_DETAIL"

class RelationKind(str, Enum):
    SOURCE_BINDING = "SOURCE_BINDING"
    ORDERED_INPUTS = "ORDERED_INPUTS"
    ORDERED_RESULTS = "ORDERED_RESULTS"
    STATE_PRE_POST = "STATE_PRE_POST"
    CONTROL_COMPLETION = "CONTROL_COMPLETION"
    CALL_ACTUAL_FORMAL = "CALL_ACTUAL_FORMAL"
    CALL_RETURN_EXCEPTION = "CALL_RETURN_EXCEPTION"
    ENVIRONMENT_IDENTITY = "ENVIRONMENT_IDENTITY"
    OWNER_SELECTOR = "OWNER_SELECTOR"
    ALIAS_ESCAPE = "ALIAS_ESCAPE"
    VALUE_PROVENANCE = "VALUE_PROVENANCE"
    LOGICAL_MATERIALIZATION = "LOGICAL_MATERIALIZATION"
    RESOURCE_BINDING = "RESOURCE_BINDING"
    RESOURCE_WORK = "RESOURCE_WORK"
    READY_ORDER = "READY_ORDER"
    LIFETIME = "LIFETIME"

class RequirementSelection(str, Enum):
    SUBJECT_INTERFACE = "SUBJECT_INTERFACE"
    ALL_ORIGINAL_INPUTS = "ALL_ORIGINAL_INPUTS"
    ALL_ORIGINAL_RESULTS = "ALL_ORIGINAL_RESULTS"
    ALL_ORIGINAL_STATE_PORTS = "ALL_ORIGINAL_STATE_PORTS"
    ALL_ORIGINAL_COMPLETION_PATHS = "ALL_ORIGINAL_COMPLETION_PATHS"
    ALL_ORIGINAL_RESOURCE_USES = "ALL_ORIGINAL_RESOURCE_USES"

@dataclass(frozen=True)
class RelationRequirement:
    key: str
    kind: RelationKind
    selection: RequirementSelection
    source: JsonRecordRef

@dataclass(frozen=True)
class ObligationSource:
    rule: JsonRecordRef
    origin: EvidenceLocator

@dataclass(frozen=True)
class CoverageObligation:
    id: ObligationID
    scope_revision: ScopeRevision
    rule_key: str
    source: ObligationSource
    subject: CoverageSubject
    required_relations: tuple[RelationRequirement, ...]
    required_expansion: Expansion
    mandatory: bool

class DenominatorDomain(str, Enum):
    SOURCE_DEFINITIONS = "SOURCE_DEFINITIONS"
    SOURCE_CONSTRUCTS = "SOURCE_CONSTRUCTS"
    OBSERVED_PYTHON_CALLS = "OBSERVED_PYTHON_CALLS"
    DISPATCH_ATTEMPTS = "DISPATCH_ATTEMPTS"
    NATIVE_ACTIVITIES = "NATIVE_ACTIVITIES"
    OS_INTERFACES = "OS_INTERFACES"
    OS_RESOURCES = "OS_RESOURCES"
    PHYSICAL_OBJECTS_AND_RESOURCES = "PHYSICAL_OBJECTS_AND_RESOURCES"

class Enumeration(str, Enum):
    DECLARED = "DECLARED"
    PARTIAL = "PARTIAL"
    ENUMERATED = "ENUMERATED"

@dataclass(frozen=True)
class EnumerationCursor:
    collection: CollectionLocator
    next_partition: int
    next_ordinal: int
    end_ordinal: int | None
    reason: str

@dataclass(frozen=True)
class DenominatorInventory:
    id: DenominatorID
    domain: DenominatorDomain
    collection: CollectionLocator
    source: EvidenceLocator
    declared_count: int | None
    enumerated_count: int
    membership_sha256: Sha256 | None
    enumeration: Enumeration
    observation_coverage: Coverage
    cursor: EnumerationCursor | None
    gaps: tuple[CoverageGap, ...]

@dataclass(frozen=True)
class DenominatorMember:
    denominator: DenominatorID
    subject: CoverageSubject
    obligations: tuple[ObligationID, ...]
    source: EvidenceLocator

class Axis(str, Enum):
    STRUCTURAL_ATTRIBUTION = "STRUCTURAL_ATTRIBUTION"
    DEPENDENCY_CONNECTION = "DEPENDENCY_CONNECTION"
    INTERNAL_EXPANSION = "INTERNAL_EXPANSION"
    RUNTIME_EVIDENCE = "RUNTIME_EVIDENCE"

class RequirementStatus(str, Enum):
    SATISFIED = "SATISFIED"
    OPEN = "OPEN"
    CONTRADICTED = "CONTRADICTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"

class EvidenceMode(str, Enum):
    STATIC_SOURCE = "STATIC_SOURCE"
    ACTUAL_OBSERVATION = "ACTUAL_OBSERVATION"
    VERSIONED_CONTRACT = "VERSIONED_CONTRACT"
    CONDITIONAL = "CONDITIONAL"

@dataclass(frozen=True)
class RequirementResult:
    key: str
    status: RequirementStatus
    basis_modes: tuple[EvidenceMode, ...]
    evidence: tuple[EvidenceLocator, ...]
    conditions: tuple[EvidenceLocator, ...]
    gaps: tuple[CoverageGap, ...]
    cursor: EnumerationCursor | None

@dataclass(frozen=True)
class AxisResult:
    axis: Axis
    results: tuple[RequirementResult, ...]

class ReviewMode(str, Enum):
    PRODUCER_GATE = "PRODUCER_GATE"
    REUSED_ACCEPTED = "REUSED_ACCEPTED"
    INDEPENDENT_AUDIT = "INDEPENDENT_AUDIT"
    UNREVIEWED = "UNREVIEWED"

@dataclass(frozen=True)
class EvidenceReuseRef:
    gate_receipt: EvidenceLocator
    producers: tuple[ProviderArtifact, ...]
    scope: CoverageSubject
    inputs: tuple[EvidenceLocator, ...]
    requirement_keys: tuple[str, ...]
    remaining_conditions: tuple[EvidenceLocator, ...]

@dataclass(frozen=True)
class CheckReceipt:
    rule_key: str
    policy: JsonRecordRef
    implementation: tuple[ProviderArtifact, ...]
    inputs: tuple[EvidenceLocator, ...]
    reviewed_requirement_keys: tuple[str, ...]
    result_sha256: Sha256
    cursor: EnumerationCursor | None
    review_mode: ReviewMode
    reused_evidence: tuple[EvidenceReuseRef, ...]

@dataclass(frozen=True)
class CoverageAssessment:
    obligation: ObligationID
    scope_revision: ScopeRevision
    axes: tuple[AxisResult, ...]
    checker: CheckReceipt
    source: EvidenceLocator

@dataclass(frozen=True)
class ScopeRevisionDelta:
    parent: ScopeRevision
    child: ScopeRevision
    added: tuple[ObligationID, ...]
    removed: tuple[ObligationID, ...]
    modified: tuple[ObligationID, ...]
    reasons: tuple[EvidenceLocator, ...]
    source: EvidenceLocator

class LedgerTableKind(str, Enum):
    OBLIGATIONS = "OBLIGATIONS"
    DENOMINATORS = "DENOMINATORS"
    MEMBERS = "MEMBERS"
    ASSESSMENTS = "ASSESSMENTS"
    DELTAS = "DELTAS"

@dataclass(frozen=True)
class LedgerTableRef:
    name: LedgerTableKind
    collection: JsonRecordRef

@dataclass(frozen=True)
class LedgerReceipt:
    schema: str
    schema_version: int
    scope_revision: ScopeRevision
    scope: JsonRecordRef
    tables: tuple[LedgerTableRef, ...]
    storage_receipts: tuple[RetainedArtifact, ...]

LedgerRow: TypeAlias = (
    CoverageObligation | DenominatorInventory | DenominatorMember |
    CoverageAssessment | ScopeRevisionDelta
)

# Resolver opens only explicitly supplied immutable artifacts under known
# schema/profile readers. No caller-supplied "verified" callbacks or booleans.
class LedgerResolver(Protocol):
    def resolve(self, locator: EvidenceLocator, /) -> bytes: ...

@dataclass(frozen=True)
class InputBinding:
    domain: DenominatorDomain
    collection: CollectionLocator

@dataclass(frozen=True)
class ScopeInputs:
    coordinates: JsonRecordRef
    command: JsonRecordRef
    collections: tuple[InputBinding, ...]
    scope_evidence: tuple[EvidenceLocator, ...]
    provider_evidence: tuple[EvidenceLocator, ...]

@dataclass(frozen=True)
class CoveragePolicy:
    contract: TextRangeRef
    rules: JsonRecordRef

@dataclass(frozen=True)
class LedgerBudgets:
    max_manifest_bytes: int
    max_record_bytes: int
    max_chunk_bytes: int
    max_total_bytes: int
    max_members: int
    max_check_steps: int

@dataclass(frozen=True)
class ModelCatalogs:
    artifacts: tuple[RetainedArtifact, ...]
    accepted_evidence: tuple[EvidenceReuseRef, ...]

class VerificationStatus(str, Enum):
    INVALID = "INVALID"
    OPEN = "OPEN"
    SATISFIED_WITHIN_SCOPE = "SATISFIED_WITHIN_SCOPE"

@dataclass(frozen=True)
class LedgerVerification:
    scope_revision: ScopeRevision
    status: VerificationStatus
    mandatory_obligations: int
    unresolved_requirement_keys: tuple[str, ...]
    gaps: tuple[CoverageGap, ...]
    denominators: tuple[DenominatorInventory, ...]
    bytes_read: int
    checks_performed: int
    evidence_reused: int
    raw_replay_scope: tuple[CollectionLocator, ...]

@dataclass(frozen=True)
class ObligationView:
    obligation: CoverageObligation
    assessment: CoverageAssessment | None
    memberships: tuple[DenominatorMember, ...]
    gaps: tuple[CoverageGap, ...]
    review_mode: ReviewMode
    reused_evidence: tuple[EvidenceReuseRef, ...]
    unreplayed_sources: tuple[EvidenceLocator, ...]

class LedgerReader(Protocol):
    def rows(self) -> Iterator[LedgerRow]: ...
    def obligation(self, identity: ObligationID, /) -> ObligationView: ...

def plan_scope(inputs: ScopeInputs, policy: CoveragePolicy, resolver: LedgerResolver,
               budgets: LedgerBudgets) -> AnalysisScope: ...
def enumerate_obligations(scope: AnalysisScope, inputs: ScopeInputs, policy: CoveragePolicy,
                          resolver: LedgerResolver, budgets: LedgerBudgets) -> Iterator[LedgerRow]: ...
def assess_obligation(scope: AnalysisScope, obligation: CoverageObligation, catalogs: ModelCatalogs,
                      resolver: LedgerResolver, budgets: LedgerBudgets) -> CoverageAssessment: ...
def verify_ledger(scope: AnalysisScope, rows: Iterator[LedgerRow], catalogs: ModelCatalogs,
                  resolver: LedgerResolver, budgets: LedgerBudgets) -> LedgerVerification: ...
def query_obligation(scope_revision: ScopeRevision, obligation_id: ObligationID,
                      reader: LedgerReader) -> ObligationView: ...
def write_ledger(scope: AnalysisScope, rows: Iterator[LedgerRow], fresh_output: str,
                  budgets: LedgerBudgets) -> LedgerReceipt: ...
def read_ledger(receipt: LedgerReceipt, resolver: LedgerResolver,
                 budgets: LedgerBudgets) -> LedgerReader: ...
