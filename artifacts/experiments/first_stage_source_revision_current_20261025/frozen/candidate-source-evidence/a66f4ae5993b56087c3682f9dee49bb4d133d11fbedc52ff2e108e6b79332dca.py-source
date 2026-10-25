"""Typed invocation-to-slot bindings backed by a live provenance registry.

This overlay connects invocation identities to explicit semantic slots and
versioned value handles. It does not infer bindings from observation order,
value content, or semantic edges, and it does not establish optimization
legality. Validation is recomputed against the caller's current IRBundle and
ProvenanceRegistry; no mutable registry result is cached.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from bisect import bisect_right
import json
from typing import Any

from scar.ir.provenance import EventPoint, GuardState, ProvenanceRegistry, ValueHandle
from scar.ir.v2 import (
    EvidenceClaim, EvidenceKind, IRBundle, OperationDefinitionID,
    OperationInstanceID, SemanticNodeKind, SemanticRelation, ValueSlotID,
)
from scar.ir.v2._validation import record_errors
from scar.ir.v2.ids import (
    Identifier, LogicalValueID, MaterializationID, ObjectID, ValueVersionID,
)


class InvocationRole(str, Enum):
    """Formal ports and actual read slots are deliberately separate."""

    INPUT = "INPUT"
    STATE = "STATE"
    OUTPUT = "OUTPUT"
    READ = "READ"


class StructureState(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"


class SlotCoverageState(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class TypeCompatibilityState(str, Enum):
    """Whether this overlay has a concrete compatibility fact for a binding.

    The current physical-handle model can reject known Python bool slots, but
    it cannot positively prove general slot/materialization compatibility.
    """

    NOT_ESTABLISHED = "NOT_ESTABLISHED"
    INCOMPATIBLE = "INCOMPATIBLE"


class InvocationClockDomain(str, Enum):
    REGISTRY_EVENT_ORDINAL = "registry_event_ordinal"


@dataclass(frozen=True, slots=True)
class InvocationClock:
    """One ordinal event clock shared by every call in this overlay."""

    scope: str
    domain: InvocationClockDomain

    def __post_init__(self) -> None:
        if not self.scope:
            raise ValueError("invocation clock requires scope")
        if not isinstance(self.domain, InvocationClockDomain):
            raise TypeError("invocation clock domain must be InvocationClockDomain")

    def as_dict(self) -> dict[str, str]:
        return {"scope": self.scope, "domain": self.domain.value}


@dataclass(frozen=True, slots=True)
class InvocationCall:
    """Typed entry/exit window for one concrete operation instance."""

    instance: OperationInstanceID
    definition: OperationDefinitionID
    process_id: int | str
    thread_id: int | str
    entry: EventPoint
    exit: EventPoint
    evidence: EvidenceClaim

    def __post_init__(self) -> None:
        if type(self.process_id) not in (int, str) or type(self.thread_id) not in (int, str):
            raise TypeError("call process/thread identity must be int or str")
        if isinstance(self.process_id, str) and not self.process_id:
            raise ValueError("call process identity cannot be empty")
        if isinstance(self.thread_id, str) and not self.thread_id:
            raise ValueError("call thread identity cannot be empty")
        if self.entry.scope != self.exit.scope or self.exit.ordinal < self.entry.ordinal:
            raise ValueError("call entry/exit must be ordered in one event scope")

    def as_dict(self) -> dict[str, Any]:
        return {
            "instance": self.instance.as_dict(),
            "definition": self.definition.as_dict(),
            "process_id": self.process_id,
            "thread_id": self.thread_id,
            "entry": _event_dict(self.entry),
            "exit": _event_dict(self.exit),
            "evidence": self.evidence.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class InvocationSlotBinding:
    """An explicit role/slot/handle observation for one invocation."""

    instance: OperationInstanceID
    role: InvocationRole
    slot: ValueSlotID
    handle: ValueHandle
    at: EventPoint
    evidence: EvidenceClaim

    def __post_init__(self) -> None:
        if not isinstance(self.role, InvocationRole):
            raise TypeError("invocation binding role must be InvocationRole")

    def as_dict(self) -> dict[str, Any]:
        return {
            "instance": self.instance.as_dict(),
            "role": self.role.value,
            "slot": self.slot.as_dict(),
            "handle": _handle_dict(self.handle),
            "at": _event_dict(self.at),
            "evidence": self.evidence.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class BindingGuard:
    """Fresh registry guard result, evaluated at current_event, never cached."""

    instance: OperationInstanceID
    role: InvocationRole
    slot: ValueSlotID
    state: GuardState
    checked_at: EventPoint
    required_facts: tuple[str, ...]
    reason: str
    binding_evidence: EvidenceClaim
    registry_evidence: tuple[EvidenceClaim, ...]
    type_compatibility: TypeCompatibilityState

    def as_dict(self) -> dict[str, Any]:
        return {
            "instance": self.instance.as_dict(),
            "role": self.role.value,
            "slot": self.slot.as_dict(),
            "state": self.state.value,
            "checked_at": _event_dict(self.checked_at),
            "required_facts": list(self.required_facts),
            "reason": self.reason,
            "binding_evidence": self.binding_evidence.as_dict(),
            "registry_guard_evidence": [item.as_dict() for item in self.registry_evidence],
            "type_compatibility": self.type_compatibility.value,
        }


@dataclass(frozen=True, slots=True)
class InvocationBindingReport:
    """Recomputed structure, slot coverage and current-guard findings."""

    structure: StructureState
    slot_coverage: SlotCoverageState
    errors: tuple[str, ...]
    coverage_gaps: tuple[str, ...]
    missing_slots: tuple[tuple[OperationInstanceID, InvocationRole, ValueSlotID], ...]
    guards: tuple[BindingGuard, ...]
    compatibility_gaps: tuple[str, ...] = ()

    @property
    def bindings_currently_guarded(self) -> bool:
        """Whether every overlay binding has a VALID current registry guard.

        This is a freshness fact only. It neither upgrades DECLARED evidence to
        OBSERVED nor says anything about equality, hidden state, effects, type
        compatibility in general, or optimization legality.
        """
        return (self.structure is StructureState.VALID
                and self.slot_coverage is SlotCoverageState.COMPLETE
                and bool(self.guards)
                and all(item.state is GuardState.VALID for item in self.guards))

    def as_dict(self) -> dict[str, Any]:
        """Diagnostic output only; reports are not accepted by the decoder."""
        return {
            "structure": self.structure.value,
            "slot_coverage": self.slot_coverage.value,
            "errors": list(self.errors),
            "coverage_gaps": list(self.coverage_gaps),
            "compatibility_gaps": list(self.compatibility_gaps),
            "slot_coverage_scope": (
                "formal slots and known READS_SLOT targets for calls listed in this overlay; "
                "does not close hidden calls, reads, or omitted call instances"
            ),
            "validation_atomicity": (
                "not atomic; caller must hold an external lock or provide stable snapshots "
                "of the bundle and registry for the full validation"
            ),
            "missing_slots": [
                {"instance": instance.as_dict(), "role": role.value, "slot": slot.as_dict()}
                for instance, role, slot in self.missing_slots
            ],
            "guards": [item.as_dict() for item in self.guards],
            "bindings_currently_guarded": self.bindings_currently_guarded,
            "bindings_currently_guarded_scope": (
                "current registry guard only; not independent event-log replay, "
                "OBSERVED evidence, type compatibility, or optimization legality"
            ),
        }


@dataclass(slots=True)
class _ValidationIndex:
    """Indexes rebuilt for each check against the mutable external models."""

    reads_by_definition: dict[OperationDefinitionID, set[ValueSlotID]]
    intervals_by_scope_slot: dict[tuple[str, ValueSlotID], tuple[list[int], list[Any]]]
    registry_objects: dict[tuple[ObjectID, ValueVersionID, str], list[Any]]
    bundle_objects: dict[tuple[ObjectID, ValueVersionID, str], list[Any]]

    @classmethod
    def build(cls, bundle: IRBundle, registry: ProvenanceRegistry) -> "_ValidationIndex":
        reads: dict[OperationDefinitionID, set[ValueSlotID]] = {}
        for edge in bundle.semantic.edges.values():
            if (edge.relation is SemanticRelation.READS_SLOT
                    and edge.source.kind is SemanticNodeKind.OPERATION
                    and edge.target.kind is SemanticNodeKind.VALUE_SLOT):
                reads.setdefault(edge.source.id, set()).add(edge.target.id)

        intervals: dict[tuple[str, ValueSlotID], list[Any]] = {}
        for interval in registry.bindings:
            intervals.setdefault((interval.scope, interval.slot), []).append(interval)
        indexed_intervals = {}
        for key, records in intervals.items():
            records.sort(key=lambda item: item.start_event.ordinal)
            indexed_intervals[key] = ([item.start_event.ordinal for item in records], records)

        def index_objects(graph):
            result: dict[tuple[ObjectID, ValueVersionID, str], list[Any]] = {}
            for binding in graph.bindings:
                if binding.scope is not None:
                    key = (binding.object_id, binding.value_version, binding.scope)
                    result.setdefault(key, []).append(binding)
            return result

        return cls(reads, indexed_intervals, index_objects(registry.graph),
                   index_objects(bundle.values))

    def live_interval(self, scope: str, slot: ValueSlotID,
                      at: EventPoint) -> Any | None:
        starts, records = self.intervals_by_scope_slot.get((scope, slot), ([], []))
        position = bisect_right(starts, at.ordinal) - 1
        if position < 0:
            return None
        interval = records[position]
        if interval.start_event.scope != at.scope:
            return None
        if interval.end_event is not None and at.ordinal >= interval.end_event.ordinal:
            return None
        return interval


@dataclass(frozen=True, slots=True)
class InvocationBindingsV2:
    """Deterministic overlay; raw records only, never cached validation status."""

    clock: InvocationClock
    calls: tuple[InvocationCall, ...]
    bindings: tuple[InvocationSlotBinding, ...]

    SCHEMA = "scar.ir.invocation-bindings.v2"
    SCHEMA_VERSION = 1

    def __post_init__(self) -> None:
        errors = record_errors(self.clock, InvocationClock, "clock")
        for index, item in enumerate(self.calls):
            errors.extend(record_errors(item, InvocationCall, f"calls[{index}]"))
        for index, item in enumerate(self.bindings):
            errors.extend(record_errors(item, InvocationSlotBinding, f"bindings[{index}]"))
        if errors:
            raise TypeError("invalid invocation binding overlay: " + "; ".join(errors))
        call_ids = [item.instance for item in self.calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("invocation calls must be unique by instance")
        binding_keys = [(item.instance, item.role, item.slot) for item in self.bindings]
        if len(binding_keys) != len(set(binding_keys)):
            raise ValueError("invocation bindings must be unique by instance, role and slot")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "schema_version": self.SCHEMA_VERSION,
            "clock": self.clock.as_dict(),
            "calls": [item.as_dict() for item in sorted(self.calls, key=lambda row: row.instance.wire)],
            "bindings": [item.as_dict() for item in sorted(
                self.bindings, key=lambda row: (row.instance.wire, row.role.value, row.slot.wire))],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> "InvocationBindingsV2":
        expected = {"schema", "schema_version", "clock", "calls", "bindings"}
        if not isinstance(document, dict) or set(document) != expected:
            raise ValueError("invalid invocation binding document fields")
        if (document["schema"] != cls.SCHEMA or type(document["schema_version"]) is not int
                or document["schema_version"] != cls.SCHEMA_VERSION):
            raise ValueError("unsupported invocation binding schema")
        if not isinstance(document["calls"], list) or not isinstance(document["bindings"], list):
            raise ValueError("invocation calls and bindings must be JSON arrays")
        result = cls(_decode_clock(document["clock"]),
                     tuple(_decode_call(item) for item in document["calls"]),
                     tuple(_decode_binding(item) for item in document["bindings"]))
        if result.to_dict() != document:
            raise ValueError("invocation binding document is not canonical")
        return result

    @classmethod
    def from_json(cls, payload: str) -> "InvocationBindingsV2":
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON field")
                result[key] = value
            return result

        document = json.loads(payload, object_pairs_hook=unique,
                              parse_constant=lambda value: (_ for _ in ()).throw(
                                  ValueError("non-finite JSON value")))
        return cls.from_dict(document)

    def validate(self, bundle: IRBundle, registry: ProvenanceRegistry) -> InvocationBindingReport:
        """Recompute references, slot coverage and current guards.

        Structure, declared-slot coverage, and current registry guards remain
        separate. This check is not an atomic snapshot: callers must stabilize
        the mutable bundle and registry for its duration, for example by
        holding an external lock.
        """
        errors: list[str] = []
        gaps: list[str] = []
        compatibility_gaps: list[str] = []
        missing: list[tuple[OperationInstanceID, InvocationRole, ValueSlotID]] = []
        guards: list[BindingGuard] = []
        try:
            bundle.assert_valid()
        except (TypeError, ValueError) as exc:
            errors.append("invalid IR bundle: " + str(exc))
        try:
            registry.assert_valid()
        except (TypeError, ValueError) as exc:
            errors.append("invalid provenance registry: " + str(exc))

        if errors:
            return InvocationBindingReport(StructureState.INVALID,
                SlotCoverageState.INCOMPLETE, tuple(sorted(set(errors))), (),
                (), ())
        errors.extend("registry reference: " + item for item in
                      registry.validate_references(bundle.semantic, bundle.evidence))
        if errors:
            return InvocationBindingReport(StructureState.INVALID,
                SlotCoverageState.INCOMPLETE, tuple(sorted(set(errors))), (), (), ())
        index = _ValidationIndex.build(bundle, registry)
        if self.clock.scope != registry.scope:
            errors.append("overlay clock scope differs from registry scope")
        if registry.current_event.scope != self.clock.scope:
            errors.append("registry current event is outside overlay scope")

        calls = {item.instance: item for item in self.calls}
        definitions = {}
        expected: set[tuple[OperationInstanceID, InvocationRole, ValueSlotID]] = set()
        for call in self.calls:
            errors.extend(self._validate_call(call, bundle, registry))
            instance = bundle.evidence.instances.get(call.instance)
            definition = bundle.semantic.definitions.get(call.definition)
            if instance is None or definition is None:
                continue
            definitions[call.instance] = definition
            expected.update((call.instance, InvocationRole.INPUT, slot)
                            for slot in definition.input_slots)
            expected.update((call.instance, InvocationRole.STATE, slot)
                            for slot in definition.state_slots)
            expected.update((call.instance, InvocationRole.OUTPUT, slot)
                            for slot in definition.output_slots)
            expected.update((call.instance, InvocationRole.READ, slot)
                            for slot in index.reads_by_definition.get(definition.id, ()))

        actual = set()
        guard_cache = {}
        for item in self.bindings:
            key = (item.instance, item.role, item.slot)
            actual.add(key)
            call = calls.get(item.instance)
            if call is None:
                errors.append(f"binding references call absent from overlay: {item.instance.wire}")
                continue
            definition = definitions.get(item.instance)
            if definition is None:
                continue
            handle_valid = self._valid_handle_references(item.handle, bundle, registry, index)
            type_compatibility, type_gap = self._type_compatibility(
                item, bundle, registry, handle_valid)
            if type_gap is not None:
                compatibility_gaps.append(type_gap)
                errors.append(type_gap)
            errors.extend(self._validate_binding(
                item, call, definition, bundle, registry, index, handle_valid))
            if handle_valid:
                try:
                    guarded = guard_cache.get(item.handle)
                    if guarded is None:
                        guarded = registry.guard(item.handle)
                    guard_cache[item.handle] = guarded
                    guards.append(BindingGuard(item.instance, item.role, item.slot,
                        guarded.state, guarded.checked_at, guarded.required_facts, guarded.reason,
                        item.evidence, guarded.evidence, type_compatibility))
                except (KeyError, TypeError, ValueError) as exc:
                    errors.append(f"cannot recompute current guard for {item.slot.wire}: {exc}")

        for key in sorted(expected - actual, key=_binding_key):
            missing.append(key)
        if missing:
            gaps.extend(f"missing declared {role.value} slot {slot.wire} for {instance.wire}"
                        for instance, role, slot in missing)
        extra = actual - expected
        if extra:
            errors.extend(f"binding role/slot is not declared or read by operation: {instance.wire} "
                          f"{role.value} {slot.wire}"
                          for instance, role, slot in sorted(extra, key=_binding_key))

        errors = sorted(set(errors))
        gaps = sorted(set(gaps))
        return InvocationBindingReport(
            StructureState.INVALID if errors else StructureState.VALID,
            SlotCoverageState.INCOMPLETE if gaps or expected - actual else SlotCoverageState.COMPLETE,
            tuple(errors), tuple(gaps), tuple(missing),
            tuple(sorted(guards, key=lambda item: (item.instance.wire,
                                                   item.role.value, item.slot.wire))),
            tuple(sorted(set(compatibility_gaps))))

    @staticmethod
    def _type_compatibility(item: InvocationSlotBinding, bundle: IRBundle,
                            registry: ProvenanceRegistry, handle_valid: bool
                            ) -> tuple[TypeCompatibilityState, str | None]:
        """Reject one known Python-object/tensor mismatch; infer no positives."""
        if not handle_valid:
            return TypeCompatibilityState.NOT_ESTABLISHED, None
        slot = bundle.semantic.slots.get(item.slot)
        materialization = registry.graph.materializations.get(item.handle.materialization)
        if slot is None or materialization is None:
            return TypeCompatibilityState.NOT_ESTABLISHED, None
        # These are exact Python bool type spellings. A tensor dtype of bool is
        # deliberately not inspected or treated as a Python bool singleton.
        if (slot.semantic_type in {"python.bool", "builtins.bool"}
                and materialization.representation == "strided_tensor"):
            return (TypeCompatibilityState.INCOMPATIBLE,
                    f"INCOMPATIBLE binding: Python bool slot {item.slot.wire} "
                    "cannot use a strided-tensor materialization")
        return TypeCompatibilityState.NOT_ESTABLISHED, None

    def _validate_call(self, call: InvocationCall, bundle: IRBundle,
                       registry: ProvenanceRegistry) -> list[str]:
        errors = []
        instance = bundle.evidence.instances.get(call.instance)
        if instance is None:
            return [f"unknown operation instance: {call.instance.wire}"]
        if call.definition not in bundle.semantic.definitions:
            errors.append(f"unknown call definition: {call.definition.wire}")
        if instance.definition != call.definition:
            errors.append(f"call definition differs from instance owner: {call.instance.wire}")
        if type(call.process_id) is not type(instance.process_id) or call.process_id != instance.process_id:
            errors.append(f"call process differs from instance: {call.instance.wire}")
        if type(call.thread_id) is not type(instance.thread_id) or call.thread_id != instance.thread_id:
            errors.append(f"call thread differs from instance: {call.instance.wire}")
        if call.entry.scope != self.clock.scope or call.exit.scope != self.clock.scope:
            errors.append(f"call event scope/clock mismatch: {call.instance.wire}")
        if call.entry.ordinal > call.exit.ordinal:
            errors.append(f"call entry follows exit: {call.instance.wire}")
        if call.exit.ordinal > registry.current_event.ordinal:
            errors.append(f"call exit is later than registry current event: {call.instance.wire}")
        errors.extend(_evidence_errors(call.evidence, registry.scope,
                                       f"call evidence {call.instance.wire}"))
        if call.evidence.kind is EvidenceKind.OBSERVED and instance.status.value != "Observed":
            errors.append(f"OBSERVED call evidence would upgrade non-observed instance: {call.instance.wire}")
        return errors

    def _validate_binding(self, item: InvocationSlotBinding, call: InvocationCall,
                          definition, bundle: IRBundle,
                          registry: ProvenanceRegistry, index: _ValidationIndex,
                          handle_valid: bool) -> list[str]:
        errors = []
        slot = bundle.semantic.slots.get(item.slot)
        if slot is None:
            return [f"unknown semantic slot: {item.slot.wire}"]
        formal = {
            InvocationRole.INPUT: set(definition.input_slots),
            InvocationRole.STATE: set(definition.state_slots),
            InvocationRole.OUTPUT: set(definition.output_slots),
        }
        if item.role is InvocationRole.READ:
            if item.slot not in index.reads_by_definition.get(definition.id, ()):
                errors.append(f"READ binding lacks a READS_SLOT edge: {item.slot.wire}")
        elif item.slot not in formal[item.role]:
            errors.append(f"slot {item.slot.wire} does not have role {item.role.value} "
                          f"for {definition.id.wire}")
        if item.role in (InvocationRole.INPUT, InvocationRole.STATE, InvocationRole.OUTPUT):
            if slot.owner != definition.id:
                errors.append(f"formal slot owner differs from operation: {item.slot.wire}")
        if item.at.scope != self.clock.scope:
            errors.append(f"binding event scope/clock mismatch: {item.slot.wire}")
        if not call.entry.ordinal <= item.at.ordinal <= call.exit.ordinal:
            errors.append(f"binding event is outside call interval: {item.slot.wire}")
        if item.role is InvocationRole.INPUT and item.at.ordinal != call.entry.ordinal:
            errors.append(f"input binding must be sampled at call entry: {item.slot.wire}")
        if item.role is InvocationRole.OUTPUT and item.at.ordinal != call.exit.ordinal:
            errors.append(f"output binding must be sampled at call exit: {item.slot.wire}")
        errors.extend(_evidence_errors(item.evidence, registry.scope,
                                       f"binding evidence {item.slot.wire}"))
        if not handle_valid:
            errors.append(f"unknown, stale or cross-graph value handle: {item.handle.materialization.wire}")
        elif not self._handle_valid_at(item.handle, item.at, registry):
            errors.append(f"materialization or allocation is not live at binding event: "
                          f"{item.handle.materialization.wire}")
        interval = index.live_interval(call.instance.wire, item.slot, item.at)
        if interval is None:
            errors.append(f"no unique live registry binding interval for "
                          f"{call.instance.wire} {item.slot.wire}")
        elif interval.handle != item.handle:
            errors.append(f"registry interval handle mismatch for {call.instance.wire} {item.slot.wire}")
        elif interval.evidence != item.evidence:
            errors.append(f"overlay evidence does not match registry observer record for {item.slot.wire}")
        return errors

    @staticmethod
    def _valid_handle_references(handle: ValueHandle, bundle: IRBundle,
                                 registry: ProvenanceRegistry,
                                 index: _ValidationIndex) -> bool:
        if registry.handles.get(handle.materialization) != handle:
            return False
        for graph in (registry.graph, bundle.values):
            version = graph.versions.get(handle.version)
            materialization = graph.materializations.get(handle.materialization)
            if version is None or materialization is None:
                return False
            if materialization.value_version != handle.version:
                return False
            if version.control_scope not in (None, registry.scope):
                return False
            if materialization.validity_scope != registry.scope:
                return False
            object_index = (index.registry_objects if graph is registry.graph
                            else index.bundle_objects)
            matching_bindings = object_index.get(
                (handle.object_id, handle.version, registry.scope), ())
            if not matching_bindings:
                return False
            if materialization.region is not None:
                region = graph.regions.get(materialization.region)
                if region is None or region.allocation not in graph.allocations:
                    return False
        registry_region_id = registry.graph.materializations[handle.materialization].region
        if registry_region_id is not None:
            if (registry.graph.regions[registry_region_id] != bundle.values.regions.get(registry_region_id)
                    or registry.graph.allocations[registry.graph.regions[registry_region_id].allocation]
                    != bundle.values.allocations.get(
                        registry.graph.regions[registry_region_id].allocation)):
                return False
        key = (handle.object_id, handle.version, registry.scope)
        registry_bindings = index.registry_objects.get(key, ())
        bundle_bindings = index.bundle_objects.get(key, ())
        return (registry.graph.versions[handle.version] == bundle.values.versions[handle.version]
                and registry.graph.materializations[handle.materialization]
                == bundle.values.materializations[handle.materialization]
                and any(item in bundle_bindings for item in registry_bindings))

    @staticmethod
    def _handle_valid_at(handle: ValueHandle, at: EventPoint,
                         registry: ProvenanceRegistry) -> bool:
        validity = registry.validity.get(handle.materialization)
        if validity is None or validity.start_event.scope != at.scope:
            return False
        if validity.start_event.ordinal > at.ordinal:
            return False
        if validity.end_event is not None and at.ordinal >= validity.end_event.ordinal:
            return False
        materialization = registry.graph.materializations.get(handle.materialization)
        if materialization is not None and materialization.region is not None:
            region = registry.graph.regions.get(materialization.region)
            lifetime = registry.lifetimes.get(region.allocation) if region is not None else None
            if lifetime is None or lifetime.start_event.ordinal > at.ordinal:
                return False
            if lifetime.end_event is not None and at.ordinal >= lifetime.end_event.ordinal:
                return False
        return True

def _evidence_errors(evidence: EvidenceClaim, scope: str, label: str) -> list[str]:
    errors = record_errors(evidence, EvidenceClaim, label)
    if errors:
        return errors
    if evidence.kind in (EvidenceKind.UNKNOWN, EvidenceKind.PROPOSED):
        errors.append(f"{label} cannot be UNKNOWN or PROPOSED")
    if not evidence.references:
        errors.append(f"{label} requires explicit observer references")
    if evidence.scope != scope:
        errors.append(f"{label} scope differs from registry scope")
    return errors


def _binding_key(item: tuple[OperationInstanceID, InvocationRole, ValueSlotID]):
    instance, role, slot = item
    return instance.wire, role.value, slot.wire


def _event_dict(event: EventPoint) -> dict[str, Any]:
    return {"scope": event.scope, "ordinal": event.ordinal, "label": event.label}


def _handle_dict(handle: ValueHandle) -> dict[str, Any]:
    return {
        "object_id": handle.object_id.as_dict(),
        "version": handle.version.as_dict(),
        "materialization": handle.materialization.as_dict(),
    }


def _decode_id(expected: type[Identifier], document: Any) -> Identifier:
    if not isinstance(document, dict) or set(document) != {"kind", "value", "wire"}:
        raise ValueError("invalid typed invocation binding ID")
    result = expected(document["value"])
    if result.prefix != document["kind"] or result.wire != document["wire"]:
        raise ValueError("invocation binding ID kind/wire mismatch")
    return result


def _decode_version(document: Any) -> ValueVersionID:
    if not isinstance(document, dict) or set(document) != {"logical_value", "version", "wire"}:
        raise ValueError("invalid invocation value version")
    result = ValueVersionID(_decode_id(LogicalValueID, document["logical_value"]),
                            document["version"])
    if result.wire != document["wire"]:
        raise ValueError("invocation value version wire mismatch")
    return result


def _decode_event(document: Any) -> EventPoint:
    if not isinstance(document, dict) or set(document) != {"scope", "ordinal", "label"}:
        raise ValueError("invalid invocation event point")
    return EventPoint(document["scope"], document["ordinal"], document["label"])


def _decode_evidence(document: Any) -> EvidenceClaim:
    expected = {"kind", "references", "scope", "confidence", "assumptions"}
    if not isinstance(document, dict) or set(document) != expected:
        raise ValueError("invalid invocation evidence claim")
    if not isinstance(document["references"], list) or not isinstance(document["assumptions"], list):
        raise ValueError("invocation evidence sequences must be JSON arrays")
    return EvidenceClaim(EvidenceKind(document["kind"]), tuple(document["references"]),
                         document["scope"], document["confidence"],
                         tuple(document["assumptions"]))


def _decode_clock(document: Any) -> InvocationClock:
    if not isinstance(document, dict) or set(document) != {"scope", "domain"}:
        raise ValueError("invalid invocation clock")
    return InvocationClock(document["scope"], InvocationClockDomain(document["domain"]))


def _decode_call(document: Any) -> InvocationCall:
    expected = {"instance", "definition", "process_id", "thread_id", "entry", "exit", "evidence"}
    if not isinstance(document, dict) or set(document) != expected:
        raise ValueError("invalid invocation call fields")
    return InvocationCall(
        _decode_id(OperationInstanceID, document["instance"]),
        _decode_id(OperationDefinitionID, document["definition"]),
        document["process_id"], document["thread_id"],
        _decode_event(document["entry"]), _decode_event(document["exit"]),
        _decode_evidence(document["evidence"]))


def _decode_handle(document: Any) -> ValueHandle:
    if not isinstance(document, dict) or set(document) != {"object_id", "version", "materialization"}:
        raise ValueError("invalid invocation value handle")
    return ValueHandle(_decode_id(ObjectID, document["object_id"]),
                       _decode_version(document["version"]),
                       _decode_id(MaterializationID, document["materialization"]))


def _decode_binding(document: Any) -> InvocationSlotBinding:
    expected = {"instance", "role", "slot", "handle", "at", "evidence"}
    if not isinstance(document, dict) or set(document) != expected:
        raise ValueError("invalid invocation slot binding fields")
    return InvocationSlotBinding(
        _decode_id(OperationInstanceID, document["instance"]),
        InvocationRole(document["role"]),
        _decode_id(ValueSlotID, document["slot"]),
        _decode_handle(document["handle"]),
        _decode_event(document["at"]), _decode_evidence(document["evidence"]))


__all__ = [
    "BindingGuard", "InvocationBindingReport", "InvocationBindingsV2", "InvocationCall",
    "InvocationClock", "InvocationClockDomain", "InvocationRole", "InvocationSlotBinding",
    "SlotCoverageState", "StructureState", "TypeCompatibilityState",
]
