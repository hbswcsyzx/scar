"""Archive this bounded P4 followup; this command never starts tests."""
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
BASE = "7dd8c54b8d8cfdb3454b9f3b671f3412d1a914f0"
OLD = HERE.parent / "model_remaining_protocols"
MANIFEST = HERE / "checkpoint.json"
DOCS = ("docs/M1_PROTOCOL_FOLLOWUP_PLAN.md", "docs/M1_PROTOCOL_FOLLOWUP_PROGRESS.md",
        "docs/STATUS.md", "docs/ROADMAP.md")


def git(*args, cwd=ROOT):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True).stdout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protections():
    expected = json.loads((OLD / "protected.before.json").read_text())
    for state in expected.values():
        assert git("rev-parse", "HEAD", cwd=state["path"]).decode().strip() == state["head"]
        assert git("status", "--porcelain=v1", cwd=state["path"]).decode() == state["status"]
    fixtures = {}
    with tarfile.open(fileobj=io.BytesIO(git("archive", BASE, "tests/fixtures"))) as archive:
        for member in archive.getmembers():
            if member.isfile():
                content = archive.extractfile(member).read()
                assert (ROOT / member.name).read_bytes() == content, member.name
                fixtures[member.name] = hashlib.sha256(content).hexdigest()
    frozen = ("docs/M1_PROTOCOL_CONTRACT.md", "docs/M1_PROTOCOL_CONNECTION_CONTRACT.md")
    for name in frozen:
        assert (ROOT / name).read_bytes() == git("show", f"{BASE}:{name}"), name
    # Mutable status docs are intentionally excluded from the old archive's
    # check. Its actual evidence bytes must still match their original archive.
    previous = json.loads((OLD / "implementation/checkpoint.json").read_text())
    for name, digest in previous["files"].items():
        if name.startswith("artifacts/"):
            assert sha(ROOT / name) == digest, name
    return expected, fixtures


def cases(path):
    rows = list(ET.parse(path).iter("testcase"))
    assert rows and all(not any(case.find(tag) is not None
        for tag in ("failure", "error", "skipped")) for case in rows)
    names = {(case.get("classname"), case.get("name")) for case in rows}
    assert len(names) == len(rows), "duplicate case identity"
    return names


def focused():
    folder = HERE / "final-focused"
    result = json.loads((folder / "result.json").read_text())
    assert result["returncode"] == 0 and result["source_unchanged"] is True
    digest, sources = fingerprint()
    assert digest == result["source_sha256_before"] == result["source_sha256_after"]
    current = cases(folder / "junit.xml")
    prior = cases(OLD / "implementation/final-focused/junit.xml")
    assert prior <= current, "previous affected case identity removed"
    return digest, sources, len(current), len(prior)


def files():
    paths = [path for path in HERE.rglob("*") if path.is_file()
             and path != MANIFEST and "__pycache__" not in path.parts]
    paths += [ROOT / name for name in DOCS]
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)}


def main():
    protected, fixtures = protections()
    digest, sources, count, prior = focused()
    record = {"status": "PASS_WITH_SCOPE_WIP_ARCHIVE", "base_revision": BASE,
        "source_sha256": digest, "source_files": len(sources), "focused_cases": count,
        "prior_affected_cases_retained": prior, "original_fixtures": fixtures,
        "obligation_groups": [*(f"F{i:02}" for i in range(12, 25)), "X25", "X26", "X27"],
        "completed_obligation_groups": [], "p4_complete": False, "m0_m2_complete": False,
        "full_regression_on_this_source": False, "source_runtime_verified": False,
        "transformation_authorized": False, "new_lewm_speedup": False,
        "tests_started_by_archive_check": 0, "protected": protected, "files": files()}
    if sys.argv[1:] == ["--write"]:
        assert not MANIFEST.exists(), "never overwrite an archive"
        MANIFEST.write_text(json.dumps(record, indent=2) + "\n")
    else:
        assert sys.argv[1:] == ["--check"]
        assert record == json.loads(MANIFEST.read_text()), "source/evidence changed"
    print(json.dumps({key: record[key] for key in ("status", "source_sha256",
        "source_files", "focused_cases", "prior_affected_cases_retained", "p4_complete",
        "m0_m2_complete", "full_regression_on_this_source", "tests_started_by_archive_check")}, indent=2))


if __name__ == "__main__":
    main()
