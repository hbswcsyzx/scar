"""Replay source semantics against snapshots, scopes and Python evaluation order."""
from copy import deepcopy
from dataclasses import replace

import pytest

from scar.analysis.source_semantics_v2 import extract_source_semantics, validate_source_semantics
from scar.ir.frontend_v2 import build_semantic
from scar.ir.semantics_v2 import BindingStatus, Opcode


def capture(tmp_path, text):
    path = tmp_path / "program.py"
    path.write_text(text)
    semantic = build_semantic(path).graph
    return path, semantic, extract_source_semantics(semantic)


def uses(model, semantic, name, line):
    return [item for item in model.uses.values()
            if semantic.slots[item.slot].name == name and item.source.start_line == line]


def operation(model, opcode, line):
    matches = [item for item in model.operations.values()
               if item.opcode is opcode and item.source.start_line == line]
    assert len(matches) == 1
    return matches[0]


def test_extract_and_replay_never_execute_imports_top_level_or_function_bodies(tmp_path):
    marker = tmp_path / "executed"
    package = tmp_path / "trap_package.py"
    package.write_text(f"open({str(marker)!r}, 'w').write('imported')\nTOKEN = 7\n")
    path = tmp_path / "program.py"
    text = ("from trap_package import TOKEN\n"
            f"open({str(marker)!r}, 'w').write('top-level')\n"
            "def dangerous():\n"
            f"    open({str(marker)!r}, 'w').write('called')\n"
            "    return 4 + 6\n"
            "result = dangerous()\n"
            "raise RuntimeError('target must never run')\n")
    path.write_text(text)
    semantic = build_semantic(path, project_root=tmp_path).graph
    original = {item: item.read_bytes() for item in (path, package)}
    model = extract_source_semantics(semantic)
    report = validate_source_semantics(model, semantic)
    assert report["valid"], report["errors"]
    assert not marker.exists()
    assert all(item.read_bytes() == content for item, content in original.items())


def test_snapshot_mismatch_cannot_be_repaired_by_syntactically_valid_source(tmp_path):
    path, semantic, _ = capture(tmp_path, "value = 3 + 4\n")
    with pytest.raises(ValueError):
        extract_source_semantics(semantic, sources={str(path): "value = 30 + 40\n"})
    path.write_text("value = 30 + 40\n")
    with pytest.raises(ValueError):
        extract_source_semantics(semantic)


def test_explicit_matching_snapshot_is_distinct_from_current_filesystem_validation(tmp_path):
    text = "value = 3 + 4\n"
    path, semantic, model = capture(tmp_path, text)
    path.write_text("value = 8 + 9\n")
    report = validate_source_semantics(model, semantic)
    assert report["valid"] is False and report["errors"]
    historical = extract_source_semantics(semantic, sources={str(path): text})
    historical_report = validate_source_semantics(historical, semantic, sources={str(path): text})
    assert historical_report["valid"], historical_report["errors"]


@pytest.mark.parametrize("forgery", ["opcode", "operand_order", "operand_duplicate"])
def test_replay_rejects_validly_typed_forged_expression_semantics(tmp_path, forgery):
    _, semantic, model = capture(tmp_path, "result = 7 - 2\n")
    original = operation(model, Opcode.SUB, 1)
    if forgery == "opcode":
        forged = replace(original, opcode=Opcode.ADD)
    elif forgery == "operand_order":
        first, second = original.operands
        forged = replace(original, operands=(replace(first, value=second.value), replace(second, value=first.value)))
    else:
        first, second = original.operands
        forged = replace(original, operands=(first, replace(second, value=first.value)))
    tampered = deepcopy(model)
    tampered.operations[original.operation] = forged
    report = validate_source_semantics(tampered, semantic)
    assert report["valid"] is False and report["errors"]


def test_reaching_definition_is_per_use_and_not_a_single_binding_per_slot(tmp_path):
    _, semantic, model = capture(tmp_path, "value = 1\nfirst = value\nvalue = 2\nsecond = value\n")
    first, second = uses(model, semantic, "value", 2), uses(model, semantic, "value", 4)
    assert len(first) == len(second) == 1
    assert first[0].status is second[0].status is BindingStatus.EXACT
    assert len(first[0].reaching) == len(second[0].reaching) == 1
    assert first[0].reaching != second[0].reaching
    earlier = model.bindings[first[0].reaching[0]]
    later = model.bindings[second[0].reaching[0]]
    assert earlier.slot == later.slot
    assert earlier.value != later.value
    assert earlier.source.start_line == 1 and later.source.start_line == 3


@pytest.mark.parametrize("text, line", [
    ("value = 3\nif flag:\n    value = 4\nresult = value + 1\n", 4),
    ("value = 3\nfor item in iterable:\n    value = item\nresult = value + 1\n", 4),
    ("value = 3\nwhile flag:\n    value = 4\nresult = value + 1\n", 4),
    ("value = 3\ntry:\n    risky()\nexcept Exception:\n    value = 4\nresult = value + 1\n", 6),
])
def test_control_merge_or_loop_does_not_preserve_a_stale_straight_line_binding(tmp_path, text, line):
    _, semantic, model = capture(tmp_path, text)
    references = uses(model, semantic, "value", line)
    assert references
    assert all(item.status is not BindingStatus.EXACT for item in references)


def test_opaque_call_kills_prior_binding_but_preserves_its_literal_argument_expression(tmp_path):
    from scar.analysis.constants_v2 import ConstantStatus, evaluate_constants

    _, semantic, model = capture(tmp_path, "value = 7\nopaque(2 + 3)\nresult = value + 1\n")
    references = uses(model, semantic, "value", 3)
    assert references and all(item.status is not BindingStatus.EXACT for item in references)
    argument = operation(model, Opcode.ADD, 2)
    report = evaluate_constants(model, targets=(argument.result,))
    assert report.facts[argument.result].status is ConstantStatus.CONSTANT
    assert report.facts[argument.result].literal.to_python() == 5


@pytest.mark.parametrize("text, line", [
    ("value = 3\ndef read():\n    return value + 1\nvalue = 9\n", 3),
    ("value = 3\ndef read():\n    global value\n    return value + 1\nvalue = 9\n", 4),
    ("value = 3\ndef read():\n    result = value + 1\n    value = 9\n    return result\n", 3),
    ("def outer():\n    value = 3\n    def inner():\n        return value + 1\n    value = 9\n    return inner\n", 4),
])
def test_deferred_function_or_closure_read_cannot_capture_declaration_time_constant(tmp_path, text, line):
    _, semantic, model = capture(tmp_path, text)
    references = uses(model, semantic, "value", line)
    assert references and all(item.status is not BindingStatus.EXACT for item in references)


def test_utf8_source_columns_refer_to_bytes_and_replay_the_exact_expression(tmp_path):
    text = '名称 = "汉字"; result = 4 + 6\n'
    _, semantic, model = capture(tmp_path, text)
    expression = operation(model, Opcode.ADD, 1)
    reference = expression.source
    fragment = text.splitlines()[0].encode("utf-8")[reference.start_column:reference.end_column].decode("utf-8")
    assert fragment == "4 + 6"
    report = validate_source_semantics(model, semantic)
    assert report["valid"], report["errors"]


@pytest.mark.parametrize("name", ["value", "tracked"])
def test_releasing_unknown_old_value_may_finalize_and_rebind_even_assignment_destination(tmp_path, name):
    text = f"tracked = opaque_factory()\nvalue = 7\ntracked = 0\nresult = {name}\n"
    _, semantic, model = capture(tmp_path, text)
    references = uses(model, semantic, name, 4)
    assert references and all(item.status is not BindingStatus.EXACT for item in references)


def test_container_with_unknown_elements_is_not_proved_free_of_finalizer_effects(tmp_path):
    text = "tracked = [opaque_factory()]\nvalue = 7\ntracked = []\nresult = value\n"
    _, semantic, model = capture(tmp_path, text)
    references = uses(model, semantic, "value", 4)
    assert references and all(item.status is not BindingStatus.EXACT for item in references)


def test_dictionary_unpack_barrier_precedes_later_entry_evaluation(tmp_path):
    _, semantic, model = capture(tmp_path, "value = 7\nresult = {**unknown_mapping, 'number': value}\n")
    references = uses(model, semantic, "value", 2)
    assert references and all(item.status is not BindingStatus.EXACT for item in references)


def test_opaque_code_can_install_an_unseen_global_with_a_finalizer(tmp_path):
    # opaque() may set globals()['tracked'] to an object whose destructor
    # changes value. The first source write to tracked need not be its birth.
    _, semantic, model = capture(tmp_path, "opaque()\nvalue = 7\ntracked = 0\nresult = value\n")
    references = uses(model, semantic, "value", 4)
    assert references and all(item.status is not BindingStatus.EXACT for item in references)


def test_keyword_unpack_executes_before_later_keyword_value_expressions(tmp_path):
    # DICT_MERGE can call mapping.keys()/__getitem__ before loading tail.
    _, semantic, model = capture(tmp_path, "value = 7\nopaque(**mapping, tail=value)\n")
    references = uses(model, semantic, "value", 2)
    assert references and all(item.status is not BindingStatus.EXACT for item in references)
