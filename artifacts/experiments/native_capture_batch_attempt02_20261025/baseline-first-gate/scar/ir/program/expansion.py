"""Analysis demand and work accounting; these records grant no program facts."""
from dataclasses import dataclass
from enum import Enum

from scar.ir.program.inventory import BodyStatus
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID


@dataclass(frozen=True, slots=True)
class ContextStoreBudget:
    max_compressed_bytes: int = 128_000_000
    max_record_bytes: int = 64_000_000

    def __post_init__(self):
        for value in (self.max_compressed_bytes, self.max_record_bytes):
            if type(value) is not int or value < 1:
                raise ValueError("context store budgets must be positive exact integers")


class BodyDemandKind(str, Enum):
    OBSERVED_CODE = "OBSERVED_CODE"
    CANDIDATE_CALL = "CANDIDATE_CALL"
    REMAINDER = "REMAINDER"


@dataclass(frozen=True, slots=True)
class BodyExpansion:
    definition: OperationDefinitionID
    source: SourceReference
    kind: BodyDemandKind
    observation_indices: tuple[int, ...] = ()
    via_call: OperationDefinitionID | None = None
    attempted: bool = False
    construction_operations: int = 0
    status: BodyStatus = BodyStatus.NOT_ATTEMPTED
    operation_budget_charged: int = 0
    construction_cost_known: bool = True

    def __post_init__(self):
        if type(self.attempted) is not bool or type(self.construction_cost_known) is not bool:
            raise ValueError("expansion flags must be exact booleans")
        if (any(type(value) is not int or value < 0 for value in self.observation_indices)
                or len(set(self.observation_indices)) != len(self.observation_indices)):
            raise ValueError("invalid expansion observation indices")
        for value in (self.construction_operations, self.operation_budget_charged):
            if type(value) is not int or value < 0:
                raise ValueError("expansion costs must be nonnegative exact integers")
        if self.operation_budget_charged < self.construction_operations:
            raise ValueError("constructed operations cannot be refunded")
        if self.kind is BodyDemandKind.OBSERVED_CODE:
            if not self.observation_indices or self.via_call is not None:
                raise ValueError("observed demand needs observation anchors only")
        elif self.kind is BodyDemandKind.CANDIDATE_CALL:
            if self.via_call is None or self.observation_indices:
                raise ValueError("call demand needs a source call anchor only")
        elif self.kind is BodyDemandKind.REMAINDER:
            if self.observation_indices or self.via_call is not None:
                raise ValueError("remainder demand cannot manufacture evidence")
        else:
            raise ValueError("unknown body demand kind")
        if not self.attempted:
            if (self.status is not BodyStatus.NOT_ATTEMPTED or self.construction_operations
                    or self.operation_budget_charged or not self.construction_cost_known):
                raise ValueError("unattempted task cannot claim construction work")
        elif self.status is BodyStatus.NOT_ATTEMPTED:
            raise ValueError("attempted task must have an explicit result")


@dataclass(frozen=True, slots=True)
class ContextUnavailable:
    path: str
    reason: str

    def __post_init__(self):
        if not self.path or not self.reason:
            raise ValueError("context boundary needs a path and reason")


@dataclass(frozen=True, slots=True)
class ExpansionSchedule:
    budget: ContextStoreBudget
    entries: tuple[BodyExpansion, ...]
    unavailable_contexts: tuple[ContextUnavailable, ...] = ()

    def __post_init__(self):
        self.budget.__post_init__()
        if len({entry.definition for entry in self.entries}) != len(self.entries):
            raise ValueError("a body definition can be scheduled only once")
        if len({entry.path for entry in self.unavailable_contexts}) != len(self.unavailable_contexts):
            raise ValueError("duplicate context boundary")


@dataclass(frozen=True, slots=True)
class ExpansionMeasurements:
    """This SCAR invocation's work; not a replay identity or target measurement."""
    context_restore_attempts: int
    compressed_payload_bytes_restored: int
    compressed_context_bytes_written: int
    uncompressed_context_bytes_accepted: int
