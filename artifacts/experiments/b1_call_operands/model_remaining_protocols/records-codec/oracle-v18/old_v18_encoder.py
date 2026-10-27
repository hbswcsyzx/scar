"""Freeze ProgramGraph schema 18 with the immutable pre-P4.2 encoder."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform

from scar.ir.program.codec import SCHEMA_VERSION, dumps, loads
from scar.ir.program.model import ProgramGraph, TerminatorKind
from tests.fixtures.program_invoke_subset_graphs import invoke_subset_program


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[4]
FIXTURES = REPO / "tests" / "fixtures"
WIRE_PATH = FIXTURES / "program_graph_v18_frozen.json"
PROOF_PATH = FIXTURES / "program_graph_v18_frozen.proof.json"


def main() -> None:
    graph, details = invoke_subset_program()
    if type(graph) is not ProgramGraph:
        raise TypeError("oracle fixture did not return an exact ProgramGraph")
    invocations = [row for row in graph.operations
                   if row.terminator is not None and row.terminator.kind is TerminatorKind.INVOKE]
    if len(invocations) != 1 or len(invocations[0].terminator.successors) != 1:
        raise AssertionError("fixture must contain exactly one single-completion INVOKE")
    if SCHEMA_VERSION != 18:
        raise AssertionError(f"archived encoder reports schema {SCHEMA_VERSION}, expected 18")

    wire = dumps(graph).encode("utf-8")
    document = json.loads(wire)
    if document.get("schema_version") != 18:
        raise AssertionError("archived encoder did not select schema 18")
    if "protocol_call_inputs" in document:
        raise AssertionError("post-v18 fields leaked into the archived v18 wire")
    restored = loads(wire.decode("utf-8"))
    if restored != graph or dumps(restored).encode("utf-8") != wire:
        raise AssertionError("archived v18 roundtrip changed the graph or bytes")

    WIRE_PATH.write_bytes(wire)
    proof = {
        "source_revision": "add4ba84c9529e1f864e4029bd7c145cfacdfafc",
        "schema_version": 18,
        "encoder_source_sha256": "355d5863e59a0714c14ad3e4bffb1e6423a6900b924cb94df8e7654310bc7a94",
        "fixture_builder_source_sha256": "41aba0cbde2c4d761b18b991cbccecc1f292836a88a1d79792c0896899b60dc5",
        "archive_sha256": "6e136bc23f73796b051d429489a0a707276e10913462c7d3cbc25abfcac13bc4",
        "command": "cd /tmp/scar-structured-model-280qf4mi/artifacts/experiments/b1_call_operands/model_remaining_protocols/records-codec/oracle-v18/source; source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm; PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python /tmp/scar-structured-model-280qf4mi/artifacts/experiments/b1_call_operands/model_remaining_protocols/records-codec/oracle-v18/old_v18_encoder.py",
        "fixture_sha256": hashlib.sha256(wire).hexdigest(),
        "fixture_bytes": len(wire),
        "python": platform.python_version(),
        "capability": "single-completion INVOKE; ProgramGraph format has no ExecutionModel.call_activations table",
        "details_included": sorted(details),
        "support_file": "tests/__init__.py was empty temporary namespace-import scaffolding, absent from the git archive",
    }
    PROOF_PATH.write_text(json.dumps(proof, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"schema_version": 18, "fixture_sha256": proof["fixture_sha256"],
                      "fixture_bytes": len(wire), "single_completion_invokes": len(invocations)},
                     sort_keys=True))


if __name__ == "__main__":
    main()
