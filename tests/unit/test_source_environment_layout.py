"""Actual compiler layout, recovered from source without target evaluation."""
import ast
import builtins
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from textwrap import dedent
from types import CodeType

import pytest

from scar.analysis.program_context_store import PreparedContextStore
from scar.analysis.program_lowering import prepare_source
from scar.analysis.source_environment_layout import compiler_environment_layout
import scar.analysis.source_environment_layout as layout_module


def prepared(tmp_path, source):
    path = tmp_path / "example.py"
    path.write_text(dedent(source).lstrip(), encoding="utf-8")
    return prepare_source(path, project_root=tmp_path)


def selection(context, name, *, line=None):
    candidates = [node for node in ast.walk(context.tree)
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.name == name and (line is None or node.lineno == line)]
    assert len(candidates) == 1
    node = candidates[0]
    definitions = [definition for definition in context.semantic.definitions.values()
                   if definition.label == name and definition.metadata.get("phase") == "call_time"
                   and any(context.semantic.source_atoms[atom].reference.start_line == node.lineno
                           for atom in definition.source_atoms)]
    assert len(definitions) == 1
    return node, definitions[0]


def layout(context, name, *, line=None):
    return compiler_environment_layout(context, *selection(context, name, line=line))


def test_order_is_compiler_order_not_alphabetical_and_no_target_evaluation(tmp_path):
    context = prepared(tmp_path, """
        must_never_execute_source()
        def outer(z, a):
            middle = None
            def inner():
                return z, a, middle
            return inner
    """)
    outer = layout(context, "outer")
    inner = layout(context, "inner")
    assert outer.cellvars == ("z", "a", "middle")
    assert outer.freevars == ()
    assert inner.freevars == ("a", "middle", "z")
    assert inner.cellvars == ()
    assert inner.qualified_name == "outer.<locals>.inner"
    with pytest.raises(FrozenInstanceError):
        inner.freevars = ()


def test_decorators_defaults_and_nested_classes_are_compiled_not_run(tmp_path):
    context = prepared(tmp_path, """
        @missing_decorator(unavailable())
        def outer(a=undefined_default()):
            class Nested:
                @another_missing_decorator
                def method(self):
                    def inner():
                        return a
                    return inner
            return Nested
    """)
    assert layout(context, "outer").first_line == 1
    method = layout(context, "method")
    assert method.qualified_name == "outer.<locals>.Nested.method"
    assert method.first_line == 4
    assert method.freevars == ("a",)
    assert layout(context, "inner").qualified_name == "outer.<locals>.Nested.method.<locals>.inner"


def test_nonlocal_and_implicit_class_cell_are_not_guessed_from_name_reads(tmp_path):
    context = prepared(tmp_path, """
        class Child:
            def method(self):
                return super()
        def outer(value):
            def inner(replacement):
                nonlocal value
                value = replacement
                return value
            return inner
    """)
    assert layout(context, "method").freevars == ("__class__",)
    assert layout(context, "inner").freevars == ("value",)
    assert layout(context, "outer").cellvars == ("value",)


def test_private_names_preserve_compiler_mangling_instead_of_source_spelling(tmp_path):
    context = prepared(tmp_path, """
        class Box:
            def outer(self, __state):
                def inner():
                    return __state
                return inner
    """)
    assert layout(context, "outer").cellvars == ("_Box__state",)
    assert layout(context, "inner").freevars == ("_Box__state",)


def test_repeated_qualnames_require_exact_definition_line(tmp_path):
    context = prepared(tmp_path, """
        def outer(first, second):
            def same():
                return first
            def same():
                return second
            return same
    """)
    assert layout(context, "same", line=2).freevars == ("first",)
    assert layout(context, "same", line=4).freevars == ("second",)


def test_cache_contains_only_primitive_projections_and_compiles_file_once(tmp_path, monkeypatch):
    context = prepared(tmp_path, "def first(a):\n    return a\ndef second(b):\n    return b\n")
    calls = []
    def observe(*args, **kwargs):
        calls.append((args, kwargs))
        return builtins.compile(*args, **kwargs)
    monkeypatch.setattr(layout_module, "compile", observe, raising=False)
    layout(context, "first")
    layout(context, "second")
    assert len(calls) == 1
    assert calls[0][1] == {"flags": 0, "dont_inherit": True, "optimize": 0}
    cache = getattr(context, layout_module._CACHE_ATTRIBUTE)
    def primitive(value):
        assert type(value) in (tuple, str, int, bool, type(None))
        assert type(value) is not CodeType
        if type(value) is tuple:
            for item in value:
                primitive(item)
    primitive(cache)


def test_private_context_store_reconstructs_layout_from_unchanged_snapshot(tmp_path):
    context = prepared(tmp_path, "def outer(x):\n    def inner():\n        return x\n    return inner\n")
    expected = layout(context, "inner")
    with PreparedContextStore() as store:
        store.put(context)
        recovered = store.get(context.path)
        assert layout(recovered, "inner") == expected


def test_changed_text_wrong_definition_and_foreign_ast_fail_explicitly(tmp_path):
    context = prepared(tmp_path, "def first(a):\n    return a\ndef second(b):\n    return b\n")
    node, definition = selection(context, "first")
    _, other = selection(context, "second")
    with pytest.raises(ValueError, match="source span"):
        compiler_environment_layout(context, node, other)
    with pytest.raises(ValueError, match="prepared AST"):
        compiler_environment_layout(context, deepcopy(node), definition)
    changed = replace(context, text=context.text + "# changed\n")
    with pytest.raises(ValueError, match="snapshot"):
        compiler_environment_layout(changed, node, definition)


def test_snapshot_python_mismatch_rejects_instead_of_inventing_layout(tmp_path):
    context = prepared(tmp_path, "def f():\n    return None\n")
    snapshot = context.semantics.sources[str(context.path)]
    context.semantics.sources[str(context.path)] = replace(snapshot, python_version="0.0")
    with pytest.raises(ValueError, match="Python version"):
        layout(context, "f")
