"""Automatically connect versioned Python source to the program core.

The result is a conservative model of a selected function body. Python
dispatch, external effects and live call targets are not certified by parsing.
All target code is read as source; construction never imports or executes it.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import symtable
import tokenize

from scar.analysis.control_flow_v2 import build_source_control_flow, validate_source_control_flow
from scar.analysis.source_semantics_v2 import extract_source_semantics, validate_source_semantics
from scar.ir.frontend_v2 import build_semantic_files
from scar.ir.program.codec import dumps as dump_graph
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, LiteralOrigin, Operation,
    ProgramGraph, ReferenceValue, Region, Stability, StateLocation,
    StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseRole,
    ValueKind, ValueType,
)
from scar.ir.program.source import (
    CallTarget, CandidateArgument, CandidateResult, GapKind, LoweringGap,
    LoweringMetadata, OperationSource, SourceRole,
    UseSource, ValueSource,
)
from scar.ir.program.validation import require_valid
from scar.ir.record_codec import encode
from scar.ir.semantics_v2 import Opcode, SourceExecutionPrecondition
from scar.ir.v2._validation import record_errors
from scar.ir.v2.common import EvidenceKind


_ASSUMPTIONS = (
    SourceExecutionPrecondition.STANDARD_FUNCTION_LOCALS,
    SourceExecutionPrecondition.NO_EXTERNAL_NAMESPACE_MUTATION,
)
_REF = ValueType(ValueKind.REFERENCE)
_BOOL = ValueType(ValueKind.DATA, "builtins.bool")


def _key(*parts):
    return hashlib.sha256("\0".join(str(part) for part in parts).encode()).hexdigest()[:32]


def _span(node):
    return (type(node).__name__, node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)


@dataclass(frozen=True)
class SourceProgram:
    graph: ProgramGraph | None
    metadata: LoweringMetadata
    semantic: object
    semantics: object
    control: object

    def summary(self):
        """Separate declaration/link counts from program and effect coverage."""
        graph = self.graph
        return {
            "entry": self.metadata.entry,
            "graph_present": graph is not None,
            "counts": {
                "regions": len(graph.regions) if graph else 0,
                "blocks": sum(len(region.blocks) for region in graph.regions) if graph else 0,
                "operations": len(graph.operations) if graph else 0,
                "values": len(graph.values) if graph else 0,
                "uses": sum(len(operation.uses) for operation in graph.operations) if graph else 0,
                "state_locations": len(graph.locations) if graph else 0,
                "incomplete_effect_operations": sum(not op.effects_complete for op in graph.operations) if graph else 0,
                "operation_source_links": len(self.metadata.operation_links),
                "value_source_links": len(self.metadata.value_links),
                "use_source_links": len(self.metadata.use_links),
                "candidate_calls": len(self.metadata.call_targets),
                "candidate_interfaces": sum(bool(target.arguments) for target in self.metadata.call_targets),
                "parsed_source_atoms": len(self.semantic.source_atoms),
            },
            "gap_counts": dict(sorted(Counter(gap.kind.value for gap in self.metadata.gaps).items())),
            "source_selection": "one file parsed; selected body and available same-file call candidates lowered",
            "whole_program_coverage_established": False,
            "fine_grained_state_effects_established": False,
            "runtime_target_verified": False,
            "transformation_authorized": False,
        }

    def to_dict(self):
        return {
            "schema": "scar.source-program", "schema_version": 1,
            "status": ("UNSUPPORTED" if self.graph is None else
                       "LOWERED_WITH_GAPS" if self.metadata.gaps else "LOWERED"),
            "scope": "selected synchronous function bodies, conservative completion/effect model",
            "metadata": encode(self.metadata),
            "graph": json.loads(dump_graph(self.graph)) if self.graph is not None else None,
            "semantic": self.semantic.to_dict(), "semantics": self.semantics.to_dict(),
            "control": self.control.to_dict(),
            "summary": self.summary(),
            "runtime_target_verified": False, "transformation_authorized": False,
        }

    @classmethod
    def from_dict(cls, document, *, max_operations=10000):
        from scar.ir.program.codec import loads as load_graph
        from scar.ir.record_codec import decode
        from scar.ir.semantics_v2 import SourceSemanticsGraph
        from scar.ir.control_flow_v2 import SourceControlFlowGraph
        from scar.ir.v2.codec import semantic_from_dict

        expected_fields = {"schema", "schema_version", "status", "scope", "metadata",
                           "graph", "semantic", "semantics", "control", "summary", "runtime_target_verified",
                           "transformation_authorized"}
        if type(document) is not dict or set(document) != expected_fields:
            raise ValueError("source program fields mismatch")
        if (document["schema"] != "scar.source-program" or type(document["schema_version"]) is not int
                or document["schema_version"] != 1):
            raise ValueError("source program schema/version mismatch")
        metadata = decode(LoweringMetadata, document["metadata"])
        semantic = semantic_from_dict(document["semantic"])
        semantics = SourceSemanticsGraph.from_dict(document["semantics"], semantic)
        control = SourceControlFlowGraph.from_dict(document["control"])
        graph = load_graph(_canonical(document["graph"])) if document["graph"] is not None else None
        result = cls(graph, metadata, semantic, semantics, control)
        if _canonical(result.to_dict()) != _canonical(document):
            raise ValueError("source program scope/status/authority or canonical fields differ")
        checked = validate_source_program(result, max_operations=max_operations)
        if not checked["valid"]:
            raise ValueError("; ".join(checked["errors"]))
        return result


def _canonical(document):
    return json.dumps(document, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


class _Unsupported(Exception):
    def __init__(self, kind, node, detail):
        self.kind, self.node, self.detail = kind, node, detail


@dataclass
class _Cursor:
    block: BlockID
    env: dict[str, ValueID]
    state: ValueID


class _Builder:
    def __init__(self, path, entry, text, semantic, semantics, control, max_operations):
        self.path, self.entry, self.text = path, entry, text
        self.semantic, self.semantics, self.control = semantic, semantics, control
        self.max_operations = max_operations
        self.snapshot = semantics.sources[str(path)]
        self.tree = ast.parse(text, filename=str(path))
        self.symbol_tables = {}
        def collect_tables(table):
            self.symbol_tables[(table.get_name(), table.get_lineno())] = table
            for child in table.get_children():
                collect_tables(child)
        collect_tables(symtable.symtable(text, str(path), "exec"))
        self.atoms = {_span_atom(atom): atom.reference for atom in semantic.source_atoms.values()
                      if atom.reference.path == str(path)}
        self.by_atom = defaultdict(list)
        self.old_by_atom = defaultdict(list)
        for definition in semantic.definitions.values():
            self.by_atom[definition.code_id].append(definition)
        for operation in semantics.operations.values():
            self.old_by_atom[operation.source.atom_id].append(operation)
        self.slots = {(slot.owner, slot.name): slot.slot_id for slot in semantic.slots.values()}
        self.functions = {}
        self._collect_functions(self.tree.body)
        self.regions, self.operations, self.values = [], [], []
        self.values_by_id = {}
        self.operation_links, self.value_links, self.use_links = [], [], []
        self.targets, self.gaps = [], []
        self.world = LocationID(_key("python-world", str(path), self.snapshot.fingerprint))
        self.state_type = ValueType(ValueKind.STATE, location=self.world)
        self.serial = 0
        self.function_context = None
        self.block_operations = {}
        self.block_arguments = {}
        self.function_blocks = []
        self.pending_targets = []

    def _collect_functions(self, statements, prefix=""):
        for node in statements:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + node.name
                self.functions[name] = node
            elif isinstance(node, ast.ClassDef):
                self._collect_functions(node.body, prefix + node.name + ".")

    def source(self, node):
        try:
            return self.atoms[_span(node)]
        except KeyError:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node, "source atom is not uniquely represented")

    def old_operation(self, node):
        records = self.old_by_atom[self.source(node).atom_id]
        if len(records) != 1:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node, "expression needs one source computational record")
        return records[0]

    def definition(self, node):
        choices = [d for d in self.by_atom[self.source(node).atom_id.wire]
                   if d.metadata.get("phase") == "call_time"]
        if len(choices) != 1:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node, "function body needs one versioned source definition")
        return choices[0]

    def fresh(self, cls, tag):
        self.serial += 1
        return cls(_key(self.snapshot.fingerprint, str(self.function_context), tag, self.serial))

    def gap(self, kind, node, detail):
        gap = LoweringGap(kind, self.source(node), detail)
        if gap not in self.gaps:
            self.gaps.append(gap)

    def link_value(self, value, node, role, *, slot=None, semantic_value=None):
        link = ValueSource(value.id, self.source(node), role, slot, semantic_value)
        if link not in self.value_links:
            self.value_links.append(link)

    def add_value(self, value):
        self.values.append(value)
        self.values_by_id[value.id] = value

    def new_block(self, node, *, named=(), role=SourceRole.CONTROL, extra_types=()):
        block = self.fresh(BlockID, "block")
        self.function_blocks.append(block)
        self.block_operations[block] = []
        args, env = [], {}
        for name in named:
            value = ReferenceValue(self.fresh(ValueID, "argument"), self.function_context,
                                   BlockArgument(block, len(args)))
            self.add_value(value); args.append(value.id); env[name] = value.id
            self.link_value(value, node, role)
        for kind in extra_types:
            if kind.kind is ValueKind.REFERENCE:
                value = ReferenceValue(self.fresh(ValueID, "completion-reference"), self.function_context,
                                       BlockArgument(block, len(args)))
            elif kind.kind is ValueKind.DATA:
                value = DataValue(self.fresh(ValueID, "completion-data"), self.function_context,
                                  BlockArgument(block, len(args)), kind.data_type)
            else:
                raise ValueError("completion state is added by the block interface")
            self.add_value(value); args.append(value.id)
            self.link_value(value, node, role)
        state = StateVersionValue(self.fresh(ValueID, "world-state"), self.function_context,
                                  BlockArgument(block, len(args)), self.world)
        self.add_value(state); args.append(state.id)
        self.link_value(state, node, SourceRole.STATE)
        self.block_arguments[block] = tuple(args)
        return _Cursor(block, env, state.id)

    def use(self, operation, value, node, role, index, *, semantic_value=None):
        record = self.values_by_id[value]
        kind = (UseRole.REFERENCE if isinstance(record, ReferenceValue) else
                UseRole.STATE_CONTENT if isinstance(record, StateVersionValue) else UseRole.DATA)
        use = Use(self.fresh(UseID, "use"), value, kind)
        self.use_links.append(UseSource(operation, use.id, self.source(node), role, index, semantic_value))
        return use

    def emit(self, cursor, operation, node, role, old=None):
        if len(self.operations) >= self.max_operations:
            raise _Unsupported(GapKind.BUDGET, node, "program operation budget exceeded")
        self.operations.append(operation)
        self.block_operations[cursor.block].append(operation.id)
        self.operation_links.append(OperationSource(operation.id, self.source(node), role,
                                                     old.operation if old else None,
                                                     old.opcode if old else None))

    def invoke(self, cursor, node, inputs, *, role=SourceRole.EXPRESSION, old=None,
               result_type=_REF):
        """Attempt one source operation, keeping its state and exception paths."""
        operation_id = self.fresh(OperationID, "invoke")
        uses = [self.use(operation_id, value, child, operand_role, index, semantic_value=static)
                for value, child, operand_role, index, static in inputs]
        uses.append(self.use(operation_id, cursor.state, node, "state", 0))
        normal = self.new_block(node, role=role, extra_types=(result_type,) if result_type else ())
        failure = self.new_block(node, role=SourceRole.EXCEPTION, extra_types=(_REF,))
        signatures = (
            CompletionSignature(ExitKind.NORMAL, ((result_type,) if result_type else ()) + (self.state_type,)),
            CompletionSignature(ExitKind.RAISE, (_REF, self.state_type)),
        )
        edges = tuple(CompletionSuccessor(signature.kind, target.block,
                      tuple(CompletionResult(i) for i in range(len(signature.types))))
                      for signature, target in zip(signatures, (normal, failure)))
        operation = Operation(operation_id, role.value, (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
                              tuple(uses), effects_complete=False,
                              terminator=Terminator(TerminatorKind.INVOKE, edges),
                              completions=signatures, invoke_arguments=tuple(u.id for u in uses))
        self.emit(cursor, operation, node, role, old)
        exception = self.block_arguments[failure.block][0]
        self.finish_exit(failure, node, exception, ExitKind.RAISE)
        normal.env = dict(cursor.env)
        value = self.block_arguments[normal.block][0] if result_type else None
        if value is not None and old is not None and old.result is not None:
            actual = self.values_by_id[value]
            self.link_value(actual, node, role, semantic_value=old.result)
        return normal, value, operation_id

    def finish_exit(self, cursor, node, value, kind):
        operation_id = self.fresh(OperationID, "exit")
        uses = (self.use(operation_id, value, node, "result", 0),
                self.use(operation_id, cursor.state, node, "state", 0))
        term_kind = TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE
        operation = Operation(operation_id, kind.value, (Behavior.CONTROL,), uses,
                              terminator=Terminator(term_kind, exit=kind.value.lower(),
                                                    values=tuple(u.id for u in uses)))
        self.emit(cursor, operation, node, SourceRole.RETURN if kind is ExitKind.NORMAL else SourceRole.EXCEPTION)

    def literal(self, node, value):
        try:
            origin = LiteralOrigin(value)
        except (TypeError, ValueError):
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, "literal is outside exact scalar support")
        record = ReferenceValue(self.fresh(ValueID, "literal"), self.function_context, origin, targets=())
        self.add_value(record)
        old = self.old_operation(node) if isinstance(node, ast.Constant) else None
        self.link_value(record, node, SourceRole.EXPRESSION, semantic_value=old.result if old else None)
        return record.id

    def expr(self, node, cursor):
        old = self.old_operation(node)
        if isinstance(node, ast.Constant):
            return cursor, self.literal(node, node.value)
        if isinstance(node, ast.Name):
            if node.id in cursor.env:
                value_id = cursor.env[node.id]
                value = self.values_by_id[value_id]
                self.link_value(value, node, SourceRole.EXPRESSION, semantic_value=old.result)
                return cursor, value_id
            if node.id in self.locals:
                raise _Unsupported(GapKind.UNBOUND_LOCAL, node, "local has no definition on every incoming path: " + node.id)
            self.gap(GapKind.EFFECT_SUMMARY, node, "global/builtin name lookup remains an effectful source operation")
            cursor, value, _ = self.invoke(cursor, node, (), old=old)
            if node.id in self.functions:
                self.reference_candidates[value] = node.id
            return cursor, value

        children = []
        if isinstance(node, ast.BinOp):
            children = [node.left, node.right]
        elif isinstance(node, ast.UnaryOp):
            children = [node.operand]
        elif isinstance(node, ast.Compare) and len(node.ops) == 1:
            children = [node.left, node.comparators[0]]
        elif isinstance(node, ast.Attribute):
            children = [node.value]
        elif isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
            children = [node.value, node.slice]
        elif isinstance(node, (ast.Tuple, ast.List)):
            children = list(node.elts)
        elif isinstance(node, ast.Call) and not any(isinstance(arg, ast.Starred) for arg in node.args) and all(k.arg is not None for k in node.keywords):
            children = [node.func, *node.args, *(keyword.value for keyword in node.keywords)]
        else:
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, "expression is not yet connected: " + type(node).__name__)
        if len(children) != len(old.operands):
            raise _Unsupported(GapKind.SOURCE_MAPPING, node, "source operand list differs from ordered semantics")
        inputs = []
        for child, operand in zip(children, old.operands):
            cursor, value = self.expr(child, cursor)
            inputs.append((value, child, operand.role, operand.index, operand.value))
        self.gap(GapKind.DYNAMIC_DISPATCH, node,
                 "source opcode is known; runtime dispatch, effects and exact exceptional behavior remain unverified")
        cursor, value, operation_id = self.invoke(cursor, node, inputs, old=old)
        if isinstance(node, ast.Call):
            callee = inputs[0][0]
            candidate_name = self.reference_candidates.get(callee)
            self.pending_targets.append((operation_id, callee, candidate_name, node))
            self.gap(GapKind.DYNAMIC_TARGET, node,
                     "source binding candidates are not live runtime target verification")
        return cursor, value

    def store(self, target, value, cursor):
        if not isinstance(target, ast.Name):
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, target, "only ordinary local name assignment is connected")
        if target.id in cursor.env:
            cursor, _, _ = self.invoke(cursor, target,
                ((cursor.env[target.id], target, "previous", 0, None),
                 (value, target, "assigned", 0, None)), role=SourceRole.LOCAL_BINDING, result_type=None)
            self.gap(GapKind.FRAME_EFFECT, target, "rebinding may release an existing reference; completion is conservatively modeled")
        cursor.env[target.id] = value
        current = self.values_by_id[value]
        old = self.old_operation(target)
        self.link_value(current, target, SourceRole.LOCAL_BINDING,
                        slot=self.slots.get((self.function_definition.id, target.id)), semantic_value=old.result)
        return cursor

    def jump(self, cursor, target, names, node):
        operation_id = self.fresh(OperationID, "jump")
        uses = [self.use(operation_id, cursor.env[name], node, "merge", index) for index, name in enumerate(names)]
        uses.append(self.use(operation_id, cursor.state, node, "state", 0))
        operation = Operation(operation_id, "join", (Behavior.CONTROL,), tuple(uses),
                              terminator=Terminator(TerminatorKind.JUMP,
                                  (Successor(target.block, tuple(use.id for use in uses)),)))
        self.emit(cursor, operation, node, SourceRole.CONTROL)

    def statements(self, statements, cursor):
        for node in statements:
            if cursor is None:
                # Preserve source diagnostics rather than claiming dead code.
                self.gap(GapKind.SOURCE_COVERAGE, node, "statement follows a closed return path; not lowered as executed work")
                continue
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                cursor, value = self.expr(node.value, cursor)
                cursor = self.store(node.targets[0], value, cursor)
            elif isinstance(node, ast.Expr):
                cursor, _ = self.expr(node.value, cursor)
            elif isinstance(node, ast.Pass):
                continue
            elif isinstance(node, ast.Return):
                if node.value is None:
                    value = self.literal(node, None)
                else:
                    cursor, value = self.expr(node.value, cursor)
                self.gap(GapKind.FRAME_EFFECT, node, "frame/reference-release effects remain conservative at return")
                cursor, returned, _ = self.invoke(cursor, node,
                    ((value, node.value or node, "return", 0, None),), role=SourceRole.RETURN)
                self.finish_exit(cursor, node, returned, ExitKind.NORMAL)
                cursor = None
            elif isinstance(node, ast.If):
                cursor, condition = self.expr(node.test, cursor)
                self.gap(GapKind.DYNAMIC_DISPATCH, node.test,
                         "Python truth conversion may execute code or raise; no parameter type is assumed")
                cursor, boolean, _ = self.invoke(cursor, node.test,
                    ((condition, node.test, "predicate", 0, None),), role=SourceRole.TRUTH, result_type=_BOOL)
                yes = self.new_block(node, role=SourceRole.CONTROL)
                no = self.new_block(node, role=SourceRole.CONTROL)
                operation_id = self.fresh(OperationID, "branch")
                uses = (self.use(operation_id, boolean, node.test, "condition", 0),
                        self.use(operation_id, cursor.state, node, "true_state", 0),
                        self.use(operation_id, cursor.state, node, "false_state", 0))
                branch = Operation(operation_id, "if", (Behavior.CONTROL,), uses,
                    terminator=Terminator(TerminatorKind.BRANCH,
                        (Successor(yes.block, (uses[1].id,)), Successor(no.block, (uses[2].id,))), condition=uses[0].id))
                self.emit(cursor, branch, node, SourceRole.CONTROL)
                yes.env, no.env = dict(cursor.env), dict(cursor.env)
                yes = self.statements(node.body, yes)
                no = self.statements(node.orelse, no)
                if yes is None or no is None:
                    cursor = yes or no
                else:
                    common = sorted(set(yes.env) & set(no.env))
                    merged = [name for name in common if yes.env[name] != no.env[name]]
                    join = self.new_block(node, named=merged, role=SourceRole.MERGE)
                    join.env.update({name: yes.env[name] for name in common if name not in merged})
                    self.jump(yes, join, merged, node)
                    self.jump(no, join, merged, node)
                    cursor = join
            else:
                raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, "statement is not yet connected: " + type(node).__name__)
        return cursor

    def function(self, name, root):
        node = self.functions[name]
        definition = self.definition(node)
        self.function_context = RegionID(_key("function-body", definition.id.wire))
        self.serial = 0
        self.function_definition = definition
        self.reference_candidates = {}
        self.function_blocks = []
        if (isinstance(node, ast.AsyncFunctionDef) or node.decorator_list or node.args.defaults
                or node.args.kw_defaults or node.args.kwonlyargs or node.args.vararg or node.args.kwarg):
            raise _Unsupported(GapKind.UNSUPPORTED_SIGNATURE, node,
                               "defaults, decorators, async and variadic/keyword-only interfaces need explicit binding rules")
        def body_nodes(statements):
            for child in statements:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                    continue
                yield child
                yield from body_nodes(ast.iter_child_nodes(child))
        if any(isinstance(child, (ast.Yield, ast.YieldFrom)) for child in body_nodes(node.body)):
            raise _Unsupported(GapKind.UNSUPPORTED_SIGNATURE, node,
                               "generator invocation/suspension requires a distinct completion and lifetime model")
        parameters = node.args.posonlyargs + node.args.args
        # Python determines scope before execution, including unreachable imports,
        # deletion and exception-handler targets. Reuse compiler symbol analysis.
        table = self.symbol_tables[(node.name, node.lineno)]
        self.locals = {symbol.get_name() for symbol in table.get_symbols() if symbol.is_local()}
        if any(symbol.is_free() or symbol.is_nonlocal() for symbol in table.get_symbols()):
            raise _Unsupported(GapKind.UNSUPPORTED_SIGNATURE, node,
                               "closure/cell bindings need explicit state-location interfaces")
        cursor = self.new_block(node)
        # Function entry has parameters followed by the explicit world state.
        state = self.values.pop()
        self.value_links.pop()
        args = []
        cursor.env = {}
        for index, parameter in enumerate(parameters):
            value = ReferenceValue(self.fresh(ValueID, "parameter"), self.function_context,
                                   BlockArgument(cursor.block, index))
            self.add_value(value); args.append(value.id); cursor.env[parameter.arg] = value.id
            slot = self.slots.get((definition.id, parameter.arg))
            if slot is None:
                raise _Unsupported(GapKind.SOURCE_MAPPING, parameter, "missing formal source slot")
            self.link_value(value, parameter, SourceRole.PARAMETER, slot=slot)
        state = StateVersionValue(state.id, state.region, BlockArgument(cursor.block, len(args)), state.location)
        self.add_value(state); args.append(state.id); cursor.state = state.id
        self.link_value(state, node, SourceRole.STATE)
        self.block_arguments[cursor.block] = tuple(args)
        entry = cursor.block
        self.gap(GapKind.CODE_VERSION, node, "source body version is bound; live function object/code and definition-time effects remain unobserved")
        cursor = self.statements(node.body, cursor)
        if cursor is not None:
            implicit = self.literal(node, None)
            cursor, value, _ = self.invoke(cursor, node,
                ((implicit, node, "return", 0, None),), role=SourceRole.RETURN)
            self.finish_exit(cursor, node, value, ExitKind.NORMAL)
        blocks = tuple(Block(block, self.block_arguments[block], tuple(self.block_operations[block]))
                       for block in self.function_blocks)
        region = Region(self.function_context, name, entry, blocks,
                        (ExitPort("normal", ExitKind.NORMAL, (_REF, self.state_type)),
                         ExitPort("raise", ExitKind.RAISE, (_REF, self.state_type))), parent=root)
        self.regions.append(region)
        return region.id

    def run(self):
        if self.entry not in self.functions:
            raise ValueError("entry must name a selected function body")
        root_node = self.functions[self.entry]
        root_id = RegionID(_key("function-body", self.definition(root_node).id.wire))
        try:
            self.function(self.entry, None)
            # Expand only referenced source candidates, not unrelated modules.
            expanded = {self.entry}
            index = 0
            failed_candidates = set()
            while index < len(self.pending_targets):
                _, _, name, _ = self.pending_targets[index]
                index += 1
                if name is None or name in expanded or name in failed_candidates:
                    continue
                checkpoint = self.checkpoint()
                try:
                    self.function(name, root_id)
                except _Unsupported as error:
                    self.restore(checkpoint)
                    failed_candidates.add(name)
                    self.gap(error.kind, error.node, "candidate body: " + error.detail)
                else:
                    expanded.add(name)
            available = {region.id for region in self.regions}
            operations = {operation.id: operation for operation in self.operations}
            regions = {region.id: region for region in self.regions}
            for operation, callee, name, node in self.pending_targets:
                definition = self.definition(self.functions[name]) if name in self.functions else None
                candidate = RegionID(_key("function-body", definition.id.wire)) if definition else None
                candidate = candidate if candidate in available else None
                arguments, results = (), ()
                if candidate is not None:
                    arguments, results = self.candidate_bindings(operations[operation], regions[candidate],
                                                                  self.functions[name], node)
                binding_use = self.old_operation(node.func).binding_use
                self.targets.append(CallTarget(operation, callee, candidate if candidate in available else None,
                                               definition.id if definition else None,
                                               EvidenceKind.INFERRED, _ASSUMPTIONS,
                                               arguments, results, binding_use))
            graph = ProgramGraph(root_id, tuple(self.regions), tuple(self.operations), tuple(self.values),
                                 (StateLocation(self.world, "coarse Python/external world", stability=Stability.UNKNOWN),))
            require_valid(graph)
        except _Unsupported as error:
            self.gap(error.kind, error.node, error.detail)
            graph = None
            # A rejected body has diagnostics, not dangling links into a graph
            # that was never emitted. Preserve the source layers and all gaps.
            self.operation_links.clear()
            self.value_links.clear()
            self.use_links.clear()
            self.targets.clear()
        metadata = LoweringMetadata(self.entry, self.snapshot, tuple(self.operation_links),
                                   tuple(self.value_links), tuple(self.targets), tuple(self.gaps),
                                   _ASSUMPTIONS, tuple(self.use_links))
        return SourceProgram(graph, metadata, self.semantic, self.semantics, self.control)

    def candidate_bindings(self, operation, region, function, node):
        """Conditional interface correspondence, never confirmation of a target."""
        parameters = function.args.posonlyargs + function.args.args
        entry = next(block for block in region.blocks if block.id == region.entry)
        if (len(node.args) > len(parameters) or len(node.args) + len(node.keywords) != len(parameters)):
            return (), ()
        parameter_index = {parameter.arg: index for index, parameter in enumerate(parameters)}
        actuals = {index: operation.invoke_arguments[index + 1] for index in range(len(node.args))}
        for index, keyword in enumerate(node.keywords):
            formal = parameter_index.get(keyword.arg)
            if formal is None or formal < len(function.args.posonlyargs) or formal in actuals:
                return (), ()
            actuals[formal] = operation.invoke_arguments[1 + len(node.args) + index]
        if set(actuals) != set(range(len(parameters))):
            return (), ()
        arguments = tuple(CandidateArgument(actuals[index], entry.arguments[index])
                          for index in range(len(parameters)))
        arguments += (CandidateArgument(operation.invoke_arguments[-1], entry.arguments[-1]),)
        exit_types = {port.kind: port.types for port in region.exits}
        results = []
        for edge in operation.terminator.successors:
            signature = next(signature for signature in operation.completions if signature.kind is edge.kind)
            if exit_types.get(edge.kind) != signature.types:
                return (), ()
            for actual, formal in zip(edge.arguments, self.block_arguments[edge.block]):
                if isinstance(actual, CompletionResult):
                    results.append(CandidateResult(edge.kind, actual.index, formal))
        return arguments, tuple(results)

    def checkpoint(self):
        return tuple(len(items) for items in (self.regions, self.operations, self.values,
            self.operation_links, self.value_links, self.use_links, self.pending_targets, self.gaps))

    def restore(self, checkpoint):
        for items, length in zip((self.regions, self.operations, self.values,
                self.operation_links, self.value_links, self.use_links, self.pending_targets, self.gaps), checkpoint):
            del items[length:]
        self.values_by_id = {value.id: value for value in self.values}


def _span_atom(atom):
    r = atom.reference
    return atom.kind, r.start_line, r.end_line, r.start_column, r.end_column


def lower_source(path: str | Path, entry: str, *, max_operations: int = 10000) -> SourceProgram:
    if type(entry) is not str or not entry:
        raise ValueError("entry must be a nonempty function-body name")
    if type(max_operations) is not int or max_operations < 1 or max_operations > 100000:
        raise ValueError("max_operations must be an integer in [1, 100000]")
    path = Path(path).resolve()
    if path.stat().st_size > 4_000_000:
        raise ValueError("source exceeds the existing 4 MB control-model input budget")
    with tokenize.open(path) as stream:
        text = stream.read()
    semantic = build_semantic_files((path,), path.parent).graph
    sources = {str(path): text}
    semantics = extract_source_semantics(semantic, sources=sources)
    control = build_source_control_flow(semantic, semantics, sources=sources)
    builder = _Builder(path, entry, text, semantic, semantics, control, max_operations)
    return builder.run()


def validate_source_program(result: SourceProgram, *, max_operations: int = 10000):
    """Rebuild from current source; reported provenance cannot raise this budget."""
    try:
        if type(result) is not SourceProgram:
            raise ValueError("expected SourceProgram")
        errors = record_errors(result.metadata, LoweringMetadata, "metadata")
        if errors:
            return {"valid": False, "errors": errors}
        result.semantic.assert_valid()
        source_check = validate_source_semantics(result.semantics, result.semantic)
        if not source_check["valid"]:
            return source_check
        control_check = validate_source_control_flow(result.control, result.semantic, result.semantics)
        if not control_check["valid"]:
            return control_check
        if result.graph is not None:
            require_valid(result.graph)
            ops = {op.id: op for op in result.graph.operations}
            values = {value.id for value in result.graph.values}
            if {link.operation for link in result.metadata.operation_links} != set(ops):
                raise ValueError("source operation correspondence is incomplete")
            if {link.value for link in result.metadata.value_links} != values:
                raise ValueError("source value correspondence is incomplete")
            if {(link.operation, link.use) for link in result.metadata.use_links} != {
                    (op.id, use.id) for op in ops.values() for use in op.uses}:
                raise ValueError("source use correspondence is incomplete")
        rebuilt = lower_source(result.metadata.source.path, result.metadata.entry, max_operations=max_operations)
        if _canonical(result.to_dict()) != _canonical(rebuilt.to_dict()):
            raise ValueError("program graph or typed source correspondence differs from source replay")
    except (ValueError, TypeError, KeyError, AttributeError, OSError, SyntaxError, RecursionError) as error:
        return {"valid": False, "errors": [str(error)]}
    return {"valid": True, "errors": []}


__all__ = ["SourceProgram", "lower_source", "validate_source_program"]
