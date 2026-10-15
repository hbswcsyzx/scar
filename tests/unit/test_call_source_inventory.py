"""Raw Python execution drives v6 discovery and expansion without a hand graph."""
from copy import deepcopy
from dataclasses import replace
import json
import sys
from types import ModuleType

import pytest

from scar.analysis.call_seeds import read_call_source_seeds
from scar.analysis.program_inventory import ProgramInventory, inventory_program
from scar.ir.program.call_demand import CallSourceAdmissionStatus, EnteredCallCode
from scar.ir.program.call_edges import CallEdgeBudget
from scar.ir.program.expansion import ContextStoreBudget
from scar.trace.call_edges import CallEdgeRecorder


def recorded_program(tmp_path, monkeypatch, *, module_only=False):
    programs = {
        "a_leaf": "def leaf(value):\n    return value + 1\n",
        "z_parent": "from a_leaf import leaf\ndef parent(value):\n    return leaf(value)\n",
        "a_unrelated": "def unrelated(value):\n    return value\n",
        "entry": ("answer = 1\n" if module_only else
                  "from z_parent import parent\nanswer = parent(7)\n"),
    }
    for name, text in programs.items():
        (tmp_path / (name + ".py")).write_text(text)
    modules = {}
    for name in ("a_leaf", "z_parent", "a_unrelated"):
        module = ModuleType(name)
        exec(compile(programs[name], str(tmp_path / (name + ".py")), "exec", dont_inherit=True),
             module.__dict__)
        monkeypatch.setitem(sys.modules, name, module)
        modules[name] = module
    trace = tmp_path / "calls"
    recorder = CallEdgeRecorder(trace, tmp_path)
    previous = sys.getprofile()
    sys.setprofile(recorder.profile)
    try:
        if not module_only:
            modules["a_unrelated"].unrelated(1)
        exec(compile(programs["entry"], str(tmp_path / "entry.py"), "exec", dont_inherit=True), {})
    finally:
        sys.setprofile(previous)
        recorder.close()
    return tmp_path / "entry.py", trace


def test_raw_calls_automatically_enter_the_body_queue_and_link_final_regions(tmp_path, monkeypatch):
    entry, trace = recorded_program(tmp_path, monkeypatch)
    result = inventory_program(entry, project_root=tmp_path, calls_trace=trace)
    document = result.to_dict()
    assert document["schema_version"] == 6
    assert document["call_sources"] == read_call_source_seeds(trace, tmp_path).to_dict()
    names = {definition.id: definition.name for file in result.files for definition in file.definitions}
    assert [names[task.definition] for task in result.expansion.entries][:2] == ["parent", "leaf"]
    assert len(result.call_source_scope.admissions) == 3
    assert all(item.status is CallSourceAdmissionStatus.CORE_LINKED
               for item in result.call_source_scope.admissions)
    bodies = {body.definition: body for file in result.files for body in file.bodies}
    for item in result.call_source_scope.admissions:
        assert item.core_region == bodies[item.definition].graph.root
    assert len(result.expansion.entry_roots) == 1
    assert result.expansion.entry_roots[0].snapshot.path == str(entry)
    assert result.source_analysis_measurements["source_prepare_max_per_path"] == 1
    assert result.summary()["whole_program_graph_established"] is False
    assert document["transformation_authorized"] is False
    assert ProgramInventory.from_dict(document).to_dict() == document


def test_caller_is_attempted_before_alphabetically_earlier_callee_or_orphan(tmp_path, monkeypatch):
    entry, trace = recorded_program(tmp_path, monkeypatch)
    result = inventory_program(entry, project_root=tmp_path, calls_trace=trace, max_lowered_bodies=1)
    names = {definition.id: definition.name for file in result.files for definition in file.definitions}
    attempted = [names[task.definition] for task in result.expansion.entries if task.attempted]
    assert attempted == ["parent"]
    statuses = {names[item.definition]: item.status for item in result.call_source_scope.admissions}
    assert statuses["parent"] is CallSourceAdmissionStatus.CORE_LINKED
    assert statuses["leaf"] is CallSourceAdmissionStatus.INDEXED_WITHOUT_BODY
    assert statuses["unrelated"] is CallSourceAdmissionStatus.INDEXED_WITHOUT_BODY


def test_zero_eligible_calls_preserve_v6_raw_input_and_module_frontier(tmp_path, monkeypatch):
    entry, trace = recorded_program(tmp_path, monkeypatch, module_only=True)
    result = inventory_program(entry, project_root=tmp_path, calls_trace=trace)
    document = result.to_dict()
    assert document["schema_version"] == 6
    assert result.call_sources.model.groups and not result.call_sources.eligible_groups()
    assert result.call_source_scope.admissions == () and result.expansion.entries == ()
    assert result.expansion.entry_roots[0].snapshot.path == str(entry)
    assert ProgramInventory.from_dict(document).to_dict() == document


@pytest.mark.parametrize("mutation", ["origin", "region", "budget_cost", "summary", "seed_count", "scope_missing"])
def test_v6_public_replay_rejects_changed_queue_links_and_evidence(tmp_path, monkeypatch, mutation):
    entry, trace = recorded_program(tmp_path, monkeypatch)
    document = deepcopy(inventory_program(entry, project_root=tmp_path, calls_trace=trace).to_dict())
    if mutation == "origin":
        document["expansion"]["entries"][0]["origins"] = [{"kind": "REMAINDER"}]
    elif mutation == "region":
        document["call_source_scope"]["admissions"][0]["core_region"]["value"] = "invented"
    elif mutation == "budget_cost":
        document["expansion"]["entries"][0]["operation_budget_charged"] += 1
    elif mutation == "summary":
        document["summary"]["whole_program_graph_established"] = True
    elif mutation == "seed_count":
        document["call_sources"]["model"]["groups"][0]["count"] += 1
    else:
        document["call_source_scope"]["admissions"].pop()
    with pytest.raises(ValueError):
        ProgramInventory.from_dict(document)


def test_independent_call_ceiling_precedes_raw_and_source_work(tmp_path, monkeypatch):
    entry, trace = recorded_program(tmp_path, monkeypatch)
    document = inventory_program(entry, project_root=tmp_path, calls_trace=trace).to_dict()
    import scar.analysis.call_demand as adapter

    def forbidden(*args, **kwargs):
        raise AssertionError("independent ceiling must be checked before source workspace creation")

    monkeypatch.setattr(adapter, "_SourceWorkspace", forbidden)
    with pytest.raises(ValueError, match="independent verifier budget"):
        ProgramInventory.from_dict(document, call_verification_budget=replace(CallEdgeBudget(), max_events=1))


def test_source_change_rejects_the_bound_v6_report(tmp_path, monkeypatch):
    entry, trace = recorded_program(tmp_path, monkeypatch)
    document = inventory_program(entry, project_root=tmp_path, calls_trace=trace).to_dict()
    (tmp_path / "a_leaf.py").write_text("def leaf(value):\n    return value + 2\n")
    with pytest.raises(ValueError, match="raw trace/source replay"):
        ProgramInventory.from_dict(document)


def test_failed_context_store_never_claims_a_final_body_link(tmp_path, monkeypatch):
    entry, trace = recorded_program(tmp_path, monkeypatch)
    result = inventory_program(entry, project_root=tmp_path, calls_trace=trace,
        context_budget=ContextStoreBudget(max_compressed_bytes=1))
    assert result.call_sources.to_dict() == read_call_source_seeds(trace, tmp_path).to_dict()
    assert not any(item.core_region is not None for item in result.call_source_scope.admissions)
    assert result.source_analysis_measurements["source_prepare_max_per_path"] == 1
    assert ProgramInventory.from_dict(result.to_dict()).to_dict() == result.to_dict()


@pytest.mark.parametrize("error_type", [ValueError, KeyError])
def test_shared_prepare_failure_preserves_the_exact_standalone_source_boundary(tmp_path, monkeypatch, error_type):
    entry, trace = recorded_program(tmp_path, monkeypatch)
    import scar.analysis.call_edges as matching
    import scar.analysis.call_demand as composition
    original = matching.prepare_source

    def fail_dependency(path, **kwargs):
        if str(path).endswith("z_parent.py"):
            raise error_type("controlled source preparation boundary")
        return original(path, **kwargs)

    monkeypatch.setattr(matching, "prepare_source", fail_dependency)
    monkeypatch.setattr(composition, "prepare_source", fail_dependency)
    standalone = read_call_source_seeds(trace, tmp_path).to_dict()
    result = inventory_program(entry, project_root=tmp_path, calls_trace=trace)
    assert result.call_sources.to_dict() == standalone
    assert result.source_analysis_measurements["source_prepare_max_per_path"] == 1


def test_cli_runs_and_replays_an_automatic_v6_inventory(tmp_path, monkeypatch, capsys):
    from scar.cli import main
    entry, trace = recorded_program(tmp_path, monkeypatch)
    output = tmp_path / "inventory.json.gz"
    assert main(["inventory-program", str(entry), "--project-root", str(tmp_path),
                 "--calls", str(trace), "--out", str(output)]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "INVENTORIED" and first["summary"]["call_source_scope"]["CORE_LINKED"] == 3
    assert main(["check-inventory", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "REPLAYED"


@pytest.mark.parametrize("hardlink", [False, True])
def test_cli_protects_captured_nonpy_source_even_when_no_seed_is_eligible(tmp_path, capsys, hardlink):
    from scar.cli import main
    entry = tmp_path / "entry.py"
    entry.write_text("answer = 1\n")
    captured_source = tmp_path / "observed.json"
    captured_source.write_text('{"schema":"scar.program-inventory"}\n')
    original = captured_source.read_bytes()
    trace = tmp_path / "calls"
    recorder = CallEdgeRecorder(trace, tmp_path)
    previous = sys.getprofile()
    sys.setprofile(recorder.profile)
    try:
        exec(compile(captured_source.read_text(), str(captured_source), "exec", dont_inherit=True), {})
    finally:
        sys.setprofile(previous)
        recorder.close()
    output = captured_source
    if hardlink:
        output = tmp_path / "alias.json"
        output.hardlink_to(captured_source)
    assert main(["inventory-program", str(entry), "--project-root", str(tmp_path),
                 "--calls", str(trace), "--out", str(output)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "INVALID"
    assert captured_source.read_bytes() == original and output.read_bytes() == original
