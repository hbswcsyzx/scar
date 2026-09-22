"""Typed semantic graph for Python/PyTorch program definitions."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .common import EvidenceClaim, SourceReference
from ._validation import cycle_errors, mapping_errors
from .contracts import ContractDefinition, EffectSummary, ResourceRequirement
from .ids import (
    ContractID,
    ControlRegionID,
    EffectSummaryID,
    Identifier,
    ModuleID,
    OperationDefinitionID,
    PackageID,
    ResourceID,
    SourceAtomID,
    ValueSlotID,
)


class OperationKind(str, Enum):
    FUNCTION = "function"
    METHOD = "method"
    MODULE = "module"
    OPERATOR = "operator"
    KERNEL = "kernel"
    TRANSFER = "transfer"
    ALLOCATION = "allocation"
    BRANCH = "branch"
    LOOP = "loop"
    CALLBACK = "callback"
    IMPORT = "import"
    ATTRIBUTE = "attribute"
    INDEX = "index"
    CONSTANT = "constant"
    REGION = "region"
    STAGE = "stage"
    OPAQUE = "opaque"


@dataclass(slots=True)
class PackageDefinition:
    id: PackageID
    name: str
    root: str | None = None
    fingerprint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id.as_dict(), "name": self.name,
                "root": self.root, "fingerprint": self.fingerprint}


@dataclass(slots=True)
class ModuleDefinition:
    id: ModuleID
    name: str
    package: PackageID | None = None
    path: str | None = None
    fingerprint: str | None = None
    initializer: OperationDefinitionID | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.as_dict(), "name": self.name,
            "package": self.package.as_dict() if self.package else None,
            "path": self.path, "fingerprint": self.fingerprint,
            "initializer": self.initializer.as_dict() if self.initializer else None,
        }


@dataclass(slots=True)
class SourceAtom:
    id: SourceAtomID
    reference: SourceReference
    kind: str
    text_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if self.reference.atom_id != self.id:
            raise ValueError("source atom ID must match its source reference")

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id.as_dict(), "reference": self.reference.as_dict(),
                "kind": self.kind, "text_fingerprint": self.text_fingerprint}


@dataclass(slots=True)
class ValueSlot:
    slot_id: ValueSlotID
    name: str
    direction: str
    semantic_type: str | None = None
    owner: OperationDefinitionID | None = None
    mutable: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.slot_id, ValueSlotID):
            raise TypeError("slot_id must be ValueSlotID")
        if self.owner is not None and not isinstance(self.owner, OperationDefinitionID):
            raise TypeError("slot owner must be OperationDefinitionID")

    def as_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id.as_dict(), "name": self.name,
            "direction": self.direction, "semantic_type": self.semantic_type,
            "owner": self.owner.as_dict() if self.owner else None,
            "mutable": self.mutable, "metadata": self.metadata,
        }


@dataclass(slots=True)
class OperationDefinition:
    id: OperationDefinitionID
    kind: OperationKind
    label: str
    code_id: str | None = None
    source_file: str | None = None
    source_start: int | None = None
    source_end: int | None = None
    parent_id: OperationDefinitionID | None = None
    control_region: ControlRegionID | None = None
    input_slots: tuple[ValueSlotID, ...] = ()
    output_slots: tuple[ValueSlotID, ...] = ()
    state_slots: tuple[ValueSlotID, ...] = ()
    source_atoms: tuple[SourceAtomID, ...] = ()
    contract: ContractID | None = None
    effect_summary: EffectSummaryID | None = None
    resource_requirements: tuple[ResourceID, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        typed_groups = (
            (self.input_slots + self.output_slots + self.state_slots, ValueSlotID, "slot"),
            (self.source_atoms, SourceAtomID, "source atom"),
            (self.resource_requirements, ResourceID, "resource"),
        )
        for members, expected, label in typed_groups:
            if any(not isinstance(item, expected) for item in members):
                raise TypeError(f"operation {label} references must use {expected.__name__}")
        if self.parent_id is not None and not isinstance(self.parent_id, OperationDefinitionID):
            raise TypeError("parent_id must be OperationDefinitionID")
        if self.control_region is not None and not isinstance(self.control_region, ControlRegionID):
            raise TypeError("control_region must be ControlRegionID")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.as_dict(), "kind": self.kind.value, "label": self.label,
            "code_id": self.code_id, "source_file": self.source_file,
            "source_start": self.source_start, "source_end": self.source_end,
            "parent_id": self.parent_id.as_dict() if self.parent_id else None,
            "control_region": self.control_region.as_dict() if self.control_region else None,
            "input_slots": [item.as_dict() for item in self.input_slots],
            "output_slots": [item.as_dict() for item in self.output_slots],
            "state_slots": [item.as_dict() for item in self.state_slots],
            "source_atoms": [item.as_dict() for item in self.source_atoms],
            "contract": self.contract.as_dict() if self.contract else None,
            "effect_summary": self.effect_summary.as_dict() if self.effect_summary else None,
            "resource_requirements": [item.as_dict() for item in self.resource_requirements],
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class ControlRegion:
    id: ControlRegionID
    kind: str
    parent_id: ControlRegionID | None = None
    owner: OperationDefinitionID | None = None
    source_atoms: tuple[SourceAtomID, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.as_dict(), "kind": self.kind,
            "parent_id": self.parent_id.as_dict() if self.parent_id else None,
            "owner": self.owner.as_dict() if self.owner else None,
            "source_atoms": [item.as_dict() for item in self.source_atoms],
            "metadata": self.metadata,
        }


class SemanticNodeKind(str, Enum):
    PACKAGE = "package"
    MODULE = "module"
    SOURCE_ATOM = "source_atom"
    OPERATION = "operation"
    VALUE_SLOT = "value_slot"
    CONTROL = "control"
    CONTRACT = "contract"
    EFFECT = "effect"
    RESOURCE = "resource"


_ENDPOINT_TYPES: dict[SemanticNodeKind, type[Identifier]] = {
    SemanticNodeKind.PACKAGE: PackageID,
    SemanticNodeKind.MODULE: ModuleID,
    SemanticNodeKind.SOURCE_ATOM: SourceAtomID,
    SemanticNodeKind.OPERATION: OperationDefinitionID,
    SemanticNodeKind.VALUE_SLOT: ValueSlotID,
    SemanticNodeKind.CONTROL: ControlRegionID,
    SemanticNodeKind.CONTRACT: ContractID,
    SemanticNodeKind.EFFECT: EffectSummaryID,
    SemanticNodeKind.RESOURCE: ResourceID,
}


@dataclass(frozen=True, slots=True)
class SemanticEndpoint:
    kind: SemanticNodeKind
    id: Identifier

    def __post_init__(self) -> None:
        expected = _ENDPOINT_TYPES[self.kind]
        if not isinstance(self.id, expected):
            raise TypeError(f"{self.kind.value} endpoint requires {expected.__name__}")

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "id": self.id.as_dict()}


class SemanticRelation(str, Enum):
    CONTAINS = "contains"
    CALLS = "calls"
    CONTROLS = "controls"
    READS_SLOT = "reads_slot"
    WRITES_SLOT = "writes_slot"
    CONSUMES = "consumes"
    PRODUCES = "produces"
    MAY_RAISE = "may_raise"
    INITIALIZES_MODULE = "initializes_module"
    IMPORTS = "imports"
    REEXPORTS = "reexports"
    ACCESSES_ATTRIBUTE = "accesses_attribute"
    HAS_CONTRACT = "has_contract"
    HAS_EFFECT = "has_effect"
    REQUIRES_RESOURCE = "requires_resource"
    HAS_SOURCE = "has_source"
    LOWERS_TO = "lowers_to"


# Relations have a direction and a domain/range.  Existing endpoints alone do
# not make an edge meaningful (for example, a resource cannot call a package).
_S = SemanticNodeKind
_SEMANTIC_RELATION_ENDPOINTS = {
    SemanticRelation.CONTAINS: {
        (_S.PACKAGE, _S.PACKAGE), (_S.PACKAGE, _S.MODULE),
        (_S.MODULE, _S.OPERATION), (_S.MODULE, _S.VALUE_SLOT),
        (_S.MODULE, _S.CONTROL), (_S.OPERATION, _S.OPERATION),
        (_S.OPERATION, _S.VALUE_SLOT), (_S.OPERATION, _S.CONTROL),
        (_S.CONTROL, _S.CONTROL), (_S.CONTROL, _S.OPERATION),
    },
    SemanticRelation.CALLS: {(_S.OPERATION, _S.OPERATION)},
    SemanticRelation.CONTROLS: {
        (source, target) for source in (_S.OPERATION, _S.CONTROL)
        for target in (_S.OPERATION, _S.CONTROL)},
    **{relation: {(_S.OPERATION, _S.VALUE_SLOT)} for relation in (
        SemanticRelation.READS_SLOT, SemanticRelation.WRITES_SLOT,
        SemanticRelation.CONSUMES, SemanticRelation.PRODUCES)},
    SemanticRelation.MAY_RAISE: {(_S.OPERATION, _S.EFFECT), (_S.OPERATION, _S.CONTROL)},
    SemanticRelation.INITIALIZES_MODULE: {(_S.OPERATION, _S.MODULE)},
    SemanticRelation.IMPORTS: {
        (source, target) for source in (_S.OPERATION, _S.MODULE)
        for target in (_S.MODULE, _S.PACKAGE)},
    SemanticRelation.REEXPORTS: {
        (_S.MODULE, target) for target in (_S.MODULE, _S.OPERATION, _S.VALUE_SLOT)},
    SemanticRelation.ACCESSES_ATTRIBUTE: {
        (_S.OPERATION, target) for target in (_S.MODULE, _S.OPERATION, _S.VALUE_SLOT)},
    SemanticRelation.HAS_CONTRACT: {(_S.OPERATION, _S.CONTRACT), (_S.MODULE, _S.CONTRACT)},
    SemanticRelation.HAS_EFFECT: {(_S.OPERATION, _S.EFFECT), (_S.MODULE, _S.EFFECT)},
    SemanticRelation.REQUIRES_RESOURCE: {(_S.OPERATION, _S.RESOURCE)},
    SemanticRelation.HAS_SOURCE: {
        (source, _S.SOURCE_ATOM) for source in (
            _S.PACKAGE, _S.MODULE, _S.OPERATION, _S.CONTROL, _S.VALUE_SLOT)},
    SemanticRelation.LOWERS_TO: {(_S.OPERATION, _S.OPERATION)},
}


@dataclass(frozen=True, slots=True)
class SemanticEdge:
    edge_id: str
    relation: SemanticRelation
    source: SemanticEndpoint
    target: SemanticEndpoint
    evidence: EvidenceClaim

    def __post_init__(self) -> None:
        if not self.edge_id:
            raise ValueError("semantic edge ID is required")
        if (self.source.kind, self.target.kind) not in _SEMANTIC_RELATION_ENDPOINTS[self.relation]:
            raise ValueError(f"invalid endpoints for semantic relation {self.relation.value}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id, "relation": self.relation.value,
            "source": self.source.as_dict(), "target": self.target.as_dict(),
            "evidence": self.evidence.as_dict(),
        }


class SemanticGraph:
    """Static definitions and typed relations, without runtime claims."""

    SCHEMA = "scar.ir.v2.semantic"
    SCHEMA_VERSION = 2

    def __init__(self) -> None:
        self.packages: dict[PackageID, PackageDefinition] = {}
        self.modules: dict[ModuleID, ModuleDefinition] = {}
        self.source_atoms: dict[SourceAtomID, SourceAtom] = {}
        self.definitions: dict[OperationDefinitionID, OperationDefinition] = {}
        self.slots: dict[ValueSlotID, ValueSlot] = {}
        self.controls: dict[ControlRegionID, ControlRegion] = {}
        self.contracts: dict[ContractID, ContractDefinition] = {}
        self.effects: dict[EffectSummaryID, EffectSummary] = {}
        self.resources: dict[ResourceID, ResourceRequirement] = {}
        self.edges: dict[str, SemanticEdge] = {}

    @staticmethod
    def _insert(mapping, key, value, label: str) -> None:
        if key in mapping:
            rendered = key.wire if hasattr(key, "wire") else str(key)
            raise ValueError(f"duplicate {label}: {rendered}")
        mapping[key] = value

    def add_package(self, item: PackageDefinition) -> None:
        self._insert(self.packages, item.id, item, "package")

    def add_module(self, item: ModuleDefinition) -> None:
        if item.package is not None and item.package not in self.packages:
            raise ValueError(f"unknown module package: {item.package.wire}")
        self._insert(self.modules, item.id, item, "module")

    def add_source_atom(self, item: SourceAtom) -> None:
        self._insert(self.source_atoms, item.id, item, "source atom")

    def add_definition(self, item: OperationDefinition) -> None:
        if item.parent_id is not None and item.parent_id not in self.definitions:
            raise ValueError(f"unknown parent definition: {item.parent_id.wire}")
        if item.control_region is not None and item.control_region not in self.controls:
            raise ValueError(f"unknown control region: {item.control_region.wire}")
        self._insert(self.definitions, item.id, item, "operation definition")

    def add_slot(self, item: ValueSlot) -> None:
        if item.owner is not None and item.owner not in self.definitions:
            raise ValueError(f"unknown slot owner: {item.owner.wire}")
        self._insert(self.slots, item.slot_id, item, "value slot")

    def add_control(self, item: ControlRegion) -> None:
        if item.parent_id is not None and item.parent_id not in self.controls:
            raise ValueError(f"unknown parent control: {item.parent_id.wire}")
        if item.owner is not None and item.owner not in self.definitions:
            raise ValueError(f"unknown control owner: {item.owner.wire}")
        self._insert(self.controls, item.id, item, "control region")

    def add_contract(self, item: ContractDefinition) -> None:
        self._insert(self.contracts, item.id, item, "contract")

    def add_effect(self, item: EffectSummary) -> None:
        self._insert(self.effects, item.id, item, "effect summary")

    def add_resource(self, item: ResourceRequirement) -> None:
        self._insert(self.resources, item.id, item, "resource")

    def add_edge(self, item: SemanticEdge) -> None:
        if not self._endpoint_exists(item.source):
            raise ValueError(f"unknown semantic edge source: {item.source.id.wire}")
        if not self._endpoint_exists(item.target):
            raise ValueError(f"unknown semantic edge target: {item.target.id.wire}")
        self._insert(self.edges, item.edge_id, item, "semantic edge")

    def _endpoint_exists(self, endpoint: SemanticEndpoint) -> bool:
        mappings = {
            SemanticNodeKind.PACKAGE: self.packages,
            SemanticNodeKind.MODULE: self.modules,
            SemanticNodeKind.SOURCE_ATOM: self.source_atoms,
            SemanticNodeKind.OPERATION: self.definitions,
            SemanticNodeKind.VALUE_SLOT: self.slots,
            SemanticNodeKind.CONTROL: self.controls,
            SemanticNodeKind.CONTRACT: self.contracts,
            SemanticNodeKind.EFFECT: self.effects,
            SemanticNodeKind.RESOURCE: self.resources,
        }
        return endpoint.id in mappings[endpoint.kind]

    def children_of(self, definition: OperationDefinitionID) -> tuple[OperationDefinition, ...]:
        if definition not in self.definitions:
            raise KeyError(f"unknown operation definition: {definition.wire}")
        return tuple(item for item in self.definitions.values() if item.parent_id == definition)

    def descendants_of(self, definition: OperationDefinitionID) -> tuple[OperationDefinition, ...]:
        result: list[OperationDefinition] = []
        pending = list(self.children_of(definition))
        visited = {definition}
        while pending:
            child = pending.pop(0)
            if child.id in visited:
                raise ValueError("cyclic operation definition ancestry")
            visited.add(child.id)
            result.append(child)
            pending.extend(self.children_of(child.id))
        return tuple(result)

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        registries = (
            (self.packages, PackageID, PackageDefinition, "packages", "id"),
            (self.modules, ModuleID, ModuleDefinition, "modules", "id"),
            (self.source_atoms, SourceAtomID, SourceAtom, "source_atoms", "id"),
            (self.definitions, OperationDefinitionID, OperationDefinition, "definitions", "id"),
            (self.slots, ValueSlotID, ValueSlot, "slots", "slot_id"),
            (self.controls, ControlRegionID, ControlRegion, "controls", "id"),
            (self.contracts, ContractID, ContractDefinition, "contracts", "id"),
            (self.effects, EffectSummaryID, EffectSummary, "effects", "id"),
            (self.resources, ResourceID, ResourceRequirement, "resources", "id"),
            (self.edges, str, SemanticEdge, "edges", "edge_id"),
        )
        for mapping, key_type, record_type, name, key_field in registries:
            errors.extend(mapping_errors(mapping, key_type, record_type, name, key_field))
        if errors:
            return self._validation_report(errors)
        for module in self.modules.values():
            if module.package is not None and module.package not in self.packages:
                errors.append(f"module {module.id.wire} references unknown package")
            if module.initializer is not None and module.initializer not in self.definitions:
                errors.append(f"module {module.id.wire} references unknown initializer")
        for definition in self.definitions.values():
            missing = {slot for slot in definition.input_slots + definition.output_slots
                       + definition.state_slots if slot not in self.slots}
            errors.extend(f"definition {definition.id.wire} references unknown slot {slot.wire}"
                          for slot in sorted(missing, key=lambda item: item.wire))
            unknown_atoms = {atom for atom in definition.source_atoms
                             if atom not in self.source_atoms}
            errors.extend(f"definition {definition.id.wire} references unknown source {atom.wire}"
                          for atom in sorted(unknown_atoms, key=lambda item: item.wire))
            if definition.parent_id is not None and definition.parent_id not in self.definitions:
                errors.append(f"definition {definition.id.wire} references unknown parent")
            if definition.control_region is not None and definition.control_region not in self.controls:
                errors.append(f"definition {definition.id.wire} references unknown control")
            if definition.contract is not None and definition.contract not in self.contracts:
                errors.append(f"definition {definition.id.wire} references unknown contract")
            if definition.effect_summary is not None and definition.effect_summary not in self.effects:
                errors.append(f"definition {definition.id.wire} references unknown effect")
            for resource in definition.resource_requirements:
                if resource not in self.resources:
                    errors.append(f"definition {definition.id.wire} references unknown resource")
            for slot_id in definition.input_slots + definition.output_slots + definition.state_slots:
                slot = self.slots.get(slot_id)
                if slot is not None and slot.owner is not None and slot.owner != definition.id:
                    errors.append(f"definition {definition.id.wire} references slot owned by another definition")
        for slot in self.slots.values():
            if slot.owner is not None and slot.owner not in self.definitions:
                errors.append(f"slot {slot.slot_id.wire} references unknown owner")
        for control in self.controls.values():
            if control.parent_id is not None and control.parent_id not in self.controls:
                errors.append(f"control {control.id.wire} references unknown parent")
            if control.owner is not None and control.owner not in self.definitions:
                errors.append(f"control {control.id.wire} references unknown owner")
            for atom in control.source_atoms:
                if atom not in self.source_atoms:
                    errors.append(f"control {control.id.wire} references unknown source")
        for contract in self.contracts.values():
            for slot in contract.required_outputs:
                if slot not in self.slots:
                    errors.append(f"contract {contract.id.wire} references unknown slot {slot.wire}")
        for edge in self.edges.values():
            if not self._endpoint_exists(edge.source):
                errors.append(f"edge {edge.edge_id} has unknown source")
            if not self._endpoint_exists(edge.target):
                errors.append(f"edge {edge.edge_id} has unknown target")
        containment = [(item.parent_id, item.id) for item in self.definitions.values()
                       if item.parent_id is not None]
        containment += [(item.parent_id, item.id) for item in self.controls.values()
                        if item.parent_id is not None]
        containment += [(edge.source.id, edge.target.id) for edge in self.edges.values()
                        if edge.relation is SemanticRelation.CONTAINS]
        errors.extend(cycle_errors(containment, "semantic containment / ancestry"))
        errors.extend(cycle_errors(
            ((edge.source.id, edge.target.id) for edge in self.edges.values()
             if edge.relation is SemanticRelation.LOWERS_TO), "semantic lowering"))
        return self._validation_report(errors)

    def _validation_report(self, errors: list[str]) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION,
            "valid": not errors, "errors": errors,
            "counts": {
                "packages": len(self.packages), "modules": len(self.modules),
                "source_atoms": len(self.source_atoms),
                "definitions": len(self.definitions), "slots": len(self.slots),
                "controls": len(self.controls), "contracts": len(self.contracts),
                "effects": len(self.effects), "resources": len(self.resources),
                "edges": len(self.edges),
            },
        }

    def assert_valid(self) -> dict[str, Any]:
        report = self.validate()
        if not report["valid"]:
            raise ValueError("invalid v2 SemanticGraph: " + "; ".join(report["errors"]))
        return report

    def to_dict(self) -> dict[str, Any]:
        validation = self.assert_valid()

        def ordered(mapping):
            return [mapping[key].as_dict() for key in sorted(
                mapping, key=lambda item: item.wire if hasattr(item, "wire") else str(item))]

        return {
            "schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION,
            "packages": ordered(self.packages), "modules": ordered(self.modules),
            "source_atoms": ordered(self.source_atoms),
            "definitions": ordered(self.definitions), "slots": ordered(self.slots),
            "controls": ordered(self.controls), "contracts": ordered(self.contracts),
            "effects": ordered(self.effects), "resources": ordered(self.resources),
            "edges": ordered(self.edges), "validation": validation,
        }


__all__ = [
    "ControlRegion", "ModuleDefinition", "OperationDefinition", "OperationKind",
    "PackageDefinition", "SemanticEdge", "SemanticEndpoint", "SemanticGraph",
    "SemanticNodeKind", "SemanticRelation", "SourceAtom", "ValueSlot",
]
