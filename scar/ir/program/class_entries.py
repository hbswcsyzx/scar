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

from scar.ir.program.ids import ControlScopeID, OperationID, RegionID, ValueID, UseID
from scar.ir.program.model import ProgramGraph
from scar.ir.program.source import LoweringMetadata
from scar.ir.program.frames import FrameRules
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
class ClassSuiteProtocol:
    operation: OperationID
    kind: str
    source: SourceReference
    offset: int

    def __post_init__(self):
        if type(self.operation) is not OperationID or type(self.source) is not SourceReference:
            raise TypeError('class suite protocol requires original core/source endpoints')
        kinds={'FRAME_ENTER','FRAME_EXIT_NORMAL','FRAME_EXIT_EXCEPTION','FRAME_DISCARD',
               'READ_CODE_CONSTANT','MAKE_CELL','LOAD_DEREF','LOAD_FROM_DICT_OR_DEREF','STORE_CELL',
               'LOAD_NAME_314','LOAD_GLOBAL','STORE_NAME_314','STORE_GLOBAL','DELETE_NAME',
               'BUILD_TUPLE','BUILD_LIST','BUILD_SET','BUILD_MAP','MAKE_FUNCTION_314',
               'SET_FUNCTION_ATTRIBUTE','LOAD_ATTRIBUTE','CALL','APPLY_DECORATOR_314',
               'LOAD_METHOD_314','CALL_METHOD_314',
               'BINARY_OP','UNARY_NEGATIVE','UNARY_INVERT','UNARY_NOT','REQUIRED_CLASS_CONTINUATION'}
        if type(self.kind) is not str or self.kind not in kinds or type(self.offset) is not int or self.offset < -1:
            raise ValueError('class suite protocol kind/compiler offset invalid')


@dataclass(frozen=True, slots=True)
class ClassSuiteInstruction:
    offset: int
    opcode: str
    argument: int | None
    positions: tuple[int | None, ...]
    source: SourceReference
    operation: OperationID | None
    stack_before: tuple[ValueID | None, ...]
    stack_after: tuple[ValueID | None, ...]

    def __post_init__(self):
        if type(self.offset)is not int or self.offset<0 or type(self.opcode)is not str or not self.opcode:
            raise ValueError('class compiler witness needs an exact offset/opcode')
        if self.argument is not None and (type(self.argument)is not int or self.argument<0):
            raise ValueError('class compiler argument invalid')
        if type(self.positions)is not tuple or len(self.positions)!=4 or any(x is not None and type(x)is not int for x in self.positions):
            raise ValueError('class compiler witness must retain its actual position tuple')
        if type(self.source)is not SourceReference or self.operation is not None and type(self.operation)is not OperationID:
            raise TypeError('class compiler witness source/core endpoint invalid')
        for row in (self.stack_before,self.stack_after):
            if type(row)is not tuple or any(x is not None and type(x)is not ValueID for x in row):
                raise TypeError('class compiler stack must contain original SSA references or NULL marker')


@dataclass(frozen=True, slots=True)
class ClassSuiteCell:
    name: str
    ordinal: int
    reference: ValueID
    operation: OperationID

    def __post_init__(self):
        if type(self.name)is not str or not self.name or type(self.ordinal)is not int or self.ordinal<0:
            raise ValueError('class own cell needs its compiler name/ordinal')
        if type(self.reference)is not ValueID or type(self.operation)is not OperationID:
            raise TypeError('class own cell must refer to an actual allocation result')


@dataclass(frozen=True, slots=True)
class ClassSuiteConstant:
    operation: OperationID
    reference: ValueID
    constant_path: tuple[int, ...]

    def __post_init__(self):
        if type(self.operation)is not OperationID or type(self.reference)is not ValueID:
            raise TypeError('class constant must refer to original core endpoints')
        if type(self.constant_path)is not tuple or not self.constant_path or any(type(n)is not int or n<0 for n in self.constant_path):
            raise ValueError('class constant needs its exact compiler constant path')


@dataclass(frozen=True, slots=True)
class ClassSuiteFactory:
    operation: OperationID
    reference: ValueID
    code_reference: ValueID
    constant_path: tuple[int, ...]
    definition: OperationDefinitionID | None
    source: SourceReference
    free_names: tuple[str, ...]

    def __post_init__(self):
        if type(self.operation)is not OperationID or any(type(v)is not ValueID for v in (self.reference,self.code_reference)):
            raise TypeError('class factory needs its actual core/result/code-reference endpoints')
        if self.definition is not None and type(self.definition)is not OperationDefinitionID:
            raise TypeError('factory body reference must be an original definition or explicitly unassociated')
        if type(self.source)is not SourceReference or type(self.free_names)is not tuple or any(type(n)is not str for n in self.free_names):
            raise TypeError('class factory source/free-name table invalid')
        if type(self.constant_path)is not tuple or not self.constant_path or any(type(n)is not int or n<0 for n in self.constant_path):
            raise ValueError('class factory must keep original code constant path')


@dataclass(frozen=True, slots=True)
class ClassSuiteResidual:
    operation: OperationID
    first_offset: int
    statements: tuple[ClassBodyStatement, ...]
    stack_inputs: tuple[ValueID | None, ...]
    reason: str
    status: str = 'REQUIRED_COMPILER_CONTINUATION'

    def __post_init__(self):
        if type(self.operation)is not OperationID or type(self.first_offset)is not int or self.first_offset<0:
            raise ValueError('class residual must identify its exact compiler continuation')
        if type(self.statements)is not tuple or any(type(x)is not ClassBodyStatement for x in self.statements):
            raise TypeError('class residual requires original source statement rows')
        if type(self.stack_inputs)is not tuple or any(x is not None and type(x)is not ValueID for x in self.stack_inputs):
            raise TypeError('class residual must carry the actual partial evaluation stack')
        if type(self.reason)is not str or not self.reason or self.status!='REQUIRED_COMPILER_CONTINUATION':
            raise ValueError('class residual cannot discharge its continuation obligation')


@dataclass(frozen=True, slots=True)
class ClassSuiteOverlay:
    definition: OperationDefinitionID
    parent_definition: OperationDefinitionID | None
    source: SourceReference
    compilation: SourceCompilationCodeRef
    root_scope: ControlScopeID
    interface: ClassFrameABI
    inputs: tuple[ClassEntryInput, ...]
    normal_payload: ClassNormalPayloadKind
    statements: tuple[ClassBodyStatement, ...]
    instructions: tuple[ClassSuiteInstruction, ...]
    protocols: tuple[ClassSuiteProtocol, ...]
    cells: tuple[ClassSuiteCell, ...]
    constants: tuple[ClassSuiteConstant, ...]
    factories: tuple[ClassSuiteFactory, ...]
    remaining: ClassSuiteResidual | None
    frontiers: tuple[ClassEntryFrontier, ...]
    operations_emitted: int
    frame_rules: FrameRules = FrameRules()
    profile: str = 'STATIC_CLASS_SUITE_314_V1'
    status: str = 'CLASS_SUITE_TOPOLOGY_WITH_OPEN_EFFECTS'

    def __post_init__(self):
        if (type(self.definition) is not OperationDefinitionID or type(self.source) is not SourceReference
                or type(self.compilation) is not SourceCompilationCodeRef
                or self.compilation.definition != self.definition or self.compilation.source != self.source
                or type(self.interface) is not ClassFrameABI or type(self.root_scope) is not ControlScopeID):
            raise TypeError('class suite requires its original source, compiler and class ABI')
        for rows,kind in ((self.inputs,ClassEntryInput),(self.statements,ClassBodyStatement),
                (self.instructions,ClassSuiteInstruction),(self.protocols,ClassSuiteProtocol),
                (self.cells,ClassSuiteCell),(self.constants,ClassSuiteConstant),
                (self.factories,ClassSuiteFactory),(self.frontiers,ClassEntryFrontier)):
            if type(rows) is not tuple or any(type(row) is not kind for row in rows):
                raise TypeError('class suite ordered record table has invalid types')
        if type(self.normal_payload) is not ClassNormalPayloadKind:
            raise TypeError('class suite must preserve its Python-reference return mode')
        if self.remaining is not None and type(self.remaining) is not ClassSuiteResidual:
            raise TypeError('class suite residual must be a typed exact continuation')
        expected=('STATIC_CLASS_SUITE_METHOD_314_V1' if type(self)is ClassSuiteMethodOverlay else 'STATIC_CLASS_SUITE_314_V1')
        if self.profile != expected or self.status != 'CLASS_SUITE_TOPOLOGY_WITH_OPEN_EFFECTS':
            raise ValueError('class suite cannot claim closed effects or parent construction')
        if type(self)is ClassSuiteOverlay and any(p.kind in ('LOAD_METHOD_314','CALL_METHOD_314')for p in self.protocols):
            raise ValueError('historical class suite cannot acquire normalized method-call protocols')
        if type(self.operations_emitted) is not int or self.operations_emitted <= 0:
            raise ValueError('class suite must contain actual canonical operations')
        if type(self.frame_rules)is not FrameRules:
            raise TypeError('class suite must retain conditional frame lifetime rules')


@dataclass(frozen=True, slots=True)
class ClassSuiteMethodLookup:
    """Normalized CPython method lookup, without a NULL-valued PyObject.

    ``has_self`` selects the physical second stack slot. False means its Ref
    holds Py_None padding; it must never become an explicit None argument.
    The lookup primitive steals the original owner on normal and raise paths,
    transferring it into self/bound-callable ownership or releasing it there.
    This says nothing about destruction if another alias still owns the object.
    """
    operation: OperationID
    owner: UseID
    attribute_key: UseID
    callable: ValueID
    optional_self: ValueID
    has_self: ValueID
    absent_self: str = 'PY_NONE_PADDING_NOT_ARGUMENT'
    ownership: str = 'OWNER_CONSUMED_BY_LOOKUP_BOTH_OUTCOMES'

    def __post_init__(self):
        if type(self.operation)is not OperationID or any(type(u)is not UseID for u in (self.owner,self.attribute_key)):
            raise TypeError('method lookup requires original operation/owner/key Uses')
        if any(type(v)is not ValueID for v in (self.callable,self.optional_self,self.has_self)):
            raise TypeError('method lookup requires its actual normalized completion Values')
        if self.absent_self!='PY_NONE_PADDING_NOT_ARGUMENT' or self.ownership!='OWNER_CONSUMED_BY_LOOKUP_BOTH_OUTCOMES':
            raise ValueError('method lookup cannot confuse NULL, None or borrowed owner lifetime')


@dataclass(frozen=True, slots=True)
class ClassSuiteMethodCall:
    """Consume a normalized callable/self carrier and original actuals.

    The compound primitive passes optional_self iff has_self is true, releases
    padding otherwise, and consumes its call references on both outcomes.
    Dynamic descriptor selection and effects remain open evidence.
    """
    operation: OperationID
    lookup: OperationID
    callable: UseID
    optional_self: UseID
    has_self: UseID
    arguments: tuple[UseID, ...]
    keyword_names: UseID | None = None
    selection: str = 'PASS_SELF_IFF_HAS_SELF'
    ownership: str = 'CALL_INPUTS_CONSUMED_BOTH_OUTCOMES'

    def __post_init__(self):
        if any(type(o)is not OperationID for o in (self.operation,self.lookup)):
            raise TypeError('method CALL requires its original call and lookup operations')
        if any(type(u)is not UseID for u in (self.callable,self.optional_self,self.has_self)):
            raise TypeError('method CALL must retain its exact normalized operand Uses')
        if type(self.arguments)is not tuple or any(type(u)is not UseID for u in self.arguments):
            raise TypeError('method CALL arguments must be ordered original Uses')
        if self.keyword_names is not None and type(self.keyword_names)is not UseID:
            raise TypeError('method CALL keyword names must be an actual Use')
        if self.selection!='PASS_SELF_IFF_HAS_SELF' or self.ownership!='CALL_INPUTS_CONSUMED_BOTH_OUTCOMES':
            raise ValueError('method CALL cannot pass padding or retain consumed call inputs')


@dataclass(frozen=True, slots=True)
class ClassSuiteMethodOverlay(ClassSuiteOverlay):
    method_lookups: tuple[ClassSuiteMethodLookup, ...] = ()
    method_calls: tuple[ClassSuiteMethodCall, ...] = ()
    profile: str = 'STATIC_CLASS_SUITE_METHOD_314_V1'

    def __post_init__(self):
        super(ClassSuiteMethodOverlay,self).__post_init__()
        for rows,kind in ((self.method_lookups,ClassSuiteMethodLookup),(self.method_calls,ClassSuiteMethodCall)):
            if type(rows)is not tuple or any(type(row)is not kind for row in rows):
                raise TypeError('method-capable suite requires typed ordered call/lookup tables')


@dataclass(frozen=True, slots=True)
class ClassEntryResult:
    graph: ProgramGraph
    metadata: LoweringMetadata
    overlay: ClassEntryOverlay | ClassSuiteOverlay | ClassSuiteMethodOverlay
    operations_emitted: int

    def __post_init__(self):
        if type(self.graph) is not ProgramGraph or type(self.metadata) is not LoweringMetadata:
            raise TypeError("class entry result needs canonical graph and source metadata")
        if type(self.overlay) not in (ClassEntryOverlay, ClassSuiteOverlay, ClassSuiteMethodOverlay):
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
    ClassSuiteProtocol: ('class_record','CLASS_SUITE_PROTOCOL'),
    ClassSuiteInstruction: ('class_record','CLASS_SUITE_INSTRUCTION'),
    ClassSuiteCell: ('class_record','CLASS_SUITE_CELL'),
    ClassSuiteConstant: ('class_record','CLASS_SUITE_CONSTANT'),
    ClassSuiteFactory: ('class_record','CLASS_SUITE_FACTORY'),
    ClassSuiteResidual: ('class_record','CLASS_SUITE_RESIDUAL'),
    ClassSuiteOverlay: ('class_record','STATIC_CLASS_SUITE_OVERLAY'),
    ClassSuiteMethodLookup: ('class_record','CLASS_SUITE_METHOD_LOOKUP'),
    ClassSuiteMethodCall: ('class_record','CLASS_SUITE_METHOD_CALL'),
    ClassSuiteMethodOverlay: ('class_record','STATIC_CLASS_SUITE_METHOD_OVERLAY'),
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
    kind=({'STATIC_CLASS_SUITE_OVERLAY':ClassSuiteOverlay,
           'STATIC_CLASS_SUITE_METHOD_OVERLAY':ClassSuiteMethodOverlay}.get(value.get('class_record'),ClassEntryOverlay)
          if type(value)is dict else ClassEntryOverlay)
    return decode(kind, value,
                  record_tags={**CLASS_FRAME_ABI_RECORD_TAGS, **CLASS_ENTRY_RECORD_TAGS})


def validate_class_entry_core(overlay: ClassEntryOverlay, graph: ProgramGraph, metadata) -> None:
    """Check that a saved class overlay names its exact canonical core ports.

    This is a structural join only. It validates the typed overlay, graph and
    source links already supplied by the caller; it does not replay source
    compilation or revalidate every source mapping.
    """
    if type(overlay) in (ClassSuiteOverlay,ClassSuiteMethodOverlay):
        return validate_class_suite_core(overlay,graph,metadata)
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


def validate_class_suite_core(overlay,graph,metadata):
    """Join suite declarations to existing core ports, without source replay."""
    from scar.ir.program.model import (
        BlockArgument,CompletionResult,ExitKind,OperationResult,ReferenceValue,StateVersionValue,
        TerminatorKind,ValueKind,ValueType,
    )
    from scar.ir.program.source_subjects import SourceCompilationFrameRoot,FrameKind
    def need(ok,why):
        if not ok:raise ValueError('class suite core: '+why)
    need(type(overlay)in(ClassSuiteOverlay,ClassSuiteMethodOverlay),'wrong explicit suite variant')
    overlay.__post_init__()
    roots=graph.frame_roots
    need(len(roots)==1 and type(roots[0])is SourceCompilationFrameRoot and roots[0].kind is FrameKind.CLASS
         and roots[0].scope==overlay.root_scope and roots[0].entry==overlay.interface
         and roots[0].code==overlay.compilation,'original CLASS frame/compiler ABI differs')
    need(metadata.entry==overlay.definition.wire and metadata.source.path==overlay.source.path
         and metadata.source.fingerprint==overlay.source.fingerprint,'source snapshot/entry differs')
    need(overlay.operations_emitted==len(graph.operations),'operation count differs')
    ops={x.id:x for x in graph.operations};values={x.id:x for x in graph.values}
    regions={r.id:r for r in graph.regions};root=regions[graph.root]
    blocks={b.id:b for r in graph.regions for b in r.blocks};entry=blocks[root.entry]
    mapping=overlay.interface.mapping
    inputs=(mapping.locals_namespace,mapping.globals_namespace,mapping.builtins_namespace,*mapping.closure_cells,mapping.world)
    need(entry.arguments==inputs,'suite entry partition differs')
    world=values[mapping.world].location;state=ValueType(ValueKind.STATE,location=world);ref=ValueType(ValueKind.REFERENCE)
    links={r.operation:r for r in metadata.operation_links}
    need(len(links)==len(metadata.operation_links) and set(links)==set(ops),'source/core operation coverage differs')
    need({r.value for r in metadata.value_links}==set(values),'value source coverage differs')
    need({(r.operation,r.use)for r in metadata.use_links}=={(o.id,u.id)for o in graph.operations for u in o.uses},'Use correspondence differs')
    protocols={p.operation:p for p in overlay.protocols}
    need(len(protocols)==len(overlay.protocols),'duplicate suite protocol')
    for identity,p in protocols.items():
        need(identity in ops and links[identity].source==p.source,'protocol source/core link differs')
        op=ops[identity]
        if op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE:
            need(not op.effects_complete and op.callee is None and op.invoke_arguments==tuple(u.id for u in op.uses)
                and tuple(c.kind for c in op.completions)==(ExitKind.NORMAL,ExitKind.RAISE)
                and op.completions[-1].types==(ref,ref,state)
                and op.completions[0].types[-1:]==(state,),'suite invocation/paired completion differs')
            need(tuple(e.kind for e in op.terminator.successors)==(ExitKind.NORMAL,ExitKind.RAISE)
                and all(e.arguments==tuple(CompletionResult(i)for i in range(len(c.types)))
                    for e,c in zip(op.terminator.successors,op.completions)),'produced completion ports differ')
            failed=blocks[op.terminator.successors[1].block]
            need(len(failed.arguments)==3 and len(failed.operations)==2,'failure must retain one frame handoff and original paired exit')
            cleanup=ops[failed.operations[0]];raised=ops[failed.operations[1]]
            need(cleanup.id in protocols and protocols[cleanup.id].kind=='FRAME_EXIT_EXCEPTION'
                 and cleanup.uses[-1].value==failed.arguments[-1]
                 and tuple(u.value for u in cleanup.uses[-3:-1])==failed.arguments[:2]
                 and len(cleanup.results)==1,'failure cleanup lost original exception/traceback/post-world')
            need(raised.terminator is not None and raised.terminator.kind is TerminatorKind.RAISE
                 and tuple(u.value for u in raised.uses)==(*failed.arguments[:2],cleanup.results[0]),
                 'failure exit substituted the pair or stale world')
    for cell in overlay.cells:
        need(cell.ordinal<len(overlay.interface.co_cellvars)
             and overlay.interface.co_cellvars[cell.ordinal]==cell.name
             and cell.operation in protocols and protocols[cell.operation].kind=='MAKE_CELL','owned cell layout/operation differs')
        op=ops[cell.operation];normal=blocks[op.terminator.successors[0].block]
        need(normal.arguments[0]==cell.reference and type(values[cell.reference])is ReferenceValue,'own cell allocation result differs')
    for c in overlay.constants:
        need(c.operation in protocols and protocols[c.operation].kind=='READ_CODE_CONSTANT'
             and ops[c.operation].results==(c.reference,)
             and values[c.reference].origin==OperationResult(c.operation,0),
             'constant code-slot result differs')
    for f in overlay.factories:
        need(f.operation in protocols and protocols[f.operation].kind=='MAKE_FUNCTION_314','factory protocol differs')
        op=ops[f.operation];normal=blocks[op.terminator.successors[0].block]
        need(tuple(u.value for u in op.uses[:2])==(f.code_reference,mapping.globals_namespace)
             and normal.arguments[0]==f.reference,'method factory must borrow G and its actual code slot')
    if overlay.remaining is not None:
        need(overlay.remaining.operation in protocols and protocols[overlay.remaining.operation].kind=='REQUIRED_CLASS_CONTINUATION',
             'remaining continuation operation differs')
    if type(overlay)is ClassSuiteMethodOverlay:
        from scar.ir.program.model import UseRole,value_type
        lookups={x.operation:x for x in overlay.method_lookups}
        calls={x.operation:x for x in overlay.method_calls}
        witnesses={w.operation:w for w in overlay.instructions if w.operation is not None}
        need(len(lookups)==len(overlay.method_lookups)and len(calls)==len(overlay.method_calls),'duplicate normalized method endpoints')
        need(set(lookups)=={p.operation for p in overlay.protocols if p.kind=='LOAD_METHOD_314'}
             and set(calls)=={p.operation for p in overlay.protocols if p.kind=='CALL_METHOD_314'},
             'normalized method interfaces lack their exact protocol operations')
        for lookup in overlay.method_lookups:
            op=ops[lookup.operation];normal=blocks[op.terminator.successors[0].block]
            need(tuple(u.id for u in op.uses[:-1])==(lookup.owner,lookup.attribute_key)
                 and normal.arguments[:-1]==(lookup.callable,lookup.optional_self,lookup.has_self)
                 and tuple(value_type(values[v])for v in normal.arguments[:-1])==
                    (ref,ref,ValueType(ValueKind.DATA,data_type='builtins.bool')),
                 'lookup must expose callable/optional-self/boolean selector, never NULL as PyObject')
            witness=witnesses.get(op.id)
            need(witness is not None and witness.opcode=='LOAD_ATTR'and witness.argument is not None
                 and witness.argument&1 and bool(witness.stack_before)
                 and witness.stack_before[-1]==op.uses[0].value
                 and witness.stack_after==(*witness.stack_before[:-1],lookup.callable,lookup.optional_self),
                 'method lookup does not match the exact owner/two-slot compiler stack transition')
            selector_uses=[(other,u)for other in graph.operations for u in other.uses if u.value==lookup.has_self]
            need(all(u.role is UseRole.DATA and
                     (other.id in calls and calls[other.id].has_self==u.id
                      or overlay.remaining is not None and other.id==overlay.remaining.operation)
                     for other,u in selector_uses),
                 'method selector escaped into a reference argument or non-carrier operation')
        for call in overlay.method_calls:
            op=ops[call.operation];lookup=lookups.get(call.lookup)
            need(lookup is not None and tuple(u.id for u in op.uses[:-1])==
                 (call.callable,call.optional_self,call.has_self,*call.arguments,*((call.keyword_names,)if call.keyword_names is not None else())),
                 'method call normalized operand shape differs')
            need(tuple(u.value for u in op.uses[:3])==(lookup.callable,lookup.optional_self,lookup.has_self)
                 and op.uses[2].role is UseRole.DATA,
                 'method CALL changed lookup selector or treated selector as a reference')
            witness=witnesses.get(op.id)
            need(witness is not None and witness.opcode in ('CALL','CALL_KW')
                 and witness.argument==len(call.arguments)
                 and (witness.opcode=='CALL_KW')==(call.keyword_names is not None),
                 'method CALL changed its actual argument/keyword compiler layout')
        # New-profile lookup and CALL primitives consume their input slots.
        # Check the saved witness/frame tables too, so a core-only reader
        # cannot silently reintroduce a delayed owner/call-input lifetime.
        for identity,protocol in protocols.items():
            if protocol.kind not in ('LOAD_METHOD_314','CALL_METHOD_314','CALL','APPLY_DECORATOR_314'):continue
            op=ops[identity];witness=witnesses.get(identity)
            need(witness is not None,'consuming primitive lacks its compiler witness')
            before=witness.stack_before
            consumed=1 if protocol.kind=='LOAD_METHOD_314'else witness.argument+2+(witness.opcode=='CALL_KW')
            need(len(before)>=consumed,'consuming primitive compiler stack underflow')
            active_cells=tuple(c.reference for c in overlay.cells if protocols[c.operation].offset<protocol.offset)
            remaining=(*inputs[:-1],*active_cells,*(v for v in before[:-consumed]if v is not None))
            expected=tuple(dict.fromkeys(v for v in remaining if type(values[v])is ReferenceValue))
            failure=blocks[op.terminator.successors[1].block];cleanup=ops[failure.operations[0]]
            need(tuple(u.value for u in cleanup.uses[:-3])==expected,
                 'consumed owner/call inputs were retained past the primitive or live frame bindings lost')
    need((overlay.normal_payload is ClassNormalPayloadKind.CLASS_CELL)==('__class__'in overlay.interface.co_cellvars),
         'Python-reference normal mode differs from compiler cell layout')


__all__ = ["ClassEntryInputRole", "ClassNormalPayloadKind", "ClassFrontierKind",
           "ClassEntryInput", "ClassBodyStatement", "ClassCompilerStage", "ClassEntryFrontier",
           "RequiredClassBodyExpansion", "ClassEntryOverlay", "ClassEntryResult",
           "CLASS_ENTRY_RECORD_TAGS", "compiler_cell_protocol",
           "encode_class_entry_overlay", "decode_class_entry_overlay",
           "validate_class_entry_core", "ClassSuiteOverlay", "ClassSuiteProtocol", "ClassSuiteInstruction",
           "ClassSuiteCell", "ClassSuiteConstant", "ClassSuiteFactory", "ClassSuiteResidual", "validate_class_suite_core",
           "ClassSuiteMethodOverlay", "ClassSuiteMethodLookup", "ClassSuiteMethodCall"]
