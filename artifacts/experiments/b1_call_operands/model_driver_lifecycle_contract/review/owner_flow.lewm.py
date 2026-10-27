"""Bounded stdlib design probe for owner-indexed terminal-history must facts.

This is an ephemeral transfer-equation harness, not another ProgramGraph or a
producer/state store. It neither imports nor changes product code.
"""
from dataclasses import dataclass
from itertools import product
from pathlib import Path
import json
import random
import sys


@dataclass(frozen=True)
class Facts:
    groups: tuple[tuple[str, ...], ...]
    proofs: tuple[tuple[str, tuple[str, ...]], ...]

    def group(self, name):
        return next(group for group in self.groups if name in group)

    def proof(self, name):
        return frozenset(dict(self.proofs)[name])


def facts(groups, proofs):
    groups = tuple(sorted(tuple(sorted(group)) for group in groups if group))
    normalized = {}
    for group in groups:
        proof = frozenset().union(*(proofs.get(name, frozenset()) for name in group))
        normalized.update((name, tuple(sorted(proof))) for name in group)
    return Facts(groups, tuple(sorted(normalized.items())))


def empty(names):
    return facts(((name,) for name in names), {})


def join(states):
    states = tuple(state for state in states if state is not None)
    if not states:
        return None  # unreachable bottom, never a source of terminal evidence
    names = tuple(name for name, _ in states[0].proofs)
    grouped = {}
    for name in names:
        signature = tuple(state.group(name) for state in states)
        grouped.setdefault(signature, []).append(name)
    proofs = {}
    for name in names:
        incoming = tuple(state.proof(name) for state in states)
        proofs[name] = frozenset().union(*incoming) if all(incoming) else frozenset()
    return facts(grouped.values(), proofs)


def assign(state, assignments):
    """Simultaneously redefine target names, using only the pre-edge snapshot."""
    if state is None:
        return None
    grouped, proofs = {}, {}
    for name, old_proof in state.proofs:
        source = assignments.get(name, name)
        key = ("unknown", name) if source is None else ("copy", state.group(source))
        grouped.setdefault(key, []).append(name)
        proofs[name] = frozenset() if source is None else state.proof(source)
    return facts(grouped.values(), proofs)


def terminal(state, owner, anchor):
    if state is None:
        return None
    proofs = {name: frozenset(proof) for name, proof in state.proofs}
    for alias in state.group(owner):
        proofs[alias] = frozenset((anchor,))
    return facts(state.groups, proofs)


def release_allowed(state, owner):
    return state is not None and bool(state.proof(owner))


def solve(initial, predecessors, node_transfer):
    """Small forward must worklist; no producer graph and no configuration set."""
    ins = {name: None for name in predecessors}
    outs = dict(ins)
    updates = 0
    while True:
        changed = False
        for node, incoming in predecessors.items():
            states = [initial] if node == "entry" else []
            states.extend(assign(outs[parent], mapping) for parent, mapping in incoming)
            new_in = join(states)
            new_out = node_transfer.get(node, lambda value: value)(new_in)
            if new_in != ins[node] or new_out != outs[node]:
                ins[node], outs[node] = new_in, new_out
                changed = True
                updates += 1
                assert updates < 10000, "finite equation system must converge"
        if not changed:
            return ins, outs, updates


def scenario_checks():
    result = {}
    names = ("x", "y", "z", "p", "q")
    base = empty(names)
    left = terminal(base, "x", "return_A")
    right = terminal(base, "y", "raise_B")
    shared = join((assign(left, {"p": "x"}), assign(right, {"p": "y"})))
    assert release_allowed(shared, "p")
    assert shared.proof("p") == frozenset(("return_A", "raise_B"))
    result["different_anchors_shared_release"] = sorted(shared.proof("p"))

    swapped = join((assign(left, {"p": "y", "q": "x"}),
                    assign(right, {"p": "x", "q": "y"})))
    assert not release_allowed(swapped, "p")
    assert release_allowed(swapped, "q")
    result["owner_source_cross_swap"] = {"p": False, "q": True}

    alias = assign(base, {"p": "x", "q": "x"})
    alias = terminal(alias, "p", "finish")
    assert all(release_allowed(alias, name) for name in ("x", "p", "q"))
    reset = assign(alias, {"x": None})
    assert not release_allowed(reset, "x") and release_allowed(reset, "p") and release_allowed(reset, "q")
    result["alias_carriers_and_result_redefinition"] = {"new_x": False, "old_p": True, "old_q": True}

    simultaneous = assign(left, {"x": "y", "y": "x"})
    assert not release_allowed(simultaneous, "x") and release_allowed(simultaneous, "y")
    result["simultaneous_phi_swap"] = {"x": False, "y": True}

    polluted = join((assign(left, {"p": "x"}), assign(base, {"p": "x"})))
    assert not release_allowed(polluted, "p")
    result["one_unfinished_incoming"] = False

    # Unknown helper may change every world and drop references; it cannot undo
    # an actual historical terminal event under the chosen no-reactivation profile.
    callback = assign(left, {"z": None})
    regate = assign(callback, {"p": "x"})
    assert release_allowed(regate, "p") and not release_allowed(regate, "z")
    assert release_allowed(regate, "p")  # repeated/idempotent attempts consume no fact
    result["unknown_write_regate_repeated_release"] = {"p_twice": [True, True], "unknown_result_z": False}

    suspend = base  # does not seed terminal history, unlike terminal/no-body finish
    assert not release_allowed(suspend, "x")
    result["suspend_is_not_a_terminal_seed"] = False

    topology = {"entry": (), "loop": (("entry", {"p": "x"}), ("loop", {"p": "p"})),
                "exit": (("loop", {"q": "p"}),)}
    ins, outs, count = solve(base, topology, {})
    assert not release_allowed(outs["exit"], "q")
    result["reachable_loop_without_terminal_seed"] = {"allowed": False, "updates": count}
    ins, outs, count = solve(base, topology, {"entry": lambda state: terminal(state, "x", "seed")})
    assert release_allowed(outs["loop"], "p") and release_allowed(outs["exit"], "q")
    result["seeded_loop"] = {"allowed": True, "updates": count}
    ins, outs, count = solve(base, topology, {"loop": lambda state: terminal(assign(state, {"p": None}), "p", "visit")})
    assert not release_allowed(ins["loop"], "p")
    assert release_allowed(outs["loop"], "p")
    result["loop_static_id_forget_then_reseed"] = {"before_commit": False, "after_commit": True, "updates": count}

    ins, outs, count = solve(base, {"entry": (), "dead": (("dead", {}),)}, {})
    assert outs["dead"] is None and not release_allowed(outs["dead"], "x")
    result["unreachable_cycle_is_not_vacuous_terminal_proof"] = {"reachable": False, "allowed": False}
    return result


# A finite concrete oracle checks only alias/history transfer soundness. Different
# object numbers are concrete identities here; abstract different groups do NOT
# mean proved disequality. Each concrete history stores (object, static anchor).
NAMES = ("x", "y", "z")
ANCHORS = ("a", "b")


def alpha(concretes):
    grouped = {}
    for index, name in enumerate(NAMES):
        grouped.setdefault(tuple(mapping[index] for mapping, history in concretes), []).append(name)
    proofs = {}
    for index, name in enumerate(NAMES):
        incoming = [frozenset(anchor for obj, anchor in history if obj == mapping[index])
                    for mapping, history in concretes]
        proofs[name] = frozenset().union(*incoming) if all(incoming) else frozenset()
    return facts(grouped.values(), proofs)


def concrete_assign(concretes, mapping):
    expanded = []
    for refs, history in concretes:
        source = dict(zip(NAMES, refs))
        choices = [(0, 1, 2, 3) if mapping.get(name, name) is None else (source[mapping.get(name, name)],)
                   for name in NAMES]
        expanded.extend((values, history) for values in product(*choices))
    return expanded


def concrete_terminal(concretes, owner, anchor):
    index = NAMES.index(owner)
    return [(refs, history | frozenset(((refs[index], anchor),))) for refs, history in concretes]


def sound(abstract, concretes):
    for group in abstract.groups:
        indices = [NAMES.index(name) for name in group]
        assert all(len({refs[index] for index in indices}) == 1 for refs, history in concretes)
    for index, name in enumerate(NAMES):
        proof = abstract.proof(name)
        if proof:
            assert all(any((refs[index], anchor) in history for anchor in proof)
                       for refs, history in concretes)


def oracle_checks():
    pairs = tuple(product(range(3), ANCHORS))
    histories = [frozenset(pair for index, pair in enumerate(pairs) if bits & (1 << index))
                 for bits in range(1 << len(pairs))]
    pool = tuple((refs, history) for refs in product(range(3), repeat=3) for history in histories)
    rng = random.Random(20261018)
    checks = 0
    operations = (
        (lambda state: terminal(state, "x", "a"), lambda states: concrete_terminal(states, "x", "a")),
        (lambda state: terminal(state, "y", "b"), lambda states: concrete_terminal(states, "y", "b")),
        (lambda state: assign(state, {"x": "y", "y": "x"}), lambda states: concrete_assign(states, {"x": "y", "y": "x"})),
        (lambda state: assign(state, {"z": "x"}), lambda states: concrete_assign(states, {"z": "x"})),
        (lambda state: assign(state, {"x": None}), lambda states: concrete_assign(states, {"x": None})),
        (lambda state: state, lambda states: states),
    )
    for _ in range(320):
        concretes = rng.sample(pool, rng.randrange(1, 5))
        abstract = alpha(concretes)
        for transform, oracle in operations:
            sound(transform(abstract), oracle(concretes))
            checks += 1
    return {"sampled_concrete_groups": 320, "sound_transfer_checks": checks,
            "seed": 20261018, "concrete_pool_size": len(pool)}


def main():
    output = {"python": sys.version, "scenarios": scenario_checks(), "bounded_oracle": oracle_checks(),
              "scope": "design transfer probe only; no product/runtime/source claim"}
    rendered = json.dumps(output, indent=2, sort_keys=True)
    Path(__file__).with_suffix(".json").write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
