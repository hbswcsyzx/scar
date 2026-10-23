"""Compiler-derived closure layout for a pinned source definition.

Compilation constructs code objects but never evaluates the module, imports,
decorators, defaults, annotations or function bodies.  Only immutable primitive
projections are cached on the prepared context; no CodeType or runtime callable
escapes the query.  This witnesses source layout, not a live function binding.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import platform
import symtable
import sys
from types import CodeType

from scar.ir.v2.semantic import OperationDefinition, OperationKind


_CACHE_ATTRIBUTE = "_scar_compiler_environment_layout_v1"
_MAX_SOURCE_BYTES = 4_000_000
_MAX_CODES = 100_000


@dataclass(frozen=True, slots=True)
class CompilerEnvironmentLayout:
    freevars: tuple[str, ...]
    cellvars: tuple[str, ...]
    qualified_name: str
    first_line: int

    def __post_init__(self):
        for name in ("freevars", "cellvars"):
            values = getattr(self, name)
            if (type(values) is not tuple or any(type(value) is not str or not value for value in values)
                    or len(set(values)) != len(values)):
                raise ValueError(name + " must be a tuple of unique names")
        if set(self.freevars) & set(self.cellvars):
            raise ValueError("a binding cannot be both free and locally owned")
        if type(self.qualified_name) is not str or not self.qualified_name:
            raise ValueError("compiler qualified name must be nonempty text")
        if type(self.first_line) is not int or self.first_line < 1:
            raise ValueError("compiler first line must be positive")


def _functions(tree):
    """Yield lexical Python qualnames, distinguishing function/class scopes."""
    def visit(node, prefix):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualified = prefix + node.name
            yield node, qualified
            for statement in node.body:
                yield from visit(statement, qualified + ".<locals>.")
            return
        if isinstance(node, ast.ClassDef):
            for statement in node.body:
                yield from visit(statement, prefix + node.name + ".")
            return
        for child in ast.iter_child_nodes(node):
            yield from visit(child, prefix)
    yield from visit(tree, "")


def _table_kind(table):
    kind = table.get_type()
    return getattr(kind, "value", kind)


def _symbol_projection(table):
    """Keep classification sets separate from the compiler's ordered layout."""
    symbols = table.get_symbols()
    free = tuple(symbol.get_name() for symbol in symbols if symbol.is_free() or symbol.is_nonlocal())
    local = tuple(symbol.get_name() for symbol in symbols if symbol.is_local())
    # A local cell must serve a child scope.  Descendant demand is a consistency
    # check only: the compiler, rather than lexical name searches, owns layout.
    descendant_free = set()
    def visit(child):
        descendant_free.update(symbol.get_name() for symbol in child.get_symbols()
                               if symbol.is_free() or symbol.is_nonlocal())
        for grandchild in child.get_children():
            visit(grandchild)
    for child in table.get_children():
        visit(child)
    return (table.get_name(), table.get_lineno(), free, local, tuple(sorted(descendant_free)))


def _project(prepared, cache_key):
    code = compile(prepared.text, str(prepared.path), "exec", flags=0,
                   dont_inherit=True, optimize=0)
    rows = []
    def visit(current):
        if len(rows) >= _MAX_CODES:
            raise ValueError("compiler environment code budget exceeded")
        positions = [line for position in current.co_positions()
                     for line in position[:2] if type(line) is int and line > 0]
        rows.append((current.co_name, current.co_qualname, current.co_firstlineno,
                     tuple(current.co_freevars), tuple(current.co_cellvars),
                     min(positions) if positions else None,
                     max(positions) if positions else None))
        for constant in current.co_consts:
            if type(constant) is CodeType:
                visit(constant)
    visit(code)
    tables = []
    def visit_table(table):
        if _table_kind(table) == "function":
            tables.append(_symbol_projection(table))
        for child in table.get_children():
            visit_table(child)
    visit_table(symtable.symtable(prepared.text, str(prepared.path), "exec"))
    # A PreparedSource is frozen but intentionally has an instance dictionary.
    # Its private scratch store serializes declared fields only; keeping this
    # optional cache primitive also makes direct inspection/pickling harmless.
    projection = (cache_key, tuple(rows), tuple(tables))
    object.__setattr__(prepared, _CACHE_ATTRIBUTE, projection)
    return projection


def compiler_environment_layout(prepared, node, definition):
    """Recover exact co_freevars/co_cellvars order for one source function.

    The selected AST node and definition must belong to the prepared snapshot.
    A repeated name, ambiguous code candidate, source mismatch or disagreement
    with the compiler's own symbol table fails explicitly.  This API never
    obtains a callable by evaluating source or looking it up in a live module.
    """
    if platform.python_implementation() != "CPython":
        raise ValueError("compiler environment layout requires CPython")
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise ValueError("environment layout requires a selected function definition")
    if type(definition) is not OperationDefinition:
        raise ValueError("environment layout requires a semantic function definition")
    if (definition.kind not in (OperationKind.FUNCTION, OperationKind.METHOD)
            or definition.metadata.get("phase") != "call_time"
            or prepared.semantic.definitions.get(definition.id) is not definition):
        raise ValueError("environment definition is not a prepared call-time function")
    if type(prepared.text) is not str or len(prepared.text) > _MAX_SOURCE_BYTES:
        raise ValueError("environment source exceeds the fixed compile ceiling")
    encoded = prepared.text.encode("utf-8")
    if len(encoded) > _MAX_SOURCE_BYTES:
        raise ValueError("environment UTF-8 source exceeds the fixed compile ceiling")
    fingerprint = "sha256:" + hashlib.sha256(encoded).hexdigest()
    snapshot = prepared.semantics.sources.get(str(prepared.path))
    if snapshot is None or snapshot.fingerprint != fingerprint:
        raise ValueError("environment source differs from its prepared snapshot")
    expected_version = (str(sys.version_info.major), str(sys.version_info.minor))
    if (type(snapshot.python_version) is not str
            or tuple(snapshot.python_version.split(".")[:2]) != expected_version):
        raise ValueError("environment compiler differs from the source Python version")
    selected = [(candidate, name) for candidate, name in _functions(prepared.tree) if candidate is node]
    if len(selected) != 1:
        raise ValueError("selected function is not unique in the prepared AST")
    qualified = selected[0][1]
    atoms = [prepared.semantic.source_atoms[identity] for identity in definition.source_atoms
             if identity in prepared.semantic.source_atoms]
    if (definition.source_file != str(prepared.path) or definition.label != node.name
            or not any(atom.kind == type(node).__name__ and atom.reference.path == str(prepared.path)
                       and atom.reference.fingerprint == fingerprint
                       and (atom.reference.start_line, atom.reference.end_line,
                            atom.reference.start_column, atom.reference.end_column)
                       == (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)
                       for atom in atoms)):
        raise ValueError("environment definition differs from the selected source span")
    cache_key = (str(prepared.path), fingerprint, sys.implementation.name,
                 tuple(sys.version_info), 0, True)
    projection = getattr(prepared, _CACHE_ATTRIBUTE, None)
    if type(projection) is not tuple or len(projection) != 3 or projection[0] != cache_key:
        projection = _project(prepared, cache_key)
    first_line = node.decorator_list[0].lineno if node.decorator_list else node.lineno
    candidates = [row for row in projection[1]
                  if row[:3] == (node.name, qualified, first_line)
                  and (row[5] is None or first_line <= row[5] <= row[6] <= node.end_lineno)]
    if len(candidates) != 1:
        raise ValueError("selected function has no unique exact compiler layout")
    matching_tables = [row for row in projection[2] if row[:2] == (node.name, node.lineno)]
    if len(matching_tables) != 1:
        raise ValueError("selected function has no unique compiler symbol table")
    _, _, free, local, child_free = matching_tables[0]
    _, _, first_line, freevars, cellvars, _, _ = candidates[0]
    if set(freevars) != set(free):
        raise ValueError("compiler free-variable layout disagrees with free/nonlocal symbols")
    if not set(cellvars) <= set(local) or not set(cellvars) <= set(child_free):
        raise ValueError("compiler cell layout disagrees with locally owned child captures")
    if set(freevars) & set(local):
        raise ValueError("compiler free bindings overlap local bindings")
    return CompilerEnvironmentLayout(freevars, cellvars, qualified, first_line)


__all__ = ["CompilerEnvironmentLayout", "compiler_environment_layout"]
