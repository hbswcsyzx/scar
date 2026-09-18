from scar.analysis import graph_liveness
from scar.ir import Effect, Event, ExecutionGraph, ProgramGraph


def _graph(events):
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph(events))
    return graph


def test_graph_liveness_marks_observed_read_as_live():
    value = {"logical_version": "x:v0", "storage_id": "x",
             "shape": [2], "strides": [1], "dtype": "float32", "device": "cpu"}
    facts = graph_liveness(_graph([
        Event(kind="torch_dispatch", invocation_id=1, outputs=[value], effect=Effect(writes=["x:v0"])),
        Event(kind="torch_dispatch", invocation_id=2, inputs=[value], effect=Effect(reads=["x:v0"])),
    ]))
    fact = next(item for item in facts if item.state_id == "state:x:v0")
    assert fact.status == "LIVE"
    assert fact.consumer_actions


def test_graph_liveness_does_not_call_unconsumed_state_dead_without_contract():
    facts = graph_liveness(_graph([
        Event(kind="torch_dispatch", invocation_id=1,
              outputs=[{"logical_version": "x:v0"}], effect=Effect(writes=["x:v0"])),
    ]))
    fact = next(item for item in facts if item.state_id == "state:x:v0")
    assert fact.status == "UNKNOWN"
    assert "absence is not proof" in fact.reason
    assert graph_liveness(_graph([
        Event(kind="torch_dispatch", invocation_id=1,
              outputs=[{"logical_version": "x:v0"}], effect=Effect(writes=["x:v0"])),
    ]), closed_world=True)[0].status == "DEAD"
