import json

from scar.analysis.constants import constant_candidates, find_constant_uses
from scar.analysis.rejection_audit import audit_report
from scar.analysis.topdown import topdown_report
from scar.ir import GraphNode, GraphEdge, NodeKind, Opportunity, ProgramGraph, ProofStatus, proof


def _candidate(*obligations):
    return {
        "kind": "SyntheticCandidate",
        "code_id": "demo",
        "decision": "rejected",
        "supporting_events": [2, 3],
        "proof_obligations": [item for item in obligations],
    }


def _obligation(name, category, status, reason):
    return {"name": name, "category": category, "status": status,
            "reason": reason, "required": True}


def test_rejection_audit_separates_proven_blocker_from_evidence_gap():
    report = audit_report({
        "status": "Observed",
        "opportunities": [
            _candidate(_obligation("effects_allow_exact_reuse", "legality", "UNKNOWN", "effect incomplete")),
            _candidate(_obligation("no_intervening_input_write", "legality", "DISPROVEN", "intervening write")),
        ],
        "graph_opportunities": [],
    })
    assert report["disposition"] == {"EVIDENCE_GAP": 1, "PROVEN_BLOCKER": 1}
    assert report["root_causes"]["effect_completeness_missing"] == 1
    assert report["root_causes"]["intervening_write_observed"] == 1


def _complete_effect():
    return {
        "reads": [], "writes": [], "allocates": [], "frees": [],
        "aliases": [], "escapes": [], "rng_effect": "NONE",
        "may_raise": "NONE", "external_effect": "NONE",
        "ordering_effect": "NONE",
        "collection_knowledge": {name: "KNOWN" for name in
                                  ("reads", "writes", "allocates", "frees", "aliases", "escapes")},
    }


def test_topdown_region_summary_preserves_unknown_effects():
    graph = ProgramGraph()
    for index, parent in ((0, None), (1, 0), (2, 1), (3, 1)):
        graph.add_node(GraphNode(
            f"invocation:{index}:{index}", NodeKind.ACTION, "module_call",
            attrs={"process_id": 1, "duration_ns": 10,
                   "effect": _complete_effect() if index != 2 else {
                       **_complete_effect(),
                       "collection_knowledge": {"reads": "UNKNOWN", "writes": "UNKNOWN",
                                                 "allocates": "UNKNOWN", "frees": "UNKNOWN",
                                                 "aliases": "UNKNOWN", "escapes": "UNKNOWN"},
                   }},
        ))
        if parent is not None:
            graph.edges.append(GraphEdge(f"invocation:{parent}:{parent}",
                                         f"invocation:{index}:{index}", "controls_dynamic"))
    graph.add_node(GraphNode("state:x", NodeKind.STATE, "logical_version"))
    graph.edges.append(GraphEdge("state:x", "invocation:2:2", "reads"))
    graph.edges.append(GraphEdge("invocation:0:0", "state:x", "writes"))
    candidate = Opportunity(
        kind="ReuseCandidate", code_id="demo", evidence="Observed",
        applicability="same", guard="guard", reason="repeat",
        supporting_events=[2, 3], expected_savings_ns=10,
    )
    report = topdown_report(graph, [candidate])
    assert report["counts"]["placements"] == 1
    placement = report["placements"][0]
    assert placement["status"] == "UNKNOWN"
    assert "candidate_effect_contract_incomplete" in placement["unknown_reasons"]


def test_topdown_proposes_higher_boundary_when_input_origin_is_outer():
    graph = ProgramGraph()
    for index, parent in ((0, None), (1, 0), (2, 1), (3, 1)):
        graph.add_node(GraphNode(
            f"invocation:{index}:{index}", NodeKind.ACTION, "module_call",
            attrs={"process_id": 1, "duration_ns": 10, "effect": _complete_effect()},
        ))
        if parent is not None:
            graph.edges.append(GraphEdge(f"invocation:{parent}:{parent}",
                                         f"invocation:{index}:{index}", "controls_dynamic"))
    graph.add_node(GraphNode("state:x", NodeKind.STATE, "logical_version"))
    graph.edges.append(GraphEdge("state:x", "invocation:2:2", "reads"))
    graph.edges.append(GraphEdge("invocation:0:0", "state:x", "writes"))
    candidate = Opportunity(
        kind="ReuseCandidate", code_id="demo", evidence="Observed",
        applicability="same", guard="guard", reason="repeat",
        supporting_events=[2, 3], expected_savings_ns=10,
    )
    placement = topdown_report(graph, [candidate])["placements"][0]
    assert placement["status"] == "PROPOSED"
    assert placement["proposed_region"] == "invocation:0:0"


def test_constant_provenance_resolves_local_import_without_importing_it(tmp_path):
    package = tmp_path / "demo_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "constants.py").write_text(
        "VALUE = dict(mean=[1.0, 2.0], std=[3.0, 4.0])\n"
        "RUNTIME = make_value()\n"
    )
    source = tmp_path / "program.py"
    source.write_text("import demo_pkg as pkg\nx = pkg.constants.VALUE\n")
    uses = find_constant_uses(source, project_root=tmp_path)
    assert len(uses) == 1
    assert uses[0].definition.qualified_name == "demo_pkg.constants.VALUE"
    assert uses[0].definition.value == {"mean": [1.0, 2.0], "std": [3.0, 4.0]}
    candidate = constant_candidates(uses)[0]
    assert candidate.proof_obligations[0].status == ProofStatus.PROVEN
    # The literal itself is statically known, but importing this module also
    # executes the unresolved ``make_value()`` assignment.  Inlining the
    # value therefore cannot silently remove the module initialization.
    assert candidate.proof_obligations[1].status == ProofStatus.UNKNOWN


def test_constant_provenance_marks_literal_only_import_chain_pure(tmp_path):
    package = tmp_path / "pure_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("\n")
    (package / "constants.py").write_text(
        "VALUE = {'mean': [1.0, 2.0], 'std': [3.0, 4.0]}\n"
    )
    source = tmp_path / "program.py"
    source.write_text("import pure_pkg.constants as constants\nx = constants.VALUE\n")
    candidate = constant_candidates(
        find_constant_uses(source, project_root=tmp_path)
    )[0]
    assert candidate.proof_obligations[0].status == ProofStatus.PROVEN
    assert candidate.proof_obligations[1].status == ProofStatus.PROVEN
