"""Archive a scoped P4 implementation checkpoint; never starts tests."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
BASE = "add4ba84c9529e1f864e4029bd7c145cfacdfafc"
MANIFEST = HERE / "checkpoint.json"


def git(*args, cwd=ROOT):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True).stdout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protections():
    expected = json.loads((PARENT / "protected.before.json").read_text())
    for state in expected.values():
        assert git("rev-parse", "HEAD", cwd=state["path"]).decode().strip() == state["head"]
        assert git("status", "--porcelain=v1", cwd=state["path"]).decode() == state["status"]
    raw = git("archive", BASE, "tests/fixtures")
    fixtures = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive.getmembers():
            if member.isfile():
                before = archive.extractfile(member).read()
                assert (ROOT / member.name).read_bytes() == before, member.name
                fixtures[member.name] = hashlib.sha256(before).hexdigest()
    for name in ("docs/M1_PROTOCOL_CONTRACT.md", "docs/M1_PROTOCOL_CONNECTION_CONTRACT.md"):
        assert (ROOT / name).read_bytes() == git("show", f"{BASE}:{name}"), name
    # Historical evidence stays intact even though later mutable status docs
    # and product source intentionally change after that old checkpoint.
    previous = json.loads((PARENT / "intermediate-checkpoint.json").read_text())
    for name, digest in previous["files"].items():
        if name.startswith("artifacts/"):
            assert sha(ROOT / name) == digest, name
    return expected, fixtures


def focused():
    folder = HERE / "final-focused"
    result = json.loads((folder / "result.json").read_text())
    assert result["returncode"] == 0 and result["source_unchanged"] is True
    digest, sources = fingerprint()
    assert digest == result["source_sha256_before"] == result["source_sha256_after"]
    cases = list(ET.parse(folder / "junit.xml").iter("testcase"))
    assert cases and all(not list(case.iter("failure")) and not list(case.iter("error"))
                         and not list(case.iter("skipped")) for case in cases)
    assert len({(case.get("classname"), case.get("name")) for case in cases}) == len(cases)
    return digest, sources, len(cases)


def files():
    roots = (PARENT, ROOT / "artifacts/experiments/b1_call_operands/model_protocol_implementation")
    selected = [path for root in roots if root.exists() for path in root.rglob("*")
                if path.is_file() and path != MANIFEST and "__pycache__" not in path.parts]
    selected += [ROOT / name for name in ("docs/M1_PROTOCOL_CONNECTION_IMPLEMENTATION.md",
                                         "docs/M1_REMAINING_PROTOCOL_PLAN.md",
                                         "docs/STATUS.md", "docs/ROADMAP.md")]
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(set(selected))}


def main():
    protected, fixtures = protections()
    digest, sources, cases = focused()
    record = {"status": "PASS_WITH_SCOPE_WIP_ARCHIVE", "base_revision": BASE,
              "source_sha256": digest, "source_files": len(sources), "focused_cases": cases,
              "obligation_groups": [*(f"F{i:02}" for i in range(12, 25)), "X25", "X26", "X27"],
              "completed_obligation_groups": [], "p4_complete": False, "m0_m2_complete": False,
              "full_regression_on_this_source": False, "tests_started_by_archive_check": 0,
              "source_runtime_verified": False, "transformation_authorized": False,
              "new_lewm_speedup": False, "protected": protected,
              "original_fixtures": fixtures, "files": files()}
    if sys.argv[1:] == ["--write"]:
        assert not MANIFEST.exists(), "never overwrite an archived checkpoint"
        MANIFEST.write_text(json.dumps(record, indent=2) + "\n")
    else:
        assert sys.argv[1:] == ["--check"]
        assert record == json.loads(MANIFEST.read_text()), "checkpoint source/evidence changed"
    print(json.dumps({key: record[key] for key in (
        "status", "source_sha256", "source_files", "focused_cases", "p4_complete",
        "m0_m2_complete", "full_regression_on_this_source", "tests_started_by_archive_check")}, indent=2))


if __name__ == "__main__":
    main()
