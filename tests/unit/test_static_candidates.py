import json

from scar.analysis import loop_invariant_candidates
from scar.ir import from_source


def test_loop_invariant_detector_is_graph_based_and_conservative(tmp_path):
    source = tmp_path / "loop.py"
    source.write_text("scale = 2\nfor i in range(3):\n    y = i * scale\nprint(y)\n")
    graph = from_source(source)
    found = loop_invariant_candidates(graph)
    assert found
    assert all(item.kind == "LoopInvariantCandidate" for item in found)
    assert all(item.evidence == "Inferred" and item.decision == "rejected" for item in found)
    assert all(":i" not in item.reason for item in found)


def test_loop_invariant_detector_rejects_visible_mutation(tmp_path):
    source = tmp_path / "mutating.py"
    source.write_text("x = 0\nfor i in range(3):\n    x = x + i\nprint(x)\n")
    graph = from_source(source)
    found = loop_invariant_candidates(graph)
    assert not any("static_state:" in item.reason and ":x" in item.reason for item in found)
