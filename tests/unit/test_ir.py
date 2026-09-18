from pathlib import Path

from scar.ir import (CodeID, Effect, Event, ExecutionGraph, GraphNode, Knowledge,
                     NodeKind, ProgramGraph, from_project, from_source)
from scar.analysis.repetition import repeated_regions


def test_source_graph_covers_every_line():
    path = Path(__file__).resolve().parents[2] / "scar" / "workloads" / "micro.py"
    graph = from_source(path)
    lines = {node.line for node in graph.nodes.values() if node.source == str(path.resolve())}
    assert set(range(1, len(path.read_text().splitlines()) + 1)) <= lines
    assert any(node.kind == NodeKind.CONTROL for node in graph.nodes.values())
    assert any(edge.relation == "ast_contains" for edge in graph.edges)


def test_graph_validation_proves_static_line_coverage(tmp_path):
    source = tmp_path / "coverage.py"
    source.write_text("x = 1\n\nif x:\n    y = x + 1\n")
    graph = from_source(source)
    report = graph.assert_valid()
    assert report["valid"] is True
    coverage = report["source_coverage"][str(source.resolve())]
    assert coverage["physical_lines"] == 4
    assert coverage["coverage_complete"] is True
    assert coverage["missing_lines"] == []
    assert coverage["classification_complete"] is True
    assert all(coverage["line_labels"].get(str(line))
               for line in range(1, 5))


def test_graph_validation_rejects_dangling_edges():
    graph = ProgramGraph()
    graph.add_node(GraphNode("node", NodeKind.ACTION, "action"))
    graph.add_edge("node", "missing", "reads")
    report = graph.validate()
    assert report["valid"] is False
    assert "missing" in report["errors"][0]


def test_graph_validation_rejects_unknown_source_action_label(tmp_path):
    source = tmp_path / "invalid_label.py"
    source.write_text("x = 1\n")
    graph = ProgramGraph()
    graph.add_node(GraphNode(
        "bad", NodeKind.ACTION, "Assign", str(source.resolve()), 1,
        labels=["VAL", "NOT_A_SCAR_ACTION"],
    ))
    report = graph.validate()
    coverage = report["source_coverage"][str(source.resolve())]
    assert report["valid"] is False
    assert coverage["classification_complete"] is False
    assert coverage["invalid_line_labels"] == {"1": ["NOT_A_SCAR_ACTION"]}
    assert any("invalid action labels" in error for error in report["errors"])


def test_program_graph_json_is_versioned_and_round_trips(tmp_path):
    graph = ProgramGraph()
    graph.add_node(GraphNode("n", NodeKind.ACTION, "action", labels=["VAL"],
                             attrs={"evidence": "Observed"}))
    graph.add_node(GraphNode("m", NodeKind.STATE, "state", labels=["STATE"]))
    graph.add_edge("m", "n", "reads", evidence="Observed")
    path = tmp_path / "graph.json"
    graph.write_json(path)
    document = __import__("json").loads(path.read_text())
    assert document["schema"] == "scar.program_graph"
    assert document["schema_version"] == 1
    assert document["validation"]["valid"] is True
    restored = ProgramGraph.read_json(path)
    assert set(restored.nodes) == {"n", "m"}
    assert [(edge.source, edge.target, edge.relation) for edge in restored.edges] == [("m", "n", "reads")]


def test_program_graph_json_rejects_unknown_schema(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"schema":"other","schema_version":1,"nodes":[],"edges":[]}')
    try:
        ProgramGraph.read_json(path)
    except ValueError as error:
        assert "unsupported program graph schema" in str(error)
    else:
        raise AssertionError("unknown graph schema was accepted")


def test_source_graph_exposes_conservative_data_and_control_dependencies(tmp_path):
    source = tmp_path / "case.py"
    source.write_text("x = 1\nif x:\n    y = x + 1\nprint(y)\n")
    graph = from_source(source)
    relations = {edge.relation for edge in graph.edges}
    assert {"reads", "writes", "control_depends"} <= relations
    states = [node for node in graph.nodes.values() if node.label == "variable"]
    assert {node.attrs["name"] for node in states} >= {"x", "y"}


def test_operation_view_has_recursive_operations_and_data_edges(tmp_path):
    source = tmp_path / "nested.py"
    source.write_text("def outer(x):\n    y = x + 1\n    return y\n")
    graph = from_source(source)
    view = graph.operation_view()
    assert view["schema"] == "scar.operation_graph"
    assert any(node["kind"] == "operation" and node["label"] == "FunctionDef"
               for node in view["nodes"])
    assert any(edge["relation"] in {"reads", "writes"} for edge in view["edges"])
    assert any(node["children"] for node in view["nodes"] if node["kind"] == "operation")


def test_source_graph_classifies_expression_state_representation_and_io(tmp_path):
    source = tmp_path / "labels.py"
    source.write_text("import math\nx = a + b\ny = obj.field[0]\nwith open('x') as f:\n    y = f.read()\n")
    graph = from_source(source)
    labels_by_line = {}
    for node in graph.nodes.values():
        if node.source == str(source.resolve()) and node.line is not None:
            labels_by_line.setdefault(node.line, set()).update(node.labels)
    assert "IO" in labels_by_line[1]
    assert "VAL" in labels_by_line[2]
    assert {"STATE", "REP", "OPAQUE"} <= labels_by_line[3]
    assert "IO" in labels_by_line[4]


def test_source_graph_classifies_call_families_with_multi_labels(tmp_path):
    source = tmp_path / "call_families.py"
    source.write_text(
        "x = value.to('cuda')\n"
        "y = torch.empty(2)\n"
        "z = x.reshape(1, 2)\n"
        "torch.cuda.synchronize()\n"
        "print(z)\n"
        "state.append(z)\n"
    )
    graph = from_source(source)
    labels_by_line = {}
    for node in graph.nodes.values():
        if node.source == str(source.resolve()) and node.line is not None:
            labels_by_line.setdefault(node.line, set()).update(node.labels)
    assert {"XFER", "REP", "OPAQUE"} <= labels_by_line[1]
    assert {"MEM", "VAL", "OPAQUE"} <= labels_by_line[2]
    assert {"REP", "VAL", "OPAQUE"} <= labels_by_line[3]
    assert {"ORDER", "OPAQUE"} <= labels_by_line[4]
    assert "IO" in labels_by_line[5]
    assert "STATE" in labels_by_line[6]


def test_static_labels_record_hint_provenance_separately_from_runtime_effects(tmp_path):
    source = tmp_path / "provenance.py"
    source.write_text("# comment only\nx = value.to('cuda')\n")
    graph = from_source(source)
    source_nodes = [node for node in graph.nodes.values()
                    if node.source == str(source.resolve())]
    assert source_nodes
    assert all(node.attrs["label_provenance"] in {"static_syntax", "static_dataflow"}
               for node in source_nodes)
    assert all(node.attrs["label_status"] == "Inferred"
               for node in source_nodes)
    assert all(node.attrs["labels_are_hints"] is True
               for node in source_nodes)
    assert all("observed" not in node.attrs.get("label_provenance", "").lower()
               for node in source_nodes)


def test_static_dataflow_restores_outer_scope_after_function(tmp_path):
    """Lexical State nodes must not leak a function scope into later code."""
    source = tmp_path / "scopes.py"
    source.write_text(
        "outer = 1\n"
        "def inner(argument):\n"
        "    local = argument\n"
        "    return local\n"
        "after = outer\n"
    )
    graph = from_source(source)
    states = [node for node in graph.nodes.values() if node.label == "variable"]
    outer_scope = {node.attrs["scope"] for node in states if node.attrs["name"] in {"outer", "after"}}
    inner_scope = {node.attrs["scope"] for node in states if node.attrs["name"] in {"argument", "local"}}
    assert len(outer_scope) == 1
    assert len(inner_scope) == 1
    assert next(iter(outer_scope)) != next(iter(inner_scope))
    assert "function:inner:2" not in next(iter(outer_scope))


def test_source_graph_builds_conservative_cfg_for_branch_loop_and_exception(tmp_path):
    source = tmp_path / "control.py"
    source.write_text(
        "for i in xs:\n"
        "    if i:\n"
        "        y = f(i)\n"
        "    else:\n"
        "        continue\n"
        "try:\n"
        "    z = g(y)\n"
        "except ValueError:\n"
        "    z = 0\n"
    )
    graph = from_source(source)
    relations = {edge.relation for edge in graph.edges}
    assert {"cfg_true", "cfg_false", "cfg_backedge", "cfg_continue",
            "cfg_exception"} <= relations
    exits = [node for node in graph.nodes.values() if node.label == "loop_exit"]
    assert len(exits) == 1
    assert any(edge.target == exits[0].node_id and edge.relation == "cfg_break"
               for edge in graph.edges) is False


def test_project_graph_merges_modules_and_resolvable_imports(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("from .worker import run\n")
    (package / "worker.py").write_text("def run(value):\n    return value + 1\n")
    main = tmp_path / "main.py"
    main.write_text("import pkg.worker\nfrom pkg import worker\nresult = worker.run(1)\n")

    graph = from_project(tmp_path)
    sources = {node.source for node in graph.nodes.values() if node.source}
    assert sources == {str(main.resolve()), str((package / "__init__.py").resolve()),
                       str((package / "worker.py").resolve())}
    modules = [node for node in graph.nodes.values() if node.label == "module"]
    assert len(modules) == 3
    imports = [edge for edge in graph.edges if edge.relation == "imports"]
    # Two imports are in ``main.py`` and the package ``__init__.py`` has a
    # relative import.  The latter must resolve against the package itself,
    # not against the (empty) parent of the ``pkg`` module name.
    assert len(imports) == 3
    assert all(edge.attrs["evidence"] == "Inferred" for edge in imports)
    assert all(node.attrs["labels_are_hints"] is True for node in modules)
    # Every physical line from every source remains represented in the merged
    # graph, including blank lines if a source contains them.
    for source in sources:
        line_numbers = {node.line for node in graph.nodes.values()
                        if node.source == source and node.line is not None}
        assert set(range(1, len(Path(source).read_text().splitlines()) + 1)) <= line_numbers


def test_code_id_is_not_line_only():
    a = CodeID("/a.py", "f", 3, version="1")
    b = CodeID("/a.py", "f", 3, version="2")
    assert a.key() != b.key()


def test_dispatch_repetition_uses_regions_but_rejects_unknown_effects():
    events = [
        Event(kind="torch_dispatch", code_id="aten::add.Tensor",
              inputs=[{"storage_id": "storage:a", "logical_version": "a:v0",
                       "shape": [2], "dtype": "torch.float32", "device": "cpu"}],
              effect=Effect(reads=["a:v0"]), duration_ns=10),
        Event(kind="torch_dispatch", code_id="aten::add.Tensor",
              inputs=[{"storage_id": "storage:a", "logical_version": "a:v0",
                       "shape": [2], "dtype": "torch.float32", "device": "cpu"}],
              effect=Effect(reads=["a:v0"]), duration_ns=20),
    ]
    candidates = repeated_regions(ExecutionGraph(events))
    assert len(candidates) == 1
    assert candidates[0].applicability == "same_input_logical_versions"
    assert candidates[0].decision == "rejected"
    assert candidates[0].supporting_events == [0, 1]


def test_dispatch_repetition_does_not_merge_distinct_views():
    events = [
        Event(kind="torch_dispatch", code_id="aten::add.Tensor",
              inputs=[{"storage_id": "storage:a", "logical_version": "a:v0",
                       "offset": 0, "shape": [2], "strides": [1]}]),
        Event(kind="torch_dispatch", code_id="aten::add.Tensor",
              inputs=[{"storage_id": "storage:a", "logical_version": "a:v0",
                       "offset": 2, "shape": [2], "strides": [1]}]),
    ]
    candidates = repeated_regions(ExecutionGraph(events))
    assert len(candidates) == 1
    assert candidates[0].applicability == "changed_input_logical_versions"
    assert candidates[0].decision == "rejected"


def test_program_graph_does_not_overwrite_aggregate_events():
    events = [
        Event(kind="torch_op", code_id="aten::add", resource={"count": 3}),
        Event(kind="torch_op", code_id="aten::add", resource={"count": 4}),
    ]
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph(events))
    actions = [node for node in graph.nodes.values() if node.kind == NodeKind.ACTION]
    assert len(actions) == 2
    assert actions[0].node_id != actions[1].node_id


def test_program_graph_exposes_control_contract_and_measurement_views():
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph([Event(kind="python_call", code_id="f")]))
    kinds = {node.kind for node in graph.nodes.values()}
    assert {NodeKind.CONTROL, NodeKind.ACTION, NodeKind.CONTRACT,
            NodeKind.MEASUREMENT} <= kinds
    relations = {edge.relation for edge in graph.edges}
    assert {"controls", "subject_to", "measured_by"} <= relations


def test_program_graph_preserves_dynamic_source_coordinates_without_static_coverage():
    event = Event(kind="python_c_call", code_id="user:call:v1", labels=["CTRL", "IO", "OPAQUE"],
                  metadata={"file": "/tmp/program.py", "line": 12})
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph([event]))
    action = next(node for node in graph.nodes.values()
                  if node.kind == NodeKind.ACTION)
    assert action.source == "user:call:v1"
    assert action.line is None
    assert action.attrs["source_file"] == "/tmp/program.py"
    assert action.attrs["source_line"] == 12
    assert graph.validate()["source_coverage"] == {}


def test_program_graph_preserves_observed_call_nesting_and_returns():
    events = [
        Event(kind="python_call", code_id="outer:v1", invocation_id=1,
              metadata={"process_id": 7, "parent_invocation_id": None, "call_depth": 0}),
        Event(kind="module_call", code_id="inner:v1", invocation_id=2,
              metadata={"process_id": 7, "parent_invocation_id": 1, "call_depth": 1}),
        Event(kind="python_return", code_id="outer:v1", invocation_id=1,
              metadata={"process_id": 7, "parent_invocation_id": None,
                        "call_depth": 0, "outcome": "return"}),
    ]
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph(events))
    relations = {edge.relation for edge in graph.edges}
    assert {"controls_dynamic", "returns"} <= relations


def test_program_graph_records_order_only_within_the_same_cuda_stream():
    events = [
        Event(kind="cuda_kernel", resource={"device": 0, "stream": 7}),
        Event(kind="cuda_kernel", resource={"device": 0, "stream": 8}),
        Event(kind="cuda_kernel", resource={"device": 0, "stream": 7}),
    ]
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph(events))
    stream_edges = [edge for edge in graph.edges if edge.relation == "stream_order"]
    assert len(stream_edges) == 1
    assert stream_edges[0].source == "invocation:0:aggregate"
    assert stream_edges[0].target == "invocation:2:aggregate"
    assert stream_edges[0].attrs == {
        "happens_before": True, "evidence": "Observed", "stream": 7,
        "device": 0, "context": None,
    }


def test_program_graph_connects_actions_to_observed_loop_markers():
    events = [
        Event(kind="loop_iteration", invocation_id=9,
              metadata={"process_id": 3, "parent_invocation_id": None,
                        "loop_target_offset": 24, "iteration": 2}),
        Event(kind="module_call", invocation_id=2,
              metadata={"process_id": 3, "parent_invocation_id": 9,
                        "loop_target_offset": 24, "loop_iteration": 2}),
    ]
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph(events))
    edges = [edge for edge in graph.edges if edge.relation == "loop_controls"]
    assert len(edges) == 1
    assert edges[0].source == "invocation:0:9"
    assert edges[0].target == "invocation:1:2"
    assert edges[0].attrs == {
        "iteration": 2, "loop_target_offset": 24, "evidence": "Observed",
    }


def test_program_graph_uses_outer_loop_scope_for_nested_actions():
    events = [
        Event(kind="loop_iteration", invocation_id=9,
              metadata={"process_id": 3, "thread_id": 4,
                        "loop_target_offset": 24, "iteration": 2}),
        Event(kind="module_call", invocation_id=2,
              metadata={"process_id": 3, "thread_id": 4,
                        "parent_invocation_id": 8,
                        "loop_parent_invocation_id": 9,
                        "loop_target_offset": 24,
                        "loop_iteration": 2}),
    ]
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph(events))
    edges = [edge for edge in graph.edges if edge.relation == "loop_controls"]
    assert len(edges) == 1
    assert edges[0].source == "invocation:0:9"
    assert edges[0].target == "invocation:1:2"


def test_program_graph_marks_callable_capture_as_unknown_control_boundary():
    event = Event(
        kind="python_call", invocation_id=1,
        inputs=[{"object_id": "py:callback", "logical_version": "callable:callback",
                 "state_role": "callable", "type": "function"}],
    )
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph([event]))
    edges = [edge for edge in graph.edges if edge.relation == "captures_callable"]
    assert edges and edges[0].attrs == {"evidence": "Observed", "status": "UNKNOWN"}


def test_program_graph_marks_returned_callable_as_unknown_escape():
    event = Event(
        kind="python_return", invocation_id=1,
        metadata={"returned_callables": [{
            "object_id": "py:callback", "logical_version": "callable:callback",
            "callable_code_id": "callable:pkg.make.<locals>.callback",
            "closure_names": ["bias"], "callable_capture": "UNKNOWN",
        }]},
    )
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph([event]))
    edges = [edge for edge in graph.edges
             if edge.relation == "escapes" and edge.target == "state:callable:callback"]
    assert edges and edges[0].attrs == {
        "evidence": "Observed", "status": "UNKNOWN", "escape_kind": "callable"
    }
    state = graph.nodes["state:callable:callback"]
    assert state.attrs["state_role"] == "callable"


def test_program_graph_keeps_object_regions_and_alias_edges():
    values = [
        {"object_id": "py:a", "storage_id": "storage:s", "logical_version": "storage:s@0:v0",
         "offset": 0, "shape": [4], "strides": [1], "dtype": "torch.float32", "device": "cpu"},
        {"object_id": "py:b", "storage_id": "storage:s", "logical_version": "storage:s@0:v0",
         "offset": 2, "shape": [4], "strides": [1], "dtype": "torch.float32", "device": "cpu"},
    ]
    events = [Event(kind="torch_dispatch", inputs=[values[0]]),
              Event(kind="torch_dispatch", inputs=[values[1]])]
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph(events))
    assert any(node.label == "object" for node in graph.nodes.values())
    assert any(node.label == "region" for node in graph.nodes.values())
    aliases = [edge for edge in graph.edges if edge.relation == "aliases"]
    assert aliases and aliases[0].attrs["overlap"] == "PARTIAL"


def test_program_graph_connects_observed_producers_consumers_and_overwrites():
    producer = Event(
        kind="torch_dispatch", invocation_id=1,
        outputs=[{"object_id": "py:y", "storage_id": "storage:y",
                  "logical_version": "storage:y@0:v0", "shape": [2],
                  "strides": [1], "dtype": "torch.float32", "device": "cuda:0"}],
        effect=Effect(writes=["storage:y@0:v0"], collection_knowledge={
            "reads": "KNOWN", "writes": "KNOWN", "allocates": "KNOWN",
            "frees": "KNOWN", "aliases": "KNOWN", "escapes": "KNOWN"}))
    consumer = Event(
        kind="torch_dispatch", invocation_id=2,
        inputs=[{"object_id": "py:y", "storage_id": "storage:y",
                 "logical_version": "storage:y@0:v0", "shape": [2],
                 "strides": [1], "dtype": "torch.float32", "device": "cuda:0"}],
        effect=Effect(reads=["storage:y@0:v0"]))
    overwrite = Event(
        kind="torch_dispatch", invocation_id=3,
        outputs=[{"object_id": "py:y", "storage_id": "storage:y",
                  "logical_version": "storage:y@0:v0", "shape": [2],
                  "strides": [1], "dtype": "torch.float32", "device": "cuda:0"}],
        effect=Effect(writes=["storage:y@0:v0"]))
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph([producer, consumer, overwrite]))
    dependencies = [edge for edge in graph.edges if edge.relation == "data_depends"]
    overwrites = [edge for edge in graph.edges if edge.relation == "overwrites"]
    assert dependencies and dependencies[0].attrs["logical_version"] == "storage:y@0:v0"
    assert overwrites and overwrites[0].attrs["logical_version"] == "storage:y@0:v0"


def test_program_graph_preserves_observed_escape_without_calling_unknown_empty():
    event = Event(kind="python_call", invocation_id=1,
                  effect=Effect(escapes=["state:external"],
                                collection_knowledge={"escapes": "KNOWN"}))
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph([event]))
    assert any(edge.relation == "escapes" and edge.target == "state:state:external"
               for edge in graph.edges)


def test_program_graph_links_non_tensor_effect_reads():
    events = [
        Event(kind="python_call", invocation_id=1,
              effect=Effect(writes=["module:cache:v0"])),
        Event(kind="python_call", invocation_id=2,
              effect=Effect(reads=["module:cache:v0"])),
    ]
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph(events))
    assert any(edge.relation == "data_depends" and
               edge.attrs["logical_version"] == "module:cache:v0"
               for edge in graph.edges)


def test_program_graph_links_inferred_physical_copy_to_logical_state():
    event = Event(kind="cuda_memcpy", resource={"direction": "HtoD", "bytes": 4096},
                  metadata={"logical_version": "x:v0", "storage_id": "gpu:x",
                            "mapping_confidence": "Inferred"})
    graph = ProgramGraph()
    graph.merge_execution(ExecutionGraph([event]))
    links = [edge for edge in graph.edges if edge.relation == "materializes_physical"]
    assert len(links) == 1
    assert links[0].target == "state:x:v0"
    assert links[0].attrs["confidence"] == "Inferred"
def test_package_exposes_v010_version():
    import scar

    assert scar.__version__ == "0.1.0"
