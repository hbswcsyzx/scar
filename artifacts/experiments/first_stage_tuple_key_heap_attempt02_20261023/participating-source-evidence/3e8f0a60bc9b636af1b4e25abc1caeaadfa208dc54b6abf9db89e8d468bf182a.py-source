"""Declared resumable-body structure, without driver or runtime authority.

Logical successors retain cleanup activation. The core separately cuts value
availability at resume landings. Context attachment is local to one drive; it
does not identify a Python frame, a runtime generation, or an exclusive owner.
"""
from dataclasses import dataclass
from enum import Enum

from .control import ProtocolValueKind as P, ProtocolValueType
from .ids import ValueID
from .model import (
    AccessMode, Behavior, BlockArgument, DataValue, FootprintKind,
    LocalBindingValue, OperationResult, ProtocolValue, ReferenceValue,
    StateVersionValue, TerminatorKind,
)
from .resumption import (
    FrameContextAttach, FrameContextInitial, ResumableKind, ResumeInput,
    ResumeSlotKind, SavedInput, SavedRole, SuspendTerminator, SuspensionFlavor,
)


class ContextMode(str, Enum):
    DETACHED = "DETACHED"
    ATTACHED = "ATTACHED"


@dataclass(frozen=True, slots=True)
class DriveContext:
    mode: ContextMode
    caller: ValueID | None


@dataclass(frozen=True, slots=True)
class ResumptionFacts:
    contexts: dict
    roots: dict


def analyze_resumption(graph, *, operation_blocks, region_domains, incoming_edges):
    """Check declarations only, after the base CFG/state and cleanup checks."""
    issues = []

    def error(code, path, message):
        issues.append((code, str(path), message))

    bodies = {row.region: row for row in graph.resumable_bodies}
    initials = {row.operation: row for row in graph.frame_context_initials}
    attaches = {row.operation: row for row in graph.frame_context_attaches}
    detaches = {row.operation: row for row in graph.frame_context_detaches}
    actions = {**initials, **attaches, **detaches}
    operations = {op.id: op for op in graph.operations}
    values = {value.id: value for value in graph.values}
    regions = {region.id: region for region in graph.regions}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    owners = {block.id: region.id for region in graph.regions for block in region.blocks}
    private_kinds = {P.FRAME_CONTEXT, P.DRIVE_CALLER_CONTEXT}
    private = {value.id: value for value in graph.values
               if isinstance(value, ProtocolValue) and value.protocol in private_kinds}
    suspends = {op.id: op for op in graph.operations
                if isinstance(op.terminator, SuspendTerminator)}
    facts = ResumptionFacts({}, {})
    if not (bodies or actions or private or suspends):
        return issues, facts

    def protocol(identity, kind):
        value = values.get(identity)
        return isinstance(value, ProtocolValue) and value.protocol is kind

    for body in bodies.values():
        if body.region not in regions:
            error("resumption_region", body.region, "body region must exist")
            continue
        if body.context_location not in region_domains[body.region]:
            error("resumption_context_domain", body.region,
                  "body context is an entry-carried state domain")
        for row in graph.handled_context_domains:
            if row.region == body.region and row.location != body.context_location:
                error("resumption_context_domain", body.region,
                      "cleanup and body context must use the same domain")
        for value in private.values():
            if value.region == body.region and value.id in blocks[regions[body.region].entry].arguments:
                error("resumption_private_entry", value.id, "private context is not a normal entry port")
        for port in regions[body.region].exits:
            if any(isinstance(t, ProtocolValueType) and t.protocol in private_kinds for t in port.types):
                error("resumption_private_exit", body.region, "private context is not a region exit")
    for operation_id in (*actions, *suspends):
        if operation_id not in operations or owners.get(operation_blocks.get(operation_id)) not in bodies:
            error("resumption_owner", operation_id, "body action needs one declared owning body")
    for value in private.values():
        if value.region not in bodies:
            error("resumption_owner", value.id, "private context requires a declared body")
    if issues:
        return issues, facts

    # Exact intrinsic operands/results do not certify a real interpreter switch.
    allowed_private_uses = set()
    expected_producers = {}
    for operation_id, row in actions.items():
        op = operations[operation_id]
        body = bodies[owners[operation_blocks[operation_id]]]
        own = {use.id: use for use in op.uses}
        if isinstance(row, FrameContextInitial):
            valid = (not op.uses and op.results == (row.frame,) and not op.accesses
                     and set(op.behaviors) == {Behavior.CONTROL})
            output, output_kind = row.frame, P.FRAME_CONTEXT
        else:
            is_attach = isinstance(row, FrameContextAttach)
            operand = row.frame if is_attach else row.caller
            output = row.caller if is_attach else row.frame
            output_kind = P.DRIVE_CALLER_CONTEXT if is_attach else P.FRAME_CONTEXT
            input_kind = P.FRAME_CONTEXT if is_attach else P.DRIVE_CALLER_CONTEXT
            allowed_private_uses.add(operand)
            valid = (operand in own and protocol(own[operand].value, input_kind)
                     and set(op.behaviors) == {Behavior.CONTROL, Behavior.READ, Behavior.WRITE}
                     and len(op.accesses) == 1)
            if len(op.accesses) == 1:
                access = op.accesses[0]
                valid &= (access.location == body.context_location
                          and access.mode is AccessMode.READ_WRITE
                          and access.footprint.kind is FootprintKind.WHOLE
                          and not access.full_overwrite and access.reference is None
                          and set(own) == {operand, access.before}
                          and set(op.results) == {output, access.after}
                          and len(op.results) == 2)
        valid &= (op.effects_complete and op.callee is None and op.terminator is None
                  and not op.call_arguments and not op.invoke_arguments
                  and not op.completions and protocol(output, output_kind)
                  and output in op.results)
        if not valid:
            error("resumption_context_action", op.id,
                  "context intrinsic must have its exact private and current-context operands/results")
        expected_producers[output] = operation_id
    for value in private.values():
        if isinstance(value.origin, OperationResult) and expected_producers.get(value.id) != value.origin.operation:
            error("resumption_context_producer", value.id,
                  "private context only has its declared Initial/Attach/Detach producer")
    if issues:
        return issues, facts

    landings = {}
    for op in suspends.values():
        term = op.terminator
        body = bodies[owners[operation_blocks[op.id]]]
        own = {use.id: use for use in op.uses}
        domains = region_domains[body.region]
        if not isinstance(values[own[term.exported].value], ReferenceValue):
            error("resumption_export", op.id, "body export must be a Python reference")
        handed = [values[own[use].value] for use in term.handoff]
        if (any(not isinstance(value, StateVersionValue) for value in handed)
                or len(handed) != len(domains)
                or {value.location for value in handed if isinstance(value, StateVersionValue)} != domains):
            error("resumption_handoff", op.id, "handoff needs each current state domain exactly once")
        permitted = {
            ResumableKind.GENERATOR: {SuspensionFlavor.YIELD, SuspensionFlavor.DELEGATION},
            ResumableKind.GENERATOR_COROUTINE: {SuspensionFlavor.YIELD, SuspensionFlavor.DELEGATION},
            ResumableKind.COROUTINE: {SuspensionFlavor.AWAIT},
            ResumableKind.ASYNC_GENERATOR: {SuspensionFlavor.AWAIT, SuspensionFlavor.ASYNC_YIELD},
        }[body.kind]
        if term.flavor not in permitted:
            error("resumption_flavor", op.id, "suspension flavor differs from declared body family")
        frame_slot = None
        for index, saved in enumerate(term.saved):
            value = values[own[saved.use].value]
            correct = {
                SavedRole.VALUE: isinstance(value, (DataValue, ReferenceValue)),
                SavedRole.DELEGATE_REFERENCE: isinstance(value, ReferenceValue),
                SavedRole.LOCAL_BINDING: isinstance(value, LocalBindingValue),
                SavedRole.PENDING_COMPLETION: protocol(value.id, P.PENDING_COMPLETION),
                SavedRole.CLEANUP_CONTEXT: protocol(value.id, P.SAVED_HANDLED_CONTEXT),
                SavedRole.FRAME_CONTEXT: protocol(value.id, P.FRAME_CONTEXT),
            }[saved.role]
            if not correct:
                error("resumption_saved_role", saved.use, "saved role must match the exact value kind")
            if saved.role is SavedRole.FRAME_CONTEXT:
                frame_slot = index
                allowed_private_uses.add(saved.use)
        source_block = blocks[operation_blocks[op.id]]
        previous = source_block.operations[-2] if len(source_block.operations) >= 2 else None
        current_detach = detaches.get(previous)
        if (current_detach is None
                or own[term.saved[frame_slot].use].value != current_detach.frame):
            error("resumption_current_frame", op.id,
                  "suspend must save the exact frame fragment from its adjacent Detach")
        for case, edge in enumerate(term.successors):
            target = blocks[edge.block]
            state_slots = {slot.location for slot in edge.inputs if slot.kind is ResumeSlotKind.STATE}
            if state_slots != domains:
                error("resumption_state_inputs", op.id,
                      "every body ingress provides latest state for every domain")
            if edge.block == regions[body.region].entry or len(incoming_edges[edge.block]) != 1:
                error("resumption_landing", edge.block, "resume landing must be a private nonentry target")
            frame_formals = [formal for actual, formal in zip(edge.arguments, target.arguments)
                             if isinstance(actual, SavedInput) and actual.saved_slot == frame_slot]
            attach = attaches.get(target.operations[0])
            attach_op = operations[target.operations[0]]
            attach_use = (next((use for use in attach_op.uses if use.id == attach.frame), None)
                          if attach is not None else None)
            if (not frame_formals or attach_use is None
                    or attach_use.value not in frame_formals):
                error("resumption_landing_attach", edge.block,
                      "landing first attaches this exact saved frame fragment")
            landings[edge.block] = (op.id, case)

    for body in bodies.values():
        region = regions[body.region]
        entry = blocks[region.entry]
        initial_rows = [row for row in initials.values()
                        if owners[operation_blocks[row.operation]] == body.region]
        if (len(initial_rows) != 1 or entry.operations[0] not in initials
                or len(entry.operations) < 2 or entry.operations[1] not in attaches):
            error("resumption_initial", body.region, "body starts with exactly one Initial then Attach")
        else:
            initial = initials[entry.operations[0]]
            attach = attaches[entry.operations[1]]
            attach_op = operations[attach.operation]
            frame = next((use.value for use in attach_op.uses if use.id == attach.frame), None)
            if frame != initial.frame:
                error("resumption_initial", body.region, "initial Attach must use the Initial frame fragment")
        local_landings = {block for block in landings if owners[block] == body.region}
        facts.roots[body.region] = (region.entry, *sorted(local_landings, key=lambda b: b.wire))

        for block in region.blocks:
            detached_entry = block.id == region.entry or block.id in landings
            tokens = [value for value in block.arguments if protocol(value, P.DRIVE_CALLER_CONTEXT)]
            frame_args = [value for value in block.arguments if protocol(value, P.FRAME_CONTEXT)]
            if (detached_entry and tokens) or (not detached_entry and len(tokens) != 1):
                error("resumption_caller_parameter", block.id,
                      "only an Attached block carries exactly one current caller parameter")
            if (block.id not in landings and frame_args) or (block.id in landings and not frame_args):
                error("resumption_frame_parameter", block.id,
                      "private frame arguments only enter their exact resume landing")
            mode = ContextMode.DETACHED if detached_entry else ContextMode.ATTACHED
            caller = tokens[0] if len(tokens) == 1 else None
            facts.contexts[block.id] = DriveContext(mode, caller)
            for index, operation_id in enumerate(block.operations):
                op = operations[operation_id]
                own = {use.id: use for use in op.uses}
                if operation_id in initials:
                    if block.id != region.entry or index != 0 or mode is not ContextMode.DETACHED:
                        error("resumption_initial_position", operation_id, "Initial only starts body entry")
                    continue
                if operation_id in attaches:
                    allowed_position = ((block.id == region.entry and index == 1)
                                        or (block.id in landings and index == 0))
                    if mode is not ContextMode.DETACHED or not allowed_position:
                        error("resumption_attach_position", operation_id, "Attach only begins an actual body ingress")
                    caller = attaches[operation_id].caller
                    mode = ContextMode.ATTACHED
                    continue
                if operation_id in detaches:
                    row = detaches[operation_id]
                    if mode is not ContextMode.ATTACHED or own[row.caller].value != caller:
                        error("resumption_active_caller", operation_id, "Detach must restore this drive's active caller")
                    if (index != len(block.operations) - 2
                            or operations[block.operations[-1]].terminator.kind not in (
                                TerminatorKind.SUSPEND, TerminatorKind.RETURN, TerminatorKind.RAISE)):
                        error("resumption_detach_position", operation_id, "Detach immediately precedes handoff or termination")
                    mode, caller = ContextMode.DETACHED, None
                    continue
                term = op.terminator
                terminal = term is not None and term.kind in (
                    TerminatorKind.SUSPEND, TerminatorKind.RETURN, TerminatorKind.RAISE)
                if terminal:
                    if (mode is not ContextMode.DETACHED or index == 0
                            or block.operations[index - 1] not in detaches):
                        error("resumption_terminal_context", op.id, "handoff/termination requires its adjacent Detach")
                elif mode is not ContextMode.ATTACHED:
                    error("resumption_detached_work", op.id, "body user work needs Attached context")
                if term is not None and not isinstance(term, SuspendTerminator):
                    for edge in term.successors:
                        target = blocks[edge.block]
                        for actual, formal in zip(edge.arguments, target.arguments):
                            if protocol(formal, P.DRIVE_CALLER_CONTEXT):
                                use = own.get(actual)
                                if use is None or use.value != caller or mode is not ContextMode.ATTACHED:
                                    error("resumption_caller_forward", op.id,
                                          "ordinary edge forwards the exact current caller")
                                elif detached_entry and edge.block in landings:
                                    error("resumption_context_mode", op.id, "ordinary edge cannot enter a resume landing")
                                if use is not None:
                                    allowed_private_uses.add(use.id)

    for op in graph.operations:
        for use in op.uses:
            if use.value in private and (use.id not in allowed_private_uses
                    or use.id in (*op.call_arguments, *op.invoke_arguments)):
                error("resumption_private_escape", use.id,
                      "private context only uses its canonical switch, saved-frame or caller-edge operand")
    return issues, facts


__all__ = ["ContextMode", "DriveContext", "ResumptionFacts", "analyze_resumption"]
