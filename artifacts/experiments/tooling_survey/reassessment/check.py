"""Validate this documentation/capability review without rerunning workloads."""
from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
EXPECTED_HEAD = "845ebb4381f656e5c51b692e688444cd29da8a91"
EXPECTED_PRODUCT = "06773c8c8863910cffb70d5859e5019dc040f0a5e8903799abeb837bb52d4a53"
DOCS = (
    "docs/TOOLING_SURVEY.md", "docs/MODELING_INTEGRATION.md",
    "docs/STATUS.md", "docs/WHOLE_PROGRAM_MODEL_PLAN.md",
)


def git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


head = git("rev-parse", "HEAD")
assert head == EXPECTED_HEAD, (head, EXPECTED_HEAD)
assert not git("diff", "--cached", "--name-only"), "unexpected staged changes"
changed = set(git("diff", "--name-only").splitlines())
assert changed == set(DOCS), changed
subprocess.run(["git", "diff", "--check", "--", *DOCS], cwd=ROOT, check=True)
spec = importlib.util.spec_from_file_location("scar_review_fingerprint", ROOT / "scripts/run_gate.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
fingerprint, product_files = module.fingerprint()
assert fingerprint == EXPECTED_PRODUCT and len(product_files) == 356

checked_links = []
for relative in (*DOCS, *[str(path.relative_to(ROOT)) for path in OUT.glob("*-review.md")]):
    source = ROOT / relative
    for match in re.finditer(r"\]\(([^)]+)\)", source.read_text()):
        target = match.group(1).split("#", 1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        resolved = (source.parent / target).resolve()
        assert resolved.exists(), (relative, target)
        checked_links.append({"document": relative, "target": target})

probe_dir = OUT / "memory-provider"
probe = json.loads((probe_dir / "results.json").read_text())
assert probe["capture_count"] == 1
assert all(stage["status"] == "PASS" for stage in probe["stages"].values())
assert probe["stages"]["experimental_event_tree"]["record_count"] == 34
assert probe["stages"]["memory_profile"]["node_count"] == 12
assert not probe["cuda_initialized_before"] and not probe["cuda_initialized_after"]
assert probe["scar_imported"] is False
assert sha(probe_dir / "probe.py") == probe["source_sha256"]
for path, digest in probe["source_evidence"].items():
    assert sha(Path(path)) == digest, path
transitions = probe["checks"]["two_sequential_schema_based_mutation_increments"]
assert [(item["before"], item["after"]) for item in transitions] == [(0, 1), (1, 2)]

lewm = Path("/home/zyf/AAA/le-wm")
lewm_head = git("rev-parse", "HEAD", cwd=lewm)
assert lewm_head == "f70fed80288462ca4d006cb3607ec6da6eaa851f"
assert not git("status", "--porcelain", cwd=lewm)
assert git("rev-parse", "HEAD") == head
assert module.fingerprint()[0] == fingerprint

report = {
    "schema": "scar.tooling-reassessment", "schema_version": 1,
    "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "status": "PASS", "scope": "documentation, independent source reviews and one CPU capability probe",
    "revision_before_documentation_commit": head,
    "command": "conda activate lewm; PYTHONDONTWRITEBYTECODE=1 python artifacts/experiments/tooling_survey/reassessment/check.py",
    "python": sys.version, "product_fingerprint": fingerprint,
    "product_file_count": len(product_files), "product_unchanged": True,
    "documentation_sha256": {name: sha(ROOT / name) for name in DOCS},
    "local_links_checked": checked_links,
    "probe": {"torch": probe["torch"], "torch_git_revision": probe["torch_git_revision"],
              "stages": probe["stages"], "checks": probe["checks"],
              "cuda_initialized": False, "scar_imported": False},
    "lewm_head": lewm_head, "lewm_git_clean": True,
    "not_claimed": ["new full regression", "adapter integration", "M1/M2 complete",
                    "first-stage complete", "whole-program LeWM graph", "new GPU profiling",
                    "automatic transform", "capture overhead comparison", "clean speedup"],
}
(OUT / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
artifacts = {str(path.relative_to(OUT)): sha(path)
             for path in sorted(OUT.rglob("*")) if path.is_file() and path.name != "MANIFEST.json"}
(OUT / "MANIFEST.json").write_text(json.dumps({"schema": "scar.review-artifact-manifest",
    "schema_version": 1, "sha256": artifacts}, indent=2) + "\n")
print(json.dumps({"status": "PASS", "product_files": len(product_files),
                  "local_links_checked": len(checked_links), "probe_capture_count": 1,
                  "lewm_git_clean": True}))
