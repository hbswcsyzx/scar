"""Independent demand-budget and context-restoration counterexamples for S0."""
from collections import Counter
import json

import pytest

import scar.analysis.program_inventory as inventory_module
from scar.analysis.program_context_store import PreparedContextStore
from scar.analysis.program_inventory import ProgramInventory, inventory_program
from scar.analysis.program_lowering import PreparedSource
from scar.ir.ids import CodeID
from scar.ir.program.expansion import BodyDemandKind
from scar.ir.program.inventory import BodyStatus


def _write(root, name, text):
    path = root / name
    path.write_text(text, encoding="utf-8")
    return path


def _trace(root, source, name):
    line = next(index for index, text in enumerate(source.read_text().splitlines(), 1)
                if text.startswith(f"def {name}("))
    trace = root / "events.jsonl"
    trace.write_text(json.dumps({
        "kind": "python_call",
        "code_id": CodeID(str(source), name, line, None, "unknown").key(),
        "metadata": {"process_id": 1},
    }) + "\n", encoding="utf-8")
    return trace


def _run(root, source, trace, **limits):
    return inventory_program(source, project_root=root, source_roots=(root,),
                             runtime_trace=trace, **limits)


def _tasks(result):
    names = {definition.id: (file.snapshot.path, definition.qualname)
             for file in result.files for definition in file.definitions}
    return {names[entry.definition]: entry for entry in result.expansion.entries}


def test_unobserved_import_call_cannot_spend_the_observed_demand_witness_first(tmp_path):
    entry = _write(tmp_path, "entry.py", """\
from z_dependency import target
def unrelated(value):
    return target(value)
def observed(value):
    return target(value)
""")
    dependency = _write(tmp_path, "z_dependency.py", "def target(value):\n    return value\n")
    result = _run(tmp_path, entry, _trace(tmp_path, entry, "observed"),
                  max_lowered_bodies=2, max_call_witnesses=1)

    tasks = _tasks(result)
    assert tasks[(str(entry), "observed")].attempted
    assert tasks[(str(dependency), "target")].kind is BodyDemandKind.CANDIDATE_CALL
    assert tasks[(str(dependency), "target")].attempted
    assert not tasks[(str(entry), "unrelated")].attempted


def test_unobserved_import_call_cannot_starve_a_later_local_target(tmp_path):
    entry = _write(tmp_path, "entry.py", """\
from z_dependency import imported
def unrelated(value):
    return imported(value)
def observed(value):
    return target(value)
def target(value):
    return value
""")
    _write(tmp_path, "z_dependency.py", "def imported(value):\n    return value\n")
    result = _run(tmp_path, entry, _trace(tmp_path, entry, "observed"),
                  max_lowered_bodies=2, max_call_witnesses=1)

    tasks = _tasks(result)
    assert tasks[(str(entry), "observed")].attempted
    assert tasks[(str(entry), "target")].kind is BodyDemandKind.CANDIDATE_CALL
    assert tasks[(str(entry), "target")].attempted
    assert not tasks[(str(entry), "unrelated")].attempted
    assert sum(len(call.candidate_witnesses) for file in result.files for call in file.calls) == 1
    assert all(operation.callee is None for file in result.files for body in file.bodies
               if body.graph is not None for operation in body.graph.operations)


def test_alternating_candidate_restores_are_bounded_by_attempts_without_repreparing(tmp_path, monkeypatch):
    # Imported edges are indexed before execution, while each local edge is
    # discovered by root-only lowering. Alternating them exposes restore churn.
    count = 5
    a_source = "import b\n" + "".join(
        f"def a{index}(value):\n    return local_a{index}(value)\n"
        f"def local_a{index}(value):\n    return b.b{index}(value)\n"
        for index in range(count)
    )
    b_source = "import a\n" + "".join(
        f"def b{index}(value):\n    return local_b{index}(value)\n"
        f"def local_b{index}(value):\n    return "
        + (f"a.a{index + 1}(value)\n" if index + 1 < count else "value\n")
        for index in range(count)
    )
    entry = _write(tmp_path, "a.py", a_source)
    other = _write(tmp_path, "b.py", b_source)
    restored, prepared = Counter(), Counter()
    original_get = PreparedContextStore.get
    original_prepare = inventory_module.prepare_source

    def counted_get(self, path):
        restored[str(path)] += 1
        return original_get(self, path)

    def counted_prepare(path, *args, **kwargs):
        prepared[str(path)] += 1
        return original_prepare(path, *args, **kwargs)

    monkeypatch.setattr(PreparedContextStore, "get", counted_get)
    monkeypatch.setattr(inventory_module, "prepare_source", counted_prepare)
    result = _run(tmp_path, entry, _trace(tmp_path, entry, "a0"), max_lowered_bodies=20)

    attempts = sum(item.attempted for item in result.expansion.entries)
    assert attempts == 20
    assert all(item.kind is not BodyDemandKind.REMAINDER for item in result.expansion.entries)
    assert sum(restored.values()) <= attempts
    assert prepared == Counter({file.snapshot.path: 1 for file in result.files})
    # Keep the actual restore cost visible: the single-context scheduler needs
    # five visits per file here; it does not promise three visits per file.
    assert restored == Counter({str(entry): 5, str(other): 5})


def test_restore_uses_sealed_source_and_replay_rejects_later_disk_drift(tmp_path, monkeypatch):
    entry = _write(tmp_path, "entry.py", "def observed(value):\n    return value\n")
    trace = _trace(tmp_path, entry, "observed")
    original = PreparedContextStore.put

    def change_disk_after_put(self, context):
        original(self, context)
        entry.write_text("def observed(value):\n    return changed_global(value)\n", encoding="utf-8")

    monkeypatch.setattr(PreparedContextStore, "put", change_disk_after_put)
    result = _run(tmp_path, entry, trace, max_lowered_bodies=1)
    file = result.files[0]
    assert file.bodies[0].graph is not None
    assert not file.calls
    assert not file.bodies[0].metadata.call_targets
    assert result.expansion.entries[0].source.fingerprint == file.snapshot.fingerprint
    monkeypatch.setattr(PreparedContextStore, "put", original)
    with pytest.raises(ValueError, match="replay"):
        ProgramInventory.from_dict(result.to_dict())


def test_unknown_body_failure_consumes_remaining_operation_allowance(tmp_path, monkeypatch):
    entry = _write(tmp_path, "entry.py", """\
def observed(value):
    return value
def remainder(value):
    return value
""")
    trace = _trace(tmp_path, entry, "observed")
    original = PreparedSource.lower
    calls = []

    def fail_after_work(self, name, **options):
        calls.append(name)
        original(self, name, **options)
        raise ValueError("review: failed after operations were constructed")

    monkeypatch.setattr(PreparedSource, "lower", fail_after_work)
    result = _run(tmp_path, entry, trace, max_lowered_bodies=2, max_operations=100)
    observed = result.expansion.entries[0]
    assert observed.attempted and observed.status is BodyStatus.UNSUPPORTED
    assert observed.construction_cost_known is False
    assert observed.operation_budget_charged == 100
    assert not result.expansion.entries[1].attempted
    assert calls == ["observed"]
