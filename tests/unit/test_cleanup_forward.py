"""Forwarding algorithms and their canonical CFG operand bindings.

The small record assemblies isolate the helper from routing/state validators;
they are not complete cleanup acceptance fixtures or runtime execution proofs.
"""
from dataclasses import FrozenInstanceError, replace

import pytest

from scar.ir.program.cleanup import CleanupEnter, CleanupInterface
from scar.ir.program.cleanup_forward import (
    CleanupForwardFacts, _must_forward, derive_cleanup_forward,
)
from scar.ir.program.control import (
    PendingCompletionDefinition, PendingDispatchTerminator, PendingPayload,
    PendingSuccessor, ProtocolValueKind as P, ProtocolValueType,
)
from scar.ir.program.ids import (
    BlockID, ControlPortID, ControlScopeID, OperationID, RegionID, UseID, ValueID,
)
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, LiteralOrigin, Operation,
    OperationResult, ProgramGraph, ProtocolValue, Region, Successor, Terminator,
    TerminatorKind, Use, UseRole,
)


def _ids(*names):
    return frozenset(ValueID(name) for name in names)


@pytest.mark.parametrize("reverse", [False, True])
def test_seedless_cycle_cannot_pollute_a_seeded_phi_or_its_consumers(reverse):
    anchor, cycle, phi, consumer = map(ValueID, ("anchor", "cycle", "phi", "consumer"))
    rows = [(cycle, (cycle,)), (phi, (anchor, cycle)), (consumer, (phi,))]
    incoming = dict(reversed(rows) if reverse else rows)
    assert _must_forward({anchor}, incoming) == {anchor}


def test_seedless_cycles_and_empty_incoming_do_not_prove_copies():
    a, b, empty = map(ValueID, ("a", "b", "empty"))
    assert _must_forward(set(), {a: (b,), b: (a,), empty: ()}) == frozenset()


def test_seeded_mutual_loop_is_accepted_but_external_boundary_poison_propagates():
    anchor, a, b, exit_value = map(ValueID, ("anchor", "a", "b", "exit"))
    incoming = {a: (anchor, b), b: (a,), exit_value: (b,)}
    assert _must_forward({anchor}, incoming) == {anchor, a, b, exit_value}
    assert _must_forward({anchor}, {**incoming, b: (a, None)}) == {anchor}


def _graph(arguments, edges, *, contexts=(), packs=None, invokes=(), dispatches=(), inner=None):
    """Assemble real immutable records; all supplied edges/arguments stay ordered."""
    region = RegionID("forward")
    values, operations, definitions, blocks, enters = [], [], [], [], []
    contexts = frozenset(contexts) | {"context"}
    packs = packs or {}
    interfaces = [CleanupInterface(ControlScopeID("outer"), ControlScopeID("protected"),
                                   BlockID("entry"), ValueID("pending"))]
    enter_specs = [("outer", "entry", "pending", "context")]
    if inner is not None:
        name, block, pending, context = inner
        contexts |= {context}
        enter_specs.append(inner)
        interfaces.append(CleanupInterface(ControlScopeID(name), ControlScopeID(name + ".protected"),
                                            BlockID(block), ValueID(pending)))
    for name, names in arguments.items():
        for index, value_name in enumerate(names):
            protocol = P.SAVED_HANDLED_CONTEXT if value_name in contexts else P.PENDING_COMPLETION
            values.append(ProtocolValue(ValueID(value_name), region,
                                        BlockArgument(BlockID(name), index), protocol))

    for name, names in arguments.items():
        block_operations = []
        for scope, entry, pending, context in enter_specs:
            if name != entry:
                continue
            identity = OperationID(scope + ".enter")
            used = Use(UseID(scope + ".enter.pending"), ValueID(pending), UseRole.PROTOCOL)
            result = ProtocolValue(ValueID(context), region, OperationResult(identity, 0),
                                   P.SAVED_HANDLED_CONTEXT)
            operations.append(Operation(identity, "enter", (Behavior.CONTROL,), (used,), (result.id,)))
            values.append(result)
            enters.append(CleanupEnter(identity, ControlScopeID(scope), used.id, result.id))
            block_operations.append(identity)
        for value_name in packs.get(name, ()):
            identity = OperationID("pack." + value_name)
            value = ProtocolValue(ValueID(value_name), region, OperationResult(identity, 0),
                                  P.PENDING_COMPLETION)
            values.append(value)
            operations.append(Operation(identity, "pack", (Behavior.CONTROL,), results=(value.id,)))
            definitions.append(PendingCompletionDefinition(value.id, ControlPortID("same.port")))
            block_operations.append(identity)

        identity = OperationID(name + ".term")
        uses, successors = [], []
        local_edges = edges.get(name, ())
        for index, (target, actuals) in enumerate(local_edges):
            actual_arguments = []
            for slot, actual in enumerate(actuals):
                if isinstance(actual, str):
                    used = Use(UseID(f"{name}.edge{index}.slot{slot}"), ValueID(actual), UseRole.PROTOCOL)
                    uses.append(used)
                    actual_arguments.append(used.id)
                else:
                    actual_arguments.append(actual)
            if name in invokes:
                successors.append(CompletionSuccessor((ExitKind.NORMAL, ExitKind.RAISE)[index],
                                                       BlockID(target), tuple(actual_arguments)))
            elif name in dispatches:
                successors.append(PendingSuccessor(ControlPortID(f"case{index}"),
                                                    BlockID(target), tuple(actual_arguments)))
            else:
                successors.append(Successor(BlockID(target), tuple(actual_arguments)))
        completions = ()
        if name in invokes:
            completions = tuple(CompletionSignature(kind, (ProtocolValueType(P.PENDING_COMPLETION),))
                                for kind in (ExitKind.NORMAL, ExitKind.RAISE))
            term = Terminator(TerminatorKind.INVOKE, tuple(successors))
        elif name in dispatches:
            selected = Use(UseID(name + ".selector"), ValueID("pending"), UseRole.PROTOCOL)
            uses.append(selected)
            term = PendingDispatchTerminator(selected.id, tuple(successors))
        elif len(successors) == 2:
            condition = DataValue(ValueID(name + ".condition"), region, LiteralOrigin(True), "builtins.bool")
            values.append(condition)
            used = Use(UseID(name + ".condition"), condition.id)
            uses.append(used)
            term = Terminator(TerminatorKind.BRANCH, tuple(successors), condition=used.id)
        elif successors:
            term = Terminator(TerminatorKind.JUMP, tuple(successors))
        else:
            term = Terminator(TerminatorKind.RETURN, exit="normal")
        operations.append(Operation(identity, "control", (Behavior.CONTROL,), tuple(uses),
                                    terminator=term, completions=completions))
        block_operations.append(identity)
        blocks.append(Block(BlockID(name), tuple(ValueID(value) for value in names),
                            tuple(block_operations)))
    body = Region(region, "forward", BlockID("entry"), tuple(blocks),
                  (ExitPort("normal", ExitKind.NORMAL, ()),))
    graph = ProgramGraph(region, (body,), tuple(operations), tuple(values),
                         pending_completions=tuple(definitions), cleanup_enters=tuple(enters),
                         cleanup_interfaces=tuple(interfaces))
    return graph, interfaces[0]


def _facts(graph, interface, *, scope=None, dominators=None):
    blocks = graph.regions[0].blocks
    operation_blocks = {operation: block.id for block in blocks for operation in block.operations}
    if dominators is None:
        dominators = {block.id: {interface.entry, block.id} for block in blocks}
    return derive_cleanup_forward(graph, interface,
        scope_blocks=frozenset(BlockID(name) for name in scope) if scope is not None
        else frozenset(block.id for block in blocks),
        operation_blocks=operation_blocks, dominators=dominators)


def test_real_phi_accepts_only_unchanged_pending_and_context_on_both_branches():
    graph, interface = _graph(
        {"entry": ("pending",), "left": ("lp", "lc"), "right": ("rp", "rc"), "join": ("jp", "jc")},
        {"entry": (("left", ("pending", "context")), ("right", ("pending", "context"))),
         "left": (("join", ("lp", "lc")),), "right": (("join", ("rp", "rc")),)},
        contexts=("lc", "rc", "jc"))
    facts = _facts(graph, interface)
    assert facts.pending == _ids("pending", "lp", "rp", "jp")
    assert facts.context == _ids("context", "lc", "rc", "jc")
    assert facts.fresh == frozenset()


def test_same_port_repack_is_fresh_but_does_not_resume_saved_pending():
    graph, interface = _graph({"entry": ("pending",), "body": ("copied", "saved"), "join": ("selected",)},
        {"entry": (("body", ("pending", "context")),),
         "body": (("join", ("copied",)), ("join", ("repacked",)))},
        contexts=("saved",), packs={"body": ("repacked",)})
    facts = _facts(graph, interface)
    assert facts.pending == _ids("pending", "copied")
    assert facts.context == _ids("context", "saved")
    assert facts.fresh == _ids("repacked")
    assert ValueID("selected") not in facts.pending | facts.fresh


def test_distinct_local_packs_can_merge_as_fresh_without_becoming_saved_copy():
    graph, interface = _graph(
        {"entry": ("pending",), "left": (), "right": (), "join": ("selected",)},
        {"entry": (("left", ()), ("right", ())),
         "left": (("join", ("left.new",)),), "right": (("join", ("right.new",)),)},
        packs={"left": ("left.new",), "right": ("right.new",)})
    facts = _facts(graph, interface)
    assert facts.pending == _ids("pending")
    assert facts.fresh == _ids("left.new", "right.new", "selected")


def test_operation_result_without_pending_definition_does_not_seed_freshness():
    graph, interface = _graph({"entry": ("pending",), "body": ("result",)},
        {"entry": (("body", ("ordinary.result",)),)}, packs={"entry": ("ordinary.result",)})
    facts = _facts(replace(graph, pending_completions=()), interface)
    assert facts.pending == _ids("pending")
    assert facts.fresh == frozenset()


def test_two_successors_to_same_block_keep_each_actual_formal_position():
    graph, interface = _graph(
        {"entry": ("pending", "other"), "join": ("first", "second", "saved")},
        {"entry": (("join", ("pending", "other", "context")),
                   ("join", ("other", "pending", "context")))}, contexts=("saved",))
    facts = _facts(graph, interface)
    assert facts.pending == _ids("pending")
    assert facts.context == _ids("context", "saved")


def test_loop_self_carries_pending_context_and_fresh_pack_without_losing_seed():
    graph, interface = _graph(
        {"entry": ("pending",), "loop": ("lp", "lc", "new"), "exit": ("ep", "ec", "en")},
        {"entry": (("loop", ("pending", "context", "packed")),),
         "loop": (("loop", ("lp", "lc", "new")), ("exit", ("lp", "lc", "new")))},
        contexts=("lc", "ec"), packs={"entry": ("packed",)})
    facts = _facts(graph, interface)
    assert facts.pending == _ids("pending", "lp", "ep")
    assert facts.context == _ids("context", "lc", "ec")
    assert facts.fresh == _ids("packed", "new", "en")


def test_previous_visit_of_same_static_enter_result_does_not_seed_entry_argument():
    graph, interface = _graph(
        {"entry": ("pending", "old.context", "old.pending"),
         "body": ("bp", "old.saved", "current.saved", "old.selected"), "outside": ()},
        {"entry": (("body", ("pending", "old.context", "context", "old.pending")),),
         "body": (("outside", ()),),
         "outside": (("entry", ("bp", "context", "repacked")),)},
        contexts=("old.context", "old.saved", "current.saved"), packs={"body": ("repacked",)})
    facts = _facts(graph, interface, scope=("entry", "body"))
    assert facts.slice_blocks == {BlockID("entry"), BlockID("body")}
    assert facts.pending == _ids("pending", "bp")
    assert facts.context == _ids("context", "current.saved")
    assert facts.fresh == _ids("repacked")


def test_external_predecessor_is_false_even_when_it_names_current_anchor():
    graph, interface = _graph(
        {"entry": ("pending",), "join": ("jp", "jc"), "outside": ()},
        {"entry": (("join", ("pending", "context")), ("outside", ())),
         "outside": (("join", ("pending", "context")),)}, contexts=("jc",))
    facts = _facts(graph, interface, scope=("entry", "join"))
    assert facts.pending == _ids("pending")
    assert facts.context == _ids("context")


@pytest.mark.parametrize("dominated", [False, True])
def test_fresh_pack_requires_producer_in_slice_and_entry_dominance(dominated):
    graph, interface = _graph(
        {"entry": ("pending",), "body": (), "outside": ()},
        {"entry": (("body", ()),), "body": (("outside", ()),)},
        packs={"body": ("local.pack",), "outside": ("external.pack",)})
    dominators = {BlockID("body"): {BlockID("body")} | ({interface.entry} if dominated else set()),
                  BlockID("outside"): {interface.entry, BlockID("outside")}}
    facts = _facts(graph, interface, scope=("entry", "body"), dominators=dominators)
    assert facts.fresh == (_ids("local.pack") if dominated else frozenset())


def test_invoke_uses_forward_but_completion_results_are_not_copies_or_fresh():
    graph, interface = _graph(
        {"entry": ("pending",), "normal": ("np", "nc", "produced.n"),
         "raise": ("rp", "rc", "produced.r")},
        {"entry": (("normal", ("pending", "context", CompletionResult(0))),
                   ("raise", ("pending", "context", CompletionResult(0))))},
        contexts=("nc", "rc"), invokes=("entry",))
    facts = _facts(graph, interface)
    assert facts.pending == _ids("pending", "np", "rp")
    assert facts.context == _ids("context", "nc", "rc")
    assert facts.fresh == frozenset()


def test_pending_payload_projection_is_not_a_copy():
    graph, interface = _graph({"entry": ("pending",), "projected": ("projection",)},
        {"entry": (("projected", (PendingPayload(),)),)}, dispatches=("entry",))
    assert _facts(graph, interface).pending == _ids("pending")


def test_nested_cleanup_anchors_and_freshness_remain_relative_to_each_entry():
    graph, outer = _graph(
        {"entry": ("pending",), "inner": ("inner.pending", "outer.context"),
         "after": ("outer.pending", "restored.context", "replacement", "inner.saved")},
        {"entry": (("inner", ("pending", "context")),),
         "inner": (("after", ("inner.pending", "outer.context", "inner.new", "inner.context")),)},
        contexts=("outer.context", "restored.context", "inner.saved"),
        packs={"entry": ("outer.new",), "inner": ("inner.new",)},
        inner=("inner", "inner", "inner.pending", "inner.context"))
    outer_facts = _facts(graph, outer)
    assert outer_facts.pending == _ids("pending", "inner.pending", "outer.pending")
    assert outer_facts.context == _ids("context", "outer.context", "restored.context")
    assert outer_facts.fresh == _ids("outer.new", "inner.new", "replacement")
    inner = graph.cleanup_interfaces[1]
    inner_facts = _facts(graph, inner, scope=("inner",))
    assert inner_facts.pending == _ids("inner.pending")
    assert inner_facts.context == _ids("inner.context")
    assert inner_facts.fresh == _ids("inner.new")


def test_results_are_immutable_and_canonical_record_order_does_not_change_facts():
    graph, interface = _graph({"entry": ("pending",), "body": ("bp", "bc")},
        {"entry": (("body", ("pending", "context")),)}, contexts=("bc",))
    facts = _facts(graph, interface)
    reordered = replace(graph, operations=tuple(reversed(graph.operations)),
                        values=tuple(reversed(graph.values)),
                        regions=(replace(graph.regions[0], blocks=tuple(reversed(graph.regions[0].blocks))),))
    assert _facts(reordered, interface) == facts
    assert isinstance(facts, CleanupForwardFacts)
    assert all(isinstance(value, frozenset) for value in (facts.slice_blocks, facts.pending, facts.context, facts.fresh))
    with pytest.raises(FrozenInstanceError):
        facts.pending = frozenset()
