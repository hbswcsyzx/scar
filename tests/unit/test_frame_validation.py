"""Manual core counterexamples; these tests are not automatic lowering acceptance."""
from copy import deepcopy
from dataclasses import dataclass, replace

import pytest

from scar.ir.frontend_v2 import build_semantic_files
from scar.ir.program.frame_validation import require_valid_frame_model, validate_frame_model
from scar.ir.program.frames import FrameBind, FrameDiscard, FrameEnter, FrameExit, FrameFormal, FrameModel
from scar.ir.program.functions import BodyEntryInterface, FormalPort
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, ExitKind, ExitPort, Footprint, FootprintKind, Operation,
    OperationResult, ProgramGraph, ReferenceValue, Region, StateAccess, StateLocation,
    StateVersionValue, Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.validation import require_valid
from scar.ir.v2.semantic import OperationKind


TEXT = """\
def sample(a, /, b=object(), *args, c, **kwargs):
    local = a
    a
    return local

def other(z):
    return z
"""


@dataclass
class Fixture:
    graph: ProgramGraph
    model: FrameModel
    interface: BodyEntryInterface
    semantic: object

    def issues(self):
        return validate_frame_model(self.model, self.graph, interface=self.interface, semantic=self.semantic)

    def codes(self):
        return {issue.code for issue in self.issues()}

    def valid(self):
        assert not self.issues(), self.issues()
        require_valid_frame_model(self.model, self.graph, interface=self.interface, semantic=self.semantic)

    def operation(self, name):
        return next(op for op in self.graph.operations if op.id == OperationID(name))

    def set_operation(self, operation):
        self.graph = replace(self.graph, operations=tuple(operation if op.id == operation.id else op
                                                         for op in self.graph.operations))

    def set_transition(self, transition):
        self.model = replace(self.model, transitions=tuple(transition if item.operation == transition.operation else item
                                                         for item in self.model.transitions))


@pytest.fixture
def fixture(tmp_path):
    path = tmp_path / "sample.py"
    path.write_text(TEXT)
    semantic = build_semantic_files((path,), tmp_path).graph
    definition = next(d for d in semantic.definitions.values()
                      if d.kind is OperationKind.FUNCTION and d.label == "sample")
    source = next(a.reference for a in semantic.source_atoms.values()
                  if a.kind == "FunctionDef" and a.reference.start_line == 1)
    references = {line: next(a.reference for a in semantic.source_atoms.values()
                            if a.reference.start_line == line and a.kind == kind)
                  for line, kind in ((2, "Assign"), (3, "Expr"), (4, "Return"))}
    slots = {s.name: s.slot_id for s in semantic.slots.values() if s.owner == definition.id}
    region_id, entry_id, location = RegionID("body"), BlockID("entry"), LocationID("world")
    names = ("a", "b", "args", "c", "kwargs")
    values = [ReferenceValue(ValueID(name), region_id, BlockArgument(entry_id, index))
              for index, name in enumerate(names)]
    world = StateVersionValue(ValueID("initial"), region_id, BlockArgument(entry_id, len(names)), location)
    values.append(world)
    operations, transitions = [], []
    current = world.id

    def transition(name, bindings, source, make):
        nonlocal current
        identity = OperationID(name)
        refs = tuple(Use(UseID(name + "." + label), ValueID(value), UseRole.REFERENCE)
                     for label, value in bindings)
        before = Use(UseID(name + ".state"), current, UseRole.STATE_CONTENT)
        after = StateVersionValue(ValueID(name + ".after"), region_id, OperationResult(identity, 0), location)
        operation = Operation(identity, "arbitrary human label", (Behavior.MEMORY, Behavior.READ, Behavior.WRITE),
                              refs + (before,), (after.id,),
                              (StateAccess(location, before.id, AccessMode.READ_WRITE, after.id),))
        operations.append(operation); values.append(after)
        transitions.append(make(operation, refs, source))
        current = after.id

    transition("enter", tuple((name, name) for name in names), source,
               lambda op, refs, src: FrameEnter(op.id, src, tuple(FrameFormal(slots[name], use.id)
                                                                 for name, use in zip(names, refs))))
    transition("bind", (("assigned", "a"),), references[2],
               lambda op, refs, src: FrameBind(op.id, src, slots["local"], refs[0].id))
    transition("discard", (("reference", "a"),), references[3],
               lambda op, refs, src: FrameDiscard(op.id, src, refs[0].id))
    transition("exit", (("payload", "a"),), references[4],
               lambda op, refs, src: FrameExit(op.id, src, OperationID("return"), refs[0].id))
    uses = (Use(UseID("return.payload"), ValueID("a"), UseRole.REFERENCE),
            Use(UseID("return.state"), current, UseRole.STATE_CONTENT))
    operations.append(Operation(OperationID("return"), "not an EXIT label", (Behavior.CONTROL,), uses,
                                terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                                                      values=tuple(use.id for use in uses))))
    block = Block(entry_id, tuple(ValueID(name) for name in names) + (world.id,), tuple(op.id for op in operations))
    region = Region(region_id, "sample", entry_id, (block,),
                    (ExitPort("normal", ExitKind.NORMAL, (ValueType(ValueKind.REFERENCE),
                                                         ValueType(ValueKind.STATE, location=location))),))
    graph = ProgramGraph(region_id, (region,), tuple(operations), tuple(values), (StateLocation(location, "opaque world"),))
    interface = BodyEntryInterface(definition.id, region_id, tuple(FormalPort(slots[name], ValueID(name)) for name in names), world.id)
    result = Fixture(graph, FrameModel(definition.id, region_id, source, tuple(transitions)), interface, semantic)
    result.valid()
    return result


def reorder_chain(fixture, names):
    """Keep core SSA valid while changing where the frame actions execute."""
    current = fixture.interface.world
    for name in names:
        op = fixture.operation(name)
        before = op.accesses[0].before
        fixture.set_operation(replace(op, uses=tuple(replace(use, value=current) if use.id == before else use for use in op.uses)))
        current = op.accesses[0].after
    done = fixture.operation("return")
    fixture.set_operation(replace(done, uses=tuple(replace(use, value=current) if use.role is UseRole.STATE_CONTENT else use
                                                 for use in done.uses)))
    region, = fixture.graph.regions
    block, = region.blocks
    block = replace(block, operations=tuple(OperationID(name) for name in names) + (done.id,))
    fixture.graph = replace(fixture.graph, regions=(replace(region, blocks=(block,)),))
    require_valid(fixture.graph)


def with_invoke(fixture):
    """Both completion paths receive independently produced states/payloads."""
    region, = fixture.graph.regions
    entry, = region.blocks
    world = next(v for v in fixture.graph.values if v.id == fixture.interface.world).location
    ref_type, state_type = ValueType(ValueKind.REFERENCE), ValueType(ValueKind.STATE, location=world)
    values = [v for v in fixture.graph.values if v.id != ValueID("exit.after")]
    operations = [op for op in fixture.graph.operations if op.id not in (OperationID("exit"), OperationID("return"))]
    uses = (Use(UseID("invoke.callee"), ValueID("b"), UseRole.REFERENCE),
            Use(UseID("invoke.state"), ValueID("discard.after"), UseRole.STATE_CONTENT))
    edges = tuple(CompletionSuccessor(kind, BlockID(name), (CompletionResult(0), CompletionResult(1)))
                  for kind, name in ((ExitKind.NORMAL, "normal"), (ExitKind.RAISE, "failure")))
    operations.append(Operation(OperationID("invoke"), "call", (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), uses,
                                terminator=Terminator(TerminatorKind.INVOKE, edges),
                                completions=tuple(CompletionSignature(kind, (ref_type, state_type)) for kind in ExitKind),
                                invoke_arguments=tuple(use.id for use in uses)))
    blocks = [replace(entry, operations=tuple(op.id for op in operations))]
    transitions = list(fixture.model.transitions[:-1])
    for name, kind in (("normal", ExitKind.NORMAL), ("failure", ExitKind.RAISE)):
        block_id = BlockID(name)
        payload = ReferenceValue(ValueID(name + ".payload"), region.id, BlockArgument(block_id, 0))
        state = StateVersionValue(ValueID(name + ".state"), region.id, BlockArgument(block_id, 1), world)
        exit_id, done_id = OperationID(name + ".exit"), OperationID(name + ".done")
        after = StateVersionValue(ValueID(name + ".after"), region.id, OperationResult(exit_id, 0), world)
        exit_uses = (Use(UseID(name + ".held"), payload.id, UseRole.REFERENCE),
                     Use(UseID(name + ".before"), state.id, UseRole.STATE_CONTENT))
        exit_op = Operation(exit_id, "exit", (Behavior.READ, Behavior.WRITE, Behavior.MEMORY), exit_uses, (after.id,),
                            (StateAccess(world, exit_uses[1].id, AccessMode.READ_WRITE, after.id),))
        done_uses = (Use(UseID(name + ".result"), payload.id, UseRole.REFERENCE),
                     Use(UseID(name + ".out"), after.id, UseRole.STATE_CONTENT))
        done = Operation(done_id, "done", (Behavior.CONTROL,), done_uses,
                         terminator=Terminator(TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE,
                                               exit=kind.value.lower(), values=tuple(use.id for use in done_uses)))
        values.extend((payload, state, after)); operations.extend((exit_op, done))
        blocks.append(Block(block_id, (payload.id, state.id), (exit_id, done_id)))
        transitions.append(FrameExit(exit_id, fixture.model.transitions[-1].source, done_id, exit_uses[0].id))
    region = replace(region, blocks=tuple(blocks), exits=tuple(ExitPort(kind.value.lower(), kind, (ref_type, state_type)) for kind in ExitKind))
    fixture.graph = replace(fixture.graph, regions=(region,), operations=tuple(operations), values=tuple(values))
    fixture.model = replace(fixture.model, transitions=tuple(transitions))
    fixture.valid()
    return fixture


def test_real_parsed_slots_and_all_five_formals_match_manual_core(fixture):
    assert len(fixture.interface.parameters) == 5
    assert FrameModel.from_dict(fixture.model.to_dict()) == fixture.model
    fixture.valid()


def test_labels_never_select_rules_and_equal_referents_do_not_deduplicate_formals(fixture):
    fixture.graph = replace(fixture.graph,
        operations=tuple(replace(op, label="ENTER") for op in fixture.graph.operations),
        values=tuple(replace(value, referent_identity="shared-object") if isinstance(value, ReferenceValue) else value
                     for value in fixture.graph.values))
    fixture.valid()
    assert len(fixture.model.transitions[0].formals) == 5


@pytest.mark.parametrize("kind", ["normal", "raise"])
def test_exit_kind_is_taken_from_core_and_payload_identity_is_unchanged(fixture, kind):
    with_invoke(fixture)
    transition = next(t for t in fixture.model.transitions if isinstance(t, FrameExit)
                      and t.completion == OperationID(("normal" if kind == "normal" else "failure") + ".done"))
    assert not hasattr(transition, "pending_kind")
    fixture.valid()


@pytest.mark.parametrize("name", ["bind", "discard", "exit"])
def test_missing_transition_cannot_hide_an_existing_core_action(fixture, name):
    fixture.model = replace(fixture.model, transitions=tuple(t for t in fixture.model.transitions if t.operation != OperationID(name)))
    assert "frame_operation_coverage" in fixture.codes()
    if name == "exit":
        assert "frame_exit_coverage" in fixture.codes()


def test_missing_exception_exit_cannot_bypass_unwind(fixture):
    with_invoke(fixture)
    fixture.model = replace(fixture.model, transitions=tuple(t for t in fixture.model.transitions
                                                           if t.operation != OperationID("failure.exit")))
    assert "frame_exit_coverage" in fixture.codes()


def test_unused_formal_is_still_required_even_when_core_has_the_use(fixture):
    enter = fixture.model.transitions[0]
    fixture.set_transition(replace(enter, formals=enter.formals[:-1]))
    assert {"frame_enter_formals", "frame_use_coverage"} <= fixture.codes()


def test_formal_slot_cannot_be_swapped_to_another_input_reference(fixture):
    enter = fixture.model.transitions[0]
    a, b, *others = enter.formals
    fixture.set_transition(replace(enter, formals=(replace(a, use=b.use), replace(b, use=a.use), *others)))
    assert "frame_formal_use" in fixture.codes()


@pytest.mark.parametrize("which", ["formal", "local"])
def test_slot_from_another_function_cannot_be_claimed(fixture, which):
    foreign = next(s.slot_id for s in fixture.semantic.slots.values() if s.name == "z")
    if which == "formal":
        enter = fixture.model.transitions[0]
        fixture.set_transition(replace(enter, formals=(replace(enter.formals[0], slot=foreign), *enter.formals[1:])))
    else:
        fixture.set_transition(replace(fixture.model.transitions[1], slot=foreign))
    assert "frame_slot" in fixture.codes()


def test_return_cannot_replace_held_payload_with_an_equal_typed_parameter(fixture):
    done = fixture.operation("return")
    fixture.set_operation(replace(done, uses=(replace(done.uses[0], value=ValueID("b")), done.uses[1])))
    require_valid(fixture.graph)
    assert "frame_payload" in fixture.codes()


def test_unwind_cannot_replace_exception_reference_with_normal_payload(fixture):
    with_invoke(fixture)
    done = fixture.operation("failure.done")
    fixture.set_operation(replace(done, uses=(replace(done.uses[0], value=ValueID("a")), done.uses[1])))
    require_valid(fixture.graph)
    assert "frame_payload" in fixture.codes()


@pytest.mark.parametrize("which", ["return", "failure"])
def test_exit_cannot_return_pre_cleanup_world(fixture, which):
    if which == "failure":
        with_invoke(fixture)
    done = fixture.operation("return" if which == "return" else "failure.done")
    before = ValueID("discard.after" if which == "return" else "failure.state")
    fixture.set_operation(replace(done, uses=(done.uses[0], replace(done.uses[1], value=before))))
    assert "core.stale_state" in fixture.codes()


@pytest.mark.parametrize("case", ["complete", "write", "overwrite", "interval", "reference_selector", "behavior"])
def test_frame_effect_contract_cannot_be_strengthened_or_narrowed(fixture, case):
    op = fixture.operation("exit")
    access, = op.accesses
    if case == "complete":
        op = replace(op, effects_complete=True)
    elif case == "write":
        op = replace(op, accesses=(replace(access, mode=AccessMode.WRITE),))
    elif case == "overwrite":
        access = replace(access, mode=AccessMode.WRITE, full_overwrite=True, footprint=Footprint(FootprintKind.WHOLE))
        op = replace(op, accesses=(access,), uses=(op.uses[0], replace(op.uses[1], role=UseRole.STATE_ORDER)))
    elif case == "interval":
        op = replace(op, accesses=(replace(access, footprint=Footprint(FootprintKind.INTERVAL, 0, 1)),))
    elif case == "reference_selector":
        op = replace(op, accesses=(replace(access, reference=op.uses[0].id),))
    else:
        op = replace(op, behaviors=(Behavior.READ, Behavior.WRITE))
    fixture.set_operation(op)
    require_valid(fixture.graph)
    assert {"frame_effects", "frame_access", "frame_behavior"} & fixture.codes()


def test_frame_cannot_produce_an_opaque_replacement_payload(fixture):
    op = fixture.operation("exit")
    extra = ReferenceValue(ValueID("replacement"), fixture.graph.root, OperationResult(op.id, 1))
    fixture.set_operation(replace(op, results=(*op.results, extra.id)))
    fixture.graph = replace(fixture.graph, values=(*fixture.graph.values, extra))
    require_valid(fixture.graph)
    assert "frame_results" in fixture.codes()


def test_enter_must_precede_bind_even_if_core_state_order_is_valid(fixture):
    reorder_chain(fixture, ("bind", "enter", "discard", "exit"))
    assert {"frame_enter_position", "frame_enter_world"} <= fixture.codes()


def test_exit_must_be_last_effect_and_completion_must_use_its_post_world(fixture):
    reorder_chain(fixture, ("enter", "bind", "exit", "discard"))
    assert {"frame_exit_position", "frame_post_world"} <= fixture.codes()


def test_exit_cannot_name_an_invoke_or_another_paths_completion(fixture):
    with_invoke(fixture)
    normal = next(t for t in fixture.model.transitions if t.operation == OperationID("normal.exit"))
    fixture.set_transition(replace(normal, completion=OperationID("invoke")))
    assert {"frame_completion", "frame_exit_coverage"} <= fixture.codes()


def test_normal_and_raise_exits_cannot_swap_completion_operations(fixture):
    with_invoke(fixture)
    normal, failure = fixture.model.transitions[-2:]
    fixture.model = replace(fixture.model, transitions=(*fixture.model.transitions[:-2],
        replace(normal, completion=failure.completion), replace(failure, completion=normal.completion)))
    require_valid(fixture.graph)
    assert {"frame_exit_position", "frame_payload", "frame_post_world"} <= fixture.codes()


def test_exit_cannot_use_another_operations_reference_use(fixture):
    fixture.set_transition(replace(fixture.model.transitions[-1], payload=UseID("bind.assigned")))
    assert {"frame_reference_use", "frame_payload", "frame_use_coverage"} <= fixture.codes()


@pytest.mark.parametrize("field", ["fingerprint", "path", "atom_id"])
def test_source_reference_must_match_its_parsed_atom(fixture, field):
    from scar.ir.v2.ids import SourceAtomID
    bind = fixture.model.transitions[1]
    changes = {"fingerprint": "sha256:" + "0" * 64, "path": "/elsewhere.py", "atom_id": SourceAtomID("missing")}
    fixture.set_transition(replace(bind, source=replace(bind.source, **{field: changes[field]})))
    assert "frame_source" in fixture.codes()


def test_valid_source_atom_from_another_body_cannot_anchor_transition(fixture):
    source = next(a.reference for a in fixture.semantic.source_atoms.values() if a.kind == "Return" and a.reference.start_line == 7)
    fixture.set_transition(replace(fixture.model.transitions[1], source=source))
    assert "frame_source_owner" in fixture.codes()


def test_default_evaluation_inside_function_span_is_not_body_execution(fixture):
    source = next(a.reference for a in fixture.semantic.source_atoms.values()
                  if a.kind == "Call" and a.reference.start_line == 1)
    fixture.set_transition(replace(fixture.model.transitions[1], source=source))
    assert "frame_source_context" in fixture.codes()


@pytest.mark.parametrize("transition_type", [FrameBind, FrameDiscard])
def test_bind_and_discard_cannot_use_function_declaration_source(fixture, transition_type):
    transition = next(item for item in fixture.model.transitions if type(item) is transition_type)
    fixture.set_transition(replace(transition, source=fixture.model.source))
    assert "frame_source_context" in fixture.codes()


def test_interface_cannot_silently_omit_a_formal(fixture):
    fixture.interface = replace(fixture.interface, parameters=fixture.interface.parameters[:-1])
    assert {"frame_entry_ports", "frame_formal_slots"} <= fixture.codes()


def test_model_definition_and_region_need_independent_context(fixture):
    fixture.model = replace(fixture.model, region=RegionID("another-body"))
    assert {"frame_interface", "frame_body"} <= fixture.codes()


def test_wrong_source_definition_is_not_repaired_by_matching_labels(fixture):
    other = next(d.id for d in fixture.semantic.definitions.values() if d.kind is OperationKind.FUNCTION and d.label == "other")
    fixture.model = replace(fixture.model, definition=other)
    assert "frame_interface" in fixture.codes()


def test_mutated_context_and_frozen_rule_records_are_rechecked(fixture):
    from scar.ir.v2.common import ProofStatus
    changed = deepcopy(fixture.model)
    object.__setattr__(changed.rules, "condition_status", ProofStatus.PROVEN)
    fixture.model = changed
    assert fixture.codes() == {"frame_schema"}
    with pytest.raises(ValueError, match="frame_schema"):
        require_valid_frame_model(fixture.model, fixture.graph, interface=fixture.interface, semantic=fixture.semantic)


def test_async_metadata_does_not_accept_truthy_integer(fixture):
    fixture.semantic.definitions[fixture.model.definition].metadata["async"] = 1
    assert "frame_definition" in fixture.codes()
