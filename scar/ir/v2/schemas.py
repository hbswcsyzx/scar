"""Cross-graph validation and deterministic serialization for IR v2."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .correspondence import CorrespondenceGraph
from .evidence import EvidenceGraph, EvidenceNodeKind
from .optimization import OptimizationContext, OptimizationGraph
from .semantic import SemanticGraph
from .values import ValueGraph


def canonical_json(document: Any) -> str:
    """Serialize an IR object deterministically for hashing and review."""
    payload = document.to_dict() if hasattr(document, "to_dict") else document
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def optimization_context(
    semantic: SemanticGraph,
    evidence: EvidenceGraph,
    values: ValueGraph,
) -> OptimizationContext:
    """Create the exact external-reference universe accepted by an OIR graph."""
    return OptimizationContext(
        definitions=frozenset(semantic.definitions),
        instances=frozenset(evidence.instances),
        value_versions=frozenset(values.versions),
        provenance=frozenset(values.provenance),
        materializations=frozenset(values.materializations),
        controls=frozenset(semantic.controls),
        resources=frozenset(semantic.resources),
        effects=frozenset(semantic.effects),
        contracts=frozenset(semantic.contracts),
        source_atoms=frozenset(semantic.source_atoms),
        measurements=frozenset(evidence.measurements),
    )


@dataclass(slots=True)
class IRBundle:
    """A validated view over separate SG, EEG, ValueGraph and optional OIR."""

    semantic: SemanticGraph
    evidence: EvidenceGraph
    values: ValueGraph
    correspondence: CorrespondenceGraph | None = None
    optimization: OptimizationGraph | None = None

    SCHEMA = "scar.ir.v2.bundle"
    SCHEMA_VERSION = 1

    def validate(self) -> dict[str, Any]:
        reports = {
            "semantic": self.semantic.validate(),
            "evidence": self.evidence.validate(),
            "values": self.values.validate(),
        }
        if self.optimization is not None:
            reports["optimization"] = self.optimization.validate()
        if self.correspondence is not None:
            reports["correspondence"] = self.correspondence.validate()
        errors: list[str] = []
        for name, report in reports.items():
            errors.extend(f"{name}: {item}" for item in report["errors"])

        for instance in self.evidence.instances.values():
            if instance.definition not in self.semantic.definitions:
                errors.append(
                    f"evidence instance {instance.id.wire} references unknown "
                    f"definition {instance.definition.wire}")
        for observation in self.evidence.observations.values():
            if observation.version not in self.values.versions:
                errors.append(
                    f"observation {observation.observation_id} references unknown "
                    f"version {observation.version.wire}")
            if (observation.materialization is not None
                    and observation.materialization not in self.values.materializations):
                errors.append(
                    f"observation {observation.observation_id} references unknown "
                    f"materialization {observation.materialization.wire}")
        for provenance in self.values.provenance.values():
            if provenance.producer is not None and provenance.producer not in self.evidence.instances:
                errors.append(
                    f"provenance {provenance.id.wire} references unknown producer "
                    f"{provenance.producer.wire}")
        for materialization in self.values.materializations.values():
            if (materialization.producer is not None
                    and materialization.producer not in self.evidence.instances):
                errors.append(
                    f"materialization {materialization.id.wire} references unknown "
                    f"producer {materialization.producer.wire}")
        external_owners = {
            EvidenceNodeKind.VALUE_VERSION: self.values.versions,
            EvidenceNodeKind.MATERIALIZATION: self.values.materializations,
            EvidenceNodeKind.OBJECT: {
                item.object_id for item in self.values.bindings
            },
            EvidenceNodeKind.ALLOCATION: self.values.allocations,
            EvidenceNodeKind.STORAGE_REGION: self.values.regions,
            EvidenceNodeKind.RESOURCE: self.semantic.resources,
        }
        for kind, wire in self.evidence.external_references:
            owners = external_owners.get(kind)
            if owners is None or not any(item.wire == wire for item in owners):
                errors.append(f"evidence external reference {kind.value}:{wire} is unknown")
        if self.correspondence is not None:
            errors.extend(self.correspondence.validate_references(
                self.semantic, self.evidence, self.values))
        if self.optimization is not None:
            expected = optimization_context(self.semantic, self.evidence, self.values)
            if self.optimization.context != expected:
                errors.append("optimization context does not match SG/EEG/ValueGraph")

        return {
            "schema": self.SCHEMA,
            "schema_version": self.SCHEMA_VERSION,
            "valid": not errors,
            "errors": errors,
            "graphs": reports,
        }

    def assert_valid(self) -> dict[str, Any]:
        report = self.validate()
        if not report["valid"]:
            raise ValueError("invalid v2 IRBundle: " + "; ".join(report["errors"]))
        return report

    def to_dict(self) -> dict[str, Any]:
        self.assert_valid()
        return {
            "schema": self.SCHEMA,
            "schema_version": self.SCHEMA_VERSION,
            "semantic": self.semantic.to_dict(),
            "evidence": self.evidence.to_dict(),
            "values": self.values.to_dict(),
            "correspondence": self.correspondence.to_dict()
            if self.correspondence is not None else None,
            "optimization": self.optimization.to_dict()
            if self.optimization is not None else None,
            "validation": self.validate(),
        }

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> "IRBundle":
        from .codec import bundle_from_dict
        return bundle_from_dict(document)

    @classmethod
    def from_json(cls, payload: str) -> "IRBundle":
        from .codec import bundle_from_json
        return bundle_from_json(payload)


__all__ = ["IRBundle", "canonical_json", "optimization_context"]
