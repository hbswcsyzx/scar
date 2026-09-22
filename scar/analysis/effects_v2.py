"""Scoped compositional effect closure for explicitly supplied regions.

The engine combines declared/observed effects; it does not discover regions,
execute programs, infer purity from empty traces, or choose transformations.
Static definition containment is deliberately not interpreted as dynamic calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fnmatch import fnmatchcase
import hashlib
import json
from typing import Any

from scar.ir.record_codec import decode as _decode, encode as _encode
from scar.ir.v2 import (
    Completeness, ControlRegionID, EffectPresence, EffectSet, EffectSummary,
    EffectSummaryID, EffectTarget, EffectTargetKind, EvidenceClaim, EvidenceGraph,
    EvidenceKind, OperationDefinitionID, OperationInstanceID, SemanticGraph,
    SourceAtomID, ValueSlotID,
)
from scar.ir.v2._validation import cycle_errors, mapping_errors, record_errors


class EffectDimension(str, Enum):
    READS = "reads"
    WRITES = "writes"
    ALLOCATES = "allocates"
    FREES = "frees"
    ALIASES = "aliases"
    ESCAPES = "escapes"
    RNG = "rng"
    MAY_RAISE = "may_raise"
    EXTERNAL = "external"
    ORDERING = "ordering"


class ScopeMode(str, Enum):
    DYNAMIC_PATH = "dynamic_path"
    ALL_PATHS = "all_paths"


class ClosureState(str, Enum):
    LIVE = "LIVE"
    DEAD_IN_SCOPE = "DEAD_IN_SCOPE"
    OPEN = "OPEN"


@dataclass(frozen=True)
class ObservationScope:
    id: str
    entry: str
    exit: str | None
    run_id: str
    mode: ScopeMode
    clock_domain: str
    process_id: str | None = None
    thread_id: str | None = None
    control: ControlRegionID | None = None
    collectors: tuple[str, ...] = ()
    closed: bool = False
    evidence: tuple[EvidenceClaim, ...] = ()

    def __post_init__(self):
        if not self.id or not self.entry or not self.run_id or not self.clock_domain:
            raise ValueError("observation scope requires identity, entry, run and time domain")
        if self.closed and (not self.exit or not _supported(self.evidence)):
            raise ValueError("closed scope requires an exit and auditable closure evidence")


@dataclass(frozen=True)
class EffectOccurrence:
    id: str
    definition: OperationDefinitionID
    dimension: EffectDimension
    target: EffectTarget
    scope: str
    position: int | None
    evidence: EvidenceClaim
    instance: OperationInstanceID | None = None
    dependencies: tuple[str, ...] = ()
    ordered_after: tuple[str, ...] = ()
    source_atoms: tuple[SourceAtomID, ...] = ()
    raw_references: tuple[str, ...] = ()
    related_targets: tuple[EffectTarget, ...] = ()
    dependency_coverage: Completeness = Completeness.UNKNOWN
    order_coverage: Completeness = Completeness.UNKNOWN

    def __post_init__(self):
        if not self.id or not self.scope:
            raise ValueError("effect occurrence requires identity and scope")
        if self.position is not None and (type(self.position) is not int or self.position < 0):
            raise ValueError("effect position must be a non-negative integer")
        if (self.dependency_coverage is Completeness.COMPLETE or self.order_coverage is Completeness.COMPLETE) and not _supported((self.evidence,)):
            raise ValueError("complete occurrence dependency/order coverage requires auditable evidence")


@dataclass(frozen=True)
class EffectCoverage:
    scope: str
    dimension: EffectDimension
    completeness: Completeness
    target_domain: tuple[str, ...] = ("*",)
    branches: Completeness = Completeness.UNKNOWN
    calls: Completeness = Completeness.UNKNOWN
    aliases: Completeness = Completeness.UNKNOWN
    evidence: tuple[EvidenceClaim, ...] = ()
    assumptions: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.scope or any(not domain for domain in self.target_domain):
            raise ValueError("effect coverage requires scope and target domains")
        if self.completeness is Completeness.COMPLETE and not self.target_domain:
            raise ValueError("complete coverage cannot have an empty target domain")
        if self.completeness is Completeness.COMPLETE and not _supported(self.evidence):
            raise ValueError("complete effect coverage requires auditable evidence")

    @property
    def closed(self) -> bool:
        return (self.completeness is Completeness.COMPLETE
                and self.branches is Completeness.COMPLETE
                and self.calls is Completeness.COMPLETE
                and self.aliases is Completeness.COMPLETE)


@dataclass(frozen=True)
class OperationEffects:
    definition: OperationDefinitionID
    scope: str
    occurrences: tuple[str, ...] = ()
    coverage: tuple[EffectCoverage, ...] = ()
    children: tuple[OperationDefinitionID, ...] = ()
    inclusive: bool = False
    open_boundaries: tuple[str, ...] = ()


@dataclass(frozen=True)
class EffectGap:
    definition: OperationDefinitionID | None
    scope: str
    dimension: EffectDimension | None
    reason: str


@dataclass(frozen=True)
class BoundarySummary:
    members: tuple[OperationDefinitionID, ...]
    scope: str
    occurrences: tuple[EffectOccurrence, ...]
    effects: EffectSummary
    coverage: tuple[EffectCoverage, ...]
    entry_reads: tuple[EffectTarget, ...]
    outward_writes: tuple[EffectTarget, ...]
    open_boundaries: tuple[str, ...]
    gaps: tuple[EffectGap, ...]
    ready_for_region_construction: bool
    mode: ScopeMode = ScopeMode.DYNAMIC_PATH

    def as_dict(self):
        return _encode(self)


@dataclass(frozen=True)
class ConsumerClosure:
    target: EffectTarget
    scope: str
    state: ClosureState
    visited_consumers: tuple[OperationDefinitionID, ...]
    endpoint: str | None
    open_boundaries: tuple[str, ...]
    coverage: tuple[EffectCoverage, ...]
    evidence: tuple[EvidenceClaim, ...]
    reason: str

    def as_dict(self):
        return _encode(self)


@dataclass(frozen=True)
class ResidualSlice:
    scope: str
    occurrences: tuple[EffectOccurrence, ...]
    dependencies: tuple[str, ...]
    order_edges: tuple[tuple[str, str], ...]
    open_boundaries: tuple[str, ...]
    requires_original_region: bool

    def as_dict(self):
        return _encode(self)


def _supported(evidence):
    return any(item.kind not in (EvidenceKind.UNKNOWN, EvidenceKind.PROPOSED)
               and item.references for item in evidence)


def _target_key(target):
    return target.kind.value + ":" + target.reference


def _targets(occurrences, dimension):
    return tuple(sorted({item.target for item in occurrences if item.dimension is dimension},
                        key=_target_key))


def _merge_completeness(values):
    values = tuple(values)
    if values and all(value is Completeness.COMPLETE for value in values):
        return Completeness.COMPLETE
    if any(value is not Completeness.UNKNOWN for value in values):
        return Completeness.PARTIAL
    return Completeness.UNKNOWN


def _ordered_occurrences(items):
    return tuple(sorted(items, key=lambda item: (item.position is None,
                                                item.position if item.position is not None else 0, item.id)))


class EffectClosureEngine:
    SCHEMA = "scar.effects.closure"
    SCHEMA_VERSION = 1

    def __init__(self, semantic: SemanticGraph, evidence: EvidenceGraph | None = None):
        self.semantic, self.evidence = semantic, evidence
        self.scopes: dict[str, ObservationScope] = {}
        self.occurrences: dict[str, EffectOccurrence] = {}
        self.operations: dict[tuple[OperationDefinitionID, str], OperationEffects] = {}

    @staticmethod
    def _typed(record, expected):
        errors = record_errors(record, expected, expected.__name__)
        if errors:
            raise ValueError("invalid effect record: " + "; ".join(errors))

    def add_scope(self, scope: ObservationScope):
        self._typed(scope, ObservationScope)
        if scope.id in self.scopes:
            raise ValueError("duplicate observation scope")
        if scope.control is not None and scope.control not in self.semantic.controls:
            raise ValueError("scope references unknown control")
        self.scopes[scope.id] = scope

    def add_occurrence(self, occurrence: EffectOccurrence):
        self._typed(occurrence, EffectOccurrence)
        if occurrence.id in self.occurrences:
            raise ValueError("duplicate effect occurrence identity")
        errors = self._occurrence_errors(occurrence)
        if errors:
            raise ValueError("invalid occurrence: " + "; ".join(errors))
        self.occurrences[occurrence.id] = occurrence

    def add_operation_effects(self, effects: OperationEffects):
        self._typed(effects, OperationEffects)
        key = (effects.definition, effects.scope)
        if key in self.operations:
            raise ValueError("duplicate operation effect summary in scope")
        errors = self._operation_errors(effects)
        if errors:
            raise ValueError("invalid operation effects: " + "; ".join(errors))
        self.operations[key] = effects

    def _occurrence_errors(self, occurrence):
        errors = []
        if occurrence.definition not in self.semantic.definitions:
            errors.append("unknown occurrence definition")
        if occurrence.scope not in self.scopes:
            errors.append("unknown occurrence scope")
        if occurrence.instance is not None and (
            self.evidence is None or occurrence.instance not in self.evidence.instances
        ):
            errors.append("unknown occurrence instance")
        elif occurrence.instance is not None and occurrence.scope in self.scopes:
            instance = self.evidence.instances[occurrence.instance]
            scope = self.scopes[occurrence.scope]
            if scope.process_id is not None and scope.process_id != str(instance.process_id):
                errors.append("occurrence instance belongs to a different process scope")
            if scope.thread_id is not None and scope.thread_id != str(instance.thread_id):
                errors.append("occurrence instance belongs to a different thread scope")
        for source in occurrence.source_atoms:
            if source not in self.semantic.source_atoms:
                errors.append("unknown occurrence source atom")
        # Exact typed references for local SG state are checked.  Other target
        # kinds describe external domains and need collector/library contracts.
        if occurrence.target.kind is EffectTargetKind.VALUE_SLOT and (
            not occurrence.target.reference.startswith("slot:")
            or not occurrence.target.reference[5:]
            or ValueSlotID(occurrence.target.reference[5:]) not in self.semantic.slots
        ):
            errors.append("unknown effect value slot")
        if occurrence.dimension is EffectDimension.RNG and occurrence.target.kind not in (
            EffectTargetKind.RNG, EffectTargetKind.OPAQUE
        ):
            errors.append("RNG occurrence requires RNG or opaque target")
        if occurrence.dimension is EffectDimension.ORDERING and occurrence.target.kind not in (
            EffectTargetKind.ORDERING, EffectTargetKind.OPAQUE
        ):
            errors.append("ordering occurrence requires ordering or opaque target")
        return errors

    def _operation_errors(self, effects):
        errors = []
        if effects.definition not in self.semantic.definitions or effects.scope not in self.scopes:
            errors.append("unknown operation definition or scope")
        if len({item.dimension for item in effects.coverage}) != len(effects.coverage):
            errors.append("coverage dimensions must be unique within operation")
        if len(set(effects.occurrences)) != len(effects.occurrences):
            errors.append("duplicate occurrence reference within summary")
        for child in effects.children:
            if child not in self.semantic.definitions:
                errors.append("unknown child definition")
        for coverage in effects.coverage:
            if coverage.scope != effects.scope:
                errors.append("coverage scope differs from operation scope")
        for identity in effects.occurrences:
            occurrence = self.occurrences.get(identity)
            if occurrence is None:
                errors.append("unknown effect occurrence")
            elif occurrence.scope != effects.scope:
                errors.append("occurrence scope differs from operation scope")
            elif not effects.inclusive and occurrence.definition != effects.definition:
                errors.append("direct summary includes another definition's occurrence")
        return errors

    def validate(self):
        errors = mapping_errors(self.scopes, str, ObservationScope, "scopes")
        errors.extend(mapping_errors(self.occurrences, str, EffectOccurrence, "occurrences"))
        for key, effects in self.operations.items():
            errors.extend(record_errors(key, tuple[OperationDefinitionID, str], "operation key"))
            errors.extend(record_errors(effects, OperationEffects, "operation effects"))
        if errors:
            return {"valid": False, "errors": errors}
        for key, scope in self.scopes.items():
            if key != scope.id:
                errors.append("scope registry key mismatch")
            if scope.control is not None and scope.control not in self.semantic.controls:
                errors.append("scope references unknown control")
        for key, occurrence in self.occurrences.items():
            if key != occurrence.id:
                errors.append("occurrence registry key mismatch")
        for key, effects in self.operations.items():
            if key != (effects.definition, effects.scope):
                errors.append("operation summary registry key mismatch")
        if errors:
            return {"valid": False, "errors": errors}
        for occurrence in self.occurrences.values():
            errors.extend(self._occurrence_errors(occurrence))
            for dependency in occurrence.dependencies + occurrence.ordered_after:
                if dependency not in self.occurrences:
                    errors.append(f"unknown effect dependency {dependency}")
                elif self.occurrences[dependency].scope != occurrence.scope:
                    errors.append("dependency crosses incomparable observation scopes")
            for previous in occurrence.ordered_after:
                predecessor = self.occurrences.get(previous)
                if (predecessor and predecessor.position is not None and occurrence.position is not None
                        and predecessor.position >= occurrence.position):
                    errors.append("ordering edge contradicts scoped sequence positions")
        for effects in self.operations.values():
            errors.extend(self._operation_errors(effects))
        order_arcs = {scope: [] for scope in self.scopes}
        for item in self.occurrences.values():
            if item.scope in order_arcs:
                order_arcs[item.scope].extend((previous, item.id) for previous in item.ordered_after)
        for arcs in order_arcs.values():
            errors.extend(cycle_errors(arcs, "effect ordering"))
        return {"valid": not errors, "errors": errors,
                "counts": {"scopes": len(self.scopes), "occurrences": len(self.occurrences),
                           "operation_summaries": len(self.operations)}}

    def assert_valid(self):
        report = self.validate()
        if not report["valid"]:
            raise ValueError("invalid effect closure: " + "; ".join(report["errors"]))
        return report

    def _members(self, members, scope):
        if scope not in self.scopes:
            raise ValueError("unknown observation scope")
        reached, pending = set(), list(members)
        while pending:
            definition = pending.pop()
            if definition not in self.semantic.definitions:
                raise ValueError("unknown boundary member")
            if definition in reached:
                continue  # monotone fixed point also terminates recursive SCCs
            reached.add(definition)
            effects = self.operations.get((definition, scope))
            if effects is not None:
                pending.extend(effects.children)
                if effects.inclusive:
                    pending.extend(self.occurrences[identity].definition for identity in effects.occurrences)
        return tuple(sorted(reached, key=lambda item: item.wire))

    def boundary(self, members, scope: str) -> BoundarySummary:
        return self.boundaries(((members, scope),))[0]

    def boundaries(self, requests) -> tuple[BoundarySummary, ...]:
        """Validate one snapshot and answer a batch without persistent caches."""
        self.assert_valid()
        occurrence_index = {}
        for occurrence in self.occurrences.values():
            occurrence_index.setdefault((occurrence.scope, occurrence.definition), []).append(occurrence.id)
        return tuple(self._boundary(members, scope, occurrence_index) for members, scope in requests)

    def _boundary(self, members, scope, occurrence_index):
        members = self._members(members, scope)
        if not members:
            raise ValueError("boundary requires at least one member")
        member_set = set(members)
        occurrence_ids, gaps = set(), []
        observations = []
        for definition in members:
            effects = self.operations.get((definition, scope))
            if effects is None:
                gaps.extend(EffectGap(definition, scope, dimension, "no scoped direct effect observation or contract")
                            for dimension in EffectDimension)
                continue
            observations.append(effects)
            occurrence_ids.update(effects.occurrences)
            gaps.extend(EffectGap(definition, scope, None, boundary) for boundary in effects.open_boundaries)
        # Include directly observed occurrences even if a caller omitted an
        # OperationEffects projection.  Missing coverage remains an explicit gap.
        for definition in member_set:
            occurrence_ids.update(occurrence_index.get((scope, definition), ()))
        occurrences = _ordered_occurrences(self.occurrences[identity] for identity in occurrence_ids)
        merged = []
        for dimension in EffectDimension:
            coverages = []
            for definition in members:
                effects = self.operations.get((definition, scope))
                coverage = next((item for item in effects.coverage if item.dimension is dimension), None) if effects else None
                if coverage is None:
                    coverage = EffectCoverage(scope, dimension, Completeness.UNKNOWN)
                coverages.append(coverage)
                if not coverage.closed or "*" not in coverage.target_domain:
                    gaps.append(EffectGap(definition, scope, dimension,
                        "coverage does not close branch, call, alias and complete target domain"))
            completeness = _merge_completeness(item.completeness for item in coverages)
            if any(item.dimension is dimension for item in occurrences) and completeness is Completeness.UNKNOWN:
                completeness = Completeness.PARTIAL
            # Every member must cover a target before the composed region can
            # cover it.  A union would silently fill one child's missing domain.
            domains = None
            for item in coverages:
                if "*" not in item.target_domain:
                    domains = set(item.target_domain) if domains is None else domains & set(item.target_domain)
            target_domain = ("*",) if domains is None else tuple(sorted(domains))
            if not target_domain and completeness is Completeness.COMPLETE:
                completeness = Completeness.PARTIAL
            merged.append(EffectCoverage(scope, dimension, completeness,
                target_domain=target_domain,
                branches=_merge_completeness(item.branches for item in coverages),
                calls=_merge_completeness(item.calls for item in coverages),
                aliases=_merge_completeness(item.aliases for item in coverages),
                evidence=tuple(claim for item in coverages for claim in item.evidence),
                assumptions=tuple(sorted({assumption for item in coverages for assumption in item.assumptions}))))
        coverage_map = {item.dimension: item for item in merged}
        collection_dimensions = (EffectDimension.READS, EffectDimension.WRITES, EffectDimension.ALLOCATES,
                                 EffectDimension.FREES, EffectDimension.ALIASES, EffectDimension.ESCAPES)
        collections = {dimension.value: EffectSet(_targets(occurrences, dimension),
            Completeness.COMPLETE if coverage_map[dimension].closed and "*" in coverage_map[dimension].target_domain
            else Completeness.PARTIAL if _targets(occurrences, dimension) else Completeness.UNKNOWN)
            for dimension in collection_dimensions}
        presences = {}
        for dimension in (EffectDimension.RNG, EffectDimension.MAY_RAISE, EffectDimension.EXTERNAL, EffectDimension.ORDERING):
            presences[dimension.value] = EffectPresence.PRESENT if _targets(occurrences, dimension) else (
                EffectPresence.NONE if coverage_map[dimension].closed and "*" in coverage_map[dimension].target_domain
                else EffectPresence.UNKNOWN)
        identity = hashlib.sha256((scope + ":" + ",".join(item.wire for item in members)).encode()).hexdigest()[:24]
        summary = EffectSummary(EffectSummaryID("boundary:" + identity), **collections, **presences,
            evidence=tuple(item.evidence for item in occurrences))
        if not self.scopes[scope].closed:
            gaps.append(EffectGap(None, scope, None, "observation scope has no evidenced closed endpoint"))
        unique_gaps = tuple(sorted(set(gaps), key=lambda item: (
            item.definition.wire if item.definition else "", item.dimension.value if item.dimension else "", item.reason)))
        return BoundarySummary(members, scope, occurrences, summary, tuple(merged),
            _targets(occurrences, EffectDimension.READS), _targets(occurrences, EffectDimension.WRITES),
            tuple(sorted({gap.reason for gap in unique_gaps})), unique_gaps,
            not unique_gaps and summary.is_complete, self.scopes[scope].mode)

    def consumer_closure(self, target: EffectTarget, scope: str, *, required_consumers=None,
                         members=(), coverage: tuple[EffectCoverage, ...] | None = None,
                         scope_end_closed: bool | None = None) -> ConsumerClosure:
        self.assert_valid()
        self._typed(target, EffectTarget)
        if scope not in self.scopes:
            raise ValueError("unknown consumer observation scope")
        required = set(self.semantic.definitions) if required_consumers is None else set(required_consumers)
        if any(definition not in self.semantic.definitions for definition in required):
            raise ValueError("unknown required consumer")
        selected = self._members(members, scope) if members else tuple(self.semantic.definitions)
        known = [item for item in self.occurrences.values() if item.scope == scope]
        visited, targets, pending, reasons = set(), {target}, [target], set()
        while pending:
            current = pending.pop()
            for item in known:
                if item.target != current and not (item.dimension is EffectDimension.ALIASES
                                                  and current in item.related_targets):
                    continue
                if item.dimension in (EffectDimension.READS, EffectDimension.ALIASES, EffectDimension.ESCAPES):
                    visited.add(item.definition)
                if item.dimension is EffectDimension.ESCAPES:
                    reasons.add("value escapes to a callback, external consumer or future scope")
                if item.dimension is EffectDimension.ALIASES:
                    if not item.related_targets:
                        reasons.add("alias target mapping is incomplete")
                    for related in (item.target,) + item.related_targets:
                        if related not in targets:
                            targets.add(related)
                            pending.append(related)
        for definition in selected:
            effects = self.operations.get((definition, scope))
            if effects:
                reasons.update(effects.open_boundaries)
        if coverage is None:
            coverage = self.boundary(selected, scope).coverage if selected else ()
        for item in coverage:
            self._typed(item, EffectCoverage)
            if item.scope != scope:
                raise ValueError("consumer coverage belongs to another scope")
        if len({item.dimension for item in coverage}) != len(coverage):
            raise ValueError("consumer coverage dimensions must be unique")
        needed = {EffectDimension.READS, EffectDimension.ALIASES, EffectDimension.ESCAPES,
                  EffectDimension.MAY_RAISE, EffectDimension.ORDERING}
        if target.kind in (EffectTargetKind.STORAGE, EffectTargetKind.OBJECT):
            needed.update((EffectDimension.ALLOCATES, EffectDimension.FREES))
        by_dimension = {item.dimension: item for item in coverage}
        for dimension in needed:
            item = by_dimension.get(dimension)
            if item is None or not item.closed or any(not any(
                fnmatchcase(_target_key(value), domain) for domain in item.target_domain) for value in targets):
                reasons.add(f"{dimension.value} consumer/branch/call/alias coverage is incomplete")
        observation_scope = self.scopes[scope]
        if not observation_scope.closed or scope_end_closed is False:
            reasons.add("future consumers beyond observation endpoint remain open")
        if visited & required:
            state, reason = ClosureState.LIVE, "found a consumer required by the explicit contract"
        elif reasons:
            state, reason = ClosureState.OPEN, "consumer closure has unobserved or escaped boundaries"
        else:
            state, reason = ClosureState.DEAD_IN_SCOPE, "no required consumer within the evidenced closed scope"
        return ConsumerClosure(target, scope, state, tuple(sorted(visited, key=lambda item: item.wire)),
            observation_scope.exit, tuple(sorted(reasons)), tuple(coverage),
            tuple(claim for item in coverage for claim in item.evidence), reason)

    def residual_slice(self, required_occurrence_ids, scope: str) -> ResidualSlice:
        self.assert_valid()
        if scope not in self.scopes:
            raise ValueError("unknown residual observation scope")
        selected, pending, reasons = set(), list(required_occurrence_ids), set()
        while pending:
            identity = pending.pop()
            if identity in selected:
                continue
            occurrence = self.occurrences.get(identity)
            if occurrence is None or occurrence.scope != scope:
                raise ValueError("residual references unknown occurrence or different scope")
            selected.add(identity)
            if occurrence.dependency_coverage is not Completeness.COMPLETE:
                reasons.add("effect occurrence dependency edges are not proved complete")
            if occurrence.order_coverage is not Completeness.COMPLETE:
                reasons.add("effect occurrence ordering edges are not proved complete")
            pending.extend(occurrence.dependencies)
            # An ordering predecessor can have visible effects or raise.  It
            # must remain until a later transformation proves it removable.
            pending.extend(occurrence.ordered_after)
            effects = self.operations.get((occurrence.definition, scope))
            if effects is None:
                reasons.add("effect producer lacks a scoped dependency/coverage summary")
            else:
                reasons.update(effects.open_boundaries)
                coverage = {item.dimension: item for item in effects.coverage}
                for dimension in (EffectDimension.READS, EffectDimension.MAY_RAISE, EffectDimension.ORDERING):
                    if dimension not in coverage or not coverage[dimension].closed:
                        reasons.add(f"effect producer {dimension.value} dependencies are not closed")
            if occurrence.position is None:
                reasons.add("effect has no scoped sequence position; original ordering boundary is required")
        occurrences = _ordered_occurrences(self.occurrences[identity] for identity in selected)
        order = {(previous, item.id) for item in occurrences for previous in item.ordered_after if previous in selected}
        positioned = [item for item in occurrences if item.position is not None]
        order.update((left.id, right.id) for left, right in zip(positioned, positioned[1:])
                     if left.position < right.position)
        reasons.update(cycle_errors(((dependency, item.id) for item in occurrences
                                    for dependency in item.dependencies), "residual dependencies"))
        if not self.scopes[scope].closed:
            reasons.add("scope endpoint and exception continuation remain open")
        return ResidualSlice(scope, occurrences,
            tuple(sorted({dependency for item in occurrences for dependency in item.dependencies})),
            tuple(sorted(order)), tuple(sorted(reasons)), bool(reasons))

    def to_dict(self):
        validation = self.assert_valid()
        return {"schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION,
            "scopes": [_encode(self.scopes[key]) for key in sorted(self.scopes)],
            "occurrences": [_encode(self.occurrences[key]) for key in sorted(self.occurrences)],
            "operations": [_encode(self.operations[key]) for key in sorted(self.operations, key=lambda item: (item[1], item[0].wire))],
            "validation": validation}

    @classmethod
    def from_dict(cls, document, semantic: SemanticGraph, evidence: EvidenceGraph | None = None):
        if not isinstance(document, dict) or set(document) != {"schema", "schema_version", "scopes", "occurrences", "operations", "validation"}:
            raise ValueError("invalid effect closure document fields")
        if document["schema"] != cls.SCHEMA or type(document["schema_version"]) is not int or document["schema_version"] != cls.SCHEMA_VERSION:
            raise ValueError("unsupported effect closure schema")
        if any(not isinstance(document[name], list) for name in ("scopes", "occurrences", "operations")):
            raise ValueError("effect collections must be JSON arrays")
        engine = cls(semantic, evidence)
        for record in document["scopes"]:
            engine.add_scope(_decode(ObservationScope, record))
        for record in document["occurrences"]:
            engine.add_occurrence(_decode(EffectOccurrence, record))
        for record in document["operations"]:
            engine.add_operation_effects(_decode(OperationEffects, record))
        engine.assert_valid()
        return engine

    def to_json(self):
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def from_json(cls, payload, semantic, evidence=None):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON field")
                result[key] = value
            return result
        return cls.from_dict(json.loads(payload, object_pairs_hook=unique,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-finite JSON value"))), semantic, evidence)


__all__ = ["BoundarySummary", "ClosureState", "ConsumerClosure", "EffectClosureEngine", "EffectCoverage",
           "EffectDimension", "EffectGap", "EffectOccurrence", "ObservationScope", "OperationEffects",
           "ResidualSlice", "ScopeMode"]
