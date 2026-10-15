"""Semantic and scaling checks for call-edge source lookups."""
import ast
import dis
from pathlib import Path
import sys
from types import ModuleType

from scar.analysis import call_edges
from scar.analysis.call_edges import CallEdgeReport, _Sources, _span, link_calls
from scar.analysis.program_inventory import inventory_program
from scar.ir.program.call_edges import (
    CallEdgeBudget, CallRecordAnchor, CallLinkStatus, CapturedSite,
    CodeSourceLink, FrameCompletion, FrameExit, InvocationKey,
)
from scar.ir.record_codec import decode
from scar.trace.call_edges import CallEdgeRecorder
from scar.trace.code_snapshot import describe_code, site


def test_return_position_index_matches_the_original_file_wide_scan(tmp_path):
    source = """\
def target(value):
    if value:
        return (value +
                1)
    def nested(item):
        return item
    return nested(value)

class Container:
    def method(self, item):
        return item

def empty():
    return
"""
    path = tmp_path / "returns.py"
    path.write_text(source, encoding="utf-8")
    sources = _Sources(tmp_path.resolve(), CallEdgeBudget(), None)
    context = sources.context(str(path.resolve()))

    positions = {
        _span(node)
        for node in ast.walk(context.tree)
        if hasattr(node, "end_lineno")
    }
    positions.add((999, 999, 0, 0))
    indexed_positions = {
        position
        for position in positions
        if context.return_nodes_by_position.get(position, ())
    }
    assert set(context.return_nodes_by_position) == indexed_positions

    for position in positions:
        expected = tuple(
            node for node in ast.walk(context.tree)
            if isinstance(node, ast.Return)
            and node.value is not None
            and position in (_span(node), _span(node.value))
        )
        actual = context.return_nodes_by_position.get(position, ())
        assert len(actual) == len(expected)
        assert all(left is right for left, right in zip(actual, expected))


def test_repeated_return_lookup_does_not_walk_the_ast_again(tmp_path, monkeypatch):
    source = "def target(value):\n    return value\n"
    path = tmp_path / "target.py"
    path.write_text(source, encoding="utf-8")
    sources = _Sources(tmp_path.resolve(), CallEdgeBudget(), None)
    context = sources.context(str(path.resolve()))

    module_code = compile(source, str(path.resolve()), "exec", dont_inherit=True)
    target_code = next(code for code in call_edges._nested_codes(module_code)
                       if code.co_name == "target")
    code_key = describe_code(target_code)["key"]
    sources.objects[code_key] = target_code
    return_offset = next(instruction.offset for instruction in dis.get_instructions(target_code)
                         if instruction.opname in ("RETURN_VALUE", "RETURN_CONST"))
    return_site = decode(CapturedSite, site(target_code, return_offset))
    exit = FrameExit(
        CallRecordAnchor("trace.jsonl", 1, "0" * 64, 1),
        InvocationKey(1, 0, 1),
        code_key,
        return_site,
        FrameCompletion.NORMAL,
        "weak:1:1",
        (),
        True,
    )
    code_link = CodeSourceLink(code_key, CallLinkStatus.VERIFIED, context.snapshot)
    expected = next(node for node in ast.walk(context.tree)
                    if isinstance(node, ast.Return) and node.value is not None)

    def unexpected_walk(_tree):
        raise AssertionError("returned_node must use the prebuilt source-position index")

    monkeypatch.setattr(call_edges.ast, "walk", unexpected_walk)
    for _ in range(500):
        assert sources.returned_node(exit, code_link) is expected


def test_recursive_and_exception_frames_keep_report_replay_identical(tmp_path, monkeypatch):
    source = """\
def descend(value, depth):
    if depth:
        return descend(value, depth - 1)
    return value

def fail(value):
    raise ValueError("expected")

def run(value, should_fail):
    if should_fail:
        try:
            fail(value)
        except ValueError:
            pass
    return descend(value, 3)
"""
    root = tmp_path.resolve()
    entry_path = root / "entry.py"
    entry_path.write_text(source, encoding="utf-8")
    module = ModuleType("entry")
    module.__file__ = str(entry_path)
    exec(compile(source, str(entry_path), "exec", dont_inherit=True), module.__dict__)

    trace = root / "trace"
    recorder = CallEdgeRecorder(trace, root)
    previous_profile = sys.getprofile()
    sys.setprofile(recorder.profile)
    value = object()
    try:
        assert module.run(value, False) is value
        assert module.run(value, True) is value
    finally:
        sys.setprofile(previous_profile)
        recorder.close()

    inventory = inventory_program(entry_path, project_root=root)
    report = link_calls(trace, root, inventory=inventory)
    code_names = {capture.code.key: capture.code.qualname for capture in report.model.codes}
    recursive_edges = [edge for edge in report.model.edges if code_names[edge.entry.code] == "descend"]
    assert len(recursive_edges) >= 4
    assert all(edge.caller_identity_verified for edge in recursive_edges)
    failed_edges = [edge for edge in report.model.edges if code_names[edge.entry.code] == "fail"]
    assert len(failed_edges) == 1
    assert failed_edges[0].exit is not None
    assert failed_edges[0].exit.completion is FrameCompletion.UNKNOWN
    assert not failed_edges[0].exit_verified

    document = report.to_dict()
    assert CallEdgeReport.from_dict(document, inventory=inventory).to_dict() == document
