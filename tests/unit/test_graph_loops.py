from scar.analysis import graph_loop_candidates
from scar.ir import Effect, Event, ExecutionGraph, Knowledge, ProgramGraph
from scar.planner import plan_candidates


def _pure_effect():
    return Effect(
        collection_knowledge={name: Knowledge.KNOWN for name in
                              ("reads", "writes", "allocates", "frees", "aliases", "escapes")},
        rng_effect=Knowledge.NONE, may_raise=Knowledge.NONE,
        external_effect=Knowledge.NONE, ordering_effect=Knowledge.NONE)


def _graph(inputs_by_iteration):
    events = []
    for iteration, value in enumerate(inputs_by_iteration, start=1):
        events.append(Event(
            kind="loop_iteration", invocation_id=10,
            metadata={"process_id": 3, "thread_id": 4,
                      "loop_target_offset": 80, "iteration": iteration}))
        events.append(Event(
            kind="module_call", invocation_id=iteration,
            code_id="case.py:Model.forward:1:v1", duration_ns=100 + iteration,
            inputs=[value], effect=_pure_effect(),
            metadata={"process_id": 3, "thread_id": 4,
                      "parent_invocation_id": 10,
                      "loop_target_offset": 80,
                      "loop_iteration": iteration}))
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph(events))
    return graph


def test_graph_loop_candidate_uses_observed_markers_and_region_signature():
    value = {"storage_id": "storage:x", "logical_version": "storage:x@0:v0",
             "offset": 0, "shape": [4], "strides": [1],
             "dtype": "torch.float32", "device": "cpu"}
    found = graph_loop_candidates(_graph([value, value]))
    assert len(found) == 1
    assert found[0].kind == "GraphLoopInvariantCandidate"
    assert found[0].decision == "proposed"
    assert found[0].supporting_events == [1, 3]
    planned = plan_candidates(found)
    assert planned[0].decision == "rejected"
    assert any(item.name == "hoisting_preserves_graph_control"
               and item.status.value == "UNKNOWN"
               for item in planned[0].proof_obligations)


def test_graph_loop_candidate_rejects_changed_region_version():
    first = {"storage_id": "storage:x", "logical_version": "storage:x@0:v0",
             "offset": 0, "shape": [4], "strides": [1],
             "dtype": "torch.float32", "device": "cpu"}
    second = {**first, "logical_version": "storage:x@0:v1"}
    found = graph_loop_candidates(_graph([first, second]))
    assert len(found) == 1
    assert found[0].decision == "rejected"
    assert found[0].applicability == "changing_inputs_across_graph_loop_iterations"


def test_graph_loop_candidate_rejects_ambiguous_same_code_actions_in_one_iteration():
    value = {"storage_id": "storage:x", "logical_version": "storage:x@0:v0",
             "offset": 0, "shape": [4], "strides": [1],
             "dtype": "torch.float32", "device": "cpu"}
    events = [
        Event(kind="loop_iteration", invocation_id=10,
              metadata={"process_id": 3, "thread_id": 4,
                        "loop_target_offset": 80, "iteration": 1}),
        Event(kind="module_call", invocation_id=1, code_id="case:forward:v1",
              inputs=[value], effect=_pure_effect(),
              metadata={"process_id": 3, "thread_id": 4,
                        "parent_invocation_id": 10, "loop_target_offset": 80,
                        "loop_iteration": 1}),
        Event(kind="module_call", invocation_id=2, code_id="case:forward:v1",
              inputs=[value], effect=_pure_effect(),
              metadata={"process_id": 3, "thread_id": 4,
                        "parent_invocation_id": 10, "loop_target_offset": 80,
                        "loop_iteration": 1}),
        Event(kind="loop_iteration", invocation_id=10,
              metadata={"process_id": 3, "thread_id": 4,
                        "loop_target_offset": 80, "iteration": 2}),
        Event(kind="module_call", invocation_id=3, code_id="case:forward:v1",
              inputs=[value], effect=_pure_effect(),
              metadata={"process_id": 3, "thread_id": 4,
                        "parent_invocation_id": 10, "loop_target_offset": 80,
                        "loop_iteration": 2}),
    ]
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph(events))
    found = graph_loop_candidates(graph)
    assert len(found) == 1
    assert found[0].decision == "rejected"
    assert found[0].applicability == "ambiguous_graph_loop_actions"
    assert any(item.name == "aligned_graph_loop_actions"
               and item.status.value == "UNKNOWN"
               for item in found[0].proof_obligations)
