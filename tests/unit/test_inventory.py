from scar.analysis import summarize_action_inventory
from scar.ir import Effect, Event, ExecutionGraph, Knowledge, Opportunity, ProgramGraph
from scar.planner import plan_candidates, select_candidates


def _pure_effect():
    return Effect(
        collection_knowledge={name: Knowledge.KNOWN for name in
                              ("reads", "writes", "allocates", "frees",
                               "aliases", "escapes")},
        rng_effect=Knowledge.NONE, may_raise=Knowledge.NONE,
        external_effect=Knowledge.NONE, ordering_effect=Knowledge.NONE,
    )


def test_action_inventory_covers_unmatched_dynamic_actions_without_calling_them_safe():
    value = {"storage_id": "s", "logical_version": "s@0:v0", "shape": [2],
             "strides": [1], "dtype": "torch.float32", "device": "cpu"}
    execution = ExecutionGraph([
        Event(kind="module_call", code_id="case:module", inputs=[value],
              outputs=[value], duration_ns=100, effect=_pure_effect()),
        Event(kind="module_call", code_id="case:module", inputs=[value],
              outputs=[value], duration_ns=100, effect=_pure_effect()),
        Event(kind="python_c_call", code_id="case:print", labels=["CTRL", "IO", "OPAQUE"],
              effect=Effect()),
    ])
    graph = ProgramGraph()
    graph.merge_execution(execution)
    candidate = Opportunity(
        kind="ReuseCandidate", code_id="case:module", evidence="Observed",
        applicability="same_input_logical_versions", guard="proof",
        reason="same value", supporting_events=[0, 1], expected_savings_ns=100,
        guard_cost_ns=1, lookup_cost_ns=1, decision="proposed",
        backend="exact_reuse", proof_obligations=[],
    )
    # The inventory is also useful when the detector was supplied a candidate
    # by an external analysis pass; its status still comes from the selector.
    planned = plan_candidates([candidate])
    selected = select_candidates(planned)
    inventory = summarize_action_inventory(graph, planned, selected)
    assert inventory["actions"] == 3
    assert inventory["dynamic_actions"] == 3
    assert inventory["by_family"]["control"] >= 1
    assert inventory["by_status"]["TRANSFORM"] == 2
    assert inventory["by_status"]["UNKNOWN"] == 1
    print_action = next(item for item in inventory["records"]
                        if item["event_index"] == 2)
    assert print_action["status"] == "UNKNOWN"
    assert "no complete candidate" in print_action["reason"]


def test_static_action_inventory_is_unknown_until_runtime_or_contract_evidence(tmp_path):
    from scar.ir import from_source

    source = tmp_path / "scar_inventory_static.py"
    source.write_text("def work(x):\n    return x + 1\n\nwork(1)\n")
    graph = from_source(source)
    inventory = summarize_action_inventory(graph)
    assert inventory["static_actions"] > 0
    assert inventory["by_status"]["UNKNOWN"] == inventory["actions"]
    assert inventory["by_family"]["compute"] > 0
