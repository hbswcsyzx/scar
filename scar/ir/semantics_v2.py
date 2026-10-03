"""Typed, source-bound semantics overlay; structural validity is not AST proof.

Static values describe expression results, not runtime Tensor identities. Binding
epochs describe source definitions, not storage mutation. Exact reaching bindings
are deliberately restricted to a single straight-line block in G7.1. Call and
import records express syntax only; they never certify builtin dispatch, import
purity, object identity, or safe replacement. A separate source replay checker
must attest that these records actually match the fingerprinted source text.

Source fingerprints follow the frontend convention: SHA256 of decoded source
text encoded as UTF-8, rather than a claim about original file encoding bytes.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from enum import Enum
import json
import re
from typing import ClassVar

from .record_codec import decode, encode, loads
from .literals import LiteralKind, PythonLiteral
from .v2._validation import cycle_errors, mapping_errors, record_errors
from .v2.common import SourceReference
from .v2.ids import (
    BindingUseID,
    ModuleID,
    OperationDefinitionID,
    StaticBindingID,
    StaticValueID,
    ValueSlotID,
)
from .v2.semantic import SemanticGraph


class Opcode(str, Enum):
    LITERAL = "literal"
    READ = "read"
    ALIAS = "alias"
    BUILD_TUPLE = "build_tuple"
    BUILD_LIST = "build_list"
    BUILD_DICT = "build_dict"
    BUILD_SET = "build_set"
    POS = "pos"
    NEG = "neg"
    INVERT = "invert"
    NOT = "not"
    ADD = "add"
    SUB = "sub"
    MUL = "mul"
    TRUE_DIV = "true_div"
    FLOOR_DIV = "floor_div"
    MOD = "mod"
    POW = "pow"
    MATMUL = "matmul"
    LSHIFT = "lshift"
    RSHIFT = "rshift"
    BIT_AND = "bit_and"
    BIT_OR = "bit_or"
    BIT_XOR = "bit_xor"
    INDEX = "index"
    CALL = "call"
    ATTRIBUTE = "attribute"
    IMPORT = "import"
    RETURN = "return"
    OPAQUE = "opaque"


PythonOpcode = Opcode


class DispatchKind(str, Enum):
    BUILTIN = "builtin"
    BINDING = "binding"
    MODULE_EXPORT = "module_export"
    USER_DEFINED = "user_defined"
    UNRESOLVED = "unresolved"


class BindingStatus(str, Enum):
    EXACT = "exact"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class ImportForm(str, Enum):
    MODULE = "module"
    FROM = "from"


class BoundaryKind(str, Enum):
    IMPORT = "import"
    ATTRIBUTE = "attribute"
    INDEX = "index"
    CALL = "call"
    CONTROL = "control"
    REBIND = "rebind"
    OPAQUE = "opaque"


class SourceExecutionPrecondition(str, Enum):
    """Required contracts for this source abstraction, never accepted facts.

    These exclude hidden preexisting namespace objects/finalizers and mutation
    by signals, threads, callbacks or frame tracing between modeled operations.
    Later legality checking must discharge the applicable contracts; graph
    construction and a constant derivation do not discharge any of them.
    """
    FRESH_MODULE_NAMESPACE = "fresh_module_namespace"
    STANDARD_FUNCTION_LOCALS = "standard_function_locals"
    NO_EXTERNAL_NAMESPACE_MUTATION = "no_external_namespace_mutation"


def _nonnegative(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    path: str
    fingerprint: str
    encoding: str = "utf-8"
    python_version: str | None = None

    def __post_init__(self) -> None:
        if not self.path or not self.encoding:
            raise ValueError("source path and encoding are required")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.fingerprint):
            raise ValueError("source fingerprint must be canonical SHA256")


@dataclass(frozen=True, slots=True)
class OperandUse:
    role: str
    index: int
    value: StaticValueID

    def __post_init__(self) -> None:
        if not self.role:
            raise ValueError("operand role is required")
        _nonnegative(self.index, "operand index")


@dataclass(frozen=True, slots=True)
class ImportSpec:
    requested: str
    module: ModuleID | None = None
    symbol: str | None = None
    relative_level: int = 0
    form: ImportForm | None = None
    bound_name: str | None = None
    asname: str | None = None
    bound_module: ModuleID | None = None

    def __post_init__(self) -> None:
        _nonnegative(self.relative_level, "relative level")
        if not self.requested and not self.relative_level:
            raise ValueError("import requires a requested module or relative level")
        if self.symbol == "":
            raise ValueError("import symbol must be nonempty when present")
        expected = ImportForm.FROM if self.symbol is not None else ImportForm.MODULE
        if self.form is None:
            object.__setattr__(self, "form", expected)
        elif self.form is not expected:
            raise ValueError("import form and symbol disagree")
        if self.form is ImportForm.MODULE and self.relative_level:
            raise ValueError("module import cannot be relative")
        if self.bound_name == "" or self.asname == "":
            raise ValueError("bound name and alias must be nonempty when present")
        if self.form is ImportForm.FROM and self.bound_module is not None:
            raise ValueError("from import binds an export, not the module")


@dataclass(frozen=True, slots=True)
class OperationSemantics:
    operation: OperationDefinitionID
    scope: OperationDefinitionID
    block: str
    position: int
    opcode: Opcode
    operands: tuple[OperandUse, ...]
    result: StaticValueID | None
    source: SourceReference
    literal: PythonLiteral | None = None
    binding_use: BindingUseID | None = None
    attribute: str | None = None
    dispatch: DispatchKind = DispatchKind.UNRESOLVED
    callee: OperationDefinitionID | None = None
    import_spec: ImportSpec | None = None

    def __post_init__(self) -> None:
        if not self.block:
            raise ValueError("operation block is required")
        _nonnegative(self.position, "operation position")
        if (self.opcode is Opcode.LITERAL) != (self.literal is not None):
            raise ValueError("literal payload belongs exactly to LITERAL opcode")
        if (self.opcode is Opcode.READ) != (self.binding_use is not None):
            raise ValueError("binding use belongs exactly to READ opcode")
        if (self.opcode is Opcode.ATTRIBUTE) != (self.attribute is not None):
            raise ValueError("attribute name belongs exactly to ATTRIBUTE opcode")
        if self.attribute == "":
            raise ValueError("attribute name cannot be empty")
        if (self.opcode is Opcode.IMPORT) != (self.import_spec is not None):
            raise ValueError("import spec belongs exactly to IMPORT opcode")
        if self.callee is not None and self.opcode is not Opcode.CALL:
            raise ValueError("callee belongs only to CALL opcode")
        if len({(x.role, x.index) for x in self.operands}) != len(self.operands):
            raise ValueError("duplicate operand role/index")


@dataclass(frozen=True, slots=True)
class StaticValue:
    id: StaticValueID
    producer: OperationDefinitionID | None
    scope: OperationDefinitionID
    source: SourceReference
    external: bool = False

    def __post_init__(self) -> None:
        if self.external != (self.producer is None):
            raise ValueError("external values have no producer; produced values must name one")


@dataclass(frozen=True, slots=True)
class StaticBinding:
    id: StaticBindingID
    slot: ValueSlotID
    definition: OperationDefinitionID
    value: StaticValueID
    scope: OperationDefinitionID
    block: str
    position: int
    epoch: int
    source: SourceReference

    def __post_init__(self) -> None:
        if not self.block:
            raise ValueError("binding block is required")
        _nonnegative(self.position, "binding position")
        _nonnegative(self.epoch, "binding epoch")


@dataclass(frozen=True, slots=True)
class BindingUse:
    id: BindingUseID
    operation: OperationDefinitionID
    slot: ValueSlotID
    scope: OperationDefinitionID
    block: str
    position: int
    reaching: tuple[StaticBindingID, ...]
    status: BindingStatus
    source: SourceReference
    conditional_reaching: tuple[StaticBindingID, ...] = ()

    def __post_init__(self) -> None:
        if not self.block:
            raise ValueError("use block is required")
        _nonnegative(self.position, "use position")
        if len(set(self.reaching)) != len(self.reaching):
            raise ValueError("duplicate reaching binding")
        if self.status is BindingStatus.EXACT and len(self.reaching) != 1:
            raise ValueError("EXACT use requires one reaching binding")
        if self.status is BindingStatus.AMBIGUOUS and len(self.reaching) < 2:
            raise ValueError("AMBIGUOUS use requires at least two reaching bindings")
        if len(set(self.conditional_reaching)) != len(self.conditional_reaching):
            raise ValueError("duplicate conditional reaching binding")
        if self.status is BindingStatus.EXACT and self.conditional_reaching:
            raise ValueError("EXACT cannot carry conditional bindings")


@dataclass(frozen=True, slots=True)
class SemanticBoundary:
    """Potential invalidation; retaining a candidate is never proof it survived."""
    kind: BoundaryKind
    scope: OperationDefinitionID
    block: str
    position: int
    reason: str
    operation: OperationDefinitionID | None = None
    source: SourceReference | None = None

    def __post_init__(self) -> None:
        if not self.block or not self.reason:
            raise ValueError("boundary block and reason are required")
        _nonnegative(self.position, "boundary position")


@dataclass(frozen=True, slots=True)
class SemanticGap:
    reason: str
    operation: OperationDefinitionID | None = None
    use: BindingUseID | None = None
    source: SourceReference | None = None
    required_fact: str = ""

    def __post_init__(self) -> None:
        if not self.reason or not self.required_fact:
            raise ValueError("semantic gap must name reason and required fact")


@dataclass(slots=True)
class SourceSemanticsGraph:
    sources: dict[str, SourceSnapshot] = field(default_factory=dict)
    operations: dict[OperationDefinitionID, OperationSemantics] = field(default_factory=dict)
    values: dict[StaticValueID, StaticValue] = field(default_factory=dict)
    bindings: dict[StaticBindingID, StaticBinding] = field(default_factory=dict)
    uses: dict[BindingUseID, BindingUse] = field(default_factory=dict)
    gaps: tuple[SemanticGap, ...] = ()
    unmodeled_operations: tuple[OperationDefinitionID, ...] = ()
    required_preconditions: tuple[SourceExecutionPrecondition, ...] = tuple(SourceExecutionPrecondition)
    boundaries: tuple[SemanticBoundary, ...] = ()

    SCHEMA: ClassVar[str] = "scar.source-semantics.v2"
    SCHEMA_VERSION: ClassVar[int] = 2

    def validate(self, semantic: SemanticGraph | None = None) -> dict:
        errors = record_errors(self, SourceSemanticsGraph, "source_semantics")
        if errors:
            return self._report(errors, semantic is not None)
        if (len(self.required_preconditions) != len(SourceExecutionPrecondition)
                or set(self.required_preconditions) != set(SourceExecutionPrecondition)):
            errors.append("source abstraction requires the full fixed execution precondition set")
        groups = ((self.sources, str, SourceSnapshot, "sources", "path"),
                  (self.operations, OperationDefinitionID, OperationSemantics, "operations", "operation"),
                  (self.values, StaticValueID, StaticValue, "values", "id"),
                  (self.bindings, StaticBindingID, StaticBinding, "bindings", "id"),
                  (self.uses, BindingUseID, BindingUse, "uses", "id"))
        for mapping, key_type, record_type, label, key in groups:
            errors.extend(mapping_errors(mapping, key_type, record_type, label, key))
        if semantic is not None:
            if not isinstance(semantic, SemanticGraph):
                errors.append("semantic context must be SemanticGraph")
                return self._report(errors, False)
            semantic_report = semantic.validate()
            if not semantic_report["valid"]:
                errors.append("semantic context is invalid")
                return self._report(errors, True)

        def source(reference, label):
            snapshot = self.sources.get(reference.path)
            if snapshot is None or snapshot.fingerprint != reference.fingerprint:
                errors.append(f"{label}: source snapshot missing or fingerprint differs")
            if semantic is not None:
                atom = semantic.source_atoms.get(reference.atom_id)
                if atom is None or atom.reference != reference:
                    errors.append(f"{label}: source reference does not match semantic source atom")

        def definition(identifier, label):
            if semantic is not None and identifier not in semantic.definitions:
                errors.append(f"{label}: missing semantic operation {identifier}")

        def slot(identifier, label):
            if semantic is not None and identifier not in semantic.slots:
                errors.append(f"{label}: missing semantic slot {identifier}")

        arcs = []
        for op in self.operations.values():
            label = op.operation.wire
            source(op.source, label)
            definition(op.operation, label)
            definition(op.scope, label)
            if op.callee is not None:
                definition(op.callee, label)
            if semantic is not None and op.operation in semantic.definitions:
                original = semantic.definitions[op.operation]
                if original.source_atoms and op.source.atom_id not in original.source_atoms:
                    errors.append(f"{label}: source atom not owned by operation")
                if original.source_file is not None and original.source_file != op.source.path:
                    errors.append(f"{label}: operation source path mismatch")
            if (op.import_spec is not None and op.import_spec.module is not None
                    and semantic is not None and op.import_spec.module not in semantic.modules):
                errors.append(f"{label}: missing semantic imported module")
            if (op.import_spec is not None and op.import_spec.bound_module is not None
                    and semantic is not None and op.import_spec.bound_module not in semantic.modules):
                errors.append(f"{label}: missing semantic bound module")
            if op.result is not None:
                value = self.values.get(op.result)
                if value is None or value.producer != op.operation or value.scope != op.scope:
                    errors.append(f"{label}: result/producer/scope mismatch")
            for operand in op.operands:
                if operand.value not in self.values:
                    errors.append(f"{label}: missing operand value {operand.value}")
                if op.result is not None:
                    arcs.append((operand.value, op.result))
            if op.binding_use is not None:
                use = self.uses.get(op.binding_use)
                if use is None or use.operation != op.operation:
                    errors.append(f"{label}: missing or mismatched binding use")
        for value in self.values.values():
            source(value.source, value.id.wire)
            definition(value.scope, value.id.wire)
            if value.producer is not None:
                producer = self.operations.get(value.producer)
                if producer is None or producer.result != value.id or producer.source != value.source:
                    errors.append(f"{value.id}: producer/result/source mismatch")

        histories = {}
        epochs = set()
        for binding in self.bindings.values():
            label = binding.id.wire
            source(binding.source, label)
            definition(binding.definition, label)
            definition(binding.scope, label)
            slot(binding.slot, label)
            if binding.value not in self.values:
                errors.append(f"{label}: missing bound value")
            key = (binding.slot, binding.scope, binding.block)
            epoch_key = (*key, binding.epoch)
            if epoch_key in epochs:
                errors.append(f"{label}: duplicate binding epoch")
            epochs.add(epoch_key)
            histories.setdefault(key, []).append(binding)
            op = self.operations.get(binding.definition)
            if op is not None and (op.scope, op.block, op.position) != (binding.scope, binding.block, binding.position):
                errors.append(f"{label}: binding position differs from defining operation")
        history_positions = {}
        for key, bindings in histories.items():
            bindings.sort(key=lambda item: (item.position, item.epoch, item.id.wire))
            history_positions[key] = [item.position for item in bindings]
            if any(a.epoch >= b.epoch for a, b in zip(bindings, bindings[1:])):
                errors.append("binding epochs must increase with source position")
        uses_with_gap = {gap.use for gap in self.gaps if gap.use is not None}
        operations_with_gap = {gap.operation for gap in self.gaps if gap.operation is not None}
        unmodeled = set(self.unmodeled_operations)
        if len(unmodeled) != len(self.unmodeled_operations):
            errors.append("duplicate unmodeled operation")
        if unmodeled.intersection(self.operations):
            errors.append("modeled and unmodeled operations must be disjoint")
        for identifier in unmodeled:
            definition(identifier, "unmodeled operation")
            if identifier not in operations_with_gap:
                errors.append(f"{identifier}: unmodeled operation requires explicit semantic gap")
        for use in self.uses.values():
            label = use.id.wire
            source(use.source, label)
            definition(use.scope, label)
            slot(use.slot, label)
            op = self.operations.get(use.operation)
            if op is None or op.binding_use != use.id or (op.scope, op.block, op.position, op.source) != (use.scope, use.block, use.position, use.source):
                errors.append(f"{label}: use/operation location mismatch")
            for identifier in (*use.reaching, *use.conditional_reaching):
                binding = self.bindings.get(identifier)
                if binding is None:
                    errors.append(f"{label}: missing reaching binding")
                    continue
                if binding.slot != use.slot:
                    errors.append(f"{label}: reaching binding slot mismatch")
                if identifier in use.conditional_reaching:
                    if (binding.scope, binding.block) != (use.scope, use.block) or binding.position > use.position:
                        errors.append(f"{label}: conditional binding requires same-scope/block nonfuture definition")
                    key = (use.slot, use.scope, use.block)
                    count = bisect_right(history_positions.get(key, ()), use.position)
                    if not count or histories[key][count - 1].id != binding.id:
                        errors.append(f"{label}: conditional binding is not latest preceding definition")
                if use.status is BindingStatus.EXACT:
                    if (binding.scope, binding.block) != (use.scope, use.block) or binding.position > use.position:
                        errors.append(f"{label}: EXACT requires same-scope/block nonfuture binding")
                    key = (use.slot, use.scope, use.block)
                    history = histories.get(key, ())
                    count = bisect_right(history_positions.get(key, ()), use.position)
                    if not count or history[count - 1].id != binding.id:
                        errors.append(f"{label}: EXACT binding is not latest preceding definition")
                    if op is not None and op.result is not None:
                        arcs.append((binding.value, op.result))
            if use.status is not BindingStatus.EXACT and use.id not in uses_with_gap:
                errors.append(f"{label}: unresolved/ambiguous use requires explicit semantic gap")
        for op in self.operations.values():
            if op.opcode is Opcode.OPAQUE and op.operation not in operations_with_gap:
                errors.append(f"{op.operation}: OPAQUE operation requires explicit semantic gap")
        for gap in self.gaps:
            if gap.operation is not None and gap.operation not in self.operations and gap.operation not in unmodeled:
                errors.append("semantic gap references missing operation")
            if gap.use is not None and gap.use not in self.uses:
                errors.append("semantic gap references missing binding use")
            if gap.source is not None:
                source(gap.source, "semantic gap")
        boundary_keys = set()
        for boundary in self.boundaries:
            definition(boundary.scope, "semantic boundary")
            if boundary.operation is not None:
                definition(boundary.operation, "semantic boundary")
                op = self.operations.get(boundary.operation)
                if op is not None and boundary.source is not None and op.source != boundary.source:
                    errors.append("boundary operation scope/source mismatch")
            if boundary.source is not None:
                source(boundary.source, "semantic boundary")
            key = (boundary.scope, boundary.block, boundary.position)
            if key in boundary_keys:
                errors.append("duplicate semantic boundary position")
            boundary_keys.add(key)
        errors.extend(cycle_errors(arcs, "static value dependency"))
        return self._report(errors, semantic is not None)

    def _report(self, errors, semantic_checked):
        return {"valid": not errors, "errors": sorted(set(errors)),
                "semantic_references_checked": semantic_checked,
                "source_replay_checked": False,
                "counts": {name: len(getattr(self, name)) if isinstance(getattr(self, name), (dict, tuple)) else None
                           for name in ("sources", "operations", "values", "bindings", "uses", "gaps", "unmodeled_operations", "boundaries")}}

    def assert_valid(self, semantic: SemanticGraph | None = None) -> dict:
        result = self.validate(semantic)
        if not result["valid"]:
            raise ValueError("; ".join(result["errors"]))
        return result

    def to_dict(self) -> dict:
        self.assert_valid()
        result = {"schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION}
        for name in ("sources", "operations", "values", "bindings", "uses"):
            mapping = getattr(self, name)
            result[name] = [encode(mapping[key]) for key in sorted(mapping, key=str)]
        result["gaps"] = sorted((encode(gap) for gap in self.gaps),
                                key=lambda item: json.dumps(item, sort_keys=True))
        result["unmodeled_operations"] = [encode(item) for item in sorted(self.unmodeled_operations, key=str)]
        result["required_preconditions"] = sorted(item.value for item in self.required_preconditions)
        result["boundaries"] = [encode(item) for item in sorted(self.boundaries,
            key=lambda item: (item.scope.wire, item.block, item.position))]
        return result

    @classmethod
    def from_dict(cls, document: dict, semantic: SemanticGraph | None = None) -> SourceSemanticsGraph:
        names = ("sources", "operations", "values", "bindings", "uses", "gaps", "unmodeled_operations", "required_preconditions", "boundaries")
        if type(document) is dict and type(document.get("schema_version")) is int and document["schema_version"] == 1:
            old_names = set(names) - {"boundaries"}
            if set(document) != {"schema", "schema_version", *old_names} or document.get("schema") != cls.SCHEMA:
                raise ValueError("legacy source semantics document fields mismatch")
            # Decode the old record shape strictly before adding new syntax
            # fields; a migrated graph still needs AST replay to attest source.
            from copy import deepcopy
            document = deepcopy(document)
            for name in old_names:
                if type(document[name]) is not list:
                    raise ValueError(f"legacy {name} must be an array")
            for use in document["uses"]:
                if type(use) is not dict or set(use) != {"id", "operation", "slot", "scope", "block", "position", "reaching", "status", "source"}:
                    raise ValueError("legacy binding use fields mismatch")
                use["conditional_reaching"] = []
            for op in document["operations"]:
                spec = op.get("import_spec") if type(op) is dict else None
                if spec is not None:
                    if type(spec) is not dict or set(spec) != {"requested", "module", "symbol", "relative_level"}:
                        raise ValueError("legacy import spec fields mismatch")
                    spec.update(form="from" if spec["symbol"] is not None else "module",
                                bound_name=None, asname=None, bound_module=None)
            document.update(schema_version=cls.SCHEMA_VERSION, boundaries=[])
        if type(document) is not dict or set(document) != {"schema", "schema_version", *names}:
            raise ValueError("source semantics document fields mismatch")
        if document["schema"] != cls.SCHEMA or type(document["schema_version"]) is not int or document["schema_version"] != cls.SCHEMA_VERSION:
            raise ValueError("unsupported source semantics schema/version")
        result = cls()
        for name, record_type, key in (("sources", SourceSnapshot, "path"),
                                      ("operations", OperationSemantics, "operation"),
                                      ("values", StaticValue, "id"),
                                      ("bindings", StaticBinding, "id"),
                                      ("uses", BindingUse, "id")):
            if type(document[name]) is not list:
                raise ValueError(f"{name} must be an array")
            mapping = getattr(result, name)
            for entry in document[name]:
                record = decode(record_type, entry)
                identity = getattr(record, key)
                if identity in mapping:
                    raise ValueError(f"duplicate {name} identity")
                mapping[identity] = record
        result.gaps = decode(tuple[SemanticGap, ...], document["gaps"])
        result.unmodeled_operations = decode(tuple[OperationDefinitionID, ...], document["unmodeled_operations"])
        result.required_preconditions = decode(tuple[SourceExecutionPrecondition, ...], document["required_preconditions"])
        result.boundaries = decode(tuple[SemanticBoundary, ...], document["boundaries"])
        result.assert_valid(semantic)
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)

    @classmethod
    def from_json(cls, payload: str, semantic: SemanticGraph | None = None) -> SourceSemanticsGraph:
        return cls.from_dict(loads(payload), semantic)


StaticSemanticsGraph = SourceSemanticsGraph

__all__ = ["StaticValueID", "StaticBindingID", "BindingUseID", "LiteralKind",
           "PythonLiteral", "Opcode", "PythonOpcode", "DispatchKind", "BindingStatus", "SourceExecutionPrecondition",
           "SourceSnapshot", "OperandUse", "ImportSpec", "OperationSemantics", "StaticValue",
           "StaticBinding", "BindingUse", "SemanticGap", "SourceSemanticsGraph", "StaticSemanticsGraph",
           "ImportForm", "BoundaryKind", "SemanticBoundary"]
