"""Captured calls become traversable source/core and identity-only routes."""
from copy import deepcopy
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from textwrap import dedent
from types import ModuleType

import pytest

from scar.analysis.call_edges import CallEdgeReport, link_calls
from scar.analysis.program_inventory import inventory_program
from scar.ir.program.call_edges import (
    CallEdgeBudget, CallEdgeIssueKind, CallLinkStatus, FrameCompletion,
    InvocationKey, ReferenceRole, ReferenceRouteKind,
)
from scar.trace.call_edges import CallEdgeRecorder


class Token:
    pass


HELPER = """\
def identity(value):
    return value
def relay(value):
    return identity(value)
"""
ENTRY = """\
from helper import relay
def run(left, right):
    a = relay(left)
    b = relay(right)
    return a
"""


def capture(tmp_path, monkeypatch, *, helper=HELPER, entry=ENTRY, call=None, **limits):
    helper_path, entry_path = tmp_path / "helper.py", tmp_path / "entry.py"
    helper_path.write_text(dedent(helper).lstrip(), encoding="utf-8")
    entry_path.write_text(dedent(entry).lstrip(), encoding="utf-8")
    module = ModuleType("helper")
    module.__file__ = str(helper_path)
    exec(compile(helper_path.read_text(), str(helper_path), "exec", dont_inherit=True), module.__dict__)
    monkeypatch.setitem(sys.modules, "helper", module)
    entry_module = ModuleType("entry")
    entry_module.__file__ = str(entry_path)
    exec(compile(entry_path.read_text(), str(entry_path), "exec", dont_inherit=True), entry_module.__dict__)
    left, right = Token(), Token()
    output = tmp_path / "trace"
    recorder = CallEdgeRecorder(output, tmp_path, **limits)
    old_profile = sys.getprofile()
    sys.setprofile(recorder.profile)
    try:
        result = call(entry_module, left, right) if call else entry_module.run(left, right)
    finally:
        sys.setprofile(old_profile)
        recorder.close()
    inventory = inventory_program(entry_path, project_root=tmp_path)
    report = link_calls(output, tmp_path, inventory=inventory)
    return report, inventory, output, left, right, result


def edges_named(report, name):
    names = {capture.code.key: capture.code.qualname for capture in report.model.codes}
    return [edge for edge in report.model.edges if names[edge.entry.code] == name]


def rewrite_events(output, change):
    path, = output.glob("call-events.*.jsonl")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    change(rows)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    refresh_byte_count(output)


def refresh_byte_count(output):
    """Keep the independent byte accounting valid for semantic tamper fixtures."""
    for path in output.glob("call-meta.*.json"):
        meta = json.loads(path.read_text())
        meta["bytes"] = sum((output / f"call-{family}.{meta['process_id']}.jsonl").stat().st_size
                            for family in ("codes", "events"))
        path.write_text(json.dumps(meta), encoding="utf-8")


def test_two_file_return_chain_stops_at_unproved_argument_routing(tmp_path, monkeypatch):
    report, inventory, output, left, right, result = capture(tmp_path, monkeypatch)
    assert result is left
    run, = edges_named(report, "run")
    relay_left, relay_right = edges_named(report, "relay")
    identity_left, identity_right = edges_named(report, "identity")
    assert report.children(run.entry.invocation) == (relay_left, relay_right)
    assert report.parents(identity_left.entry.invocation) == (identity_left,)
    assert identity_left.entry.caller_invocation == relay_left.entry.invocation
    assert all(edge.exit_verified and edge.exit.completion is FrameCompletion.NORMAL
               for edge in (run, relay_left, relay_right, identity_left, identity_right))
    assert relay_left.path[0].core_operation is not None
    observations = report.by_core_call(relay_left.path[0].core_operation)
    assert len(observations) == 1 and observations[0].invocation == relay_left.entry.invocation
    assert observations[0].site.callee_use is not None and observations[0].site.callee_value is not None
    assert observations[0].target.definition == relay_left.target.definition
    assert observations[0].target_body == relay_left.target_body
    trace = report.trace_reference(run.exit)
    roles = {route.kind for route in trace.routes}
    assert {ReferenceRouteKind.CORE_CALL_RESULT, ReferenceRouteKind.RETURN_CALL,
            ReferenceRouteKind.OBSERVED_CALL_RETURN,
            ReferenceRouteKind.SAME_FRAME_PARAMETER, ReferenceRouteKind.SOURCE_RETURN_LOCAL} <= roles
    assert ReferenceRouteKind.SOURCE_ARGUMENT_LOCAL not in roles
    occurrences = [item for group in trace.groups for item in group.occurrences]
    assert any(item.owner == identity_left.entry.invocation and item.role is ReferenceRole.PARAMETER and item.name == "value"
               for item in occurrences)
    assert not any(item.owner == run.entry.invocation and item.role is ReferenceRole.PARAMETER
                   for item in occurrences)
    assert not any(item.name in {"right", "b"} for item in occurrences)
    assert not any(item.observed_in in {relay_right.entry.invocation, identity_right.entry.invocation}
                   for item in occurrences)
    assert trace.identity_only and not trace.content_or_effect_equivalence_established
    assert {issue.kind for issue in trace.issues} == {CallEdgeIssueKind.ARGUMENT_ROUTING_UNVERIFIED}
    assert all(not group.contents_established and not group.function_environment_established for group in trace.groups)
    document = report.to_dict()
    assert CallEdgeReport.from_dict(document, inventory=inventory).to_dict() == document


def test_same_line_calls_keep_distinct_full_spans_and_core_operands(tmp_path, monkeypatch):
    entry = "from helper import relay\ndef run(left, right):\n    a = relay(left); b = relay(right)\n    return a\n"
    report, *_ = capture(tmp_path, monkeypatch, entry=entry)
    first, second = edges_named(report, "relay")
    assert first.path[0].site.offset != second.path[0].site.offset
    assert first.path[0].source.start_line == second.path[0].source.start_line
    assert first.path[0].source.start_column != second.path[0].source.start_column
    assert first.path[0].core_operation != second.path[0].core_operation
    assert first.path[0].callee_use != second.path[0].callee_use
    assert first.entry.invocation != second.entry.invocation


def test_shared_object_does_not_link_unrelated_sibling_call_dependencies(tmp_path, monkeypatch):
    report, *_ = capture(tmp_path, monkeypatch, call=lambda module, left, right: module.run(left, left))
    run, = edges_named(report, "run")
    first, second = edges_named(report, "relay")
    trace = report.trace_reference(run.entry.invocation)
    owners = {item.observed_in for group in trace.groups for item in group.occurrences}
    assert first.entry.invocation in owners
    assert second.entry.invocation not in owners
    assert not any(item.name == "right" and item.owner == run.entry.invocation
                   for group in trace.groups for item in group.occurrences)


def test_recursion_keeps_each_invocation_and_parent(tmp_path, monkeypatch):
    helper = "def descend(value, depth):\n    if depth:\n        return descend(value, depth - 1)\n    return value\n"
    entry = "from helper import descend\ndef run(left, right):\n    return descend(left, 3)\n"
    report, *_ = capture(tmp_path, monkeypatch, helper=helper, entry=entry)
    calls = edges_named(report, "descend")
    assert len(calls) == 4 and len({edge.entry.invocation for edge in calls}) == 4
    assert len({edge.entry.code for edge in calls}) == 1
    for outer, inner in zip(calls, calls[1:]):
        assert inner.entry.caller_invocation == outer.entry.invocation
        assert report.children(outer.entry.invocation) == (inner,)


def test_wrapper_paths_are_not_collapsed_to_direct_source_calls(tmp_path, monkeypatch):
    # An outside-root trampoline is retained as an intervening frame while the
    # actual project frame entry still carries its immediate caller site.
    external_path = tmp_path.parent / (tmp_path.name + "_outside.py")
    external_text = "def trampoline(function, value):\n    return function(value)\n"
    external_path.write_text(external_text, encoding="utf-8")
    outside = {}
    exec(compile(external_text, str(external_path), "exec", dont_inherit=True), outside)
    helper = "def identity(value):\n    return value\n"
    entry = "from helper import identity\ndef run(left, right):\n    return identity(left)\n"
    def invoke(module, left, right):
        original = module.identity
        module.identity = lambda value: outside["trampoline"](original, value)
        return module.run(left, right)
    report, *_ = capture(tmp_path, monkeypatch, helper=helper, entry=entry, call=invoke)
    target, = edges_named(report, "identity")
    assert len(target.path) > 1
    assert target.entry.caller_invocation is None
    assert target.ancestor_identity_verified
    assert target.path[0].site.code != target.path[-1].site.code
    assert target.path[0].core_operation is None
    run, = edges_named(report, "run")
    wrapper, = report.children(run.entry.invocation)
    assert target.entry.ancestor_invocation == wrapper.entry.invocation
    assert target.path[-1].site.code == wrapper.entry.code
    original_call = wrapper.path[0].core_operation
    assert original_call is not None
    observations = report.by_core_call(original_call)
    assert [row.invocation for row in observations] == [wrapper.entry.invocation]
    assert all(row.invocation != target.entry.invocation for row in observations)
    assert report.parents(target.entry.invocation) == ()
    assert report.parents(target.entry.invocation, include_ancestors=True) == (target,)


def test_changed_source_never_keeps_old_core_or_target_links(tmp_path, monkeypatch):
    report, inventory, output, *_ = capture(tmp_path, monkeypatch)
    (tmp_path / "helper.py").write_text(HELPER.replace("return value", "return None"), encoding="utf-8")
    changed = link_calls(output, tmp_path, inventory=inventory)
    assert all(edge.target.status is not CallLinkStatus.VERIFIED for edge in edges_named(changed, "identity"))
    assert all(edge.target_body is None for edge in edges_named(changed, "identity"))
    with pytest.raises(ValueError, match="replay"):
        CallEdgeReport.from_dict(report.to_dict(), inventory=inventory)


def test_tampered_site_span_and_opcode_do_not_get_source_core_links(tmp_path, monkeypatch):
    report, inventory, output, *_ = capture(tmp_path, monkeypatch)
    first, _ = edges_named(report, "relay")
    def tamper(rows):
        row = next(row for row in rows if row["kind"] == "call_enter" and row["invocation_id"] == first.entry.invocation.invocation_id)
        row["caller"]["position"][2] += 1
        row["path"][0]["position"][2] += 1
    rewrite_events(output, tamper)
    changed = link_calls(output, tmp_path, inventory=inventory)
    bad, _ = edges_named(changed, "relay")
    assert bad.path[0].status is CallLinkStatus.MISMATCH
    assert bad.path[0].source is None and bad.path[0].core_operation is None
    with pytest.raises(ValueError, match="replay"):
        CallEdgeReport.from_dict(report.to_dict(), inventory=inventory)


def test_tampered_report_routes_and_authority_are_rejected(tmp_path, monkeypatch):
    report, inventory, *_ = capture(tmp_path, monkeypatch)
    document = report.to_dict()
    changed = deepcopy(document)
    changed["model"]["reference_routes"][0]["source"]["ref"] = "weak:1:1"
    with pytest.raises(ValueError):
        CallEdgeReport.from_dict(changed, inventory=inventory)
    changed = deepcopy(document)
    changed["transformation_authorized"] = True
    with pytest.raises(ValueError, match="replay"):
        CallEdgeReport.from_dict(changed, inventory=inventory)


def test_snapshot_tokens_do_not_cross_events(tmp_path, monkeypatch):
    report, *_ = capture(tmp_path, monkeypatch, call=lambda module, left, right: module.run([], []))
    run, = edges_named(report, "run")
    trace = report.trace_reference(run.entry.invocation)
    assert not any(route.destination.anchor != route.source.anchor and route.source.ref.startswith("snapshot:")
                   for route in report.model.reference_routes)
    assert all(not group.across_events for group in trace.groups)
    assert trace.issues


def test_binding_failure_has_no_callee_entry_and_unknown_exit(tmp_path, monkeypatch):
    entry = "from helper import relay\ndef run(left, right):\n    return relay()\n"
    def invoke(module, left, right):
        try:
            module.run(left, right)
        except TypeError:
            return None
    report, *_ = capture(tmp_path, monkeypatch, entry=entry, call=invoke)
    assert edges_named(report, "relay") == []
    run, = edges_named(report, "run")
    assert run.exit.completion is FrameCompletion.UNKNOWN and not run.exit_verified
    assert report.trace_reference(run.entry.invocation).issues


def test_gzip_families_replay_and_budget_ceiling(tmp_path, monkeypatch):
    report, inventory, output, *_ = capture(tmp_path, monkeypatch)
    document = report.to_dict()
    for path in output.iterdir():
        path.with_suffix(path.suffix + ".gz").write_bytes(gzip.compress(path.read_bytes()))
        path.unlink()
    assert CallEdgeReport.from_dict(document, inventory=inventory).to_dict() == document
    with pytest.raises(ValueError, match="independent verifier budget"):
        CallEdgeReport.from_dict(document, inventory=inventory, verification_budget=CallEdgeBudget(max_events=1))
    with pytest.raises(ValueError, match="budget"):
        link_calls(output, tmp_path, inventory=inventory, budget=CallEdgeBudget(max_raw_bytes=32))


def test_truncation_is_explicit_and_missing_exit_is_not_normal(tmp_path, monkeypatch):
    report, inventory, output, *_ = capture(tmp_path, monkeypatch, max_events=2)
    assert any(issue.kind is CallEdgeIssueKind.TRACE_COLLECTION_GAP for issue in report.model.issues)
    assert any(edge.exit is None for edge in report.model.edges)
    assert not any(edge.exit_verified for edge in report.model.edges if edge.exit is None)


def test_verified_inventory_path_avoids_heavy_source_preparation(tmp_path, monkeypatch):
    report, inventory, output, *_ = capture(tmp_path, monkeypatch)
    def forbidden(*args, **kwargs):
        raise AssertionError("verified inventory source maps should be reused")
    monkeypatch.setattr("scar.analysis.call_edges.prepare_source", forbidden)
    replay = link_calls(output, tmp_path, inventory=inventory)
    assert replay.to_dict() == report.to_dict()
    run, = edges_named(replay, "run")
    assert replay.trace_reference(run.exit).routes


def test_optional_inventory_preserves_source_links_and_identity_boundaries(tmp_path, monkeypatch):
    report, inventory, output, *_ = capture(tmp_path, monkeypatch)
    standalone = link_calls(output, tmp_path)
    relay, _ = edges_named(standalone, "relay")
    assert relay.path[0].status is CallLinkStatus.VERIFIED
    assert relay.path[0].source is not None and relay.path[0].core_operation is None
    assert standalone.model.inventory_sha256 is None
    run, = edges_named(standalone, "run")
    assert standalone.trace_reference(run.exit).issues
    assert CallEdgeReport.from_dict(standalone.to_dict()).to_dict() == standalone.to_dict()


def test_zero_first_line_is_an_unmatched_code_boundary_not_a_trace_parse_error(tmp_path, monkeypatch):
    report, inventory, output, *_ = capture(tmp_path, monkeypatch)
    path, = output.glob("call-codes.*.jsonl")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    next(row for row in rows if row["qualname"] == "identity")["first_line"] = 0
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    refresh_byte_count(output)
    changed = link_calls(output, tmp_path, inventory=inventory)
    assert all(edge.target.status is CallLinkStatus.MISMATCH for edge in edges_named(changed, "identity"))
    assert all(edge.target.definition is None and edge.target_body is None for edge in edges_named(changed, "identity"))


def test_forged_stable_code_key_cannot_reuse_definition_or_body(tmp_path, monkeypatch):
    report, inventory, output, *_ = capture(tmp_path, monkeypatch)
    path, = output.glob("call-codes.*.jsonl")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    description = next(row for row in rows if row["qualname"] == "identity")
    original, forged = description["key"], "pycode-v2:" + "0" * 64
    description["key"] = forged
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    def tamper(events):
        for row in events:
            if row["code"] == original:
                row["code"] = forged
                if row["kind"] == "call_exit":
                    row["return_site"]["code"] = forged
    rewrite_events(output, tamper)
    changed = link_calls(output, tmp_path, inventory=inventory)
    assert all(edge.target.status is CallLinkStatus.MISMATCH for edge in edges_named(changed, "identity"))
    run, = edges_named(changed, "run")
    traced = changed.trace_reference(run.exit)
    assert traced.issues
    assert not any(route.source.role is ReferenceRole.PARAMETER and route.source.name == "left" for route in traced.routes)


def test_concurrent_threads_share_static_calls_without_sharing_invocation_routes(tmp_path, monkeypatch):
    def invoke(module, left, right):
        barrier, results = threading.Barrier(3), []
        def worker(first, second):
            barrier.wait()
            results.append(module.run(first, second))
        previous = threading.getprofile()
        threading.setprofile(sys.getprofile())
        try:
            workers = [threading.Thread(target=worker, args=values) for values in ((left, right), (right, left))]
            for worker_thread in workers:
                worker_thread.start()
            barrier.wait()
            for worker_thread in workers:
                worker_thread.join()
        finally:
            threading.setprofile(previous)
        return results
    report, *_ = capture(tmp_path, monkeypatch, call=invoke)
    runs = edges_named(report, "run")
    assert len(runs) == 2 and len({edge.entry.invocation.thread_id for edge in runs}) == 2
    for run in runs:
        traced = report.trace_reference(run.exit)
        assert traced.routes
        assert {issue.kind for issue in traced.issues} == {CallEdgeIssueKind.ARGUMENT_ROUTING_UNVERIFIED}
        assert all(item.observed_in.thread_id == run.entry.invocation.thread_id
                   for group in traced.groups for item in group.occurrences)
        assert len(report.children(run.entry.invocation)) == 2


def test_two_real_processes_with_restarted_invocation_ids_do_not_cross_link(tmp_path):
    helper_path, entry_path = tmp_path / "helper.py", tmp_path / "entry.py"
    helper_path.write_text(HELPER, encoding="utf-8")
    entry_path.write_text(ENTRY, encoding="utf-8")
    trace = tmp_path / "trace"
    script = """import sys
from pathlib import Path
from scar.trace.call_edges import CallEdgeRecorder
root, output = map(Path, sys.argv[1:])
sys.path.insert(0, str(root))
from entry import run
class Token: pass
left, right = Token(), Token()
recorder = CallEdgeRecorder(output, root)
sys.setprofile(recorder.profile)
try:
    assert run(left, right) is left
finally:
    sys.setprofile(None)
    recorder.close()
"""
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for _ in range(2):
        run = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(trace)],
                             capture_output=True, text=True, env=environment)
        assert run.returncode == 0, run.stderr
    inventory = inventory_program(entry_path, project_root=tmp_path)
    report = link_calls(trace, tmp_path, inventory=inventory)
    runs = edges_named(report, "run")
    assert len(runs) == 2 and {edge.entry.invocation.invocation_id for edge in runs} == {1}
    assert len({edge.entry.invocation.process_id for edge in runs}) == 2
    for run in runs:
        traced = report.trace_reference(run.exit)
        assert traced.routes
        assert {issue.kind for issue in traced.issues} == {CallEdgeIssueKind.ARGUMENT_ROUTING_UNVERIFIED}
        assert all(item.observed_in.process_id == run.entry.invocation.process_id
                   for group in traced.groups for item in group.occurrences)
        assert len(report.children(run.entry.invocation)) == 2


def test_raw_reference_cannot_claim_another_process_identity(tmp_path, monkeypatch):
    report, inventory, output, *_ = capture(tmp_path, monkeypatch)
    def tamper(rows):
        first = next(row for row in rows if row["kind"] == "call_enter")
        first["parameters"][0]["ref"] = "weak:1:1"
    rewrite_events(output, tamper)
    with pytest.raises(ValueError, match="another process"):
        link_calls(output, tmp_path, inventory=inventory)


def test_parent_cannot_be_an_already_returned_same_code_invocation(tmp_path, monkeypatch):
    report, inventory, output, *_ = capture(tmp_path, monkeypatch)
    first, second = edges_named(report, "relay")
    _, child = edges_named(report, "identity")
    assert first.exit.anchor.index < child.entry.anchor.index < second.exit.anchor.index
    def tamper(rows):
        row = next(row for row in rows if row["kind"] == "call_enter"
                   and row["invocation_id"] == child.entry.invocation.invocation_id)
        row["caller_invocation_id"] = row["ancestor_invocation_id"] = first.entry.invocation.invocation_id
    rewrite_events(output, tamper)
    changed = link_calls(output, tmp_path, inventory=inventory)
    _, bad = edges_named(changed, "identity")
    assert not bad.caller_identity_verified and not bad.ancestor_identity_verified
    assert CallEdgeIssueKind.INVOCATION_MISMATCH in {issue.kind for issue in bad.issues}
    assert all(site.source is None and site.core_operation is None for site in bad.path)
    assert changed.parents(bad.entry.invocation, include_ancestors=True) == ()


def test_parent_cannot_skip_an_active_same_code_recursive_frame(tmp_path, monkeypatch):
    helper = "def descend(value, depth):\n    if depth:\n        return descend(value, depth - 1)\n    return value\n"
    entry = "from helper import descend\ndef run(left, right):\n    return descend(left, 3)\n"
    report, inventory, output, *_ = capture(tmp_path, monkeypatch, helper=helper, entry=entry)
    first, second, child, _ = edges_named(report, "descend")
    assert first.entry.anchor.index < second.entry.anchor.index < child.entry.anchor.index < first.exit.anchor.index
    def tamper(rows):
        row = next(row for row in rows if row["kind"] == "call_enter"
                   and row["invocation_id"] == child.entry.invocation.invocation_id)
        row["caller_invocation_id"] = row["ancestor_invocation_id"] = first.entry.invocation.invocation_id
    rewrite_events(output, tamper)
    changed = link_calls(output, tmp_path, inventory=inventory)
    bad = edges_named(changed, "descend")[2]
    assert not bad.caller_identity_verified and not bad.ancestor_identity_verified
    assert CallEdgeIssueKind.INVOCATION_MISMATCH in {issue.kind for issue in bad.issues}
    assert all(site.source is None and site.core_operation is None for site in bad.path)


@pytest.mark.parametrize("field,value", [
    ("bytes", 0), ("events", 0), ("invocations", 0), ("codes", 0),
    ("open_invocations", 1), ("unknown_exits", 999), ("suspended_exits", 999),
    ("active_frames", 1), ("event_attempts", 0), ("invocation_attempts", 0),
    ("limits.max_events", 1), ("limits.max_bytes", 1), ("limits.max_codes", 1),
    ("limits.max_values", 1), ("limits.max_path", 0),
])
def test_metadata_known_counts_and_limits_are_independently_checked(tmp_path, monkeypatch, field, value):
    _, inventory, output, *_ = capture(tmp_path, monkeypatch)
    path, = output.glob("call-meta.*.json")
    meta = json.loads(path.read_text())
    if field.startswith("limits."):
        meta["limits"][field.split(".")[1]] = value
    else:
        meta[field] = value
    path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ValueError):
        link_calls(output, tmp_path, inventory=inventory)


@pytest.mark.parametrize("helper,entry,target,formal", [
    ("class Holder:\n    def method(self, value=None):\n        return self\n",
     "from helper import Holder\ndef run(left, right):\n    return left.method(right)\n", "Holder.method", "self"),
    ("class Holder:\n    def method(self, value=None):\n        return self\n",
     "from helper import Holder\ndef run(left, right):\n    method = left.method\n    return method(right)\n", "Holder.method", "self"),
    ("def choose(first, second):\n    return first\n",
     "from functools import partial\nfrom helper import choose\ndef run(left, right):\n    pick = partial(choose, left)\n    return pick(right)\n", "choose", "first"),
    ("def choose(first, second=None):\n    return second\n",
     "from helper import choose\ndef run(left, right):\n    choose.__defaults__ = (left,)\n    return choose(right)\n", "choose", "second"),
])
def test_aliasing_cannot_turn_raw_signature_plan_into_argument_provenance(
        tmp_path, monkeypatch, helper, entry, target, formal):
    def invoke(module, left, right):
        shared = module.Holder() if hasattr(module, "Holder") else left
        return module.run(shared, shared)
    report, inventory, output, *_ = capture(tmp_path, monkeypatch, helper=helper, entry=entry, call=invoke)
    run, = edges_named(report, "run")
    callee, = edges_named(report, target)
    assert callee.exit_verified and callee.caller_identity_verified
    traced = report.trace_reference(run.exit)
    assert traced.issues
    callee_traced = report.trace_reference(callee.exit)
    assert CallEdgeIssueKind.ARGUMENT_ROUTING_UNVERIFIED in {issue.kind for issue in callee_traced.issues}
    assert not any(route.kind is ReferenceRouteKind.SOURCE_ARGUMENT_LOCAL for route in report.model.reference_routes)
    # Even equal weak references cannot promote raw explicit-argument order to
    # a receiver/partial/default-state provenance route.
    assert any(item.owner == callee.entry.invocation and item.role is ReferenceRole.PARAMETER and item.name == formal
               for group in callee_traced.groups for item in group.occurrences)
    assert not any(item.owner == run.entry.invocation and item.role is ReferenceRole.PARAMETER
                   for group in traced.groups for item in group.occurrences)
    assert CallEdgeReport.from_dict(report.to_dict(), inventory=inventory).to_dict() == report.to_dict()

