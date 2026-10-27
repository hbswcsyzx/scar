"""Correct only the initial review harness's two-domain assumption."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys

from scar.ir.program.model import AccessMode
from scar.ir.program.validation import validate
from tests.fixtures.program_publication_graphs import publication_program


graph = publication_program(strict_subset=True)
row, = graph.body_outcome_commits
commit = next(op for op in graph.operations if op.id == row.operation)
retained = tuple(access for access in commit.accesses if access.mode is AccessMode.READ_WRITE)
removed = {access.before for access in commit.accesses if access.mode is AccessMode.READ}
assert retained and removed
commit = replace(commit, accesses=retained,
                 uses=tuple(use for use in commit.uses if use.id not in removed))
graph = replace(graph, operations=tuple(commit if op.id == commit.id else op for op in graph.operations))
issues = validate(graph)
result = {
    "name": "write_subset_omits_all_unaccessed_read_domains",
    "scope": "one IR case correcting only review-harness assumption; no product changes",
    "python": sys.version, "executable": sys.executable,
    "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
    "initial_script_sha256": sha256(Path(__file__).with_name("integration_review_probe.py").read_bytes()).hexdigest(),
    "validator_sha256": sha256(Path("scar/ir/program/lifecycle_validation.py").read_bytes()).hexdigest(),
    "lifecycle_domain_count": len(graph.driver_interfaces[0].lifecycle),
    "write_count": len(retained), "omitted_read_count": len(removed),
    "actual_codes": sorted({issue.code for issue in issues}),
    "passed": not issues,
}
rendered = json.dumps(result, indent=2, sort_keys=True)
Path(__file__).with_suffix(".json").write_text(rendered + "\n")
print(rendered)
raise SystemExit(0 if result["passed"] else 1)
