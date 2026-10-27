"""Declared lexical control and SSA protocol checks, without cleanup authority.

Case facts derive from canonical producers and real CFG operand positions.
They are not execution frequencies, source correspondence or an unwind proof.
"""
from dataclasses import dataclass

from .control import (
    ControlScopeKind, LanguageCompletionKind as K, PendingDispatchTerminator,
    PendingPayload, ProtocolValueKind as P, ProtocolValueType,
)
from .cleanup import CleanupRouteTerminator
from .ids import ControlPortID, ValueID
from .model import (
    Behavior, BlockArgument, CompletionResult, ExitKind, FootprintKind,
    OperationResult, ProtocolValue, ReferenceValue, StateVersionValue,
    TerminatorKind, UseRole, ValueKind, ValueType,
)
from .resumption import (
    ResumeInput, SavedInput, SavedRole, SuspendTerminator, saved_actual_use,
)
from .drivers import BodyDriveResult
from .source_subjects import (
    ClassFrameABI, FrameKind, FunctionFrameABI, MappingFramePorts, ModuleUnitSource,
    SourceCompilationFrameRoot,
)
from scar.ir.v2.common import SourceReference


def _protocol(value, kind):
    return isinstance(value, ProtocolValue) and value.protocol is kind


@dataclass(frozen=True, slots=True)
class PendingFacts:
    value: ValueID
    ports: tuple[ControlPortID, ...]
    complete: bool


def derive_pending_facts(graph):
    """Derive port unions; no caller-supplied union or independent edge store.

    This internal derivation expects core structural validation first. Unknown
    cross-region/boundary origins stay incomplete instead of an empty proof.
    ProgramIndex exposes it only after full graph validation.
    """
    values = {v.id: v for v in graph.values}
    pending = {v.id for v in graph.values if _protocol(v, P.PENDING_COMPLETION)}
    facts = {v: set() for v in pending}
    incomplete = set()
    definitions = {d.value: d for d in graph.pending_completions}
    blocks = {b.id: b for r in graph.regions for b in r.blocks}
    operations = {o.id: o for o in graph.operations}
    region_entries = {r.entry for r in graph.regions}
    for identity in pending:
        value = values[identity]
        if identity in definitions:
            facts[identity].add(definitions[identity].port)
        elif isinstance(value.origin, OperationResult) or value.origin.block in region_entries:
            incomplete.add(identity)
    changed = True
    while changed:
        changed = False
        for operation in operations.values():
            term = operation.terminator
            if term is None:
                continue
            own = {u.id: u.value for u in operation.uses}
            saved_pending = {slot.use for slot in term.saved
                             if slot.role is SavedRole.PENDING_COMPLETION} if isinstance(
                                 term, SuspendTerminator) else set()
            selected = own.get(term.pending) if isinstance(
                term, (PendingDispatchTerminator, CleanupRouteTerminator)) else None
            for edge in term.successors:
                if isinstance(term, (PendingDispatchTerminator, CleanupRouteTerminator)):
                    if edge.port not in facts.get(selected, ()) and selected not in incomplete:
                        continue  # This case cannot carry another token either.
                for actual, formal in zip(edge.arguments, blocks[edge.block].arguments):
                    if formal not in pending:
                        continue
                    before = len(facts[formal]), formal in incomplete
                    actual_use = saved_actual_use(operation, actual)
                    if (isinstance(actual, (CompletionResult, ResumeInput, BodyDriveResult))
                            or isinstance(actual, SavedInput) and actual_use not in saved_pending):
                        incomplete.add(formal)
                    elif actual_use in own:
                        source = own[actual_use]
                        carried = facts.get(source, set())
                        if selected == source:
                            carried = carried & {edge.port}
                        facts[formal].update(carried)
                        if source in incomplete:
                            incomplete.add(formal)
                    if before != (len(facts[formal]), formal in incomplete):
                        changed = True
    return {v: PendingFacts(v, tuple(sorted(ports, key=lambda p: p.wire)),
                            bool(ports) and v not in incomplete)
            for v, ports in facts.items()}


def control_errors(graph):
    """Return structural issues after the ordinary core has validated CFG/state."""
    scopes = {s.id: s for s in graph.control_scopes}
    ports = {p.id: p for p in graph.control_ports}
    values = {v.id: v for v in graph.values}
    operations = {o.id: o for o in graph.operations}
    regions = {r.id: r for r in graph.regions}
    blocks = {b.id: b for r in graph.regions for b in r.blocks}
    block_region = {b.id: r.id for r in graph.regions for b in r.blocks}
    operation_block = {o: b.id for b in blocks.values() for o in b.operations}
    # Frame/caller and raw driver requests have dedicated interface validators.
    # Delivered exception packets still use C0 lexical ownership and packing.
    protocol_values = [v for v in graph.values if isinstance(v, ProtocolValue)
                       and v.protocol not in (P.FRAME_CONTEXT, P.DRIVE_CALLER_CONTEXT,
                                              P.RAW_DRIVER_REQUEST)]
    dispatches = [o for o in graph.operations if isinstance(
        o.terminator, (PendingDispatchTerminator, CleanupRouteTerminator))]
    if not (scopes or ports or protocol_values or dispatches or graph.frame_roots
            or graph.exception_packets or graph.pending_completions):
        return []
    issues = []

    def error(code, path, text):
        issues.append((code, path, text))

    owners = {}
    roots = {}
    for scope in scopes.values():
        if scope.region not in regions:
            error("control_scope_region", scope.id, "scope needs an existing region")
            continue
        if scope.kind in (ControlScopeKind.FUNCTION, ControlScopeKind.FRAME):
            if scope.region in roots:
                error("control_scope_root", scope.id, "one function/frame root per enabled region")
            roots[scope.region] = scope.id
            if regions[scope.region].entry not in scope.blocks:
                error("control_scope_entry", scope.id, "control root directly owns the region entry")
        elif scope.parent not in scopes or scopes[scope.parent].region != scope.region:
            error("control_scope_parent", scope.id, "parent must be in the same region")
        for block in scope.blocks:
            if block_region.get(block) != scope.region:
                error("control_scope_block", scope.id, "scope block must belong to its region")
            if block in owners:
                error("control_scope_owner", block, "one direct lexical owner per block")
            owners[block] = scope.id
    for scope in scopes.values():
        seen, current = set(), scope.id
        while current in scopes:
            if current in seen:
                error("control_scope_cycle", scope.id, "lexical ownership cannot cycle")
                break
            seen.add(current)
            current = scopes[current].parent
        if scope.region not in roots:
            error("control_scope_root", scope.id, "enabled region needs one function/frame root")
    for region_id in {s.region for s in scopes.values()} & regions.keys():
        if set(b.id for b in regions[region_id].blocks) != {
                b for b, s in owners.items() if scopes[s].region == region_id}:
            error("control_scope_partition", region_id, "direct scopes must cover every block exactly once")
    for value in protocol_values:
        if value.region not in roots:
            error("protocol_scope", value.id, "protocol values need declared lexical ownership")
    frame_roots = {row.scope: row for row in graph.frame_roots}
    environments = {row.id: row for row in graph.environments}
    for scope in scopes.values():
        if scope.kind is ControlScopeKind.FRAME and scope.id not in frame_roots:
            error("frame_root_missing", scope.id, "FRAME scope needs its unique entry authority")
    for root in graph.frame_roots:
        scope = scopes.get(root.scope)
        if scope is None or scope.kind is not ControlScopeKind.FRAME:
            error("frame_root_scope", root.scope, "frame root must name an existing FRAME scope")
            continue
        if scope.region not in regions:
            continue  # Already reported by the scope check.
        region = regions[scope.region]
        entry = blocks[region.entry]
        static = type(root) is SourceCompilationFrameRoot
        module = root.kind is FrameKind.MODULE
        expected_source = ModuleUnitSource if module else SourceReference
        if type(scope.source) is not expected_source:
            error("frame_root_subject", root.scope, "frame kind needs its exact source-subject category")
        elif static:
            if scope.source != root.code.source:
                error("frame_root_static_source", root.scope,
                      "source-compilation root must retain the scope's exact original source subject")
            if module and root.code.definition != scope.source.initializer:
                error("frame_root_static_definition", root.scope,
                      "module source-compilation root must retain the original initializer definition")
        else:
            path = scope.source.snapshot.path if module else scope.source.path
            if root.code.filename != path:
                error("frame_root_code", root.scope, "code filename must retain the source subject's logical path")
        if type(root.entry) is FunctionFrameABI:
            environment = environments.get(root.entry.environment)
            if environment is None or environment.region != region.id:
                error("frame_root_environment", root.scope,
                      "function ABI must reference this region's existing environment")
            if (static and environment is not None
                    and environment.code_definition != root.code.definition):
                error("frame_root_static_definition", root.scope,
                      "function source-compilation root must match the environment code definition")
            if len([layout for layout in graph.function_entries
                    if layout.environment == root.entry.environment]) != 1:
                error("frame_root_function_entry", root.scope,
                      "function ABI needs the unique existing formal/environment partition")
            continue
        if type(root.entry) is ClassFrameABI:
            if not static or root.kind is not FrameKind.CLASS:
                error("class_frame_root_abi", root.scope,
                      "ClassFrameABI is reserved for a source-compilation CLASS root")
                continue
            mapping = root.entry.mapping
            if any(environment.region == region.id for environment in graph.environments):
                error("class_frame_root_entry_authority", root.scope,
                      "class mapping ABI cannot also declare a function environment entry")
        elif type(root.entry) is MappingFramePorts:
            mapping = root.entry
            if static and root.kind is FrameKind.CLASS:
                error("class_frame_root_abi", root.scope,
                      "source-compilation CLASS root requires ClassFrameABI")
                continue
        else:
            continue  # Exact ABI/kind discrimination is a record invariant.
        if type(root.entry) is MappingFramePorts and any(
                environment.region == region.id for environment in graph.environments):
            error("frame_root_entry_authority", root.scope,
                  "mapping ABI cannot also declare a function environment entry")
        references = (mapping.locals_namespace, mapping.globals_namespace,
                      mapping.builtins_namespace) + mapping.closure_cells
        expected_ports = references + (mapping.world,)
        if set(entry.arguments) != set(expected_ports):
            error("frame_root_partition", root.scope,
                  "mapping ABI must cover exactly this region's entry ports")
        for identity in expected_ports:
            value = values.get(identity)
            kind = StateVersionValue if identity == mapping.world else ReferenceValue
            if (not isinstance(value, kind) or value.region != region.id
                    or not isinstance(value.origin, BlockArgument)
                    or value.origin.block != entry.id
                    or not 0 <= value.origin.index < len(entry.arguments)
                    or entry.arguments[value.origin.index] != identity):
                error("frame_root_port", identity,
                      "mapping role must name its exact typed region-entry argument")
    if issues:
        return issues

    def ancestor(outer, inner):
        while inner is not None:
            if inner == outer:
                return True
            inner = scopes[inner].parent
        return False

    def target_active(port, inner):
        if not ancestor(port.scope, inner):
            return False
        if port.kind in (K.BREAK, K.CONTINUE):
            while inner is not None:
                if scopes[inner].kind is ControlScopeKind.LOOP:
                    return inner == port.scope
                inner = scopes[inner].parent
            return False
        return True

    for port in ports.values():
        scope = scopes.get(port.scope)
        if scope is None:
            error("control_port_scope", port.id, "port needs an existing lexical scope")
            continue
        if port.exit is not None:
            expected_kind = ExitKind.NORMAL if port.kind is K.RETURN else ExitKind.RAISE
            exit_port = next((p for p in regions[scope.region].exits if p.name == port.exit), None)
            if (scope.kind not in (ControlScopeKind.FUNCTION, ControlScopeKind.FRAME)
                    or exit_port is None or exit_port.kind is not expected_kind):
                error("control_port_exit", port.id, "root port must name the correct existing region exit")
            elif [t for t in exit_port.types if t.kind is not ValueKind.STATE] != [
                    ValueType(ValueKind.REFERENCE) if port.kind is K.RETURN
                    else ProtocolValueType(P.EXCEPTION_PACKET)]:
                error("control_port_payload", port.id, "exit must carry one matching language payload and state")
        elif block_region.get(port.block) != scope.region:
            error("control_port_block", port.id, "landing must belong to the same region")
        elif port.kind in (K.BREAK, K.CONTINUE):
            inside = ancestor(scope.id, owners[port.block])
            if scope.kind is not ControlScopeKind.LOOP or inside != (port.kind is K.CONTINUE):
                error("control_port_loop", port.id, "break lands outside and continue inside its declared loop")
    if issues:
        return issues

    packet_definitions = {d.value: d for d in graph.exception_packets}
    pending_definitions = {d.value: d for d in graph.pending_completions}

    def definition_operation(identity, protocol):
        value = values.get(identity)
        if not _protocol(value, protocol) or not isinstance(value.origin, OperationResult):
            error("protocol_definition", identity, "definition must own a matching protocol OperationResult")
            return None
        operation = operations[value.origin.operation]
        if (operation.results != (identity,) or operation.terminator is not None
                or operation.callee is not None or operation.accesses
                or not operation.effects_complete
                or set(operation.behaviors) != {Behavior.CONTROL}):
            error("protocol_pack_operation", identity, "pack only constructs its one control payload; state/effects stay outside")
        return operation

    for definition in graph.exception_packets:
        operation = definition_operation(definition.value, P.EXCEPTION_PACKET)
        if operation is None:
            continue
        own = {u.id: u for u in operation.uses}
        if set(own) != {definition.exception, definition.traceback} or any(
                not isinstance(values[u.value], ReferenceValue) for u in operation.uses):
            error("exception_packet_operands", definition.value, "packet needs its exact exception/traceback reference Uses")
    for definition in graph.pending_completions:
        operation = definition_operation(definition.value, P.PENDING_COMPLETION)
        if operation is None:
            continue
        port = ports.get(definition.port)
        if port is None:
            error("pending_port", definition.value, "pending constructor needs an existing control port")
            continue
        if not target_active(port, owners[operation_block[operation.id]]):
            error("pending_target_scope", definition.value, "target must be active; unlabelled transfer selects the nearest loop")
        own = {u.id: u for u in operation.uses}
        expected = {definition.payload} if port.kind in (K.RETURN, K.RAISE) else set()
        if set(own) != expected or (not expected and definition.payload is not None):
            error("pending_payload", definition.value, "constructor must use exactly the payload required by its port")
        elif expected:
            actual = values[own[definition.payload].value]
            if not (isinstance(actual, ReferenceValue) if port.kind is K.RETURN
                    else _protocol(actual, P.EXCEPTION_PACKET)):
                error("pending_payload_type", definition.value, "Return needs Reference; Raise needs an exception packet")
    for value in protocol_values:
        if isinstance(value.origin, OperationResult):
            definitions = (pending_definitions if value.protocol is P.PENDING_COMPLETION
                           else packet_definitions if value.protocol is P.EXCEPTION_PACKET
                           else {row.saved_context: row for row in graph.cleanup_enters})
            # A known ordinary call transports the callee's typed result; it
            # is not a local packet constructor. Core call validation checks
            # the whole argument/result signature separately. Pending tokens
            # and cleanup contexts retain their lexical constructor rules.
            operation = operations[value.origin.operation]
            callee = regions.get(operation.callee)
            normal = (() if callee is None else tuple(exit_ for exit_ in callee.exits
                        if exit_.kind is ExitKind.NORMAL))
            slot = value.origin.index
            carrier = (value.protocol is P.EXCEPTION_PACKET
                and operation.callee is not None and operation.terminator is None
                and not operation.accesses and 0 <= slot < len(operation.results)
                and operation.results[slot] == value.id and len(normal) == 1
                and slot < len(normal[0].types)
                and normal[0].types[slot] == ProtocolValueType(P.EXCEPTION_PACKET))
            if value.id not in definitions and not carrier:
                error("protocol_definition_missing", value.id, "protocol result needs its unique typed constructor")
    if issues:
        return issues

    facts = derive_pending_facts(graph)
    for fact in facts.values():
        if not fact.complete:
            error("pending_origin", fact.value, "pending case set has an unsupported boundary or no constructor source")
    cleanup_operands = {}
    for row in graph.cleanup_enters:
        cleanup_operands[row.operation] = {row.pending}
    for row in graph.cleanup_resumes:
        cleanup_operands[row.operation] = {row.pending}
    for row in graph.cleanup_replacements:
        cleanup_operands[row.operation] = {row.saved_pending, row.replacement}
    body_regions = {row.region for row in graph.resumable_bodies}
    detach_operations = {row.operation for row in graph.frame_context_detaches}
    for operation in graph.operations:
        term = operation.terminator
        saved_pending = {slot.use for slot in term.saved
                         if slot.role is SavedRole.PENDING_COMPLETION} if isinstance(
                             term, SuspendTerminator) else set()
        for use in operation.uses:
            if not _protocol(values[use.value], P.PENDING_COMPLETION):
                continue
            bound = (isinstance(term, (PendingDispatchTerminator, CleanupRouteTerminator))
                     and term.pending == use.id)
            bound |= term is not None and any(
                saved_actual_use(operation, actual) == use.id
                and (not isinstance(actual, SavedInput) or use.id in saved_pending)
                for edge in term.successors for actual in edge.arguments)
            # A declared private retained value need not be restored by a case.
            bound |= use.id in saved_pending
            bound |= use.id in cleanup_operands.get(operation.id, ())
            if not bound or use.id in (*operation.call_arguments, *operation.invoke_arguments):
                error("pending_escape", use.id, "pending only travels on canonical typed local control operands")
        if not isinstance(term, (PendingDispatchTerminator, CleanupRouteTerminator)):
            continue
        selected = next(u for u in operation.uses if u.id == term.pending)
        if not _protocol(values[selected.value], P.PENDING_COMPLETION):
            error("pending_dispatch_type", operation.id, "dispatch selector must be pending, not a packet or Python value")
            continue
        if set(e.port for e in term.successors) != set(facts[selected.value].ports):
            error("pending_dispatch_cases", operation.id, "dispatch cases must equal the derived incoming port union")
        for edge in term.successors:
            port = ports.get(edge.port)
            if port is None:
                error("pending_dispatch_port", operation.id, "dispatch case needs an existing port")
                continue
            if not target_active(port, owners[operation_block[operation.id]]):
                error("pending_dispatch_scope", operation.id, "case target must remain active with the nearest loop")
            if isinstance(term, CleanupRouteTerminator):
                continue  # C1 validates the next cleanup step, without projecting payloads.
            projections = [(i, values[v]) for i, (a, v) in enumerate(zip(edge.arguments, blocks[edge.block].arguments))
                           if isinstance(a, PendingPayload)]
            has_payload = port.kind in (K.RETURN, K.RAISE)
            if len(projections) != int(has_payload):
                error("pending_projection_count", operation.id, "project a payload exactly once only for Return/Raise")
            for _, formal in projections:
                correct = (isinstance(formal, ReferenceValue) if port.kind is K.RETURN
                           else _protocol(formal, P.EXCEPTION_PACKET))
                if not correct:
                    error("pending_projection_type", formal.id, "case projection differs from its language payload type")
                if isinstance(formal, ReferenceValue) and (
                        formal.targets is not None or formal.referent_identity is not None
                        or formal.selector.kind is not FootprintKind.UNKNOWN):
                    error("pending_projection_precision", formal.id, "projection grants no identity or alias summary")
            if port.block is not None:
                if edge.block != port.block:
                    error("pending_landing", operation.id, "block case must land at its exact declared port")
            else:
                landing = blocks[edge.block]
                final = operations[landing.operations[-1]]
                expected_kind = TerminatorKind.RETURN if port.kind is K.RETURN else TerminatorKind.RAISE
                detached_shim = (len(landing.operations) == 2
                                 and block_region[landing.id] in body_regions
                                 and landing.operations[0] in detach_operations)
                if ((len(landing.operations) != 1 and not detached_shim)
                        or final.terminator.kind is not expected_kind
                        or final.terminator.exit != port.exit):
                    error("pending_exit_landing", operation.id, "exit case needs an exact forwarding exit shim")
                elif len(projections) == 1:
                    payload_id = projections[0][1].id
                    nonstate = [u.value for u in final.uses if not isinstance(values[u.value], StateVersionValue)]
                    if nonstate != [payload_id]:
                        error("pending_exit_payload", operation.id, "exit shim must forward the selected payload unchanged")
    return issues


__all__ = ["PendingFacts", "control_errors", "derive_pending_facts"]
