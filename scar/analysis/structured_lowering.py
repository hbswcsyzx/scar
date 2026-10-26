"""Source-to-core construction with explicit local binding and loop ports.

This is a versioned synchronous language profile.  Its supported operations
are constructed from source, never from workload names or live Tensor data.
Unknown language constructs remain explicit coverage failures; they are not
silently executed as ordinary fallthrough or certified as effect free.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field

from scar.analysis.program_lowering import _Builder, _Unsupported, _key, _REF, _BOOL, _Cursor, LoweredSourceBody
from scar.ir.program.bindings import BindingDefinition, BindingRead, BindingState
from scar.ir.program.functions import BodyEntryInterface, BodyLoweringProfile, FormalPort
from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, LocalBindingValue, Operation,
    OperationResult, ProgramGraph, ReferenceValue, Region, Stability, StateAccess,
    StateLocation, StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseRole,
    value_type,
)
from scar.ir.program.source import CallTarget, GapKind, LoweringMetadata, SourceRole
from scar.ir.program.structured import (
    ControlEdgeReference, LoopBindingPort, LoopInterface, LoopKind,
    PythonProtocol, PythonProtocolKind, StructuredBodyModel,
)
from scar.ir.program.validation import require_valid
from scar.ir.program.source_language import FUNCTION_TRY_PROTOCOLS, NESTED_FUNCTION_PROTOCOLS, FUNCTION_IMPORT_PROTOCOLS, FUNCTION_WITH_PROTOCOLS, FUNCTION_SET_PROTOCOLS
from scar.ir.v2.common import EvidenceKind


@dataclass
class _Loop:
    node: object
    kind: LoopKind
    header: _Cursor
    names: tuple[str, ...]
    body_entry: BlockID
    natural_exit: BlockID
    after: _Cursor | None = None
    backedges: list = field(default_factory=list)
    breaks: list = field(default_factory=list)
    continues: list = field(default_factory=list)
    iterator: ValueID | None = None


class StructuredBuilder(_Builder):
    def __init__(self, context, entry, *, source=None, max_operations=10000, sealed_source=None,
                 language_options=None):
        if sealed_source is not None:
            sealed_source._require_inputs(context.semantic, context.control)
        self.sealed_source = sealed_source
        super().__init__(context.path, entry, context.text, context.semantic, context.semantics,
                         context.control, max_operations, selected_source=source,
                         tree=context.tree, symbol_tables=context.symbol_tables,
                         expand_candidates=False, profile=BodyLoweringProfile.STRUCTURED_BODY,
                         source_index=context._lowering_index if sealed_source is not None else None)
        self.binding_definitions = []
        self.binding_reads = []
        self.known_binding_states = {}
        self.protocols = []
        self.loops = []
        self.loop_stack = []
        self.active_temporaries = []
        self.operation_records = {}
        if language_options is not None:
            from scar.analysis.source_language import SourceLanguageOptions
            if type(language_options) is not SourceLanguageOptions:
                raise TypeError("extended source language requires explicit SourceLanguageOptions")
        self.language_options = language_options
        self.language_namespace_root = str(context.root)
        self.language_unpackings = []
        self.language_slices = []
        self.language_constants = []
        self.language_compiler_locals = []

    def has_language(self, name):
        return self.language_options is not None and any(
            item.name == name for item in self.language_options.capabilities)

    def language_overlay(self, graph):
        if self.language_options is None:
            return None
        from scar.ir.program.source_language import SourceLanguageOverlay
        return SourceLanguageOverlay(self.snapshot, self.language_options.capabilities,
            tuple(self.language_unpackings) if graph is not None else (),
            tuple(self.language_slices) if graph is not None else (),
            tuple(self.language_constants) if graph is not None else (),
            tuple(self.language_compiler_locals),
            self.language_options.code_evidence.to_dict() if self.language_options.code_evidence else None,
            namespace_root=self.language_namespace_root,
            version='PYTHON_SOURCE_LANGUAGE_V2' if self.has_language('LAMBDA_EXPRESSION_314_V1') else 'PYTHON_SOURCE_LANGUAGE_V1',
            lambda_bodies=tuple(getattr(self,'lambda_bodies',())) if graph is not None else ())

    def emit(self, cursor, operation, node, role, old=None):
        super().emit(cursor, operation, node, role, old=old)
        self.operation_records[operation.id] = operation

    def protocol(self, operation, kind, node):
        self.protocols.append(PythonProtocol(operation, kind, self.source(node)))

    def use(self, operation, value, node, role, index, *, semantic_value=None):
        if isinstance(self.values_by_id[value], LocalBindingValue):
            from scar.ir.program.source import UseSource
            use = Use(self.fresh(UseID, "binding-use"), value, UseRole.LOCAL_BINDING)
            self.use_links.append(UseSource(operation, use.id, self.source(node), role, index, semantic_value))
            return use
        return super().use(operation, value, node, role, index, semantic_value=semantic_value)

    def new_block(self, node, *, named=(), role=SourceRole.CONTROL, extra_types=()):
        cursor = super().new_block(node, role=role, extra_types=extra_types)
        if not named:
            return cursor
        # Compiler binding tokens carry an entire slot binding, including its
        # possibly-unbound state.  They are not optional Python references.
        existing = self.block_arguments[cursor.block]
        tokens = []
        for index, name in enumerate(named):
            slot = self.slots.get((self.function_definition.id, name))
            if slot is None:
                raise _Unsupported(GapKind.SOURCE_MAPPING, node, "ordinary local has no parsed slot: " + name)
            token = LocalBindingValue(self.fresh(ValueID, "binding-argument"), self.function_context,
                                      BlockArgument(cursor.block, index), slot)
            self.add_value(token); tokens.append(token.id); cursor.env[name] = token.id
            self.link_value(token, node, role, slot=slot)
        # The old helper has emitted value records for the extra/state ports;
        # move their argument indices without inventing a second definition.
        from dataclasses import replace
        for value_id in existing:
            value = self.values_by_id[value_id]
            shifted = replace(value, origin=BlockArgument(cursor.block, value.origin.index + len(tokens)))
            self.replace_value(shifted)
        self.block_arguments[cursor.block] = tuple(tokens) + existing
        return cursor

    def frame_transition(self, cursor, node, references, kind):
        operation_id = self.fresh(OperationID, "structured-frame")
        uses = tuple(self.use(operation_id, value, child, role, index)
                     for index, (value, child, role) in enumerate(references))
        before = self.use(operation_id, cursor.state, node, "frame-world", 0)
        after = StateVersionValue(self.fresh(ValueID, "frame-state"), self.function_context,
                                  OperationResult(operation_id, 0), self.world)
        self.add_value(after); self.link_value(after, node, SourceRole.STATE)
        op = Operation(operation_id, "structured-frame", (Behavior.READ, Behavior.WRITE, Behavior.MEMORY),
                       uses + (before,), (after.id,),
                       (StateAccess(self.world, before.id, AccessMode.READ_WRITE, after.id),),
                       effects_complete=False)
        self.emit(cursor, op, node, SourceRole.LOCAL_BINDING)
        self.protocol(operation_id, kind, node)
        cursor.state = after.id
        return operation_id

    def define_binding(self, name, cursor, node, reference=None):
        slot = self.slots.get((self.function_definition.id, name))
        if slot is None:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node, "ordinary local has no parsed slot: " + name)
        operation_id = self.fresh(OperationID, "binding-definition")
        uses = () if reference is None else (self.use(operation_id, reference, node, "bound-reference", 0),)
        token = LocalBindingValue(self.fresh(ValueID, "local-binding"), self.function_context,
                                  OperationResult(operation_id, 0), slot)
        self.add_value(token)
        self.link_value(token, node, SourceRole.LOCAL_BINDING, slot=slot)
        self.emit(cursor, Operation(operation_id, "local-binding", (Behavior.COMPUTE,), uses,
                                    (token.id,), effects_complete=True), node, SourceRole.LOCAL_BINDING)
        state = BindingState.UNBOUND if reference is None else BindingState.BOUND
        self.binding_definitions.append(BindingDefinition(token.id, state, uses[0].id if uses else None))
        self.known_binding_states[token.id] = state
        cursor.env[name] = token.id
        return token.id

    def frame_exit_references(self, cursor, node, value):
        """Ordered retained inputs, independent of a function entry ABI.

        Mapping-frame construction extends this list with its actual entry
        ports. This default preserves the historical function-frame contract.
        """
        refs = [(value, node, "held-payload")]
        refs.extend((cursor.env[name], node, "held-local") for name in sorted(cursor.env))
        refs.extend((value, node, "held-temporary") for value in self.active_temporaries)
        return refs

    def finish_exit(self, cursor, node, value, kind, *, binding=None):
        refs = self.frame_exit_references(cursor, node, value)
        self.frame_transition(cursor, node, refs, PythonProtocolKind.FRAME_EXIT)
        operation_id = self.fresh(OperationID, "structured-exit")
        uses = (self.use(operation_id, value, node, "result", 0),
                self.use(operation_id, cursor.state, node, "state", 0))
        if binding is not None:
            token_use = self.use(operation_id, binding, node, "unbound-local", 0)
            uses += (token_use,)
            self.binding_reads.append(BindingRead(operation_id, token_use.id, None))
        terminator = Terminator(TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE,
                                exit=kind.value.lower(), values=tuple(use.id for use in uses[:2]))
        self.emit(cursor, Operation(operation_id, kind.value, (Behavior.CONTROL,), uses,
                                    terminator=terminator), node,
                  SourceRole.RETURN if kind is ExitKind.NORMAL else SourceRole.EXCEPTION)
        return operation_id

    def invoke(self, cursor, node, inputs, *, role=SourceRole.EXPRESSION, old=None,
               result_type=_REF, failure_handler=None):
        normal, results, operation = self.invoke_results(cursor, node, inputs, role=role, old=old,
            result_types=(result_type,) if result_type else (), failure_handler=failure_handler)
        return normal, results[0] if results else None, operation

    def invoke_results(self, cursor, node, inputs, *, role=SourceRole.EXPRESSION, old=None,
                       result_types=(), failure_handler=None):
        if type(result_types) is not tuple:
            raise TypeError("normal payload types must be an explicit tuple")
        operation_id = self.fresh(OperationID, "structured-invoke")
        uses = [self.use(operation_id, value, child, input_role, index, semantic_value=static)
                for value, child, input_role, index, static in inputs]
        uses.append(self.use(operation_id, cursor.state, node, "state", 0))
        normal = self.new_block(node, role=role, extra_types=result_types)
        failure = self.new_block(node, role=SourceRole.EXCEPTION, extra_types=self.raise_payload_types())
        normal.env = dict(cursor.env); failure.env = dict(cursor.env)
        signatures = (CompletionSignature(ExitKind.NORMAL, result_types + (self.state_type,)),
                      CompletionSignature(ExitKind.RAISE, self.raise_payload_types() + (self.state_type,)))
        edges = tuple(CompletionSuccessor(signature.kind, target.block,
                      tuple(CompletionResult(index) for index in range(len(signature.types))))
                      for signature, target in zip(signatures, (normal, failure)))
        op = Operation(operation_id, role.value, (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
                       tuple(uses), effects_complete=False,
                       terminator=Terminator(TerminatorKind.INVOKE, edges),
                       completions=signatures, invoke_arguments=tuple(use.id for use in uses))
        self.emit(cursor, op, node, role, old=old)
        exception = self.failure_payload(self.block_arguments[failure.block][:-1])
        if failure_handler is None:
            self.finish_exit(failure, node, exception, ExitKind.RAISE)
        else:
            failure_handler(failure, exception)
        return normal, tuple(self.block_arguments[normal.block][:-1]), operation_id

    def raise_payload_types(self):
        return (_REF,)

    def failure_payload(self, values):
        return values[0]

    def exception_reference(self, payload):
        return payload

    def failure_references(self, payload):
        return (payload,)

    def invoke_protocol(self, cursor, node, values, kind, *, result_type=_REF, failure_handler=None):
        inputs = tuple((value, node, "protocol-input", index, None) for index, value in enumerate(values))
        normal, result, operation = self.invoke(cursor, node, inputs, result_type=result_type,
                                                failure_handler=failure_handler)
        self.protocol(operation, kind, node)
        return normal, result, operation

    def read_local(self, node, cursor, old):
        binding = cursor.env[node.id]
        known = self.known_binding_states.get(binding)
        if known is BindingState.UNBOUND:
            cursor, error, _ = self.invoke_protocol(cursor, node, (), PythonProtocolKind.MAKE_UNBOUND_LOCAL_ERROR)
            self.finish_exit(cursor, node, error, ExitKind.RAISE, binding=binding)
            return None, None
        if known is BindingState.BOUND:
            operation_id = self.fresh(OperationID, "read-bound-local")
            use = self.use(operation_id, binding, node, "local-binding", 0)
            value = ReferenceValue(self.fresh(ValueID, "local-reference"), self.function_context,
                                   OperationResult(operation_id, 0))
            self.add_value(value); self.link_value(value, node, SourceRole.EXPRESSION,
                                                  semantic_value=old.result if old is not None else None)
            self.emit(cursor, Operation(operation_id, "read-local", (Behavior.COMPUTE,), (use,),
                                        (value.id,), effects_complete=True), node, SourceRole.EXPRESSION, old=old)
            self.binding_reads.append(BindingRead(operation_id, use.id, value.id))
            return cursor, value.id
        normal, value, operation_id = self.invoke(cursor, node,
            ((binding, node, "local-binding", 0, None),), old=old)
        self.binding_reads.append(BindingRead(operation_id,
            self.operation_records[operation_id].uses[0].id, value))
        return normal, value

    def expr(self, node, cursor):
        if isinstance(node, ast.Name) and node.id in cursor.env:
            return self.read_local(node, cursor, self.old_operation(node))
        if isinstance(node, (ast.Constant, ast.Name)):
            return super().expr(node, cursor)
        old = self.old_operation(node)
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
        elif (isinstance(node, ast.Call) and not any(isinstance(arg, ast.Starred) for arg in node.args)
                and all(keyword.arg is not None for keyword in node.keywords)):
            children = [node.func, *node.args, *(keyword.value for keyword in node.keywords)]
        else:
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node,
                               "structured expression protocol still required for " + type(node).__name__)
        old, children_and_operands = self.ordered_expression_inputs(node, children, old)
        inputs = []
        for child, role, index, static in children_and_operands:
            cursor, value = self.expr(child, cursor)
            if cursor is None:
                return None, None
            inputs.append((value, child, role, index, static))
        self.gap(GapKind.DYNAMIC_DISPATCH, node,
                 "source operation is connected; runtime dispatch, state accesses and effects remain unproved")
        cursor, value, operation = self.invoke(cursor, node, inputs, old=old)
        self.associate_expression(operation, node, old)
        if isinstance(node, ast.Call):
            callee = inputs[0][0]
            self.pending_targets.append((operation, callee, self.reference_candidates.get(callee), node))
            self.gap(GapKind.DYNAMIC_TARGET, node, "candidate source is not verified runtime dispatch")
        return cursor, value

    def ordered_expression_inputs(self, node, children, old):
        """Default function adapter requires the original computational overlay."""
        if len(children) != len(old.operands):
            raise _Unsupported(GapKind.SOURCE_MAPPING, node, "source operands differ from typed source semantics")
        return old, tuple((child, operand.role, operand.index, operand.value)
                          for child, operand in zip(children, old.operands))

    def associate_expression(self, operation, node, old):
        """Source adapters may link an exact SG definition without inventing IR."""

    def store(self, target, value, cursor):
        if not isinstance(target, ast.Name) or target.id not in self.locals:
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, target,
                               "structured heap/global/destructuring writes require their own typed protocol")
        previous = cursor.env[target.id]
        self.frame_transition(cursor, target,
            ((previous, target, "previous-binding"), (value, target, "assigned-reference")),
            PythonProtocolKind.FRAME_BIND)
        self.define_binding(target.id, cursor, target, value)
        return cursor

    def jump(self, cursor, target, names, node):
        operation_id = self.fresh(OperationID, "structured-jump")
        uses = tuple(self.use(operation_id, cursor.env[name], node, "carried-binding", index)
                     for index, name in enumerate(names))
        uses += (self.use(operation_id, cursor.state, node, "state", 0),)
        self.emit(cursor, Operation(operation_id, "jump", (Behavior.CONTROL,), uses,
            terminator=Terminator(TerminatorKind.JUMP,
                (Successor(target.block, tuple(use.id for use in uses)),))), node, SourceRole.CONTROL)
        return ControlEdgeReference(operation_id, 0)

    def branch(self, cursor, boolean, yes, no, node):
        operation_id = self.fresh(OperationID, "structured-branch")
        uses = (self.use(operation_id, boolean, node, "condition", 0),
                self.use(operation_id, cursor.state, node, "true-state", 0),
                self.use(operation_id, cursor.state, node, "false-state", 0))
        self.emit(cursor, Operation(operation_id, "branch", (Behavior.CONTROL,), uses,
            terminator=Terminator(TerminatorKind.BRANCH,
                (Successor(yes.block, (uses[1].id,)), Successor(no.block, (uses[2].id,))),
                condition=uses[0].id)), node, SourceRole.CONTROL)
        yes.env = dict(cursor.env); no.env = dict(cursor.env)

    def merge(self, cursors, names, node):
        if not cursors:
            return None
        if len(cursors) == 1:
            return cursors[0]
        merged = tuple(name for name in names if len({cursor.env[name] for cursor in cursors}) > 1)
        target = self.new_block(node, named=merged, role=SourceRole.MERGE)
        target.env.update({name: cursors[0].env[name] for name in names if name not in merged})
        for cursor in cursors:
            self.jump(cursor, target, merged, node)
        return target

    def loop_after(self, loop):
        if loop.after is None:
            loop.after = self.new_block(loop.node, named=loop.names, role=SourceRole.MERGE)
        return loop.after

    def record_loop(self, loop):
        self.loops.append(LoopInterface(self.source(loop.node), loop.kind, self.function_context,
            loop.header.block, loop.body_entry, loop.natural_exit,
            loop.after.block if loop.after is not None else None,
            tuple(LoopBindingPort(self.values_by_id[loop.header.env[name]].slot, loop.header.env[name])
                  for name in loop.names), tuple(loop.backedges), tuple(loop.breaks), tuple(loop.continues)))

    def condition(self, node, cursor):
        cursor, value = self.expr(node, cursor)
        if cursor is None:
            return None, None
        cursor, boolean, _ = self.invoke_protocol(cursor, node, (value,),
                                                  PythonProtocolKind.TRUTH, result_type=_BOOL)
        return cursor, boolean

    def while_statement(self, node, cursor):
        names = tuple(sorted(cursor.env))
        header = self.new_block(node, named=names)
        self.jump(cursor, header, names, node)
        tested, boolean = self.condition(node.test, header)
        if tested is None:
            return None
        body, natural = self.new_block(node), self.new_block(node)
        self.branch(tested, boolean, body, natural, node)
        loop = _Loop(node, LoopKind.WHILE, header, names, body.block, natural.block)
        self.loop_stack.append(loop)
        body = self.statements(node.body, body)
        self.loop_stack.pop()
        if body is not None:
            loop.backedges.append(self.jump(body, header, names, node))
        natural = self.statements(node.orelse, natural)
        if natural is not None:
            self.jump(natural, self.loop_after(loop), names, node)
        self.record_loop(loop)
        return loop.after

    def for_statement(self, node, cursor):
        cursor, iterable = self.expr(node.iter, cursor)
        if cursor is None:
            return None
        cursor, iterator, _ = self.invoke_protocol(cursor, node.iter, (iterable,), PythonProtocolKind.GET_ITERATOR)
        self.frame_transition(cursor, node, ((iterator, node, "iterator-hold"),),
                              PythonProtocolKind.FRAME_HOLD_TEMPORARY)
        self.active_temporaries.append(iterator)
        names = tuple(sorted(cursor.env))
        header = self.new_block(node, named=names)
        self.jump(cursor, header, names, node)
        natural = self.new_block(node)

        def exhausted_or_raise(failure, exception):
            operation_id = self.fresh(OperationID, "stop-iteration-match")
            use = self.use(operation_id, self.exception_reference(exception), node, "exception", 0)
            before = self.use(operation_id, failure.state, node, "exception-type-state", 0)
            boolean = DataValue(self.fresh(ValueID, "matches-stop"), self.function_context,
                                OperationResult(operation_id, 0), "builtins.bool")
            self.add_value(boolean); self.link_value(boolean, node, SourceRole.TRUTH)
            self.emit(failure, Operation(operation_id, "match-stop-iteration", (Behavior.COMPUTE, Behavior.READ),
                       (use, before), (boolean.id,),
                       (StateAccess(self.world, before.id, AccessMode.READ),), effects_complete=True),
                      node, SourceRole.TRUTH)
            self.protocol(operation_id, PythonProtocolKind.MATCH_STOP_ITERATION, node)
            reraised = self.new_block(node)
            self.branch(failure, boolean.id, natural, reraised, node)
            self.frame_transition(natural, node, tuple((ref, node, "consumed-exhaustion") for ref in self.failure_references(exception)),
                                  PythonProtocolKind.FRAME_DISCARD)
            self.finish_exit(reraised, node, exception, ExitKind.RAISE)

        body, item, _ = self.invoke_protocol(header, node, (iterator,), PythonProtocolKind.ADVANCE_ITERATOR,
                                              failure_handler=exhausted_or_raise)
        loop = _Loop(node, LoopKind.FOR, header, names, body.block, natural.block, iterator=iterator)
        self.loop_stack.append(loop)
        body = self.store(node.target, item, body)
        body = self.statements(node.body, body)
        self.loop_stack.pop()
        if body is not None:
            loop.backedges.append(self.jump(body, header, names, node))
        self.active_temporaries.pop()
        self.frame_transition(natural, node, ((iterator, node, "exhausted-iterator"),),
                              PythonProtocolKind.FRAME_RELEASE_TEMPORARY)
        natural = self.statements(node.orelse, natural)
        if natural is not None:
            self.jump(natural, self.loop_after(loop), names, node)
        self.record_loop(loop)
        return loop.after

    def statements(self, statements, cursor):
        for node in statements:
            if cursor is None:
                self.gap(GapKind.SOURCE_COVERAGE, node,
                         "closed completion path: source remains indexed, no executable core operation emitted")
                continue
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                cursor, value = self.expr(node.value, cursor)
                if cursor is not None:
                    cursor = self.store(node.targets[0], value, cursor)
            elif isinstance(node, ast.Expr):
                cursor, value = self.expr(node.value, cursor)
                if cursor is not None:
                    self.frame_transition(cursor, node, ((value, node, "discarded-reference"),),
                                          PythonProtocolKind.FRAME_DISCARD)
            elif isinstance(node, ast.Pass):
                continue
            elif isinstance(node, ast.Return):
                if node.value is None:
                    value = self.literal(node, None)
                else:
                    cursor, value = self.expr(node.value, cursor)
                if cursor is not None:
                    self.finish_exit(cursor, node, value, ExitKind.NORMAL)
                cursor = None
            elif isinstance(node, ast.If):
                cursor, boolean = self.condition(node.test, cursor)
                if cursor is None:
                    continue
                yes, no = self.new_block(node), self.new_block(node)
                self.branch(cursor, boolean, yes, no, node)
                names = tuple(sorted(cursor.env))
                yes = self.statements(node.body, yes)
                no = self.statements(node.orelse, no)
                cursor = self.merge([branch for branch in (yes, no) if branch is not None], names, node)
            elif isinstance(node, ast.While):
                cursor = self.while_statement(node, cursor)
            elif isinstance(node, ast.For):
                cursor = self.for_statement(node, cursor)
            elif isinstance(node, (ast.Break, ast.Continue)):
                if not self.loop_stack:
                    raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, "loop transfer has no active loop")
                loop = self.loop_stack[-1]
                if isinstance(node, ast.Break):
                    if loop.iterator is not None:
                        self.frame_transition(cursor, node, ((loop.iterator, node, "broken-iterator"),),
                                              PythonProtocolKind.FRAME_RELEASE_TEMPORARY)
                    loop.breaks.append(self.jump(cursor, self.loop_after(loop), loop.names, node))
                else:
                    edge = self.jump(cursor, loop.header, loop.names, node)
                    loop.backedges.append(edge); loop.continues.append(edge)
                cursor = None
            else:
                raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node,
                    "structured control/effect protocol still required for " + type(node).__name__)
        return cursor

    def build_function(self):
        from scar.analysis.function_interfaces import formal_nodes
        node = self.functions[self.entry]
        if isinstance(node, ast.AsyncFunctionDef):
            raise _Unsupported(GapKind.UNSUPPORTED_SIGNATURE, node, "async completion/suspension interface is not implemented")
        def body_nodes(nodes):
            for child in nodes:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                    continue
                yield child
                yield from body_nodes(ast.iter_child_nodes(child))
        if any(isinstance(child, (ast.Yield, ast.YieldFrom)) for child in body_nodes(node.body)):
            raise _Unsupported(GapKind.UNSUPPORTED_SIGNATURE, node, "generator enter/yield/resume/close interface is not implemented")
        self.function_definition = self.definition(node)
        self.function_context = RegionID(_key("function-body", self.function_definition.id.wire, self.profile.value))
        self.function_blocks = []; self.reference_candidates = {}
        table = self.symbol_tables[(node.name, node.lineno)]
        if any(symbol.is_free() or symbol.is_nonlocal() for symbol in table.get_symbols()):
            raise _Unsupported(GapKind.UNSUPPORTED_SIGNATURE, node, "closure cell environment/state interface remains unconnected")
        self.locals = {symbol.get_name() for symbol in table.get_symbols() if symbol.is_local()}
        parameters = [argument for argument, _ in formal_nodes(node)]
        cursor = self.new_block(node)
        state = self.pop_value()
        args, ports, refs = [], [], []
        for index, parameter in enumerate(parameters):
            value = ReferenceValue(self.fresh(ValueID, "formal"), self.function_context, BlockArgument(cursor.block, index))
            slot = self.slots.get((self.function_definition.id, parameter.arg))
            if slot is None:
                raise _Unsupported(GapKind.SOURCE_MAPPING, parameter, "formal has no parsed slot")
            self.add_value(value); args.append(value.id); refs.append((value.id, parameter, "formal-reference"))
            self.link_value(value, parameter, SourceRole.PARAMETER, slot=slot)
            ports.append(FormalPort(slot, value.id))
        state = StateVersionValue(state.id, state.region, BlockArgument(cursor.block, len(args)), state.location)
        self.add_value(state); self.link_value(state, node, SourceRole.STATE)
        cursor.state = state.id; args.append(state.id); self.block_arguments[cursor.block] = tuple(args)
        self.interface = BodyEntryInterface(self.function_definition.id, self.function_context,
                                            tuple(ports), state.id, self.profile)
        self.frame_transition(cursor, node, refs, PythonProtocolKind.FRAME_ENTER)
        parameter_values = {parameter.arg: port.value for parameter, port in zip(parameters, ports)}
        for name in sorted(self.locals):
            parameter_node = next((p for p in parameters if p.arg == name), node)
            self.define_binding(name, cursor, parameter_node, parameter_values.get(name))
        self.gap(GapKind.FRAME_EFFECT, node, "frame interposition, lifetime, finalizers and noncompletion remain explicit unproved conditions")
        self.gap(GapKind.CODE_VERSION, node, "source is fixed; live function object, environment and definition-time effects remain unproved")
        statements = node.body
        if statements and isinstance(statements[0], ast.Expr) and isinstance(statements[0].value, ast.Constant) and type(statements[0].value.value) is str:
            statements = statements[1:]
        cursor = self.statements(statements, cursor)
        if cursor is not None:
            self.finish_exit(cursor, node, self.literal(node, None), ExitKind.NORMAL)
        blocks = tuple(Block(block, self.block_arguments[block], tuple(self.block_operations[block])) for block in self.function_blocks)
        completed = {operation.terminator.kind for operation in self.operations if operation.terminator is not None}
        exits = tuple(ExitPort(kind.value.lower(), kind, (_REF, self.state_type)) for kind, terminator in
                      ((ExitKind.NORMAL, TerminatorKind.RETURN), (ExitKind.RAISE, TerminatorKind.RAISE))
                      if terminator in completed)
        self.regions.append(Region(self.function_context, self.entry, self.interface_region_entry(), blocks, exits))
        return node

    def interface_region_entry(self):
        return self.values_by_id[self.interface.world].origin.block

    def assemble_region(self, entry_world):
        """Assemble existing core blocks/exits without choosing an entry ABI."""
        blocks = tuple(Block(block, self.block_arguments[block], tuple(self.block_operations[block]))
                       for block in self.function_blocks)
        completed = {op.terminator.kind for op in self.operations if op.terminator is not None}
        exits = tuple(ExitPort(kind.value.lower(), kind, (_REF, self.state_type))
                      for kind, terminator in ((ExitKind.NORMAL, TerminatorKind.RETURN),
                                              (ExitKind.RAISE, TerminatorKind.RAISE))
                      if terminator in completed)
        return Region(self.function_context, self.entry, self.values_by_id[entry_world].origin.block,
                      blocks, exits)

    def make_graph(self):
        """Assemble canonical core; newer profiles may add existing interfaces."""
        return ProgramGraph(self.function_context, tuple(self.regions), tuple(self.operations), tuple(self.values),
            (StateLocation(self.world, "coarse Python/external world", stability=Stability.UNKNOWN),),
            binding_definitions=tuple(self.binding_definitions), binding_reads=tuple(self.binding_reads))

    def run(self):
        if self.entry not in self.functions:
            raise ValueError("entry must name a selected function body")
        structured = graph = None
        try:
            node = self.build_function()
            for operation, callee, candidate, call in self.pending_targets:
                definition = self.definition(self.functions[candidate]) if candidate in self.functions else None
                old_callees = self.old_by_atom.get(self.source(call.func).atom_id, ())
                if len(old_callees) > 1:
                    raise _Unsupported(GapKind.SOURCE_MAPPING, call.func,
                                       "callable has ambiguous computational source records")
                self.targets.append(CallTarget(operation, callee, None, definition.id if definition else None,
                    EvidenceKind.INFERRED, self.assumptions(), (), (),
                    old_callees[0].binding_use if old_callees else None))
            graph = self.make_graph()
            structured = StructuredBodyModel(self.function_definition.id, self.function_context, self.source(node),
                                              tuple(self.protocols), tuple(self.loops))
        except _Unsupported as error:
            self.gap(error.kind, error.node, error.detail)
            self.operation_links.clear(); self.clear_value_links(); self.use_links.clear(); self.targets.clear()
            self.interface = None
        metadata = LoweringMetadata(self.entry, self.snapshot, tuple(self.operation_links), tuple(self.value_links),
                                    tuple(self.targets), tuple(self.gaps), self.assumptions(), tuple(self.use_links))
        if graph is not None:
            # This complete check also validates the canonical core; callers of
            # PreparedSource.lower receive a fully checked constructed body.
            _require_valid_structured_body(structured, graph, self.interface, metadata,
                semantic=self.semantic, control=self.control, sealed_source=self.sealed_source,
                language=self.language_overlay(graph), source_tree=self.tree,
                language_options=self.language_options)
        return LoweredSourceBody(graph, metadata, self.operations_emitted, self.interface, None, structured,
                                 self.language_overlay(graph))

    @staticmethod
    def assumptions():
        from scar.analysis.program_lowering import _ASSUMPTIONS
        return _ASSUMPTIONS


def require_valid_structured_body(model, graph, interface, metadata, *, semantic, control,
                                  language=None, source_tree=None, language_options=None, structural_only=False):
    """Validate typed overlay endpoints; exact source replay is a separate gate."""
    # Public validation always checks caller-owned mutable source layers.
    return _require_valid_structured_body(model, graph, interface, metadata,
        semantic=semantic, control=control, language=language, source_tree=source_tree,
        language_options=language_options, structural_only=structural_only)


def _require_valid_structured_body(model, graph, interface, metadata, *, semantic, control,
                                   sealed_source=None, language=None, source_tree=None, language_options=None,
                                   structural_only=False):
    if language is None:
        from scar.ir.program.source_language import reject_extended_protocols
        reject_extended_protocols(model)
    from scar.ir.v2._validation import record_errors
    errors = record_errors(model, StructuredBodyModel, "structured")
    if errors:
        raise ValueError("; ".join(errors))
    if sealed_source is None:
        checked_control = control.validate(semantic=semantic)
        if not checked_control["valid"]:
            raise ValueError("structured loop source control must be independently well formed")
    else:
        from scar.analysis.program_lowering import _SealedLoweringSession
        if type(sealed_source) is not _SealedLoweringSession:
            raise TypeError("source reuse requires the local sealed construction session")
        sealed_source._require_inputs(semantic, control)
    # Every newly constructed core, interface, protocol and correspondence is
    # still checked below. Only the unchanged private source layer is reused.
    require_valid(graph)
    delegated = set()
    if language is not None:
        if language.lambda_bodies:
            from scar.analysis.source_lambda_validation import validate_lambda_regions,root_projection as lambda_projection
            delegated.update(validate_lambda_regions(model,graph,interface,metadata,semantic,control,language,
                source_tree=source_tree,options=language_options,structural_only=structural_only,sealed_source=sealed_source))
            model,graph,metadata,language=lambda_projection(model,graph,metadata,language,delegated)
        from scar.ir.program.source_language import SourceLanguageCapability
        if any(c in language.capabilities for c in (SourceLanguageCapability.GENEXPR_314_V1,
                SourceLanguageCapability.GENEXPR_CREATION_314_V1)):
            from scar.analysis.source_generator_validation import validate_generator_regions, root_projection
            delegated.update(validate_generator_regions(model, graph, interface, metadata, semantic, language,
                source_tree=source_tree, options=language_options, structural_only=structural_only))
            model, graph, metadata, language = root_projection(model, graph, metadata, language, delegated)
    environment_profile = interface.profile is BodyLoweringProfile.STRUCTURED_ENV
    if (interface.profile not in (BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV) or model.region != graph.root
            or model.definition != interface.definition or model.region != interface.region):
        raise ValueError("structured body/interface/root identities differ")
    operations = {op.id: op for op in graph.operations}
    regions = {region.id: region for region in graph.regions}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    values = {value.id: value for value in graph.values}
    operation_blocks = {operation: block for region in graph.regions for block in region.blocks
                        for operation in block.operations}
    links = {link.operation: link for link in metadata.operation_links}
    if set(links) != set(operations):
        raise ValueError("structured source correspondence must cover every operation")
    for link in metadata.operation_links:
        atom = semantic.source_atoms.get(link.source.atom_id)
        if atom is None or atom.reference != link.source:
            raise ValueError("structured operation source differs from its independently parsed atom")
    binding_producers = {values[definition.value].origin.operation for definition in graph.binding_definitions}
    binding_readers = {read.operation for read in graph.binding_reads}
    synthetic = {operation.id for operation in graph.operations
        if links[operation.id].semantic_operation is None
        and operation.id not in delegated
        and operation.id not in binding_producers | binding_readers
        and (operation.terminator is None or operation.terminator.kind is TerminatorKind.INVOKE)}
    protocol_ids = {protocol.operation for protocol in model.protocols}
    if (not synthetic <= protocol_ids or not environment_profile and protocol_ids != synthetic):
        raise ValueError("every synthetic source operation requires its exact typed protocol")
    for protocol in model.protocols:
        if protocol.operation not in operations or links.get(protocol.operation) is None or links[protocol.operation].source != protocol.source:
            raise ValueError("structured protocol has no matching source/core operation")
        operation = operations[protocol.operation]
        inputs = [use for use in operation.uses if not isinstance(values[use.value], StateVersionValue)]
        frame_kinds = (PythonProtocolKind.FRAME_ENTER, PythonProtocolKind.FRAME_BIND,
                       PythonProtocolKind.FRAME_DISCARD, PythonProtocolKind.FRAME_EXIT,
                       PythonProtocolKind.FRAME_HOLD_TEMPORARY, PythonProtocolKind.FRAME_RELEASE_TEMPORARY)
        if protocol.kind in frame_kinds:
            if (operation.terminator is not None or operation.callee is not None
                    or set(operation.behaviors) != {Behavior.READ, Behavior.WRITE, Behavior.MEMORY}
                    or operation.effects_complete or len(operation.accesses) != 1):
                raise ValueError("frame protocol requires an incomplete ordinary lifetime operation")
            access = operation.accesses[0]
            if (access.mode is not AccessMode.READ_WRITE or access.full_overwrite
                    or access.reference is not None or operation.results != (access.after,)):
                raise ValueError("frame protocol must advance its whole coarse world")
            if protocol.kind is PythonProtocolKind.FRAME_ENTER:
                entry = blocks[regions[graph.root].entry]
                expected_enter = (entry.arguments[:-1] if environment_profile else
                                  tuple(port.value for port in interface.parameters))
                if entry.operations[0] != operation.id or tuple(use.value for use in inputs) != expected_enter:
                    raise ValueError("frame enter must first hold the exact bound formals")
            elif protocol.kind is PythonProtocolKind.FRAME_BIND:
                if (len(inputs) != 2 or not isinstance(values[inputs[0].value], LocalBindingValue)
                        or not isinstance(values[inputs[1].value], ReferenceValue)):
                    raise ValueError("frame bind needs previous binding and assigned reference")
            elif protocol.kind in (PythonProtocolKind.FRAME_DISCARD, PythonProtocolKind.FRAME_HOLD_TEMPORARY,
                                    PythonProtocolKind.FRAME_RELEASE_TEMPORARY):
                if len(inputs) != 1 or not isinstance(values[inputs[0].value], ReferenceValue):
                    raise ValueError("frame discard needs one temporary reference")
            elif protocol.kind is PythonProtocolKind.FRAME_EXIT:
                block = operation_blocks[operation.id]
                if len(block.operations) < 2 or block.operations[-2] != operation.id:
                    raise ValueError("frame exit must immediately precede its completion")
                completion = operations[block.operations[-1]]
                if completion.terminator is None or completion.terminator.kind not in (TerminatorKind.RETURN, TerminatorKind.RAISE):
                    raise ValueError("frame exit must hold a returning or raising payload")
                if not inputs or not isinstance(values[inputs[0].value], ReferenceValue):
                    raise ValueError("frame exit needs a reference payload")
                uses = {use.id: use for use in completion.uses}
                ports = completion.terminator.values
                if uses[ports[0]].value != inputs[0].value or uses[ports[1]].value != access.after:
                    raise ValueError("completion must carry the frame payload and post-world")
        elif protocol.kind is PythonProtocolKind.MATCH_STOP_ITERATION:
            if (operation.terminator is not None or not operation.effects_complete
                    or len(inputs) != 1 or not isinstance(values[inputs[0].value], ReferenceValue)
                    or len(operation.results) != 1 or not isinstance(values[operation.results[0]], DataValue)
                    or values[operation.results[0]].data_type != "builtins.bool"
                    or len(operation.accesses) != 1 or operation.accesses[0].mode is not AccessMode.READ):
                raise ValueError("StopIteration matching requires a typed exception-to-bool operation")
        elif protocol.kind in (PythonProtocolKind.TRUTH, PythonProtocolKind.GET_ITERATOR,
                                PythonProtocolKind.ADVANCE_ITERATOR, PythonProtocolKind.MAKE_UNBOUND_LOCAL_ERROR):
            expected_inputs = 0 if protocol.kind is PythonProtocolKind.MAKE_UNBOUND_LOCAL_ERROR else 1
            if (operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE
                    or operation.effects_complete or len(inputs) != expected_inputs
                    or any(not isinstance(values[use.value], ReferenceValue) for use in inputs)):
                raise ValueError("Python protocol requires its typed operands and both stateful completions")
            signature = next(signature for signature in operation.completions if signature.kind is ExitKind.NORMAL)
            expected = _BOOL if protocol.kind is PythonProtocolKind.TRUTH else _REF
            if signature.types != (expected, value_type(values[interface.world])):
                raise ValueError("Python protocol normal completion payload type differs")
        elif environment_profile and protocol.kind in (
                PythonProtocolKind.LOOKUP_GLOBAL, PythonProtocolKind.READ_FREE_CELL,
                PythonProtocolKind.READ_LOCAL_CELL, PythonProtocolKind.MAKE_CELL,
                PythonProtocolKind.STORE_CELL, PythonProtocolKind.STORE_GLOBAL,
                PythonProtocolKind.STORE_ATTRIBUTE, PythonProtocolKind.STORE_SUBSCRIPT,
                PythonProtocolKind.MAKE_ASSERTION_ERROR, PythonProtocolKind.RERAISE,
                PythonProtocolKind.RAISE_EXCEPTION, PythonProtocolKind.RAISE_WITH_CAUSE,
                PythonProtocolKind.FSTRING_CONVERT, PythonProtocolKind.FSTRING_FORMAT,
                PythonProtocolKind.BUILD_STRING, PythonProtocolKind.BUILD_MAP,
                PythonProtocolKind.MAP_ADD, PythonProtocolKind.DICT_UPDATE):
            # Ownership, typed uses, state address and completion validation are
            # profile-specific; no legacy protocol is broadened by this branch.
            pass
        elif language is not None and protocol.kind in (
                PythonProtocolKind.UNPACK_FIXED, PythonProtocolKind.BUILD_SLICE,
                PythonProtocolKind.READ_CODE_CONSTANT, PythonProtocolKind.BUILD_CALL_POSITIONALS,
                PythonProtocolKind.DICT_MERGE, PythonProtocolKind.CALL_FUNCTION_EX,
                PythonProtocolKind.BUILD_CALL_POSITIONAL_LIST, PythonProtocolKind.EXTEND_CALL_POSITIONALS,
                PythonProtocolKind.APPEND_CALL_POSITIONAL, PythonProtocolKind.CALL_POSITIONALS_TO_TUPLE):
            pass  # Exact shapes, source, payloads and lifetime are checked below.
        elif language is not None and protocol.kind.value in FUNCTION_TRY_PROTOCOLS | NESTED_FUNCTION_PROTOCOLS | FUNCTION_IMPORT_PROTOCOLS | FUNCTION_WITH_PROTOCOLS | FUNCTION_SET_PROTOCOLS:
            pass  # Exact canonical C0/C1/source checks belong to the opt-in Try adapter.
        else:
            raise ValueError("opaque protocol has no implemented structured control interface")
    if environment_profile:
        from scar.analysis.source_environment_validation import validate_environment_body
        validate_environment_body(model, graph, interface, metadata, semantic, language=language)
        from scar.analysis.source_statement_lowering import validate_statement_protocols
        validate_statement_protocols(model, graph, interface, metadata, semantic, language=language)
        from scar.analysis.source_string_lowering import validate_string_protocols
        validate_string_protocols(model, graph, interface, metadata, semantic, language=language)
        from scar.analysis.source_mapping_lowering import validate_mapping_protocols
        validate_mapping_protocols(model, graph, interface, metadata, semantic, language=language)
    if language is not None:
        from scar.analysis.source_language_validation import validate_language_body
        validate_language_body(model, graph, interface, metadata, semantic, language,
                               source_tree=source_tree, options=language_options, structural_only=structural_only,
                               control=control,sealed_source=sealed_source)
    expected_loops = {link.source.atom_id for link in metadata.operation_links
        if semantic.source_atoms[link.source.atom_id].kind in ("While", "For")
        and operations[link.operation].terminator is not None
        and operations[link.operation].terminator.kind is TerminatorKind.BRANCH}
    if len({loop.source.atom_id for loop in model.loops}) != len(model.loops) or {loop.source.atom_id for loop in model.loops} != expected_loops:
        raise ValueError("structured loop interfaces must cover each emitted source loop control")
    if not model.loops:
        # All body/protocol and loop-coverage checks are complete. The remaining
        # predecessor/dominance analysis is used only by loop-interface checks.
        return
    predecessors = {block: set() for block in blocks}
    incoming = []
    for operation in graph.operations:
        if operation.terminator is not None:
            for index, edge in enumerate(operation.terminator.successors):
                origin = operation_blocks[operation.id].id
                predecessors[edge.block].add(origin)
                incoming.append((operation, index, origin, edge.block))
    dominators = {}
    for region in graph.regions:
        local = {block.id for block in region.blocks}
        dom = {block: ({block} if block == region.entry else set(local)) for block in local}
        changed = True
        while changed:
            changed = False
            for block in local - {region.entry}:
                updated = {block} | set.intersection(*(dom[parent] for parent in predecessors[block]))
                if updated != dom[block]:
                    dom[block] = updated; changed = True
        dominators.update(dom)
    for loop in model.loops:
        atom = semantic.source_atoms.get(loop.source.atom_id)
        if atom is None or atom.reference != loop.source or atom.kind != ("For" if loop.kind is LoopKind.FOR else "While"):
            raise ValueError("loop kind/source differs from its parsed language construct")
        if loop.region not in regions or any(block not in blocks for block in (loop.header, loop.body_entry, loop.natural_exit)):
            raise ValueError("loop interface contains missing control ports")
        if loop.after is not None and loop.after not in blocks:
            raise ValueError("loop interface after port does not exist")
        required_ports = tuple(LoopBindingPort(values[value].slot, value) for value in blocks[loop.header].arguments
                               if isinstance(values[value], LocalBindingValue))
        if loop.bindings != required_ports:
            raise ValueError("loop binding interface must cover every ordered header binding")
        if loop.kind is LoopKind.FOR:
            advance = [protocol for protocol in model.protocols if protocol.kind is PythonProtocolKind.ADVANCE_ITERATOR
                       and protocol.source == loop.source]
            if len(advance) != 1:
                raise ValueError("for loop needs its unique iterator advance")
            operation = operations[advance[0].operation]
            normal = next(edge for edge in operation.terminator.successors if edge.kind is ExitKind.NORMAL)
            failure = next(edge for edge in operation.terminator.successors if edge.kind is ExitKind.RAISE)
            matcher = operations[blocks[failure.block].operations[-1]]
            if (operation_blocks[operation.id].id != loop.header or normal.block != loop.body_entry
                    or matcher.terminator.kind is not TerminatorKind.BRANCH
                    or matcher.terminator.successors[0].block != loop.natural_exit):
                raise ValueError("for loop control ports differ from its item/exhaustion edges")
        else:
            branches = [operations[link.operation] for link in metadata.operation_links if link.source == loop.source
                        and operations[link.operation].terminator is not None
                        and operations[link.operation].terminator.kind is TerminatorKind.BRANCH]
            if len(branches) != 1 or tuple(edge.block for edge in branches[0].terminator.successors) != (loop.body_entry, loop.natural_exit):
                raise ValueError("while loop body/natural ports differ from its predicate branch")
            branch_block = operation_blocks[branches[0].id].id
            headers = {edge.block for operation in graph.operations
                if links[operation.id].source == loop.source and operation.terminator is not None
                and operation.terminator.kind is TerminatorKind.JUMP
                for edge in operation.terminator.successors if edge.block in dominators[branch_block]}
            if headers != {loop.header}:
                raise ValueError("while header differs from its preheader/backedge target")
        actual_backedges = tuple(ControlEdgeReference(operation.id, index)
            for operation, index, origin, target in incoming
            if target == loop.header and loop.header in dominators[origin])
        if set(loop.backedges) != set(actual_backedges):
            raise ValueError("loop backedge interface must cover each actual backedge")
        from scar.ir.control_flow_v2 import EdgeKind
        def source_transfer_owner(operation, kind):
            reference = links[operation].source
            owners = {control.nodes[edge.target].source for edge in control.edges.values()
                if edge.kind is kind and control.nodes[edge.source].source == reference
                and control.nodes[edge.source].scope == model.definition}
            if not owners and language is not None and source_tree is not None:
                from scar.ir.program.source_language import SourceLanguageCapability
                if SourceLanguageCapability.FUNCTION_TRY_314_V1 in language.capabilities:
                    # Old control-flow artifacts explicitly retain Try as a
                    # gap, so nested handler Break/Continue has no old edge.
                    # Resolve its exact lexical AST owner, never invent a CFG
                    # edge or ignore a contradictory existing owner.
                    expected="Break" if kind is EdgeKind.BREAK else "Continue"
                    span=lambda n:(n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)
                    subject=(model.source.start_line,model.source.end_line,model.source.start_column,model.source.end_column)
                    roots=[n for n in ast.walk(source_tree)if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))and span(n)==subject]
                    found=[]
                    def descend(node,stack):
                        if type(node).__name__==expected and span(node)==(reference.start_line,reference.end_line,reference.start_column,reference.end_column):
                            if stack:found.append(stack[-1])
                            return
                        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.Lambda,ast.ClassDef)):return
                        if isinstance(node,(ast.For,ast.While,ast.AsyncFor)):
                            for child in node.body:descend(child,stack+(node,))
                            for child in node.orelse:descend(child,stack)
                        else:
                            for child in ast.iter_child_nodes(node):descend(child,stack)
                    if len(roots)==1:
                        for child in roots[0].body:descend(child,())
                    if len(found)==1:
                        refs=[a.reference for a in semantic.source_atoms.values()if a.kind==type(found[0]).__name__
                            and (a.reference.start_line,a.reference.end_line,a.reference.start_column,a.reference.end_column)==span(found[0])]
                        if len(refs)==1:return refs[0]
            if len(owners) != 1:
                raise ValueError("source loop transfer has no unique lexical owner")
            return next(iter(owners))
        actual_continues = {edge for edge in actual_backedges
            if semantic.source_atoms[links[edge.operation].source.atom_id].kind == "Continue"
            and source_transfer_owner(edge.operation, EdgeKind.CONTINUE) == loop.source}
        if set(loop.continues) != actual_continues:
            raise ValueError("loop continue interface must cover each actual continue")
        actual_breaks = {ControlEdgeReference(operation.id, index)
            for operation, index, origin, target in incoming
            if semantic.source_atoms[links[operation.id].source.atom_id].kind == "Break"
            and source_transfer_owner(operation.id, EdgeKind.BREAK) == loop.source}
        if set(loop.breaks) != actual_breaks:
            raise ValueError("loop break interface must cover each actual break")
        after_targets = {target for operation, index, origin, target in incoming
            if ((links[operation.id].source == loop.source and operation.terminator.kind is TerminatorKind.JUMP
                 and target != loop.header) or ControlEdgeReference(operation.id, index) in actual_breaks)}
        if len(after_targets) > 1 or after_targets != ({loop.after} if loop.after is not None else set()):
            raise ValueError("loop after port differs from its actual natural/break exits")
        for port in loop.bindings:
            value = values.get(port.header_value)
            if not isinstance(value, LocalBindingValue) or value.slot != port.slot or not isinstance(value.origin, BlockArgument) or value.origin.block != loop.header:
                raise ValueError("loop carried binding must be its same-slot header argument")
        for edge in loop.backedges + loop.breaks + loop.continues:
            operation = operations.get(edge.operation)
            if operation is None or operation.terminator is None or edge.successor_index >= len(operation.terminator.successors):
                raise ValueError("loop interface points to a missing control edge")
            target = operation.terminator.successors[edge.successor_index].block
            expected = loop.after if edge in loop.breaks else loop.header
            if target != expected:
                raise ValueError("loop transfer has a different target than its declared interface")


__all__ = ["StructuredBuilder", "require_valid_structured_body"]
