from scar.analysis import graph_candidates
from scar.ir import (Effect, Event, ExecutionGraph, Knowledge, ProgramGraph,
                     ProofStatus)
from scar.planner import plan_candidates


def _complete_pure_effect():
    return Effect(
        rng_effect=Knowledge.NONE, may_raise=Knowledge.NONE,
        external_effect=Knowledge.NONE, ordering_effect=Knowledge.NONE,
        collection_knowledge={name: Knowledge.KNOWN for name in
                              ("reads", "writes", "allocates", "frees", "aliases", "escapes")})


def _graph(events):
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph(events))
    return graph


def test_graph_candidate_uses_read_edges_and_keeps_cost_unknown():
    value = {"object_id": "py:x", "storage_id": "storage:x",
             "logical_version": "storage:x@0:v0", "shape": [2],
             "strides": [1], "dtype": "torch.float32", "device": "cpu"}
    graph = _graph([
        Event(kind="module_call", code_id="user:work", invocation_id=1,
              inputs=[value], duration_ns=10, effect=_complete_pure_effect()),
        Event(kind="module_call", code_id="user:work", invocation_id=2,
              inputs=[value], duration_ns=100, effect=_complete_pure_effect()),
    ])
    found = graph_candidates(graph)
    assert len(found) == 1
    assert found[0].kind == "GraphReuseCandidate"
    assert found[0].supporting_events == [0, 1]
    assert found[0].decision == "proposed"
    [planned] = plan_candidates(found)
    assert planned.decision == "rejected"
    assert "cost evidence incomplete" in planned.rejection_reason


def test_graph_candidate_with_measured_cost_selects_generic_backend():
    import torch
    from scar.backends import apply_candidates, pure

    value = {"object_id": "py:x", "storage_id": "storage:x",
             "logical_version": "storage:x@0:v0", "shape": [2],
             "strides": [1], "dtype": "torch.float32", "device": "cpu"}
    graph = _graph([
        Event(kind="module_call", code_id="user:work", invocation_id=1,
              inputs=[value], duration_ns=10, effect=_complete_pure_effect()),
        Event(kind="module_call", code_id="user:work", invocation_id=2,
              inputs=[value], duration_ns=100, effect=_complete_pure_effect()),
    ])
    [candidate] = graph_candidates(graph)
    candidate.guard_cost_ns = 5
    candidate.lookup_cost_ns = 5
    [planned] = plan_candidates([candidate])
    assert planned.decision == "accepted"

    @pure
    def function(x):
        return x.square()

    result = apply_candidates([planned], {"user:work": function})["user:work"]
    assert result.applied
    with torch.inference_mode():
        x = torch.ones(2)
        first = result.value(x)
        second = result.value(x)
    assert torch.equal(first, second)
    assert result.value.hits == 1


def test_graph_candidate_rejects_unknown_effects_and_intervening_writes():
    value = {"object_id": "py:x", "storage_id": "storage:x",
             "logical_version": "storage:x@0:v0", "shape": [2],
             "strides": [1], "dtype": "torch.float32", "device": "cpu"}
    unknown = Event(kind="module_call", code_id="user:work", invocation_id=1,
                    inputs=[value], duration_ns=10)
    mutation = Event(kind="torch_dispatch", code_id="aten::add_", invocation_id=2,
                     inputs=[value], duration_ns=5,
                     effect=Effect(reads=[value["logical_version"]],
                                   writes=[value["logical_version"]]))
    later = Event(kind="module_call", code_id="user:work", invocation_id=3,
                  inputs=[value], duration_ns=10, effect=_complete_pure_effect())
    found = graph_candidates(_graph([unknown, mutation, later]))
    assert len(found) == 1
    assert found[0].decision == "rejected"
    assert "incomplete" in found[0].rejection_reason


def test_graph_candidate_rejects_an_indexed_intervening_write():
    value = {"object_id": "py:x", "storage_id": "storage:x",
             "logical_version": "storage:x@0:v0", "shape": [2],
             "strides": [1], "dtype": "torch.float32", "device": "cpu"}
    mutation_effect = _complete_pure_effect()
    mutation_effect.reads = [value["logical_version"]]
    mutation_effect.writes = [value["logical_version"]]
    found = graph_candidates(_graph([
        Event(kind="module_call", code_id="user:work", invocation_id=1,
              inputs=[value], duration_ns=10, effect=_complete_pure_effect()),
        Event(kind="torch_dispatch", code_id="aten::add_", invocation_id=2,
              inputs=[value], duration_ns=5, effect=mutation_effect),
        Event(kind="module_call", code_id="user:work", invocation_id=3,
              inputs=[value], duration_ns=10, effect=_complete_pure_effect()),
    ]))
    assert len(found) == 1
    assert found[0].decision == "rejected"
    assert "intervening write" in found[0].rejection_reason


def test_graph_candidate_does_not_treat_missing_intervening_writes_as_none():
    value = {"object_id": "py:x", "storage_id": "storage:x",
             "logical_version": "storage:x@0:v0", "shape": [2],
             "strides": [1], "dtype": "torch.float32", "device": "cpu"}
    found = graph_candidates(_graph([
        Event(kind="module_call", code_id="user:work", invocation_id=1,
              inputs=[value], duration_ns=10, effect=_complete_pure_effect()),
        # This action does not expose a write, but its write collection is
        # UNKNOWN.  The absence of a graph edge therefore cannot prove that
        # the input remained unchanged.
        Event(kind="python_call", code_id="user:opaque", invocation_id=2),
        Event(kind="module_call", code_id="user:work", invocation_id=3,
              inputs=[value], duration_ns=10, effect=_complete_pure_effect()),
    ]))
    assert len(found) == 1
    assert found[0].decision == "rejected"
    obligation = next(item for item in found[0].proof_obligations
                      if item.name == "no_intervening_input_write")
    assert obligation.status == ProofStatus.UNKNOWN
    assert "incomplete" in obligation.reason
