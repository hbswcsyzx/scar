from copy import deepcopy
from dataclasses import replace
import json
from types import CellType, CodeType, FunctionType

import pytest

from scar.analysis.identity_source_v2 import (
    IdentityFunctionSource, prepare_identity_source, validate_identity_source,
)
from scar.analysis.source_semantics_v2 import extract_source_semantics
from scar.ir.control_flow_v2 import ControlFlowBudget
from scar.ir.frontend_v2 import build_semantic
from scar.ir.semantics_v2 import Opcode


def _function_from_source(source, path, qualname):
    module_code = compile(source, str(path), "exec", dont_inherit=True)
    pending = [module_code]
    while pending:
        code = pending.pop()
        if isinstance(code, CodeType) and code.co_qualname == qualname:
            closure = tuple(CellType(None) for _ in code.co_freevars)
            return FunctionType(code, {}, closure=closure or None)
        if isinstance(code, CodeType):
            pending.extend(item for item in code.co_consts if isinstance(item, CodeType))
    raise AssertionError("source did not compile the requested function code")


def capture(tmp_path, source, *, qualname="compare"):
    path = tmp_path / "program.py"
    path.write_text(source)
    semantic = build_semantic(path).graph
    source_semantics = extract_source_semantics(semantic)
    function = _function_from_source(source, path, qualname)
    return path, semantic, source_semantics, function


def test_returned_identity_source_binds_ordered_reads_primitive_and_return(tmp_path):
    path, semantic, source_semantics, function = capture(
        tmp_path, "def compare(left, right):\n    return left is right\n")
    model = prepare_identity_source(semantic, source_semantics, function)
    assert model.opcode is Opcode.IS
    assert model.primitive.coverage.value == "OPERATOR_ONLY"
    assert model.primitive.result == model.return_use.returned_value == model.result
    assert model.return_use.identity_output_slot == model.output_slot
    assert model.return_use.scope == model.function_definition
    assert model.function_source.path == str(path)
    assert [(item.index, item.role, item.parameter_name) for item in model.operands] == [
        (0, "left", "left"), (1, "right", "right")]
    assert all(item.read_operation != model.identity_operation for item in model.operands)
    assert [item.opname for item in model.instructions] == [
        "RESUME", *(["LOAD_FAST", "LOAD_FAST"] if model.instructions[1].opname == "LOAD_FAST"
                     else ["LOAD_FAST_BORROW_LOAD_FAST_BORROW"]), "IS_OP", "RETURN_VALUE"]
    assert model.validate()["valid"]


def test_repeated_parameter_preserves_two_occurrences_and_load_subindices(tmp_path):
    _, semantic, source_semantics, function = capture(
        tmp_path, "def compare(value):\n    return value is value\n")
    model = prepare_identity_source(semantic, source_semantics, function)
    left, right = model.operands
    assert left.slot == right.slot
    assert left.read_output_slot != right.read_output_slot
    assert left.value != right.value
    assert left.read_operation != right.read_operation
    assert left.binding_use != right.binding_use
    if left.load_offset == right.load_offset:
        assert (left.load_subindex, right.load_subindex) == (0, 1)
    else:
        assert left.load_offset < right.load_offset
        assert (left.load_subindex, right.load_subindex) == (0, 0)


def test_is_not_and_keyword_only_required_parameters_are_supported(tmp_path):
    _, semantic, source_semantics, function = capture(
        tmp_path, "def compare(*, left, right):\n    return left is not right\n")
    model = prepare_identity_source(semantic, source_semantics, function)
    assert model.opcode is Opcode.IS_NOT
    assert [item.parameter_name for item in model.operands] == ["left", "right"]


@pytest.mark.parametrize("source", [
    "def compare(left, right):\n    left is right\n    return left is right\n",
    "def compare(left, right=True):\n    return left is right\n",
    "@decorator\ndef compare(left, right):\n    return left is right\n",
    "def compare(left: object, right):\n    return left is right\n",
    "def compare(left, *right):\n    return left is right[0]\n",
    "def compare(left, right):\n    value = left\n    return value is right\n",
    "def compare(left, right):\n    return make(left) is right\n",
    "def compare(left, right):\n    if left:\n        return left is right\n    return False\n",
    "def compare(left, right):\n    return left == right\n",
    "def compare(left, right):\n    return left is right is left\n",
])
def test_rejects_source_outside_exact_single_return_subset(tmp_path, source):
    _, semantic, source_semantics, function = capture(tmp_path, source)
    with pytest.raises(ValueError):
        prepare_identity_source(semantic, source_semantics, function)


def test_rejects_closure_operand_even_when_source_shape_is_identity_return(tmp_path):
    source = ("def outer(captured):\n"
              "    def compare(left, right):\n"
              "        return captured is right\n"
              "    return compare\n")
    _, semantic, source_semantics, function = capture(
        tmp_path, source, qualname="outer.<locals>.compare")
    with pytest.raises(ValueError, match="closure|parameter"):
        prepare_identity_source(semantic, source_semantics, function)


def test_source_analysis_never_executes_module_or_imports(tmp_path):
    marker = tmp_path / "must-not-exist"
    source = (f"open({str(marker)!r}, 'w').write('executed')\n"
              "def compare(left, right):\n"
              "    return left is right\n"
              "raise RuntimeError('must not run')\n")
    _, semantic, source_semantics, function = capture(tmp_path, source)
    prepare_identity_source(semantic, source_semantics, function)
    assert not marker.exists()


def test_lazy_function_annotation_resolver_is_rejected_without_execution(tmp_path):
    marker = tmp_path / "annotation-resolver-ran"
    _, semantic, source_semantics, function = capture(
        tmp_path, "def compare(left, right):\n    return left is right\n")

    def resolver(format):
        marker.write_text(str(format))
        return {}

    function.__annotate__ = resolver
    with pytest.raises(ValueError, match="annotation resolver"):
        prepare_identity_source(semantic, source_semantics, function)
    assert not marker.exists()


def test_source_edit_after_preparation_invalidates_witness(tmp_path):
    path, semantic, source_semantics, function = capture(
        tmp_path, "def compare(left, right):\n    return left is right\n")
    model = prepare_identity_source(semantic, source_semantics, function)
    path.write_text("# source changed\ndef compare(left, right):\n    return left is right\n")
    result = validate_identity_source(model, semantic, source_semantics, function)
    assert not result["valid"]
    assert "fingerprint" in result["errors"][0]


def test_code_object_identity_is_rechecked_before_capture(tmp_path):
    _, semantic, source_semantics, function = capture(
        tmp_path, "def compare(left, right):\n    return left is right\n")
    original = function.__code__
    model = prepare_identity_source(semantic, source_semantics, function)
    try:
        function.__code__ = original.replace()
        result = validate_identity_source(model, semantic, source_semantics, function)
        assert not result["valid"]
        assert "object changed" in result["errors"][0]
    finally:
        function.__code__ = original


def test_strict_json_round_trip_replays_and_rejects_forged_occurrence(tmp_path):
    _, semantic, source_semantics, function = capture(
        tmp_path, "def compare(left, right):\n    return left is right\n")
    model = prepare_identity_source(semantic, source_semantics, function)
    payload = model.to_json()
    restored = IdentityFunctionSource.from_json(
        payload, semantic=semantic, source_semantics=source_semantics, function=function)
    assert restored.to_dict() == model.to_dict()
    forged = json.loads(payload)
    forged["operands"][0]["index"] = 1
    with pytest.raises((TypeError, ValueError)):
        IdentityFunctionSource.from_dict(
            forged, semantic=semantic, source_semantics=source_semantics, function=function)
    extra = json.loads(payload)
    extra["unreviewed"] = True
    with pytest.raises((TypeError, ValueError)):
        IdentityFunctionSource.from_dict(
            extra, semantic=semantic, source_semantics=source_semantics, function=function)


def test_source_budget_is_a_caller_ceiling(tmp_path):
    _, semantic, source_semantics, function = capture(
        tmp_path, "def compare(left, right):\n    return left is right\n")
    with pytest.raises(ValueError, match="budget"):
        prepare_identity_source(semantic, source_semantics, function,
                               budget=ControlFlowBudget(max_source_bytes=1))


def test_tampered_source_semantics_cannot_forge_operand_order(tmp_path):
    _, semantic, source_semantics, function = capture(
        tmp_path, "def compare(left, right):\n    return left is right\n")
    forged = deepcopy(source_semantics)
    identity = next(item for item in forged.operations.values() if item.opcode is Opcode.IS)
    forged.operations[identity.operation] = replace(identity, operands=tuple(reversed(identity.operands)))
    with pytest.raises(ValueError, match="source replay failed"):
        prepare_identity_source(semantic, forged, function)
