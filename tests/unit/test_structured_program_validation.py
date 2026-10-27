"""Typed source interfaces must not lose control or lifetime dependencies."""
from dataclasses import replace

import pytest

from scar.analysis.program_lowering import SourceProgram, lower_source
from scar.analysis.structured_lowering import require_valid_structured_body
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.model import ExitKind, LocalBindingValue, ReferenceValue
from scar.ir.program.structured import LoopKind, PythonProtocolKind
from tests.fixtures.structured_program_oracle import run_core, run_python


def lower(tmp_path, text):
    path = tmp_path / "source.py"
    path.write_text(text)
    result = lower_source(path, "f", profile=BodyLoweringProfile.STRUCTURED_BODY)
    assert result.graph is not None, result.metadata.gaps
    return result


def validate(program, model):
    require_valid_structured_body(model, program.graph, program.interface, program.metadata,
                                  semantic=program.semantic, control=program.control)


def test_source_v3_roundtrip_preserves_all_typed_ports(tmp_path):
    program = lower(tmp_path, "def f(items, call):\n    result = None\n    for item in items:\n        result = call(item, item)\n    return result\n")
    original = program.to_dict()
    rebuilt = SourceProgram.from_dict(original)
    assert rebuilt.to_dict() == original
    assert rebuilt.profile is BodyLoweringProfile.STRUCTURED_BODY
    assert any(isinstance(value, LocalBindingValue) for value in rebuilt.graph.values)
    assert not rebuilt.summary()["transformation_authorized"]


@pytest.mark.parametrize("mutant", ["drop_protocols", "drop_loops", "wrong_kind", "swap_body_exit",
                                   "drop_bindings", "drop_backedges", "drop_breaks", "drop_continues"])
def test_incomplete_or_relabelled_loop_interfaces_are_rejected(tmp_path, mutant):
    program = lower(tmp_path, "def f(items, skip, stop):\n    result = None\n    for item in items:\n        if skip(item):\n            continue\n        if stop(item):\n            break\n        result = item\n    return result\n")
    model = program.structured
    loop, = model.loops
    if mutant == "drop_protocols":
        altered = replace(model, protocols=())
    elif mutant == "drop_loops":
        altered = replace(model, loops=())
    elif mutant == "wrong_kind":
        altered = replace(model, loops=(replace(loop, kind=LoopKind.WHILE),))
    elif mutant == "swap_body_exit":
        altered = replace(model, loops=(replace(loop, body_entry=loop.natural_exit, natural_exit=loop.body_entry),))
    elif mutant == "drop_bindings":
        altered = replace(model, loops=(replace(loop, bindings=()),))
    elif mutant == "drop_backedges":
        altered = replace(model, loops=(replace(loop, backedges=(), continues=()),))
    elif mutant == "drop_breaks":
        altered = replace(model, loops=(replace(loop, breaks=()),))
    else:
        altered = replace(model, loops=(replace(loop, continues=()),))
    with pytest.raises(ValueError):
        validate(program, altered)


@pytest.mark.parametrize("expression", ["local", "caller(local, must_not_run())"])
def test_unbound_local_stops_before_later_argument_and_keeps_actual_error(tmp_path, expression):
    calls = []
    def must_not_run():
        calls.append("incorrectly executed")
    def caller(*args):
        calls.append("incorrect caller")
    text = "def f(caller, must_not_run):\n    return " + expression + "\n    local = 1\n"
    program = lower(tmp_path, text)
    expected = run_python(text, (caller, must_not_run), observe=lambda: calls)
    actual = run_core(program, (caller, must_not_run), observe=lambda: calls)
    assert expected.status == actual.status == "RAISE"
    assert type(expected.exception) is type(actual.exception) is UnboundLocalError
    assert expected.exception.args == actual.exception.args
    assert calls == []


def test_iterator_holds_and_path_specific_releases_are_actual_reference_uses(tmp_path):
    program = lower(tmp_path, "def f(make, stop, observe):\n    for item in make():\n        if stop(item):\n            break\n        return observe()\n    return observe()\n")
    operations = {operation.id: operation for operation in program.graph.operations}
    values = {value.id: value for value in program.graph.values}
    protocols = program.structured.protocols
    advance, = [protocol for protocol in protocols if protocol.kind is PythonProtocolKind.ADVANCE_ITERATOR]
    iterator, = [use.value for use in operations[advance.operation].uses if isinstance(values[use.value], ReferenceValue)]
    holds = [protocol for protocol in protocols if protocol.kind is PythonProtocolKind.FRAME_HOLD_TEMPORARY]
    releases = [protocol for protocol in protocols if protocol.kind is PythonProtocolKind.FRAME_RELEASE_TEMPORARY]
    assert len(holds) == 1 and len(releases) == 2
    assert all(any(use.value == iterator for use in operations[protocol.operation].uses) for protocol in holds + releases)
    assert any(protocol.kind is PythonProtocolKind.FRAME_EXIT
               and any(use.value == iterator for use in operations[protocol.operation].uses)
               for protocol in protocols)
    # Reference retention/release dependencies are represented. Physical free,
    # traceback ownership and exact finalizer timing are not thereby proved.
    assert program.structured.frame_rules.release.value == "NOT_GUARANTEED"


def test_stop_iteration_match_reads_exception_type_state(tmp_path):
    program = lower(tmp_path, "def f(items):\n    for item in items:\n        pass\n    return None\n")
    match, = [protocol for protocol in program.structured.protocols if protocol.kind is PythonProtocolKind.MATCH_STOP_ITERATION]
    operation = next(operation for operation in program.graph.operations if operation.id == match.operation)
    assert len(operation.accesses) == 1
    assert operation.accesses[0].mode.value == "READ"
    assert any(signature.kind is ExitKind.RAISE for candidate in program.graph.operations for signature in candidate.completions)
