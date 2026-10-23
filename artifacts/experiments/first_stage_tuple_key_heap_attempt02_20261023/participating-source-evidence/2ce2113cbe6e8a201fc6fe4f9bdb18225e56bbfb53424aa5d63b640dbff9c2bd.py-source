"""Additional source/owner checks for the two heap store protocols.

Core validation owns use typing/CFG; the environment validator owns the
normal/raise state signature. Exact source evaluation is checked by replay.
"""
import ast

from scar.ir.program.state_addresses import (
    AddressCoverage, AddressEffect, Element, InvokeStateOperand, ObjectField, ReferenceOwner,
)
from scar.ir.program.state_modes import AccessMode
from scar.ir.program.structured import PythonProtocolKind as Kind
from scar.ir.semantics_v2 import Opcode


def validate_heap_store(operation, kind, link, row, semantic):
    definition = semantic.definitions.get(link.semantic_operation)
    atom = semantic.source_atoms.get(link.source.atom_id)
    attribute = kind is Kind.STORE_ATTRIBUTE
    expected_kind = "Attribute" if attribute else "Subscript"
    if (definition is None or atom is None or atom.kind != expected_kind
            or definition.metadata.get("role") != "binding"
            or definition.code_id != link.source.atom_id.wire
            or link.opcode is not Opcode.OPAQUE
            or not definition.label.startswith("bind ")):
        raise ValueError("heap store must reference its exact SG assignment target")
    target = ast.parse(definition.label[5:], mode="eval").body
    if attribute:
        if not isinstance(target, ast.Attribute) or len(operation.uses) != 3:
            raise ValueError("attribute store needs its owner, assigned reference and world")
        selector = ObjectField(target.attr)
    else:
        if (not isinstance(target, ast.Subscript) or isinstance(target.slice, ast.Slice)
                or len(operation.uses) != 4):
            raise ValueError("subscript store needs its owner, key, assigned reference and world")
        selector = Element(operation.uses[1].id)
    effect = AddressEffect(ReferenceOwner(operation.uses[0].id), (selector,), AccessMode.WRITE)
    if (row is None or row.site != InvokeStateOperand(operation.id, operation.uses[-1].id)
            or row.coverage is not AddressCoverage.PARTIAL or row.protocol is not None
            or row.effects != (effect,)):
        raise ValueError("heap store address must retain its exact owner/key/world Uses")
