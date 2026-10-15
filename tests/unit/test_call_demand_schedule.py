"""D1 v6 uses raw calls to order one shared source-body construction queue."""
from __future__ import annotations

import importlib
import sys

from scar.analysis.call_demand import inventory_from_calls
from scar.analysis.program_lowering import PreparedSource
from scar.ir.program.call_demand import EnteredCallCode, SourceCallCandidate
from scar.ir.program.call_edges import CallEdgeBudget
from scar.ir.program.expansion import ContextStoreBudget
from scar.ir.program.inventory import BodyStatus, InventoryBudget
from scar.trace.call_edges import CallEdgeRecorder


def _record_actual_run(root, trace):
    """Run the tiny fixture under the repository's real call recorder."""
    names = ("entry", "m_caller", "a_callee", "b_unrelated")
    for name in names:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(root))
    recorder = CallEdgeRecorder(trace, root)
    previous = sys.getprofile()
    try:
        sys.setprofile(recorder.profile)
        importlib.import_module("entry")
        importlib.import_module("b_unrelated").noise(object())
    finally:
        sys.setprofile(previous)
        recorder.close()
        sys.path.remove(str(root))
        for name in names:
            sys.modules.pop(name, None)
    return trace


def _fixture(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    # Callee sorts before caller; source dependency, not pathname, must order
    # the two bodies. The unrelated module is observed but outside that chain.
    (root / "entry.py").write_text(
        "from m_caller import caller\ncaller(object())\n", encoding="utf-8")
    (root / "m_caller.py").write_text(
        "from a_callee import leaf\n"
        "def caller(value):\n    return leaf(value)\n", encoding="utf-8")
    (root / "a_callee.py").write_text(
        "def leaf(value):\n    return value\n", encoding="utf-8")
    (root / "b_unrelated.py").write_text(
        "def noise(value):\n    return value\n", encoding="utf-8")
    trace = _record_actual_run(root, tmp_path / "trace")
    return root, root / "entry.py", trace


def _inventory(entry, root, trace, *, lowered=8, operations=1000):
    budget = InventoryBudget(max_lowered_bodies=lowered, max_operations=operations)
    return inventory_from_calls(entry, project_root=root, source_roots=(root,), budget=budget,
        call_trace=trace, call_budget=CallEdgeBudget(), context_budget=ContextStoreBudget())


def _named_entries(result):
    definitions = {definition.id: (file.snapshot.path, definition.qualname)
                   for file in result.files for definition in file.definitions}
    return [(definitions[item.definition], item) for item in result.expansion.entries]


def test_entry_dependency_frontier_precedes_unrelated_entered_seed_despite_paths(tmp_path):
    root, entry, trace = _fixture(tmp_path)

    result = _inventory(entry, root, trace, lowered=2)

    entries = _named_entries(result)
    assert [identity[1] for identity, task in entries[:2]] == ["caller", "leaf"]
    assert all(task.attempted and task.status is BodyStatus.LOWERED_WITH_GAPS
               for _, task in entries[:2])
    unrelated = next(task for identity, task in entries if identity == (str(root / "b_unrelated.py"), "noise"))
    assert not unrelated.attempted
    assert len(result.expansion.entry_roots) == 1
    assert result.expansion.entry_roots[0].snapshot.path == str(entry)
    assert all(root.initializer not in {task.definition for task in result.expansion.entries}
               for root in result.expansion.entry_roots)


def test_entered_and_source_candidate_origins_share_one_body_task(tmp_path):
    root, entry, trace = _fixture(tmp_path)

    result = _inventory(entry, root, trace, lowered=8)

    entries = _named_entries(result)
    caller_tasks = [task for identity, task in entries if identity == (str(root / "m_caller.py"), "caller")]
    leaf_tasks = [task for identity, task in entries if identity == (str(root / "a_callee.py"), "leaf")]
    assert len(caller_tasks) == len(leaf_tasks) == 1
    caller, leaf = caller_tasks[0], leaf_tasks[0]
    assert caller.attempted and leaf.attempted
    assert any(type(origin) is EnteredCallCode for origin in caller.origins)
    assert any(type(origin) is SourceCallCandidate for origin in caller.origins)
    assert any(type(origin) is EnteredCallCode for origin in leaf.origins)
    assert any(type(origin) is SourceCallCandidate for origin in leaf.origins)
    assert len({task.definition for task in result.expansion.entries}) == len(result.expansion.entries)


def test_transitive_imported_module_initializer_candidates_join_entry_frontier(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    entry = root / "entry.py"
    (root / "entry.py").write_text("import m_bridge\n", encoding="utf-8")
    (root / "m_bridge.py").write_text(
        "from a_leaf import leaf\nleaf(object())\n", encoding="utf-8")
    (root / "a_leaf.py").write_text("def leaf(value):\n    return value\n", encoding="utf-8")
    (root / "b_unrelated.py").write_text("def noise(value):\n    return value\n", encoding="utf-8")
    trace = _record_actual_run(root, tmp_path / "trace")

    result = _inventory(entry, root, trace, lowered=1)

    entries = _named_entries(result)
    assert entries[0][0] == (str(root / "a_leaf.py"), "leaf")
    assert entries[0][1].attempted
    assert any(type(origin) is SourceCallCandidate for origin in entries[0][1].origins)
    unrelated = next(task for identity, task in entries if identity == (str(root / "b_unrelated.py"), "noise"))
    assert not unrelated.attempted
    # Imported initializer scopes are source frontiers, not fake EntryRoots.
    assert tuple(item.snapshot.path for item in result.expansion.entry_roots) == (str(entry),)


def test_unreported_lowering_failure_charges_remaining_operation_budget(tmp_path, monkeypatch):
    root, entry, trace = _fixture(tmp_path)
    original = PreparedSource.lower

    def lose_result(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise ValueError("injected lost construction result")

    monkeypatch.setattr(PreparedSource, "lower", lose_result)
    result = _inventory(entry, root, trace, lowered=1, operations=13)

    first = result.expansion.entries[0]
    assert first.attempted and first.status is BodyStatus.UNSUPPORTED
    assert first.construction_operations == 0
    assert first.operation_budget_charged == 13
    assert not first.construction_cost_known
    assert sum(task.attempted for task in result.expansion.entries) == 1
    assert all(not task.attempted for task in result.expansion.entries[1:])


def test_restore_failure_keeps_indexed_child_candidate_and_other_file_body(tmp_path, monkeypatch):
    from scar.analysis.program_context_store import PreparedContextStore

    root, entry, trace = _fixture(tmp_path)
    original = PreparedContextStore.get
    caller_path = str(root / "m_caller.py")
    calls = 0

    def fail_caller_body_restore(store, path):
        nonlocal calls
        if str(path) == caller_path:
            calls += 1
            # The first restore supplies the full inventory. The next is the
            # actual body-lowering input and simulates scratch corruption.
            if calls == 2:
                raise OSError("injected body-context restore failure")
        return original(store, path)

    monkeypatch.setattr(PreparedContextStore, "get", fail_caller_body_restore)
    result = _inventory(entry, root, trace, lowered=2)

    entries = _named_entries(result)
    caller = next(task for identity, task in entries if identity == (caller_path, "caller"))
    leaf = next(task for identity, task in entries if identity == (str(root / "a_callee.py"), "leaf"))
    assert caller.attempted and caller.status is BodyStatus.UNSUPPORTED
    assert caller.operation_budget_charged == 0 and caller.construction_cost_known
    assert leaf.attempted and leaf.status is BodyStatus.LOWERED_WITH_GAPS
    assert any(type(origin) is SourceCallCandidate for origin in leaf.origins)
    assert any(item.path == caller_path for item in result.expansion.unavailable_contexts)


def test_remainder_origin_is_not_kept_when_a_pending_body_gets_a_call_source(tmp_path):
    from scar.analysis.call_demand_schedule import CallDemandQueue
    from scar.ir.program.call_demand import Remainder
    from scar.ir.program.inventory import DefinitionKind, DefinitionInventory
    from scar.ir.semantics_v2 import SourceSnapshot
    from scar.ir.v2.common import SourceReference
    from scar.ir.v2.ids import OperationDefinitionID, SourceAtomID

    snapshot = SourceSnapshot("/project/m.py", "sha256:" + "a" * 64)
    source = SourceReference(SourceAtomID("atom"), snapshot.path, snapshot.fingerprint, 1, 1, 0, 1)
    definition = DefinitionInventory(OperationDefinitionID("fn"), source, "fn", "fn",
                                     DefinitionKind.FUNCTION, None)
    queue = CallDemandQueue({definition.id: definition})
    task = queue.add_remainder(definition.id)
    queue.add(definition.id, CallDemandQueue.ENTRY, SourceCallCandidate(OperationDefinitionID("call")))
    assert task.origins == [SourceCallCandidate(OperationDefinitionID("call"))]
    assert Remainder() not in task.origins
    popped = queue.pop()
    assert popped is task and popped.priority == CallDemandQueue.ENTRY


def test_distinct_process_seed_origins_remain_distinct_on_one_task():
    from scar.analysis.call_demand_schedule import CallDemandQueue
    from scar.ir.program.inventory import DefinitionKind, DefinitionInventory
    from scar.ir.program.expansion import ContextStoreBudget
    from scar.ir.semantics_v2 import SourceSnapshot
    from scar.ir.v2.common import SourceReference
    from scar.ir.v2.ids import OperationDefinitionID, SourceAtomID

    snapshot = SourceSnapshot("/project/m.py", "sha256:" + "a" * 64)
    source = SourceReference(SourceAtomID("atom"), snapshot.path, snapshot.fingerprint, 1, 1, 0, 1)
    definition = DefinitionInventory(OperationDefinitionID("fn"), source, "fn", "fn",
                                     DefinitionKind.FUNCTION, None)
    queue = CallDemandQueue({definition.id: definition})
    code = "pycode-v2:" + "c" * 64
    queue.add(definition.id, CallDemandQueue.OBSERVED, EnteredCallCode(7, code))
    queue.add(definition.id, CallDemandQueue.OBSERVED, EnteredCallCode(8, code))
    task = queue.pop()
    schedule = queue.schedule(ContextStoreBudget(), (), ())

    assert task is not None
    assert len(schedule.entries) == 1
    process_ids = tuple(origin.process_id for origin in schedule.entries[0].origins
                        if type(origin) is EnteredCallCode)
    assert process_ids == (7, 8)
    assert len({task.definition for task in schedule.entries}) == 1
