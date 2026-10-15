"""Raw-source frame lowering and replay; positive graphs are never repaired here."""
from copy import deepcopy
from dataclasses import replace
from textwrap import dedent

import pytest

from scar.analysis.program_lowering import SourceProgram, lower_source, prepare_source
from scar.ir.program.frame_validation import require_valid_frame_model
from scar.ir.program.frames import (
    FrameBind, FrameDiscard, FrameEnter, FrameExit, FrameFinalizerErrors,
    FrameRelease, FrameTermination,
)
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.ids import UseID
from scar.ir.program.model import (
    AccessMode, BlockArgument, CompletionResult, ExitKind, LiteralOrigin,
    OperationResult, ReferenceValue, StateVersionValue, TerminatorKind,
)
from scar.ir.program.source import GapKind
from scar.ir.program.validation import require_valid
from scar.ir.v2.common import Completeness, ProofStatus


def lower(tmp_path, source, entry="f", **kwargs):
    path = tmp_path / "raw.py"
    path.write_text(dedent(source).lstrip(), encoding="utf-8")
    return lower_source(path, entry, profile=BodyLoweringProfile.BOUND_FRAME, **kwargs)


def tables(result):
    return ({op.id: op for op in result.graph.operations},
            {value.id: value for value in result.graph.values},
            {block.id: block for region in result.graph.regions for block in region.blocks})


def formals(result):
    return {result.semantic.slots[port.slot].name: port.value for port in result.interface.parameters}


def exits(result, kind=TerminatorKind.RETURN):
    ops, _, _ = tables(result)
    return [(item, ops[item.operation], ops[item.completion]) for item in result.frame.transitions
            if isinstance(item, FrameExit) and ops[item.completion].terminator.kind is kind]


def payload(operation):
    uses = {use.id: use.value for use in operation.uses}
    return uses[operation.terminator.values[0]]


def assert_supported(result):
    assert result.graph is not None, result.metadata.gaps
    assert result.profile is BodyLoweringProfile.BOUND_FRAME
    assert result.interface.profile is result.profile
    require_valid(result.graph)
    require_valid_frame_model(result.frame, result.graph, interface=result.interface, semantic=result.semantic)


def assert_replays(result):
    wire = result.to_dict()
    assert wire["schema_version"] == 2
    assert SourceProgram.from_dict(wire).to_dict() == wire


def test_return_parameter_has_original_payload_without_fake_exception_exit(tmp_path):
    result = lower(tmp_path, "def f(unused, x):\n    return x\n")
    assert_supported(result)
    _, frame_exit, returned = exits(result)[0]
    assert payload(returned) == formals(result)["x"]
    assert frame_exit.results == (frame_exit.accesses[0].after,)
    assert not exits(result, TerminatorKind.RAISE)
    assert_replays(result)


def test_all_five_formal_kinds_and_unused_parameters_enter_frame(tmp_path):
    result = lower(tmp_path, "def f(a, /, b=None, *args, c=None, **kwargs):\n    return a\n")
    assert_supported(result)
    enter, = [item for item in result.frame.transitions if isinstance(item, FrameEnter)]
    ops, _, _ = tables(result)
    held = {item.slot: next(use.value for use in ops[enter.operation].uses if use.id == item.use)
            for item in enter.formals}
    assert {result.semantic.slots[slot].name for slot in held} == {"a", "b", "args", "c", "kwargs"}
    assert held == {port.slot: port.value for port in result.interface.parameters}
    assert payload(exits(result)[0][2]) == formals(result)["a"]
    assert_replays(result)


@pytest.mark.parametrize("body,returned,bindings", [
    ("y = x\nreturn y", "x", 1),
    ("y = x\nx = replacement\nreturn y", "x", 2),
    ("x = x\nreturn x", "x", 1),
    ("y = x\ny = replacement\nreturn y", "replacement", 2),
])
def test_alias_rebinding_and_self_binding_keep_reference_source(tmp_path, body, returned, bindings):
    source = "def f(x, replacement):\n" + "".join("    " + line + "\n" for line in body.splitlines())
    result = lower(tmp_path, source)
    assert_supported(result)
    assert payload(exits(result)[0][2]) == formals(result)[returned]
    assert len([t for t in result.frame.transitions if isinstance(t, FrameBind)]) == bindings
    assert_replays(result)


def test_return_new_local_preserves_its_actual_call_result_not_a_formal(tmp_path):
    result = lower(tmp_path, "def f(make, x):\n    local = make(x)\n    return local\n")
    assert_supported(result)
    ops, values, blocks = tables(result)
    bind, = [item for item in result.frame.transitions if isinstance(item, FrameBind)]
    assigned = next(use.value for use in ops[bind.operation].uses if use.id == bind.assigned)
    assert payload(exits(result)[0][2]) == assigned
    assert assigned not in formals(result).values()
    origin = values[assigned].origin
    assert isinstance(origin, BlockArgument)
    incoming = [(op, edge) for op in ops.values() if op.terminator
                for edge in op.terminator.successors if edge.block == origin.block]
    assert len(incoming) == 1
    invoke, edge = incoming[0]
    assert invoke.terminator.kind is TerminatorKind.INVOKE
    assert edge.kind is ExitKind.NORMAL
    assert edge.arguments[origin.index] == CompletionResult(0)
    assert blocks[origin.block].arguments[origin.index] == assigned
    assert_replays(result)


def incoming_values(result, argument):
    ops, values, _ = tables(result)
    origin = values[argument].origin
    assert isinstance(origin, BlockArgument)
    incoming = []
    for op in ops.values():
        if not op.terminator:
            continue
        uses = {use.id: use.value for use in op.uses}
        for edge in op.terminator.successors:
            if edge.block == origin.block:
                actual = edge.arguments[origin.index]
                incoming.append((op, uses[actual] if isinstance(actual, UseID) else actual))
    return incoming


def test_branch_merge_returns_each_predecessors_reference_and_state(tmp_path):
    result = lower(tmp_path, """
        def f(flag, left, right):
            if flag:
                selected = left
            else:
                selected = right
            return selected
    """)
    assert_supported(result)
    returned = payload(exits(result)[0][2])
    incoming = incoming_values(result, returned)
    assert len(incoming) == 2
    assert {value for _, value in incoming} == {formals(result)["left"], formals(result)["right"]}
    assert all(op.terminator.kind is TerminatorKind.JUMP for op, _ in incoming)
    binds = [t for t in result.frame.transitions if isinstance(t, FrameBind)]
    assert len(binds) == 2 and binds[0].slot == binds[1].slot
    assert_replays(result)


def test_each_early_return_keeps_its_own_payload(tmp_path):
    result = lower(tmp_path, """
        def f(flag, left, right):
            if flag:
                return left
            return right
    """)
    assert_supported(result)
    assert {payload(done) for _, _, done in exits(result)} == {formals(result)["left"], formals(result)["right"]}
    assert_replays(result)


def state_predecessor_operations(result, value_id):
    """Follow only declared state dependencies, keeping branch inputs separate."""
    ops, values, _ = tables(result)
    visited, found, pending = set(), set(), [value_id]
    while pending:
        value_id = pending.pop()
        if value_id in visited:
            continue
        visited.add(value_id)
        origin = values[value_id].origin
        if isinstance(origin, OperationResult):
            op = ops[origin.operation]
            found.add(op.id)
            pending.extend(use.value for use in op.uses if isinstance(values[use.value], StateVersionValue))
        elif isinstance(origin, BlockArgument):
            for op, actual in incoming_values(result, value_id):
                if isinstance(actual, CompletionResult):
                    found.add(op.id)
                    pending.extend(use.value for use in op.uses if isinstance(values[use.value], StateVersionValue))
                else:
                    pending.append(actual)
    return found


def test_branch_only_local_hold_survives_through_world_without_fake_binding_on_other_path(tmp_path):
    result = lower(tmp_path, """
        def f(flag, x):
            if flag:
                local = x
            return x
    """)
    assert_supported(result)
    ops, values, _ = tables(result)
    bind, = [item for item in result.frame.transitions if isinstance(item, FrameBind)]
    _, frame_exit, done = exits(result)[0]
    assert payload(done) == formals(result)["x"]
    before_id = frame_exit.accesses[0].before
    before = next(use.value for use in frame_exit.uses if use.id == before_id)
    assert isinstance(values[before], StateVersionValue)
    incoming = incoming_values(result, before)
    assert len(incoming) == 2
    paths = [state_predecessor_operations(result, state) for _, state in incoming]
    assert sum(bind.operation in path for path in paths) == 1
    assert bind.operation in state_predecessor_operations(result, before)
    assert ops[bind.operation].accesses[0].after in {state for _, state in incoming}
    assert_replays(result)


def test_expression_discard_occurs_before_next_call_and_first_bind_is_a_state_action(tmp_path):
    result = lower(tmp_path, """
        def f(x, mark):
            local = x
            local
            mark()
            return local
    """)
    assert_supported(result)
    ops, values, _ = tables(result)
    bind, = [item for item in result.frame.transitions if isinstance(item, FrameBind)]
    discards = [item for item in result.frame.transitions if isinstance(item, FrameDiscard)]
    assert len(discards) == 2
    first = next(item for item in discards if item.source.start_line == 3)
    invoked, = [op for op in ops.values() if op.terminator and op.terminator.kind is TerminatorKind.INVOKE]
    invocation_state, = [use.value for use in invoked.uses if isinstance(values[use.value], StateVersionValue)]
    assert invocation_state == ops[first.operation].accesses[0].after
    assert bind.operation in state_predecessor_operations(result, invocation_state)
    assert payload(exits(result)[0][2]) == formals(result)["x"]
    assert_replays(result)


def test_every_expression_exception_unwinds_its_own_payload_and_post_state_once(tmp_path):
    result = lower(tmp_path, "def f(touch, failing):\n    touch()\n    return failing()\n")
    assert_supported(result)
    ops, values, blocks = tables(result)
    invokes = [op for op in ops.values() if op.terminator and op.terminator.kind is TerminatorKind.INVOKE]
    assert len(invokes) == 2
    exceptional = {item.operation: (item, op, done) for item, op, done in exits(result, TerminatorKind.RAISE)}
    assert len(exceptional) == len(invokes)
    for invoked in invokes:
        edge, = [edge for edge in invoked.terminator.successors if edge.kind is ExitKind.RAISE]
        block = blocks[edge.block]
        assert len(block.operations) == 2
        item, unwind, done = exceptional[block.operations[0]]
        held = next(use.value for use in unwind.uses if use.id == item.payload)
        before = next(use.value for use in unwind.uses if use.id == unwind.accesses[0].before)
        assert held == block.arguments[0] == payload(done)
        assert before == block.arguments[1]
        assert isinstance(values[before], StateVersionValue)
        assert unwind.accesses[0].after != before
        assert next(use.value for use in done.uses if use.id == done.terminator.values[1]) == unwind.accesses[0].after
        assert unwind.terminator is None
    assert_replays(result)


@pytest.mark.parametrize("body", ["return", "pass", "x = None"])
def test_bare_and_implicit_return_hold_none_without_unknown_replacement(tmp_path, body):
    result = lower(tmp_path, "def f():\n    " + body + "\n")
    assert_supported(result)
    _, values, _ = tables(result)
    returned = values[payload(exits(result)[0][2])]
    assert isinstance(returned, ReferenceValue)
    assert isinstance(returned.origin, LiteralOrigin) and returned.origin.value is None
    assert not exits(result, TerminatorKind.RAISE)
    assert_replays(result)


def test_generated_rules_keep_applicability_effects_termination_and_release_unproved(tmp_path):
    result = lower(tmp_path, "def f(x):\n    y = x\n    y\n    return y\n")
    assert_supported(result)
    rules = result.frame.rules
    assert rules.condition_status is ProofStatus.UNKNOWN
    assert rules.effects is Completeness.UNKNOWN
    assert rules.termination is FrameTermination.MAY_NOT_COMPLETE
    assert rules.release is FrameRelease.NOT_GUARANTEED
    assert rules.finalizer_errors is FrameFinalizerErrors.UNRAISABLE
    ops, _, _ = tables(result)
    for transition in result.frame.transitions:
        op = ops[transition.operation]
        assert not op.effects_complete and op.terminator is None
        assert op.accesses[0].mode is AccessMode.READ_WRITE
        assert not op.accesses[0].full_overwrite
    assert GapKind.FRAME_EFFECT in {gap.kind for gap in result.metadata.gaps}
    assert result.summary()["transformation_authorized"] is False


@pytest.mark.parametrize("source", [
    "def f(x):\n    try:\n        return x\n    finally:\n        x()\n",
    "def f(x):\n    with x:\n        return x\n",
    "def f(x):\n    del x\n    return None\n",
    "def f(x):\n    raise x\n",
    "def f(x):\n    return x\n    yield x\n",
    "async def f(x):\n    return x\n",
    "def f(x):\n    while x:\n        pass\n    return x\n",
    "def f(x):\n    for item in x:\n        pass\n    return x\n",
])
def test_unsupported_lifetime_and_control_forms_leave_no_partial_frame_graph(tmp_path, source):
    result = lower(tmp_path, source)
    assert result.graph is None
    assert result.frame is None and result.interface is None
    assert not result.metadata.operation_links and not result.metadata.use_links and not result.metadata.value_links
    assert {GapKind.UNSUPPORTED_SYNTAX, GapKind.UNSUPPORTED_SIGNATURE} & {gap.kind for gap in result.metadata.gaps}
    assert result.to_dict()["status"] == "UNSUPPORTED"
    assert_replays(result)


def test_source_selected_closure_requires_a_cell_interface_and_leaves_no_frame_graph(tmp_path):
    path = tmp_path / "raw.py"
    path.write_text("def outer(x):\n    def f():\n        return x\n    return f\n")
    context = prepare_source(path)
    source, = [atom.reference for atom in context.semantic.source_atoms.values()
               if atom.kind == "FunctionDef" and atom.reference.start_line == 2]
    body = context.lower("f", source=source, profile=BodyLoweringProfile.BOUND_FRAME,
                         expand_candidates=False)
    assert body.graph is None and body.frame is None and body.interface is None
    assert not body.metadata.operation_links and not body.metadata.use_links and not body.metadata.value_links
    assert any(gap.kind is GapKind.UNSUPPORTED_SIGNATURE and "closure/cell" in gap.detail
               for gap in body.metadata.gaps)


def test_prepared_frame_lowering_requires_explicit_root_only_scope(tmp_path):
    result = lower(tmp_path, "def f(x):\n    return x\n")
    context = prepare_source(result.metadata.source.path)
    with pytest.raises(ValueError, match="root-only"):
        context.lower("f", profile=BodyLoweringProfile.BOUND_FRAME)
    body = context.lower("f", profile=BodyLoweringProfile.BOUND_FRAME, expand_candidates=False)
    assert body.graph == result.graph
    assert body.frame == result.frame and body.interface == result.interface


@pytest.mark.parametrize("mutation", ["drop_overlay", "promote_condition", "promote_effects", "old_world", "profile"])
def test_public_source_replay_rejects_independent_wire_tampering(tmp_path, mutation):
    result = lower(tmp_path, "def f(x):\n    local = x\n    return local\n")
    assert_supported(result)
    wire = deepcopy(result.to_dict())
    if mutation == "drop_overlay":
        wire["frame"]["transitions"] = [item for item in wire["frame"]["transitions"] if "assigned" not in item]
    elif mutation == "promote_condition":
        wire["frame"]["rules"]["condition_status"] = "PROVEN"
    elif mutation == "promote_effects":
        wire["frame"]["rules"]["effects"] = "COMPLETE"
    elif mutation == "profile":
        wire["profile"] = BodyLoweringProfile.BOUND_FORMALS.value
    else:
        done = exits(result)[0][2]
        raw = next(op for op in wire["graph"]["operations"] if op["id"]["wire"] == done.id.wire)
        state_use = next(use for use in raw["uses"] if use["id"]["wire"] == done.terminator.values[1].wire)
        state_use["value"] = deepcopy(wire["interface"]["world"])
    with pytest.raises(ValueError):
        SourceProgram.from_dict(wire)


def test_source_replay_rejects_consistent_but_wrong_return_payload(tmp_path):
    result = lower(tmp_path, "def f(x, other):\n    return x\n")
    assert_supported(result)
    item, exit_op, done = exits(result)[0]
    other = formals(result)["other"]
    wrong = {exit_op.id: item.payload, done.id: done.terminator.values[0]}
    graph = replace(result.graph, operations=tuple(
        replace(op, uses=tuple(replace(use, value=other) if use.id == wrong[op.id] else use for use in op.uses))
        if op.id in wrong else op for op in result.graph.operations))
    tampered = replace(result, graph=graph)
    assert_supported(tampered)  # Core/overlay agreement alone is insufficient.
    with pytest.raises(ValueError, match="differs from source replay"):
        SourceProgram.from_dict(tampered.to_dict())


def test_source_replay_rejects_deleted_bind_even_with_valid_core_state_splice(tmp_path):
    result = lower(tmp_path, "def f(x):\n    local = x\n    return local\n")
    assert_supported(result)
    ops, _, _ = tables(result)
    bind, = [item for item in result.frame.transitions if isinstance(item, FrameBind)]
    removed = ops[bind.operation]
    after = removed.accesses[0].after
    before = next(use.value for use in removed.uses if use.id == removed.accesses[0].before)
    graph = replace(result.graph,
        operations=tuple(replace(op, uses=tuple(replace(use, value=before) if use.value == after else use for use in op.uses))
                         for op in result.graph.operations if op.id != bind.operation),
        values=tuple(value for value in result.graph.values if value.id != after),
        regions=tuple(replace(region, blocks=tuple(replace(block, operations=tuple(op for op in block.operations if op != bind.operation))
                                                  for block in region.blocks)) for region in result.graph.regions))
    frame = replace(result.frame, transitions=tuple(item for item in result.frame.transitions if item.operation != bind.operation))
    metadata = replace(result.metadata,
        operation_links=tuple(link for link in result.metadata.operation_links if link.operation != bind.operation),
        use_links=tuple(link for link in result.metadata.use_links if link.operation != bind.operation),
        value_links=tuple(link for link in result.metadata.value_links if link.value != after))
    tampered = replace(result, graph=graph, frame=frame, metadata=metadata)
    assert_supported(tampered)  # Deliberately structurally valid; this is a replay counterexample.
    with pytest.raises(ValueError, match="differs from source replay"):
        SourceProgram.from_dict(tampered.to_dict())


def test_changed_raw_source_invalidates_previously_valid_frame_report(tmp_path):
    result = lower(tmp_path, "def f(x, other):\n    return x\n")
    wire = result.to_dict()
    (tmp_path / "raw.py").write_text("def f(x, other):\n    return other\n")
    with pytest.raises(ValueError):
        SourceProgram.from_dict(wire)


def test_frame_actions_consume_construction_and_independent_replay_budget(tmp_path):
    result = lower(tmp_path, "def f(x):\n    local = x\n    return local\n")
    assert_supported(result)
    assert len(result.graph.operations) == 4  # ENTER, first BIND, EXIT, RETURN.
    context = prepare_source(result.metadata.source.path)
    exhausted = context.lower("f", profile=BodyLoweringProfile.BOUND_FRAME, expand_candidates=False, max_operations=3)
    assert exhausted.graph is None and exhausted.frame is None and exhausted.interface is None
    assert exhausted.operations_emitted == 3
    assert GapKind.BUDGET in {gap.kind for gap in exhausted.metadata.gaps}
    with pytest.raises(ValueError):
        SourceProgram.from_dict(result.to_dict(), max_operations=3)


def test_legacy_default_still_emits_and_replays_its_historical_source_schema(tmp_path):
    path = tmp_path / "raw.py"
    path.write_text("def f(x):\n    return x\n")
    result = lower_source(path, "f")
    assert result.profile is BodyLoweringProfile.LEGACY
    assert result.frame is None and result.interface is None
    wire = result.to_dict()
    assert wire["schema_version"] == 1 and "frame" not in wire and "profile" not in wire
    assert SourceProgram.from_dict(wire).to_dict() == wire
