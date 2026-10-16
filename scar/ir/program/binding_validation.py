"""Cross-record checks for local-binding SSA and local reads."""
from __future__ import annotations

from dataclasses import dataclass

from .bindings import BindingState
from .ids import UseID, ValueID
from .model import (
    AccessMode, Behavior, BlockArgument, BindingDefinition, BindingRead, CompletionResult,
    CompletionSuccessor, LocalBindingValue, OperationResult, ProgramGraph,
    ExitKind, ReferenceValue, StateVersionValue, TerminatorKind, UseRole,
    ValueType, ValueKind, FootprintKind,
)


@dataclass(frozen=True, slots=True)
class BindingValidationIssue:
    code: str
    path: str
    message: str


def _compute_binding_facts(token_values, definitions, incoming_binding_values):
    """Shared fixed-point implementation for validation and read queries."""
    facts: dict[ValueID, frozenset[BindingState]] = {}
    for identity, definition in definitions.items():
        if definition.state is BindingState.UNKNOWN:
            facts[identity] = frozenset((BindingState.BOUND, BindingState.UNBOUND))
        else:
            facts[identity] = frozenset((definition.state,))
    changed = True
    rounds = 0
    while changed and rounds <= len(token_values) + 1:
        rounds += 1
        changed = False
        for identity, incoming in incoming_binding_values.items():
            merged = frozenset(state for source in incoming for state in facts.get(source, ()))
            updated = facts.get(identity, frozenset()) | merged
            if updated != facts.get(identity, frozenset()):
                facts[identity] = updated
                changed = True
    return facts


def derive_binding_facts(graph: ProgramGraph) -> dict[ValueID, frozenset[BindingState]]:
    """Return possible BOUND/UNBOUND facts for each local-binding token.

    Call this on a graph that has passed ``program.validation.require_valid``.
    For malformed graphs it returns only facts recoverable from well-shaped
    definitions and same-slot CFG carries; it does not validate or authorize
    graph transformations. An INVOKE NORMAL successor for a BindingRead is
    feasible only when that read's input token includes BOUND.
    """
    if type(graph) is not ProgramGraph:
        raise TypeError("derive_binding_facts requires ProgramGraph")
    values = {value.id: value for value in graph.values}
    operations = {operation.id: operation for operation in graph.operations}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    tokens = {identity: value for identity, value in values.items()
              if isinstance(value, LocalBindingValue)}
    definitions = {item.value: item for item in graph.binding_definitions}
    uses = {use.id: (operation.id, use) for operation in graph.operations
            for use in operation.uses}
    incoming: dict[ValueID, list[ValueID]] = {
        identity: [] for identity, value in tokens.items()
        if isinstance(value.origin, BlockArgument)
    }
    for region in graph.regions:
        for block in region.blocks:
            if not block.operations:
                continue
            terminator = operations.get(block.operations[-1])
            if terminator is None or terminator.terminator is None:
                continue
            for edge in terminator.terminator.successors:
                target = blocks.get(edge.block)
                if target is None:
                    continue
                for actual, formal in zip(edge.arguments, target.arguments):
                    formal_value = values.get(formal)
                    if not isinstance(formal_value, LocalBindingValue) or not isinstance(actual, UseID):
                        continue
                    pair = uses.get(actual)
                    source = values.get(pair[1].value) if pair is not None else None
                    if (pair is not None and pair[0] == terminator.id
                            and pair[1].role is UseRole.LOCAL_BINDING
                            and isinstance(source, LocalBindingValue)
                            and source.slot == formal_value.slot):
                        incoming[formal].append(source.id)
    return _compute_binding_facts(tokens, definitions, incoming)


def _normal_completion_reference_for_read(graph, reference, operation, blocks,
                                          operations, operation_block) -> bool:
    if isinstance(reference.origin, OperationResult):
        producer = operations.get(reference.origin.operation)
        return (producer is not None and reference.origin.index < len(producer.results)
                and producer.results[reference.origin.index] == reference.id)
    if not isinstance(reference.origin, BlockArgument):
        return False
    block_id = operation_block.get(operation.id)
    if reference.origin.block != block_id:
        return False
    block = blocks.get(block_id)
    if block is None or reference.origin.index >= len(block.arguments):
        return False
    if block.arguments[reference.origin.index] != reference.id:
        return False

    incoming = []
    for region in graph.regions:
        for source_block in region.blocks:
            if not source_block.operations:
                continue
            source = operations.get(source_block.operations[-1])
            if source is None or source.terminator is None:
                continue
            for edge in source.terminator.successors:
                if edge.block == block_id:
                    incoming.append((source, edge))
    if len(incoming) != 1:
        return False
    source, edge = incoming[0]
    if (source.terminator.kind is not TerminatorKind.INVOKE
            or not isinstance(edge, CompletionSuccessor)
            or edge.kind is not ExitKind.NORMAL):
        return False
    actual = edge.arguments[reference.origin.index]
    if not isinstance(actual, CompletionResult):
        return False
    signature = next((item for item in source.completions
                      if item.kind is ExitKind.NORMAL), None)
    return (signature is not None and actual.index < len(signature.types)
            and signature.types[actual.index] == ValueType(ValueKind.REFERENCE))


def validate_bindings(graph: ProgramGraph) -> tuple[BindingValidationIssue, ...]:
    """Validate binding definitions, CFG carries, and read completion shape.

    This validates typed connections and derived boundness only. It does not
    prove that an operation implements Python's local-load or assignment
    semantics; the source-profile replay must establish that correspondence.
    """
    if (not graph.binding_definitions and not graph.binding_reads
            and not any(isinstance(value, LocalBindingValue) for value in graph.values)):
        return ()

    issues: list[BindingValidationIssue] = []

    def error(code: str, path: object, message: str) -> None:
        issues.append(BindingValidationIssue(code, str(path), message))

    values = {value.id: value for value in graph.values}
    operations = {operation.id: operation for operation in graph.operations}
    regions = {region.id: region for region in graph.regions}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    block_region = {block.id: region.id for region in graph.regions for block in region.blocks}
    operation_block = {operation_id: block.id for block in blocks.values()
                       for operation_id in block.operations}
    uses = {use.id: (operation.id, use) for operation in graph.operations
            for use in operation.uses}

    definitions: dict[ValueID, BindingDefinition] = {}
    for definition in graph.binding_definitions:
        if definition.value in definitions:
            error("binding_definition_duplicate", definition.value,
                  "each operation-result local binding needs one definition")
            continue
        definitions[definition.value] = definition
        value = values.get(definition.value)
        if not isinstance(value, LocalBindingValue):
            error("binding_definition_value", definition.value,
                  "definition must name a LocalBindingValue")
            continue
        if not isinstance(value.origin, OperationResult):
            error("binding_definition_origin", definition.value,
                  "only operation-result binding tokens have definition records")
            continue
        producer = operations.get(value.origin.operation)
        if producer is None:
            error("binding_definition_producer", definition.value,
                  "binding producer operation is missing")
            continue
        if definition.payload is not None:
            pair = uses.get(definition.payload)
            if pair is None or pair[0] != producer.id:
                error("binding_payload_owner", definition.value,
                      "payload use must belong to the binding producer")
            elif pair[1].role is not UseRole.REFERENCE or not isinstance(values.get(pair[1].value), ReferenceValue):
                error("binding_payload_type", definition.value,
                      "bound payload must be an ordinary ReferenceValue use")
        if definition.previous is not None:
            pair = uses.get(definition.previous)
            previous = values.get(pair[1].value) if pair is not None and pair[0] == producer.id else None
            if (pair is None or pair[0] != producer.id
                    or pair[1].role is not UseRole.LOCAL_BINDING
                    or not isinstance(previous, LocalBindingValue)
                    or previous.slot != value.slot):
                error("binding_previous", definition.value,
                      "previous binding must be a same-slot local-binding use of the producer")
        if definition.state is BindingState.UNKNOWN:
            coarse_read_write = any(
                access.mode is AccessMode.READ_WRITE and not access.full_overwrite
                for access in producer.accesses)
            if producer.effects_complete or not coarse_read_write:
                error("binding_unknown_effect", definition.value,
                      "UNKNOWN updates require an incomplete producer with coarse READ_WRITE state")

    token_values = {identity: value for identity, value in values.items()
                    if isinstance(value, LocalBindingValue)}
    for identity, value in token_values.items():
        if isinstance(value.origin, OperationResult):
            if identity not in definitions:
                error("binding_definition_missing", identity,
                      "every operation-result local-binding token needs a definition")
        elif isinstance(value.origin, BlockArgument):
            if identity in definitions:
                error("binding_argument_definition", identity,
                      "block-argument binding state is derived from incoming CFG edges")
            region = regions.get(block_region.get(value.origin.block))
            if region is not None and region.entry == value.origin.block:
                error("binding_entry_argument", identity,
                      "local bindings must be initialized by definitions, not function entry ports")
        else:
            error("binding_origin", identity,
                  "local-binding origin must be a block argument or operation result")
    for identity in definitions:
        if identity not in token_values:
            error("binding_definition_orphan", identity,
                  "definition does not correspond to a local-binding value")

    # Collect each local-binding block argument's actual incoming values. The
    # regular graph validator separately checks edge arity, ownership and type.
    incoming_binding_values: dict[ValueID, list[ValueID]] = {
        identity: [] for identity, value in token_values.items()
        if isinstance(value.origin, BlockArgument)
    }
    for region in graph.regions:
        for block in region.blocks:
            if not block.operations:
                continue
            terminator = operations.get(block.operations[-1])
            if terminator is None or terminator.terminator is None:
                continue
            for edge in terminator.terminator.successors:
                target = blocks.get(edge.block)
                if target is None:
                    continue
                for actual, formal in zip(edge.arguments, target.arguments):
                    formal_value = values.get(formal)
                    if not isinstance(formal_value, LocalBindingValue):
                        continue
                    if isinstance(actual, CompletionResult):
                        error("binding_completion_result", formal,
                              "local-binding tokens cannot be fabricated from completion results")
                    elif isinstance(actual, UseID):
                        pair = uses.get(actual)
                        actual_value = values.get(pair[1].value) if pair is not None else None
                        if (pair is None or pair[0] != terminator.id
                                or pair[1].role is not UseRole.LOCAL_BINDING
                                or not isinstance(actual_value, LocalBindingValue)
                                or actual_value.slot != formal_value.slot):
                            error("binding_edge_slot", formal,
                                  "CFG carries must forward the same local slot with LOCAL_BINDING role")
                        elif formal in incoming_binding_values:
                            incoming_binding_values[formal].append(actual_value.id)

    for identity, incoming in incoming_binding_values.items():
        if not incoming:
            error("binding_merge_inputs", identity,
                  "a local-binding block argument needs at least one incoming binding")

    reads_by_operation: dict[object, BindingRead] = {}
    for read in graph.binding_reads:
        if read.operation in reads_by_operation:
            error("binding_read_duplicate", read.operation,
                  "each local-read operation needs one canonical BindingRead")
            continue
        reads_by_operation[read.operation] = read
        operation = operations.get(read.operation)
        pair = uses.get(read.binding)
        token = values.get(pair[1].value) if pair is not None else None
        if operation is None:
            error("binding_read_operation", read.operation,
                  "read operation is missing")
            continue
        if (pair is None or pair[0] != operation.id
                or pair[1].role is not UseRole.LOCAL_BINDING
                or not isinstance(token, LocalBindingValue)):
            error("binding_read_input", read.operation,
                  "read must consume one local-binding token with LOCAL_BINDING role")
            continue
        local_binding_uses = {use.id for use in operation.uses
                              if use.role is UseRole.LOCAL_BINDING}
        if local_binding_uses != {read.binding}:
            error("binding_read_inputs", read.operation,
                  "a local-read operation must consume exactly its declared binding token")
        if operation.callee is not None or operation.call_arguments:
            error("binding_read_call", read.operation,
                  "a local-read operation cannot be an ordinary call")
        if operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE:
            invocation_values = [values[uses[use_id][1].value]
                                 for use_id in operation.invoke_arguments
                                 if use_id in uses]
            if read.binding not in operation.invoke_arguments:
                error("binding_read_inputs", read.operation,
                      "a local-read invoke must pass its local-binding token")
            if any(not isinstance(value, (LocalBindingValue, StateVersionValue))
                   for value in invocation_values):
                error("binding_read_call", read.operation,
                      "a local-read invoke may carry its token and world, not Python call arguments")
        if read.normal_result is not None:
            result = values.get(read.normal_result)
            if not isinstance(result, ReferenceValue):
                error("binding_read_result", read.operation,
                      "normal local-read result must be a ReferenceValue")
            elif (isinstance(result.origin, OperationResult)
                  and result.origin.operation == operation.id):
                if operation.terminator is not None:
                    error("binding_read_result", read.operation,
                          "an operation-result local read cannot also terminate control")
                if read.normal_result not in operation.results:
                    error("binding_read_result", read.operation,
                          "ordinary local-read result must be produced by its operation")
                if (result.targets is not None or result.referent_identity is not None
                        or result.selector.kind is not FootprintKind.UNKNOWN):
                    error("binding_read_precision", read.operation,
                          "new local-read results cannot assert unverified reference precision")
            elif operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE:
                if read.binding not in operation.invoke_arguments:
                    error("binding_read_inputs", read.operation,
                          "invoke local read must pass its binding token as an invocation input")
                normal_edge = next((edge for edge in operation.terminator.successors
                                    if isinstance(edge, CompletionSuccessor)
                                    and edge.kind.value == "NORMAL"), None)
                target = blocks.get(normal_edge.block) if normal_edge is not None else None
                if target is None or read.normal_result not in target.arguments:
                    error("binding_read_result", read.operation,
                          "invoke read result must be a normal-completion block argument")
                else:
                    target_index = target.arguments.index(read.normal_result)
                    actual = normal_edge.arguments[target_index]
                    if not isinstance(actual, CompletionResult):
                        error("binding_read_result", read.operation,
                              "normal read result must come from its completion result")
                    else:
                        signature = next((item for item in operation.completions
                                          if item.kind.value == "NORMAL"), None)
                        if (signature is None or actual.index >= len(signature.types)
                                or signature.types[actual.index] != ValueType(ValueKind.REFERENCE)):
                            error("binding_read_result_type", read.operation,
                                  "normal completion must produce the local-read reference")
                    if (result.targets is not None or result.referent_identity is not None
                            or result.selector.kind is not FootprintKind.UNKNOWN):
                        error("binding_read_precision", read.operation,
                              "completion local-read results cannot assert unverified reference precision")
            else:
                # Reusing a value is allowed only for an unambiguous direct
                # BOUND definition; merged payloads require a result produced
                # on the read's normal path.
                definition = definitions.get(token.id)
                payload_pair = uses.get(definition.payload) if definition is not None and definition.payload else None
                if (definition is None or definition.state is not BindingState.BOUND
                        or payload_pair is None or payload_pair[1].value != read.normal_result):
                    error("binding_read_result", read.operation,
                          "reused read result must be the unique direct bound payload")
                if operation.terminator is not None:
                    error("binding_read_operation", read.operation,
                          "local reads must be ordinary operations or INVOKE terminators")
        elif operation.terminator is None or operation.terminator.kind is not TerminatorKind.RAISE:
            error("binding_read_raise", read.operation,
                  "a read without a normal result must be a RAISE terminator")
        else:
            if operation.terminator.kind is TerminatorKind.INVOKE:
                error("binding_read_raise", read.operation,
                      "an INVOKE read has a normal completion result")
            exception_values = [
                values[uses[use_id][1].value]
                for use_id in operation.terminator.values if use_id in uses
                and isinstance(values.get(uses[use_id][1].value), ReferenceValue)
            ]
            if (len(exception_values) != 1 or not _normal_completion_reference_for_read(
                    graph, exception_values[0], operation, blocks, operations, operation_block)):
                error("binding_read_exception", read.operation,
                      "unbound local must raise one exception reference from a typed producer or NORMAL completion")
            state_values = [
                values[uses[use_id][1].value]
                for use_id in operation.terminator.values if use_id in uses
                and isinstance(values.get(uses[use_id][1].value), StateVersionValue)
            ]
            if not state_values:
                error("binding_read_world", read.operation,
                      "unbound-local exception must preserve an explicit world state")

    # A monotone two-bit fixed point derives possible bound/unbound states at
    # merge blocks, including loop headers and backedges. UNKNOWN means both.
    facts = _compute_binding_facts(token_values, definitions, incoming_binding_values)

    for identity, value in token_values.items():
        if not facts.get(identity):
            error("binding_state_unresolved", identity,
                  "binding state cannot be derived from a definition or incoming edge")

    # Validate read routes after the fixed point so a merge cannot claim a
    # normal path while every incoming local is unbound.
    for read in graph.binding_reads:
        operation = operations.get(read.operation)
        pair = uses.get(read.binding)
        token = values.get(pair[1].value) if pair is not None else None
        if operation is None or not isinstance(token, LocalBindingValue):
            continue
        states = facts.get(token.id, frozenset())
        can_be_bound = BindingState.BOUND in states
        can_be_unbound = BindingState.UNBOUND in states
        if not states:
            continue
        if read.normal_result is None:
            if can_be_bound:
                error("binding_read_missing_normal", read.operation,
                      "a possibly bound local read cannot discard its normal result")
            term = operation.terminator
            if term is None or term.kind is not TerminatorKind.RAISE:
                error("binding_read_unbound_exit", read.operation,
                      "definitely unbound read must terminate on its RAISE path")
        else:
            if can_be_unbound and (operation.terminator is None
                                   or operation.terminator.kind is not TerminatorKind.INVOKE):
                error("binding_read_missing_raise", read.operation,
                      "a local read that may be unbound requires NORMAL and RAISE completion paths")
            is_invoke = (operation.terminator is not None
                         and operation.terminator.kind is TerminatorKind.INVOKE)
            if is_invoke:
                if operation.effects_complete:
                    error("binding_read_effects", read.operation,
                          "an invoke local read must preserve its unproved frame/exception effects")
                signatures = {signature.kind: signature for signature in operation.completions}
                region_id = block_region.get(operation_block.get(operation.id))
                region = regions.get(region_id)
                entry = blocks.get(region.entry) if region is not None else None
                state_locations = set()
                if entry is not None:
                    state_locations = {
                        values[value_id].location for value_id in entry.arguments
                        if isinstance(values.get(value_id), StateVersionValue)
                    }
                if not state_locations:
                    error("binding_read_world", read.operation,
                          "invoke local reads require an explicit world state domain")
                for kind in (ExitKind.NORMAL, ExitKind.RAISE):
                    signature = signatures.get(kind)
                    if signature is None:
                        error("binding_read_completion", read.operation,
                              "invoke local read needs both completion signatures")
                        continue
                    refs = [item for item in signature.types
                            if item == ValueType(ValueKind.REFERENCE)]
                    states_out = [item.location for item in signature.types
                                  if item.kind is ValueKind.STATE]
                    if (len(refs) != 1 or set(states_out) != state_locations
                            or len(states_out) != len(state_locations)
                            or len(signature.types) != 1 + len(state_locations)):
                        error("binding_read_completion", read.operation,
                              "each read completion must carry one reference and every current world state")

    # A frame protocol may consume a binding token as a lifetime dependency.
    # The exact transition meaning is checked by StructuredBodyModel/source
    # replay; the core only admits its deliberately incomplete, coarse-world
    # operation shape here.
    def is_coarse_frame_consumer(operation) -> bool:
        if (operation.terminator is not None or operation.callee is not None
                or operation.call_arguments or operation.invoke_arguments
                or operation.completions or operation.effects_complete
                or set(operation.behaviors) != {Behavior.READ, Behavior.WRITE, Behavior.MEMORY}
                or len(operation.accesses) != 1):
            return False
        access = operation.accesses[0]
        if (access.mode is not AccessMode.READ_WRITE or access.full_overwrite
                or access.footprint.kind is FootprintKind.INTERVAL
                or access.reference is not None):
            return False
        if operation.results != (access.after,):
            return False
        state_inputs = [use for use in operation.uses
                        if isinstance(values.get(use.value), StateVersionValue)]
        if (len(state_inputs) != 1 or state_inputs[0].id != access.before
                or state_inputs[0].role is not UseRole.STATE_CONTENT):
            return False
        return all(use.role in (UseRole.LOCAL_BINDING, UseRole.REFERENCE,
                                UseRole.STATE_CONTENT)
                   for use in operation.uses)

    # Every local-binding input must have one typed consumer: definition update,
    # binding read, same-slot CFG successor edge, or the coarse frame-lifetime
    # operation shape above.
    authorized: set[object] = set()
    for definition in graph.binding_definitions:
        if definition.previous is not None:
            authorized.add(definition.previous)
    for read in graph.binding_reads:
        authorized.add(read.binding)
    for region in graph.regions:
        for block in region.blocks:
            if not block.operations:
                continue
            operation = operations.get(block.operations[-1])
            if operation is None or operation.terminator is None:
                continue
            for edge in operation.terminator.successors:
                for actual in edge.arguments:
                    if isinstance(actual, UseID):
                        pair = uses.get(actual)
                        if pair is not None and pair[1].role is UseRole.LOCAL_BINDING:
                            authorized.add(actual)
    for operation in graph.operations:
        for use in operation.uses:
            if (use.role is UseRole.LOCAL_BINDING and use.id not in authorized
                    and not is_coarse_frame_consumer(operation)):
                error("binding_use_unaccounted", use.id,
                      "local-binding uses must belong to a definition, read, CFG edge, or coarse frame-lifetime operation")

    # Calls expose Python values and function state, never local-binding tokens.
    reads_for_call_check = {read.operation: read for read in graph.binding_reads}
    for operation in graph.operations:
        if operation.callee is not None:
            callee = regions.get(operation.callee)
            entry = blocks.get(callee.entry) if callee is not None else None
            if entry is not None and any(isinstance(values.get(value), LocalBindingValue)
                                         for value in entry.arguments):
                error("binding_call_formal", operation.id,
                      "ordinary call interfaces cannot expose local-binding tokens")
        actual_uses = set(operation.call_arguments) | set(operation.invoke_arguments)
        local_actual_uses = {
            use_id for use_id in actual_uses if use_id in uses
            and isinstance(values.get(uses[use_id][1].value), LocalBindingValue)
        }
        read = reads_for_call_check.get(operation.id)
        permitted_local_read = ({read.binding}
                                if read is not None
                                and operation.terminator is not None
                                and operation.terminator.kind is TerminatorKind.INVOKE
                                else set())
        if local_actual_uses - permitted_local_read:
            error("binding_call_actual", operation.id,
                  "ordinary Python call arguments cannot carry local-binding tokens")

    return tuple(issues)


__all__ = ["BindingValidationIssue", "derive_binding_facts", "validate_bindings"]
