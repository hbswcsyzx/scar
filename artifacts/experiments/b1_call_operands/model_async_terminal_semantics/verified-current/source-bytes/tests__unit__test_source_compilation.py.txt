from __future__ import annotations

import ast
from dataclasses import replace
import hashlib
from pathlib import Path
import platform
import sys

import pytest

from scar.analysis.source_compilation import MAX_SOURCE_BYTES, source_compilation
from scar.ir.frontend_v2 import source_reference
from scar.ir.program.ids import OperationID
from scar.ir.program.source import OperationSource, SourceRole
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.ids import SourceAtomID


def _snapshot(text, path="/supplied/project/module.py", **changes):
    snapshot = SourceSnapshot(path, "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
                              python_version=f"{sys.version_info.major}.{sys.version_info.minor}")
    return replace(snapshot, **changes)


def _codes(view):
    return {gap["code"] for gap in view["gaps"]}


def _no_execution(view):
    assert view["target_executed"] is False
    assert view["source_runtime_verified"] is False
    assert view["runtime_identity_verified"] is False
    assert view["native_applicability_verified"] is False
    assert view["transformation_authorized"] is False
    assert "code" not in view and "graph" not in view


@pytest.mark.parametrize("text,accepted,sites", (
    ("async def body():\n    yield 1\n    return\n", True, {3: False}),
    ("async def body():\n    yield 1\n    return None\n", False, {3: True}),
    ("async def body():\n    yield 1\n    def nested():\n        return None\n    return\n",
     True, {4: True, 5: False}),
    ("async def body():\n    def nested():\n        yield 1\n    return None\n", True, {4: True}),
    ("async def body():\n    def nested(x=(yield 1)):\n        return None\n    return None\n",
     False, {3: True, 4: True}),
), ids=("bare-return", "explicit-none", "nested-sync-return",
        "yield-only-nested", "yield-in-nested-default"))
def test_cpython_compilation_and_return_expression_inventory_are_independent(text, accepted, sites):
    view = source_compilation(_snapshot(text), text=text)
    assert view["compiled"] is accepted
    assert view["compiler_attempted"] is True
    assert view["fingerprint_match"] is True
    assert view["encoding_match"] is True and view["version_match"] is True
    assert view["python_version"] == platform.python_version()
    assert {row["source"].start_line: row["expression_present"] for row in view["returns"]} == sites
    assert view["inventory"]["known_inventory_complete"] is True
    assert view["inventory"]["returns_total"] == len(sites)
    if accepted:
        assert view["status"] == "ACCEPTED" and not view["diagnostics"]
        assert view["inventory"]["diagnostics_complete"] is True
        assert all(row["compiler_checked"] is True for row in view["returns"])
    else:
        assert view["status"] == "REJECTED"
        diagnostic, = view["diagnostics"]
        assert "return" in diagnostic["message"] and "async generator" in diagnostic["message"]
        assert diagnostic["phase"] == "compile"
        assert diagnostic["return_sources"]
        assert view["inventory"]["diagnostics_complete"] is False
        assert all(row["compiler_checked"] is None for row in view["returns"])
    _no_execution(view)


def test_first_compiler_error_keeps_all_return_sites_without_claiming_all_diagnosed():
    text = ("async def first():\n    yield 1\n    return None\n"
            "async def second():\n    yield 2\n    return 3\n"
            "def unrelated():\n    return None\n")
    view = source_compilation(_snapshot(text), text=text)
    assert view["compiled"] is False
    assert {row["source"].start_line for row in view["returns"]} == {3, 6, 8}
    assert view["inventory"]["returns_total"] == 3
    assert view["inventory"]["checked_returns"] == 0
    assert view["inventory"]["diagnostics_complete"] is False
    diagnostic, = view["diagnostics"]
    assert diagnostic["line"] == 3
    assert {source.start_line for source in diagnostic["return_sources"]} == {3}
    assert "source_compilation_first_error_only" in _codes(view)


def test_compilation_does_not_run_imports_decorators_defaults_or_module_effects(tmp_path):
    marker = tmp_path / "must-not-exist"
    text = ("import definitely_absent_target_module\n"
            "@undefined_decorator\n"
            "def body(value=undefined_default()):\n    return value\n"
            f"open({str(marker)!r}, 'w').write('executed')\n"
            "raise RuntimeError('target must never run')\n")
    view = source_compilation(_snapshot(text, str(tmp_path / "not-on-disk.py")), text=text)
    assert view["compiled"] is True
    assert not marker.exists()
    assert not (tmp_path / "not-on-disk.py").exists()
    assert "definitely_absent_target_module" not in sys.modules
    _no_execution(view)


@pytest.mark.parametrize("problem", ("missing-text", "fingerprint", "version", "missing-version", "patch"))
def test_unverified_source_is_not_compiled_or_recovered_from_the_filesystem(problem):
    text = "def body():\n    return None\n"
    snapshot = _snapshot(text)
    supplied = text
    expected = {"missing-text": "source_compilation_text_missing",
                "fingerprint": "source_compilation_fingerprint_mismatch",
                "version": "source_compilation_version_mismatch",
                "missing-version": "source_compilation_version_unresolved",
                "patch": "source_compilation_version_mismatch"}[problem]
    if problem == "missing-text":
        supplied = None
    elif problem == "fingerprint":
        snapshot = replace(snapshot, fingerprint="sha256:" + "0" * 64)
    elif problem == "version":
        snapshot = replace(snapshot, python_version="0.0")
    elif problem == "patch":
        snapshot = replace(snapshot, python_version=(
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro + 1}"))
    else:
        snapshot = replace(snapshot, python_version=None)
    view = source_compilation(snapshot, text=supplied)
    assert view["compiled"] is None and view["compiler_attempted"] is False
    assert expected in _codes(view)
    assert view["returns"] == ()
    assert view["inventory"]["returns_total"] is None
    assert view["inventory"]["known_inventory_complete"] is False
    _no_execution(view)


def test_encoding_is_checked_against_the_snapshot_without_changing_utf8_fingerprint():
    text = "# coding: latin-1\ndef body():\n    return 'é'\n"
    correct = source_compilation(_snapshot(text, encoding="latin-1"), text=text)
    wrong = source_compilation(_snapshot(text, encoding="utf-8"), text=text)
    unknown = source_compilation(_snapshot(text, encoding="not-an-encoding"), text=text)
    assert correct["compiled"] is True and correct["encoding_match"] is True
    for view in (wrong, unknown):
        assert view["fingerprint_match"] is True
        assert view["encoding_match"] is False and view["compiled"] is None
        assert "source_compilation_encoding_mismatch" in _codes(view)


def test_budget_cut_does_not_present_an_inventory_prefix_or_unchecked_compile_as_complete():
    text = "def body():\n    return 1\n"
    tiny = source_compilation(_snapshot(text), text=text, budget=1)
    assert tiny["compiled"] is None and tiny["compiler_attempted"] is False
    assert tiny["inventory"]["returns_total"] is None
    assert tiny["inventory"]["known_inventory_complete"] is False
    assert tiny["budget"]["truncated"] is True and tiny["cursor"] is not None
    assert "source_compilation_budget_exhausted" in _codes(tiny)
    full = source_compilation(_snapshot(text), text=text)
    # Cut exactly before code compilation, after complete syntax inventory.
    limit = full["budget"]["used"] - full["budget"]["costs"]["source_compile"]
    late = source_compilation(_snapshot(text), text=text, budget=limit)
    assert late["compiled"] is None and late["compiler_attempted"] is False
    assert late["inventory"]["returns_total"] == 1
    assert late["inventory"]["known_inventory_complete"] is True
    assert late["inventory"]["diagnostics_complete"] is False
    assert late["returns"][0]["compiler_checked"] is None
    assert late["cursor"]["phase"] == "source_compile"


def test_return_atom_identity_and_exact_optional_links_preserve_the_original_namespace():
    text = "def first(): return None; return None\n"
    snapshot = _snapshot(text, python_version=platform.python_version())
    path, root = Path(snapshot.path), Path("/supplied")
    tree = ast.parse(text)
    expected = tuple(source_reference(path, root, snapshot.fingerprint, index, node)
                     for index, node in enumerate(ast.walk(tree)) if isinstance(node, ast.Return))
    first = OperationSource(OperationID("first-return"), expected[0], SourceRole.RETURN)
    wrong_span = replace(first, operation=OperationID("wrong-span"),
                         source=replace(first.source, start_column=first.source.start_column + 1))
    wrong_atom = replace(first, operation=OperationID("wrong-atom"),
                         source=replace(first.source, atom_id=SourceAtomID("different-original-atom")))
    linked = source_compilation(snapshot, text=text, source_root=root,
                                operation_links=(first, wrong_span, wrong_atom))
    detached = source_compilation(snapshot, text=text, source_root=root)
    assert tuple(row["source"] for row in linked["returns"]) == expected
    assert tuple(row["source"] for row in detached["returns"]) == expected
    assert linked["inventory"]["returns_total"] == detached["inventory"]["returns_total"] == 2
    assert {source.start_line for source in expected} == {1}
    assert len({source.atom_id for source in expected}) == 2
    assert linked["returns"][0]["operation_links"] == (first,)
    assert not linked["returns"][1]["operation_links"]
    assert tuple(row["match"] for row in linked["operation_links"]) == (True, False, False)
    assert "source_compilation_operation_link_mismatch" in _codes(linked)
    assert linked["compiled"] is True  # Bad metadata does not rewrite compiler facts.
    assert linked["version_match"] is True
    assert all(not row["operation_links"] for row in detached["returns"])


def test_unicode_syntaxerror_character_offsets_match_the_original_ast_byte_span():
    text = "async def body():\n    café = 1; return None\n    yield 1\n"
    view = source_compilation(_snapshot(text), text=text)
    assert view["compiled"] is False
    row, = view["returns"]
    diagnostic, = view["diagnostics"]
    assert diagnostic["phase"] == "compile"
    assert row["source"].start_column == len("    café = 1; ".encode("utf-8"))
    # The semantic compiler error retains AST byte columns, unlike parser
    # SyntaxErrors. Preserve the exact original Return span on both ends.
    assert diagnostic["offset"] - 1 == row["source"].start_column
    assert diagnostic["offset"] - 1 != len("    café = 1; ")
    assert diagnostic["end_offset"] - 1 == row["source"].end_column
    assert diagnostic["span"]["start_column"] == row["source"].start_column
    assert diagnostic["span"]["end_column"] == row["source"].end_column
    assert diagnostic["return_sources"] == (row["source"],)


def test_unicode_parser_character_offsets_are_converted_to_utf8_byte_columns():
    text = "café = ;\n"
    view = source_compilation(_snapshot(text), text=text)
    assert view["compiled"] is False and view["compiler_attempted"] is False
    diagnostic, = view["diagnostics"]
    assert diagnostic["phase"] == "parse"
    assert diagnostic["offset"] == len("café = ") + 1 == 8
    assert diagnostic["end_offset"] == len("café = ;") + 1 == 9
    assert diagnostic["span"] == {"start_line": 1, "end_line": 1,
        "start_column": len("café = ".encode("utf-8")),
        "end_column": len("café = ;".encode("utf-8"))}
    assert diagnostic["return_sources"] == ()
    assert view["returns"] == ()
    assert view["inventory"]["known_inventory_complete"] is False
    assert view["inventory"]["returns_total"] is None
    assert view["inventory"]["diagnostics_complete"] is False
    _no_execution(view)


def test_four_mebibyte_compile_ceiling_keeps_oversized_source_unchecked():
    text = "#" * (MAX_SOURCE_BYTES + 1)
    view = source_compilation(_snapshot(text), text=text)
    assert view["compiled"] is None and view["compiler_attempted"] is False
    assert "source_compilation_input_limit" in _codes(view)
    assert view["inventory"]["returns_total"] is None


@pytest.mark.parametrize("budget,error", ((True, TypeError), (0, ValueError)))
def test_budget_requires_a_positive_exact_integer(budget, error):
    text = "pass\n"
    with pytest.raises(error):
        source_compilation(_snapshot(text), text=text, budget=budget)


def test_optional_type_comment_parse_failure_cannot_reject_compilable_source_or_authorize_links():
    text = "pass # type: int\ndef body():\n    return None\n"
    snapshot = _snapshot(text)
    path, root = Path(snapshot.path), Path("/supplied")
    ordinary = ast.parse(text, type_comments=False)
    index, node = next((index, node) for index, node in enumerate(ast.walk(ordinary))
                       if isinstance(node, ast.Return))
    # Even an exact ordinary-AST span and its usual-looking atom digest do not
    # establish correspondence to the frontend's rejected typed AST.
    candidate = OperationSource(OperationID("ordinary-return-candidate"),
        source_reference(path, root, snapshot.fingerprint, index, node), SourceRole.RETURN)
    linked = source_compilation(snapshot, text=text, source_root=root, operation_links=(candidate,))
    unlinked = source_compilation(snapshot, text=text, source_root=root)
    for view in (linked, unlinked):
        assert view["compiled"] is True and view["compiler_attempted"] is True
        assert view["frontend_ast_mode_match"] is False
        assert view["status"] == "PARTIAL" and view["diagnostics"] == ()
        assert "source_compilation_frontend_ast_mode_mismatch" in _codes(view)
        assert view["inventory"]["known_inventory_complete"] is True
        assert view["inventory"]["returns_total"] == 1
        row, = view["returns"]
        assert row["source"] is None and row["expression_present"] is True
        assert row["span"] == {"start_line": 3, "end_line": 3,
                               "start_column": 4, "end_column": 15}
        assert row["operation_links"] == ()
        _no_execution(view)
    item, = linked["operation_links"]
    assert item["link"] == candidate and item["match"] is None
    assert item["return_source"] is None
    assert "source_compilation_operation_link_unresolved" in _codes(linked)


def test_valid_type_ignore_preserves_frontend_atom_namespace_and_exact_operation_link():
    text = "def body():\n    return None  # type: ignore[return-value]\n"
    snapshot = _snapshot(text)
    path, root = Path(snapshot.path), Path("/supplied")
    typed = ast.parse(text, type_comments=True)
    assert typed.type_ignores
    index, node = next((index, node) for index, node in enumerate(ast.walk(typed))
                       if isinstance(node, ast.Return))
    expected = source_reference(path, root, snapshot.fingerprint, index, node)
    link = OperationSource(OperationID("typed-return"), expected, SourceRole.RETURN)
    view = source_compilation(snapshot, text=text, source_root=root, operation_links=(link,))
    assert view["compiled"] is True and view["status"] == "ACCEPTED"
    assert view["frontend_ast_mode_match"] is True
    row, = view["returns"]
    assert row["source"] == expected and row["operation_links"] == (link,)
    item, = view["operation_links"]
    assert item["match"] is True and item["return_source"] == expected
    assert not view["gaps"]
    _no_execution(view)
