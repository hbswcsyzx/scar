"""Private context boundaries and global-construction accounting invariants."""
import json
import stat

import pytest

from scar.analysis.program_context_store import ContextStoreLimit, PreparedContextStore
from scar.analysis.program_inventory import inventory_program
from scar.analysis.program_lowering import PreparedSource, prepare_source
from scar.ir.ids import CodeID
from scar.ir.program.expansion import BodyDemandKind, ContextStoreBudget
from scar.ir.program.inventory import BodyStatus


def _trace(path, source_names):
    rows = []
    for index, (source, name, line) in enumerate(source_names):
        rows.append({"kind":"python_call", "index":index, "invocation_id":index,
                     "code_id":CodeID(str(source), name, line, None, "unknown").key(),
                     "metadata":{"process_id":7}})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


@pytest.mark.parametrize("values", ({"max_compressed_bytes":True}, {"max_record_bytes":0},
                                   {"max_record_bytes":-1}, {"max_compressed_bytes":1.0}))
def test_context_limits_reject_nonpositive_and_noninteger_values(values):
    with pytest.raises(ValueError):
        ContextStoreBudget(**values)


def test_context_permissions_snapshot_integrity_and_no_source_reread(tmp_path):
    source = tmp_path / "program.py"
    source.write_text("def value(x):\n    return x\n")
    context = prepare_source(source, project_root=tmp_path)
    with PreparedContextStore() as store:
        assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700
        store.put(context)
        cache_file, = store.directory.iterdir()
        assert stat.S_IMODE(cache_file.stat().st_mode) == 0o600
        source.write_text("# now changed\n")
        restored = store.get(source)
        assert restored.text == context.text
        assert restored.semantics.sources[str(source)] == context.semantics.sources[str(source)]
        assert restored.lower("value").graph is not None
        with pytest.raises(ValueError, match="already stored"):
            store.put(context)
    assert not store.directory.exists()


def test_context_tampering_is_rejected_before_unpickling(tmp_path, monkeypatch):
    import scar.analysis.program_context_store as module
    source = tmp_path / "program.py"
    source.write_text("def value(x):\n    return x\n")
    context = prepare_source(source, project_root=tmp_path)
    with PreparedContextStore() as store:
        store.put(context)
        cache_file, = store.directory.iterdir()
        cache_file.write_bytes(b"changed")
        def forbidden(*args, **kwargs):
            pytest.fail("corrupted scratch must not reach pickle.load")
        monkeypatch.setattr(module.pickle, "load", forbidden)
        with pytest.raises(ValueError, match="digest"):
            store.get(source)


def test_raw_record_limit_cleans_partial_file_without_refunding_writes(tmp_path):
    source = tmp_path / "program.py"
    source.write_text("def value(x):\n    return x\n")
    context = prepare_source(source, project_root=tmp_path)
    with PreparedContextStore(ContextStoreBudget(max_record_bytes=1)) as store:
        with pytest.raises(ContextStoreLimit, match="uncompressed"):
            store.put(context)
        assert not list(store.directory.iterdir())
        previous = store.compressed_bytes_written
        assert previous > 0
        with pytest.raises(ContextStoreLimit):
            store.put(context)
        assert previous < store.compressed_bytes_written <= store.budget.max_compressed_bytes


def test_single_root_lowering_cannot_consume_other_observed_root_budget(tmp_path):
    first = tmp_path / "a.py"
    second = tmp_path / "z.py"
    first.write_text("import z\ndef observed(x):\n    return child(x)\ndef child(x):\n    return x\n")
    second.write_text("def observed(x):\n    return x\n")
    trace = _trace(tmp_path / "events.jsonl", ((first,"observed",2),(second,"observed",1)))
    result = inventory_program(first, project_root=tmp_path, runtime_trace=trace,
                               max_lowered_bodies=2, max_operations=12)
    attempted = [e for e in result.expansion.entries if e.attempted]
    assert len(attempted) == 2
    assert all(e.kind is BodyDemandKind.OBSERVED_CODE for e in attempted)
    assert all(e.status is BodyStatus.LOWERED_WITH_GAPS for e in attempted)
    for file in result.files:
        for body in file.bodies:
            if body.graph is not None:
                assert len(body.graph.regions) == 1
    assert len([a for a in result.runtime_scope.definition_index if a.core_region]) == 2
    assert sum(e.operation_budget_charged for e in attempted) <= 12


def test_unreported_lowering_exception_consumes_remaining_operation_allowance(tmp_path, monkeypatch):
    source = tmp_path / "entry.py"
    source.write_text("def observed(x):\n    return x\ndef later(x):\n    return x\n")
    trace = _trace(tmp_path / "events.jsonl", ((source,"observed",1),))
    original = PreparedSource.lower
    def fail_after_work(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise ValueError("injected lost construction result")
    monkeypatch.setattr(PreparedSource, "lower", fail_after_work)
    result = inventory_program(source, project_root=tmp_path, runtime_trace=trace,
                               max_operations=9, max_lowered_bodies=2)
    first, later = result.expansion.entries
    assert first.attempted and first.status is BodyStatus.UNSUPPORTED
    assert first.operation_budget_charged == 9 and not first.construction_cost_known
    assert not later.attempted
    assert result.summary()["expansion"]["unknown_construction_costs"] == 1


def test_later_context_failure_keeps_previously_emitted_body_and_core_link(tmp_path, monkeypatch):
    first = tmp_path / "a.py"
    second = tmp_path / "z.py"
    first.write_text("import z\ndef observed(x):\n    return x\ndef remainder(x):\n    return x\n")
    second.write_text("def observed(x):\n    return x\n")
    trace = _trace(tmp_path / "events.jsonl", ((first,"observed",2),(second,"observed",1)))
    original = PreparedContextStore.get
    seen = 0
    def fail_on_second_load(self, path):
        nonlocal seen
        if str(path) == str(first):
            seen += 1
            if seen > 1:
                raise ValueError("injected second load failure")
        return original(self, path)
    monkeypatch.setattr(PreparedContextStore, "get", fail_on_second_load)
    result = inventory_program(first, project_root=tmp_path, runtime_trace=trace)
    assert len([a for a in result.runtime_scope.definition_index if a.core_region]) == 2
    file = next(f for f in result.files if f.snapshot.path == str(first))
    names = {d.id:d.name for d in file.definitions}
    assert {names[b.definition]:b.status for b in file.bodies} == {
        "observed":BodyStatus.LOWERED_WITH_GAPS, "remainder":BodyStatus.UNSUPPORTED}
