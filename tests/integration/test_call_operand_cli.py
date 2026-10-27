"""Original programs automatically produce queryable cross-call operand graphs."""
from copy import deepcopy
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


def cli(*arguments, cwd=None):
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    for name in ("SCAR_TRACE_DIR", "SCAR_TRACE_CALL_EDGES", "SCAR_CALL_TRACE_OWNER_PID", "SCAR_CALL_OPERANDS"):
        env.pop(name, None)
    return subprocess.run([sys.executable, "-m", "scar.cli", *map(str, arguments)],
                          cwd=cwd or ROOT, env=env, capture_output=True, text=True, timeout=90)


def read(path):
    with gzip.open(path, "rt") if path.suffix == ".gz" else path.open() as stream:
        return json.load(stream)


@pytest.fixture(scope="module", params=("distinct", "shared", "snapshot_shared"))
def linked(tmp_path_factory, request):
    tmp_path = tmp_path_factory.mktemp("operand-cli-" + request.param)
    project = tmp_path / "project"
    project.mkdir()
    (project / "helper.py").write_text(
        "def choose(left, right):\n    return left\n"
        "def relay(a, b):\n    selected = choose(a, b)\n    return selected\n")
    inputs = {"distinct": "left = Token()\nright = Token()\n",
              "shared": "left = Token()\nright = left\n",
              "snapshot_shared": "left = []\nright = left\n"}[request.param]
    entry = project / "entry.py"
    entry.write_text(
        "from helper import relay\nclass Token: pass\n"
        "def run(x, y):\n    first = relay(x, y)\n    second = relay(y, x)\n    return first\n"
        + inputs + "assert run(left, right) is left\nprint('completed')\n")
    trace = tmp_path / "trace"
    captured = cli("trace", "--call-operands", "--project-root", project,
                   "--out", trace, "--", sys.executable, entry, cwd=project)
    assert captured.returncode == 0, captured.stdout + captured.stderr
    assert "completed" in captured.stdout
    assert "injector disabled" not in captured.stdout + captured.stderr
    inventory = tmp_path / "inventory.json.gz"
    generated = cli("inventory-program", entry, "--project-root", project,
                    "--calls", trace, "--out", inventory)
    assert generated.returncode == 0, generated.stdout + generated.stderr
    assert read(inventory)["schema_version"] == 6
    report = tmp_path / "operands.json.gz"
    linked = cli("link-operands", trace, "--project-root", project,
                 "--inventory", inventory, "--out", report)
    assert linked.returncode == 0, linked.stdout + linked.stderr
    return project, entry, trace, inventory, report


def definitions(path):
    return {item["id"]["wire"]: item["qualname"] for file in read(path)["files"] for item in file["definitions"]}


def test_public_query_reaches_unique_upper_input_through_original_two_file_program(linked):
    _, _, _, inventory, path = linked
    document = read(path)
    analysis = document["analysis"]
    names = definitions(inventory)
    routing = analysis["routing"]
    run, = [value for value in routing["returns"] if names[value["definition"]["wire"]] == "run"]
    invocation = run["invocation"]
    checked = cli("check-operand-links", path)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    queried = cli("query-operand-refs", path, "--process", invocation["process_id"],
                  "--thread", invocation["thread_id"], "--invocation", invocation["invocation_id"])
    assert queried.returncode == 0, queried.stdout + queried.stderr
    query = json.loads(queried.stdout)["query"]
    formal_endpoints = {(value["invocation"]["invocation_id"], names[value["definition"]["wire"]], value["formal_name"])
                        for value in query["endpoints"] if value["kind"] == "FORMAL"}
    assert formal_endpoints == {(invocation["invocation_id"], "run", "x")}
    traversed = [step["completion"] for step in query["routes"] if step["kind"] == "COMPLETION"]
    assert len(traversed) == 2
    assert {names[route["callee_definition"]["wire"]] for route in traversed} == {"relay", "choose"}
    assert query["conditions"] and query["obligations"] and query["conditional_only"]
    for key in ("contents_or_effects_established", "function_environment_established",
                "world_equivalence_established", "transformation_authorized"):
        assert query[key] is False
    by_callee = {}
    for route in routing["argument_routes"]:
        if names[route["callee_definition"]["wire"]] == "choose":
            by_callee.setdefault(route["callee"]["invocation_id"], []).append(route)
    assert len(by_callee) == 2
    for routes in by_callee.values():
        assert {route["actual_index"] for route in routes} == {0, 1}
        assert len({route["actual_use"]["wire"] for route in routes}) == 2
        assert len({(route["load_anchor"]["index"], route["load_suboperand"]) for route in routes}) == 2
    # The report retains a thin query graph; the original instruction stream
    # is represented by its manifest, without a second complete event array.
    assert "operand_events" not in analysis
    assert analysis["whole_program_complete"] is False


@pytest.mark.parametrize("tamper", ("actual_index", "load_suboperand", "attempt", "condition", "summary"))
def test_public_replay_rejects_changed_operand_claims(linked, tmp_path, tamper):
    *_, path = linked
    document = deepcopy(read(path))
    analysis = document["analysis"]
    route = analysis["routing"]["argument_routes"][0]
    if tamper in ("actual_index", "load_suboperand"):
        route[tamper] += 1
    elif tamper == "attempt":
        route["attempt"]["index"] += 1
    elif tamper == "condition":
        route["conditions"] = []
    else:
        analysis["whole_program_complete"] = True
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(document))
    rejected = cli("check-operand-links", changed)
    assert rejected.returncode == 2, rejected.stdout + rejected.stderr
    assert json.loads(rejected.stdout)["status"] == "INVALID"


@pytest.mark.parametrize("kind, field", (("frame_budget", "max_events"),
                                        ("operand_budget", "max_events"),
                                        ("route_budget", "max_routes")))
def test_independent_limits_are_checked_before_missing_inventory_io(linked, tmp_path, kind, field):
    *_, path = linked
    document = deepcopy(read(path))
    document["analysis"][kind][field] += 1
    document["inventory"]["path"] = str(tmp_path / "does-not-exist.json")
    changed = tmp_path / "raised.json"
    changed.write_text(json.dumps(document))
    rejected = cli("check-operand-links", changed)
    assert rejected.returncode == 2, rejected.stdout + rejected.stderr
    assert "independent verifier budget" in json.loads(rejected.stdout)["errors"][0]


def test_public_operand_output_preserves_inventory_and_original_source(linked, tmp_path):
    project, entry, trace, inventory, _ = linked
    for source in (entry, inventory):
        alias = tmp_path / (source.stem + "-hardlink.json")
        os.link(source, alias)
        before = source.read_bytes()
        rejected = cli("link-operands", trace, "--project-root", project,
                       "--inventory", inventory, "--out", alias)
        assert rejected.returncode == 2, rejected.stdout + rejected.stderr
        assert source.read_bytes() == alias.read_bytes() == before
