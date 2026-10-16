"""Real captures test per-process sparse-window routing and its boundaries."""
from dataclasses import replace
import ast
import inspect
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from scar.analysis.call_edges import _link_call_model
from scar.analysis.call_operand_reader import read_call_operands
from scar.analysis.call_operand_routes import (
    _Boundary, _instruction_plan, _load_window, build_operand_routes, query_operand_routes,
)
from scar.analysis.program_inventory import inventory_program
from scar.ir.program.call_operands import (
    CALL_WINDOWS_RULE, LOAD_OCCURRENCES_RULE, OperandEventKind, OperandGap,
)
from scar.ir.program.call_operand_routes import OperandRouteCondition, OperandRouteIssueKind
from scar.ir.program.compilation import CallCompilationProfile
from scar.trace.call_edges import install as install_frames


HELPER = ('def choose(left, right):\n    return left\n'
          'def relay(a, b):\n    selected = choose(a, b)\n    return selected\n')
ENTRY = ('from helper import relay\ndef run(x, y):\n'
         '    first = relay(x, y)\n    second = relay(y, x)\n    return first\n')


def capture(tmp_path, monkeypatch, *, rule=CALL_WINDOWS_RULE, helper=HELPER,
            entry=ENTRY, shared=False, warmup=None, invoke=None, max_events=100000):
    from scar.trace.call_operands import install as install_operands
    project = tmp_path / 'project'
    project.mkdir()
    helper_path, entry_path = project / 'helper.py', project / 'entry.py'
    helper_path.write_text(helper)
    entry_path.write_text(entry)
    helper_module, entry_module = ModuleType('helper'), ModuleType('entry')
    exec(compile(helper, str(helper_path), 'exec', dont_inherit=True), helper_module.__dict__)
    monkeypatch.setitem(sys.modules, 'helper', helper_module)
    exec(compile(entry, str(entry_path), 'exec', dont_inherit=True), entry_module.__dict__)
    left, right = object(), object()
    if shared:
        right = left
    output = tmp_path / 'trace'
    old_profile, old_thread_profile = sys.getprofile(), __import__('threading').getprofile()
    recorder = install_frames(output, project)
    observer = None
    try:
        observer = install_operands(recorder, capture='windows' if rule == CALL_WINDOWS_RULE else 'instructions',
                                    max_events=max_events)
        if warmup is not None:
            warmup(helper_module, entry_module)
        result = invoke(entry_module, left, right) if invoke else entry_module.run(left, right)
    finally:
        if observer is not None:
            observer.stop()
        sys.setprofile(old_profile)
        __import__('threading').setprofile(old_thread_profile)
        recorder.close()
        if observer is not None:
            observer.close()
    inventory = inventory_program(entry_path, project_root=project, calls_trace=output)
    scan = read_call_operands(output, project)
    model, sources = _link_call_model(output, project, inventory, scan.frame_budget,
        compilation_profile=CallCompilationProfile.RECORDED_FUTURE_FLAGS,
        frame_scan=scan.frame_scan, entries=scan.entries, exits=scan.exits,
        include_identity_routes=False, allow_v6=True)
    routes = build_operand_routes(call_model=model, operand_model=scan, inventory=inventory, sources=sources)
    return model, scan, inventory, sources, routes, result, left


def named(model, name):
    names = {capture.code.key: capture.code.qualname for capture in model.codes}
    return [edge for edge in model.edges if names[edge.entry.code] == name]


def rebuild(case, scan):
    model, _, inventory, sources, _, _, _ = case
    return build_operand_routes(call_model=model, operand_model=scan, inventory=inventory, sources=sources)


def check_query(case):
    model, _, _, _, routes, result, left = case
    assert result is left
    run, = named(model, 'run')
    query = query_operand_routes(model, routes, run.entry.invocation)
    assert {(node.invocation, node.formal_name) for node in query.endpoints} == {(run.entry.invocation, 'x')}
    assert query.conditions == tuple(OperandRouteCondition)
    assert len(query.conditions) == 8
    assert query.conditional_only and not query.transformation_authorized
    assert not any((query.function_environment_established, query.contents_or_effects_established,
                    query.world_equivalence_established))
    first, second = named(model, 'relay')
    first_choose, = [edge for edge in named(model, 'choose')
                    if edge.entry.caller_invocation == first.entry.invocation]
    second_choose, = [edge for edge in named(model, 'choose')
                     if edge.entry.caller_invocation == second.entry.invocation]
    owners = {node.invocation for node in query.nodes}
    assert {first.entry.invocation, first_choose.entry.invocation} <= owners
    assert not owners & {second.entry.invocation, second_choose.entry.invocation}
    choose_routes = [route for route in routes.argument_routes if route.callee == first_choose.entry.invocation]
    assert len(choose_routes) == 2
    assert len({route.actual_use for route in choose_routes}) == 2
    assert len({(route.load_anchor, route.load_suboperand) for route in choose_routes}) == 2
    return query


@pytest.mark.parametrize('rule', [LOAD_OCCURRENCES_RULE, CALL_WINDOWS_RULE])
@pytest.mark.parametrize('shared', [False, True])
def test_real_two_file_routes_keep_distinct_occurrences_under_each_profile(tmp_path, monkeypatch, rule, shared):
    case = capture(tmp_path, monkeypatch, rule=rule, shared=shared)
    assert {metadata.rule for metadata in case[1].metadata} == {rule}
    check_query(case)


def test_sparse_profile_survives_large_inlined_loop_before_real_call_chain(tmp_path, monkeypatch):
    helper = HELPER + 'def warmup(values):\n    return [value * value for value in values if value % 2]\n'
    case = capture(tmp_path, monkeypatch, helper=helper, max_events=1000,
                   warmup=lambda helper, entry: helper.warmup(list(range(10000))))
    scan = case[1]
    assert all(not meta.errors and meta.dropped_events == 0 for meta in scan.metadata)
    assert len(scan.events) < 1000
    assert not scan.gaps
    check_query(case)


def test_old_profile_does_not_use_sparse_selection_or_suspended_caller_guard(tmp_path, monkeypatch):
    case = capture(tmp_path, monkeypatch, rule=LOAD_OCCURRENCES_RULE)
    import scar.trace.operand_bytecode as bytecode
    def forbidden(*args, **kwargs):
        raise AssertionError('old profile must not invoke new sparse selector')
    monkeypatch.setattr(bytecode, 'call_window_selection', forbidden)
    assert rebuild(case, case[1]).to_dict() == case[4].to_dict()
    check_query(case)


def test_sparse_profile_recomputes_selector_from_current_verified_source_code(tmp_path, monkeypatch):
    case = capture(tmp_path, monkeypatch)
    import scar.trace.operand_bytecode as bytecode
    original = bytecode.call_window_selection
    seen = []
    def verified(code, instructions=None):
        seen.append(code)
        return original(code, instructions)
    monkeypatch.setattr(bytecode, 'call_window_selection', verified)
    assert rebuild(case, case[1]).to_dict() == case[4].to_dict()
    assert seen and all(any(code is compiled for compiled in case[3].objects.values()) for code in seen)


@pytest.mark.parametrize('mutation', ['missing', 'conflicting'])
def test_capture_rule_requires_one_metadata_record_for_each_attempt_process(tmp_path, monkeypatch, mutation):
    case = capture(tmp_path, monkeypatch)
    scan = case[1]
    metadata = (() if mutation == 'missing' else
                (*scan.metadata, replace(scan.metadata[0], rule=LOAD_OCCURRENCES_RULE)))
    routes = rebuild(case, replace(scan, metadata=metadata))
    assert not routes.argument_routes and not routes.completion_routes
    assert any(issue.kind is OperandRouteIssueKind.CAPTURE_GAP for issue in routes.issues)


def _checked_loop_windows(case):
    model, scan, _, sources, _, _, _ = case
    repeat, = named(model, 'repeat')
    attempts = [attempt for attempt in scan.attempts if attempt.invocation == repeat.entry.invocation]
    instructions = [item for item in scan.instructions if item.invocation == repeat.entry.invocation]
    indices = [item.index for item in instructions]
    code = sources.objects[repeat.entry.code]
    tree = ast.parse(Path(code.co_filename).read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    previous, checked = 0, []
    for attempt in attempts:
        matching = [node for node in calls if (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset) == attempt.site.position]
        node, = matching
        result = _load_window(attempt, node, code, instructions, indices, previous,
                              {}, {}, {}, {}, CALL_WINDOWS_RULE)
        checked.append((attempt, node, result, previous))
        previous = attempt.index
    return repeat, instructions, code, checked


def test_repeated_same_call_window_cannot_borrow_prefix_from_earlier_loop_iteration(tmp_path, monkeypatch):
    helper = HELPER + ('def repeat(a, b, flags):\n'
                       '    for flag in flags:\n        selected = choose(a, b)\n'
                       '    return selected\n')
    case = capture(tmp_path, monkeypatch, helper=helper,
                   warmup=lambda helper, entry: helper.repeat(object(), object(), [False, True, False]))
    repeat, instructions, code, checked = _checked_loop_windows(case)
    assert len(checked) == 3
    assert all(len(observations) == 3 for _, _, observations, _ in checked)
    attempt, node, observations, previous = checked[-1]
    first_event = observations[0][0]
    incomplete = [event for event in instructions if event != first_event]
    with pytest.raises(_Boundary) as failure:
        _load_window(attempt, node, code, incomplete, [event.index for event in incomplete], previous,
                     {}, {}, {}, {}, CALL_WINDOWS_RULE)
    assert failure.value.kind is OperandRouteIssueKind.INSTRUCTION_WINDOW
    # C0 does not lower for-loops into a core body yet; the real raw window
    # check is a parser test, not a claim that this function has a core route.
    assert not any(route.caller == repeat.entry.invocation for route in case[4].argument_routes)
    check_query(case)


@pytest.mark.parametrize('scope', ['local', 'global'])
def test_sparse_unknown_gap_stops_arguments_and_completion(tmp_path, monkeypatch, scope):
    case = capture(tmp_path, monkeypatch)
    model, scan, _, _, _, _, _ = case
    first, _ = named(model, 'choose')
    handshake = next(item for item in scan.handshakes if item.invocation == first.entry.invocation)
    attempt = next(item for item in scan.attempts if item.index == handshake.attempt_index)
    prior = next(item for item in scan.instructions if item.invocation == attempt.invocation and item.index < attempt.index)
    gap = OperandGap(prior.anchor, prior.index, OperandEventKind.GAP, prior.process_id,
                     prior.thread_id, prior.invocation_id if scope == 'local' else None,
                     prior.frame_index, prior.hook_epoch, 'UNKNOWN_DELIVERY')
    changed = replace(scan, events=tuple(gap if item is prior else item for item in scan.events))
    routes = rebuild(case, changed)
    assert not any(route.callee == first.entry.invocation for route in routes.argument_routes)
    assert not any(route.callee == first.entry.invocation for route in routes.completion_routes)
    assert any(issue.kind in (OperandRouteIssueKind.CAPTURE_GAP, OperandRouteIssueKind.INSTRUCTION_WINDOW)
               for issue in routes.issues)


def test_sparse_capture_does_not_resolve_unknown_branch_predecessor(tmp_path, monkeypatch):
    helper = ('def choose(flag, left, right):\n'
              '    if flag:\n        selected = left\n'
              '    else:\n        selected = right\n'
              '    return selected\n')
    entry = 'from helper import choose\ndef run(flag, x, y):\n    return choose(flag, x, y)\n'
    case = capture(tmp_path, monkeypatch, helper=helper, entry=entry, shared=True,
                   invoke=lambda entry, left, right: entry.run(True, left, right))
    run, = named(case[0], 'run')
    query = query_operand_routes(case[0], case[4], run.entry.invocation)
    assert any(issue.kind is OperandRouteIssueKind.CONTROL_SELECTION_UNVERIFIED for issue in query.issues)
    assert not any(node.invocation == run.entry.invocation and node.formal_name in {'x', 'y'} for node in query.nodes)


def test_handler_and_normal_continuation_remain_live_after_initially_empty_pending_state(tmp_path, monkeypatch):
    helper = HELPER + ('def two(left, right):\n    return left\n'
                       'def one(left):\n    return left\n'
                       'def exercise(functions, value):\n'
                       '    for fn in functions:\n'
                       '        try:\n'
                       '            if fn is None:\n                raise TypeError\n'
                       '            fn(value, value)\n'
                       '        except TypeError:\n            continue\n'
                       '    return value\n')
    case = capture(tmp_path, monkeypatch, helper=helper,
                   warmup=lambda helper, entry: helper.exercise(
                       [None, helper.two, helper.one, helper.two], object()))
    model, scan, _, sources, _, _, _ = case
    exercise, = named(model, 'exercise')
    owned = [item for item in scan.instructions if item.invocation == exercise.entry.invocation]
    import dis
    from scar.trace.operand_bytecode import call_window_selection
    code = sources.objects[exercise.entry.code]
    instructions = list(dis.get_instructions(code))
    windows, expiry = call_window_selection(code, instructions)
    assert len(windows) == 1
    call_offset, = windows
    continuation = instructions[next(index for index, item in enumerate(instructions)
                                     if item.offset == call_offset) + 1].offset
    assert continuation in expiry
    assert sum(item.site.offset == continuation for item in owned) == 2
    targets = {entry.target for entry in dis.Bytecode(code).exception_entries}
    assert any(sum(item.site.offset == target for item in owned) >= 2 for target in targets)
    attempts = [item for item in scan.attempts if item.invocation == exercise.entry.invocation]
    assert len(attempts) == 3
    assert len([item for item in scan.handshakes if item.attempt_index in {attempt.index for attempt in attempts}]) == 2
    assert not named(model, 'one')  # Argument binding failed before its body.
    assert any(gap.invocation == exercise.entry.invocation and gap.reason == 'PROJECT_FUNCTION_CALL_DID_NOT_ENTER'
               for gap in scan.gaps)
    check_query(case)


def test_two_real_processes_keep_their_own_capture_rule_and_invocation_routes(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'helper.py').write_text(HELPER)
    entry = project / 'entry.py'
    entry.write_text(ENTRY)
    output = tmp_path / 'trace'
    product = Path(__file__).resolve().parents[2]
    environment = dict(os.environ, PYTHONPATH=str(product), PYTHONDONTWRITEBYTECODE='1')
    for name in tuple(environment):
        if name.startswith('SCAR_'):
            environment.pop(name)
    worker = '''import sys, threading
from entry import run
from scar.trace.call_edges import install as install_frames
from scar.trace.call_operands import install as install_operands
old, old_thread = sys.getprofile(), threading.getprofile()
recorder = install_frames(sys.argv[1], sys.argv[2])
observer = install_operands(recorder, capture=sys.argv[3])
try:
    left, right = object(), object()
    assert run(left, right) is left
finally:
    observer.stop()
    sys.setprofile(old)
    threading.setprofile(old_thread)
    recorder.close()
    observer.close()
'''
    for mode in ('instructions', 'windows'):
        process = subprocess.run([sys.executable, '-c', worker, str(output), str(project), mode],
                                 cwd=project, env=environment, capture_output=True, text=True, timeout=30)
        assert process.returncode == 0, process.stdout + process.stderr
    inventory = inventory_program(entry, project_root=project, calls_trace=output)
    scan = read_call_operands(output, project)
    assert len(scan.metadata) == 2
    assert {meta.rule for meta in scan.metadata} == {LOAD_OCCURRENCES_RULE, CALL_WINDOWS_RULE}
    model, sources = _link_call_model(output, project, inventory, scan.frame_budget,
        compilation_profile=CallCompilationProfile.RECORDED_FUTURE_FLAGS,
        frame_scan=scan.frame_scan, entries=scan.entries, exits=scan.exits,
        include_identity_routes=False, allow_v6=True)
    routes = build_operand_routes(call_model=model, operand_model=scan, inventory=inventory, sources=sources)
    assert len(named(model, 'run')) == 2
    for edge in named(model, 'run'):
        query = query_operand_routes(model, routes, edge.entry.invocation)
        assert {(node.invocation, node.formal_name) for node in query.endpoints} == {(edge.entry.invocation, 'x')}
        assert {node.invocation.process_id for node in query.nodes} == {edge.entry.invocation.process_id}


@pytest.mark.parametrize('caller_form', ['generator', 'coroutine', 'async_generator'])
def test_sparse_static_plan_rejects_suspended_caller_even_if_load_window_is_contiguous(caller_form):
    prefix, statement = {'generator': ('def', 'yield'), 'coroutine': ('async def', 'return'),
                         'async_generator': ('async def', 'yield')}[caller_form]
    text = f'{prefix} subject(fn, x, y):\n    {statement} fn(x, y)\n'
    top = compile(text, '<suspended-window>', 'exec', dont_inherit=True)
    code = next(value for value in top.co_consts if inspect.iscode(value))
    import dis
    from scar.ir.program.call_edges import CapturedSite
    from scar.trace.code_snapshot import describe_code, site
    instruction = next(item for item in dis.get_instructions(code) if item.opname == 'CALL')
    raw = site(code, instruction.offset)
    captured_site = CapturedSite(raw['code'], raw['offset'], raw['opname'], tuple(raw['position']))
    node = next(node for node in ast.walk(ast.parse(text)) if isinstance(node, ast.Call))
    # The old profile keeps its old parser. Only the new profile adds this
    # conservative suspension boundary; this unit does not execute a generator.
    assert _instruction_plan(code, captured_site, node, LOAD_OCCURRENCES_RULE)
    with pytest.raises(_Boundary) as failure:
        _instruction_plan(code, captured_site, node, CALL_WINDOWS_RULE)
    assert failure.value.kind is OperandRouteIssueKind.DISPATCH_BOUNDARY
