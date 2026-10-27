"""Static class-body entry declarations and required-expansion records.

The records preserve one original ClassDef and its exact compiled lexical body.
They declare an entry interface; they do not claim that class construction,
metaclass preparation, namespace writes, or runtime class identity are known.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import dis
from types import CodeType

from scar.ir.program.ids import ControlScopeID, OperationID, RegionID
from scar.ir.program.model import ProgramGraph
from scar.ir.program.source import LoweringMetadata
from scar.ir.program.source_subjects import ClassFrameABI, SourceCompilationCodeRef
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID


class ClassEntryInputRole(str, Enum):
    DECORATOR = "DECORATOR"
    BASE = "BASE"
    METACLASS = "METACLASS"
    CLASS_KEYWORD = "CLASS_KEYWORD"
    CLASS_KEYWORD_EXPANSION = "CLASS_KEYWORD_EXPANSION"


class ClassNormalPayloadKind(str, Enum):
    CLASS_CELL = "CLASS_CELL"
    NONE_LITERAL = "NONE_LITERAL"


class ClassFrontierKind(str, Enum):
    BODY_REQUIRED_EXPANSION = "BODY_REQUIRED_EXPANSION"
    PARENT_CLASS_STATEMENT_UNCONNECTED = "PARENT_CLASS_STATEMENT_UNCONNECTED"
    PREPARED_NAMESPACE_UNCONNECTED = "PREPARED_NAMESPACE_UNCONNECTED"
    OUTER_CLOSURE_UNCONNECTED = "OUTER_CLOSURE_UNCONNECTED"
    METACLASS_SELECTION_AND_CALL_OPEN = "METACLASS_SELECTION_AND_CALL_OPEN"
    BASE_MRO_ENTRIES_OPEN = "BASE_MRO_ENTRIES_OPEN"
    CLASSCELL_ACCEPTANCE_AND_FILL_UNPROVEN = "CLASSCELL_ACCEPTANCE_AND_FILL_UNPROVEN"
    DESCRIPTOR_AND_SUBCLASS_HOOKS_OPEN = "DESCRIPTOR_AND_SUBCLASS_HOOKS_OPEN"
    DECORATOR_APPLICATION_OPEN = "DECORATOR_APPLICATION_OPEN"
    EFFECTS_OPEN = "EFFECTS_OPEN"


@dataclass(frozen=True, slots=True)
class ClassEntryInput:
    role: ClassEntryInputRole
    index: int
    evaluation_order: int
    source: SourceReference
    keyword: str | None = None

    def __post_init__(self):
        if type(self.role) is not ClassEntryInputRole:
            raise TypeError("class entry input requires a typed role")
        if type(self.index) is not int or self.index < 0:
            raise ValueError("class entry input role index must be nonnegative")
        if type(self.evaluation_order) is not int or self.evaluation_order < 0:
            raise ValueError("class entry input evaluation order must be nonnegative")
        if type(self.source) is not SourceReference:
            raise TypeError("class entry input requires the original SourceReference")
        self.source.__post_init__()
        if self.role in (ClassEntryInputRole.METACLASS, ClassEntryInputRole.CLASS_KEYWORD):
            if type(self.keyword) is not str or not self.keyword:
                raise ValueError("class keyword inputs must retain their exact keyword name")
        elif self.keyword is not None:
            raise ValueError("decorator and positional base inputs cannot carry keyword names")


@dataclass(frozen=True, slots=True)
class ClassBodyStatement:
    order: int
    kind: str
    source: SourceReference

    def __post_init__(self):
        if type(self.order) is not int or self.order < 0:
            raise ValueError("class body statement order must be nonnegative")
        if type(self.kind) is not str or not self.kind:
            raise ValueError("class body statement kind must be nonempty")
        if type(self.source) is not SourceReference:
            raise TypeError("class body statement requires an original source reference")
        self.source.__post_init__()


@dataclass(frozen=True, slots=True)
class ClassCompilerStage:
    """One compiler-owned class-cell protocol instruction, not runtime evidence."""

    role: str
    offset: int
    opcode: str
    operand: str

    def __post_init__(self):
        if any(type(value) is not str or not value for value in
               (self.role, self.opcode, self.operand)):
            raise ValueError("class compiler stage strings must be nonempty")
        if type(self.offset) is not int or self.offset < 0:
            raise ValueError("class compiler stage offset must be nonnegative")


@dataclass(frozen=True, slots=True)
class ClassEntryFrontier:
    kind: ClassFrontierKind
    detail: str
    source: SourceReference | None = None

    def __post_init__(self):
        if type(self.kind) is not ClassFrontierKind:
            raise TypeError("class frontier requires a typed kind")
        if type(self.detail) is not str or not self.detail.strip():
            raise ValueError("class frontier requires a concrete detail")
        if self.source is not None:
            if type(self.source) is not SourceReference:
                raise TypeError("class frontier source must be an original SourceReference")
            self.source.__post_init__()


@dataclass(frozen=True, slots=True)
class RequiredClassBodyExpansion:
    """Typed body boundary whose source statements remain unexpanded."""

    region: RegionID
    operation: OperationID
    class_source: SourceReference
    body_statements: tuple[ClassBodyStatement, ...]
    normal_payload: ClassNormalPayloadKind
    compiler_stages: tuple[ClassCompilerStage, ...]
    status: str = "REQUIRED"

    def __post_init__(self):
        if type(self.region) is not RegionID or type(self.operation) is not OperationID:
            raise TypeError("required class body expansion needs canonical region/operation IDs")
        if type(self.class_source) is not SourceReference:
            raise TypeError("required class body expansion needs original ClassDef source")
        self.class_source.__post_init__()
        if type(self.body_statements) is not tuple or any(
                type(row) is not ClassBodyStatement for row in self.body_statements):
            raise TypeError("class body expansion requires ordered source statement rows")
        if tuple(row.order for row in self.body_statements) != tuple(range(len(self.body_statements))):
            raise ValueError("class body source statements must retain a contiguous lexical order")
        if type(self.normal_payload) is not ClassNormalPayloadKind:
            raise TypeError("class body expansion requires its exact compiled normal-result kind")
        if type(self.compiler_stages) is not tuple or any(
                type(row) is not ClassCompilerStage for row in self.compiler_stages):
            raise TypeError("class body expansion requires typed compiler cell stages")
        if self.status != "REQUIRED":
            raise ValueError("static class body remains a required expansion")


@dataclass(frozen=True, slots=True)
class ClassEntryOverlay:
    """Source/cell declaration around an existing canonical ProgramGraph."""

    definition: OperationDefinitionID
    parent_definition: OperationDefinitionID | None
    source: SourceReference
    compilation: SourceCompilationCodeRef
    root_scope: ControlScopeID
    interface: ClassFrameABI
    inputs: tuple[ClassEntryInput, ...]
    required_expansion: RequiredClassBodyExpansion
    frontiers: tuple[ClassEntryFrontier, ...]
    operations_emitted: int
    status: str = "STATIC_CLASS_FRAME_WITH_REQUIRED_BODY_EXPANSION"

    def __post_init__(self):
        if type(self.definition) is not OperationDefinitionID:
            raise TypeError("class entry must retain the original SG ClassDef definition ID")
        if self.parent_definition is not None and type(self.parent_definition) is not OperationDefinitionID:
            raise TypeError("class lexical parent must be an existing OperationDefinitionID or None")
        if type(self.source) is not SourceReference:
            raise TypeError("class entry needs the exact original ClassDef SourceReference")
        self.source.__post_init__()
        if type(self.compilation) is not SourceCompilationCodeRef:
            raise TypeError("class entry needs source-compilation code reference")
        self.compilation.__post_init__()
        if self.compilation.source != self.source or self.compilation.definition != self.definition:
            raise ValueError("class compilation reference differs from the original class definition")
        if type(self.root_scope) is not ControlScopeID:
            raise TypeError("class entry needs its canonical frame root scope")
        if type(self.interface) is not ClassFrameABI:
            raise TypeError("class entry needs the distinct ClassFrameABI")
        self.interface.__post_init__()
        if type(self.inputs) is not tuple or any(type(row) is not ClassEntryInput for row in self.inputs):
            raise TypeError("class entry inputs must be exact ordered source rows")
        orders = tuple(row.evaluation_order for row in self.inputs)
        if orders != tuple(range(len(self.inputs))):
            raise ValueError("class header inputs must retain complete evaluation order")
        if type(self.required_expansion) is not RequiredClassBodyExpansion:
            raise TypeError("class entry needs one typed required-expansion boundary")
        if self.required_expansion.class_source != self.source:
            raise ValueError("class expansion source differs from original ClassDef")
        if type(self.frontiers) is not tuple or any(type(row) is not ClassEntryFrontier for row in self.frontiers):
            raise TypeError("class entry frontiers must be typed records")
        if type(self.operations_emitted) is not int or self.operations_emitted <= 0:
            raise ValueError("class entry operation count must be positive")
        if self.status != "STATIC_CLASS_FRAME_WITH_REQUIRED_BODY_EXPANSION":
            raise ValueError("class entry cannot claim full body construction")


@dataclass(frozen=True, slots=True)
class ClassEntryResult:
    graph: ProgramGraph
    metadata: LoweringMetadata
    overlay: ClassEntryOverlay
    operations_emitted: int

    def __post_init__(self):
        if type(self.graph) is not ProgramGraph or type(self.metadata) is not LoweringMetadata:
            raise TypeError("class entry result needs canonical graph and source metadata")
        if type(self.overlay) is not ClassEntryOverlay:
            raise TypeError("class entry result needs a typed source overlay")
        if type(self.operations_emitted) is not int or self.operations_emitted != len(self.graph.operations):
            raise ValueError("class entry operation count differs from its canonical graph")
        if self.operations_emitted != self.overlay.operations_emitted:
            raise ValueError("class entry operation count differs from its overlay")


CLASS_ENTRY_RECORD_TAGS = {
    ClassEntryInput: ("class_record", "CLASS_ENTRY_INPUT"),
    ClassBodyStatement: ("class_record", "CLASS_BODY_STATEMENT"),
    ClassCompilerStage: ("class_record", "CLASS_COMPILER_STAGE"),
    ClassEntryFrontier: ("class_record", "CLASS_ENTRY_FRONTIER"),
    RequiredClassBodyExpansion: ("class_record", "REQUIRED_CLASS_BODY_EXPANSION"),
    ClassEntryOverlay: ("class_record", "STATIC_CLASS_ENTRY_OVERLAY"),
}


def compiler_cell_protocol(code: CodeType):
    """Return the exact CPython class-cell stages and ordinary normal payload.

    This is a compiler-layout projection. It runs ``dis`` on a source-compiled
    CodeType; it never executes the body or establishes a parent construction.
    Only the generated class-cell protocol is recorded; body bytecode stays in
    the required-expansion frontier.
    """
    if type(code) is not CodeType:
        raise TypeError("class-cell protocol requires an exact compiled CodeType")
    instructions = tuple(dis.get_instructions(code, adaptive=False, show_caches=False))
    stages = []

    if "__class__" in code.co_cellvars:
        normal_sequences = [index for index in range(max(0, len(instructions) - 3))
            if (instructions[index].opname == "LOAD_FAST_BORROW"
                and instructions[index].argval == "__class__"
                and instructions[index + 1].opname == "COPY"
                and instructions[index + 1].argval == 1
                and instructions[index + 2].opname == "STORE_NAME"
                and instructions[index + 2].argval == "__classcell__"
                and instructions[index + 3].opname == "RETURN_VALUE")]
        if not normal_sequences:
            raise ValueError("source-compiled class code has no __class__-cell normal return")
        normal_return_indices = {index + 3 for index in normal_sequences}
    else:
        normal_sequences = [index for index in range(max(0, len(instructions) - 1))
            if (instructions[index].opname == "LOAD_CONST"
                and instructions[index].argval is None
                and instructions[index + 1].opname == "RETURN_VALUE")]
        if not normal_sequences:
            raise ValueError("source-compiled class code has no implicit None normal return")
        normal_return_indices = {index + 1 for index in normal_sequences}
    if normal_return_indices != {index for index, instruction in enumerate(instructions)
                                 if instruction.opname == "RETURN_VALUE"}:
        raise ValueError("class code has an unrecognized normal-return payload path")

    def operand(instruction):
        return instruction.argrepr or (str(instruction.arg) if instruction.arg is not None else "-")

    for index, instruction in enumerate(instructions):
        role = None
        if instruction.opname == "MAKE_CELL":
            role = {"__class__": "MAKE_CLASS_CELL",
                    "__classdict__": "MAKE_CLASS_NAMESPACE_CELL"}.get(
                        instruction.argval, "MAKE_LOCAL_CELL")
        elif instruction.opname == "LOAD_LOCALS" and "__classdict__" in code.co_cellvars:
            role = "LOAD_CLASS_NAMESPACE_MAPPING"
        elif instruction.opname == "STORE_DEREF" and instruction.argval == "__classdict__":
            role = "BIND_CLASS_NAMESPACE_CELL"
        elif instruction.opname == "LOAD_FAST_BORROW" and instruction.argval == "__classdict__":
            role = "READ_CLASS_NAMESPACE_CELL"
        elif instruction.opname == "STORE_NAME" and instruction.argval == "__classdictcell__":
            role = "EXPORT_CLASS_NAMESPACE_CELL"
        elif instruction.opname == "LOAD_FAST_BORROW" and instruction.argval == "__class__":
            role = "READ_CLASS_OBJECT_CELL"
        elif instruction.opname == "STORE_NAME" and instruction.argval == "__classcell__":
            role = "EXPORT_CLASS_OBJECT_CELL"
        elif (index + 1 in normal_return_indices and instruction.opname == "LOAD_CONST"
              and instruction.argval is None and "__class__" not in code.co_cellvars):
            role = "LOAD_NONE_NORMAL_RESULT"
        elif index in normal_return_indices and instruction.opname == "RETURN_VALUE":
            role = ("RETURN_CLASS_OBJECT_CELL" if "__class__" in code.co_cellvars
                    else "RETURN_NONE")
        if role is not None:
            stages.append(ClassCompilerStage(role, instruction.offset,
                                             instruction.opname, operand(instruction)))

    def exact_pair(left_op, left_arg, right_op, right_arg, detail):
        found = []
        for index, instruction in enumerate(instructions[:-1]):
            next_instruction = instructions[index + 1]
            if (instruction.opname == left_op and instruction.argval == left_arg
                    and next_instruction.opname == right_op and next_instruction.argval == right_arg):
                found.append(index)
        if len(found) != 1:
            raise ValueError("source-compiled class code has no unique " + detail + " protocol")
        return found[0]

    if "__classdict__" in code.co_cellvars:
        bind = exact_pair("LOAD_LOCALS", None, "STORE_DEREF", "__classdict__",
                          "class namespace-cell binding")
        export = exact_pair("LOAD_FAST_BORROW", "__classdict__", "STORE_NAME", "__classdictcell__",
                            "class namespace-cell export")
        if bind >= export:
            raise ValueError("class namespace cell is exported before its compiler binding")
    elif any(stage.role.startswith("CLASS_NAMESPACE") or stage.role == "EXPORT_CLASS_NAMESPACE_CELL"
             for stage in stages):
        raise ValueError("class namespace-cell stages disagree with co_cellvars")

    if "__class__" in code.co_cellvars:
        if not any(instruction.opname == "MAKE_CELL" and instruction.argval == "__class__"
                   for instruction in instructions):
            raise ValueError("class object-cell is absent from compiler entry initialization")
    if "__classdict__" in code.co_cellvars and not any(
            instruction.opname == "MAKE_CELL" and instruction.argval == "__classdict__"
            for instruction in instructions):
        raise ValueError("class namespace cell is absent from compiler entry initialization")
    return tuple(stages), (ClassNormalPayloadKind.CLASS_CELL if "__class__" in code.co_cellvars
                           else ClassNormalPayloadKind.NONE_LITERAL)


def encode_class_entry_overlay(value: ClassEntryOverlay) -> dict:
    from scar.ir.program.source_subjects import CLASS_FRAME_ABI_RECORD_TAGS
    from scar.ir.record_codec import encode
    return encode(value, record_tags={**CLASS_FRAME_ABI_RECORD_TAGS,
                                      **CLASS_ENTRY_RECORD_TAGS})


def decode_class_entry_overlay(value) -> ClassEntryOverlay:
    from scar.ir.program.source_subjects import CLASS_FRAME_ABI_RECORD_TAGS
    from scar.ir.record_codec import decode
    return decode(ClassEntryOverlay, value,
                  record_tags={**CLASS_FRAME_ABI_RECORD_TAGS, **CLASS_ENTRY_RECORD_TAGS})


def validate_class_entry_core(overlay: ClassEntryOverlay, graph: ProgramGraph, metadata) -> None:
    """Check that a saved class overlay names its exact canonical core ports.

    This is a structural join only. It validates the typed overlay, graph and
    source links already supplied by the caller; it does not replay source
    compilation or revalidate every source mapping.
    """
    from scar.ir.program.control import ControlScopeKind
    from scar.ir.program.model import (
        BlockArgument, CompletionResult, CompletionSignature, ExitKind,
        ReferenceValue, StateVersionValue, TerminatorKind, ValueKind, ValueType,
    )
    from scar.ir.program.source import LoweringMetadata, OperationSource
    from scar.ir.program.source_subjects import FrameKind, SourceCompilationFrameRoot
    from scar.ir.semantics_v2 import Opcode

    def need(condition, detail):
        if not condition:
            raise ValueError("class entry/core mismatch: " + detail)

    need(type(overlay) is ClassEntryOverlay and type(graph) is ProgramGraph
         and type(metadata) is LoweringMetadata,
         "expected typed class overlay, ProgramGraph and LoweringMetadata")
    overlay.__post_init__()
    need(metadata.entry == overlay.definition.wire,
         "metadata entry is not the original class OperationDefinitionID")
    need(metadata.source.path == overlay.source.path
         and metadata.source.fingerprint == overlay.source.fingerprint,
         "metadata source snapshot differs from the original ClassDef source")
    need(overlay.required_expansion.status == "REQUIRED"
         and overlay.status == "STATIC_CLASS_FRAME_WITH_REQUIRED_BODY_EXPANSION",
         "class entry does not retain required body expansion status")
    need(overlay.required_expansion.region == graph.root,
         "required class body region is not the graph root")

    roots = graph.frame_roots
    need(len(roots) == 1 and type(roots[0]) is SourceCompilationFrameRoot
         and roots[0].kind is FrameKind.CLASS
         and roots[0].scope == overlay.root_scope
         and roots[0].entry == overlay.interface
         and roots[0].code == overlay.compilation,
         "CLASS frame root/ABI/scope differs from the overlay")
    scopes = [scope for scope in graph.control_scopes if scope.id == overlay.root_scope]
    need(len(scopes) == 1 and scopes[0].kind is ControlScopeKind.FRAME
         and scopes[0].region == graph.root and scopes[0].source == overlay.source,
         "CLASS frame scope does not retain the original ClassDef source")

    operations = [operation for operation in graph.operations
                  if operation.id == overlay.required_expansion.operation]
    need(len(operations) == 1, "required class body operation is absent or duplicated")
    body = operations[0]
    need(body.label == "required-class-body-expansion"
         and body.terminator is not None and body.terminator.kind is TerminatorKind.INVOKE
         and body.callee is None and body.effects_complete is False,
         "required class body is not the incomplete INVOKE boundary")
    world = next((value for value in graph.values
                  if value.id == overlay.interface.mapping.world
                  and isinstance(value, StateVersionValue)), None)
    need(world is not None, "class entry has no canonical StateVersion world port")
    world_type = ValueType(ValueKind.STATE, location=world.location)
    expected_completions = (
        CompletionSignature(ExitKind.NORMAL, (ValueType(ValueKind.REFERENCE), world_type)),
        CompletionSignature(ExitKind.RAISE, (ValueType(ValueKind.REFERENCE),
            ValueType(ValueKind.REFERENCE), world_type)),
    )
    need(body.completions == expected_completions,
         "required body lacks typed normal object/world and raise exception/traceback/world ports")
    successors = body.terminator.successors
    by_kind = {row.kind: row for row in successors}
    need(len(successors) == 2 and set(by_kind) == {ExitKind.NORMAL, ExitKind.RAISE},
         "required body must retain exactly normal and raise successors")
    need(by_kind[ExitKind.NORMAL].arguments == (CompletionResult(0), CompletionResult(1))
         and by_kind[ExitKind.RAISE].arguments == (CompletionResult(0), CompletionResult(1), CompletionResult(2)),
         "normal/raise successor ports differ from their completion signatures")
    region = next((row for row in graph.regions if row.id == graph.root), None)
    blocks = {} if region is None else {block.id: block for block in region.blocks}
    normal_block = blocks.get(by_kind[ExitKind.NORMAL].block)
    raise_block = blocks.get(by_kind[ExitKind.RAISE].block)
    need(normal_block is not None and len(normal_block.arguments) == 2
         and raise_block is not None and len(raise_block.arguments) == 3,
         "normal/raise destinations do not retain all completion ports")
    values = {value.id: value for value in graph.values}
    normal_payload = values.get(normal_block.arguments[0])
    need(type(normal_payload) is ReferenceValue
         and normal_payload.origin == BlockArgument(normal_block.id, 0),
         "normal Python payload is not an opaque ReferenceValue completion port")
    normal_world = values.get(normal_block.arguments[1])
    need(type(normal_world) is StateVersionValue
         and normal_world.origin == BlockArgument(normal_block.id, 1)
         and normal_world.location == world.location,
         "normal completion does not retain the class frame world port")
    if overlay.required_expansion.normal_payload is ClassNormalPayloadKind.CLASS_CELL:
        roles = [stage.role for stage in overlay.required_expansion.compiler_stages]
        need("__class__" in overlay.interface.co_cellvars
             and roles.count("MAKE_CLASS_CELL") == 1
             and roles.count("READ_CLASS_OBJECT_CELL") >= roles.count("EXPORT_CLASS_OBJECT_CELL")
             == roles.count("RETURN_CLASS_OBJECT_CELL") >= 1,
             "CLASS_CELL return mode conflicts with compiler cell/stage declarations")
    else:
        roles = [stage.role for stage in overlay.required_expansion.compiler_stages]
        need("__class__" not in overlay.interface.co_cellvars
             and roles.count("LOAD_NONE_NORMAL_RESULT") == roles.count("RETURN_NONE") >= 1,
             "NONE_LITERAL return mode lacks the compiler-checked None reference constraint")
    raise_values = [values.get(identity) for identity in raise_block.arguments]
    need(isinstance(raise_values[0], ReferenceValue)
         and isinstance(raise_values[1], ReferenceValue)
         and raise_values[0].origin == BlockArgument(raise_block.id, 0)
         and raise_values[1].origin == BlockArgument(raise_block.id, 1)
         and isinstance(raise_values[2], StateVersionValue)
         and raise_values[2].origin == BlockArgument(raise_block.id, 2)
         and raise_values[2].location == world.location,
         "raise destination ports are not exception/traceback/world values")

    links = [link for link in metadata.operation_links if link.operation == body.id]
    need(len(links) == 1 and type(links[0]) is OperationSource
         and links[0].source == overlay.source
         and links[0].semantic_operation == overlay.definition
         and links[0].opcode is Opcode.OPAQUE,
         "required body does not link uniquely to the original opaque ClassDef operation")


__all__ = ["ClassEntryInputRole", "ClassNormalPayloadKind", "ClassFrontierKind",
           "ClassEntryInput", "ClassBodyStatement", "ClassCompilerStage", "ClassEntryFrontier",
           "RequiredClassBodyExpansion", "ClassEntryOverlay", "ClassEntryResult",
           "CLASS_ENTRY_RECORD_TAGS", "compiler_cell_protocol",
           "encode_class_entry_overlay", "decode_class_entry_overlay",
           "validate_class_entry_core"]
