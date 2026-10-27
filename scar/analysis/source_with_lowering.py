"""Synchronous context scopes using the existing function C0/C1 and world.

ENTER owns special-exit lookup/save, special-enter lookup/call, and failure
unwind. NORMAL arms the saved binding in this activation's frame/world; it
does not manufacture a Python bound-method object. EXIT consumes that binding
once, with its internal receiver layout, and keeps arbitrary effects/failure.
"""
from __future__ import annotations

import ast
import dis

from scar.analysis.program_lowering import _Unsupported, _BOOL, _REF
from scar.analysis.source_language import supports_cpython_compiler
from scar.analysis.source_function_try_lowering import FunctionTryBuilder
from scar.ir.program.control import ControlPort, ControlScopeKind as S, LanguageCompletionKind as L, ProtocolValueKind as P, ProtocolValueType
from scar.ir.program.cleanup import CleanupInterface
from scar.ir.program.ids import ControlPortID, ValueID
from scar.ir.program.model import DataValue, ExitKind, LiteralOrigin
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.structured import PythonProtocolKind as K


def with_shape(node):
    if not isinstance(node, ast.With) or len(node.items) != 1:
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, 'FUNCTION_WITH_MULTIPLE_OR_ASYNC_ITEMS_UNIMPLEMENTED')


def check_compiler_with(node, code):
    with_shape(node)
    expr = node.items[0].context_expr
    rows = [r for r in dis.get_instructions(code) if tuple(r.positions) ==
            (expr.lineno, expr.end_lineno, expr.col_offset, expr.end_col_offset)]
    special = [r.argrepr for r in rows if r.opname == 'LOAD_SPECIAL']
    if special != ['__exit__', '__enter__']:
        raise _Unsupported(GapKind.CODE_VERSION, node, 'FUNCTION_WITH_ORIGINAL_SPECIAL_LOOKUP_SEQUENCE_UNAVAILABLE: ' + repr(special))


class FunctionWithBuilder(FunctionTryBuilder):
    def statements(self, nodes, cursor):
        for node in nodes:
            if cursor is not None and isinstance(node, ast.With):
                cursor = self.with_statement(node, cursor)
            else:
                cursor = super().statements((node,), cursor)
        return cursor

    def with_statement(self, node, cursor):
        with_shape(node)
        if self.try_depth:
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, 'FUNCTION_WITH_NESTED_CLEANUP_ROUTING_UNIMPLEMENTED')
        evidence = self.language_options.code_evidence
        if not supports_cpython_compiler(evidence):
            raise _Unsupported(GapKind.CODE_VERSION, node, 'FUNCTION_WITH_READONLY_3147_CODE_REQUIRED')
        check_compiler_with(node, evidence.code)
        item = node.items[0]
        # Older overlays omitted withitem expressions. Recover only from their
        # exact original SG definitions, using the existing source bridge.
        with self.handler_expression():
            cursor, manager = self.expr(item.context_expr, cursor)
        if cursor is None: return None
        cursor, entered, identity = self.invoke(cursor, node,
            ((manager, item.context_expr, 'context-manager', 0, None),))
        self.protocol(identity, K.WITH_ENTER_CONTEXT, node)
        parent = self.current_owner
        protected = self.new_scope(S.BLOCK, node, parent)
        cleanup = self.new_scope(S.CLEANUP, node, parent)
        with self.in_owner(protected): body = self.control_block(node)
        with self.in_owner(parent): after = self.control_block(node)
        fallthrough = ControlPort(self.fresh(ControlPortID, 'with-fallthrough'), parent, L.FALLTHROUGH, block=after.block)
        self.control_ports.append(fallthrough)
        with self.in_owner(cleanup):
            entry = self.control_block(node, extra_types=(ProtocolValueType(P.PENDING_COMPLETION), _BOOL, _REF))
        original_pending = self.block_arguments[entry.block][-4]
        self.cleanup_interfaces.append(CleanupInterface(cleanup, protected, entry.block, original_pending))
        self.jump_values(cursor, body, (), node)
        ports = []; base = len(self.active_temporaries)
        anchor = next(iter(self.environment_references.values()))

        def route(at, port, token, raised, carrier):
            flag = DataValue(self.fresh(ValueID, 'with-completion-class'), self.function_context,
                             LiteralOrigin(raised), 'builtins.bool')
            self.add_value(flag); self.link_value(flag, node, SourceRole.CONTROL)
            ports.append(port)
            self.route_to_cleanup(at, node, token, port, entry, (flag.id, carrier))

        def failed(at, payload):
            with self.unwind_temporaries(at, node, base):
                port = self.raise_landing(node)
                token = self.pending(at, node, port, self.packet(at, node, payload))
                route(at, port, token, True, payload.exception)

        def completed(at, source, kind, value):
            port = self.completion_port(source, kind)
            token = self.pending(at, source, port)
            route(at, port, token, False, value if kind is L.RETURN else anchor)

        self.try_depth += 1
        with self.in_owner(protected):
            self.failure_sinks.append(failed); self.completion_sinks.append((completed, len(self.loop_stack)))
            try:
                if item.optional_vars is not None: body = self.store(item.optional_vars, entered, body)
                else: self.frame_transition(body, node, ((entered, node, 'unused-enter-result'),), K.FRAME_DISCARD)
                normal = self.statements(node.body, body)
            finally:
                self.completion_sinks.pop(); self.failure_sinks.pop()
            if normal is not None:
                route(normal, fallthrough, self.pending(normal, node, fallthrough), False, anchor)
        with self.in_owner(cleanup):
            original, saved = self.enter_cleanup(entry, node, cleanup, trailing_references=2)
            flag, carrier = self.block_arguments[entry.block][-3:-1]
            exceptional, ordinary = self.new_block(node), self.new_block(node)
            self.branch(entry, flag, exceptional, ordinary, node)
            cleanup_holds = len(self.active_temporaries)

            def replaced(at, payload):
                with self.unwind_temporaries(at, node, cleanup_holds):
                    port = self.raise_landing(node)
                    token = self.pending(at, node, port, self.packet(at, node, payload))
                    self.cleanup_exit(at, node, cleanup, original, token, saved, (port,))

            self.failure_sinks.append(replaced)
            try:
                none = self.literal(node, None)
                ordinary, result, identity = self.invoke(ordinary, node,
                    tuple((none, node, 'exit-none', i, None) for i in range(3)))
                self.protocol(identity, K.WITH_EXIT_NORMAL, node)
                self.frame_transition(ordinary, node, ((result, node, 'ignored-exit-result'),), K.FRAME_DISCARD)
                self.cleanup_exit(ordinary, node, cleanup, original, original, saved, tuple(ports), resume=True, payload=carrier)
                # The interface reads current type/traceback from this actual
                # caught exception under the current world; no None traceback
                # or snapshot from an unrelated failure is substituted.
                exceptional, result, identity = self.invoke(exceptional, node,
                    ((carrier, node, 'caught-exception', 0, None),))
                self.protocol(identity, K.WITH_EXIT_EXCEPTION, node)
                self.frame_transition(exceptional, node, ((result, node, 'with-exit-truth-reference'),), K.FRAME_HOLD_TEMPORARY)
                self.active_temporaries.append(result)
                exceptional, boolean, _ = self.invoke_protocol(exceptional, node, (result,), K.TRUTH, result_type=_BOOL)
                self.active_temporaries.pop()
                self.frame_transition(exceptional, node, ((result, node, 'with-exit-truth-reference'),), K.FRAME_RELEASE_TEMPORARY)
                yes, no = self.new_block(node), self.new_block(node)
                self.branch(exceptional, boolean, yes, no, node)
                suppressed = self.pending(yes, node, fallthrough)
                self.cleanup_exit(yes, node, cleanup, original, suppressed, saved, (fallthrough,))
                self.cleanup_exit(no, node, cleanup, original, original, saved, tuple(ports), resume=True, payload=carrier)
            finally:
                self.failure_sinks.pop(); self.try_depth -= 1
        self.gap(GapKind.EFFECT_SUMMARY, node,
            'context special lookup/enter, saved exit, suppression and replacement use current world; '
            'actual methods, aliasing, gradient/thread/resource effects, finalizers and completion remain unproved')
        return after
