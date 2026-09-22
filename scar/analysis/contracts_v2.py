"""Scoped effect contracts and concrete requests; no transformation selection."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json

from scar.ir.record_codec import decode, encode, loads
from scar.ir.ids import CodeID
from scar.ir.v2 import (
    EffectPresence, EffectTargetKind, EvidenceClaim, EvidenceKind, OperationDefinitionID,
    SemanticGraph, SourceReference,
)
from scar.ir.v2._validation import record_errors
from .effects_v2 import BoundarySummary, EffectDimension, EffectGap, ScopeMode


class PolicyAction(str, Enum):
    PRESERVE = "preserve"
    IGNORE = "ignore"


class Disposition(str, Enum):
    KEEP = "KEEP"
    INSTRUMENT = "INSTRUMENT"
    CONTRACT = "CONTRACT"


@dataclass(frozen=True)
class EffectPolicyRule:
    dimension: EffectDimension
    target_kind: EffectTargetKind
    reference: str
    action: PolicyAction

    def __post_init__(self):
        if not self.reference:
            raise ValueError("policy target requires a reference or explicit '*'")


@dataclass(frozen=True)
class EffectPolicy:
    id: str
    scope: str
    rules: tuple[EffectPolicyRule, ...]
    evidence: EvidenceClaim

    def __post_init__(self):
        if not self.id or not self.scope:
            raise ValueError("policy requires identity and scope")
        if self.evidence.kind in (EvidenceKind.UNKNOWN, EvidenceKind.PROPOSED) or not self.evidence.references:
            raise ValueError("policy requires a declared or verified source")
        if self.evidence.scope != self.scope:
            raise ValueError("policy evidence scope must match policy scope")
        selectors = [(rule.dimension, rule.target_kind, rule.reference) for rule in self.rules]
        if len(selectors) != len(set(selectors)):
            raise ValueError("duplicate/conflicting policy selector")

    def action_for(self, occurrence):
        matches = [rule for rule in self.rules if rule.dimension is occurrence.dimension
                   and rule.target_kind is occurrence.target.kind
                   and rule.reference in ("*", occurrence.target.reference)]
        exact = [rule for rule in matches if rule.reference == occurrence.target.reference]
        return (exact or matches)[0].action if matches else PolicyAction.PRESERVE

    def to_dict(self):
        return {"schema": "scar.effect.policy", "schema_version": 1, "policy": encode(self)}

    @classmethod
    def from_dict(cls, document):
        if (type(document) is not dict or set(document) != {"schema", "schema_version", "policy"}
                or document["schema"] != "scar.effect.policy"
                or type(document["schema_version"]) is not int or document["schema_version"] != 1):
            raise ValueError("unsupported effect policy document")
        return decode(cls, document["policy"])


@dataclass(frozen=True)
class RunManifest:
    argv: tuple[str, ...]
    cwd: str
    environment_identity: str

    def __post_init__(self):
        if not self.argv or any(not arg for arg in self.argv) or not self.cwd or not self.environment_identity:
            raise ValueError("rerun requires argv, cwd and environment identity")


@dataclass(frozen=True)
class CollectorCapability:
    name: str
    mode: ScopeMode
    dimensions: tuple[EffectDimension, ...]
    fields: tuple[str, ...]
    command_prefix: tuple[str, ...]
    reference: str

    def __post_init__(self):
        if (not self.name or not self.fields or not self.command_prefix or not self.reference
                or any(type(item) is not str or not item for item in self.command_prefix + self.fields)):
            raise ValueError("collector capability needs fields, actual command and implementation reference")


@dataclass(frozen=True)
class LocationHint:
    definition: OperationDefinitionID
    path: str | None
    first_line: int | None
    loaded_code_id: str | None
    extent: str = "location hint only; source/code correspondence unproven"


@dataclass(frozen=True)
class EvidenceRequest:
    id: str
    disposition: Disposition
    scope: str
    definitions: tuple[OperationDefinitionID, ...]
    sources: tuple[SourceReference, ...]
    location_hints: tuple[LocationHint, ...]
    dimension: EffectDimension | None
    missing_fact: str
    collector: str | None
    required_fields: tuple[str, ...]
    rerun_argv: tuple[str, ...] | None
    rerun_cwd: str | None
    environment_identity: str | None
    completion: str
    invalidation: tuple[str, ...]
    fallback: str = "keep original execution"

    def __post_init__(self):
        if not self.id or not self.scope or not self.missing_fact or not self.completion:
            raise ValueError("request needs identity, scope, missing fact and completion criterion")
        if self.disposition is Disposition.INSTRUMENT and (
            not self.collector or not self.required_fields or not self.rerun_argv
            or not self.rerun_cwd or not self.environment_identity
        ):
            raise ValueError("INSTRUMENT requires executable collector/run fields")


@dataclass(frozen=True)
class ContractAssessment:
    scope: str
    policy_id: str
    disposition: Disposition
    removal_effects_satisfied: bool
    ready_for_region_construction: bool
    required_effects: tuple[str, ...]
    ignored_effects: tuple[str, ...]
    requests: tuple[EvidenceRequest, ...]
    reasons: tuple[str, ...]

    def __post_init__(self):
        if not self.scope or not self.policy_id or not self.reasons:
            raise ValueError("assessment requires scope, policy and reasons")
        if self.removal_effects_satisfied and (not self.ready_for_region_construction
                                             or self.required_effects or self.requests):
            raise ValueError("satisfied removal requires ready closure and no required effects or requests")
        if self.ready_for_region_construction and self.requests:
            raise ValueError("ready region cannot retain unresolved evidence requests")
        if set(self.required_effects) & set(self.ignored_effects):
            raise ValueError("an effect cannot be both required and ignored")
        if self.required_effects and self.disposition is not Disposition.KEEP:
            raise ValueError("required effects force KEEP")
        if self.disposition is Disposition.INSTRUMENT and (
            not self.requests or any(item.disposition is not Disposition.INSTRUMENT for item in self.requests)
        ):
            raise ValueError("INSTRUMENT requires supported evidence requests")

    def to_dict(self):
        return {"schema": "scar.effect.assessment", "schema_version": 1, "assessment": encode(self)}

    @classmethod
    def from_dict(cls, document):
        if (type(document) is not dict or set(document) != {"schema", "schema_version", "assessment"}
                or document["schema"] != "scar.effect.assessment"
                or type(document["schema_version"]) is not int or document["schema_version"] != 1):
            raise ValueError("unsupported assessment document")
        return decode(cls, document["assessment"])

    @classmethod
    def from_json(cls, payload):
        return cls.from_dict(loads(payload))


def _locations(semantic, definitions):
    sources = {}
    for identity in definitions:
        if identity not in semantic.definitions:
            raise ValueError(f"unknown source definition: {identity.wire}")
        for atom in semantic.definitions[identity].source_atoms:
            sources[atom] = semantic.source_atoms[atom].reference
    return tuple(sources[key] for key in sorted(sources, key=lambda item: item.wire))


def _location_hints(semantic, definitions):
    result = []
    for identity in definitions:
        definition = semantic.definitions[identity]
        code = CodeID.parse_key(definition.code_id or "")
        result.append(LocationHint(identity, code.source if code else definition.source_file,
                                   code.line if code else definition.source_start,
                                   definition.code_id))
    return tuple(result)


def evaluate_removal(boundary: BoundarySummary, policy: EffectPolicy, semantic: SemanticGraph,
                     *, removed_effect_ids=None, mode=None,
                     run_manifest: RunManifest | None = None,
                     collectors: tuple[CollectorCapability, ...] = ()) -> ContractAssessment:
    """Assess only effect removal. Outputs/control/autograd/cost are later gates.

    Default policy preserves every unlisted effect target. Input reads remain
    dependencies, not permission to erase their dataflow. A successful effect
    check keeps execution unchanged and enables subsequent region construction.
    """
    for value, expected in ((boundary, BoundarySummary), (policy, EffectPolicy)):
        errors = record_errors(value, expected, expected.__name__)
        if errors:
            raise ValueError("; ".join(errors))
    for value, expected in ((run_manifest, RunManifest), *((item, CollectorCapability) for item in collectors)):
        if value is not None:
            errors = record_errors(value, expected, expected.__name__)
            if errors:
                raise ValueError("; ".join(errors))
    if policy.scope != boundary.scope:
        raise ValueError("policy and boundary scopes differ")
    if (not boundary.members or len(set(boundary.members)) != len(boundary.members)
            or any(identity not in semantic.definitions for identity in boundary.members)):
        raise ValueError("boundary requires nonempty, unique, known semantic members")
    mode = boundary.mode if mode is None else mode
    if not isinstance(mode, ScopeMode):
        raise ValueError("requested scope mode must be typed")
    available = {item.id: item for item in boundary.occurrences}
    if len(available) != len(boundary.occurrences):
        raise ValueError("duplicate occurrence identity in boundary")
    if any(item.scope != boundary.scope or item.definition not in boundary.members
           for item in boundary.occurrences):
        raise ValueError("occurrence outside region members or scope")
    removed = set(available) if removed_effect_ids is None else set(removed_effect_ids)
    if not removed <= set(available):
        raise ValueError("removal references unknown effect occurrence")
    required, ignored = [], []
    for identity in sorted(removed):
        occurrence = available[identity]
        if occurrence.dimension is EffectDimension.READS:
            continue
        (ignored if policy.action_for(occurrence) is PolicyAction.IGNORE else required).append(identity)
    coverages = {item.dimension: item for item in boundary.coverage}
    if len(coverages) != len(boundary.coverage) or any(item.scope != boundary.scope for item in boundary.coverage):
        raise ValueError("boundary coverage dimensions/scopes are inconsistent")
    gaps = list(boundary.gaps)
    for dimension in EffectDimension:
        known_targets = {item.target for item in boundary.occurrences if item.dimension is dimension}
        field = {EffectDimension.RNG: "rng", EffectDimension.EXTERNAL: "external",
                 EffectDimension.ORDERING: "ordering", EffectDimension.MAY_RAISE: "may_raise"}.get(dimension)
        if field:
            presence = getattr(boundary.effects, field)
            if presence is EffectPresence.NONE and known_targets:
                raise ValueError("effect summary NONE contradicts occurrences")
            if presence is EffectPresence.UNKNOWN or (presence is EffectPresence.PRESENT and not known_targets):
                gaps.append(EffectGap(None, boundary.scope, dimension,
                                      "scalar effect coverage or occurrence targets are unresolved"))
        else:
            members = set(getattr(boundary.effects, dimension.value).members)
            if members != known_targets:
                gaps.append(EffectGap(None, boundary.scope, dimension,
                                      "effect summary and occurrence targets do not fully correspond"))
    if any(gap.scope != boundary.scope for gap in gaps):
        raise ValueError("gap belongs to another scope")
    if mode is not boundary.mode:
        gaps.append(EffectGap(None, boundary.scope, None,
                              f"requested {mode.value} but evidence covers {boundary.mode.value}"))
    covered_gaps = {gap.dimension for gap in gaps}
    for dimension in EffectDimension:
        coverage = coverages.get(dimension)
        if (coverage is None or not coverage.closed or "*" not in coverage.target_domain) and dimension not in covered_gaps:
            gaps.append(EffectGap(None, boundary.scope, dimension,
                                  "complete branch, call and alias coverage is not established"))
    if not boundary.ready_for_region_construction and not gaps:
        gaps.append(EffectGap(None, boundary.scope, None, "region boundary is not closed"))
    requests = []
    seen = set()
    for gap in sorted(gaps, key=lambda item: (
            item.definition.wire if item.definition else "", item.dimension.value if item.dimension else "", item.reason)):
        definitions = (gap.definition,) if gap.definition else boundary.members
        key = (definitions, gap.dimension, gap.reason)
        if key in seen:
            continue
        seen.add(key)
        locations = _locations(semantic, definitions)
        supported = sorted((item for item in collectors if item.mode is mode and gap.dimension in item.dimensions),
                           key=lambda item: item.name)
        collector = supported[0] if supported and run_manifest else None
        disposition = Disposition.INSTRUMENT if collector else Disposition.CONTRACT
        digest = hashlib.sha256(json.dumps([boundary.scope, [item.wire for item in definitions],
            gap.dimension.value if gap.dimension else None, gap.reason], sort_keys=True).encode()).hexdigest()
        requests.append(EvidenceRequest(
            "request:" + digest, disposition, boundary.scope, definitions, locations,
            _location_hints(semantic, definitions), gap.dimension,
            gap.reason, collector.name if collector else None,
            collector.fields if collector else ("versioned scope/effect contract",),
            collector.command_prefix + ("--",) + run_manifest.argv if collector else None,
            run_manifest.cwd if collector else None, run_manifest.environment_identity if collector else None,
            "capture required fields in this scope, then rerun closure; observations alone do not prove all paths"
            if collector else "provide a scoped, versioned contract or implement a collector for the missing fact",
            ("source or loaded code changes", "scope, alias or contract changes"),
        ))
    reasons = []
    if required:
        disposition = Disposition.KEEP
        reasons.append("required effects would be removed; preserve their dependency and ordering slice")
    elif any(item.disposition is Disposition.CONTRACT for item in requests):
        disposition = Disposition.CONTRACT
        reasons.append("effect boundary cannot be certified with available scoped evidence")
    elif requests:
        disposition = Disposition.INSTRUMENT
        reasons.append("supported collectors can obtain the requested evidence; reanalysis still required")
    else:
        disposition = Disposition.KEEP
        reasons.append("effect evidence is sufficient; continue region construction, no transformation selected here")
    ready = boundary.ready_for_region_construction and not requests
    satisfied = ready and not required
    return ContractAssessment(boundary.scope, policy.id, disposition, satisfied, ready,
                              tuple(required), tuple(ignored), tuple(requests), tuple(reasons))


__all__ = ["PolicyAction", "Disposition", "EffectPolicyRule", "EffectPolicy", "RunManifest",
           "CollectorCapability", "EvidenceRequest", "ContractAssessment", "evaluate_removal"]
