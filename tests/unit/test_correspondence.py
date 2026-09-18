from scar.ir import (CodeID, Event, ExecutionGraph, ProgramGraph,
                     add_correspondences, from_source, link_events,
                     summarize_correspondence)


def test_dynamic_events_link_to_static_source_without_guessing(tmp_path):
    source = tmp_path / "program.py"
    source.write_text("def run(x):\n    return x + 1\n\nrun(2)\n")
    static = from_source(source)
    event = Event(kind="python_call", code_id=None,
                  metadata={"file": str(source), "line": 2})
    matches = link_events(static, ExecutionGraph([event]))
    assert len(matches) == 1
    assert matches[0].status in {"linked", "ambiguous"}
    combined = ProgramGraph()
    combined.merge_graph(static)
    combined.merge_execution(ExecutionGraph([event]))
    add_correspondences(combined, matches)
    assert any(edge.relation == "dynamic_instance" for edge in combined.edges)


def test_missing_source_line_is_not_falsely_linked(tmp_path):
    source = tmp_path / "program.py"
    source.write_text("x = 1\n")
    matches = link_events(from_source(source), ExecutionGraph([
        Event(kind="python_call", metadata={"file": str(source), "line": 99})]))
    assert matches == []


def test_function_span_correspondence_uses_loaded_qualname(tmp_path):
    source = tmp_path / "program.py"
    source.write_text("def run(x):\n    return x + 1\n\nrun(2)\n")
    code_id = CodeID(str(source.resolve()), "run", 1, version="pycode-sha256:test").key()
    matches = link_events(from_source(source), ExecutionGraph([
        Event(kind="python_call", code_id=code_id,
              metadata={"file": str(source), "line": 2})]))
    assert len(matches) == 1
    assert matches[0].confidence == "function_span"
    assert matches[0].status == "linked"


def test_correspondence_summary_uses_only_modeled_sources_as_denominator(tmp_path):
    source = tmp_path / "program.py"
    other = tmp_path / "library.py"
    source.write_text("x = 1\n")
    other.write_text("y = 2\n")
    static = from_source(source)
    execution = ExecutionGraph([
        Event(kind="python_call", metadata={"file": str(source), "line": 1}),
        Event(kind="python_call", metadata={"file": str(source), "line": 99}),
        Event(kind="python_call", metadata={"file": str(other), "line": 1}),
    ])
    matches = link_events(static, execution)
    summary = summarize_correspondence(static, execution, matches)
    assert summary["source_files"] == 1
    assert summary["eligible_events"] == 2
    assert summary["linked_events"] == 1
    assert summary["unlinked_eligible_events"] == 1
    assert summary["event_coverage"] == 0.5
