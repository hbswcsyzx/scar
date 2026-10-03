"""An explicit report query is neither target execution nor a selected rewrite."""
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.measure_static_motion_v2 import source_motion_report


def test_measurement_query_preserves_source_and_replays_exact_ledger(tmp_path):
    from scar.analysis.proof_ledger_v2 import ProofContext, ProofLedger, ProofQ, ProofRequest
    from scar.analysis.regions_v2 import RegionInventory
    from scar.ir.control_flow_v2 import SourceControlFlowGraph
    from scar.ir.record_codec import decode
    from scar.ir.semantics_v2 import SourceSemanticsGraph
    from scar.ir.v2 import EvidenceGraph, IRBundle, ValueGraph
    from scar.ir.v2.codec import semantic_from_dict

    source = tmp_path / "program.py"
    sentinel = tmp_path / "executed"
    source.write_text(
        "def arbitrary_names():\n"
        "    first = ()\n"
        "    second = 1 + 2\n"
        "    third = first\n"
        "    return third\n"
        f"open({str(sentinel)!r}, 'w').write('executed')\n"
        "raise RuntimeError('never execute target')\n"
    )
    original = source.read_bytes()
    output = tmp_path / "query.json.gz"
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "scripts/measure_static_motion_v2.py", str(source),
        "--statement-line", "4", "--after-line", "2", "--out", str(output)],
        cwd=root, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(gzip.decompress(output.read_bytes()))
    assert report["decision"] == {"legality_status": "NEEDS_CONTRACT", "applied": False,
                                   "selection_status": "NOT_SELECTED", "cost_status": "PENDING"}
    assert report["summary"]["q_assumptions"] == 0
    assert len(report["summary"]["obligations"]) == 6
    assert source.read_bytes() == original and not sentinel.exists()
    metadata = json.loads(output.with_suffix(".measurement.json").read_text())
    assert json.loads(result.stdout) == metadata
    assert metadata["decision"] == report["decision"]
    semantic = semantic_from_dict(report["semantic"])
    semantics = SourceSemanticsGraph.from_dict(report["source_semantics"], semantic)
    control = SourceControlFlowGraph.from_dict(report["control_flow"])
    bundle = IRBundle(semantic, EvidenceGraph(), ValueGraph(), source_semantics=semantics)
    inventory = RegionInventory.from_dict(report["regions"], bundle=bundle)
    context = ProofContext(bundle, semantics, inventory, inventory.scope,
                           decode(ProofQ, report["q"]),
                           source_texts={str(source): source.read_text()},
                           source_control_flow=control)
    request = decode(ProofRequest, report["request"])
    ledger = ProofLedger.from_dict(report["ledger"], context=context, request=request)
    assert ledger.to_dict() == report["ledger"]


def test_explicit_motion_query_rejects_ambiguous_lines_and_forged_q(tmp_path):
    source = tmp_path / "program.py"
    source.write_text("def f():\n    a = ()\n    b = 3\n    c = a\n    return c\n")
    with pytest.raises(ValueError, match="exactly one"):
        source_motion_report(source, statement_line=999, after_line=2)
    with pytest.raises((ValueError, TypeError)):
        source_motion_report(source, statement_line=4, after_line=2,
                             q_document={"scope": "unbound", "assumptions": [], "forged": True})
