"""Optimization IR: replaceable regions, alternatives and plan instructions.

This module is report-only.  It represents what a transformation would do and
why; it does not mutate source code or dispatch an optimization backend.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import math

from .common import ProofClaim, ProofStatus, SourceReference
from .contracts import EffectTarget, EffectTargetKind
from ._validation import mapping_errors, record_errors, cycle_errors
from .ids import (
    ContractID,
    ControlRegionID,
    EffectSummaryID,
    LogicalValueID,
    MaterializationID,
    MeasurementID,
    OperationDefinitionID,
    OperationInstanceID,
    OptimizationRegionID,
    PlanAlternativeID,
    PlanID,
    ProvenanceID,
    ResourceID,
    SourceAtomID,
    ValueVersionID,
    ValueSlotID,
)


class RegionGranularity(str, Enum):
    INSTRUCTION = "instruction"
    OPERATOR = "operator"
    FUNCTION = "function"
    REGION = "region"
    LOOP_BODY = "loop_body"
    DATAFLOW_SUBGRAPH = "dataflow_subgraph"
    PIPELINE_STAGE = "pipeline_stage"


class RegionPortKind(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    STATE = "state"
    CONTROL = "control"
    RESOURCE = "resource"
    ESCAPE = "escape"
    ORDERING = "ordering"
    EFFECT = "effect"


@dataclass(frozen=True, slots=True)
class ValuePattern:
    versions: tuple[ValueVersionID, ...] = ()
    provenance: tuple[ProvenanceID, ...] = ()
    materializations: tuple[MaterializationID, ...] = ()
    semantic_type: str | None = None
    constraints: tuple[tuple[str, str], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "versions": [item.as_dict() for item in sorted(
                self.versions, key=lambda item: item.wire)],
            "provenance": [item.as_dict() for item in sorted(
                self.provenance, key=lambda item: item.wire)],
            "materializations": [item.as_dict() for item in sorted(
                self.materializations, key=lambda item: item.wire)],
            "semantic_type": self.semantic_type,
            "constraints": [{"name": name, "value": value}
                            for name, value in sorted(self.constraints)],
        }


@dataclass(frozen=True, slots=True)
class RegionPort:
    port_id: str
    kind: RegionPortKind
    name: str
    value: ValuePattern | None = None
    control: ControlRegionID | None = None
    resource: ResourceID | None = None
    required: bool = True
    slot: ValueSlotID | None = None
    effect: EffectTarget | None = None
    operation: OperationDefinitionID | OperationInstanceID | None = None

    def __post_init__(self) -> None:
        if not self.port_id or not self.name:
            raise ValueError("region port ID and name are required")
        payloads = {"value": self.value, "control": self.control, "resource": self.resource,
                    "slot": self.slot, "effect": self.effect, "operation": self.operation}
        populated = sum(item is not None for item in payloads.values())
        if populated != 1:
            raise ValueError("region port must reference exactly one value, slot, effect, control, resource or operation")
        allowed = {
            RegionPortKind.INPUT: {"value", "slot"},
            RegionPortKind.OUTPUT: {"value", "slot"},
            RegionPortKind.STATE: {"value", "slot", "effect"},
            RegionPortKind.ESCAPE: {"value", "slot", "effect"},
            RegionPortKind.CONTROL: {"control", "operation"},
            RegionPortKind.RESOURCE: {"resource"},
            RegionPortKind.ORDERING: {"control", "resource", "effect", "operation"},
            RegionPortKind.EFFECT: {"effect"},
        }
        if not isinstance(self.kind, RegionPortKind):
            raise ValueError("region port kind must be typed")
        actual = next(name for name, value in payloads.items() if value is not None)
        if actual not in allowed[self.kind]:
            raise ValueError(f"{self.kind.value} port does not permit {actual} payload")

    def as_dict(self) -> dict[str, Any]:
        return {
            "port_id": self.port_id, "kind": self.kind.value, "name": self.name,
            "value": self.value.as_dict() if self.value else None,
            "control": self.control.as_dict() if self.control else None,
            "resource": self.resource.as_dict() if self.resource else None,
            "required": self.required,
            "slot": self.slot.as_dict() if self.slot else None,
            "effect": self.effect.as_dict() if self.effect else None,
            "operation": self.operation.as_dict() if self.operation else None,
        }


@dataclass(slots=True)
class OptimizationRegion:
    id: OptimizationRegionID
    granularity: RegionGranularity
    label: str
    definitions: tuple[OperationDefinitionID, ...] = ()
    instances: tuple[OperationInstanceID, ...] = ()
    parent: OptimizationRegionID | None = None
    ports: tuple[str, ...] = ()
    effect_summary: EffectSummaryID | None = None
    contract: ContractID | None = None
    source_atoms: tuple[SourceAtomID, ...] = ()
    measurements: tuple[MeasurementID, ...] = ()

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("optimization region label is required")
        if not self.definitions and not self.instances:
            raise ValueError("optimization region needs a semantic or execution member")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.as_dict(), "granularity": self.granularity.value,
            "label": self.label,
            "definitions": [item.as_dict() for item in sorted(
                self.definitions, key=lambda item: item.wire)],
            "instances": [item.as_dict() for item in sorted(
                self.instances, key=lambda item: item.wire)],
            "parent": self.parent.as_dict() if self.parent else None,
            "ports": sorted(self.ports),
            "effect_summary": self.effect_summary.as_dict()
            if self.effect_summary else None,
            "contract": self.contract.as_dict() if self.contract else None,
            "source_atoms": [item.as_dict() for item in sorted(
                self.source_atoms, key=lambda item: item.wire)],
            "measurements": [item.as_dict() for item in sorted(
                self.measurements, key=lambda item: item.wire)],
        }


class TransformKind(str, Enum):
    NO_OP = "no_op"
    SUBSTITUTE = "substitute"
    DELETE = "delete"
    MOVE = "move"
    FUSE = "fuse"
    REUSE = "reuse"
    RESIDENCY = "residency"
    DEFER = "defer"
    BUFFER_REUSE = "buffer_reuse"
    PREFETCH = "prefetch"
    CAPTURE = "capture"


@dataclass(frozen=True, slots=True)
class LiteralValue:
    """Explicit wrapper so the Python value ``None`` is a valid literal."""

    value: Any

    def __post_init__(self) -> None:
        # This schema revision supports JSON literals only. Reject values whose
        # Python type would be silently changed by JSON (tuple, bytes, int keys).
        def check(value):
            if value is None or type(value) in (str, bool, int):
                return
            if type(value) is float and math.isfinite(value):
                return
            if type(value) is list:
                for child in value:
                    check(child)
                return
            if type(value) is dict and all(type(key) is str for key in value):
                for child in value.values():
                    check(child)
                return
            raise ValueError("literal must be a finite JSON value with string dictionary keys")
        check(self.value)

    def as_dict(self) -> dict[str, Any]:
        return {"value": self.value}


@dataclass(frozen=True, slots=True)
class ValueSubstitution:
    original: ValueVersionID
    replacement_version: ValueVersionID | None = None
    literal: LiteralValue | None = None
    equivalence: str = "exact"

    def __post_init__(self) -> None:
        if self.replacement_version is None and self.literal is None:
            raise ValueError("value substitution requires a version or literal")
        if self.replacement_version is not None and self.literal is not None:
            raise ValueError("value substitution cannot use both version and literal")

    def as_dict(self) -> dict[str, Any]:
        return {
            "original": self.original.as_dict(),
            "replacement_version": self.replacement_version.as_dict()
            if self.replacement_version else None,
            "literal": self.literal.as_dict() if self.literal else None,
            "equivalence": self.equivalence,
        }


@dataclass(frozen=True, slots=True)
class RegionMove:
    region: OptimizationRegionID
    from_control: ControlRegionID
    to_control: ControlRegionID

    def as_dict(self) -> dict[str, Any]:
        return {"region": self.region.as_dict(),
                "from_control": self.from_control.as_dict(),
                "to_control": self.to_control.as_dict()}


@dataclass(frozen=True, slots=True)
class TransformDelta:
    removed_definitions: tuple[OperationDefinitionID, ...] = ()
    removed_instances: tuple[OperationInstanceID, ...] = ()
    substitutions: tuple[ValueSubstitution, ...] = ()
    moves: tuple[RegionMove, ...] = ()
    added_operations: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not any((self.removed_definitions, self.removed_instances,
                        self.substitutions, self.moves, self.added_operations))

    def as_dict(self) -> dict[str, Any]:
        return {
            "removed_definitions": [item.as_dict() for item in sorted(
                self.removed_definitions, key=lambda item: item.wire)],
            "removed_instances": [item.as_dict() for item in sorted(
                self.removed_instances, key=lambda item: item.wire)],
            "substitutions": [item.as_dict() for item in self.substitutions],
            "moves": [item.as_dict() for item in self.moves],
            "added_operations": sorted(self.added_operations),
        }


@dataclass(frozen=True, slots=True)
class ResidualEffect:
    effect: EffectSummaryID
    reason: str
    placement: str

    def as_dict(self) -> dict[str, Any]:
        return {"effect": self.effect.as_dict(), "reason": self.reason,
                "placement": self.placement}


@dataclass(frozen=True, slots=True)
class GuardSpec:
    guard_id: str
    expression: str
    inputs: tuple[str, ...] = ()
    estimated_cost_ns: int | None = None

    def __post_init__(self) -> None:
        if not self.guard_id or not self.expression:
            raise ValueError("guard ID and expression are required")
        if self.estimated_cost_ns is not None and self.estimated_cost_ns < 0:
            raise ValueError("guard cost cannot be negative")

    def as_dict(self) -> dict[str, Any]:
        return {"guard_id": self.guard_id, "expression": self.expression,
                "inputs": sorted(self.inputs),
                "estimated_cost_ns": self.estimated_cost_ns}


@dataclass(frozen=True, slots=True)
class InvalidationSpec:
    invalidation_id: str
    trigger: str
    affected: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.invalidation_id or not self.trigger:
            raise ValueError("invalidation ID and trigger are required")

    def as_dict(self) -> dict[str, Any]:
        return {"invalidation_id": self.invalidation_id, "trigger": self.trigger,
                "affected": sorted(self.affected)}


class MeasurementMode(str, Enum):
    CLEAN = "clean"
    INSTRUMENTED = "instrumented"


@dataclass(frozen=True, slots=True)
class CostRequest:
    scope: OptimizationRegionID
    metrics: tuple[str, ...]
    mode: MeasurementMode
    warmup: int = 0
    repetitions: int = 1

    def __post_init__(self) -> None:
        if not self.metrics:
            raise ValueError("cost request needs at least one metric")
        if self.warmup < 0 or self.repetitions < 1:
            raise ValueError("invalid warmup or repetition count")

    def as_dict(self) -> dict[str, Any]:
        return {"scope": self.scope.as_dict(), "metrics": sorted(self.metrics),
                "mode": self.mode.value, "warmup": self.warmup,
                "repetitions": self.repetitions}


@dataclass(frozen=True, slots=True)
class ValidationRequest:
    contract: ContractID
    levels: tuple[int, ...]
    snapshots: tuple[str, ...]
    clean_benchmark: bool = True

    def __post_init__(self) -> None:
        if not self.levels or any(level not in (1, 2, 3, 4) for level in self.levels):
            raise ValueError("validation levels must be a non-empty subset of 1..4")

    def as_dict(self) -> dict[str, Any]:
        return {"contract": self.contract.as_dict(),
                "levels": sorted(set(self.levels)),
                "snapshots": sorted(self.snapshots),
                "clean_benchmark": self.clean_benchmark}


class InstructionKind(str, Enum):
    REPLACE_VALUE_PATH = "replace_value_path"
    DELETE_SOURCE = "delete_source"
    MOVE_REGION = "move_region"
    PRESERVE_EFFECT = "preserve_effect"
    RETAIN_MATERIALIZATION = "retain_materialization"
    DEFER_MATERIALIZATION = "defer_materialization"
    INSERT_GUARD = "insert_guard"
    KEEP_ORIGINAL = "keep_original"


@dataclass(frozen=True, slots=True)
class PlanInstruction:
    instruction_id: str
    kind: InstructionKind
    target: str
    source: SourceReference | None = None
    replacement: Any = None
    rationale: str = ""
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.instruction_id or not self.target:
            raise ValueError("plan instruction ID and target are required")

    def as_dict(self) -> dict[str, Any]:
        return {
            "instruction_id": self.instruction_id, "kind": self.kind.value,
            "target": self.target,
            "source": self.source.as_dict() if self.source else None,
            "replacement": self.replacement, "rationale": self.rationale,
            "depends_on": sorted(self.depends_on),
        }


@dataclass(slots=True)
class PlanAlternative:
    id: PlanAlternativeID
    region: OptimizationRegionID
    label: str
    transform: TransformKind
    delta: TransformDelta = field(default_factory=TransformDelta)
    original: bool = False
    proofs: tuple[ProofClaim, ...] = ()
    guards: tuple[GuardSpec, ...] = ()
    invalidations: tuple[InvalidationSpec, ...] = ()
    residual_effects: tuple[ResidualEffect, ...] = ()
    cost_request: CostRequest | None = None
    validation_request: ValidationRequest | None = None
    instructions: tuple[PlanInstruction, ...] = ()
    fallback: PlanAlternativeID | None = None

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("plan alternative label is required")
        if self.original:
            if self.transform is not TransformKind.NO_OP or not self.delta.is_empty:
                raise ValueError("original alternative must be an empty NO_OP")
            if self.fallback is not None:
                raise ValueError("original alternative cannot have a fallback")
        elif self.transform is TransformKind.NO_OP:
            raise ValueError("only the original alternative may be NO_OP")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.as_dict(), "region": self.region.as_dict(),
            "label": self.label, "transform": self.transform.value,
            "delta": self.delta.as_dict(), "original": self.original,
            "proofs": [item.as_dict() for item in sorted(
                self.proofs, key=lambda item: item.obligation)],
            "guards": [item.as_dict() for item in sorted(
                self.guards, key=lambda item: item.guard_id)],
            "invalidations": [item.as_dict() for item in sorted(
                self.invalidations, key=lambda item: item.invalidation_id)],
            "residual_effects": [item.as_dict() for item in self.residual_effects],
            "cost_request": self.cost_request.as_dict() if self.cost_request else None,
            "validation_request": self.validation_request.as_dict()
            if self.validation_request else None,
            "instructions": [item.as_dict() for item in self.instructions],
            "fallback": self.fallback.as_dict() if self.fallback else None,
        }


class PlanDisposition(str, Enum):
    REWRITE = "REWRITE"
    KEEP = "KEEP"
    INSTRUMENT = "INSTRUMENT"
    CONTRACT = "CONTRACT"


@dataclass(slots=True)
class PlanSelection:
    id: PlanID
    region: OptimizationRegionID
    disposition: PlanDisposition
    selected: PlanAlternativeID | None = None
    reason: str = ""
    requests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.disposition is PlanDisposition.REWRITE and self.selected is None:
            raise ValueError("REWRITE plan requires a selected alternative")
        if self.disposition in {PlanDisposition.INSTRUMENT, PlanDisposition.CONTRACT}:
            if not self.requests:
                raise ValueError(f"{self.disposition.value} plan requires concrete requests")
        if not self.reason:
            raise ValueError("plan selection reason is required")

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id.as_dict(), "region": self.region.as_dict(),
                "disposition": self.disposition.value,
                "selected": self.selected.as_dict() if self.selected else None,
                "reason": self.reason, "requests": sorted(self.requests)}


@dataclass(frozen=True, slots=True)
class OptimizationContext:
    definitions: frozenset[OperationDefinitionID] = frozenset()
    instances: frozenset[OperationInstanceID] = frozenset()
    value_versions: frozenset[ValueVersionID] = frozenset()
    provenance: frozenset[ProvenanceID] = frozenset()
    materializations: frozenset[MaterializationID] = frozenset()
    controls: frozenset[ControlRegionID] = frozenset()
    resources: frozenset[ResourceID] = frozenset()
    effects: frozenset[EffectSummaryID] = frozenset()
    contracts: frozenset[ContractID] = frozenset()
    source_atoms: frozenset[SourceAtomID] = frozenset()
    measurements: frozenset[MeasurementID] = frozenset()
    value_slots: frozenset[ValueSlotID] = frozenset()


class OptimizationGraph:
    """Validated report-only replacement regions and alternatives."""

    SCHEMA = "scar.ir.v2.optimization"
    SCHEMA_VERSION = 2

    def __init__(self, context: OptimizationContext) -> None:
        self.context = context
        self.ports: dict[str, RegionPort] = {}
        self.regions: dict[OptimizationRegionID, OptimizationRegion] = {}
        self.alternatives: dict[PlanAlternativeID, PlanAlternative] = {}
        self.plans: dict[PlanID, PlanSelection] = {}

    def add_port(self, port: RegionPort) -> None:
        if port.port_id in self.ports:
            raise ValueError(f"duplicate region port: {port.port_id}")
        self.ports[port.port_id] = port

    def add_region(self, region: OptimizationRegion) -> None:
        if region.id in self.regions:
            raise ValueError(f"duplicate optimization region: {region.id.wire}")
        if region.parent is not None and region.parent not in self.regions:
            raise ValueError(f"unknown parent optimization region: {region.parent.wire}")
        errors = self._region_errors(region)
        if errors:
            raise ValueError("; ".join(errors))
        self.regions[region.id] = region

    def add_alternative(self, alternative: PlanAlternative) -> None:
        if alternative.id in self.alternatives:
            raise ValueError(f"duplicate plan alternative: {alternative.id.wire}")
        if alternative.region not in self.regions:
            raise ValueError(f"unknown alternative region: {alternative.region.wire}")
        if alternative.fallback is not None:
            fallback = self.alternatives.get(alternative.fallback)
            if fallback is None:
                raise ValueError(f"unknown fallback alternative: {alternative.fallback.wire}")
            if fallback.region != alternative.region or not fallback.original:
                raise ValueError("fallback must be the original alternative for the same region")
        if alternative.cost_request and alternative.cost_request.scope != alternative.region:
            raise ValueError("cost request scope must match alternative region")
        self._validate_alternative_context(alternative)
        self.alternatives[alternative.id] = alternative

    def add_plan(self, plan: PlanSelection) -> None:
        if plan.id in self.plans:
            raise ValueError(f"duplicate plan: {plan.id.wire}")
        if plan.region not in self.regions:
            raise ValueError(f"unknown plan region: {plan.region.wire}")
        if plan.selected is not None:
            alternative = self.alternatives.get(plan.selected)
            if alternative is None or alternative.region != plan.region:
                raise ValueError("selected alternative must exist for the same region")
            if plan.disposition is PlanDisposition.REWRITE:
                if alternative.original:
                    raise ValueError("REWRITE cannot select the original alternative")
                if not alternative.proofs:
                    raise ValueError("REWRITE alternative has no proof obligations")
                if any(proof.status is not ProofStatus.PROVEN
                       for proof in alternative.proofs):
                    raise ValueError("REWRITE alternative has an unproven obligation")
                if not alternative.instructions:
                    raise ValueError("REWRITE alternative has no modification instructions")
                if alternative.validation_request is None:
                    raise ValueError("REWRITE alternative has no validation request")
        self.plans[plan.id] = plan

    def _region_errors(self, region: OptimizationRegion, *, check_ports=True) -> list[str]:
        errors: list[str] = []
        for definition in region.definitions:
            if definition not in self.context.definitions:
                errors.append(f"region references unknown definition {definition.wire}")
        for instance in region.instances:
            if instance not in self.context.instances:
                errors.append(f"region references unknown instance {instance.wire}")
        for port in region.ports:
            if port not in self.ports:
                errors.append(f"region references unknown port {port}")
        if region.effect_summary is not None and region.effect_summary not in self.context.effects:
            errors.append(f"region references unknown effect {region.effect_summary.wire}")
        if region.contract is not None and region.contract not in self.context.contracts:
            errors.append(f"region references unknown contract {region.contract.wire}")
        for atom in region.source_atoms:
            if atom not in self.context.source_atoms:
                errors.append(f"region references unknown source atom {atom.wire}")
        for measurement in region.measurements:
            if measurement not in self.context.measurements:
                errors.append(f"region references unknown measurement {measurement.wire}")
        for port_id in region.ports:
            port = self.ports.get(port_id)
            if port is not None and check_ports:
                errors.extend(self._port_errors(port))
        return errors

    def _port_errors(self, port: RegionPort) -> list[str]:
        errors = []
        prefix = f"port {port.port_id} references unknown"
        if port.control is not None and port.control not in self.context.controls:
            errors.append(f"{prefix} control {port.control.wire}")
        if port.resource is not None and port.resource not in self.context.resources:
            errors.append(f"{prefix} resource {port.resource.wire}")
        if port.slot is not None and port.slot not in self.context.value_slots:
            errors.append(f"{prefix} slot {port.slot.wire}")
        if port.operation is not None:
            registry = (self.context.definitions if isinstance(port.operation, OperationDefinitionID)
                        else self.context.instances)
            if port.operation not in registry:
                errors.append(f"{prefix} operation {port.operation.wire}")
        if port.value:
            for version in port.value.versions:
                if version not in self.context.value_versions:
                    errors.append(f"{prefix} version {version.wire}")
            for provenance in port.value.provenance:
                if provenance not in self.context.provenance:
                    errors.append(f"{prefix} provenance {provenance.wire}")
            for materialization in port.value.materializations:
                if materialization not in self.context.materializations:
                    errors.append(f"{prefix} materialization {materialization.wire}")
        if port.effect:
            target = port.effect
            if target.kind is EffectTargetKind.VALUE_SLOT:
                if (not target.reference.startswith("slot:") or not target.reference[5:]
                        or ValueSlotID(target.reference[5:]) not in self.context.value_slots):
                    errors.append(f"{prefix} effect value slot {target.reference}")
            elif target.kind is EffectTargetKind.VALUE_VERSION:
                try:
                    logical, number = target.reference[3:].rsplit("@v", 1)
                    version = ValueVersionID(LogicalValueID(logical), int(number))
                except (ValueError, TypeError):
                    version = None
                if version is None or version.wire != target.reference or version not in self.context.value_versions:
                    errors.append(f"{prefix} effect value version {target.reference}")
            # Other targets identify domains (file, environment, object, ...).
            # Their occurrence/scope binding is validated by RegionConstruction,
            # not invented as another reference registry inside this bundle.
        return errors

    def _validate_alternative_context(self, alternative: PlanAlternative) -> None:
        delta = alternative.delta
        region = self.regions.get(alternative.region)
        if region is None:
            raise ValueError("alternative references unknown region")
        # Region members are explicit, including members of any contained
        # region which the builder intends to replace as part of this boundary.
        if set(delta.removed_definitions) - set(region.definitions):
            raise ValueError("delta deletes definitions outside target region boundary")
        if set(delta.removed_instances) - set(region.instances):
            raise ValueError("delta deletes instances outside target region boundary")
        if alternative.cost_request and alternative.cost_request.scope != region.id:
            raise ValueError("cost request scope must match alternative region")
        if (alternative.validation_request and region.contract
                and alternative.validation_request.contract != region.contract):
            raise ValueError("validation contract must match region contract")
        for definition in delta.removed_definitions:
            if definition not in self.context.definitions:
                raise ValueError(f"delta references unknown definition {definition.wire}")
        for instance in delta.removed_instances:
            if instance not in self.context.instances:
                raise ValueError(f"delta references unknown instance {instance.wire}")
        for substitution in delta.substitutions:
            if substitution.original not in self.context.value_versions:
                raise ValueError(f"substitution references unknown version {substitution.original.wire}")
            if (substitution.replacement_version is not None
                    and substitution.replacement_version not in self.context.value_versions):
                raise ValueError("substitution replacement version is unknown")
        for move in delta.moves:
            if move.region not in self.regions:
                raise ValueError(f"move references unknown region {move.region.wire}")
            if (move.from_control not in self.context.controls
                    or move.to_control not in self.context.controls):
                raise ValueError("move references unknown control region")
            if move.region != region.id:
                raise ValueError("move must target the alternative region")
        for residual in alternative.residual_effects:
            if residual.effect not in self.context.effects:
                raise ValueError(f"residual references unknown effect {residual.effect.wire}")
        if (alternative.validation_request is not None
                and alternative.validation_request.contract not in self.context.contracts):
            raise ValueError("validation request references unknown contract")

    def validate(self) -> dict[str, Any]:
        errors = record_errors(self.context, OptimizationContext, "optimization.context")
        errors += mapping_errors(self.ports, str, RegionPort, "optimization.ports", "port_id")
        errors += mapping_errors(self.regions, OptimizationRegionID, OptimizationRegion,
                                 "optimization.regions")
        errors += mapping_errors(self.alternatives, PlanAlternativeID, PlanAlternative,
                                 "optimization.alternatives")
        errors += mapping_errors(self.plans, PlanID, PlanSelection, "optimization.plans")
        if errors:
            return {"schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION,
                    "valid": False, "errors": errors, "counts": {}}
        for port in self.ports.values():
            errors.extend(self._port_errors(port))
        original_counts = {}
        for alternative in self.alternatives.values():
            if alternative.original:
                original_counts[alternative.region] = original_counts.get(alternative.region, 0) + 1
        for region in self.regions.values():
            errors.extend(self._region_errors(region, check_ports=False))
            if original_counts.get(region.id, 0) != 1:
                errors.append(f"region {region.id.wire} requires exactly one original alternative")
            if region.parent is not None and region.parent not in self.regions:
                errors.append(f"region {region.id.wire} has unknown parent")
        for alternative in self.alternatives.values():
            try:
                alternative.__post_init__()
            except (ValueError, TypeError) as exc:
                errors.append(f"alternative {alternative.id.wire}: {exc}")
            if alternative.region not in self.regions:
                errors.append(f"alternative {alternative.id.wire} has unknown region")
            if (not alternative.original and alternative.fallback is None):
                errors.append(f"alternative {alternative.id.wire} has no fallback")
            if alternative.fallback is not None:
                fallback = self.alternatives.get(alternative.fallback)
                if fallback is None:
                    errors.append(f"alternative {alternative.id.wire} has unknown fallback")
                elif fallback.region != alternative.region or not fallback.original:
                    errors.append(f"alternative {alternative.id.wire} fallback is not original")
            try:
                self._validate_alternative_context(alternative)
            except ValueError as exc:
                errors.append(f"alternative {alternative.id.wire}: {exc}")
            instruction_ids = {item.instruction_id for item in alternative.instructions}
            if len(instruction_ids) != len(alternative.instructions):
                errors.append(f"alternative {alternative.id.wire} has duplicate instruction IDs")
            for instruction in alternative.instructions:
                missing = set(instruction.depends_on) - instruction_ids
                if missing:
                    errors.append(
                        f"instruction {instruction.instruction_id} has unknown dependencies")
            dependency_map = {item.instruction_id: set(item.depends_on)
                              for item in alternative.instructions}
            # Dependency cycles are invalid even when all referenced IDs exist.
            pending = dict(dependency_map)
            while pending:
                ready = {key for key, deps in pending.items() if not (deps & pending.keys())}
                if not ready:
                    errors.append(f"alternative {alternative.id.wire} has cyclic instruction dependencies")
                    break
                for key in ready:
                    del pending[key]
        for plan in self.plans.values():
            try:
                plan.__post_init__()
            except (ValueError, TypeError) as exc:
                errors.append(f"plan {plan.id.wire}: {exc}")
            if plan.region not in self.regions:
                errors.append(f"plan {plan.id.wire} has unknown region")
            if plan.selected is not None and plan.selected not in self.alternatives:
                errors.append(f"plan {plan.id.wire} has unknown selected alternative")
            if plan.selected in self.alternatives:
                chosen = self.alternatives[plan.selected]
                if chosen.region != plan.region:
                    errors.append(f"plan {plan.id.wire} selected alternative belongs to another region")
                if plan.disposition is PlanDisposition.KEEP and not chosen.original:
                    errors.append(f"plan {plan.id.wire} KEEP must select original")
            if plan.disposition is PlanDisposition.REWRITE and plan.selected in self.alternatives:
                selected = self.alternatives[plan.selected]
                if (selected.original or not selected.proofs
                        or any(item.status is not ProofStatus.PROVEN
                               for item in selected.proofs)
                        or not selected.instructions
                        or selected.validation_request is None):
                    errors.append(f"plan {plan.id.wire} selects an incomplete rewrite")

        errors += cycle_errors(((item.id, item.parent) for item in self.regions.values()
                                if item.parent is not None), "optimization-region ancestry")
        return {
            "schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION,
            "valid": not errors, "errors": errors,
            "counts": {"ports": len(self.ports), "regions": len(self.regions),
                       "alternatives": len(self.alternatives), "plans": len(self.plans)},
        }

    def assert_valid(self) -> dict[str, Any]:
        report = self.validate()
        if not report["valid"]:
            raise ValueError("invalid v2 OptimizationGraph: " + "; ".join(report["errors"]))
        return report

    def to_dict(self) -> dict[str, Any]:
        self.assert_valid()
        return {
            "schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION,
            "ports": [self.ports[key].as_dict() for key in sorted(self.ports)],
            "regions": [self.regions[key].as_dict() for key in sorted(
                self.regions, key=lambda item: item.wire)],
            "alternatives": [self.alternatives[key].as_dict() for key in sorted(
                self.alternatives, key=lambda item: item.wire)],
            "plans": [self.plans[key].as_dict() for key in sorted(
                self.plans, key=lambda item: item.wire)],
            "validation": self.validate(),
        }


__all__ = [
    "CostRequest", "GuardSpec", "InstructionKind", "InvalidationSpec",
    "LiteralValue", "MeasurementMode", "OptimizationContext", "OptimizationGraph",
    "OptimizationRegion", "PlanAlternative", "PlanDisposition",
    "PlanInstruction", "PlanSelection", "RegionGranularity", "RegionMove",
    "RegionPort", "RegionPortKind", "ResidualEffect", "TransformDelta",
    "TransformKind", "ValidationRequest", "ValuePattern", "ValueSubstitution",
]
