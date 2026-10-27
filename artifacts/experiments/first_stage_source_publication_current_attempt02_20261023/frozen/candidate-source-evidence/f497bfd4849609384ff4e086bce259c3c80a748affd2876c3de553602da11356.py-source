"""Cross-check the finite frame profile against its core and parsed context.

Only this source profile requires all ordinary body operations to be typed
frame transitions; general ProgramGraph validation is unchanged. Checking a
correspondence does not prove NO_FRAME_INTERPOSITION or replay source files.
"""
from __future__ import annotations

from scar.ir.program.frames import FrameBind, FrameDiscard, FrameEnter, FrameExit, FrameModel
from scar.ir.program.functions import BodyEntryInterface
from scar.ir.program.model import (
    AccessMode, Behavior, FootprintKind, ProgramGraph, ReferenceValue,
    StateVersionValue, TerminatorKind, UseRole, ValueKind,
)
from scar.ir.program.validation import ValidationIssue, validate
from scar.ir.v2._validation import record_errors
from scar.ir.v2.semantic import OperationDefinition, OperationKind, SemanticGraph, SourceAtom, ValueSlot


def validate_frame_model(model: FrameModel, graph: ProgramGraph, *,
                         interface: BodyEntryInterface,
                         semantic: SemanticGraph) -> tuple[ValidationIssue, ...]:
    """Check declared frame links; full source replay remains the caller's gate.

    ``interface`` and ``semantic`` must be the independently prepared context,
    not definitions copied out of this overlay to make its links agree.
    """
    issues = []

    def error(code, path, message):
        issues.append(ValidationIssue(code, str(path), message))

    for record, expected, name in ((model, FrameModel, "frame"),
                                   (interface, BodyEntryInterface, "interface")):
        for message in record_errors(record, expected, name):
            error("frame_schema", name, message)
    if type(semantic) is not SemanticGraph:
        error("frame_context", "semantic", "an independently parsed SemanticGraph is required")
    elif any(type(getattr(semantic, name)) is not dict for name in ("definitions", "source_atoms", "slots")):
        error("frame_context", "semantic", "parsed source registries must be dictionaries")
    if issues:
        return tuple(issues)
    core_issues = validate(graph)
    if core_issues:
        return tuple(ValidationIssue("core." + issue.code, issue.path, issue.message)
                     for issue in core_issues)

    operations = {op.id: op for op in graph.operations}
    values = {value.id: value for value in graph.values}
    regions = {region.id: region for region in graph.regions}
    region = regions.get(model.region)
    if model.definition != interface.definition or model.region != interface.region:
        error("frame_interface", model.region, "frame and body interface definition/region must agree")
    if region is None or model.region != graph.root:
        error("frame_body", model.region, "the frame profile describes the selected root body")
    definition = semantic.definitions.get(model.definition)
    if definition is not None:
        for message in record_errors(definition, OperationDefinition, "definition"):
            error("frame_context", model.definition, message)
        if issues:
            return tuple(issues)
    if (definition is None or definition.id != model.definition
            or definition.kind not in (OperationKind.FUNCTION, OperationKind.METHOD)
            or ("async" in definition.metadata and type(definition.metadata["async"]) is not bool)
            or definition.metadata.get("async") is True):
        error("frame_definition", model.definition, "frame needs its parsed synchronous function definition")

    atom_owners = {}
    for item in semantic.definitions.values():
        if isinstance(item, OperationDefinition):
            for atom_id in item.source_atoms:
                atom_owners.setdefault(atom_id, []).append(item.id)

    def in_body_context(owner_id):
        seen = set()
        while owner_id is not None and owner_id not in seen:
            seen.add(owner_id)
            owner = semantic.definitions.get(owner_id)
            if not isinstance(owner, OperationDefinition):
                return False
            if owner.id == model.definition:
                return True
            if owner.kind in (OperationKind.FUNCTION, OperationKind.METHOD):
                return False
            owner_id = owner.parent_id
        return False

    def source(reference):
        atom = semantic.source_atoms.get(reference.atom_id)
        if atom is not None:
            messages = record_errors(atom, SourceAtom, "source_atom")
            if messages:
                for message in messages:
                    error("frame_context", reference.atom_id, message)
                return
        if atom is None or atom.id != reference.atom_id or atom.reference != reference:
            error("frame_source", reference.atom_id, "source differs from the parsed source atom")
        if not any(in_body_context(owner) for owner in atom_owners.get(reference.atom_id, ())):
            error("frame_source_context", reference.atom_id,
                  "source must execute in this function, not its declaration or a nested function")
        owner = model.source
        if (reference.path != owner.path
                or (reference.start_line, reference.start_column) < (owner.start_line, owner.start_column)
                or reference.end_line > owner.end_line
                or (reference.end_line == owner.end_line and owner.end_column is not None
                    and (reference.end_column is None or reference.end_column > owner.end_column))):
            error("frame_source_owner", reference.atom_id, "source must lie inside this function's source span")

    source(model.source)
    if definition is not None and (
            model.source.atom_id not in definition.source_atoms
            or definition.source_file != model.source.path
            or definition.source_start != model.source.start_line
            or definition.source_end != model.source.end_line):
        error("frame_definition_source", model.definition, "frame source differs from its parsed definition")
    if issues:
        return tuple(issues)

    blocks = {block.id: block for block in region.blocks}
    entry = blocks[region.entry]
    owner_blocks = {op: block for block in region.blocks for op in block.operations}
    body_operations = {op: operations[op] for op in owner_blocks}
    formal_values = tuple(formal.value for formal in interface.parameters)
    if entry.arguments != formal_values + (interface.world,):
        error("frame_entry_ports", region.entry, "entry must carry all formals, then its sole world state")
    if any(not isinstance(values.get(value), ReferenceValue) for value in formal_values):
        error("frame_formal_type", region.entry, "every bound Python formal must be a reference")
    world = values.get(interface.world)
    if not isinstance(world, StateVersionValue):
        error("frame_world", interface.world, "body world must be an entry state parameter")
        return tuple(issues)
    for port in region.exits:
        if (len(port.types) != 2 or port.types[0].kind is not ValueKind.REFERENCE
                or port.types[1].kind is not ValueKind.STATE or port.types[1].location != world.location):
            error("frame_exit_ports", region.id, "frame exits require one reference payload and the world state")

    def slot(slot_id, *, formal=False):
        record = semantic.slots.get(slot_id)
        if record is not None:
            messages = record_errors(record, ValueSlot, "slot")
            if messages:
                for message in messages:
                    error("frame_context", slot_id, message)
                return
        if (record is None or record.slot_id != slot_id or record.owner != model.definition
                or record.direction not in (("input",) if formal else ("input", "binding"))):
            error("frame_slot", slot_id, "slot must be a parsed ordinary local/formal of this function")

    for formal in interface.parameters:
        slot(formal.slot, formal=True)
    if set(definition.input_slots) != {formal.slot for formal in interface.parameters}:
        error("frame_formal_slots", model.definition, "interface must cover every parsed formal slot")
    if issues:
        return tuple(issues)

    ordinary = {op.id for op in body_operations.values() if op.terminator is None}
    declared = {transition.operation for transition in model.transitions}
    if ordinary != declared:
        error("frame_operation_coverage", model.region,
              "this finite frame profile needs exactly one transition for each ordinary body operation")
    completions = {op.id for op in body_operations.values() if op.terminator is not None
                   and op.terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE)}
    if completions != {item.completion for item in model.transitions if type(item) is FrameExit}:
        error("frame_exit_coverage", model.region, "every actual RETURN/RAISE needs exactly one frame EXIT")

    for transition in model.transitions:
        source(transition.source)
        if (type(transition) in (FrameBind, FrameDiscard)
                and transition.source.atom_id == model.source.atom_id):
            error("frame_source_context", transition.source.atom_id,
                  "BIND/DISCARD must use a body operation source, not the function declaration")
        op = body_operations.get(transition.operation)
        if op is None:
            error("frame_operation_owner", transition.operation, "transition operation must belong to this body")
            continue
        if (op.terminator is not None or op.callee is not None or op.call_arguments
                or op.completions or op.invoke_arguments):
            error("frame_operation_shape", op.id, "frame transitions are ordinary state operations without calls or completion edges")
        if set(op.behaviors) != {Behavior.READ, Behavior.WRITE, Behavior.MEMORY}:
            error("frame_behavior", op.id, "frame transitions require READ/WRITE/MEMORY behaviors")
        if op.effects_complete:
            error("frame_effects", op.id, "unknown finalizer/external effects cannot be certified complete")
        if len(op.accesses) != 1:
            error("frame_access", op.id, "frame transition needs one coarse world READ_WRITE access")
            continue
        access = op.accesses[0]
        if (access.location != world.location or access.mode is not AccessMode.READ_WRITE
                or access.full_overwrite or access.reference is not None
                or access.footprint.kind is FootprintKind.INTERVAL):
            error("frame_access", op.id, "frame access must preserve coarse world content dependence without a reference selector")
        if op.results != (access.after,):
            error("frame_results", op.id, "frame transition must produce only its new world state")
        uses = {use.id: use for use in op.uses}
        state_use = uses.get(access.before)
        if state_use is None or state_use.role is not UseRole.STATE_CONTENT:
            error("frame_state_use", op.id, "frame before-state must be a STATE_CONTENT use")

        if type(transition) is FrameEnter:
            references = tuple(formal.use for formal in transition.formals)
            if owner_blocks[op.id].id != region.entry or entry.operations[0] != op.id:
                error("frame_enter_position", op.id, "ENTER must be the first operation in the body entry")
            expected = {formal.slot: formal.value for formal in interface.parameters}
            if set(expected) != {formal.slot for formal in transition.formals}:
                error("frame_enter_formals", op.id, "ENTER must hold every formal slot exactly once")
            for formal in transition.formals:
                slot(formal.slot, formal=True)
                use = uses.get(formal.use)
                if use is None or use.value != expected.get(formal.slot):
                    error("frame_formal_use", formal.use, "formal slot must use its own bound entry reference")
            if state_use is not None and state_use.value != interface.world:
                error("frame_enter_world", op.id, "ENTER consumes the interface's initial world")
        elif type(transition) is FrameBind:
            references = (transition.assigned,)
            slot(transition.slot)
        elif type(transition) is FrameDiscard:
            references = (transition.reference,)
        else:
            references = (transition.payload,)
            completion = body_operations.get(transition.completion)
            if (completion is None or completion.terminator is None
                    or completion.terminator.kind not in (TerminatorKind.RETURN, TerminatorKind.RAISE)):
                error("frame_completion", transition.completion, "EXIT must name a RETURN/RAISE of this body")
            else:
                block = owner_blocks[op.id]
                if (owner_blocks[completion.id].id != block.id
                        or block.operations[-2:] != (op.id, completion.id)):
                    error("frame_exit_position", op.id, "EXIT must immediately precede its completion in the same block")
                completion_uses = {use.id: use for use in completion.uses}
                ports = completion.terminator.values
                if len(ports) != 2:
                    error("frame_completion_ports", completion.id, "completion needs payload and post-world")
                else:
                    payload = uses.get(transition.payload)
                    if payload is None or completion_uses[ports[0]].value != payload.value:
                        error("frame_payload", completion.id, "completion must preserve the EXIT payload reference")
                    if completion_uses[ports[1]].value != access.after:
                        error("frame_post_world", completion.id, "completion must carry the EXIT post-world")

        for reference in references:
            use = uses.get(reference)
            if (use is None or use.role is not UseRole.REFERENCE
                    or not isinstance(values[use.value], ReferenceValue)):
                error("frame_reference_use", reference, "frame reference must be an owned REFERENCE use")
        if set(uses) != set(references) | {access.before}:
            error("frame_use_coverage", op.id, "transition must account for each reference and world use exactly")
    return tuple(issues)


def require_valid_frame_model(model: FrameModel, graph: ProgramGraph, *,
                              interface: BodyEntryInterface, semantic: SemanticGraph) -> None:
    issues = validate_frame_model(model, graph, interface=interface, semantic=semantic)
    if issues:
        raise ValueError("; ".join(f"{issue.code} at {issue.path}: {issue.message}" for issue in issues))


__all__ = ["validate_frame_model", "require_valid_frame_model"]
