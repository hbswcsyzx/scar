"""Static CPython compiler layouts for source lowering (never target execution).

The resulting CodeType objects are compilation products of the retained source
text.  They are not CapturedCode values and establish no runtime code object,
function, invocation, or loaded-module identity.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
import dis
import hashlib
import sys
from types import CodeType
from typing import Any

from scar.ir.record_codec import encode
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.program.source_subjects import ModuleUnitSource, SourceCompilationCodeRef
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID
from scar.trace.code_snapshot import code_key


class StaticCompilationError(ValueError):
    """The exact source/compiler layout needed for a definition is unavailable."""


def _span(node: ast.AST) -> tuple[int, int, int, int]:
    values = (getattr(node, "lineno", None), getattr(node, "end_lineno", None),
              getattr(node, "col_offset", None), getattr(node, "end_col_offset", None))
    if any(type(value) is not int for value in values):
        raise StaticCompilationError("source compiler mapping requires complete AST positions")
    return values  # type: ignore[return-value]


def _reference_span(reference: SourceReference) -> tuple[int, int, int, int]:
    if reference.end_column is None:
        raise StaticCompilationError("source reference has no exact end column")
    return (reference.start_line, reference.end_line,
            reference.start_column, reference.end_column)


def _code_children(parent: CodeType, source_span: tuple[int, int, int, int],
                   name: str, qualname: str, first_line: int) -> list[tuple[int, CodeType]]:
    rows = []
    for instruction in dis.get_instructions(parent, adaptive=False, show_caches=False):
        child = instruction.argval
        if (instruction.opname == "LOAD_CONST" and type(child) is CodeType
                and tuple(instruction.positions) == source_span
                and child.co_name == name and child.co_qualname == qualname
                and child.co_firstlineno == first_line):
            rows.append((instruction.arg, child))
    return rows


def _child_qualname(parent_code: CodeType, parent_kind: type[ast.AST], name: str) -> str:
    if parent_kind is ast.Module:
        return name
    if parent_kind is ast.ClassDef:
        return parent_code.co_qualname + "." + name
    return parent_code.co_qualname + ".<locals>." + name


def _scope_first_line(node: ast.AST) -> int | None:
    """Return CPython's code first-line input from the exact AST decorators."""
    decorators = tuple(getattr(node, "decorator_list", ()))
    if decorators:
        lines = [getattr(decorator, "lineno", None) for decorator in decorators]
        if any(type(line) is not int for line in lines):
            return None
        return min(lines)
    return getattr(node, "lineno", None)


def _scope_nodes(node: ast.AST, parent_code: CodeType, parent_path: tuple[int, ...],
                 parent_kind: type[ast.AST], found: dict[tuple[int, int, int, int],
                 list[tuple[tuple[int, ...], CodeType, ast.AST]]], issues: list[dict[str, Any]],
                 ) -> None:
    """Walk lexical scopes, compiling only the lexical child layout relation."""
    scope_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

    def visit(current: ast.AST, code: CodeType, path: tuple[int, ...],
              kind: type[ast.AST]) -> None:
        if isinstance(current, scope_types):
            position = _span(current)
            qualname = _child_qualname(code, kind, current.name)
            first_line = _scope_first_line(current)
            matches = ([] if first_line is None else
                       _code_children(code, position, current.name, qualname, first_line))
            if len(matches) != 1:
                issues.append({"source_span": position, "kind": type(current).__name__,
                               "status": ("DECORATOR_FIRST_LINE_UNRESOLVED" if first_line is None else
                                           "AMBIGUOUS_OR_MISSING_COMPILER_LAYOUT"),
                               "candidate_count": len(matches)})
                # Header expressions execute in the parent scope. Never guess
                # which code object owns the body when matching is ambiguous.
                if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    headers = (*current.decorator_list, *current.args.defaults,
                               *(item for item in current.args.kw_defaults if item is not None))
                else:
                    headers = (*current.decorator_list, *current.bases,
                               *(item.value for item in current.keywords))
                for expression in headers:
                    visit(expression, code, path, kind)
                return

            const_index, child_code = matches[0]
            child_path = path + (const_index,)
            found.setdefault(position, []).append((child_path, child_code, current))
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                headers = (*current.decorator_list, *current.args.defaults,
                           *(item for item in current.args.kw_defaults if item is not None))
            else:
                headers = (*current.decorator_list, *current.bases,
                           *(item.value for item in current.keywords))
            for expression in headers:
                visit(expression, code, path, kind)
            for statement in current.body:
                visit(statement, child_code, child_path, type(current))
            return

        for child in ast.iter_child_nodes(current):
            visit(child, code, path, kind)

    roots = node.body if isinstance(node, (ast.Module, ast.FunctionDef,
                                          ast.AsyncFunctionDef, ast.ClassDef)) else (node,)
    for root in roots:
        visit(root, parent_code, parent_path, parent_kind)


@dataclass(frozen=True, slots=True)
class StaticCodeEvidence:
    """One exact source definition's compiler layout, with static provenance."""

    snapshot: SourceSnapshot
    namespace_root: str
    definition: OperationDefinitionID
    source: SourceReference | ModuleUnitSource
    code_path: tuple[int, ...]
    code: CodeType = field(repr=False, compare=False)
    code_layout_key: str
    compiler_implementation: str
    compiler_version: tuple[int, int, int]
    compiler_python: str
    compiler_cache_tag: str | None
    compile_mode: str = "exec"
    compile_flags: int = 0
    dont_inherit: bool = True
    optimize: int = 0
    root_code_layout_key: str = ""
    evidence_kind: str = "SOURCE_COMPILATION"

    def __post_init__(self) -> None:
        if (type(self.snapshot) is not SourceSnapshot or type(self.definition) is not OperationDefinitionID
                or type(self.source) not in (SourceReference, ModuleUnitSource)
                or type(self.namespace_root) is not str or not self.namespace_root.startswith("/")
                or type(self.code) is not CodeType or type(self.code_path) is not tuple
                or any(type(index) is not int or index < 0 for index in self.code_path)
                or self.evidence_kind != "SOURCE_COMPILATION"):
            raise ValueError("static code evidence must bind an exact source definition and compiled code path")
        if type(self.source) is ModuleUnitSource:
            if (self.source.snapshot != self.snapshot or self.source.namespace_root != self.namespace_root
                    or self.source.initializer != self.definition or self.code_path
                    or self.code_layout_key != self.root_code_layout_key):
                raise ValueError("static module evidence must describe its exact exec compiler root")
        elif (self.source.path != self.snapshot.path or self.source.fingerprint != self.snapshot.fingerprint
                or not self.code_path):
            raise ValueError("static definition evidence must describe its exact lexical child code")
        if self.code_layout_key != code_key(self.code) or self.root_code_layout_key == "":
            raise ValueError("static code evidence compiler layout key differs")
        if (type(self.compiler_version) is not tuple or len(self.compiler_version) != 3
                or any(type(value) is not int or value < 0 for value in self.compiler_version)
                or self.compile_mode != "exec" or self.compile_flags != 0
                or self.dont_inherit is not True or self.optimize != 0):
            raise ValueError("unsupported static compiler profile")

    def require_definition(self, snapshot, definition, source) -> None:
        if (snapshot != self.snapshot or definition != self.definition or source != self.source):
            raise ValueError("static compilation evidence identifies a different source definition")

    def to_reference(self) -> SourceCompilationCodeRef:
        """Persist compiler provenance without a live CodeType or runtime ID."""
        return SourceCompilationCodeRef(self.source, self.definition, self.code_path,
            self.code_layout_key, self.root_code_layout_key, self.compiler_implementation,
            self.compiler_version, self.compiler_python, self.compiler_cache_tag,
            self.compile_mode, self.compile_flags, self.dont_inherit, self.optimize)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_kind": self.evidence_kind,
            "snapshot": encode(self.snapshot),
            "namespace_root": self.namespace_root,
            "definition": encode(self.definition),
            "source": (self.source.as_dict() if type(self.source) is SourceReference else
                       {"source_kind": "MODULE_UNIT", **encode(self.source)}),
            "code_path": list(self.code_path),
            "code_layout_key": self.code_layout_key,
            "root_code_layout_key": self.root_code_layout_key,
            "compiler": {
                "implementation": self.compiler_implementation,
                "version": list(self.compiler_version),
                "python": self.compiler_python,
                "cache_tag": self.compiler_cache_tag,
                "mode": self.compile_mode,
                "flags": self.compile_flags,
                "dont_inherit": self.dont_inherit,
                "optimize": self.optimize,
            },
            "runtime_code_instance_established": False,
        }


@dataclass(frozen=True, slots=True)
class SourceCompiledUnit:
    """One no-exec module compilation and its exact lexical child-code paths."""

    snapshot: SourceSnapshot
    namespace_root: str
    source_sha256: str
    root_code: CodeType = field(repr=False, compare=False)
    entries: tuple[tuple[OperationDefinitionID, SourceReference, tuple[int, ...], CodeType], ...] = field(
        repr=False, compare=False)
    issues: tuple[dict[str, Any], ...]
    compiler_implementation: str
    compiler_version: tuple[int, int, int]
    compiler_python: str
    compiler_cache_tag: str | None
    module: ModuleUnitSource
    compile_mode: str = "exec"
    compile_flags: int = 0
    dont_inherit: bool = True
    optimize: int = 0

    def __post_init__(self) -> None:
        if (type(self.snapshot) is not SourceSnapshot or type(self.root_code) is not CodeType
                or self.compile_mode != "exec" or self.compile_flags != 0
                or self.dont_inherit is not True or self.optimize != 0):
            raise ValueError("source compiled unit has an unsupported compilation profile")
        if (type(self.module) is not ModuleUnitSource or self.module.snapshot != self.snapshot
                or self.module.namespace_root != self.namespace_root):
            raise ValueError("compiled module declaration differs from its original source namespace")
        if self.source_sha256 != self.snapshot.fingerprint.removeprefix("sha256:"):
            raise ValueError("compiled source digest differs from its SourceSnapshot")
        if code_key(self.root_code) == "":
            raise ValueError("compiled module has no structural code key")

    @property
    def root_code_layout_key(self) -> str:
        return code_key(self.root_code)

    def for_module(self, unit: ModuleUnitSource) -> StaticCodeEvidence:
        """Select the original module initializer, never a function substitute."""
        if type(unit) is not ModuleUnitSource or unit != self.module:
            raise StaticCompilationError("module differs from the compiled source unit")
        return StaticCodeEvidence(self.snapshot, self.namespace_root, unit.initializer, unit,
            (), self.root_code, self.root_code_layout_key, self.compiler_implementation,
            self.compiler_version, self.compiler_python, self.compiler_cache_tag,
            self.compile_mode, self.compile_flags, self.dont_inherit, self.optimize,
            self.root_code_layout_key)

    def for_definition(self, definition: OperationDefinitionID,
                       source: SourceReference) -> StaticCodeEvidence:
        if type(definition) is not OperationDefinitionID or type(source) is not SourceReference:
            raise TypeError("static source lookup requires original definition and source reference IDs")
        if (source.path != self.snapshot.path or source.fingerprint != self.snapshot.fingerprint):
            raise StaticCompilationError("definition source differs from compiled source snapshot")
        position = _reference_span(source)
        matches = [(path, code) for def_id, reference, path, code in self.entries
                   if def_id == definition and reference == source]
        if len(matches) != 1:
            local = [row for row in self.issues if tuple(row.get("source_span", ())) == position]
            detail = local[0]["status"] if local else "NO_EXACT_LEXICAL_CODE_MAPPING"
            raise StaticCompilationError(detail)
        path, code = matches[0]
        return StaticCodeEvidence(self.snapshot, self.namespace_root, definition, source,
            path, code, code_key(code), self.compiler_implementation, self.compiler_version,
            self.compiler_python, self.compiler_cache_tag, self.compile_mode, self.compile_flags,
            self.dont_inherit, self.optimize, self.root_code_layout_key)


def compile_source_unit(prepared) -> SourceCompiledUnit:
    """Compile one exact PreparedSource to CodeType layout; never execute it."""
    from scar.analysis.program_lowering import PreparedSource

    if type(prepared) is not PreparedSource:
        raise TypeError("static compilation requires an exact PreparedSource")
    path = str(prepared.path)
    namespace_root = str(prepared.root)
    if (not prepared.path.is_absolute() or not prepared.root.is_absolute()
            or not prepared.path.is_relative_to(prepared.root) or ".." in prepared.path.parts
            or ".." in prepared.root.parts):
        raise StaticCompilationError("compiled source needs its original absolute namespace")
    source_bytes = prepared.text.encode("utf-8")
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    snapshot = prepared.semantics.sources.get(path)
    if (type(snapshot) is not SourceSnapshot or snapshot.path != path
            or snapshot.fingerprint != "sha256:" + source_sha256):
        raise StaticCompilationError("PreparedSource text differs from its exact source snapshot")
    parsed = ast.parse(prepared.text, filename=path)
    if ast.dump(parsed, include_attributes=True) != ast.dump(prepared.tree, include_attributes=True):
        raise StaticCompilationError("PreparedSource AST differs from its retained source text")
    root = compile(prepared.text, path, "exec", flags=0, dont_inherit=True, optimize=0)
    if type(root) is not CodeType:
        raise StaticCompilationError("source compiler did not return a module CodeType")

    # Build exact AST definition -> compiler child path rows. A named scope is
    # admitted only by its parent LOAD_CONST occurrence, complete span, name,
    # qualname, and first line. Ambiguity is retained as an issue.
    by_span: dict[tuple[int, int, int, int], list[tuple[tuple[int, ...], CodeType, ast.AST]]] = {}
    issues: list[dict[str, Any]] = []
    _scope_nodes(parsed, root, (), ast.Module, by_span, issues)
    entries = []
    semantic_definitions = prepared.semantic.definitions
    for definition_id, definition in semantic_definitions.items():
        if type(definition_id) is not OperationDefinitionID:
            continue
        for atom_id in definition.source_atoms:
            atom = prepared.semantic.source_atoms.get(atom_id)
            if atom is None:
                continue
            reference = atom.reference
            if (reference.path != path or reference.fingerprint != snapshot.fingerprint):
                continue
            span = _reference_span(reference)
            candidates = by_span.get(span, ())
            exact = [(code_path, code) for code_path, code, node in candidates
                     if getattr(node, "lineno", None) == reference.start_line
                     and getattr(node, "end_lineno", None) == reference.end_line]
            if len(exact) == 1:
                code_path, code = exact[0]
                entries.append((definition_id, reference, code_path, code))
            elif len(exact) > 1:
                issues.append({"source_span": span, "definition": encode(definition_id),
                               "status": "MULTIPLE_DEFINITION_CODE_PATHS", "candidate_count": len(exact)})
    # A source operation can have many atom references; preserve only exact,
    # unique definition/source pairs. Do not choose among duplicate mappings.
    unique = {}
    for row in entries:
        key = row[0], row[1]
        unique.setdefault(key, []).append(row)
    clean_entries = tuple(rows[0] for rows in unique.values() if len(rows) == 1)
    for (definition_id, reference), rows in unique.items():
        if len(rows) > 1:
            issues.append({"source_span": _reference_span(reference), "definition": encode(definition_id),
                           "status": "DUPLICATE_DEFINITION_SOURCE_MAPPING", "candidate_count": len(rows)})

    from scar.analysis.source_module_lowering import module_unit
    return SourceCompiledUnit(snapshot, namespace_root, source_sha256, root, clean_entries,
        tuple(issues), sys.implementation.name, tuple(sys.version_info[:3]), sys.version,
        sys.implementation.cache_tag, module_unit(prepared))


__all__ = ["StaticCompilationError", "StaticCodeEvidence", "SourceCompiledUnit", "compile_source_unit"]
