"""Opt-in synchronous function Try over existing C0/C1 control records."""
from __future__ import annotations

import ast
from contextlib import contextmanager
from dataclasses import replace

from scar.analysis.environment_lowering import StructuredEnvironmentBuilder
from scar.analysis.program_lowering import _Unsupported, _REF
from scar.analysis.source_module_lowering import PropagationOperands, PropagationModuleBuilder
from scar.ir.program.bindings import BindingState
from scar.ir.program.control import (ControlScope, ControlScopeKind as S, ControlPort,
    LanguageCompletionKind as L, ProtocolValueKind as P, ProtocolValueType,
    PendingDispatchTerminator, PendingSuccessor, PendingPayload)
from scar.ir.program.cleanup import (CleanupInterface, CleanupEnter, CleanupResume,
    CleanupReplace, CleanupRouteTerminator, CleanupRouteSuccessor, HandledContextDomain)
from scar.ir.program.ids import ControlScopeID, ControlPortID, OperationID, ValueID, UseID
from scar.ir.program.model import (Behavior, Operation, OperationResult, ProtocolValue, ReferenceValue,
    StateVersionValue, StateAccess, AccessMode, Footprint, FootprintKind, ExitKind, Terminator,
    TerminatorKind, Use, UseRole, DataValue)
from scar.ir.program.source import GapKind, SourceRole, UseSource
from scar.ir.program.structured import PythonProtocolKind as K, ControlEdgeReference


class FunctionTryBuilder(StructuredEnvironmentBuilder):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.root_scope = self.current_owner = None
        self.scope_specs, self.block_owners, self.control_names = {}, {}, {}
        self.incoming_states = {}
        self.control_ports, self.exception_packets, self.pending_completions = [], [], []
        self.cleanup_interfaces, self.cleanup_enters, self.cleanup_resumes, self.cleanup_replacements = [], [], [], []
        self.exception_matches, self.failure_sinks = [], []
        self.try_depth = 0
        self.handler_expression_depth = 0
        node = self.functions[self.entry]
        args = node.args
        self.formal_names = {x.arg for x in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
        self.formal_names.update(x.arg for x in (args.vararg, args.kwarg) if x is not None)

    @property
    def frame_region(self):
        return self.function_context

    def new_block(self, *args, **kwargs):
        cursor = super().new_block(*args, **kwargs)
        if self.root_scope is None:
            self.root_scope = self.fresh(ControlScopeID, 'function-control-root')
            self.current_owner = self.root_scope
            self.scope_specs[self.root_scope] = (S.FUNCTION, None, self.source(self.functions[self.entry]))
        self.block_owners[cursor.block] = self.current_owner
        return cursor

    @contextmanager
    def in_owner(self, owner):
        before = self.current_owner
        self.current_owner = owner
        try:
            yield
        finally:
            self.current_owner = before

    new_scope = PropagationModuleBuilder.new_scope
    packet = PropagationModuleBuilder.packet
    pending = PropagationModuleBuilder.pending

    def emit(self, cursor, operation, node, role, old=None):
        super().emit(cursor, operation, node, role, old=old)
        kind = {'pack-propagation-pair': K.FUNCTION_EXCEPTION_PACKET,
                'pack-language-pending': K.FUNCTION_PENDING_COMPLETION,
                'handler-context-enter': K.FUNCTION_HANDLED_CONTEXT_ENTER,
                'cleanup-resume': K.FUNCTION_CLEANUP_RESUME,
                'cleanup-replace': K.FUNCTION_CLEANUP_REPLACE}.get(operation.label)
        if kind is not None:
            self.protocol(operation.id, kind, node)

    def use(self, operation, value, node, role, index, *, semantic_value=None):
        if type(self.values_by_id[value]) is ProtocolValue:
            use = Use(self.fresh(UseID, 'protocol-use'), value, UseRole.PROTOCOL)
            self.use_links.append(UseSource(operation, use.id, self.source(node), role, index, semantic_value))
            return use
        return super().use(operation, value, node, role, index, semantic_value=semantic_value)

    def control_block(self, node, *, extra_types=()):
        names = tuple(sorted(self.locals))
        cursor = self.new_block(node, named=names, extra_types=extra_types)
        self.control_names[cursor.block] = names
        for name in names:
            if name in self.formal_names:
                self.known_binding_states[cursor.env[name]] = BindingState.BOUND
        return cursor

    def carry(self, cursor, target, node):
        values = []
        for index, name in enumerate(self.control_names[target.block]):
            value = cursor.env[name]
            values.append(self.use(self._transfer_id, value, node, 'carried-binding', index))
            self.incoming_binding(target, name, value)
        return values

    def incoming_binding(self, target, name, value):
        states = self.incoming_states.setdefault((target.block, name), [])
        states.append(self.known_binding_states.get(value))
        if states[0] is not None and all(state is states[0] for state in states):
            self.known_binding_states[target.env[name]] = states[0]
        else:
            self.known_binding_states.pop(target.env[name], None)

    def jump(self, cursor, target, names, node):
        for name in names:
            self.incoming_binding(target, name, cursor.env[name])
        return super().jump(cursor, target, names, node)

    def jump_values(self, cursor, target, values, node):
        from scar.ir.program.model import Successor
        identity = self.fresh(OperationID, 'function-control-jump')
        self._transfer_id = identity
        uses = self.carry(cursor, target, node)
        uses += [self.use(identity, value, node, 'forwarded', i) for i, value in enumerate(values)]
        uses.append(self.use(identity, cursor.state, node, 'current-world', 0))
        self.emit(cursor, Operation(identity, 'function-control-jump', (Behavior.CONTROL,), tuple(uses),
            terminator=Terminator(TerminatorKind.JUMP, (Successor(target.block, tuple(x.id for x in uses)),))), node, SourceRole.CONTROL)
        return identity

    def raise_payload_types(self):
        return (_REF, _REF)

    def failure_payload(self, values):
        if len(values) != 2:
            raise ValueError('function Try needs this completion exception/traceback pair')
        return PropagationOperands(*values)

    def exception_reference(self, payload):
        return payload.exception

    def failure_references(self, payload):
        return payload.exception, payload.traceback

    def read_local(self, node, cursor, old):
        token = cursor.env[node.id]
        if self.known_binding_states.get(token) is not BindingState.BOUND:
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node,
                'FUNCTION_TRY_LOCAL_BINDING_PROPAGATION_UNIMPLEMENTED')
        return super().read_local(node, cursor, old)

    @contextmanager
    def handler_expression(self):
        self.handler_expression_depth += 1
        try:
            yield
        finally:
            self.handler_expression_depth -= 1

    def old_operation(self, node):
        records = self.old_by_atom.get(self.source(node).atom_id, ())
        if self.handler_expression_depth and not records:
            return None
        return super().old_operation(node)

    def expr(self, node, cursor):
        if self.handler_expression_depth and not self.old_by_atom.get(self.source(node).atom_id, ()):
            from scar.analysis.source_heap_lowering import expression_for_heap_target
            return expression_for_heap_target(self, node, cursor)
        if isinstance(node, ast.GeneratorExp):
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node,
                'FUNCTION_TRY_RESUMABLE_PROPAGATION_ABI_UNIMPLEMENTED')
        if isinstance(node, ast.Call) and (any(isinstance(arg, ast.Starred) for arg in node.args)
                                         or any(kw.arg is None for kw in node.keywords)):
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node,
                'FUNCTION_TRY_EXTENDED_CALL_LIFETIME_UNIMPLEMENTED')
        return super().expr(node, cursor)

    def invoke_protocol(self, cursor, node, values, kind, *, result_type=_REF, failure_handler=None):
        if kind in (K.RERAISE, K.RAISE_EXCEPTION, K.RAISE_WITH_CAUSE, K.FUNCTION_START_PROPAGATION):
            inputs = tuple((value, node, 'protocol-input', i, None) for i, value in enumerate(values))
            normal, payload, operation = self.invoke_results(cursor, node, inputs,
                result_types=(_REF, _REF), failure_handler=failure_handler)
            self.protocol(operation, kind, node)
            return normal, PropagationOperands(*payload), operation
        return super().invoke_protocol(cursor, node, values, kind, result_type=result_type,
                                       failure_handler=failure_handler)

    def raise_landing(self, node):
        with self.in_owner(self.root_scope):
            landing = self.control_block(node, extra_types=(ProtocolValueType(P.EXCEPTION_PACKET),))
        packet = self.block_arguments[landing.block][-2]
        roots = self.frame_exit_references(landing, node, packet)
        bindings = tuple(row for row in roots if type(self.values_by_id[row[0]]) is not ProtocolValue
                         and type(self.values_by_id[row[0]]) is not ReferenceValue)
        if bindings:
            self.frame_transition(landing, node, bindings, K.FUNCTION_FRAME_EXIT_BINDINGS)
        roots = tuple(row for row in roots if row not in bindings)
        self.frame_transition(landing, node, roots,
                              K.FUNCTION_FRAME_EXIT_EXCEPTION_PACKET)
        identity = self.fresh(OperationID, 'function-packet-exit')
        uses = (self.use(identity, packet, node, 'exception-packet', 0),
                self.use(identity, landing.state, node, 'post-world', 0))
        self.emit(landing, Operation(identity, 'function-packet-exit', (Behavior.CONTROL,), uses,
            terminator=Terminator(TerminatorKind.RAISE, exit='raise', values=tuple(x.id for x in uses))), node, SourceRole.EXCEPTION)
        port = ControlPort(self.fresh(ControlPortID, 'function-raise-port'), self.root_scope, L.RAISE, block=landing.block)
        self.control_ports.append(port)
        return port

    def dispatch(self, cursor, node, token, ports):
        identity = self.fresh(OperationID, 'function-pending-dispatch')
        selector = self.use(identity, token, node, 'pending-selector', 0)
        uses, edges = [selector], []
        for index, port in enumerate(ports):
            target = self._cursor_for(port.block)
            self._transfer_id = identity
            carried = self.carry(cursor, target, node)
            state = self.use(identity, cursor.state, node, 'dispatch-world', index)
            uses.extend(carried); uses.append(state)
            arguments = tuple(x.id for x in carried)
            if port.kind in (L.RETURN, L.RAISE):
                arguments += (PendingPayload(),)
            edges.append(PendingSuccessor(port.id, port.block, arguments + (state.id,)))
        self.emit(cursor, Operation(identity, 'function-pending-dispatch', (Behavior.CONTROL,), tuple(uses),
            terminator=PendingDispatchTerminator(selector.id, tuple(edges))), node, SourceRole.CONTROL)

    def _cursor_for(self, block):
        from scar.analysis.program_lowering import _Cursor
        env = dict(zip(self.control_names[block], self.block_arguments[block]))
        return _Cursor(block, env, self.block_arguments[block][-1])

    def finish_exit(self, cursor, node, value, kind, *, binding=None):
        if kind is ExitKind.NORMAL:
            return super().finish_exit(cursor, node, value, kind, binding=binding)
        if binding is not None:
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, 'FUNCTION_TRY_UNBOUND_LOCAL_EXIT_UNIMPLEMENTED')
        if type(value) is not PropagationOperands:
            cursor, value, _ = self.invoke_protocol(cursor, node, (value,), K.FUNCTION_START_PROPAGATION)
        if self.failure_sinks:
            return self.failure_sinks[-1](cursor, value)
        port = self.raise_landing(node)
        token = self.pending(cursor, node, port, self.packet(cursor, node, value))
        return self.dispatch(cursor, node, token, (port,))

    def route_to_cleanup(self, cursor, node, token, port, target, extra=()):
        identity = self.fresh(OperationID, 'function-cleanup-route')
        selector = self.use(identity, token, node, 'pending-selector', 0)
        self._transfer_id = identity
        carried = self.carry(cursor, target, node)
        forward = self.use(identity, token, node, 'entry-pending', 0)
        extra_uses = tuple(self.use(identity, value, node, 'caught-reference', i) for i, value in enumerate(extra))
        state = self.use(identity, cursor.state, node, 'current-world', 0)
        self.emit(cursor, Operation(identity, 'function-cleanup-route', (Behavior.CONTROL,),
            tuple([selector, *carried, forward, *extra_uses, state]), terminator=CleanupRouteTerminator(selector.id,
                (CleanupRouteSuccessor(port.id, target.block, tuple(x.id for x in carried) + (forward.id,) + tuple(x.id for x in extra_uses) + (state.id,)),))), node, SourceRole.CONTROL)

    def enter_cleanup(self, entry, node, cleanup, *, trailing_references=0):
        token = self.block_arguments[entry.block][-2-trailing_references]
        identity = self.fresh(OperationID, 'function-context-enter')
        use = self.use(identity, token, node, 'entry-pending', 0)
        before = self.use(identity, entry.state, node, 'context-world', 0)
        saved = ProtocolValue(self.fresh(ValueID, 'saved-context'), self.function_context, OperationResult(identity, 0), P.SAVED_HANDLED_CONTEXT)
        after = StateVersionValue(self.fresh(ValueID, 'context-world'), self.function_context, OperationResult(identity, 1), self.world)
        for value in (saved, after):
            self.add_value(value); self.link_value(value, node, SourceRole.EXCEPTION)
        self.emit(entry, Operation(identity, 'handler-context-enter', (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
            (use, before), (saved.id, after.id),
            (StateAccess(self.world, before.id, AccessMode.READ_WRITE, after.id, Footprint(FootprintKind.WHOLE)),), effects_complete=False), node, SourceRole.CONTROL)
        self.cleanup_enters.append(CleanupEnter(identity, cleanup, use.id, saved.id)); entry.state = after.id
        return token, saved.id

    def cleanup_exit(self, cursor, node, cleanup, original, selected, context, ports, *, resume=False):
        parent = self.scope_specs[cleanup][1]
        with self.in_owner(cleanup):
            action = self.control_block(node)
        self.jump_values(cursor, action, (), node)
        with self.in_owner(parent):
            corridor = self.control_block(node, extra_types=(ProtocolValueType(P.PENDING_COMPLETION),))
            final = self.control_block(node, extra_types=(ProtocolValueType(P.PENDING_COMPLETION),))
        identity = self.fresh(OperationID, 'function-context-restore')
        pending = self.use(identity, original, node, 'entry-pending', 0)
        replacement = None if resume else self.use(identity, selected, node, 'replacement-pending', 0)
        context_use = self.use(identity, context, node, 'saved-context', 0)
        before = self.use(identity, action.state, node, 'current-world', 0)
        after = StateVersionValue(self.fresh(ValueID, 'cleanup-post-world'), self.function_context, OperationResult(identity, 0), self.world)
        self.add_value(after); self.link_value(after, node, SourceRole.STATE)
        uses = (pending, context_use, before) if resume else (pending, replacement, context_use, before)
        self.emit(action, Operation(identity, 'cleanup-resume' if resume else 'cleanup-replace',
            (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), uses, (after.id,),
            (StateAccess(self.world, before.id, AccessMode.READ_WRITE, after.id, Footprint(FootprintKind.WHOLE)),), effects_complete=False), node, SourceRole.CONTROL)
        action.state = after.id; jump = self.jump_values(action, corridor, (selected,), node)
        record = (CleanupResume(identity, cleanup, pending.id, context_use.id, ControlEdgeReference(jump, 0)) if resume
            else CleanupReplace(identity, cleanup, pending.id, replacement.id, context_use.id, ControlEdgeReference(jump, 0)))
        (self.cleanup_resumes if resume else self.cleanup_replacements).append(record)
        token = self.block_arguments[corridor.block][-2]
        route = self.fresh(OperationID, 'function-post-pop-route')
        selector = self.use(route, token, node, 'pending-selector', 0); self._transfer_id = route
        successors, route_uses = [], [selector]
        for i, port in enumerate(ports):
            carried = self.carry(corridor, final, node)
            forward = self.use(route, token, node, 'forwarded-pending', i)
            state = self.use(route, corridor.state, node, 'post-pop-world', i)
            route_uses.extend((*carried, forward, state))
            successors.append(CleanupRouteSuccessor(port.id, final.block, tuple(x.id for x in carried) + (forward.id, state.id)))
        self.emit(corridor, Operation(route, 'function-post-pop-route', (Behavior.CONTROL,), tuple(route_uses),
            terminator=CleanupRouteTerminator(selector.id, tuple(successors))), node, SourceRole.CONTROL)
        self.dispatch(final, node, self.block_arguments[final.block][-2], ports)

    def _try_shape(self, node):
        if self.try_depth or (node.handlers and node.finalbody):
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, 'FUNCTION_TRY_NESTED_OR_COMBINED_UNIMPLEMENTED')
        for child in ast.walk(node):
            if child is not node and isinstance(child, (ast.Try, ast.TryStar, ast.Return, ast.Break, ast.Continue,
                                                        ast.Yield, ast.YieldFrom, ast.Await)):
                raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, child, 'FUNCTION_TRY_NONLOCAL_TRANSFER_OR_NESTED_UNIMPLEMENTED')
        if not node.finalbody and not node.handlers:
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, 'FUNCTION_TRY_WITHOUT_CLEANUP_UNIMPLEMENTED')

    def bind_exception_name(self, handler, reference, cursor):
        name = handler.name
        if name not in self.locals or name in self.cell_references:
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, handler,
                'FUNCTION_TRY_NONLOCAL_EXCEPTION_ALIAS_UNIMPLEMENTED')
        previous = cursor.env[name]
        self.frame_transition(cursor, handler, ((previous, handler, 'previous-exception-binding'),
            (reference, handler, 'caught-exception-binding')), K.FRAME_BIND)
        self.define_binding(name, cursor, handler, reference)
        return cursor

    def clear_exception_name(self, handler, cursor):
        cursor = self.bind_exception_name(handler, self.literal(handler, None), cursor)
        self.frame_transition(cursor, handler, ((cursor.env[handler.name], handler, 'cleared-exception-binding'),),
                              K.FUNCTION_CLEAR_EXCEPTION_NAME)
        self.define_binding(handler.name, cursor, handler)
        return cursor

    def match_handler(self, handler, current, caught_ref, entry):
        from scar.ir.program.exception_matches import ExceptionMatcher, ExceptionHandlerOperand
        from scar.ir.program.state_addresses import ExistingAccess
        from scar.ir.program.model import BlockArgument
        with self.handler_expression():
            current, handler_ref = self.expr(handler.type, current)
        self.frame_transition(current, handler, ((handler_ref, handler.type, 'handler-type-hold'),), K.FRAME_HOLD_TEMPORARY)
        self.active_temporaries.append(handler_ref)
        def invalid_type(failed, payload):
            held = self.active_temporaries.pop()
            try:
                self.frame_transition(failed, handler, ((held, handler.type, 'handler-type-release'),), K.FRAME_RELEASE_TEMPORARY)
                self.finish_exit(failed, handler, payload, ExitKind.RAISE)
            finally:
                self.active_temporaries.append(held)
        current, validated, operation = self.invoke(current, handler,
            ((handler_ref, handler.type, 'handler-type', 0, None),), failure_handler=invalid_type)
        self.protocol(operation, K.VALIDATE_EXCEPT_TYPE_314, handler)
        identity = self.fresh(OperationID, 'borrowed-function-exception-match')
        exc = self.use(identity, caught_ref, handler, 'caught-exception', 0)
        selected = self.use(identity, validated, handler.type, 'dynamic-handler', 0)
        world = self.use(identity, current.state, handler, 'match-world', 0)
        boolean = DataValue(self.fresh(ValueID, 'exception-match'), self.function_context,
                            OperationResult(identity, 0), 'builtins.bool')
        self.add_value(boolean); self.link_value(boolean, handler, SourceRole.TRUTH)
        self.emit(current, Operation(identity, 'borrowed-function-exception-match',
            (Behavior.COMPUTE, Behavior.READ, Behavior.CONTROL), (exc, selected, world), (boolean.id,),
            (StateAccess(self.world, world.id, AccessMode.READ, footprint=Footprint(FootprintKind.WHOLE)),), effects_complete=True), handler, SourceRole.TRUTH)
        self.protocol(identity, K.MATCH_EXCEPTION_BORROWED_314, handler)
        self.active_temporaries.pop()
        self.frame_transition(current, handler, ((handler_ref, handler.type, 'handler-type-release'),), K.FRAME_RELEASE_TEMPORARY)
        yes, no = self.new_block(handler), self.new_block(handler)
        self.branch(current, boolean.id, yes, no, handler)
        self.exception_matches.append(ExceptionMatcher(identity, exc.id,
            BlockArgument(entry.block, len(self.control_names[entry.block]) + 1),
            ExceptionHandlerOperand(selected.id, self.values_by_id[validated].origin),
            OperationResult(identity, 0), None, self.operations[-1].id, (ExistingAccess(identity, 0),)))
        return yes, no

    def try_except(self, node, cursor):
        self._try_shape(node)
        parent, after = self.current_owner, None
        body_scope = self.new_scope(S.BLOCK, node, parent)
        gate_scope = self.new_scope(S.BLOCK, node, parent)
        cleanup = self.new_scope(S.CLEANUP, node, parent)
        with self.in_owner(body_scope):
            body = self.control_block(node)
        with self.in_owner(gate_scope):
            gate = self.control_block(node, extra_types=(_REF, _REF))
        with self.in_owner(cleanup):
            entry = self.control_block(node, extra_types=(ProtocolValueType(P.PENDING_COMPLETION), _REF))
        self.cleanup_interfaces.append(CleanupInterface(cleanup, gate_scope, entry.block, self.block_arguments[entry.block][-3]))
        self.jump_values(cursor, body, (), node)
        caught_edges = []
        def caught(failed, payload):
            caught_edges.append(failed.block)
            self.jump_values(failed, gate, (payload.exception, payload.traceback), node)
        self.try_depth += 1
        with self.in_owner(body_scope):
            self.failure_sinks.append(caught)
            try:
                normal = self.statements(node.body, body)
            finally:
                self.failure_sinks.pop()
        if not caught_edges:
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node,
                'FUNCTION_TRY_NO_RAISING_PROTECTED_OPERATION_UNIMPLEMENTED')
        if normal is not None:
            with self.in_owner(parent):
                else_entry = self.control_block(node)
            self.jump_values(normal, else_entry, (), node)
            normal = self.statements(node.orelse, else_entry)
            if normal is not None:
                with self.in_owner(parent):
                    after = self.control_block(node)
                self.jump_values(normal, after, (), node)
        original_port = self.raise_landing(node)
        pair = PropagationOperands(*self.block_arguments[gate.block][-3:-1])
        with self.in_owner(gate_scope):
            token = self.pending(gate, node, original_port, self.packet(gate, node, pair))
            self.route_to_cleanup(gate, node, token, original_port, entry, (pair.exception,))
        with self.in_owner(cleanup):
            original, saved = self.enter_cleanup(entry, node, cleanup, trailing_references=1)
            caught_ref = self.block_arguments[entry.block][-2]
            def replaced(failed, payload):
                port = self.raise_landing(node)
                fresh = self.pending(failed, node, port, self.packet(failed, node, payload))
                self.cleanup_exit(failed, node, cleanup, original, fresh, saved, (port,))
            self.failure_sinks.append(replaced)
            current = entry
            try:
                for handler in node.handlers:
                    if handler.type is None:
                        selected, current = current, None
                    else:
                        selected, current = self.match_handler(handler, current, caught_ref, entry)
                    body_owner = self.new_scope(S.BLOCK, handler, cleanup)
                    with self.in_owner(body_owner):
                        handler_body = self.control_block(handler)
                        self.jump_values(selected, handler_body, (), handler)
                        if handler.name:
                            handler_body = self.bind_exception_name(handler, caught_ref, handler_body)
                        hold_base = len(self.active_temporaries)
                        def body_failed(failed, payload):
                            held = tuple(self.active_temporaries[hold_base:])
                            del self.active_temporaries[hold_base:]
                            try:
                                for reference in reversed(held):
                                    self.frame_transition(failed, handler, ((reference, handler, 'handler-unwind-temporary'),), K.FRAME_RELEASE_TEMPORARY)
                                if handler.name:
                                    self.clear_exception_name(handler, failed)
                                replaced(failed, payload)
                            finally:
                                self.active_temporaries.extend(held)
                        self.failure_sinks.append(body_failed)
                        try:
                            completed = self.statements(handler.body, handler_body)
                        finally:
                            self.failure_sinks.pop()
                        if completed is not None:
                            if after is None:
                                with self.in_owner(parent):
                                    after = self.control_block(node)
                            with self.in_owner(parent):
                                target = self.control_block(handler) if handler.name else after
                            port = ControlPort(self.fresh(ControlPortID, 'handler-fallthrough'), parent, L.FALLTHROUGH, block=target.block)
                            self.control_ports.append(port)
                            selected_pending = self.pending(completed, handler, port)
                            self.cleanup_exit(completed, handler, cleanup, original, selected_pending, saved, (port,))
                            if handler.name:
                                with self.in_owner(parent):
                                    self.clear_exception_name(handler, target)
                                    self.jump_values(target, after, (), handler)
                    if current is None:
                        break
                if current is not None:
                    self.cleanup_exit(current, node, cleanup, original, original, saved, (original_port,), resume=True)
            finally:
                self.failure_sinks.pop(); self.try_depth -= 1
        return after

    def try_finally(self, node, cursor):
        self._try_shape(node)
        parent = self.current_owner
        protected = self.new_scope(S.BLOCK, node, parent)
        cleanup = self.new_scope(S.CLEANUP, node, parent)
        with self.in_owner(protected):
            body = self.control_block(node)
        with self.in_owner(cleanup):
            entry = self.control_block(node, extra_types=(ProtocolValueType(P.PENDING_COMPLETION),))
        self.cleanup_interfaces.append(CleanupInterface(cleanup, protected, entry.block, self.block_arguments[entry.block][-2]))
        self.jump_values(cursor, body, (), node)
        ports = []
        def failed(failure, payload):
            port = self.raise_landing(node); ports.append(port)
            token = self.pending(failure, node, port, self.packet(failure, node, payload))
            self.route_to_cleanup(failure, node, token, port, entry)
        self.try_depth += 1
        with self.in_owner(protected):
            self.failure_sinks.append(failed)
            try:
                normal = self.statements(node.body, body)
            finally:
                self.failure_sinks.pop()
        after = None
        if normal is not None:
            with self.in_owner(parent):
                after = self.control_block(node)
            port = ControlPort(self.fresh(ControlPortID, 'finally-fallthrough'), parent, L.FALLTHROUGH, block=after.block)
            self.control_ports.append(port); ports.append(port)
            with self.in_owner(protected):
                token = self.pending(normal, node, port)
                self.route_to_cleanup(normal, node, token, port, entry)
        with self.in_owner(cleanup):
            original, saved = self.enter_cleanup(entry, node, cleanup)
            def replaced(failure, payload):
                port = self.raise_landing(node)
                token = self.pending(failure, node, port, self.packet(failure, node, payload))
                self.cleanup_exit(failure, node, cleanup, original, token, saved, (port,))
            self.failure_sinks.append(replaced)
            try:
                completed = self.statements(node.finalbody, entry)
            finally:
                self.failure_sinks.pop(); self.try_depth -= 1
            if completed is not None:
                self.cleanup_exit(completed, node, cleanup, original, original, saved, tuple(ports), resume=True)
        return after

    def statements(self, nodes, cursor):
        for node in nodes:
            if cursor is not None and isinstance(node, ast.Try):
                cursor = (self.try_except(node, cursor) if node.handlers else self.try_finally(node, cursor))
            else:
                cursor = super().statements((node,), cursor)
        return cursor

    def build_function(self):
        node = super().build_function()
        packet = ProtocolValueType(P.EXCEPTION_PACKET)
        self.regions = [replace(region, exits=tuple(replace(port, types=(packet, self.state_type))
            if port.kind is ExitKind.RAISE else port for port in region.exits)) for region in self.regions]
        return node

    def make_graph(self):
        graph = super().make_graph()
        scopes = tuple(ControlScope(identity, self.function_context, parent, kind, source,
            tuple(block for block in self.function_blocks if self.block_owners[block] == identity))
            for identity, (kind, parent, source) in self.scope_specs.items()
            if any(self.block_owners[block] == identity for block in self.function_blocks))
        return replace(graph, control_scopes=scopes, control_ports=tuple(self.control_ports),
            exception_packets=tuple(self.exception_packets), pending_completions=tuple(self.pending_completions),
            handled_context_domains=(HandledContextDomain(self.function_context, self.world),) if self.cleanup_interfaces else (),
            cleanup_interfaces=tuple(self.cleanup_interfaces), cleanup_enters=tuple(self.cleanup_enters),
            cleanup_resumes=tuple(self.cleanup_resumes), cleanup_replacements=tuple(self.cleanup_replacements),
            exception_matches=tuple(self.exception_matches))
