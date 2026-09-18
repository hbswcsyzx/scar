"""Small semantic-graph layer for v2 operation definitions."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .ids import ControlRegionID, OperationDefinitionID


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
    REGION = "region"
    STAGE = "stage"
    OPAQUE = "opaque"


@dataclass(slots=True)
class ValueSlot:
    slot_id: str
    name: str
    direction: str
    semantic_type: str | None = None
    owner: OperationDefinitionID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "name": self.name,
            "direction": self.direction,
            "semantic_type": self.semantic_type,
            "owner": self.owner.as_dict() if self.owner else None,
            "metadata": self.metadata,
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
    input_slots: tuple[str, ...] = ()
    output_slots: tuple[str, ...] = ()
    state_slots: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.as_dict(),
            "kind": self.kind.value,
            "label": self.label,
            "code_id": self.code_id,
            "source_file": self.source_file,
            "source_start": self.source_start,
            "source_end": self.source_end,
            "parent_id": self.parent_id.as_dict() if self.parent_id else None,
            "control_region": self.control_region.as_dict() if self.control_region else None,
            "input_slots": list(self.input_slots),
            "output_slots": list(self.output_slots),
            "state_slots": list(self.state_slots),
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class ControlRegion:
    id: ControlRegionID
    kind: str
    parent_id: ControlRegionID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id.as_dict(), "kind": self.kind,
                "parent_id": self.parent_id.as_dict() if self.parent_id else None,
                "metadata": self.metadata}


class SemanticGraph:
    """Static definitions and control/value slots, without runtime claims."""

    SCHEMA = "scar.ir.v2.semantic"
    SCHEMA_VERSION = 1

    def __init__(self) -> None:
        self.definitions: dict[OperationDefinitionID, OperationDefinition] = {}
        self.slots: dict[str, ValueSlot] = {}
        self.controls: dict[ControlRegionID, ControlRegion] = {}

    def add_definition(self, definition: OperationDefinition) -> None:
        if definition.id in self.definitions:
            raise ValueError(f"duplicate operation definition: {definition.id.wire}")
        if definition.parent_id is not None and definition.parent_id not in self.definitions:
            raise ValueError(f"unknown parent definition: {definition.parent_id.wire}")
        if definition.control_region is not None and definition.control_region not in self.controls:
            raise ValueError(f"unknown control region: {definition.control_region.wire}")
        self.definitions[definition.id] = definition

    def add_slot(self, slot: ValueSlot) -> None:
        if slot.slot_id in self.slots:
            raise ValueError(f"duplicate value slot: {slot.slot_id}")
        if slot.owner is not None and slot.owner not in self.definitions:
            raise ValueError(f"unknown slot owner: {slot.owner.wire}")
        self.slots[slot.slot_id] = slot

    def add_control(self, control: ControlRegion) -> None:
        if control.id in self.controls:
            raise ValueError(f"duplicate control region: {control.id.wire}")
        if control.parent_id is not None and control.parent_id not in self.controls:
            raise ValueError(f"unknown parent control: {control.parent_id.wire}")
        self.controls[control.id] = control

    def children_of(self, definition: OperationDefinitionID) -> tuple[OperationDefinition, ...]:
        """Return direct nested definitions in insertion order."""
        if definition not in self.definitions:
            raise KeyError(f"unknown operation definition: {definition.wire}")
        return tuple(item for item in self.definitions.values()
                     if item.parent_id == definition)

    def descendants_of(self, definition: OperationDefinitionID) -> tuple[OperationDefinition, ...]:
        """Recursively expand a definition without merging child identities."""
        result: list[OperationDefinition] = []
        pending = list(self.children_of(definition))
        while pending:
            child = pending.pop(0)
            result.append(child)
            pending.extend(self.children_of(child.id))
        return tuple(result)

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        for definition in self.definitions.values():
            missing = set(definition.input_slots + definition.output_slots + definition.state_slots) - set(self.slots)
            errors.extend(f"definition {definition.id.wire} references unknown slot {slot}"
                          for slot in sorted(missing))
        for slot in self.slots.values():
            if slot.owner is not None and slot.owner not in self.definitions:
                errors.append(f"slot {slot.slot_id} references unknown owner")
        for control in self.controls.values():
            if control.parent_id is not None and control.parent_id not in self.controls:
                errors.append(f"control {control.id.wire} references unknown parent")
        return {"schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION,
                "valid": not errors, "errors": errors,
                "counts": {"definitions": len(self.definitions),
                            "slots": len(self.slots), "controls": len(self.controls)}}

    def assert_valid(self) -> dict[str, Any]:
        report = self.validate()
        if not report["valid"]:
            raise ValueError("invalid v2 SemanticGraph: " + "; ".join(report["errors"]))
        return report

    def to_dict(self) -> dict[str, Any]:
        self.assert_valid()
        return {
            "schema": self.SCHEMA,
            "schema_version": self.SCHEMA_VERSION,
            "definitions": [item.as_dict() for item in self.definitions.values()],
            "slots": [item.as_dict() for item in self.slots.values()],
            "controls": [item.as_dict() for item in self.controls.values()],
            "validation": self.validate(),
        }


__all__ = ["OperationKind", "ValueSlot", "OperationDefinition",
           "ControlRegion", "SemanticGraph"]
