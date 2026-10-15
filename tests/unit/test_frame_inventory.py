"""Automatic v5 frame construction, bounded scheduling and historical replay."""
from copy import deepcopy
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from scar.analysis.program_inventory import ProgramInventory, _inventory_from_inputs, inventory_program
from scar.analysis.program_lowering import PreparedSource
from scar.ir.ids import CodeID
from scar.ir.program.expansion import ContextStoreBudget
from scar.ir.program.frames import FrameBind, FrameEnter, FrameExit
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.inventory import BodyStatus, InventoryBudget


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def compat_trace(path, source, name, line):
    """Synthetic compatibility evidence; no application profiling is claimed."""
    return write(path, json.dumps({"kind": "python_call", "index": 1, "invocation_id": 1,
                 "code_id": CodeID(str(source), name, line, None, "unknown").key(),
                 "metadata": {"process_id": 1}}) + "\n")


@pytest.fixture
def automatic(tmp_path):
    write(tmp_path / "helper.py", "def identity(value):\n    return value\n")
    entry = write(tmp_path / "entry.py", "from helper import identity\n"
                  "def target(unused, a, /, b=7, *rest, c=8, **extra):\n"
                  "    y = a\n    a = b\n    identity(y)\n    return y\n"
                  "def caller(value):\n    return target(value, value)\n"
                  "def broken(value):\n    try:\n        return value\n    finally:\n        pass\n"
                  "raise AssertionError('source fixture must never execute')\n")
    return inventory_program(entry, project_root=tmp_path), entry


def test_default_v5_has_one_frame_for_every_automatically_emitted_body(automatic):
    result, entry = automatic
    document = result.to_dict()
    assert document["schema_version"] == 5 and document["profile"] == "BOUND_FRAME_V1"
    assert result.profile is result.interfaces.profile is BodyLoweringProfile.BOUND_FRAME
    bodies = {body.definition: body for file in result.files for body in file.bodies if body.graph is not None}
    frames = {model.definition: model for model in result.frames}
    assert set(frames) == set(bodies) == {port.definition for port in result.interfaces.bodies}
    assert len(frames) == 3  # helper, target and caller are all automatic bodies.
    definitions = {definition.id: definition for file in result.files for definition in file.definitions}
    target = next(model for model in result.frames if definitions[model.definition].name == "target")
    enter, = [transition for transition in target.transitions if isinstance(transition, FrameEnter)]
    assert len(enter.formals) == 6  # unused plus all five parameter kinds.
    assert len([transition for transition in target.transitions if isinstance(transition, FrameBind)]) == 2
    for model in result.frames:
        body = bodies[model.definition]
        assert len(body.graph.regions) == 1 and model.region == body.graph.root
        operations = {operation.id: operation for operation in body.graph.operations}
        for transition in model.transitions:
            access, = operations[transition.operation].accesses
            assert not access.full_overwrite and not operations[transition.operation].effects_complete
            if isinstance(transition, FrameExit):
                uses = {use.id: use for use in operations[transition.operation].uses}
                completion = operations[transition.completion]
                completion_uses = {use.id: use for use in completion.uses}
                assert uses[transition.payload].value == completion_uses[completion.terminator.values[0]].value
    assert document["summary"]["frames"]["runtime_conditions_established"] is False
    assert not document["target_executed"] and not document["transformation_authorized"]
    assert ProgramInventory.from_dict(document).to_dict() == document


@pytest.mark.parametrize("tamper", ["profile", "interface_profile", "no_frame", "duplicate_frame",
                                   "no_enter_formal", "missing_bind", "payload", "rules", "budget"])
def test_v5_public_replay_rejects_profile_frame_coverage_state_and_authority_tampering(automatic, tamper):
    result, _ = automatic
    document = deepcopy(result.to_dict())
    model = next(model for model in document["frames"]
                 if any("assigned" in transition for transition in model["transitions"]))
    if tamper == "profile":
        document["profile"] = "BOUND_FORMALS_V1"
    elif tamper == "interface_profile":
        document["interfaces"]["profile"] = "BOUND_FORMALS_V1"
    elif tamper == "no_frame":
        document["frames"].pop()
    elif tamper == "duplicate_frame":
        document["frames"].append(deepcopy(document["frames"][0]))
    elif tamper == "no_enter_formal":
        next(t for t in model["transitions"] if "formals" in t)["formals"].pop()
    elif tamper == "missing_bind":
        model["transitions"] = [t for t in model["transitions"] if "assigned" not in t]
    elif tamper == "payload":
        bound = next(t for t in model["transitions"] if "assigned" in t)
        next(t for t in model["transitions"] if "payload" in t)["payload"] = bound["assigned"]
    elif tamper == "rules":
        model["rules"]["condition_status"] = "PROVEN"
    else:
        document["budget"]["max_operations"] += 1
    with pytest.raises(ValueError):
        ProgramInventory.from_dict(document)


def test_trace_bearing_v5_replay_preserves_profile_after_runtime_options(tmp_path):
    entry = write(tmp_path / "entry.py", "def observed(value):\n    return value\n")
    trace = compat_trace(tmp_path / "events.jsonl", entry, "observed", 1)
    result = inventory_program(entry, project_root=tmp_path, runtime_trace=trace)
    assert result.runtime_scope is not None and result.frames
    assert result.profile is BodyLoweringProfile.BOUND_FRAME
    assert ProgramInventory.from_dict(result.to_dict()).to_dict() == result.to_dict()


def test_explicit_historical_modes_have_no_new_wire_fields_or_summary(automatic):
    _, entry = automatic
    for interfaces, version in ((False, 1), (True, 4)):
        result = _inventory_from_inputs(entry, project_root=entry.parent, source_roots=(),
                                       budget=InventoryBudget(), interface_model=interfaces,
                                       body_profile=BodyLoweringProfile.BOUND_FORMALS if interfaces else None)
        document = result.to_dict()
        assert document["schema_version"] == version
        assert "frames" not in document and "profile" not in document and "frames" not in document["summary"]
        assert result.profile is None and result.frames == ()
        assert ProgramInventory.from_dict(document).to_dict() == document


def test_frame_rejection_is_transactional_and_does_not_refund_construction(tmp_path, monkeypatch):
    entry = write(tmp_path / "entry.py", "def first(value):\n    return value\n"
                  "def later(value):\n    return value\n")
    original = PreparedSource.lower
    charges = []
    def remove_frame(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        charges.append(result.operations_emitted)
        return replace(result, frame=None)
    monkeypatch.setattr(PreparedSource, "lower", remove_frame)
    result = inventory_program(entry, project_root=tmp_path, max_operations=3)
    assert len(charges) == 1 and charges[0] == 3
    first, later = result.expansion.entries
    assert first.status is BodyStatus.UNSUPPORTED and first.operation_budget_charged == charges[0]
    assert not later.attempted
    assert not result.frames and not result.interfaces.bodies
    assert all(argument.use is None for binding in result.interfaces.bindings for argument in binding.arguments)
    assert all(body.graph is None for file in result.files for body in file.bodies)


def test_frame_construction_and_rolled_back_failure_obey_global_operation_ceiling(tmp_path):
    entry = write(tmp_path / "entry.py", "def first(value):\n    value\n    value\n    return value\n"
                  "def later(value):\n    return value\n")
    result = inventory_program(entry, project_root=tmp_path, max_operations=2)
    assert sum(e.operation_budget_charged for e in result.expansion.entries) == 2
    assert sum(body.construction_operations for file in result.files for body in file.bodies) == 2
    assert not result.frames and not result.interfaces.bodies
    assert len([e for e in result.expansion.entries if e.attempted]) == 1
    assert ProgramInventory.from_dict(result.to_dict()).to_dict() == result.to_dict()
    with pytest.raises(ValueError, match="independent verifier budget"):
        ProgramInventory.from_dict(result.to_dict(), max_operations=1)


def test_context_budget_keeps_inventory_and_scope_but_cannot_publish_frame(tmp_path):
    entry = write(tmp_path / "entry.py", "def unavailable(value):\n    return value\n")
    result = inventory_program(entry, project_root=tmp_path, context_budget=ContextStoreBudget(max_record_bytes=1))
    assert result.to_dict()["schema_version"] == 5
    assert not result.frames and not result.interfaces.bodies
    assert result.expansion.unavailable_contexts
    assert result.files[0].definitions and result.files[0].coverage
    assert ProgramInventory.from_dict(result.to_dict()).to_dict() == result.to_dict()


@pytest.fixture(scope="module", params=[(1, "f21eb53"), (2, "b886e40"), (3, "994f944"),
                                      (4, "677e10f4461cdf47b1cb7839ed3fd1b856f7610e")])
def archived_document(request, tmp_path_factory):
    """Actual historical package generation, never a forced schema number."""
    version, revision = request.param
    repository = Path(__file__).resolve().parents[2]
    folder = tmp_path_factory.mktemp("frame-real-legacy-" + str(version))
    package, project = folder / "package", folder / "project"
    package.mkdir(); project.mkdir()
    archive = subprocess.check_output(["git", "archive", revision, "scar"], cwd=repository)
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        stream.extractall(package, filter="data")
    entry = write(project / "entry.py", "def caller(value):\n    return helper(value)\n"
                  "def helper(value):\n    return value\n"
                  "def defaults(value=[]):\n    return value\n"
                  "raise AssertionError('fixture must never execute')\n")
    output = folder / "inventory.json"
    command = [sys.executable, "-m", "scar.cli", "inventory-program", str(entry),
               "--project-root", str(project), "--out", str(output)]
    if version in (2, 3):
        trace = compat_trace(folder / "events.jsonl", entry, "caller", 1)
        command.extend(("--trace", str(trace)))
    environment = dict(os.environ, PYTHONPATH=str(package), PYTHONDONTWRITEBYTECODE="1")
    for name in ("SCAR_TRACE_DIR", "SCAR_TRACE_CALL_EDGES", "SCAR_CALL_TRACE_OWNER_PID"):
        environment.pop(name, None)
    probe = subprocess.run([sys.executable, "-c", "import scar; print(scar.__file__)"],
                           cwd=package, env=environment, capture_output=True, text=True, timeout=60)
    assert probe.returncode == 0 and Path(probe.stdout.strip()).is_relative_to(package)
    generated = subprocess.run(command, cwd=package, env=environment,
                               capture_output=True, text=True, timeout=60)
    assert generated.returncode == 0, generated.stdout + generated.stderr
    document = json.loads(output.read_text())
    assert document["schema_version"] == version
    return version, document


def test_real_archived_v1_to_v4_reports_replay_without_frame_upgrade(archived_document):
    version, document = archived_document
    replayed = ProgramInventory.from_dict(document)
    assert replayed.to_dict() == document
    assert replayed.profile is None and replayed.frames == ()
    assert "frames" not in replayed.summary()
    if version == 4:
        assert replayed.interfaces.profile is BodyLoweringProfile.BOUND_FORMALS
    else:
        assert replayed.interfaces is None
    defaults = next(definition.id for file in replayed.files for definition in file.definitions
                    if definition.name == "defaults")
    body = next(body for file in replayed.files for body in file.bodies if body.definition == defaults)
    assert (body.graph is not None) is (version == 4)
