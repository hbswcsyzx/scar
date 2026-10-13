"""Source adapter for one returned Python identity-comparison primitive.

The record connects replayed parameter reads, one fixed-rule ``is`` / ``is
not`` certificate, and the SG return use to verified bytecode offsets.  It does
not certify operand evaluation or the enclosing function as pure.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import dis
import hashlib
import json
from pathlib import Path
import sys
import tokenize
from types import CodeType, FunctionType
from typing import Mapping

from scar.analysis.constants_v2 import EvaluationBudget
from scar.analysis.correspondence_v2 import (
    CodeSourceWitness, reproduce_code_source_witness,
)
from scar.analysis.primitive_semantics_v2 import (
    PrimitiveSemanticsCertificate, derive_primitive_semantics,
)
from scar.ir import CodeID
from scar.ir import semantics_v2 as sm
from scar.ir.control_flow_v2 import ControlFlowBudget
from scar.ir.record_codec import decode, encode, loads
from scar.ir.v2 import OperationDefinitionID, SemanticGraph, SemanticRelation, ValueSlotID
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import BindingUseID, StaticValueID
from scar.ir.v2.semantic import OperationKind


SCHEMA = "scar.identity-function-source.v1"
SCHEMA_VERSION = 1
RULE_ID = "python.identity_comparison.returned_function"
RULE_VERSION = "scar.identity-source.v1"
_SUPPORTED_CPYTHON = {(3, 14)}


@dataclass(frozen=True, slots=True)
class SourceIdentityOperand:
    """One ordered source Name occurrence, including repeated parameters."""

    index: int
    role: str
    read_operation: OperationDefinitionID
    binding_use: BindingUseID
    slot: ValueSlotID
    read_output_slot: ValueSlotID
    value: StaticValueID
    parameter_name: str
    source: SourceReference
    load_offset: int
    load_subindex: int

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index not in (0, 1):
            raise ValueError("identity operand index must be 0 or 1")
        if self.role != ("left" if self.index == 0 else "right"):
            raise ValueError("identity operand role/index mismatch")
        if not self.parameter_name:
            raise ValueError("identity operand must name a required parameter")
        if type(self.load_offset) is not int or self.load_offset < 0:
            raise ValueError("identity operand load offset must be non-negative")
        if type(self.load_subindex) is not int or self.load_subindex not in (0, 1):
            raise ValueError("identity operand load subindex must be 0 or 1")


@dataclass(frozen=True, slots=True)
class ReturnValueUse:
    """The SG return operation's use of this primitive's output slot."""

    operation: OperationDefinitionID
    source: SourceReference
    scope: OperationDefinitionID
    returned_value: StaticValueID
    identity_output_slot: ValueSlotID
    function_return_slot: ValueSlotID


@dataclass(frozen=True, slots=True)
class IdentityInstruction:
    """One meaningful instruction in the supported straight-line body."""

    offset: int
    opname: str
    arg: int | None
    local_names: tuple[str, ...] = ()
    subindices: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if type(self.offset) is not int or self.offset < 0 or not self.opname:
            raise ValueError("identity instruction needs offset and opname")
        if self.arg is not None and (type(self.arg) is not int or self.arg < 0):
            raise ValueError("instruction arg must be a non-negative integer or None")
        if any(type(item) is not str or not item for item in self.local_names):
            raise ValueError("instruction local names must be nonempty strings")
        if any(type(item) is not int or item not in (0, 1) for item in self.subindices):
            raise ValueError("instruction subindices must be 0 or 1")
        if len(self.local_names) != len(self.subindices):
            raise ValueError("instruction local names/subindices differ in length")


@dataclass(frozen=True, slots=True)
class _IdentityFunctionSourceRecord:
    schema: str
    schema_version: int
    rule_id: str
    rule_version: str
    semantic_digest: str
    source_semantics_digest: str
    source_snapshot: sm.SourceSnapshot
    function_definition: OperationDefinitionID
    function_source: SourceReference
    code_witness: CodeSourceWitness
    primitive: PrimitiveSemanticsCertificate
    output_slot: ValueSlotID
    operands: tuple[SourceIdentityOperand, ...]
    return_use: ReturnValueUse
    instructions: tuple[IdentityInstruction, ...]
    runtime_implementation: str
    runtime_version: tuple[int, int, int]
    budget: ControlFlowBudget

    def __post_init__(self) -> None:
        if self.schema != SCHEMA or self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported identity source schema/version")
        if self.rule_id != RULE_ID or self.rule_version != RULE_VERSION:
            raise ValueError("unsupported identity source rule/version")
        if self.primitive.operation is None or self.primitive.result is None:
            raise ValueError("identity source needs one fixed primitive certificate")
        if len(self.operands) != 2 or tuple((item.index, item.role) for item in self.operands) != (
                (0, "left"), (1, "right")):
            raise ValueError("identity source requires ordered left/right source occurrences")
        if (self.return_use.returned_value != self.primitive.result or
                self.return_use.identity_output_slot != self.output_slot):
            raise ValueError("return use does not connect the certified primitive result")
        if len({item.read_operation for item in self.operands}) != 2 or len(
                {item.binding_use for item in self.operands}) != 2:
            raise ValueError("operand occurrences must retain distinct reads and binding uses")
        if not self.runtime_implementation or len(self.runtime_version) != 3:
            raise ValueError("identity source runtime scope is incomplete")
        if any(type(item) is not int or item < 0 for item in self.runtime_version):
            raise ValueError("identity source runtime version is invalid")


class IdentityFunctionSource:
    """Strict replayable source record with a private exact loaded-code lease."""

    __slots__ = ("_record", "_loaded_code", "_semantic", "_source_semantics", "_function")

    def __init__(self, record: _IdentityFunctionSourceRecord, *, loaded_code,
                 semantic, source_semantics, function):
        self._record = record
        self._loaded_code = loaded_code
        self._semantic = semantic
        self._source_semantics = source_semantics
        self._function = function

    def __getattr__(self, name):
        if name in _IdentityFunctionSourceRecord.__dataclass_fields__:
            return getattr(self._record, name)
        raise AttributeError(name)

    @property
    def loaded_code_id(self) -> str:
        return self.code_witness.loaded_code_id

    @property
    def identity_operation(self) -> OperationDefinitionID:
        return self.primitive.operation

    @property
    def opcode(self) -> sm.Opcode:
        return self.primitive.opcode

    @property
    def source(self) -> SourceReference:
        return self.primitive.source

    @property
    def result(self) -> StaticValueID:
        return self.primitive.result

    def validate(self, semantic=None, source_semantics=None, function=None, *,
                 source_texts=None, verification_budget=ControlFlowBudget()):
        return validate_identity_source(
            self, self._semantic if semantic is None else semantic,
            self._source_semantics if source_semantics is None else source_semantics,
            self._function if function is None else function,
            source_texts=source_texts, verification_budget=verification_budget)

    def assert_valid(self, semantic=None, source_semantics=None, function=None, *,
                     source_texts=None, verification_budget=ControlFlowBudget()):
        report = self.validate(semantic, source_semantics, function,
                               source_texts=source_texts,
                               verification_budget=verification_budget)
        if not report["valid"]:
            raise ValueError("invalid identity function source: " + "; ".join(report["errors"]))
        return report

    def to_dict(self, *, semantic=None, source_semantics=None, function=None,
                source_texts=None, verification_budget=ControlFlowBudget()):
        self.assert_valid(semantic, source_semantics, function,
                          source_texts=source_texts,
                          verification_budget=verification_budget)
        return encode(self._record)

    def to_json(self, **kwargs):
        return json.dumps(self.to_dict(**kwargs), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)

    @classmethod
    def from_dict(cls, document, *, semantic, source_semantics, function,
                  source_texts=None, verification_budget=ControlFlowBudget()):
        record = decode(_IdentityFunctionSourceRecord, document)
        if record.schema != SCHEMA or record.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported identity function source schema/version")
        _check_budget(record.budget, verification_budget)
        expected = _prepare_record(semantic, source_semantics, function,
                                   source_texts=source_texts, budget=record.budget)
        if encode(record) != encode(expected):
            raise ValueError("identity source document differs from source replay")
        return cls(expected, loaded_code=function.__code__, semantic=semantic,
                   source_semantics=source_semantics, function=function)

    @classmethod
    def from_json(cls, payload, **kwargs):
        return cls.from_dict(loads(payload), **kwargs)


def _canonical(value) -> str:
    return json.dumps(encode(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _digest(value) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _check_budget(stored, ceiling) -> None:
    if type(stored) is not ControlFlowBudget or type(ceiling) is not ControlFlowBudget:
        raise TypeError("source budget must be ControlFlowBudget")
    stored.__post_init__()
    ceiling.__post_init__()
    if any(getattr(stored, key) > getattr(ceiling, key)
           for key in stored.__dataclass_fields__):
        raise ValueError("stored identity source budget exceeds verification ceiling")


def _source_inputs(semantic, source_semantics, source_texts, budget):
    paths = [module.path for module in semantic.modules.values()
             if module.path and module.fingerprint]
    if not paths or len(paths) != len(set(paths)):
        raise ValueError("semantic graph must have unique fingerprinted source paths")
    if source_texts is not None:
        if not isinstance(source_texts, Mapping):
            raise TypeError("source_texts must map source paths to decoded text")
        if set(source_texts) != set(paths) or any(type(key) is not str or type(value) is not str
                                                   for key, value in source_texts.items()):
            raise ValueError("source_texts must cover exactly the graph's module paths")
        texts = dict(source_texts)
    else:
        texts = {}
        for path in paths:
            with tokenize.open(path) as stream:
                texts[path] = stream.read()

    source_bytes = 0
    ast_nodes = 0
    trees = {}
    expected = {module.path: module.fingerprint for module in semantic.modules.values()
                if module.path and module.fingerprint}
    for path in paths:
        text = texts[path]
        source_bytes += len(text.encode("utf-8"))
        if source_bytes > budget.max_source_bytes:
            raise ValueError("identity source byte budget exceeded")
        fingerprint = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
        if fingerprint != expected[path]:
            raise ValueError("source fingerprint mismatch: " + path)
        tree = ast.parse(text, filename=path, type_comments=True)
        pending = [tree]
        while pending:
            current = pending.pop()
            ast_nodes += 1
            if ast_nodes > budget.max_ast_nodes:
                raise ValueError("identity source AST-node budget exceeded")
            pending.extend(ast.iter_child_nodes(current))
        trees[path] = tree
    graph_nodes = (len(semantic.definitions) + len(semantic.edges) + len(semantic.slots) +
                   len(source_semantics.operations) + len(source_semantics.values) +
                   len(source_semantics.uses) + len(source_semantics.bindings))
    if graph_nodes > budget.max_nodes or graph_nodes > budget.max_build_work:
        raise ValueError("identity source graph work budget exceeded")
    return texts, trees, source_bytes


def _ast_callable_candidates(tree):
    found = []

    def visit(statements, prefix="", parent_is_function=False):
        for node in statements:
            if isinstance(node, ast.ClassDef):
                qualname = prefix + (".<locals>." if parent_is_function else "." if prefix else "") + node.name
                visit(node.body, qualname, False)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = prefix + (".<locals>." if parent_is_function else "." if prefix else "") + node.name
                found.append((qualname, node))
                visit(node.body, qualname, True)

    visit(tree.body)
    return found


def _source_ref(semantic, path, node):
    span = (path, type(node).__name__, node.lineno, node.end_lineno,
            node.col_offset, node.end_col_offset)
    matches = [atom.reference for atom in semantic.source_atoms.values()
               if (atom.reference.path, atom.kind, atom.reference.start_line,
                   atom.reference.end_line, atom.reference.start_column,
                   atom.reference.end_column) == span]
    if len(matches) != 1:
        raise ValueError("source atom is missing or ambiguous for " + type(node).__name__)
    return matches[0]


def _static_operation_for_source(source_semantics, reference, *, opcode=None):
    matches = [operation for operation in source_semantics.operations.values()
               if operation.source == reference and (opcode is None or operation.opcode is opcode)]
    if len(matches) != 1:
        raise ValueError("source semantics operation is missing or ambiguous")
    return matches[0]


def _operation_for_source(semantic, reference, *, parent=None, label=None, kind=None):
    matches = []
    for definition in semantic.definitions.values():
        if parent is not None and definition.parent_id != parent:
            continue
        if label is not None and definition.label != label:
            continue
        if kind is not None and definition.kind is not kind:
            continue
        if any(semantic.source_atoms[atom].reference == reference
               for atom in definition.source_atoms if atom in semantic.source_atoms):
            matches.append(definition)
    if len(matches) != 1:
        raise ValueError("semantic operation is missing or ambiguous at source span")
    return matches[0]


def _edge_slots(semantic, operation, relation):
    return {edge.target.id for edge in semantic.edges.values()
            if edge.relation is relation and edge.source.id == operation}


def _load_names(instruction):
    if instruction.opname == "LOAD_FAST_BORROW_LOAD_FAST_BORROW":
        names = instruction.argval
        if type(names) is not tuple or len(names) != 2 or any(type(name) is not str for name in names):
            raise ValueError("fused borrowed-load instruction lacks an exact pair of local names")
        return names, (0, 1)
    raise ValueError("unsupported identity operand instruction: " + instruction.opname)


def _instructions(code, operand_names, opcode):
    if sys.implementation.name != "cpython" or tuple(sys.version_info[:2]) not in _SUPPORTED_CPYTHON:
        raise ValueError("identity operand bytecode is unsupported on this Python runtime")
    decoded = tuple(dis.get_instructions(code, show_caches=False, adaptive=False))
    loads = [item for item in decoded
             if item.opname in {"LOAD_FAST", "LOAD_FAST_BORROW_LOAD_FAST_BORROW"}]
    if len(loads) == 1 and loads[0].opname == "LOAD_FAST_BORROW_LOAD_FAST_BORROW":
        load_map = ((loads[0].offset, 0), (loads[0].offset, 1))
        actual_names = _load_names(loads[0])[0]
    else:
        raise ValueError("identity operands require one verified fused borrowed-load pair")
    if actual_names != tuple(operand_names):
        raise ValueError("bytecode local order differs from source operand occurrences")
    is_ops = [item for item in decoded if item.opname == "IS_OP"]
    expected_arg = 0 if opcode is sm.Opcode.IS else 1
    if len(is_ops) != 1 or is_ops[0].arg != expected_arg:
        raise ValueError("bytecode IS_OP polarity differs from primitive source")
    allowed = {"RESUME", "LOAD_FAST_BORROW_LOAD_FAST_BORROW", "IS_OP", "RETURN_VALUE"}
    if (len(decoded) != len(loads) + 3 or decoded[0].opname != "RESUME" or
            decoded[0].arg != 0 or decoded[-2].opname != "IS_OP" or
            decoded[-1].opname != "RETURN_VALUE" or
            any(item.opname not in allowed for item in decoded)):
        raise ValueError("unsupported instruction outside the verified identity return sequence")
    result = []
    for item in decoded:
        if item.opname == "LOAD_FAST_BORROW_LOAD_FAST_BORROW":
            names, subindices = _load_names(item)
        else:
            names, subindices = (), ()
        result.append(IdentityInstruction(item.offset, item.opname, item.arg,
                                          tuple(names), tuple(subindices)))
    return tuple(result), load_map


def _function_source_model(semantic, source_semantics, function, texts, trees,
                           budget):
    if type(function) is not FunctionType:
        raise TypeError("identity source requires ordinary Python FunctionType")
    code = function.__code__
    code_id = CodeID.from_code(code)
    source_paths = [module.path for module in semantic.modules.values()
                    if module.path and module.fingerprint and
                    str(Path(module.path).resolve()) == code_id.source]
    if len(source_paths) != 1:
        raise ValueError("loaded code path does not identify one source module")
    path = source_paths[0]
    tree = trees[path]
    candidates = [(qualname, node) for qualname, node in _ast_callable_candidates(tree)
                  if qualname == code.co_qualname and node.lineno == code.co_firstlineno]
    if len(candidates) != 1:
        raise ValueError("loaded code does not identify one source function definition")
    qualname, node = candidates[0]
    if type(node) is not ast.FunctionDef:
        raise ValueError("source target must be synchronous FunctionDef")
    if (node.decorator_list or len(node.body) != 1 or type(node.body[0]) is not ast.Return or
            node.body[0].value is None):
        raise ValueError("function must contain exactly one undecorated return expression")
    if function.__defaults__ is not None or function.__kwdefaults__ is not None:
        raise ValueError("defaults are outside this source rule")
    # On CPython 3.14, reading ``__annotations__`` can invoke this resolver.
    # Inspect only the resolver slot and never ask for the annotations value.
    if getattr(function, "__annotate__", None) is not None:
        raise ValueError("runtime annotation resolver is outside this source rule")
    if (code.co_freevars or code.co_cellvars or code.co_names or
            code.co_flags & (0x20 | 0x80 | 0x200)):
        raise ValueError("closures, global lookups, async, and generators are outside this source rule")
    if any(argument.annotation is not None for argument in
           (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)):
        raise ValueError("parameter annotations are outside this source rule")
    if (node.returns is not None or node.args.vararg is not None or node.args.kwarg is not None or
            node.args.defaults or any(default is not None for default in node.args.kw_defaults) or
            getattr(node, "type_params", ())):
        raise ValueError("required fixed parameters without annotations are required")
    expression = node.body[0].value
    if (type(expression) is not ast.Compare or len(expression.ops) != 1 or
            len(expression.comparators) != 1 or type(expression.left) is not ast.Name or
            type(expression.comparators[0]) is not ast.Name or
            type(expression.ops[0]) not in {ast.Is, ast.IsNot}):
        raise ValueError("return expression must be exactly Name is/is not Name")
    arg_nodes = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
    arg_names = tuple(argument.arg for argument in arg_nodes)
    if (len(arg_names) != len(set(arg_names)) or
            code.co_argcount != len(node.args.posonlyargs) + len(node.args.args) or
            code.co_posonlyargcount != len(node.args.posonlyargs) or
            code.co_kwonlyargcount != len(node.args.kwonlyargs) or
            tuple(code.co_varnames[:len(arg_names)]) != arg_names or
            len(code.co_varnames) != len(arg_names)):
        raise ValueError("loaded function argument layout differs from source parameters")
    operand_names = (expression.left.id, expression.comparators[0].id)
    if any(name not in arg_names for name in operand_names):
        raise ValueError("identity operands must be required positional or keyword parameters")

    function_source = _source_ref(semantic, path, node)
    function_atoms = {atom.id for atom in semantic.source_atoms.values()
                      if atom.reference == function_source}
    function_defs = [definition for definition in semantic.definitions.values()
                     if definition.kind in {OperationKind.FUNCTION, OperationKind.METHOD}
                     and definition.metadata.get("phase") == "call_time"
                     and function_atoms.intersection(definition.source_atoms)]
    if len(function_defs) != 1:
        raise ValueError("source function has missing or ambiguous SG call-time definition")
    function_definition = function_defs[0]
    if tuple(semantic.slots[slot].name for slot in function_definition.input_slots) != arg_names:
        raise ValueError("SG function parameter slots differ from source signature")
    if len(function_definition.output_slots) != 1:
        raise ValueError("SG function must have exactly one return slot")

    expression_source = _source_ref(semantic, path, expression)
    return_source = _source_ref(semantic, path, node.body[0])
    left_source = _source_ref(semantic, path, expression.left)
    right_source = _source_ref(semantic, path, expression.comparators[0])
    opcode = sm.Opcode.IS if type(expression.ops[0]) is ast.Is else sm.Opcode.IS_NOT
    identity = _static_operation_for_source(source_semantics, expression_source)
    if identity.opcode is not opcode or identity.result is None:
        raise ValueError("source overlay identity operation differs from AST")
    primitive_report = derive_primitive_semantics(
        semantic, source_semantics, identity.operation, source_texts=texts,
        budget=EvaluationBudget(max_nodes=budget.max_nodes,
            max_steps=budget.max_build_work, max_work=budget.max_query_work,
            max_bytes=budget.max_source_bytes,
            max_total_output_bytes=budget.max_source_bytes))
    primitive = primitive_report.certificates.get(identity.operation)
    if type(primitive) is not PrimitiveSemanticsCertificate:
        raise ValueError("fixed primitive semantics replay did not certify the identity operator")
    if (primitive.opcode is not opcode or primitive.source != expression_source or
            primitive.result != identity.result):
        raise ValueError("primitive certificate differs from source identity operation")
    if (identity.scope != function_definition.id or
            identity.block == "" or len(identity.operands) != 2):
        raise ValueError("identity operation is outside one source function block")

    definition = semantic.definitions[identity.operation]
    if definition.parent_id != function_definition.id or len(definition.output_slots) != 1:
        raise ValueError("identity operator SG output is not owned by source function")
    output_slot = definition.output_slots[0]
    if _edge_slots(semantic, definition.id, SemanticRelation.PRODUCES) != {output_slot}:
        raise ValueError("identity result lacks one exact SG PRODUCES edge")
    if source_semantics.values.get(identity.result) is None or \
            source_semantics.values[identity.result].producer != identity.operation:
        raise ValueError("identity static value is not produced by its source operation")

    decoded, load_map = _instructions(code, operand_names, opcode)
    operands = []
    for index, (name, source_ref, load) in enumerate(zip(
            operand_names, (left_source, right_source), load_map)):
        read = _static_operation_for_source(source_semantics, source_ref, opcode=sm.Opcode.READ)
        if read.result is None or read.binding_use is None:
            raise ValueError("operand READ lacks a static result or BindingUse")
        binding_use = source_semantics.uses.get(read.binding_use)
        if binding_use is None or binding_use.operation != read.operation:
            raise ValueError("operand READ BindingUse link is missing or mismatched")
        if (read.scope != function_definition.id or binding_use.scope != function_definition.id or
                read.block != identity.block or binding_use.block != identity.block or
                read.position >= identity.position):
            raise ValueError("operand READ is not ordered in the identity operation's function block")
        if (binding_use.slot not in function_definition.input_slots or
                semantic.slots[binding_use.slot].name != name):
            raise ValueError("operand READ does not bind the named required parameter slot")
        if _edge_slots(semantic, read.operation, SemanticRelation.READS_SLOT) != {binding_use.slot}:
            raise ValueError("operand READ SG slot edge differs from its BindingUse")
        read_definition = semantic.definitions.get(read.operation)
        if read_definition is None or len(read_definition.output_slots) != 1:
            raise ValueError("operand READ must produce exactly one SG value slot")
        read_output_slot = read_definition.output_slots[0]
        if _edge_slots(semantic, read.operation, SemanticRelation.PRODUCES) != {read_output_slot}:
            raise ValueError("operand READ result lacks one exact SG PRODUCES edge")
        if identity.operands[index].value != read.result or \
                (identity.operands[index].role, identity.operands[index].index) != (
                    "left" if index == 0 else "right", index):
            raise ValueError("ordered identity input does not match its source READ occurrence")
        operands.append(SourceIdentityOperand(index, "left" if index == 0 else "right",
            read.operation, read.binding_use, binding_use.slot, read_output_slot, read.result,
            name, source_ref, load[0], load[1]))
    if len({item.read_operation for item in operands}) != 2 or \
            len({item.binding_use for item in operands}) != 2:
        raise ValueError("separate source operand occurrences were collapsed")
    if _edge_slots(semantic, definition.id, SemanticRelation.READS_SLOT) != {
            item.read_output_slot for item in operands}:
        raise ValueError("SG comparison does not consume the two ordered READ output occurrences")

    return_operation = _operation_for_source(semantic, return_source,
        parent=function_definition.id, label="return")
    function_return_slot = function_definition.output_slots[0]
    if (_edge_slots(semantic, return_operation.id, SemanticRelation.READS_SLOT) != {output_slot} or
            _edge_slots(semantic, return_operation.id, SemanticRelation.PRODUCES) != {function_return_slot}):
        raise ValueError("SG return use does not read the identity result and produce function return")
    return_use = ReturnValueUse(return_operation.id, return_source,
        function_definition.id, identity.result, output_slot, function_return_slot)

    witnesses = reproduce_code_source_witness(semantic, code, source_texts=texts)
    if not witnesses:
        raise ValueError("loaded function has no exact code-source witness")
    source_snapshot = source_semantics.sources.get(path)
    if source_snapshot is None or source_snapshot.fingerprint != witnesses[0].source_fingerprint:
        raise ValueError("source semantics snapshot differs from exact code witness")
    return _IdentityFunctionSourceRecord(
        SCHEMA, SCHEMA_VERSION, RULE_ID, RULE_VERSION,
        _digest(semantic.to_dict()), _digest(source_semantics.to_dict()),
        source_snapshot, function_definition.id, function_source,
        witnesses[0], primitive, output_slot, tuple(operands), return_use,
        decoded, sys.implementation.name, tuple(sys.version_info[:3]), budget)


def prepare_identity_source(semantic: SemanticGraph,
                           source_semantics: sm.SourceSemanticsGraph,
                           function: FunctionType, *, source_texts=None,
                           budget=ControlFlowBudget()) -> IdentityFunctionSource:
    """Build evidence for ``return required_arg is[/not] required_arg`` only.

    The target function and any module are never executed or imported.  The
    fixed primitive certificate is included as a primitive-only fact; operand
    and return links are source/reachability connectors, not a function-purity
    assertion.
    """
    if type(semantic) is not SemanticGraph or type(source_semantics) is not sm.SourceSemanticsGraph:
        raise TypeError("SemanticGraph and SourceSemanticsGraph are required")
    if type(budget) is not ControlFlowBudget:
        raise TypeError("budget must be ControlFlowBudget")
    budget.__post_init__()
    semantic.assert_valid()
    texts, trees, _ = _source_inputs(semantic, source_semantics, source_texts, budget)
    record = _function_source_model(semantic, source_semantics, function, texts, trees, budget)
    return IdentityFunctionSource(record, loaded_code=function.__code__, semantic=semantic,
                                  source_semantics=source_semantics, function=function)


def validate_identity_source(model: IdentityFunctionSource, semantic: SemanticGraph,
                             source_semantics: sm.SourceSemanticsGraph,
                             function: FunctionType, *, source_texts=None,
                             verification_budget=ControlFlowBudget()):
    if type(model) is not IdentityFunctionSource:
        return {"valid": False, "errors": ["model must be IdentityFunctionSource"]}
    if type(function) is not FunctionType:
        return {"valid": False, "errors": ["function must be ordinary FunctionType"]}
    if function.__code__ is not model._loaded_code:
        return {"valid": False, "errors": ["function __code__ object changed after source preparation"]}
    try:
        _check_budget(model.budget, verification_budget)
        expected = _prepare_record(semantic, source_semantics, function,
            source_texts=source_texts, budget=model.budget)
        if encode(model._record) != encode(expected):
            raise ValueError("identity source differs from fixed-rule rederivation")
        return {"valid": True, "errors": []}
    except (ValueError, TypeError, KeyError, AttributeError, OSError,
            UnicodeError, SyntaxError, OverflowError) as error:
        return {"valid": False, "errors": [str(error)]}


def _prepare_record(semantic, source_semantics, function, *, source_texts, budget):
    if type(semantic) is not SemanticGraph or type(source_semantics) is not sm.SourceSemanticsGraph:
        raise TypeError("SemanticGraph and SourceSemanticsGraph are required")
    if type(function) is not FunctionType:
        raise TypeError("function must be ordinary FunctionType")
    if type(budget) is not ControlFlowBudget:
        raise TypeError("budget must be ControlFlowBudget")
    budget.__post_init__()
    semantic.assert_valid()
    texts, trees, _ = _source_inputs(semantic, source_semantics, source_texts, budget)
    return _function_source_model(semantic, source_semantics, function, texts, trees, budget)


__all__ = [
    "SCHEMA", "SCHEMA_VERSION", "RULE_ID", "RULE_VERSION",
    "SourceIdentityOperand", "ReturnValueUse", "IdentityInstruction",
    "IdentityFunctionSource", "prepare_identity_source", "validate_identity_source",
]
