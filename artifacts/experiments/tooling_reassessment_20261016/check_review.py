"""Check this documentation review without importing Torch or running tests."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
DOCS = (
    "README.md", "docs/STATUS.md", "docs/TOOLING_SURVEY.md",
    "docs/WHOLE_PROGRAM_MODEL_PLAN.md", "docs/MODELING_REUSE_DECISION.md",
    "docs/M1_CLEANUP_INTERFACES.md",
)


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


source_hash, source_files = runpy.run_path(str(ROOT / "scripts/run_gate.py"))["fingerprint"]()
previous = json.loads((ROOT / "artifacts/experiments/b1_call_operands/"
                       "model_native_interfaces/full/report.json").read_text())
bad_links, checked = [], 0
for relative in DOCS:
    document = ROOT / relative
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", document.read_text()):
        target = target.strip("<>").split("#", 1)[0]
        if not target or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target):
            continue
        checked += 1
        if not (document.parent / target).exists():
            bad_links.append({"document": relative, "target": target})

changed = git(ROOT, "diff", "--name-only").splitlines()
lewm = Path("/home/zyf/AAA/le-wm")
report = {
    "schema": "scar.tooling-reassessment-review",
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "base_revision": "78c5fdaaea5b189c0de8c3d9f26159912d615486",
    "revision_during_check": git(ROOT, "rev-parse", "HEAD"),
    "scope": "Documentation/source/official-reference review, not adapter or model acceptance",
    "new_product_code": False, "new_tests_run": False, "new_capture": False,
    "new_lewm_run": False, "external_links_validated_by_this_script": False,
    "source_sha256": source_hash, "source_file_count": len(source_files),
    "same_source_as_previous_frozen_regression": source_hash == previous["expected_source_sha256"],
    "previous_frozen_regression": {"revision": previous["expected_revision"],
                                  "status": previous["status"], "counts": previous["counts"]},
    "changed_tracked_paths": changed,
    "tracked_changes_are_docs_only": all(p.endswith(".md") for p in changed),
    "local_document_links_checked": checked, "missing_local_links": bad_links,
    "document_sha256": {p: digest(ROOT / p) for p in DOCS},
    "review_file_sha256": {str(p.relative_to(ROOT)): digest(p)
                           for p in sorted((OUT / "review").glob("*.md"))},
    "lewm_revision": git(lewm, "rev-parse", "HEAD"),
    "lewm_status": git(lewm, "status", "--porcelain=v1"),
}
ok = (report["same_source_as_previous_frozen_regression"]
      and report["tracked_changes_are_docs_only"] and not bad_links
      and report["lewm_status"] == "")
report["status"] = "PASS" if ok else "FAIL"
(OUT / "review_checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"status": report["status"], "source_files": len(source_files),
                  "source_unchanged": report["same_source_as_previous_frozen_regression"],
                  "local_links_checked": checked, "missing_links": bad_links}, ensure_ascii=False))
raise SystemExit(0 if ok else 1)
