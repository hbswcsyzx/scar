"""Evidence-backed mappings between semantic definitions and runtime records."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .common import EvidenceClaim
from ._validation import mapping_errors
from .ids import (
    CorrespondenceID,
    OperationDefinitionID,
    OperationInstanceID,
    SourceAtomID,
    ValueSlotID,
    ValueVersionID,
)


class CorrespondenceKind(str, Enum):
    DEFINITION_INSTANCE = "definition_instance"
    SOURCE_INSTANCE = "source_instance"
    SLOT_VERSION = "slot_version"


@dataclass(frozen=True, slots=True)
class CorrespondenceRecord:
    id: CorrespondenceID
    kind: CorrespondenceKind
    definition: OperationDefinitionID | None = None
    instance: OperationInstanceID | None = None
    source_atom: SourceAtomID | None = None
    value_slot: ValueSlotID | None = None
    value_version: ValueVersionID | None = None
    evidence: EvidenceClaim | None = None
    ambiguous: bool = False

    def __post_init__(self) -> None:
        if self.evidence is None:
            raise ValueError("correspondence requires evidence")
        if self.kind is CorrespondenceKind.DEFINITION_INSTANCE:
            if self.definition is None or self.instance is None:
                raise ValueError("definition-instance correspondence needs both endpoints")
        elif self.kind is CorrespondenceKind.SOURCE_INSTANCE:
            if self.source_atom is None or self.instance is None:
                raise ValueError("source-instance correspondence needs both endpoints")
        elif self.kind is CorrespondenceKind.SLOT_VERSION:
            if self.value_slot is None or self.value_version is None:
                raise ValueError("slot-version correspondence needs both endpoints")
        allowed = {
            CorrespondenceKind.DEFINITION_INSTANCE: {"definition", "instance"},
            CorrespondenceKind.SOURCE_INSTANCE: {"source_atom", "instance"},
            CorrespondenceKind.SLOT_VERSION: {"value_slot", "value_version"},
        }[self.kind]
        for name in ("definition", "instance", "source_atom", "value_slot", "value_version"):
            if name not in allowed and getattr(self, name) is not None:
                raise ValueError(f"{name} is not an endpoint of {self.kind.value}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.as_dict(), "kind": self.kind.value,
            "definition": self.definition.as_dict() if self.definition else None,
            "instance": self.instance.as_dict() if self.instance else None,
            "source_atom": self.source_atom.as_dict() if self.source_atom else None,
            "value_slot": self.value_slot.as_dict() if self.value_slot else None,
            "value_version": self.value_version.as_dict() if self.value_version else None,
            "evidence": self.evidence.as_dict(), "ambiguous": self.ambiguous,
        }


class CorrespondenceGraph:
    """Append-only mapping claims; ambiguity is represented, never overwritten."""

    SCHEMA = "scar.ir.v2.correspondence"
    SCHEMA_VERSION = 1

    def __init__(self) -> None:
        self.records: dict[CorrespondenceID, CorrespondenceRecord] = {}

    def add(self, record: CorrespondenceRecord) -> None:
        if record.id in self.records:
            raise ValueError(f"duplicate correspondence: {record.id.wire}")
        self.records[record.id] = record

    def validate_references(self, semantic, evidence, values) -> list[str]:
        errors: list[str] = []
        for record in self.records.values():
            if record.definition is not None and record.definition not in semantic.definitions:
                errors.append(f"{record.id.wire} references unknown definition")
            if record.instance is not None and record.instance not in evidence.instances:
                errors.append(f"{record.id.wire} references unknown instance")
            if record.source_atom is not None and record.source_atom not in semantic.source_atoms:
                errors.append(f"{record.id.wire} references unknown source atom")
            if record.value_slot is not None and record.value_slot not in semantic.slots:
                errors.append(f"{record.id.wire} references unknown value slot")
            if record.value_version is not None and record.value_version not in values.versions:
                errors.append(f"{record.id.wire} references unknown value version")
        return errors

    def validate(self) -> dict[str, Any]:
        errors = mapping_errors(self.records, CorrespondenceID, CorrespondenceRecord,
                                "correspondence.records")
        return {"schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION,
                "valid": not errors, "errors": errors,
                "counts": {"records": len(self.records)}}

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION,
                "records": [self.records[key].as_dict() for key in sorted(
                    self.records, key=lambda item: item.wire)],
                "validation": self.validate()}


__all__ = ["CorrespondenceGraph", "CorrespondenceKind", "CorrespondenceRecord"]
