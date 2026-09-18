from scar.analysis.loops import loop_invariant_candidates
from scar.ir import Effect, Event, ExecutionGraph, Knowledge
from scar.planner import plan_candidates
from scar.trace.session import TraceSession
import threading


def _pure_effect():
    return Effect(
        collection_knowledge={name: Knowledge.KNOWN for name in
                              ("reads", "writes", "allocates", "frees", "aliases", "escapes")},
        rng_effect=Knowledge.NONE, may_raise=Knowledge.NONE,
        external_effect=Knowledge.NONE, ordering_effect=Knowledge.NONE)


def test_dynamic_loop_candidate_requires_distinct_observed_iterations():
    events = [
        Event(kind="module_call", code_id="case.py:Model:1:None:v1",
              duration_ns=100, inputs=[{"logical_version": "x:v0", "shape": [2]}],
              metadata={"parent_invocation_id": 10, "loop_target_offset": 20,
                        "loop_iteration": 1}, effect=_pure_effect()),
        Event(kind="module_call", code_id="case.py:Model:1:None:v1",
              duration_ns=120, inputs=[{"logical_version": "x:v0", "shape": [2]}],
              metadata={"parent_invocation_id": 10, "loop_target_offset": 20,
                        "loop_iteration": 2}, effect=_pure_effect()),
    ]
    candidates = loop_invariant_candidates(ExecutionGraph(events))
    assert len(candidates) == 1
    assert candidates[0].applicability == "same_inputs_across_loop_iterations"
    assert candidates[0].decision == "proposed"
    assert candidates[0].backend == "exact_reuse"
    assert candidates[0].supporting_events == [0, 1]
    planned = plan_candidates(candidates)
    assert planned[0].decision == "rejected"
    assert "unknown" in (planned[0].rejection_reason or "")


def test_dynamic_loop_candidate_rejects_changed_inputs():
    events = [
        Event(kind="module_call", code_id="model", inputs=[{"logical_version": "x:v0"}],
              metadata={"parent_invocation_id": 1, "loop_target_offset": 8,
                        "loop_iteration": 1}, effect=_pure_effect()),
        Event(kind="module_call", code_id="model", inputs=[{"logical_version": "x:v1"}],
              metadata={"parent_invocation_id": 1, "loop_target_offset": 8,
                        "loop_iteration": 2}, effect=_pure_effect()),
    ]
    candidates = loop_invariant_candidates(ExecutionGraph(events))
    assert candidates[0].applicability == "changing_inputs_across_loop_iterations"
    assert candidates[0].rejection_reason is not None


def test_dynamic_loop_candidate_uses_outer_loop_scope_for_nested_actions():
    events = [
        Event(kind="module_call", code_id="model",
              inputs=[{"logical_version": "x:v0"}],
              metadata={"parent_invocation_id": 8,
                        "loop_parent_invocation_id": 10,
                        "loop_target_offset": 20, "loop_iteration": 1},
              effect=_pure_effect()),
        Event(kind="module_call", code_id="model",
              inputs=[{"logical_version": "x:v0"}],
              metadata={"parent_invocation_id": 8,
                        "loop_parent_invocation_id": 10,
                        "loop_target_offset": 20, "loop_iteration": 2},
              effect=_pure_effect()),
    ]
    candidates = loop_invariant_candidates(ExecutionGraph(events))
    assert len(candidates) == 1
    assert candidates[0].proof_obligations[0].details["parent_invocation_id"] == 10


def test_parent_metadata_propagates_nearest_outer_active_loop(tmp_path):
    session = TraceSession(tmp_path / "trace")
    thread = threading.get_ident()
    try:
        session.call_stacks[thread] = [(11, 3, 0, None), (22, 4, 0, None)]
        session.active_loops[11] = (80, 2)
        metadata = session._parent_metadata()
    finally:
        session.close()
    assert metadata["parent_invocation_id"] == 4
    assert metadata["loop_target_offset"] == 80
    assert metadata["loop_iteration"] == 2
    assert metadata["loop_parent_invocation_id"] == 3
