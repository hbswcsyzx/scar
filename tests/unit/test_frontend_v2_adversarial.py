"""Independent semantic-boundary checks for the nonexecuting Python frontend."""
from __future__ import annotations

from pathlib import Path

import pytest

from scar.ir.frontend_v2 import build_semantic
from scar.ir.v2 import OperationKind, SemanticRelation


def model(tmp_path, source):
    path = tmp_path / "example.py"
    path.write_text(source)
    return build_semantic(path), path


def line(source, text):
    return next(index for index, value in enumerate(source.splitlines(), 1) if text in value)


def calls_on(result, source_line):
    return [definition for definition in result.graph.definitions.values()
            if definition.source_start == source_line
            and definition.metadata.get("ast_type") == "Call"]


def call_targets(result, source_line):
    calls = {definition.id for definition in calls_on(result, source_line)}
    return {edge.target.id for edge in result.graph.edges.values()
            if edge.relation is SemanticRelation.CALLS and edge.source.id in calls}


def read_owners(result, name, source_line):
    reads = {definition.id for definition in result.graph.definitions.values()
             if definition.label == "read " + name and definition.source_start == source_line}
    return {result.graph.slots[edge.target.id].owner for edge in result.graph.edges.values()
            if edge.relation is SemanticRelation.READS_SLOT and edge.source.id in reads
            and result.graph.slots[edge.target.id].name == name}


def function(result, name):
    return next(definition for definition in result.graph.definitions.values()
                if definition.metadata.get("callable_name") == name)


def test_frontend_does_not_execute_imports_or_top_level_effects(tmp_path):
    sentinel = tmp_path / "executed.txt"
    source = ("from pathlib import Path\n"
              f"Path({str(sentinel)!r}).write_text('executed')\n"
              "raise RuntimeError('target source must never execute')\n")
    result, _ = model(tmp_path, source)
    assert not sentinel.exists()
    assert result.graph.assert_valid()["valid"]
    assert result.coverage["target_executed"] is False
    assert result.coverage["source_atoms"] == result.coverage["owned_source_atoms"]
    assert result.coverage["unowned_source_atoms"] == 0


@pytest.mark.parametrize("source,call_line", [
    ("def fn():\n    return 1\ndef use(fn):\n    return fn()\n", 4),
    ("def fn():\n    return 1\ndef use():\n    result = fn()\n    fn = unknown\n    return result\n", 4),
    ("def fn():\n    return 1\nfn = unknown\nresult = fn()\n", 4),
    ("def fn():\n    return 1\ndel fn\nresult = fn()\n", 4),
])
def test_shadowed_or_deleted_binding_cannot_call_stale_global(tmp_path, source, call_line):
    result, _ = model(tmp_path, source)
    assert calls_on(result, call_line)
    assert not call_targets(result, call_line)


def test_module_redefinition_resolves_each_call_at_its_binding_point(tmp_path):
    source = ("def fn():\n    return 1\nfirst = fn()\n"
              "def fn():\n    return 2\nsecond = fn()\n")
    result, _ = model(tmp_path, source)
    first = call_targets(result, 3)
    second = call_targets(result, 6)
    assert len(first) == len(second) == 1
    assert first.isdisjoint(second)
    assert {result.graph.definitions[item].source_start for item in first} == {1}
    assert {result.graph.definitions[item].source_start for item in second} == {4}


def test_defaults_read_enclosing_scope_and_body_reads_parameter(tmp_path):
    source = "value = 7\ndef use(value=value):\n    return value\n"
    result, _ = model(tmp_path, source)
    initializer = next(iter(result.graph.modules.values())).initializer
    body = function(result, "use").id
    assert read_owners(result, "value", 2) == {initializer}
    assert read_owners(result, "value", 3) == {body}


def test_global_nonlocal_and_closure_reads_keep_lexical_owners(tmp_path):
    source = ("counter = 0\ndef outer():\n    value = 1\n"
              "    def inner():\n        nonlocal value\n        value += 1\n"
              "        return value\n    def global_reader():\n        global counter\n"
              "        return counter\n    def closure():\n        return value\n"
              "    return inner, global_reader, closure\n")
    result, _ = model(tmp_path, source)
    initializer = next(iter(result.graph.modules.values())).initializer
    outer = function(result, "outer").id
    assert read_owners(result, "value", line(source, "return value")) == {outer}
    assert read_owners(result, "counter", line(source, "return counter")) == {initializer}
    assert read_owners(result, "value", 12) == {outer}


def test_method_unqualified_name_does_not_capture_class_namespace(tmp_path):
    source = "value = 1\nclass Example:\n    value = 2\n    def read(self):\n        return value\n"
    result, _ = model(tmp_path, source)
    initializer = next(iter(result.graph.modules.values())).initializer
    assert read_owners(result, "value", 5) == {initializer}


def test_relative_import_alias_and_reexport_preserve_value_path(tmp_path):
    package = tmp_path / "samplepkg"
    package.mkdir()
    (package / "values.py").write_text("TOKEN = (3, 5)\n")
    (package / "__init__.py").write_text("from .values import TOKEN as EXPORTED\n")
    consumer = tmp_path / "consumer.py"
    consumer.write_text("from samplepkg import EXPORTED as local\nresult = local[0]\n")
    result = build_semantic(consumer, project_root=tmp_path)
    constant = next(definition for definition in result.graph.definitions.values()
                    if definition.kind is OperationKind.CONSTANT
                    and Path(definition.source_file).name == "values.py")
    index = next(definition for definition in result.graph.definitions.values()
                 if definition.kind is OperationKind.INDEX)
    assert result.value_path(constant.id, index.id)
    imports = [edge for edge in result.graph.edges.values()
               if edge.relation is SemanticRelation.IMPORTS]
    imported_names = {result.graph.modules[edge.target.id].name for edge in imports}
    assert {"samplepkg.values", "samplepkg"} <= imported_names


def test_try_branch_target_is_not_reported_as_one_unconditional_binding(tmp_path):
    source = ("def left():\n    return 1\ndef right():\n    return 2\n"
              "try:\n    chosen = left\n    risky()\n"
              "except Exception:\n    chosen = right\nresult = chosen()\n")
    result, _ = model(tmp_path, source)
    calls = calls_on(result, 10)
    targets = call_targets(result, 10)
    possible = {function(result, "left").id, function(result, "right").id}
    # A closed candidate set may contain both paths.  A frontend that cannot
    # merge path-sensitive bindings must leave resolution explicitly opaque.
    assert targets == possible or (not targets and all(
        operation.kind is OperationKind.OPAQUE for operation in calls))


def test_loop_and_exception_regions_do_not_claim_effect_free_execution(tmp_path):
    source = ("for item in items:\n    try:\n        consume(item)\n"
              "    except Exception:\n        recover()\n    finally:\n        cleanup()\n")
    result, _ = model(tmp_path, source)
    kinds = {control.kind for control in result.graph.controls.values()}
    assert {"loop_body", "try_body", "except_0", "finally"} <= kinds
    for source_line in (3, 5, 7):
        operation = calls_on(result, source_line)[0]
        assert operation.control_region is not None
        assert operation.kind is OperationKind.OPAQUE
        assert not result.graph.effects[operation.effect_summary].is_complete


def test_comprehension_target_does_not_replace_enclosing_binding(tmp_path):
    source = "value = 9\nitems = [value for value in source]\nresult = value\n"
    result, _ = model(tmp_path, source)
    initializer = next(iter(result.graph.modules.values())).initializer
    inner = read_owners(result, "value", 2)
    assert inner and initializer not in inner
    assert read_owners(result, "value", 3) == {initializer}
