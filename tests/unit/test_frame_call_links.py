"""The real captured return chain survives both source-body profiles."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from scar.analysis.call_edges import CallEdgeReport, link_calls
from scar.analysis.program_inventory import ProgramInventory, _inventory_from_inputs
from scar.ir.program.call_edges import CallEdgeIssueKind, ReferenceRole, ReferenceRouteKind
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.inventory import InventoryBudget
from scar.ir.program.model import TerminatorKind
from tests.unit.test_call_edge_links import capture, edges_named


@pytest.mark.parametrize("profile", [BodyLoweringProfile.BOUND_FORMALS, BodyLoweringProfile.BOUND_FRAME])
@pytest.mark.parametrize("shared", [False, True])
def test_exact_return_payload_routes_keep_child_identity_and_stop_before_actual_routing(
        tmp_path, monkeypatch, profile, shared):
    _, default_inventory, trace, *_ = capture(tmp_path, monkeypatch,
        call=(lambda module, left, right: module.run(left, left)) if shared else None)
    inventory = (default_inventory if profile is BodyLoweringProfile.BOUND_FRAME else
        _inventory_from_inputs(tmp_path / "entry.py", project_root=tmp_path, source_roots=(),
                               budget=InventoryBudget(), interface_model=True, body_profile=profile))
    assert inventory.to_dict()["schema_version"] == (5 if profile is BodyLoweringProfile.BOUND_FRAME else 4)
    report = link_calls(trace, tmp_path, inventory=inventory)
    run, = edges_named(report, "run")
    first, second = edges_named(report, "relay")
    identity, other_identity = edges_named(report, "identity")
    query = report.trace_reference(run.exit)
    assert {issue.kind for issue in query.issues} == {CallEdgeIssueKind.ARGUMENT_ROUTING_UNVERIFIED}
    assert {ReferenceRouteKind.SOURCE_RETURN_LOCAL, ReferenceRouteKind.CORE_CALL_RESULT,
            ReferenceRouteKind.RETURN_CALL, ReferenceRouteKind.OBSERVED_CALL_RETURN,
            ReferenceRouteKind.SAME_FRAME_PARAMETER} <= {route.kind for route in query.routes}
    assert not any(route.kind is ReferenceRouteKind.SOURCE_ARGUMENT_LOCAL for route in query.routes)
    occurrences = [item for group in query.groups for item in group.occurrences]
    assert {item.owner for item in occurrences} == {
        run.entry.invocation, first.entry.invocation, identity.entry.invocation}
    assert not any(item.observed_in in {second.entry.invocation, other_identity.entry.invocation}
                   for item in occurrences)
    assert not any(item.owner == run.entry.invocation and item.role is ReferenceRole.PARAMETER
                   for item in occurrences)
    assert all(not route.function_environment_established and not route.contents_or_effects_established
               for route in query.routes)
    assert not query.content_or_effect_equivalence_established
    assert all(edge.conditions for edge in report.model.edges)
    # In v5 each refined return points to the actual RETURN's owned payload
    # operand, rather than the removed opaque return operation's input.
    if profile is BodyLoweringProfile.BOUND_FRAME:
        bodies = {body.definition: body for file in inventory.files for body in file.bodies if body.graph}
        by_owner = {edge.entry.invocation: edge for edge in report.model.edges}
        for item in occurrences:
            if item.role is not ReferenceRole.RETURN:
                continue
            body = bodies[by_owner[item.owner].target.definition]
            returned = [operation for operation in body.graph.operations
                        if operation.terminator is not None
                        and operation.terminator.kind is TerminatorKind.RETURN
                        and operation.terminator.values[0] == item.core_use]
            assert len(returned) == 1
            assert any(use.id == item.core_use and use.value == item.core_value for use in returned[0].uses)
        assert all(model.rules.condition_status.value == "UNKNOWN" for model in inventory.frames)
    document = report.to_dict()
    assert CallEdgeReport.from_dict(document, inventory=inventory).to_dict() == document


def test_report_from_real_archived_v4_package_keeps_complete_canonical_document(tmp_path, monkeypatch):
    _, _, trace, *_ = capture(tmp_path, monkeypatch)
    repository = Path(__file__).resolve().parents[2]
    package = tmp_path.parent / (tmp_path.name + "-archived-v4")
    package.mkdir()
    revision = "677e10f4461cdf47b1cb7839ed3fd1b856f7610e"
    archive = subprocess.check_output(["git", "archive", revision, "scar"], cwd=repository)
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        stream.extractall(package, filter="data")
    environment = dict(os.environ, PYTHONPATH=str(package), PYTHONDONTWRITEBYTECODE="1")
    for name in ("SCAR_TRACE_DIR", "SCAR_TRACE_CALL_EDGES", "SCAR_CALL_TRACE_OWNER_PID"):
        environment.pop(name, None)
    probe = subprocess.run([sys.executable, "-c", "import scar; print(scar.__file__)"], cwd=package,
                           env=environment, capture_output=True, text=True, timeout=60)
    assert probe.returncode == 0 and Path(probe.stdout.strip()).is_relative_to(package)
    inventory_path, report_path = tmp_path / "old-inventory.json", tmp_path / "old-calls.json"
    commands = [
        ["inventory-program", str(tmp_path / "entry.py"), "--project-root", str(tmp_path),
         "--out", str(inventory_path)],
        ["link-calls", str(trace), "--project-root", str(tmp_path), "--inventory", str(inventory_path),
         "--out", str(report_path)],
    ]
    for arguments in commands:
        generated = subprocess.run([sys.executable, "-m", "scar.cli", *arguments], cwd=package,
                                   env=environment, capture_output=True, text=True, timeout=60)
        assert generated.returncode == 0, generated.stdout + generated.stderr
    old_inventory = json.loads(inventory_path.read_text())
    assert old_inventory["schema_version"] == 4 and "frames" not in old_inventory
    inventory = ProgramInventory.from_dict(old_inventory)
    old_document = json.loads(report_path.read_text())["analysis"]
    assert old_document["schema_version"] == 1
    replayed = CallEdgeReport.from_dict(old_document, inventory=inventory)
    assert replayed.to_dict() == old_document
    run, = edges_named(replayed, "run")
    query = replayed.trace_reference(run.exit)
    assert {issue.kind for issue in query.issues} == {CallEdgeIssueKind.ARGUMENT_ROUTING_UNVERIFIED}
    assert ReferenceRouteKind.RETURN_CALL in {route.kind for route in query.routes}
