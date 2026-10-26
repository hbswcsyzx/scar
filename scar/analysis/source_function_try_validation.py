"""Source checks for the opt-in function propagation/C0/C1 adapter."""
import ast

from scar.ir.program.source_language import SourceLanguageCapability as C, FUNCTION_TRY_PROTOCOLS
from scar.ir.program.structured import PythonProtocolKind as K
from scar.ir.program.model import (ProtocolValue, StateVersionValue, ReferenceValue, LocalBindingValue,
    ExitKind, TerminatorKind, Behavior, AccessMode, ValueKind, ValueType, BlockArgument,
    CompletionResult, OperationResult)
from scar.ir.program.control import ControlScopeKind as S, ProtocolValueKind as P, ProtocolValueType


def exception_handoff_holds(block_id, operations, protocols, blocks, use_links):
    """Read actual unwind Uses up to this validated exception's cleanup entry.

    This query does not run a handler or certify finalizers/whole-frame
    lifetime. It follows only the single exception corridor already checked
    by the canonical C0/C1 and function-source consumers.
    """
    cursor, seen, released = (block_id, 0), set(), []
    while cursor not in seen:
        seen.add(cursor)
        block = blocks[cursor[0]]
        if cursor[1] >= len(block.operations):
            raise ValueError('function exception handoff falls out of block')
        op = operations[block.operations[cursor[1]]]
        marker = protocols.get(op.id)
        kind = marker.kind if marker is not None else None
        first = use_links.get((op.id, op.uses[0].id)) if op.uses else None
        if kind is K.FRAME_RELEASE_TEMPORARY and first is not None and first.role == 'function-exception-unwind':
            released.append(op.uses[0].value)
        if kind in (K.FRAME_EXIT, K.FUNCTION_FRAME_EXIT_EXCEPTION_PACKET):
            retained = tuple(u.value for u in op.uses
                if (link := use_links.get((op.id, u.id))) is not None and link.role == 'held-temporary')
            return retained + tuple(reversed(released))
        if kind is K.FUNCTION_HANDLED_CONTEXT_ENTER:
            return tuple(reversed(released))
        term = op.terminator
        if term is None:
            cursor = block.id, cursor[1] + 1
        elif term.kind in (TerminatorKind.JUMP, TerminatorKind.PENDING_DISPATCH, TerminatorKind.CLEANUP_ROUTE) and len(term.successors) == 1:
            cursor = term.successors[0].block, 0
        else:
            raise ValueError('function exception handoff lost its single canonical continuation')
    raise ValueError('function exception handoff cycles without a cleanup endpoint')


def validate_function_try_protocols(model, graph, interface, metadata, semantic, language, *, source_tree=None):
    def need(value, detail):
        if not value:
            raise ValueError('function Try: ' + detail)
    actual = {r.operation for r in model.protocols if r.kind.value in FUNCTION_TRY_PROTOCOLS}
    enabled = language is not None and C.FUNCTION_TRY_314_V1 in language.capabilities
    if not enabled:
        need(not actual, 'new control protocol requires its explicit capability')
        return set()
    need(isinstance(source_tree, ast.Module), 'exact retained source AST required')
    need(not graph.frame_roots and not graph.resumable_creates, 'function capability cannot inherit mapping/resumable ABI')
    values = {r.id: r for r in graph.values}
    operations = {r.id: r for r in graph.operations}
    blocks = {b.id: b for region in graph.regions for b in region.blocks}
    owners = {b: s.id for s in graph.control_scopes for b in s.blocks}
    scopes = {r.id: r for r in graph.control_scopes}
    links = {r.operation: r for r in metadata.operation_links}
    operation_blocks = {identity:b.id for b in blocks.values() for identity in b.operations}
    protocols = {r.operation: r for r in model.protocols}
    uses = {u.id: u for op in graph.operations for u in op.uses}
    roots = [r for r in graph.control_scopes if r.parent is None]
    need(len(roots) == 1 and roots[0].kind is S.FUNCTION and roots[0].source == model.source,
         'exact original function control root required')
    need(all(r.region == graph.root and r.kind in (S.FUNCTION, S.BLOCK, S.CLEANUP, S.LOOP) for r in scopes.values()),
         'only this function local control scopes are implemented')
    state = ValueType(ValueKind.STATE, location=values[interface.world].location)
    ref = ValueType(ValueKind.REFERENCE)
    pairs, incoming = set(), {block: [] for block in blocks}
    normalizers = (K.RERAISE, K.RAISE_EXCEPTION, K.RAISE_WITH_CAUSE, K.FUNCTION_START_PROPAGATION)
    for op in graph.operations:
        if op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE:
            raised = next(s for s in op.completions if s.kind is ExitKind.RAISE)
            need(raised.types == (ref, ref, state), 'invoke lost original exception/traceback/post-world pair')
            for signature, edge in zip(op.completions, op.terminator.successors):
                if signature.kind is ExitKind.RAISE or protocols.get(op.id) is not None and protocols[op.id].kind in normalizers:
                    need(signature.types == (ref, ref, state)
                         and edge.arguments == tuple(CompletionResult(i) for i in range(3)),
                         'propagation must use both results of this exact completion')
                    pairs.add(tuple(blocks[edge.block].arguments[:2]))
        if op.terminator is not None:
            for edge in getattr(op.terminator, 'successors', ()):
                if edge.block in incoming:
                    incoming[edge.block].append((op, edge))
    # Same fixed-point provenance check as the existing module C adapter:
    # forwarding may preserve a pair, never combine two invocation failures.
    changed = True
    while changed:
        changed = False
        for block in blocks.values():
            refs = [v for v in block.arguments if type(values[v]) is ReferenceValue]
            if len(refs) != 2 or tuple(refs) in pairs or not incoming[block.id]:
                continue
            positions = [block.arguments.index(v) for v in refs]
            sources = []
            for op, edge in incoming[block.id]:
                arguments = [edge.arguments[i] for i in positions]
                own = {u.id: u for u in op.uses}
                sources.append(tuple(own[u].value for u in arguments) if all(u in own for u in arguments) else None)
            if all(pair in pairs for pair in sources):
                pairs.add(tuple(refs)); changed = True
    for packet in graph.exception_packets:
        need((uses[packet.exception].value, uses[packet.traceback].value) in pairs,
             'packet must keep one actual completion/forwarded exception-traceback pair')
    for region in graph.regions:
        for port in region.exits:
            if port.kind is ExitKind.RAISE:
                need(port.types == (ProtocolValueType(P.EXCEPTION_PACKET), state), 'function Raise boundary must carry its packet')
    expected = {}
    for record in graph.exception_packets:
        expected[values[record.value].origin.operation] = K.FUNCTION_EXCEPTION_PACKET
    for record in graph.pending_completions:
        expected[values[record.value].origin.operation] = K.FUNCTION_PENDING_COMPLETION
    for rows, kind in ((graph.cleanup_enters, K.FUNCTION_HANDLED_CONTEXT_ENTER),
                       (graph.cleanup_resumes, K.FUNCTION_CLEANUP_RESUME),
                       (graph.cleanup_replacements, K.FUNCTION_CLEANUP_REPLACE)):
        for record in rows:
            expected[record.operation] = kind
    def node_for(reference, cls):
        found = [n for n in ast.walk(source_tree) if isinstance(n, cls) and hasattr(n, 'end_lineno')
                 and (n.lineno, n.end_lineno, n.col_offset, n.end_col_offset) ==
                 (reference.start_line, reference.end_line, reference.start_column, reference.end_column)]
        need(len(found) == 1, 'scope has no unique original AST node')
        atom = semantic.source_atoms.get(reference.atom_id)
        need(atom is not None and atom.reference == reference, 'scope source atom differs')
        return found[0]
    def within(owner, ancestor):
        while owner is not None:
            if owner == ancestor:
                return True
            owner = scopes[owner].parent
        return False

    def check_handler(handler, scope, entry):
        handler_source = next(a.reference for a in semantic.source_atoms.values() if a.kind == 'ExceptHandler' and (a.reference.start_line,a.reference.end_line,a.reference.start_column,a.reference.end_column)==(handler.lineno,handler.end_lineno,handler.col_offset,handler.end_col_offset))
        matches = [r for r in graph.exception_matches if protocols[r.operation].source == handler_source]
        validations = [operations[r.operation] for r in model.protocols
                       if r.kind is K.VALIDATE_EXCEPT_TYPE_314 and r.source == handler_source]
        if handler.type is not None:
            need(len(matches) == len(validations) == 1 and uses[matches[0].input_use].value == entry.arguments[-2],
                 'handler must match its own borrowed original caught reference')
            normal = next(e for e in validations[0].terminator.successors if e.kind is ExitKind.NORMAL)
            need(uses[matches[0].handler.use].value == blocks[normal.block].arguments[0],
                 'matcher did not consume its own handler validation result')
            handler_value = validations[0].uses[0].value
            origin = values[handler_value].origin
            if type(origin) is OperationResult:
                producer = operations[origin.operation]
            else:
                producers = [op for op in graph.operations if op.terminator is not None
                    and op.terminator.kind is TerminatorKind.INVOKE
                    and any(e.kind is ExitKind.NORMAL and e.block == origin.block for e in op.terminator.successors)]
                need(len(producers) == 1, 'handler result has no unique actual evaluation')
                producer = producers[0]
            need(node_for(links[producer.id].source, ast.expr) is handler.type,
                 'handler validation did not evaluate its original AST expression')
            definition = semantic.definitions.get(links[producer.id].semantic_operation)
            if definition is None:
                # The initial explicit capability admitted only this exact
                # ordinary formal-name BindingRead, before the SG bridge.
                formals = {semantic.slots[p.slot].name:p.slot for p in interface.parameters}
                reads = [r for r in graph.binding_reads if r.operation == producer.id and r.normal_result == handler_value]
                need(isinstance(handler.type, ast.Name) and handler.type.id in formals
                     and len(reads) == 1 and values[uses[reads[0].binding].value].slot == formals[handler.type.id],
                     'legacy handler has no exact original formal binding')
            else:
                need(definition.code_id == links[producer.id].source.atom_id.wire
                     and links[producer.id].source.atom_id in definition.source_atoms,
                     'handler evaluation lost exact original SG ownership')
        else:
            need(not matches and not validations, 'bare handler must not fabricate matching/type validation')
        return matches[0] if matches else None

    for record in graph.cleanup_interfaces:
        scope, protected = scopes[record.scope], scopes[record.protected]
        atom = semantic.source_atoms[scope.source.atom_id]
        if atom.kind == 'With':
            need(C.FUNCTION_WITH_314_V1 in language.capabilities, 'With cleanup requires its explicit source capability')
            node = node_for(scope.source, ast.With)
            need(protected.source == scope.source, 'With cleanup/protected source differs')
            suites = ((protected, [*node.body, *(i.optional_vars for i in node.items if i.optional_vars is not None)]),)
            handlers = ()
        elif atom.kind == 'Try':
            node = node_for(scope.source, ast.Try)
            need(protected.source == scope.source, 'cleanup/protected original Try differs')
            if node.finalbody:
                need(not node.handlers, 'combined handler/finally protocol not implemented')
                suites = ((protected, node.body), (scope, node.finalbody))
                handlers = ()
            else:
                need(bool(node.handlers), 'exception cleanup has no original handler clauses')
                suites = ((scope, node.handlers),)
                handlers = node.handlers
        else:
            handler = node_for(scope.source, ast.ExceptHandler)
            node = node_for(protected.source, ast.Try)
            need(len(node.handlers) == 1 and node.handlers[0] is handler and not handler.name and not node.finalbody,
                 'legacy handler cleanup original source differs')
            suites = ((scope, [handler]),)
            handlers = (handler,)
        if handlers:
            gate = blocks[next(iter(protected.blocks))]
            need(len(protected.blocks) == 1, 'handler must keep its single propagation gate')
            route = operations[gate.operations[-1]]
            edges = [e for e in route.terminator.successors if e.block == record.entry]
            need(len(edges) == 1, 'handler has no exact original entry edge')
            entry = blocks[record.entry]
            token = uses[edges[0].arguments[-3]].value
            pending = next((r for r in graph.pending_completions if r.value == token), None)
            packet = next((r for r in graph.exception_packets if pending is not None
                           and r.value == uses[pending.payload].value), None)
            need(packet is not None and uses[edges[0].arguments[-2]].value == uses[packet.exception].value,
                 'handler caught-reference must come from this original pending packet')
            checked = [(handler,check_handler(handler,scope,entry)) for handler in handlers]
            def local_reachable(start):
                seen=set();todo=[start]
                while todo:
                    block=todo.pop()
                    if block in seen or not within(owners[block],scope.id):continue
                    seen.add(block);last=operations[blocks[block].operations[-1]]
                    todo.extend(e.block for e in getattr(last.terminator,'successors',()))
                return seen
            for index,(handler,matcher) in enumerate(checked):
                if matcher is None:continue
                branch=operations[matcher.branch]
                yes,no=branch.terminator.successors
                matched=local_reachable(yes.block);missed=local_reachable(no.block)
                for later,later_match in checked[index+1:]:
                    if later_match is None:continue
                    target=operation_blocks[later_match.operation]
                    need(target in missed and target not in matched,
                         'later handler evaluated on an earlier match or lost clause order')
            for handler,matcher in checked:
                if not handler.name:continue
                source=next(a.reference for a in semantic.source_atoms.values() if a.kind=='ExceptHandler'
                    and (a.reference.start_line,a.reference.end_line,a.reference.start_column,a.reference.end_column)==
                    (handler.lineno,handler.end_lineno,handler.col_offset,handler.end_col_offset))
                bound=[op for op in graph.operations if links[op.id].source==source
                    and protocols.get(op.id) is not None and protocols[op.id].kind is K.FRAME_BIND
                    and len(op.uses)==3 and op.uses[1].value==entry.arguments[-2]]
                need(len(bound)==1,'handler alias must bind this one original caught reference')
                clears={op.id for op in graph.operations if links[op.id].source==source
                    and protocols.get(op.id) is not None and protocols[op.id].kind is K.FUNCTION_CLEAR_EXCEPTION_NAME}
                need(bool(clears),'handler alias omitted all normal/exceptional name cleanup')
                start=operation_blocks[bound[0].id];todo=[(start,blocks[start].operations.index(bound[0].id)+1)];seen=set()
                while todo:
                    block,offset=todo.pop()
                    if(block,offset)in seen:continue
                    seen.add((block,offset));identities=blocks[block].operations[offset:]
                    if any(identity in clears for identity in identities):continue
                    need(block!=entry.id,'handler alias crossed a new caught entry without clearing')
                    last=operations[blocks[block].operations[-1]]
                    need(last.terminator is not None and last.terminator.kind not in (TerminatorKind.RETURN,TerminatorKind.RAISE),
                         'handler completion bypassed as-name clear/delete')
                    for edge in getattr(last.terminator,'successors',()):
                        target=blocks[edge.block]
                        need(within(owners[target.id],scope.id) or links[target.operations[0]].source==source,
                             'handler alias escaped its cleanup corridor before clearing')
                        todo.append((target.id,0))
        for source_scope, suite in suites:
            spans = [(n.lineno, n.end_lineno, n.col_offset, n.end_col_offset) for n in suite]
            for block in blocks.values():
                if not within(owners[block.id], source_scope.id):
                    continue
                for identity in block.operations:
                    source = links[identity].source
                    if source == scope.source or source == protected.source:
                        continue
                    need(source.path == scope.source.path and source.fingerprint == scope.source.fingerprint
                         and any((a, c) <= (source.start_line, source.start_column)
                             and (source.end_line, source.end_column) <= (b, d) for a, b, c, d in spans),
                         'protected/cleanup operation came from another source suite')
    # Source Return may use an internal FALLTHROUGH continuation so canonical
    # C1 route/dispatch-only blocks remain unchanged. Its real reference must
    # reach the frame-closing ordinary RETURN landing through actual SSA Uses.
    incoming = {block:[] for block in blocks}
    for op in graph.operations:
        for edge in getattr(op.terminator,'successors',()):
            incoming[edge.block].append((op,edge))
    value_sources = {}
    for row in metadata.value_links:value_sources.setdefault(row.value,[]).append(row.source)
    for pending in graph.pending_completions:
        constructor=operations[values[pending.value].origin.operation]
        source=links[constructor.id].source
        if semantic.source_atoms[source.atom_id].kind!='Return':continue
        node=node_for(source,ast.Return)
        port=next(p for p in graph.control_ports if p.id==pending.port)
        from scar.ir.program.control import LanguageCompletionKind
        need(port.kind is LanguageCompletionKind.FALLTHROUGH and port.scope==roots[0].id
             and port.block is not None and pending.payload is None,
             'source Return needs its exact internal post-cleanup continuation')
        target=blocks[port.block];last=operations[target.operations[-1]]
        need(last.terminator.kind is TerminatorKind.RETURN and links[last.id].source==source,
             'source Return continuation does not actually close/return')
        returned=uses[last.terminator.values[0]].value
        expected_node=node.value if node.value is not None else node
        expected_span=(expected_node.lineno,expected_node.end_lineno,expected_node.col_offset,expected_node.end_col_offset)
        todo=[returned];seen=set();leaves=0
        while todo:
            value=todo.pop()
            if value in seen:continue
            seen.add(value);record=values[value]
            exact=[r for r in value_sources.get(value,())if (r.start_line,r.end_line,r.start_column,r.end_column)==expected_span]
            if exact:
                if node.value is None:
                    from scar.ir.program.model import LiteralOrigin
                    need(type(record.origin)is LiteralOrigin and record.origin.value is None,'empty return changed None')
                leaves+=1;continue
            need(type(record.origin)is BlockArgument,'return carrier did not originate at its exact source expression')
            for operation,edge in incoming[record.origin.block]:
                if hasattr(edge,'port') and edge.port!=port.id:continue
                operand=edge.arguments[record.origin.index]
                own={u.id:u for u in operation.uses}
                need(operand in own,'return carrier cannot be reconstructed from a guessed completion payload')
                todo.append(own[operand].value)
        need(leaves>0,'return carrier has no original expression leaf')
    for block in blocks.values():
        if not block.operations:
            continue
        final = operations[block.operations[-1]]
        if final.terminator is None or final.terminator.kind is not TerminatorKind.RAISE:
            continue
        need(len(block.operations) >= 2, 'packet exit omitted its conditional frame cleanup')
        before = operations[block.operations[-2]]
        need(protocols.get(before.id) is not None and protocols[before.id].kind is K.FUNCTION_FRAME_EXIT_EXCEPTION_PACKET,
             'packet exit has no exact preceding frame protocol')
        expected[before.id] = K.FUNCTION_FRAME_EXIT_EXCEPTION_PACKET
        local_roots = tuple(v for v in block.arguments if type(values[v]) is LocalBindingValue)
        need(not local_roots or len(block.operations) >= 3,
             'exception frame omitted its current local roots')
        if len(block.operations) >= 3:
            binding_exit = operations[block.operations[-3]]
            marker = protocols.get(binding_exit.id)
            if marker is not None and marker.kind is K.FUNCTION_FRAME_EXIT_BINDINGS:
                need(all(type(values[u.value]) is LocalBindingValue for u in binding_exit.uses[:-1])
                     and tuple(u.value for u in binding_exit.uses[:-1]) == local_roots
                     and type(values[binding_exit.uses[-1].value]) is StateVersionValue
                     and not binding_exit.effects_complete
                     and set(binding_exit.behaviors) == {Behavior.READ, Behavior.WRITE, Behavior.MEMORY}
                     and len(binding_exit.accesses) == 1
                     and binding_exit.accesses[0].after == before.uses[-1].value,
                     'frame binding roots must feed the following packet exit current world')
                expected[binding_exit.id] = K.FUNCTION_FRAME_EXIT_BINDINGS
            else:
                need(not local_roots, 'exception frame bypassed exact local-binding cleanup')
        payload = values[before.uses[0].value]
        need(type(payload) is ProtocolValue and payload.protocol is P.EXCEPTION_PACKET,
             'frame exceptional payload is not the selected packet')
        need(not before.effects_complete and set(before.behaviors) == {Behavior.READ, Behavior.WRITE, Behavior.MEMORY}
             and before.terminator is None and len(before.accesses) == 1 and before.accesses[0].mode is AccessMode.READ_WRITE,
             'frame packet cleanup must advance its incomplete coarse world')
        need(all(type(values[u.value]) in (ReferenceValue, LocalBindingValue) for u in before.uses[1:-1]),
             'private pending/context token escaped with frame roots')
        own = {u.id: u for u in final.uses}
        need(tuple(own[u].value for u in final.terminator.values) == (payload.id, before.accesses[0].after),
             'packet/world differs from actual frame post-state')
    for identity in actual:
        kind = protocols[identity].kind
        if kind is K.FUNCTION_INPLACE_BINARY:
            node = node_for(protocols[identity].source, ast.AugAssign)
            operation = operations[identity]
            need(isinstance(node.target, ast.Name) and isinstance(node.op,
                 (ast.Add, ast.Sub, ast.Mult, ast.MatMult, ast.Div, ast.FloorDiv,
                  ast.Mod, ast.Pow, ast.LShift, ast.RShift, ast.BitOr, ast.BitXor, ast.BitAnd)),
                 'in-place operation needs an original supported Name AugAssign')
            need(operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
                 and len(operation.uses) == 3 and operation.invoke_arguments == tuple(u.id for u in operation.uses)
                 and all(type(values[u.value]) is ReferenceValue for u in operation.uses[:-1])
                 and type(values[operation.uses[-1].value]) is StateVersionValue
                 and not operation.effects_complete and operation.callee is None
                 and tuple(s.types for s in operation.completions) == ((ref, state), (ref, ref, state)),
                 'in-place operation lost its ordered references/world/completions')
            sources = {(r.operation, r.use):r for r in metadata.use_links}
            for use, original, role, index in zip(operation.uses, (node.target, node.value),
                                                ('augassign-left', 'augassign-right'), (0, 1)):
                link = sources[(identity, use.id)]
                need(node_for(link.source, ast.expr) is original and (link.role, link.index) == (role, index),
                     'in-place operands do not use the original target-before-RHS AST')
            normal = blocks[operation.terminator.successors[0].block]
            assigned = [r for r in graph.binding_definitions if r.payload is not None
                        and uses[r.payload].value == normal.arguments[0]]
            need(len(assigned) == 1 and semantic.slots[values[assigned[0].value].slot].name == node.target.id
                 and semantic.slots[values[assigned[0].value].slot].owner == interface.definition,
                 'in-place result must rebind the original local slot')
            expected[identity] = kind
        elif kind is K.FUNCTION_START_PROPAGATION:
            node_for(protocols[identity].source, ast.Assert)
            operation = operations[identity]
            constructors = [operations[r.operation] for r in model.protocols
                            if r.kind is K.MAKE_ASSERTION_ERROR and r.source == protocols[identity].source]
            need(len(constructors) == 1, 'assert propagation has no original allocation')
            edge = next(e for e in constructors[0].terminator.successors if e.kind is ExitKind.NORMAL)
            need(operation.uses[0].value == blocks[edge.block].arguments[0],
                 'assert propagation is not its actual newly allocated exception reference')
            expected[identity] = kind
        elif kind is K.FUNCTION_CLEAR_EXCEPTION_NAME:
            from scar.ir.program.bindings import BindingState
            from scar.ir.program.model import LiteralOrigin
            handler = node_for(protocols[identity].source, ast.ExceptHandler)
            op = operations[identity]
            need(handler.name is not None and len(op.uses) == 2
                 and type(values[op.uses[0].value]) is LocalBindingValue
                 and type(values[op.uses[1].value]) is StateVersionValue
                 and not op.effects_complete and op.terminator is None
                 and set(op.behaviors) == {Behavior.READ,Behavior.WRITE,Behavior.MEMORY}
                 and len(op.accesses) == 1 and op.accesses[0].mode is AccessMode.READ_WRITE,
                 'exception alias deletion lost exact binding/current world')
            bound = values[op.uses[0].value]
            slot = semantic.slots[bound.slot]
            need(slot.owner == interface.definition and slot.name == handler.name,
                 'exception alias deletion targets another source local')
            definition = next((r for r in graph.binding_definitions if r.value == bound.id), None)
            need(definition is not None and definition.state is BindingState.BOUND
                 and type(values[uses[definition.payload].value].origin) is LiteralOrigin
                 and values[uses[definition.payload].value].origin.value is None,
                 'exception alias must be overwritten with None before deletion')
            block = next(b for b in blocks.values() if identity in b.operations)
            position = block.operations.index(identity)
            need(position + 1 < len(block.operations), 'exception alias missing unbound definition')
            deleted = operations[block.operations[position+1]]
            records = [r for r in graph.binding_definitions if r.value in deleted.results]
            need(len(records) == 1 and records[0].state is BindingState.UNBOUND
                 and values[records[0].value].slot == bound.slot
                 and links[deleted.id].source == protocols[identity].source,
                 'exception alias deletion must define this same local UNBOUND')
            expected[identity] = kind
        elif kind is K.VALIDATE_EXCEPT_TYPE_314:
            node = node_for(protocols[identity].source, ast.ExceptHandler)
            op = operations[identity]
            need(node.type is not None and op.terminator is not None
                 and op.terminator.kind is TerminatorKind.INVOKE
                 and len(op.uses) == 2 and type(values[op.uses[0].value]) is ReferenceValue
                 and op.invoke_arguments == tuple(u.id for u in op.uses)
                 and not op.effects_complete and op.callee is None
                 and tuple((s.kind, s.types) for s in op.completions) ==
                     ((ExitKind.NORMAL, (ref, state)), (ExitKind.RAISE, (ref, ref, state))),
                 'handler class validation has no actual original expression operand')
            expected[identity] = kind
        elif kind is K.MATCH_EXCEPTION_BORROWED_314:
            node_for(protocols[identity].source, ast.ExceptHandler)
            need(any(row.operation == identity for row in graph.exception_matches),
                 'borrowed match has no canonical matcher authority')
            expected[identity] = kind
        need(expected.get(identity) is kind, 'control marker has no matching canonical constructor/action/source')
    need(set(expected) == actual, 'canonical C0/C1 operations are missing their exact source protocol markers')
    return actual
