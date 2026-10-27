"""A read's symbolic result, distinct from the input reference occurrence.

This adds no operation, Use, state, object or storage identity. Constructing the
record grants neither observed-memory-read nor content-stability authority.
"""
from dataclasses import dataclass
from enum import Enum

from scar.ir.program.providers import ProviderArtifact
from .content import ContentRead, HostConsumer, NativeInputRef, VersionRef
from .coordinates import ProgramSnapshot, UnresolvedHostThread
from .ids import HostThreadInstanceID, ProcessInstanceID, RunID, ValueOccurrenceID
from .resources import AllocationTarget
from .work import InvokeBoundaryStateEffect


class NativeReadCondition(str, Enum):
    PINNED_PROVIDER_IMPLEMENTATION = 'PINNED_PROVIDER_IMPLEMENTATION_ASSUMED'
    ACTUAL_STORAGE_READ_PATH = 'ACTUAL_STORAGE_READ_PATH_UNVERIFIED'
    STATE_CONTENT_FOOTPRINT = 'STATE_CONTENT_FOOTPRINT_UNRESOLVED'
    INTERVAL_STABILITY = 'INTERVAL_CONTENT_STABILITY_UNPROVED'
    UPSTREAM_CONTENT = 'UPSTREAM_CONTENT_ORIGIN_UNRESOLVED'


@dataclass(frozen=True, slots=True)
class NativeTensorRead:
    """Typed ContentRead -> VersionRef relation under explicit conditions.

    `input` remains the existing reference occurrence; `result` denotes only
    this read's payload. Unequal result IDs do not assert unequal contents.
    """
    execution: ProviderArtifact
    snapshot: ProgramSnapshot
    run: RunID
    process: ProcessInstanceID
    actor: HostThreadInstanceID | UnresolvedHostThread
    read: ContentRead
    input: ValueOccurrenceID
    result: VersionRef
    allocation: AllocationTarget
    conditions: tuple[NativeReadCondition, ...]

    def __post_init__(self):
        for name, cls in (('execution', ProviderArtifact), ('snapshot', ProgramSnapshot),
                ('run', RunID), ('process', ProcessInstanceID), ('read', ContentRead),
                ('input', ValueOccurrenceID), ('result', VersionRef), ('allocation', AllocationTarget)):
            value = getattr(self, name)
            if type(value) is not cls:
                raise TypeError('native read requires exact ' + name)
            value.__post_init__()
        if type(self.actor) not in (HostThreadInstanceID, UnresolvedHostThread):
            raise TypeError('native read requires an original actor or explicit unresolved actor')
        self.actor.__post_init__()
        if type(self.read.basis) is not NativeInputRef or type(self.read.consumer) is not HostConsumer:
            raise TypeError('native CPU read requires original NativeInputRef and HostConsumer')
        if type(self.read.effect) is not InvokeBoundaryStateEffect or not self.read.support:
            raise ValueError('native read must retain original invocation state and support')
        if type(self.conditions) is not tuple or not self.conditions or any(
                type(c) is not NativeReadCondition for c in self.conditions):
            raise TypeError('native read conditions must be explicit closed typed conditions')
        if len(set(self.conditions)) != len(self.conditions):
            raise ValueError('native read conditions must not repeat')
