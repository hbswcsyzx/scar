"""Conservative effect ingestion from normalized runtime evidence.

This adapter retains runtime stub definitions and separate capture boundaries.
It supplies possible effects to the closure engine; incomplete v1 collection
never becomes a complete semantic contract or a clean performance estimate.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from scar.ir.v2 import (
    Completeness, EffectTarget, EffectTargetKind, EvidenceClaim, EvidenceKind,
    EvidenceNodeKind, EvidenceRelation, IRBundle, OperationInstanceID,
)
from .effects_v2 import (
    EffectClosureEngine, EffectCoverage, EffectDimension, EffectOccurrence,
    ObservationScope, OperationEffects, ScopeMode,
)


@dataclass
class RuntimeEffectsResult:
    engine: EffectClosureEngine
    coverage: dict[str, Any]
    instance_scopes: dict[OperationInstanceID, str]


_COLLECTIONS = tuple(EffectDimension(name) for name in (
    "reads", "writes", "allocates", "frees", "aliases", "escapes"))
_SCALARS = {"rng_effect": EffectDimension.RNG,
            "may_raise": EffectDimension.MAY_RAISE,
            "external_effect": EffectDimension.EXTERNAL,
            "ordering_effect": EffectDimension.ORDERING}
_ALLOCATION = {"allocation", "memory_allocation", "cuda_allocation"}
_FREE = {"free", "memory_free", "cuda_free"}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]


def ingest_runtime_effects(bundle: IRBundle, *, namespace="runtime-effects") -> RuntimeEffectsResult:
    """Create open dynamic scopes and explicit effect observations.

    Raw token targets are scoped to one observation boundary. Matching legacy
    strings cannot join values across records. Scalar absence assertions and
    KNOWN capture sets are retained in coverage counts, without closing calls,
    branches, aliases or future consumers. No operation name is inspected.
    """
    if not isinstance(namespace, str) or not namespace:
        raise ValueError("runtime effect namespace must be nonempty")
    bundle.assert_valid()
    engine = EffectClosureEngine(bundle.semantic, bundle.evidence)
    counts, assertions = Counter(), Counter()
    groups = defaultdict(lambda: {"occurrences": [], "children": set(), "gaps": set(),
                                  "references": set(), "inclusive": False})
    instance_scopes = {}
    allocation_targets = defaultdict(list)
    input_observations = defaultdict(list)
    for observation in bundle.evidence.observations.values():
        if observation.operation is not None and observation.role == "input":
            input_observations[observation.operation].append(observation)
    for edge in bundle.evidence.edges.values():
        if (edge.relation is EvidenceRelation.USES_STORAGE
                and edge.source.kind is EvidenceNodeKind.OPERATION_INSTANCE
                and edge.target.kind is EvidenceNodeKind.ALLOCATION):
            allocation_targets[edge.source.reference].append(edge.target.wire)

    def occurrence(instance, group, dimension, target, raw_reference, suffix,
                   *, kind=EvidenceKind.INFERRED, assumptions=()):
        identity = namespace + ":effect:" + _digest((instance.id.wire, raw_reference, dimension.value, suffix))
        fact = EffectOccurrence(
            identity, instance.definition, dimension, target, instance_scopes[instance.id],
            None, EvidenceClaim(kind, (raw_reference,), scope=instance_scopes[instance.id],
                                assumptions=tuple(assumptions)),
            instance=instance.id, raw_references=(raw_reference,))
        engine.add_occurrence(fact)
        group["occurrences"].append(identity)
        counts[dimension.value] += 1

    def opaque_target(raw_reference, dimension, suffix):
        return EffectTarget(EffectTargetKind.OPAQUE,
                            f"capture:{raw_reference}:{dimension.value}:{suffix}")

    def boundary(instance, group, data, raw_reference, *, returned=False):
        effect = data.get("legacy_effect", {})
        if not isinstance(effect, dict):
            group["gaps"].add("legacy effect payload is invalid; recollect this boundary")
            counts["invalid_effect_payloads"] += 1
            return
        for dimension in _COLLECTIONS:
            values = effect.get(dimension.value, [])
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                group["gaps"].add(f"legacy {dimension.value} members are invalid")
                counts["invalid_effect_members"] += 1
                continue
            for index, _token in enumerate(values):
                evidence_kind = EvidenceKind.INFERRED
                assumptions = ["legacy token denotes a boundary-local target; logical identity unresolved"]
                if dimension is EffectDimension.READS:
                    assumptions.append("captured argument/state may be read; actual read not observed")
                    counts["may_read_occurrences"] += 1
                elif dimension is EffectDimension.WRITES:
                    assumptions.append("legacy may-write report; exact written target and coverage unproven")
                    if instance.metadata.get("raw_kind") == "torch_dispatch":
                        assumptions.append("v1 suffix heuristic marked tensor arguments; not an observed exact write")
                    counts["may_write_occurrences"] += 1
                elif returned and dimension is EffectDimension.ESCAPES:
                    evidence_kind = EvidenceKind.OBSERVED
                    assumptions.append("returned value escapes this invocation; broader consumer boundary unresolved")
                    counts["return_escape_occurrences"] += 1
                else:
                    assumptions.append("legacy target assertion lacks a reviewed complete collector contract")
                occurrence(instance, group, dimension,
                           opaque_target(raw_reference, dimension, str(index)), raw_reference,
                           f"{'return' if returned else 'entry'}:{index}",
                           kind=evidence_kind, assumptions=assumptions)
        knowledge = effect.get("collection_knowledge", {})
        if isinstance(knowledge, dict):
            for dimension in _COLLECTIONS:
                value = knowledge.get(dimension.value, "UNKNOWN")
                assertions[f"{'return' if returned else 'entry'}:{dimension.value}:{value}"] += 1
        else:
            group["gaps"].add("legacy collection completeness is invalid")
        for field, dimension in _SCALARS.items():
            value = effect.get(field, "UNKNOWN")
            assertions[f"{'return' if returned else 'entry'}:{field}:{value}"] += 1
            if value == "KNOWN":
                kind = (EffectTargetKind.RNG if dimension is EffectDimension.RNG
                        else EffectTargetKind.ORDERING if dimension is EffectDimension.ORDERING
                        else EffectTargetKind.OPAQUE)
                occurrence(instance, group, dimension, EffectTarget(kind, f"capture:{raw_reference}:{field}"),
                           raw_reference, field, assumptions=(
                               "legacy collector asserts effect presence; target and complete execution scope unproven",))
            elif value not in ("UNKNOWN", "NONE"):
                group["gaps"].add(f"unsupported legacy {field} status")
        callbacks = data.get("returned_callables") if returned else data.get("callable_inputs")
        if data.get("callable_capture") == "UNKNOWN":
            group["gaps"].add("callable input capture did not close closure/global state")
        if callbacks:
            group["gaps"].add("callback closure/global state and future consumers require an explicit contract")
            counts["callback_boundaries"] += 1
            if returned and isinstance(callbacks, list):
                for index, callback in enumerate(callbacks):
                    if not isinstance(callback, dict) or not isinstance(callback.get("object_id"), str) or not callback["object_id"]:
                        group["gaps"].add("returned callback descriptor is invalid; escape identity is unresolved")
                        counts["invalid_callback_descriptors"] += 1
                        continue
                    occurrence(instance, group, EffectDimension.ESCAPES,
                               opaque_target(raw_reference, EffectDimension.ESCAPES, f"callback:{index}"),
                               raw_reference, f"callback:{index}", kind=EvidenceKind.OBSERVED,
                               assumptions=("callable descriptor returned; callback effects and future consumers open",))
        if returned:
            group["gaps"].add("return capture completeness applies only to the exit boundary")
        if data.get("pure_contract"):
            group["gaps"].add("legacy pure flag is a declaration requiring a versioned reviewed contract")
        if len(group["references"]) < 8:
            group["references"].add(raw_reference)

    for instance in sorted(bundle.evidence.instances.values(), key=lambda item: item.id.wire):
        metadata = instance.metadata
        clock = metadata.get("clock_domain")
        if not isinstance(clock, str) or not clock:
            clock = "unresolved:" + instance.id.wire
        key = (type(instance.process_id).__name__, instance.process_id,
               type(instance.thread_id).__name__, instance.thread_id, clock)
        scope_id = namespace + ":scope:" + _digest(key)
        raw_reference = metadata.get("raw_reference") or instance.id.wire
        if scope_id not in engine.scopes:
            engine.add_scope(ObservationScope(
                scope_id, f"captured-runtime-context:{_digest(key)}", None, namespace,
                ScopeMode.DYNAMIC_PATH, clock, str(instance.process_id), str(instance.thread_id),
                collectors=("scar.v1",), closed=False))
        instance_scopes[instance.id] = scope_id
        group = groups[(instance.definition, scope_id)]
        group["gaps"].add("v1 collection does not close hidden calls, aliases, branches or future consumers")
        raw_kind = metadata.get("raw_kind")
        group["inclusive"] |= raw_kind in {"python_call", "module_call"}
        if raw_kind in {"python_call", "module_call"}:
            group["gaps"].add("hook spans can include child observations; occurrences are not independent cost units")
        if raw_kind == "python_call":
            group["gaps"].add("Python profile return/completion does not establish exception-free behavior")
        exit_boundary = metadata.get("return_boundary")
        if raw_kind == "unmatched_python_return" and isinstance(exit_boundary, dict):
            # The orphan's own legacy_effect is the same return record; ingest
            # it once rather than duplicating it as an entry and an exit.
            boundary(instance, group, exit_boundary, exit_boundary.get("raw_reference", raw_reference), returned=True)
        else:
            boundary(instance, group, metadata, raw_reference)
            if isinstance(exit_boundary, dict):
                boundary(instance, group, exit_boundary,
                         exit_boundary.get("raw_reference", raw_reference), returned=True)
        legacy = metadata.get("legacy_effect", {})
        if not isinstance(legacy, dict) or not legacy.get("reads"):
            # A captured input with no legacy read projection still represents
            # a possible consumer. Its provisional version is local to this
            # observation, without joining any other snapshot's identity.
            for observation in input_observations[instance.id]:
                occurrence(instance, group, EffectDimension.READS,
                           EffectTarget(EffectTargetKind.VALUE_VERSION, observation.version.wire),
                           observation.metadata.get("raw_reference", raw_reference),
                           "captured-input:" + observation.observation_id,
                           assumptions=("captured input may be read; actual read and future consumers unproven",
                                        "capture-occurrence identity only; no cross-snapshot equivalence"))
                counts["may_read_occurrences"] += 1
        if raw_kind == "cuda_barrier" and clock == "kineto":
            occurrence(instance, group, EffectDimension.ORDERING,
                       EffectTarget(EffectTargetKind.ORDERING, f"runtime-barrier:{raw_reference}"),
                       raw_reference, "runtime-barrier", kind=EvidenceKind.OBSERVED,
                       assumptions=("observed runtime barrier; full happens-before dependency set unproven",))
        if raw_kind == "cuda_memcpy" and metadata.get("physical_copy") is True:
            for dimension, endpoint in ((EffectDimension.READS, "source"), (EffectDimension.WRITES, "destination")):
                occurrence(instance, group, dimension, opaque_target(raw_reference, dimension, endpoint),
                           raw_reference, "physical-copy:" + endpoint, kind=EvidenceKind.OBSERVED,
                           assumptions=("measured physical copy; exact logical endpoint unresolved",))
        if raw_kind in _ALLOCATION | _FREE:
            dimension = EffectDimension.ALLOCATES if raw_kind in _ALLOCATION else EffectDimension.FREES
            targets = allocation_targets[instance.id]
            target = (EffectTarget(EffectTargetKind.STORAGE, targets[0]) if len(targets) == 1
                      else opaque_target(raw_reference, dimension, "unresolved-allocation"))
            occurrence(instance, group, dimension, target, raw_reference, "memory-event",
                       kind=EvidenceKind.OBSERVED,
                       assumptions=("explicit memory event; cross-event allocation lifetime pairing unproven",))
        counts["instances"] += 1

    for instance in bundle.evidence.instances.values():
        if instance.parent is None:
            continue
        parent = bundle.evidence.instances[instance.parent]
        parent_scope, child_scope = instance_scopes[parent.id], instance_scopes[instance.id]
        parent_group = groups[(parent.definition, parent_scope)]
        if parent_scope == child_scope:
            parent_group["children"].add(instance.definition)
        else:
            parent_group["gaps"].add("child execution crosses an incomparable runtime observation scope")
    for (definition, scope), group in sorted(groups.items(), key=lambda item: (item[0][1], item[0][0].wire)):
        dimensions = {engine.occurrences[item].dimension for item in group["occurrences"]}
        claim = EvidenceClaim(EvidenceKind.INFERRED, tuple(sorted(group["references"])), scope=scope,
                              assumptions=("runtime evidence is partial and dynamic-path only",))
        coverage = tuple(EffectCoverage(
            scope, dimension, Completeness.PARTIAL if dimension in dimensions else Completeness.UNKNOWN,
            evidence=(claim,), assumptions=("no closed branch/call/alias target domain",))
            for dimension in EffectDimension)
        engine.add_operation_effects(OperationEffects(
            definition, scope, tuple(group["occurrences"]), coverage,
            tuple(sorted(group["children"], key=lambda item: item.wire)), group["inclusive"],
            tuple(sorted(group["gaps"]))))
    validation = engine.assert_valid()
    report = {"schema": "scar.runtime-effects.coverage", "schema_version": 1,
              "namespace": namespace, "counts": dict(sorted(counts.items())),
              "legacy_assertions": dict(sorted(assertions.items())),
              "validation": validation, "scope_mode": ScopeMode.DYNAMIC_PATH.value,
              "closed_scopes": 0, "completed_effect_contracts": 0,
              "cost_measurements_ingested": 0,
              "limitations": [
                  "Captured arguments are possible reads; v1 dispatch writes may be suffix heuristics.",
                  "Legacy tokens remain observation-local opaque targets, without logical equivalence joins.",
                  "Return escape sets cover exit captures only; callback and future consumers stay open.",
                  "Aggregates remain measurements; hook and child observations are not independent costs.",
                  "No source/runtime correspondence, pure contract, backend or transformation is inferred.",
              ]}
    return RuntimeEffectsResult(engine, report, instance_scopes)


__all__ = ["RuntimeEffectsResult", "ingest_runtime_effects"]
