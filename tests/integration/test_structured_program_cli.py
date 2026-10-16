"""Public construction/replay of structured source, without target execution."""
import gzip
import json
import subprocess
import sys

import pytest


def cli(*args):
    return subprocess.run([sys.executable, "-m", "scar.cli", *map(str, args)],
                          text=True, capture_output=True, timeout=30)


@pytest.mark.parametrize("suffix", [".json", ".json.gz"])
def test_public_loop_source_model_roundtrips_without_importing_target(tmp_path, suffix):
    marker = tmp_path / "must-not-execute"
    source = tmp_path / "original.py"
    source.write_text(f"open({str(marker)!r}, 'w').write('executed')\n"
                      "def f(items, callback):\n"
                      "    result = None\n"
                      "    for item in items:\n"
                      "        result = callback(item, item)\n"
                      "    return result\n")
    original = source.read_bytes()
    output = tmp_path / ("model" + suffix)
    built = cli("model-program", source, "--entry", "f", "--body-profile", "structured", "--out", output)
    assert built.returncode == 0, built.stdout + built.stderr
    with (gzip.open(output, "rt") if suffix.endswith("gz") else output.open()) as stream:
        document = json.load(stream)
    assert document["schema_version"] == 3
    assert document["profile"] == "STRUCTURED_BODY_V1"
    assert document["graph"]["schema_version"] == 3
    assert document["summary"]["counts"]["loops"] == 1
    assert document["summary"]["counts"]["binding_reads"] > 0
    assert document["transformation_authorized"] is False
    replay = cli("check-source-program", output)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    assert json.loads(replay.stdout)["status"] == "REPLAYED"
    assert not marker.exists() and source.read_bytes() == original
    # The old reference query cannot silently reinterpret the new profile.
    query = cli("query-frame-refs", output)
    assert query.returncode == 2


def test_public_structured_replay_rejects_missing_protocol_and_source_drift(tmp_path):
    source = tmp_path / "original.py"
    source.write_text("def f(flag):\n    while flag():\n        pass\n    return None\n")
    output = tmp_path / "model.json"
    assert cli("model-program", source, "--entry", "f", "--body-profile", "structured", "--out", output).returncode == 0
    original = json.loads(output.read_text())
    altered = json.loads(output.read_text())
    altered["structured"]["protocols"] = []
    output.write_text(json.dumps(altered))
    assert cli("check-source-program", output).returncode == 2
    output.write_text(json.dumps(original))
    source.write_text("def f(flag):\n    return 7\n")
    assert cli("check-source-program", output).returncode == 2


def test_unsupported_suspension_remains_explicit_and_cannot_claim_a_core_body(tmp_path):
    source = tmp_path / "generator.py"
    source.write_text("def f(items):\n    for item in items:\n        yield item\n")
    output = tmp_path / "model.json"
    result = cli("model-program", source, "--entry", "f", "--body-profile", "structured", "--out", output)
    assert result.returncode == 3
    document = json.loads(output.read_text())
    assert document["graph"] is None and document["structured"] is None
    assert any(gap["kind"] == "UNSUPPORTED_SIGNATURE" for gap in document["metadata"]["gaps"])
    assert document["summary"]["whole_program_coverage_established"] is False
    assert cli("check-source-program", output).returncode == 0
