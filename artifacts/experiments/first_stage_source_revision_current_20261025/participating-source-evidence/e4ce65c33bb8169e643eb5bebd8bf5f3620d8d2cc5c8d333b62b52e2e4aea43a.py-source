"""Typed queue/event ordering endpoints over existing work and resource IDs.

These records preserve generation-specific declarations. They do not infer
device order, event completion, or consumer visibility.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from scar.ir.program.providers import ProviderFactReference
from .common import FactSource, Unresolved
from .coordinates import AccessRef, ExecutionPoint, UseRef
from .ids import (
    EventRecordID, QueueOrderProfileID, QueuePrefixID, QueueWaitID,
    ResourceAccessID, ResourceInstanceID, WorkTicketID,
)
from .resources import _id, _point, _record, _source, _variant
from .work import InvokeBoundaryStateEffect, QueueStart


@dataclass(frozen=True, slots=True)
class QueueOrderProfile:
    id: QueueOrderProfileID
    queue: ResourceInstanceID
    through: QueuePrefixID
    protocol: ProviderFactReference
    source: FactSource

    def __post_init__(self):
        _id(self.id, QueueOrderProfileID, "queue-order profile ID")
        _id(self.queue, ResourceInstanceID, "queue-order profile queue")
        _id(self.through, QueuePrefixID, "queue-order profile cutoff prefix")
        _record(self.protocol, ProviderFactReference, "queue-order profile protocol")
        _source(self.source, "queue-order profile source")


@dataclass(frozen=True, slots=True)
class RecordedPrefix:
    queue: ResourceInstanceID
    prefix: QueuePrefixID | QueueStart | Unresolved

    def __post_init__(self):
        _id(self.queue, ResourceInstanceID, "recorded-prefix queue")
        _variant(self.prefix, (QueuePrefixID, QueueStart, Unresolved), "recorded prefix")


@dataclass(frozen=True, slots=True)
class EventRecord:
    id: EventRecordID
    event: ResourceInstanceID
    event_access: ResourceAccessID | Unresolved
    marker: WorkTicketID | Unresolved
    captured: RecordedPrefix
    generation: AccessRef | InvokeBoundaryStateEffect | Unresolved
    observed_at: ExecutionPoint
    protocol: ProviderFactReference
    source: FactSource

    def __post_init__(self):
        _id(self.id, EventRecordID, "event-record ID")
        _id(self.event, ResourceInstanceID, "event-record event instance")
        _variant(self.event_access, (ResourceAccessID, Unresolved), "event-record access")
        _variant(self.marker, (WorkTicketID, Unresolved), "event-record marker work")
        _record(self.captured, RecordedPrefix, "event-record captured prefix")
        _variant(self.generation, (AccessRef, InvokeBoundaryStateEffect, Unresolved), "event-record generation")
        _point(self.observed_at, "event-record observation point")
        _record(self.protocol, ProviderFactReference, "event-record protocol")
        _source(self.source, "event-record source")


@dataclass(frozen=True, slots=True)
class QueueWait:
    id: QueueWaitID
    ticket: WorkTicketID
    record: EventRecordID | Unresolved
    event_access: ResourceAccessID | Unresolved
    selection: UseRef | Unresolved
    observed_at: ExecutionPoint
    protocol: ProviderFactReference
    source: FactSource

    def __post_init__(self):
        _id(self.id, QueueWaitID, "queue-wait ID")
        _id(self.ticket, WorkTicketID, "queue-wait consumer ticket")
        _variant(self.record, (EventRecordID, Unresolved), "queue-wait event record")
        _variant(self.event_access, (ResourceAccessID, Unresolved), "queue-wait event access")
        _variant(self.selection, (UseRef, Unresolved), "queue-wait generation selection")
        _point(self.observed_at, "queue-wait observation point")
        _record(self.protocol, ProviderFactReference, "queue-wait protocol")
        _source(self.source, "queue-wait source")


@dataclass(frozen=True, slots=True)
class WorkStart:
    ticket: WorkTicketID

    def __post_init__(self):
        _id(self.ticket, WorkTicketID, "work-start ticket")


@dataclass(frozen=True, slots=True)
class WorkEnd:
    ticket: WorkTicketID

    def __post_init__(self):
        _id(self.ticket, WorkTicketID, "work-end ticket")


@dataclass(frozen=True, slots=True)
class PrefixEnd:
    prefix: QueuePrefixID

    def __post_init__(self):
        _id(self.prefix, QueuePrefixID, "queue-prefix-end prefix")


@dataclass(frozen=True, slots=True)
class EventSignal:
    record: EventRecordID

    def __post_init__(self):
        _id(self.record, EventRecordID, "event-signal record")


OrderPoint: TypeAlias = WorkStart | WorkEnd | PrefixEnd | EventSignal


__all__ = [
    "QueueOrderProfile", "RecordedPrefix", "EventRecord", "QueueWait",
    "WorkStart", "WorkEnd", "PrefixEnd", "EventSignal", "OrderPoint",
]
