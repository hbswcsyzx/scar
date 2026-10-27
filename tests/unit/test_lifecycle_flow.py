"""Owner-flow algebra and existing valid declaration fixtures, not runtime proof."""
from dataclasses import FrozenInstanceError, replace
from itertools import product
import random

import pytest

from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.lifecycle_flow import (
    _Must, _empty, _finish, _meet, _rename, derive_terminal_facts, reference_assignments,
)


def test_shared_selected_owner_keeps_distinct_terminal_anchors_correlated():
    base = _empty(4)
    left, right = _finish(base, 0), _finish(base, 1)
    good = _meet((_rename(left, {2: 0}), _rename(right, {2: 1})))
    bad = _meet((_rename(left, {2: 1, 3: 0}), _rename(right, {2: 0, 3: 1})))
    assert 2 in good.finished
    assert 2 not in bad.finished and 3 in bad.finished


def test_simultaneous_swap_and_forget_keep_other_alias_carriers():
    state = _finish(_rename(_empty(4), {2: 0, 3: 0}), 0)
    swapped = _rename(state, {0: 1, 1: 0})
    assert 0 not in swapped.finished and {1, 2, 3} <= swapped.finished
    reset = _rename(state, {0: None})
    assert 0 not in reset.finished and {2, 3} <= reset.finished
    assert reset.classes[2] == reset.classes[3] != reset.classes[0]


def test_unreachable_is_not_a_vacuous_terminal_proof_and_meet_is_must():
    base = _empty(2)
    assert _meet((None, None)) is None
    assert not _meet((_finish(base, 0), base)).finished
    assert _meet((_finish(base, 0), None)).finished == {0}


def test_bounded_concrete_alias_history_oracle_for_must_transfers():
    # Concrete objects are independent of static carriers/seed labels. Distinct
    # abstract classes do not claim disequality. Unknown results may alias any
    # old object or a new object, and may therefore be terminal in some runs.
    histories = [frozenset(obj for obj in range(3) if bits & (1 << obj)) for bits in range(8)]
    pool = tuple(product(product(range(3), repeat=3), histories))
    rng = random.Random(20261018)

    def abstract(states):
        representative = {}
        classes = tuple(representative.setdefault(tuple(refs[index] for refs, _ in states), index)
                        for index in range(3))
        return _Must(classes, frozenset(index for index in range(3)
                                       if all(refs[index] in history for refs, history in states)))

    def sound(state, concrete):
        for refs, history in concrete:
            assert all(refs[left] == refs[right] for left in range(3) for right in range(3)
                       if state.classes[left] == state.classes[right])
            assert all(refs[index] in history for index in state.finished)

    for _ in range(100):
        states = rng.sample(pool, rng.randrange(1, 5))
        state = abstract(states)
        sound(_finish(state, 0), [(refs, history | {refs[0]}) for refs, history in states])
        sound(_rename(state, {0: 1, 1: 0}), [((refs[1], refs[0], refs[2]), history)
                                                   for refs, history in states])
        sound(_rename(state, {2: 0}), [((refs[0], refs[1], refs[0]), history)
                                             for refs, history in states])
        sound(_rename(state, {0: None}), [((obj, refs[1], refs[2]), history)
                                                for refs, history in states for obj in range(4)])
        sound(state, states)  # unknown callback cannot reset this profile's history
        midpoint = max(1, len(states) // 2)
        pieces = [abstract(part) for part in (states[:midpoint], states[midpoint:]) if part]
        sound(_meet(pieces), states)


@pytest.mark.parametrize("target,terminal", (("start", False), ("value", True), ("packet", True)))
def test_existing_publication_source_kind_seeds_only_terminal_after(target, terminal):
    from tests.fixtures.program_publication_graphs import publication_program
    graph = publication_program(target=target)
    interface, = graph.driver_interfaces
    row, = graph.body_outcome_commits
    op = next(op for op in graph.operations if op.id == row.operation)
    owner = next(use.value for use in op.uses if use.id == row.instance)
    facts = derive_terminal_facts(graph, interface)
    assert not facts.before[row.operation].is_finished(owner)
    assert facts.after[row.operation].is_finished(owner) is terminal
    assert facts.after[row.operation].source_operations(owner) == (
        frozenset((row.operation,)) if terminal else frozenset())


def test_no_body_finish_seed_and_predicate_only_no_seed_are_separate():
    from tests.fixtures.program_no_body_graphs import no_body_program
    graph = no_body_program()
    interface, = graph.driver_interfaces
    finish, = graph.no_body_finishes
    op = next(op for op in graph.operations if op.id == finish.operation)
    owner = next(use.value for use in op.uses if use.id == finish.instance)
    facts = derive_terminal_facts(graph, interface)
    assert facts.after[finish.operation].source_operations(owner) == {finish.operation}
    graph = no_body_program(predicate_only=True)
    facts = derive_terminal_facts(graph, graph.driver_interfaces[0])
    assert all(not point.finished for point in facts.after.values())


def test_renamed_edges_expose_same_owner_before_target_meet_and_are_immutable():
    from tests.fixtures.program_publication_graphs import publication_program
    graph = publication_program(target="value")
    drive, = graph.body_drives
    row, = graph.body_outcome_commits
    op = next(op for op in graph.operations if op.id == drive.operation)
    commit = next(op for op in graph.operations if op.id == row.operation)
    original = next(use.value for use in op.uses if use.id == drive.instance)
    owner = next(use.value for use in commit.uses if use.id == row.instance)
    facts = derive_terminal_facts(graph, graph.driver_interfaces[0])
    edge = facts.edges[(drive.operation, 0)]
    assert edge.same_owner(original, owner)
    assert not edge.is_finished(owner)
    with pytest.raises(TypeError):
        edge.aliases[ValueID("other")] = frozenset()
    with pytest.raises(TypeError):
        facts.before[OperationID("other")] = edge
    with pytest.raises(FrozenInstanceError):
        edge.reachable = False


@pytest.mark.parametrize("boundary", ("drive", "invoke", "temporal", "legacy"))
def test_reference_assignments_resolve_original_uses_and_fresh_boundaries(boundary):
    from scar.ir.program.ids import UseID
    from tests.fixtures.program_no_body_graphs import no_body_program
    from tests.fixtures.program_publication_graphs import publication_program
    from tests.fixtures.program_resumption_graphs import resumption_program

    if boundary == "drive":
        graph = publication_program(target="value")
        op = next(op for op in graph.operations if op.id == graph.body_drives[0].operation)
        edge = op.terminator.successors[0]
        expected = {ValueID("driver.outcome.arg.0"): None,
                    ValueID("publication.0.owner"): ValueID("driver.ingress.arg.0")}
    elif boundary == "invoke":
        graph = no_body_program(receiver="ASYNC_REQUEST", association=True)
        op = next(op for op in graph.operations if op.id == graph.request_association_reads[0].operation)
        edge = op.terminator.successors[0]
        expected = {ValueID("driver.association.body"): None,
                    ValueID("driver.no_body.test.arg.3"): ValueID("driver.entry.arg.2")}
    elif boundary == "temporal":
        graph = resumption_program()
        op = next(op for op in graph.operations if op.id == OperationID("resume.suspend"))
        edge = op.terminator.successors[0]
        expected = {ValueID("resume.value.x"): ValueID("resume.x"), ValueID("resume.value.sent"): None}
    else:
        class LegacyUse(UseID):
            pass
        graph = no_body_program()
        op = next(op for op in graph.operations if op.id == graph.no_body_finishes[0].precondition.operation)
        edge = op.terminator.successors[0]
        actual = edge.arguments[0]
        old = next(use for use in op.uses if use.id == actual)
        alias = LegacyUse(actual.value)
        edge = replace(edge, arguments=(alias, *edge.arguments[1:]))
        op = replace(op, uses=tuple(replace(use, id=alias) if use.id == actual else use for use in op.uses),
                     terminator=replace(op.terminator, successors=(edge, *op.terminator.successors[1:])))
        expected = {ValueID("driver.no_body.owner"): old.value}
    values = {value.id: value for value in graph.values}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    assert reference_assignments(op, edge, values=values, blocks=blocks) == expected


def test_explicit_scope_and_only_owning_driver_operations_are_analyzed():
    from tests.fixtures.program_no_body_graphs import no_body_program
    graph = no_body_program(create=True)
    interface, = graph.driver_interfaces
    region = next(region for region in graph.regions if region.id == interface.region)
    facts = derive_terminal_facts(graph, interface)
    assert set(facts.before) == {op_id for block in region.blocks for op_id in block.operations}
    with pytest.raises(ValueError, match="explicit DriverLifecycle"):
        derive_terminal_facts(replace(graph, driver_lifecycles=()), interface)


def _shared_flow_graph(*, seeded=True, wrong_owner=False, loop=False):
    """Join two real driver paths after their existing private first marks."""
    from scar.ir.program.ids import BlockID, UseID
    from scar.ir.program.model import (
        Behavior, Block, BlockArgument, DataValue, LiteralOrigin, Operation,
        ReferenceValue, StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseRole,
    )
    from tests.fixtures.program_no_body_graphs import no_body_program

    graph = no_body_program(target="value" if seeded else "start", predicate_only=not seeded)
    interface, = graph.driver_interfaces
    region = next(region for region in graph.regions if region.id == interface.region)
    by_id = {op.id: op for op in graph.operations}
    values = {value.id: value for value in graph.values}
    normal = [by_id[block.operations[-1]] for block in region.blocks
              if by_id[block.operations[-1]].terminator.kind is TerminatorKind.RETURN]
    assert len(normal) == 2
    state_ids = [use.value for use in normal[0].uses[1:]]
    join_id, exit_id = BlockID("flow.join"), BlockID("flow.exit")

    def formals(block):
        made = [ReferenceValue(ValueID(f"{block.value}.owner"), region.id, BlockArgument(block, 0))]
        made.extend(StateVersionValue(ValueID(f"{block.value}.state.{i}"), region.id,
            BlockArgument(block, i + 1), values[old].location) for i, old in enumerate(state_ids))
        return made

    joined = formals(join_id)
    join_args = tuple(value.id for value in joined)
    new_values = list(joined)

    def uses(name, arguments):
        return tuple(Use(UseID(f"{name}.{i}"), value,
                         UseRole.REFERENCE if i == 0 else UseRole.STATE_CONTENT)
                     for i, value in enumerate(arguments))

    # Source landing payloads remain real projections. Only owner/state actuals
    # are selected for a common downstream host return; no new source producer.
    for terminal in normal:
        source_block = next(block for block in region.blocks if terminal.id in block.operations)
        rows = (*graph.no_body_finishes, *graph.body_outcome_commits)
        mark = next((row for row in rows if row.operation in source_block.operations), None)
        owner = (next(use.value for use in by_id[mark.operation].uses if use.id == mark.instance)
                 if mark is not None else terminal.uses[0].value)
        if wrong_owner and any(row.operation in source_block.operations for row in graph.body_outcome_commits):
            owner = terminal.uses[0].value  # produced reference payload, not the seeded owner
        actuals = uses(f"flow.from.{terminal.id.value}", (owner, *(use.value for use in terminal.uses[1:])))
        by_id[terminal.id] = replace(terminal, uses=actuals, terminator=Terminator(
            TerminatorKind.JUMP, (Successor(join_id, tuple(use.id for use in actuals)),)))

    exit_args = join_args
    new_blocks, new_operations = [], []
    if loop:
        exited = formals(exit_id)
        new_values.extend(exited)
        exit_args = tuple(value.id for value in exited)
        condition = DataValue(ValueID("flow.condition"), region.id, LiteralOrigin(True), "builtins.bool")
        new_values.append(condition)
        select = Use(UseID("flow.loop.condition"), condition.id, UseRole.DATA)
        back, onward = uses("flow.loop.back", join_args), uses("flow.loop.exit", join_args)
        branch = Operation(OperationID("flow.loop"), "loop carries the selected owner", (Behavior.CONTROL,),
            (select, *back, *onward), terminator=Terminator(TerminatorKind.BRANCH,
                (Successor(join_id, tuple(use.id for use in back)),
                 Successor(exit_id, tuple(use.id for use in onward))), condition=select.id), effects_complete=True)
        new_operations.append(branch)
        new_blocks.append(Block(join_id, join_args, (branch.id,)))
    returned = uses("flow.return", exit_args)
    ret = Operation(OperationID("flow.return"), "shared downstream return", (Behavior.CONTROL,), returned,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal", values=tuple(use.id for use in returned)))
    new_operations.append(ret)
    new_blocks.append(Block(exit_id if loop else join_id, exit_args, (ret.id,)))
    graph = replace(graph, operations=(*by_id.values(), *new_operations), values=(*graph.values, *new_values),
        regions=tuple(replace(old, blocks=(*old.blocks, *new_blocks)) if old.id == region.id else old
                      for old in graph.regions),
        control_scopes=tuple(replace(scope, blocks=(*scope.blocks, *(block.id for block in new_blocks)))
                             if scope.region == region.id else scope for scope in graph.control_scopes))
    return graph, joined[0].id


@pytest.mark.parametrize("loop", (False, True))
def test_real_shared_paths_and_anchored_loop_union_sources_after_must_stabilizes(loop):
    from scar.ir.program.validation import require_valid
    graph, owner = _shared_flow_graph(loop=loop)
    require_valid(graph)
    facts = derive_terminal_facts(graph, graph.driver_interfaces[0])
    point = facts.before[OperationID("flow.loop" if loop else "flow.return")]
    assert point.is_finished(owner)
    assert point.source_operations(owner) == {
        graph.no_body_finishes[0].operation, graph.body_outcome_commits[0].operation}


def test_real_join_does_not_cross_seeded_owner_with_unfinished_payload():
    from scar.ir.program.validation import require_valid
    graph, owner = _shared_flow_graph(wrong_owner=True)
    require_valid(graph)
    facts = derive_terminal_facts(graph, graph.driver_interfaces[0])
    assert not facts.before[OperationID("flow.return")].is_finished(owner)
    assert not facts.before[OperationID("flow.return")].source_operations(owner)
    incoming = [point for (operation, _), point in facts.edges.items()
                if operation in {OperationID("driver.no_body.return"), OperationID("driver.outcome.exit")}]
    assert len(incoming) == 2 and sum(point.is_finished(owner) for point in incoming) == 1


def test_real_loop_without_a_terminal_seed_does_not_self_justify_finished():
    from scar.ir.program.validation import require_valid
    graph, owner = _shared_flow_graph(seeded=False, loop=True)
    require_valid(graph)
    facts = derive_terminal_facts(graph, graph.driver_interfaces[0])
    point = facts.before[OperationID("flow.loop")]
    assert point.reachable and not point.is_finished(owner) and not point.source_operations(owner)
