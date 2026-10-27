"""Public environment recovery from source and original raw calls, no hand IR."""
from copy import deepcopy
import sys

import pytest

from tests.integration.test_inventory_structured_cli import cli, read


def test_environment_source_inventory_and_source_program_never_execute_target(tmp_path):
    entry = tmp_path / "entry.py"
    marker = tmp_path / "executed"
    entry.write_text(
        f"open({str(marker)!r}, 'w').write('executed')\n"
        "def factory(shared):\n"
        "    def inner(value):\n        return shared + value\n"
        "    return inner\n"
        "def lookup(value):\n    return abs(value)\n",
        encoding="utf-8",
    )
    output = tmp_path / "inventory.json.gz"
    process = cli("inventory-program", entry, "--project-root", tmp_path,
                  "--body-profile", "environment", "--out", output)
    assert process.returncode == 0, process.stdout + process.stderr
    document = read(output)
    assert document["schema_version"] == 8 and document["profile"] == "STRUCTURED_ENV_V1"
    assert "frames" not in document
    assert len(document["structured"]) == 2  # factory creation is still a separate gap
    replay = cli("check-inventory", output)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    model = tmp_path / "body.json"
    lowered = cli("model-program", entry, "--entry", "lookup",
                  "--body-profile", "environment", "--out", model)
    assert lowered.returncode == 0, lowered.stdout + lowered.stderr
    assert read(model)["schema_version"] == 4
    checked = cli("check-source-program", model)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    archive = tmp_path / "source-layers"
    retained = cli("source-layers", "--inventory", output, "--out", archive)
    assert retained.returncode == 0, retained.stdout + retained.stderr
    assert read(archive / "index.json")["input"]["schema_version"] == 8
    assert not marker.exists()


def test_actual_shared_code_closures_are_recovered_without_claiming_runtime_environment(tmp_path):
    entry = tmp_path / "entry.py"
    entry.write_text(
        "def factory(shared):\n"
        "    def inner(value):\n        return shared + value\n"
        "    return inner\n"
        "left = factory(10)\nright = factory(20)\n"
        "assert left(1) == 11\nassert right(1) == 21\n",
        encoding="utf-8",
    )
    trace = tmp_path / "trace"
    captured = cli("trace", "--calls-only", "--project-root", tmp_path, "--out", trace,
                   "--", sys.executable, entry, cwd=tmp_path)
    assert captured.returncode == 0, captured.stdout + captured.stderr
    output = tmp_path / "inventory.json.gz"
    process = cli("inventory-program", entry, "--project-root", tmp_path, "--calls", trace,
                  "--body-profile", "environment", "--out", output)
    assert process.returncode == 0, process.stdout + process.stderr
    document = read(output)
    assert document["schema_version"] == 8
    assert len(document["structured"]) == 1
    assert document["summary"]["whole_program_graph_established"] is False
    assert document["transformation_authorized"] is False
    assert document["call_source_scope"]["admissions"]
    replay = cli("check-inventory", output)
    assert replay.returncode == 0, replay.stdout + replay.stderr


@pytest.mark.parametrize("version,profile", [(7, "STRUCTURED_ENV_V1"), (8, "STRUCTURED_BODY_V1")])
def test_inventory_profile_version_cannot_reinterpret_historical_graphs(tmp_path, version, profile):
    from scar.analysis.program_inventory import ProgramInventory, inventory_program
    from scar.ir.program.functions import BodyLoweringProfile
    entry = tmp_path / "entry.py"
    entry.write_text("def f(value):\n    return value\n")
    document = deepcopy(inventory_program(entry, project_root=tmp_path,
        body_profile=BodyLoweringProfile.STRUCTURED_ENV).to_dict())
    document["schema_version"], document["profile"] = version, profile
    with pytest.raises(ValueError, match="exact structured profile"):
        ProgramInventory.from_dict(document)
