"""Actual tiny Python programs drive conditional operand and return routes."""
from dataclasses import replace
import sys
from types import ModuleType

import pytest

from scar.analysis.call_edges import _link_call_model
from scar.analysis.call_operand_reader import OperandReadIssue, read_call_operands
from scar.analysis.call_operand_routes import build_operand_routes, query_operand_routes
from scar.analysis.program_inventory import inventory_program
from scar.ir.program.call_operands import OperandEventKind, OperandGap
from scar.ir.program.call_operand_routes import (
    OperandQueryRouteKind, OperandRouteBudget, OperandRouteCondition,
    OperandRouteIssueKind, OperandRouteModel, ReferenceConsistency,
)
from scar.ir.program.compilation import CallCompilationProfile
from scar.trace.call_edges import install as install_frames


HELPER = '''def choose(left, right):
    return left
def relay(a, b):
    selected = choose(a, b)
    return selected
'''
ENTRY = '''from helper import relay
def run(x, y):
    first = relay(x, y)
    second = relay(y, x)
    return first
'''


class Token:
    pass


def captured(tmp_path, monkeypatch, *, helper=HELPER, entry=ENTRY, shared=False,
             weak=True, invoke=None):
    from scar.trace.call_operands import install as install_operands
    helper_path, entry_path = tmp_path / 'helper.py', tmp_path / 'entry.py'
    helper_path.write_text(helper)
    entry_path.write_text(entry)
    helper_module, entry_module = ModuleType('helper'), ModuleType('entry')
    exec(compile(helper, str(helper_path), 'exec', dont_inherit=True), helper_module.__dict__)
    monkeypatch.setitem(sys.modules, 'helper', helper_module)
    exec(compile(entry, str(entry_path), 'exec', dont_inherit=True), entry_module.__dict__)
    factory = Token if weak else object
    left, right = factory(), factory()
    if shared:
        right = left
    output = tmp_path / 'trace'
    old_profile, old_thread_profile = sys.getprofile(), __import__('threading').getprofile()
    recorder = install_frames(output, tmp_path)
    observer = install_operands(recorder)
    try:
        result = invoke(entry_module, left, right) if invoke else entry_module.run(left, right)
    finally:
        observer.stop()
        sys.setprofile(old_profile)
        __import__('threading').setprofile(old_thread_profile)
        recorder.close()
        observer.close()
    inventory = inventory_program(entry_path, project_root=tmp_path, calls_trace=output)
    scan = read_call_operands(output, tmp_path)
    model, sources = _link_call_model(output, tmp_path, inventory, scan.frame_budget,
        compilation_profile=CallCompilationProfile.RECORDED_FUTURE_FLAGS,
        frame_scan=scan.frame_scan, entries=scan.entries, exits=scan.exits, allow_v6=True)
    routes = build_operand_routes(call_model=model, operand_model=scan, inventory=inventory, sources=sources)
    return model, scan, inventory, sources, routes, result, left


def named(model, name):
    names = {capture.code.key: capture.code.qualname for capture in model.codes}
    return [edge for edge in model.edges if names[edge.entry.code] == name]


def rebuilt(case, scan, *, budget=OperandRouteBudget()):
    model, _, inventory, sources, _, _, _ = case
    return build_operand_routes(call_model=model, operand_model=scan, inventory=inventory,
                                sources=sources, budget=budget)


@pytest.mark.parametrize('shared', [False, True])
@pytest.mark.parametrize('weak', [False, True])
def test_two_file_query_reaches_only_run_x_without_reference_identity_selection(tmp_path, monkeypatch, shared, weak):
    model, scan, inventory, sources, routes, result, left = captured(tmp_path, monkeypatch, shared=shared, weak=weak)
    assert result is left
    run, = named(model, 'run')
    first, second = named(model, 'relay')
    choose_first, choose_second = named(model, 'choose')
    query = query_operand_routes(model, routes, run.entry.invocation)
    assert {(value.invocation, value.formal_name) for value in query.endpoints} == {(run.entry.invocation, 'x')}
    assert {step.kind for step in query.routes} >= {OperandQueryRouteKind.ARGUMENT, OperandQueryRouteKind.COMPLETION}
    owners = {value.invocation for value in query.nodes}
    assert {run.entry.invocation, first.entry.invocation, choose_first.entry.invocation} <= owners
    assert not owners & {second.entry.invocation, choose_second.entry.invocation}
    assert not any(value.invocation == run.entry.invocation and value.formal_name == 'y' for value in query.nodes)
    incoming = [route for route in routes.argument_routes if route.callee == choose_first.entry.invocation]
    assert len(incoming) == 2 and {route.actual_index for route in incoming} == {0, 1}
    assert len({route.actual_use for route in incoming}) == 2
    assert len({(route.load_anchor, route.load_suboperand) for route in incoming}) == 2
    assert query.conditional_only and query.conditions == tuple(OperandRouteCondition)
    assert query.obligations and any(item.incomplete_effect_operations for item in query.obligations)
    assert not any((query.function_environment_established, query.contents_or_effects_established,
                    query.world_equivalence_established, query.transformation_authorized))
    if not weak:
        assert all(route.reference_consistency is ReferenceConsistency.UNKNOWN for route in incoming)
    assert OperandRouteModel.from_dict(routes.to_dict()).to_dict() == routes.to_dict()


def test_same_call_same_name_twice_keeps_fused_suboperands_and_distinct_uses(tmp_path, monkeypatch):
    helper = HELPER.replace('choose(a, b)', 'choose(a, a)')
    model, scan, _, _, routes, _, _ = captured(tmp_path, monkeypatch, helper=helper, shared=True)
    first, _ = named(model, 'choose')
    incoming = [route for route in routes.argument_routes if route.callee == first.entry.invocation]
    assert {route.actual_index for route in incoming} == {0, 1}
    assert len({route.actual_use for route in incoming}) == 2
    assert len({route.actual_value for route in incoming}) == 1
    assert len({route.load_anchor for route in incoming}) == 1
    assert {route.load_suboperand for route in incoming} == {0, 1}
    run, = named(model, 'run')
    query = query_operand_routes(model, routes, run.entry.invocation)
    assert [(value.invocation, value.formal_name) for value in query.endpoints] == [(run.entry.invocation, 'x')]
    # Both routes remain stored even though the selected return visits only
    # formal left. Neither equal ValueIDs nor tokens collapse the argument uses.
    assert len(incoming) == 2


def test_existing_default_is_allowed_when_all_fixed_formals_are_explicit(tmp_path, monkeypatch):
    helper = HELPER.replace('choose(left, right)', 'choose(left, right=[])')
    model, _, _, _, routes, _, _ = captured(tmp_path, monkeypatch, helper=helper)
    choose = {edge.entry.invocation for edge in named(model, 'choose')}
    assert len([route for route in routes.argument_routes if route.callee in choose]) == 4


@pytest.mark.parametrize('shared', [False, True])
@pytest.mark.parametrize('flag', [False, True])
def test_branch_merge_does_not_claim_all_static_predecessors_as_actual_sources(tmp_path, monkeypatch, shared, flag):
    helper = ('def choose(flag, left, right):\n'
              '    if flag:\n        chosen = left\n'
              '    else:\n        chosen = right\n'
              '    return chosen\n')
    entry = 'from helper import choose\ndef run(flag, x, y):\n    return choose(flag, x, y)\n'
    model, _, _, _, routes, result, left = captured(
        tmp_path, monkeypatch, helper=helper, entry=entry, shared=shared,
        invoke=lambda module, left, right: module.run(flag, left, right))
    if flag or shared:
        assert result is left
    run, = named(model, 'run')
    choose, = named(model, 'choose')
    assert len([route for route in routes.argument_routes if route.callee == choose.entry.invocation]) == 3
    assert any(route.callee == choose.entry.invocation for route in routes.completion_routes)
    query = query_operand_routes(model, routes, run.entry.invocation)
    assert any(issue.kind is OperandRouteIssueKind.CONTROL_SELECTION_UNVERIFIED for issue in query.issues)
    assert not any(value.invocation == run.entry.invocation and value.formal_name in {'x', 'y'}
                   for value in query.nodes)
    assert len(query.endpoints) == 1
    assert query.endpoints[0].invocation == choose.entry.invocation


def test_branch_merge_with_common_ssa_source_needs_no_predecessor_selection(tmp_path, monkeypatch):
    helper = ('def choose(flag, left, right):\n'
              '    if flag:\n        chosen = left\n'
              '    else:\n        chosen = left\n'
              '    return chosen\n')
    entry = 'from helper import choose\ndef run(flag, x, y):\n    return choose(flag, x, y)\n'
    model, _, _, _, routes, _, _ = captured(
        tmp_path, monkeypatch, helper=helper, entry=entry,
        invoke=lambda module, left, right: module.run(True, left, right))
    run, = named(model, 'run')
    query = query_operand_routes(model, routes, run.entry.invocation)
    assert {(value.invocation, value.formal_name) for value in query.endpoints} == {(run.entry.invocation, 'x')}
    assert not any(issue.kind is OperandRouteIssueKind.CONTROL_SELECTION_UNVERIFIED for issue in query.issues)


@pytest.mark.parametrize('adapter', ['method', 'partial', 'default'])
def test_bound_method_partial_and_consumed_default_cannot_create_false_argument_routes(tmp_path, monkeypatch, adapter):
    if adapter == 'method':
        helper = 'class Holder:\n    def method(self, value):\n        return self\n'
        entry = 'from helper import Holder\ndef run(x, y):\n    fn = x.method\n    return fn(y)\n'
        invoke = lambda module, left, right: module.run(*(lambda value: (value, value))(module.Holder()))
    elif adapter == 'partial':
        helper = 'def choose(left, right):\n    return left\n'
        entry = ('from functools import partial\nfrom helper import choose\n'
                 'def run(x, y):\n    fn = partial(choose, x)\n    return fn(y)\n')
        invoke = None
    else:
        helper = 'def choose(left, right=None):\n    return left\n'
        entry = 'from helper import choose\ndef run(x, y):\n    return choose(y)\n'
        invoke = None
    model, _, _, _, routes, _, _ = captured(tmp_path, monkeypatch, helper=helper, entry=entry,
                                            invoke=invoke, shared=True)
    names = {capture.code.key: capture.code.qualname for capture in model.codes}
    unsupported = {edge.entry.invocation for edge in model.edges
                   if names[edge.entry.code] in {'choose', 'Holder.method'}}
    assert unsupported and not any(route.callee in unsupported for route in routes.argument_routes)
    assert any(issue.kind in (OperandRouteIssueKind.DISPATCH_BOUNDARY,
                              OperandRouteIssueKind.HANDSHAKE_BOUNDARY) for issue in routes.issues)


@pytest.mark.parametrize('mutation', ['instruction_missing', 'position', 'load_slot', 'hook_epoch', 'layout'])
def test_contradictory_capture_cannot_route_the_first_choose_arguments(tmp_path, monkeypatch, mutation):
    case = captured(tmp_path, monkeypatch)
    model, scan, _, _, _, _, _ = case
    first, _ = named(model, 'choose')
    handshake = next(item for item in scan.handshakes if item.invocation == first.entry.invocation)
    attempt = next(item for item in scan.attempts if item.index == handshake.attempt_index)
    load_instruction = next(item for item in reversed(scan.instructions)
                            if item.invocation == attempt.invocation and item.index < attempt.index
                            and len(item.loads) == 2)
    events = list(scan.events)
    if mutation == 'instruction_missing':
        events.remove(load_instruction)
    elif mutation == 'position':
        changed = replace(load_instruction, site=replace(load_instruction.site, position=(999, 999, 0, 1)))
        events[events.index(load_instruction)] = changed
    elif mutation == 'load_slot':
        first_load, second_load = load_instruction.loads
        changed = replace(load_instruction, loads=(replace(first_load, slot='other'), second_load))
        events[events.index(load_instruction)] = changed
    elif mutation == 'hook_epoch':
        events[events.index(load_instruction)] = replace(load_instruction, hook_epoch=load_instruction.hook_epoch + 1)
    else:
        # The preload layout is never the binding authority: changing CALL's
        # current flags while keeping its entered code must stop the route.
        layout = replace(attempt.dispatch.layout, flags=attempt.dispatch.layout.flags ^ 0x1000000)
        events[events.index(attempt)] = replace(attempt, dispatch=replace(attempt.dispatch, layout=layout))
    changed = rebuilt(case, replace(scan, events=tuple(events)))
    assert not any(route.callee == first.entry.invocation for route in changed.argument_routes)
    assert not any(route.callee == first.entry.invocation for route in changed.completion_routes)
    assert changed.issues


def test_global_hook_gap_before_complete_window_also_blocks_completion(tmp_path, monkeypatch):
    case = captured(tmp_path, monkeypatch)
    model, scan, _, _, _, _, _ = case
    first, _ = named(model, 'choose')
    handshake = next(item for item in scan.handshakes if item.invocation == first.entry.invocation)
    attempt = next(item for item in scan.attempts if item.index == handshake.attempt_index)
    run, = named(model, 'run')
    prior = next(item for item in scan.instructions if item.invocation == run.entry.invocation
                 and item.index < attempt.index)
    gap = OperandGap(prior.anchor, prior.index, OperandEventKind.GAP, prior.process_id,
                     prior.thread_id, None, prior.frame_index, prior.hook_epoch, 'HOOK_INTERFERENCE')
    events = tuple(gap if item is prior else item for item in scan.events)
    changed = rebuilt(case, replace(scan, events=events))
    assert not any(route.callee == first.entry.invocation for route in changed.argument_routes)
    assert not any(route.callee == first.entry.invocation for route in changed.completion_routes)
    assert any(issue.kind is OperandRouteIssueKind.CAPTURE_GAP for issue in changed.issues)


def test_process_wide_original_frame_gap_blocks_otherwise_direct_verified_routes(tmp_path, monkeypatch):
    case = captured(tmp_path, monkeypatch)
    model, scan, _, _, routes, _, _ = case
    assert routes.argument_routes and any(edge.caller_identity_verified for edge in model.edges)
    process = scan.metadata[0].process_id
    issue = OperandReadIssue('FRAME_COLLECTION_GAP', 'original frame observations are incomplete', process)
    changed = rebuilt(case, replace(scan, issues=(*scan.issues, issue)))
    assert not changed.argument_routes and not changed.completion_routes
    assert any(value.kind is OperandRouteIssueKind.CAPTURE_GAP for value in changed.issues)


def test_wrong_handshake_cannot_borrow_another_same_code_invocation(tmp_path, monkeypatch):
    case = captured(tmp_path, monkeypatch, shared=True)
    model, scan, _, _, _, _, _ = case
    first, second = named(model, 'choose')
    one = next(item for item in scan.handshakes if item.invocation == first.entry.invocation)
    two = next(item for item in scan.handshakes if item.invocation == second.entry.invocation)
    events = tuple(replace(item, attempt_index=one.attempt_index) if item is two else item for item in scan.events)
    changed = rebuilt(case, replace(scan, events=events))
    assert not any(route.callee in (first.entry.invocation, second.entry.invocation)
                   for route in changed.argument_routes)
    assert not any(route.callee in (first.entry.invocation, second.entry.invocation)
                   for route in changed.completion_routes)


@pytest.mark.parametrize('budget', [OperandRouteBudget(max_routes=1), OperandRouteBudget(max_template_values=1)])
def test_construction_budget_preserves_explicit_missing_routes(tmp_path, monkeypatch, budget):
    case = captured(tmp_path, monkeypatch)
    model, scan, _, _, _, _, _ = case
    routes = rebuilt(case, scan, budget=budget)
    assert any(issue.kind is OperandRouteIssueKind.ROUTE_BUDGET for issue in routes.issues)
    assert not routes.argument_routes
    run, = named(model, 'run')
    query = query_operand_routes(model, routes, run.entry.invocation)
    assert any(issue.kind is OperandRouteIssueKind.ROUTE_BUDGET for issue in query.issues)


def test_query_budget_is_explicit_and_keeps_no_opaque_all_input_aliases(tmp_path, monkeypatch):
    model, _, _, _, routes, _, _ = captured(tmp_path, monkeypatch)
    run, = named(model, 'run')
    query = query_operand_routes(model, routes, run.entry.invocation, max_steps=1)
    assert query.reference_steps == 1 and query.max_reference_steps == 1
    assert any(issue.kind is OperandRouteIssueKind.QUERY_BUDGET for issue in query.issues)
    assert not any(node.formal_name == 'y' for node in query.nodes)


@pytest.mark.parametrize('value', [0, -1, True, 1.5])
def test_route_budget_requires_exact_positive_integers(value):
    with pytest.raises(ValueError):
        OperandRouteBudget(max_routes=value)
    with pytest.raises(ValueError):
        OperandRouteBudget(max_template_values=value)
