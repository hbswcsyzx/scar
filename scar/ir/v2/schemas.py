"""Cross-graph validation and deterministic serialization for IR v2."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, TYPE_CHECKING

from .correspondence import CorrespondenceGraph
from .evidence import EvidenceGraph, EvidenceNodeKind
from .optimization import (
    OptimizationContext,
    OptimizationGraph,
    StaticBindingInfo,
    StaticValueInfo,
)
from .semantic import SemanticGraph
from .values import ValueGraph

if TYPE_CHECKING:
    from ..semantics_v2 import SourceSemanticsGraph


def canonical_json(document: Any) -> str:
    """Serialize an IR object deterministically for hashing and review."""
    payload = document.to_dict() if hasattr(document, "to_dict") else document
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def optimization_context(
    semantic: SemanticGraph,
    evidence: EvidenceGraph,
    values: ValueGraph,
    source_semantics: SourceSemanticsGraph | None = None,
) -> OptimizationContext:
    """Create the exact external-reference universe accepted by an OIR graph."""
    static_values = {}
    static_bindings = {}
    if source_semantics is not None:
        # Delayed import avoids loading semantics_v2 while the v2 package is
        # still initializing (semantics_v2 itself uses v2 validation helpers).
        from ..semantics_v2 import SourceSemanticsGraph

        if type(source_semantics) is not SourceSemanticsGraph:
            raise TypeError("source_semantics must be SourceSemanticsGraph or None")
        static_values = {
            identifier: StaticValueInfo(value.producer, value.source, value.external)
            for identifier, value in source_semantics.values.items()
        }
        static_bindings = {
            identifier: StaticBindingInfo(binding.value, binding.definition, binding.source)
            for identifier, binding in source_semantics.bindings.items()
        }
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
        value_slots=frozenset(semantic.slots),
        static_values=static_values,
        static_bindings=static_bindings,
    )


@dataclass(slots=True)
class IRBundle:
    """A validated view over separate SG, EEG, ValueGraph and optional OIR."""

    semantic: SemanticGraph
    evidence: EvidenceGraph
    values: ValueGraph
    correspondence: CorrespondenceGraph | None = None
    optimization: OptimizationGraph | None = None
    source_semantics: SourceSemanticsGraph | None = None

    SCHEMA = "scar.ir.v2.bundle"
    SCHEMA_VERSION = 2

    def validate(self) -> dict[str, Any]:
        reports = {
            "semantic": self.semantic.validate(),
            "evidence": self.evidence.validate(),
            "values": self.values.validate(),
        }
        if self.optimization is not None:
            reports["optimization"] = self.optimization.validate()
        if self.source_semantics is not None:
            from ..semantics_v2 import SourceSemanticsGraph

            if type(self.source_semantics) is SourceSemanticsGraph:
                reports["source_semantics"] = self.source_semantics.validate(self.semantic)
            else:
                reports["source_semantics"] = {
                    "schema": "scar.source-semantics.v2", "valid": False,
                    "errors": ["source_semantics must be SourceSemanticsGraph"],
                }
        if self.correspondence is not None:
            reports["correspondence"] = self.correspondence.validate()
        errors: list[str] = []
        for name, report in reports.items():
            errors.extend(f"{name}: {item}" for item in report["errors"])
        if errors:
            return {"schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION,
                    "valid": False, "errors": errors, "graphs": reports}

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
            elif observation.materialization is not None:
                materialization = self.values.materializations[observation.materialization]
                if materialization.value_version != observation.version:
                    errors.append(f"observation {observation.observation_id} materialization version mismatch")
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
        external_wires = {kind: {item.wire for item in owners}
                          for kind, owners in external_owners.items()}
        for kind, wire in self.evidence.external_references:
            if wire not in external_wires.get(kind, set()):
                errors.append(f"evidence external reference {kind.value}:{wire} is unknown")
        if self.correspondence is not None:
            errors.extend(self.correspondence.validate_references(
                self.semantic, self.evidence, self.values))
        if self.optimization is not None:
            expected = optimization_context(
                self.semantic, self.evidence, self.values, self.source_semantics)
            if self.optimization.context != expected:
                errors.append("optimization context does not match bundle graphs")
            for port in self.optimization.ports.values():
                if not port.value:
                    continue
                for mid in port.value.materializations:
                    materialization = self.values.materializations.get(mid)
                    if (materialization and port.value.versions
                            and materialization.value_version not in port.value.versions):
                        errors.append(f"port {port.port_id} materialization version mismatch")
            for alternative in self.optimization.alternatives.values():
                if self.source_semantics is not None:
                    static_values = self.source_semantics.values
                    static_operations = self.source_semantics.operations
                    static_bindings = self.source_semantics.bindings
                    for substitution in alternative.delta.static_substitutions:
                        static_value = static_values.get(substitution.static_value)
                        if static_value is None:
                            errors.append(
                                f"static substitution references unknown static value "
                                f"{substitution.static_value.wire}")
                            continue
                        operation = static_operations.get(substitution.operation)
                        if (static_value.external or static_value.producer != substitution.operation
                                or static_value.source != substitution.source):
                            errors.append(
                                f"static substitution {substitution.static_value.wire} "
                                "does not match its static value producer/source")
                        if (operation is None or operation.result != substitution.static_value
                                or operation.source != substitution.source):
                            errors.append(
                                f"static substitution {substitution.static_value.wire} "
                                "does not match source operation semantics")
                        if substitution.binding is not None:
                            binding = static_bindings.get(substitution.binding)
                            if (binding is None
                                    or binding.value != substitution.static_value
                                    or binding.definition != substitution.operation
                                    or binding.source != substitution.source):
                                errors.append(
                                    f"static substitution {substitution.static_value.wire} "
                                    "does not match replacement binding")
                for instruction in alternative.instructions:
                    if instruction.source is None:
                        continue
                    atom = self.semantic.source_atoms.get(instruction.source.atom_id)
                    if atom is None or atom.reference != instruction.source:
                        errors.append(f"instruction {instruction.instruction_id} source reference mismatch")

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
            "source_semantics": self.source_semantics.to_dict()
            if self.source_semantics is not None else None,
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
