"""Global body-demand ordering and replay tests.

These fixtures synthesize trace records instead of executing project code. A
CodeID with an unknown digest is a source-selection hint for the scheduler; it
does not assert an exact loaded-code match, callable target, or runtime effect.
"""
from __future__ import annotations

from collections import Counter
import json

import pytest

from scar.analysis.program_inventory import (
    ProgramInventory, _inventory_from_inputs, inventory_program,
)
from scar.analysis.runtime_sources import read_runtime_trace
from scar.ir.ids import CodeID
from scar.ir.program.expansion import BodyDemandKind, ContextStoreBudget
from scar.ir.program.inventory import BodyStatus, InventoryBudget


def _write_trace(path, source, qualname, line):
    row = {
        "kind": "python_call",
        "index": 1,
        "invocation_id": 1,
        "code_id": CodeID(str(source), qualname, line, None, "unknown").key(),
        "metadata": {"process_id": 101, "thread_id": 7},
    }
    path.write_text(json.dumps(row, separators=(",", ":")) + "\n", encoding="utf-8")


def _inventory(entry, root, trace, *, max_lowered_bodies, **kwargs):
    return inventory_program(
        entry,
        project_root=root,
        source_roots=(root,),
        runtime_trace=trace,
        max_lowered_bodies=max_lowered_bodies,
        **kwargs,
    )


def _expansions_by_path_and_name(result):
    definitions = {
        definition.id: (file.snapshot.path, definition.qualname)
        for file in result.files
        for definition in file.definitions
    }
    return {
        definitions[item.definition]: item
        for item in result.expansion.entries
    }


def _write_unused_functions(count):
    return "".join(
        f"def unused_{index:02d}(value):\n    return value\n\n"
        for index in range(count)
    )


def _line_of(path, prefix):
    return next(index for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                if line.startswith(prefix))


def test_early_entry_siblings_do_not_starve_later_observed_definition(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    entry = root / "entry.py"
    later = root / "z_later.py"
    trace = tmp_path / "events.jsonl"
    entry.write_text(
        "from z_later import observed\n\n" + _write_unused_functions(40),
        encoding="utf-8",
    )
    later.write_text("def observed(value):\n    return value\n", encoding="utf-8")
    _write_trace(trace, later, "observed", 1)

    result = _inventory(entry, root, trace, max_lowered_bodies=1)

    scheduled = _expansions_by_path_and_name(result)
    observed = scheduled[(str(later), "observed")]
    assert observed.kind is BodyDemandKind.OBSERVED_CODE
    assert observed.attempted
    assert observed.status is BodyStatus.LOWERED_WITH_GAPS
    unused = [item for (path, name), item in scheduled.items()
              if path == str(entry) and name.startswith("unused_")]
    assert len(unused) == 40
    assert not any(item.attempted for item in unused)
    assert sum(item.attempted for item in result.expansion.entries) == 1


@pytest.mark.parametrize(
    "observed_name,static_name",
    (("a_observed.py", "z_static.py"), ("z_observed.py", "a_static.py")),
)
def test_observed_demand_category_is_stable_when_file_and_definition_order_swap(
    tmp_path, observed_name, static_name,
):
    root = tmp_path / "project"
    root.mkdir()
    entry = root / "entry.py"
    observed_path = root / observed_name
    static_path = root / static_name
    trace = tmp_path / "events.jsonl"
    observed_module = observed_path.stem
    static_module = static_path.stem
    entry.write_text(
        f"from {observed_module} import observed\nimport {static_module}\n",
        encoding="utf-8",
    )
    observed_path.write_text(
        "def ordinary(value):\n    return value\n\n"
        "def observed(value):\n    return value\n",
        encoding="utf-8",
    )
    static_path.write_text("def static_sibling(value):\n    return value\n", encoding="utf-8")
    _write_trace(trace, observed_path, "observed", _line_of(observed_path, "def observed"))

    result = _inventory(entry, root, trace, max_lowered_bodies=1)

    scheduled = _expansions_by_path_and_name(result)
    observed = scheduled[(str(observed_path), "observed")]
    assert observed.kind is BodyDemandKind.OBSERVED_CODE
    assert observed.attempted
    assert sum(item.attempted for item in result.expansion.entries) == 1
    assert all(item.kind is BodyDemandKind.REMAINDER
               for key, item in scheduled.items()
               if key != (str(observed_path), "observed"))


def test_observed_cross_file_call_candidate_gets_next_demand_without_callee_claim(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    entry = root / "entry.py"
    helper = root / "helper.py"
    trace = tmp_path / "events.jsonl"
    entry.write_text(
        "from helper import transform\n\n"
        + _write_unused_functions(20)
        + "def observed(value):\n    return transform(value)\n",
        encoding="utf-8",
    )
    helper.write_text(
        "def transform(value):\n    return value\n\n"
        "def helper_sibling(value):\n    return value\n",
        encoding="utf-8",
    )
    observed_line = _line_of(entry, "def observed")
    _write_trace(trace, entry, "observed", observed_line)

    result = _inventory(entry, root, trace, max_lowered_bodies=2)

    scheduled = _expansions_by_path_and_name(result)
    caller = scheduled[(str(entry), "observed")]
    callee_candidate = scheduled[(str(helper), "transform")]
    assert caller.kind is BodyDemandKind.OBSERVED_CODE and caller.attempted
    assert callee_candidate.kind is BodyDemandKind.CANDIDATE_CALL
    assert callee_candidate.attempted
    assert callee_candidate.via_call is not None
    assert sum(item.attempted for item in result.expansion.entries) == 2
    assert not scheduled[(str(helper), "helper_sibling")].attempted
    assert not any(item.attempted for key, item in scheduled.items()
                   if key[0] == str(entry) and key[1].startswith("unused_"))

    caller_definition = next(definition for file in result.files for definition in file.definitions
                             if definition.id == caller.definition)
    call = next(item for file in result.files for item in file.calls
                if item.execution_owner == caller_definition.id)
    target_definition = next(definition for file in result.files for definition in file.definitions
                             if definition.id == callee_candidate.definition)
    assert target_definition.id in call.candidates
    assert call.candidate_witnesses
    caller_file = next(file for file in result.files if file.snapshot.path == str(entry))
    caller_body = next(body for body in caller_file.bodies if body.definition == caller.definition)
    assert caller_body.graph is not None
    assert all(operation.callee is None for operation in caller_body.graph.operations)
    assert result.summary()["transformation_authorized"] is False
    assert result.summary()["runtime_reachability_established"] is False
    assert result.summary()["runtime"]["effect_equivalence_established"] is False


def test_unsupported_observed_body_still_consumes_attempt_budget(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    entry = root / "entry.py"
    trace = tmp_path / "events.jsonl"
    entry.write_text(
        "def observed(value):\n"
        "    result = value + 1\n"
        "    try:\n"
        "        return result\n"
        "    except Exception:\n"
        "        return value\n\n"
        "def remainder(value):\n    return value\n",
        encoding="utf-8",
    )
    _write_trace(trace, entry, "observed", 1)

    result = _inventory(entry, root, trace, max_lowered_bodies=1)

    scheduled = _expansions_by_path_and_name(result)
    failed = scheduled[(str(entry), "observed")]
    assert failed.kind is BodyDemandKind.OBSERVED_CODE
    assert failed.attempted
    assert failed.status is BodyStatus.UNSUPPORTED
    assert failed.construction_operations > 0
    assert failed.operation_budget_charged >= failed.construction_operations
    assert failed.construction_cost_known
    assert not scheduled[(str(entry), "remainder")].attempted
    assert sum(item.attempted for item in result.expansion.entries) == 1


def test_context_restore_failure_is_charged_once_and_other_file_keeps_working(
    tmp_path, monkeypatch,
):
    from scar.analysis.program_context_store import PreparedContextStore

    root = tmp_path / "project"
    root.mkdir()
    entry = root / "entry.py"
    helper = root / "helper.py"
    trace = tmp_path / "events.jsonl"
    entry.write_text(
        "def observed_entry(value):\n    return value\n\n"
        "def entry_remainder(value):\n    return value\n",
        encoding="utf-8",
    )
    helper.write_text(
        "def observed_helper(value):\n    return value\n\n"
        "def helper_remainder(value):\n    return value\n",
        encoding="utf-8",
    )
    rows = [
        {"kind": "python_call", "index": 1, "invocation_id": 1,
         "code_id": CodeID(str(entry), "observed_entry", 1, None, "unknown").key(),
         "metadata": {"process_id": 101}},
        {"kind": "python_call", "index": 2, "invocation_id": 2,
         "code_id": CodeID(str(helper), "observed_helper", 1, None, "unknown").key(),
         "metadata": {"process_id": 101}},
    ]
    trace.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
                     encoding="utf-8")

    original_get = PreparedContextStore.get
    calls = Counter()

    def fail_entry_restore(store, path):
        calls[str(path)] += 1
        if str(path) == str(entry):
            raise OSError("injected private context restore failure")
        return original_get(store, path)

    monkeypatch.setattr(PreparedContextStore, "get", fail_entry_restore)
    result = _inventory(entry, root, trace, max_lowered_bodies=2)

    scheduled = _expansions_by_path_and_name(result)
    entry_task = scheduled[(str(entry), "observed_entry")]
    helper_task = scheduled[(str(helper), "observed_helper")]
    assert entry_task.attempted and entry_task.status is BodyStatus.UNSUPPORTED
    assert helper_task.attempted and helper_task.status is BodyStatus.LOWERED_WITH_GAPS
    assert not scheduled[(str(entry), "entry_remainder")].attempted
    assert not scheduled[(str(helper), "helper_remainder")].attempted
    assert calls[str(entry)] == 1
    assert any(item.path == str(entry) for item in result.expansion.unavailable_contexts)
    helper_file = next(file for file in result.files if file.snapshot.path == str(helper))
    assert any(body.definition == helper_task.definition and body.graph is not None
               for body in helper_file.bodies)


def test_v3_schedule_and_source_are_replayed_and_v1_static_inventory_is_unchanged(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    entry = root / "entry.py"
    trace = tmp_path / "events.jsonl"
    entry.write_text(
        "def observed(value):\n    return value\n\n"
        "def remainder(value):\n    return value\n",
        encoding="utf-8",
    )
    _write_trace(trace, entry, "observed", 1)

    static = inventory_program(entry, project_root=root, source_roots=(root,))
    runtime = _inventory(entry, root, trace, max_lowered_bodies=1)

    assert static.to_dict()["schema_version"] == 1
    assert "expansion" not in static.to_dict()
    assert runtime.to_dict()["schema_version"] == 3
    assert "expansion" in runtime.to_dict()
    assert ProgramInventory.from_dict(static.to_dict()).to_dict() == static.to_dict()
    document = runtime.to_dict()
    assert ProgramInventory.from_dict(document).to_dict() == document

    tampered_schedule = json.loads(json.dumps(document))
    tampered_schedule["expansion"]["entries"].reverse()
    with pytest.raises(ValueError):
        ProgramInventory.from_dict(tampered_schedule)

    entry.write_text(entry.read_text() + "\n# changed source\n", encoding="utf-8")
    with pytest.raises((ValueError, OSError)):
        ProgramInventory.from_dict(document)


def test_v2_dispatch_replays_legacy_local_expansion_while_v3_is_root_only(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    entry = root / "entry.py"
    trace = tmp_path / "events.jsonl"
    entry.write_text(
        "def caller(value):\n    return helper(value)\n\n"
        "def helper(value):\n    return value\n",
        encoding="utf-8",
    )
    _write_trace(trace, entry, "caller", 1)
    runtime_trace = read_runtime_trace(trace)
    budget = InventoryBudget(max_lowered_bodies=2)

    legacy_v2 = _inventory_from_inputs(
        entry,
        project_root=root,
        source_roots=(root,),
        budget=budget,
        runtime=runtime_trace,
        global_expansion=False,
    )
    legacy_document = legacy_v2.to_dict()
    assert legacy_document["schema_version"] == 2
    legacy_caller = next(body for file in legacy_v2.files if file.snapshot.path == str(entry)
                         for body in file.bodies
                         if next(definition for definition in file.definitions
                                 if definition.id == body.definition).qualname == "caller")
    assert legacy_caller.graph is not None
    assert len(legacy_caller.graph.regions) > 1
    # This checks schema dispatch to the legacy construction route; it is not
    # a comparison against an independently generated historical artifact.
    assert ProgramInventory.from_dict(legacy_document).to_dict() == legacy_document

    global_v3 = _inventory(entry, root, trace, max_lowered_bodies=2)
    expansions = _expansions_by_path_and_name(global_v3)
    caller_task = expansions[(str(entry), "caller")]
    helper_task = expansions[(str(entry), "helper")]
    caller_body = next(body for file in global_v3.files if file.snapshot.path == str(entry)
                       for body in file.bodies if body.definition == caller_task.definition)
    helper_body = next(body for file in global_v3.files if file.snapshot.path == str(entry)
                       for body in file.bodies if body.definition == helper_task.definition)
    assert global_v3.to_dict()["schema_version"] == 3
    assert caller_body.graph is not None and len(caller_body.graph.regions) == 1
    assert helper_task.kind is BodyDemandKind.CANDIDATE_CALL and helper_task.attempted
    assert helper_body.graph is not None and len(helper_body.graph.regions) == 1


def test_prepared_contexts_are_spooled_once_and_temporary_store_is_removed(tmp_path, monkeypatch):
    import scar.analysis.program_inventory as inventory_module
    from scar.analysis.program_context_store import PreparedContextStore

    root = tmp_path / "project"
    root.mkdir()
    entry = root / "entry.py"
    dependency = root / "dependency.py"
    trace = tmp_path / "events.jsonl"
    entry.write_text("import dependency\ndef entry(value):\n    return value\n", encoding="utf-8")
    dependency.write_text("def helper(value):\n    return value\n", encoding="utf-8")
    _write_trace(trace, entry, "entry", 2)

    original_prepare = inventory_module.prepare_source
    prepared = Counter()

    def counted_prepare(path, *args, **kwargs):
        prepared[str(path)] += 1
        return original_prepare(path, *args, **kwargs)

    stores = []
    original_init = PreparedContextStore.__init__

    def record_store(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        stores.append(self)

    monkeypatch.setattr(inventory_module, "prepare_source", counted_prepare)
    monkeypatch.setattr(PreparedContextStore, "__init__", record_store)

    result = _inventory(
        entry, root, trace, max_lowered_bodies=2,
        context_budget=ContextStoreBudget(),
    )

    assert prepared == Counter({file.snapshot.path: 1 for file in result.files})
    assert len(stores) == 1
    assert stores[0].compressed_bytes_written > 0
    assert not stores[0].directory.exists()


def test_context_store_budget_failure_is_reported_and_cleanup_is_still_complete(tmp_path):
    from scar.analysis.program_context_store import ContextStoreLimit, PreparedContextStore
    from scar.analysis.program_lowering import prepare_source

    root = tmp_path / "project"
    root.mkdir()
    path = root / "module.py"
    path.write_text("def function(value):\n    return value\n", encoding="utf-8")
    context = prepare_source(path, project_root=root)
    store = PreparedContextStore(budget=ContextStoreBudget(max_compressed_bytes=1))
    with pytest.raises(ContextStoreLimit):
        with store:
            directory = store.directory
            store.put(context)
    assert not directory.exists()


def test_inventory_context_budget_failure_is_a_boundary_not_a_partial_body(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    entry = root / "entry.py"
    trace = tmp_path / "events.jsonl"
    entry.write_text(
        "def observed(value):\n    return value\n\n"
        "def remainder(value):\n    return value\n",
        encoding="utf-8",
    )
    _write_trace(trace, entry, "observed", 1)

    result = _inventory(
        entry, root, trace, max_lowered_bodies=2,
        context_budget=ContextStoreBudget(max_compressed_bytes=1),
    )

    unavailable = {item.path for item in result.expansion.unavailable_contexts}
    assert str(entry) in unavailable
    scheduled = _expansions_by_path_and_name(result)
    assert not scheduled[(str(entry), "observed")].attempted
    assert not scheduled[(str(entry), "remainder")].attempted
    assert all(item.status is BodyStatus.NOT_ATTEMPTED
               for key, item in scheduled.items() if key[0] == str(entry))


def test_context_budget_verifier_checks_both_ceiling_dimensions(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    entry = root / "entry.py"
    trace = tmp_path / "events.jsonl"
    entry.write_text("def observed(value):\n    return value\n", encoding="utf-8")
    _write_trace(trace, entry, "observed", 1)
    low = ContextStoreBudget(max_compressed_bytes=8_000_000, max_record_bytes=8_000_000)

    low_report = _inventory(
        entry, root, trace, max_lowered_bodies=1, context_budget=low,
    ).to_dict()
    assert ProgramInventory.from_dict(
        low_report, context_verification_budget=low,
    ).to_dict() == low_report

    for excessive in (
        ContextStoreBudget(max_compressed_bytes=9_000_000, max_record_bytes=8_000_000),
        ContextStoreBudget(max_compressed_bytes=8_000_000, max_record_bytes=9_000_000),
    ):
        report = _inventory(
            entry, root, trace, max_lowered_bodies=1,
            context_budget=excessive,
        ).to_dict()
        with pytest.raises(ValueError, match="independent context verifier budget"):
            ProgramInventory.from_dict(report, context_verification_budget=low)
