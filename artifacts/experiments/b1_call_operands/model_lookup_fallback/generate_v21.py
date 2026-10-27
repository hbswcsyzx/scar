"""Generate a Program21 oracle using only the immutable pre-fallback encoder.

Run explicitly in conda lewm. Each invocation requires a new --out directory;
failed attempts and their commands/output are never overwritten. No tests or
workloads are executed. The archived source tree is temporary; its tar stays.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile


REVISION = "8585d7f2aa013896fa58c3759d540338b78d43a5"
PROFILE = "exception_match_program(mode='invoke', input_kind='packet')"
PRODUCER = r'''
import hashlib
import inspect
import json
from pathlib import Path
import sys

import scar.ir.program.codec as codec
import tests.fixtures.program_exception_match_graphs as fixture

tree = Path.cwd().resolve()
modules = {"encoder": codec, "fixture": fixture}
sources = {}
for label, module in modules.items():
    path = Path(inspect.getfile(module)).resolve()
    assert path.is_relative_to(tree), (label, path, tree)
    sources[label] = {"path": str(path.relative_to(tree)),
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
assert codec.SCHEMA_VERSION == 21
graph, _ = fixture.exception_match_program(mode="invoke", input_kind="packet")
wire = codec.dumps(graph).encode("ascii")
document = json.loads(wire)
assert document["schema_version"] == 21
assert document["exception_matches"]
assert not document["protocol_scopes"] and not document["protocol_bindings"]
assert codec.dumps(codec.loads(wire.decode("ascii"))).encode("ascii") == wire
Path(sys.argv[1]).write_bytes(wire)
print(json.dumps({"schema_version": 21, "python_version": sys.version,
                  "fixture_bytes": len(wire),
                  "fixture_sha256": hashlib.sha256(wire).hexdigest(),
                  "sources": sources}, sort_keys=True))
'''


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--install-fixture", action="store_true")
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.out.resolve()
    if out.exists():
        parser.error("--out must be a new directory; preserve previous attempts")
    fixtures = repo / "tests/fixtures"
    destinations = (fixtures / "program_graph_v21_frozen.json",
                    fixtures / "program_graph_v21_frozen.proof.json")
    if args.install_fixture and any(path.exists() for path in destinations):
        parser.error("Program21 fixture/proof already exists; refusing to overwrite")
    out.mkdir(parents=True)
    archive = out / "source-v21.tar"
    # Only imports/fixture inputs are needed. Do not duplicate historical
    # artifacts or unrelated tracked data from the immutable revision.
    archive_command = ["git", "-C", str(repo), "archive", "--format=tar", REVISION,
                       "scar", "tests", "pyproject.toml"]
    _json(out / "archive-command.json", archive_command)
    with archive.open("wb") as stream:
        captured = subprocess.run(archive_command, stdout=stream, stderr=subprocess.PIPE, check=False)
    (out / "archive-stderr.log").write_bytes(captured.stderr)
    _json(out / "archive-result.json", {"returncode": captured.returncode,
        "source_revision": REVISION, "archive_sha256": _sha(archive.read_bytes()),
        "archive_bytes": archive.stat().st_size})
    if captured.returncode:
        return captured.returncode
    payload = out / "program_graph_v21_frozen.json"
    with tempfile.TemporaryDirectory(prefix="program21-source-", dir=out) as temporary:
        tree = Path(temporary)
        with tarfile.open(archive) as source:
            source.extractall(tree, filter="data")
        expected_sources = {}
        for label, name in (("encoder", "scar/ir/program/codec.py"),
                            ("fixture", "tests/fixtures/program_exception_match_graphs.py")):
            original = subprocess.run(["git", "-C", str(repo), "show", f"{REVISION}:{name}"],
                                      capture_output=True, check=False)
            if original.returncode:
                (out / "source-check-stderr.log").write_bytes(original.stderr)
                return original.returncode
            digest = _sha((tree / name).read_bytes())
            assert digest == _sha(original.stdout), name
            expected_sources[label] = {"path": name, "sha256": digest}
        _json(out / "source-check.json", {"revision": REVISION, "sources": expected_sources})
        environment = dict(os.environ, PYTHONPATH=str(tree), PYTHONDONTWRITEBYTECODE="1",
                           PYTHONNOUSERSITE="1")
        command = [sys.executable, "-c", PRODUCER, str(payload)]
        _json(out / "command.json", {"argv": command, "cwd": str(tree),
            "environment": {key: environment[key] for key in
                            ("PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE")},
            "source_revision": REVISION})
        result = subprocess.run(command, cwd=tree, env=environment, capture_output=True, check=False)
        (out / "stdout.log").write_bytes(result.stdout)
        (out / "stderr.log").write_bytes(result.stderr)
        (out / "exit-code.txt").write_text(str(result.returncode) + "\n", encoding="ascii")
        _json(out / "result.json", {"returncode": result.returncode,
                                    "source_revision": REVISION})
        if result.returncode:
            return result.returncode
        receipt = json.loads(result.stdout)
        assert receipt["sources"] == expected_sources
        for source in expected_sources.values():
            assert _sha((tree / source["path"]).read_bytes()) == source["sha256"]
    proof = {"source_revision": REVISION, "schema_version": 21,
        "source_archive": str(archive.relative_to(repo)) if archive.is_relative_to(repo) else str(archive),
        "source_archive_sha256": _sha(archive.read_bytes()),
        "encoder_source_sha256": receipt["sources"]["encoder"]["sha256"],
        "fixture_source_sha256": receipt["sources"]["fixture"]["sha256"],
        "generator_sha256": _sha(Path(__file__).read_bytes()),
        "python_version": receipt["python_version"],
        "fixture_profile": PROFILE, "fixture_bytes": receipt["fixture_bytes"],
        "fixture_sha256": receipt["fixture_sha256"],
        "generation_command": str(out / "command.json"),
        "generated_by": "git archive of source_revision; isolated cwd/PYTHONPATH; old codec only",
        "source_tree_cleanup": "TemporaryDirectory removed only the owned extraction; tar retained"}
    assert _sha(payload.read_bytes()) == proof["fixture_sha256"]
    _json(out / "program_graph_v21_frozen.proof.json", proof)
    if args.install_fixture:
        shutil.copyfile(payload, destinations[0])
        shutil.copyfile(out / "program_graph_v21_frozen.proof.json", destinations[1])
    print(json.dumps(proof, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
