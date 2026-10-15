"""Runtime seeds enrich source inventory without becoming runtime authority."""
from copy import deepcopy
from dataclasses import replace
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
from textwrap import dedent

import pytest

from scar.analysis.program_inventory import ProgramInventory, inventory_program
from scar.ir.ids import CodeID
from scar.ir.program.runtime_sources import RuntimeSeedStatus, RuntimeTraceBudget


@pytest.fixture
def runtime_project(tmp_path):
    """Execute a finite fixture in a child using the existing SCAR recorder."""
    root = tmp_path / "project"
    root.mkdir()
    trace_dir = tmp_path / "trace"
    marker = root / "executed"
    entry = root / "entry.py"
    entry.write_text(dedent('''\
        from pathlib import Path
        if False:
            import dormant
        def launch(path):
            exec(compile(path.read_text(), str(path), "exec"),
                 {"__name__": "runtime_payload", "__file__": str(path)})
        launch(Path(__file__).with_name("payload.py"))
    '''), encoding="utf-8")
    payload = root / "payload.py"
    payload.write_text(dedent(f'''\
        from helper import identity
        open({str(marker)!r}, "w").write("executed")
        def unused(value):
            return value
        def compute(value):
            return identity(value)
        compute(1)
        compute(2)
    '''), encoding="utf-8")
    (root / "helper.py").write_text("def identity(value):\n    return value\n", encoding="utf-8")
    (root / "dormant.py").write_text("def unobserved(value):\n    return value\n", encoding="utf-8")
    driver = tmp_path / "driver.py"
    driver.write_text(dedent('''\
        from pathlib import Path
        import sys
        from scar.trace.session import TraceSession
        entry, trace = Path(sys.argv[1]), Path(sys.argv[2])
        sys.path.insert(0, str(entry.parent))
        session = TraceSession(trace)
        # Deliberately partial capture: helper must be recovered by the new
        # payload's static import closure, not by a second runtime seed.
        captured_sources = {str(entry), str(entry.with_name("payload.py"))}
        def profile(frame, event, argument):
            if frame.f_code.co_filename not in captured_sources:
                return
            if event == "call":
                session.python_call(frame)
            elif event == "return":
                session.python_return(frame, argument)
        code = compile(entry.read_text(), str(entry), "exec", dont_inherit=True)
        sys.setprofile(profile)
        try:
            exec(code, {"__name__": "__main__", "__file__": str(entry)})
        finally:
            sys.setprofile(None)
            session.close(0)
    '''), encoding="utf-8")
    environment = dict(os.environ)
    repository = str(Path(__file__).resolve().parents[2])
    environment["PYTHONPATH"] = repository + os.pathsep + environment.get("PYTHONPATH", "")
    environment["SCAR_RESOURCE_SAMPLER"] = "0"
    child = subprocess.run([sys.executable, str(driver), str(entry), str(trace_dir)],
                           cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stdout + child.stderr
    assert marker.read_text() == "executed"
    marker.unlink()
    trace = trace_dir / "events.jsonl"
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    assert any(row["kind"] == "python_call" and str(payload) in row["code_id"] for row in rows)
    return root, entry, payload, trace, marker


def with_trace(fixture, **kwargs):
    root, entry, _, trace, _ = fixture
    return inventory_program(entry, project_root=root, source_roots=(root,), runtime_trace=trace, **kwargs)


def test_real_runtime_seed_expands_import_closure_and_keeps_unobserved_static_branch(runtime_project):
    root, entry, payload, trace, marker = runtime_project
    static = inventory_program(entry, project_root=root, source_roots=(root,))
    assert static.to_dict()["schema_version"] == 5
    assert static.to_dict()["runtime_scope"] is None
    static_paths = {file.snapshot.path for file in static.files}
    assert str(payload) not in static_paths and str(root / "helper.py") not in static_paths
    assert str(root / "dormant.py") in static_paths
    result = with_trace(runtime_project)
    paths = {file.snapshot.path for file in result.files}
    assert paths == {str(entry), str(payload), str(root / "helper.py"), str(root / "dormant.py")}
    assert any(edge.source.path == str(payload) and edge.requested == "helper"
               for edge in result.discovery.imports)
    document = result.to_dict()
    assert document["schema_version"] == 5 and document["runtime_scope"] and document["expansion"] and document["interfaces"]
    assert document["target_executed"] is False
    assert document["summary"]["runtime_reachability_established"] is False
    assert document["transformation_authorized"] is False
    scope = result.runtime_scope
    assert not any(CodeID.parse_key(observation.code_id).source == str(root / "helper.py")
                   for observation in scope.trace.observations
                   if CodeID.parse_key(observation.code_id) is not None)
    payload_bindings = [binding for binding in scope.bindings
                        if binding.source_path == str(payload)]
    assert any(binding.status.name == "VERIFIED" and binding.witnesses for binding in payload_bindings)
    for binding in payload_bindings:
        if binding.status.name == "VERIFIED":
            assert binding.source_snapshot.fingerprint == next(
                file.snapshot.fingerprint for file in result.files if file.snapshot.path == str(payload))
            assert binding.candidate_definitions
    assert all(operation.callee is None for file in result.files for body in file.bodies
               if body.graph is not None for operation in body.graph.operations)
    assert ProgramInventory.from_dict(document).to_dict() == document
    assert ProgramInventory.from_dict(static.to_dict()).to_dict() == static.to_dict()
    assert not marker.exists(), "offline analysis must not execute source again"


def test_observed_definition_gets_body_budget_before_an_unobserved_sibling(runtime_project):
    result = with_trace(runtime_project, max_lowered_bodies=2)
    payload = runtime_project[2]
    file = next(file for file in result.files if file.snapshot.path == str(payload))
    names = {definition.id: definition.qualname for definition in file.definitions}
    statuses = {names[body.definition]: body.status.value for body in file.bodies}
    # One attempt goes to the entry's launch. The one remaining attempt in
    # payload must follow its observed compute definition, not source order.
    assert statuses["compute"] == "LOWERED_WITH_GAPS"
    assert statuses["unused"] == "NOT_ATTEMPTED"


def test_repeated_observations_do_not_repeat_offline_compilation(runtime_project):
    original = with_trace(runtime_project)
    trace = runtime_project[3]
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    selected, seen = [], set()
    for row in rows:
        process = row.get("metadata", {}).get("process_id")
        key = row.get("code_id"), type(process), process
        if key not in seen:
            seen.add(key)
            selected.append(row)
    trace.write_text("".join(json.dumps(row) + "\n" for row in selected))
    sampled = with_trace(runtime_project)
    assert sum(item.count for item in original.runtime_scope.trace.observations) > len(selected)
    assert len(sampled.runtime_scope.trace.observations) == len(original.runtime_scope.trace.observations)
    assert sampled.runtime_scope.compilation_attempts == original.runtime_scope.compilation_attempts


@pytest.mark.parametrize("change", ("trace_bytes", "current_source", "runtime_scope", "selected_files"))
def test_runtime_inventory_replay_rejects_changed_evidence_or_selection(runtime_project, change):
    _, _, payload, trace, marker = runtime_project
    result = with_trace(runtime_project)
    document = deepcopy(result.to_dict())
    if change == "trace_bytes":
        trace.write_bytes(trace.read_bytes() + b"\n")
    elif change == "current_source":
        payload.write_text(payload.read_text().replace("compute(2)", "compute(3)"))
    elif change == "runtime_scope":
        document["runtime_scope"] = {}
    else:
        document["files"] = [file for file in document["files"] if file["snapshot"]["path"] != str(payload)]
    with pytest.raises((ValueError, OSError)):
        ProgramInventory.from_dict(document)
    assert not marker.exists()


def test_compile_attempt_limit_is_an_independent_verifier_ceiling(runtime_project):
    result = with_trace(runtime_project, max_compile_attempts=2)
    document = result.to_dict()
    assert ProgramInventory.from_dict(document, max_compile_attempts=2).to_dict() == document
    with pytest.raises(ValueError):
        ProgramInventory.from_dict(document, max_compile_attempts=1)


def test_compressed_trace_input_preserves_runtime_source_selection(runtime_project):
    root, entry, _, trace, marker = runtime_project
    archive = trace.with_suffix(".jsonl.gz")
    with gzip.open(archive, "wb") as stream:
        stream.write(trace.read_bytes())
    plain = with_trace(runtime_project)
    compressed = inventory_program(entry, project_root=root, source_roots=(root,), runtime_trace=archive)
    assert {file.snapshot.path for file in plain.files} == {file.snapshot.path for file in compressed.files}
    assert ProgramInventory.from_dict(compressed.to_dict()).to_dict() == compressed.to_dict()
    assert not marker.exists()


@pytest.mark.parametrize("change", ("digest", "anchor", "seed", "match", "compile_budget"))
def test_runtime_evidence_fields_are_recomputed_not_trusted(runtime_project, change):
    document = deepcopy(with_trace(runtime_project).to_dict())
    scope = document["runtime_scope"]
    if change == "digest":
        scope["trace"]["manifest"]["raw_sha256"] = "0" * 64
    elif change == "anchor":
        scope["trace"]["observations"][0]["first"]["line_number"] += 1
    elif change == "seed":
        scope["seeds"][0]["candidate_path"] = str(runtime_project[0] / "invented.py")
    elif change == "match":
        verified = next(binding for binding in scope["bindings"] if binding["status"] == "VERIFIED")
        verified["witnesses"][0]["compiled_code_digest"] = "pycode-sha256:" + "0" * 64
    else:
        scope["max_compile_attempts"] = 1_000_000
    with pytest.raises(ValueError):
        ProgramInventory.from_dict(document)


def test_trace_budget_is_independently_checked_before_replay(runtime_project):
    budget = RuntimeTraceBudget(max_lines=1000)
    result = with_trace(runtime_project, runtime_budget=budget)
    document = result.to_dict()
    assert ProgramInventory.from_dict(document, runtime_verification_budget=budget).to_dict() == document
    with pytest.raises(ValueError):
        ProgramInventory.from_dict(document, runtime_verification_budget=replace(budget, max_lines=1))


def test_repeated_code_keeps_process_identity_types_and_raw_occurrence_anchors(runtime_project):
    _, _, payload, trace, _ = runtime_project
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    original = next(row for row in rows if row["kind"] == "python_call"
                    and CodeID.parse_key(row["code_id"]).source == str(payload)
                    and CodeID.parse_key(row["code_id"]).qualname == "compute")
    selected = []
    for index, process in enumerate((17, 17, "17"), 1):
        row = deepcopy(original)
        row["metadata"]["process_id"] = process
        row["index"] = index
        row["invocation_id"] = index
        selected.append(row)
    trace.write_text("".join(json.dumps(row) + "\n" for row in selected))
    result = with_trace(runtime_project)
    observations = result.runtime_scope.trace.observations
    assert len(observations) == 2
    integer = next(item for item in observations if type(item.process_id) is int)
    string = next(item for item in observations if type(item.process_id) is str)
    assert integer.count == 2 and string.count == 1
    assert (integer.first.line_number, integer.last.line_number) == (1, 2)
    assert (string.first.line_number, string.last.line_number) == (3, 3)
    assert {seed.observation_index for seed in result.runtime_scope.seeds} == {0, 1}


def test_untrusted_runtime_paths_do_not_gain_analyzer_cwd_or_escape_project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    entry = root / "entry.py"
    entry.write_text("def entry(value):\n    return value\n")
    relative = root / "relative.py"
    relative.write_text("def compute():\n    return 1\n")
    outside = tmp_path / "outside.py"
    outside.write_text("def compute():\n    return 1\n")
    alias = root / "alias.py"
    alias.symlink_to(relative)
    missing = root / "missing.py"
    raw_paths = ["relative.py", str(outside), str(alias), "<string>", str(missing)]
    trace = tmp_path / "paths.jsonl"
    trace.write_text("".join(json.dumps({
        "kind": "python_call", "index": index, "invocation_id": index,
        "code_id": CodeID(path, "compute", 1, None, "unknown").key(),
        "metadata": {"process_id": 1, "thread_id": 1},
    }) + "\n" for index, path in enumerate(raw_paths)))
    monkeypatch.chdir(root)
    result = inventory_program(entry, project_root=root, source_roots=(root,), runtime_trace=trace)
    assert {file.snapshot.path for file in result.files} == {str(entry)}
    assert {seed.status for seed in result.runtime_scope.seeds} == {
        RuntimeSeedStatus.RELATIVE_NO_CWD, RuntimeSeedStatus.OUTSIDE_PROJECT,
        RuntimeSeedStatus.SYMLINK, RuntimeSeedStatus.GENERATED, RuntimeSeedStatus.MISSING,
    }
    assert all(seed.reason for seed in result.runtime_scope.seeds)
    assert not any(binding.status.name == "VERIFIED" for binding in result.runtime_scope.bindings)


def test_old_trace_digest_absence_can_select_source_but_cannot_verify_code(runtime_project):
    _, _, payload, trace, _ = runtime_project
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    for row in rows:
        code = CodeID.parse_key(row.get("code_id", ""))
        if code is not None:
            row["code_id"] = replace(code, version="unknown").key()
    trace.write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = with_trace(runtime_project)
    assert str(payload) in {file.snapshot.path for file in result.files}
    assert result.runtime_scope.bindings
    assert not any(binding.status.name == "VERIFIED" for binding in result.runtime_scope.bindings)
    assert any("digest" in binding.reason.lower() for binding in result.runtime_scope.bindings)
