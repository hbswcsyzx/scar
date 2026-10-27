"""Bounded, non-executing discovery of source files reachable by import syntax.

This module reads Python source and parses its AST. It never imports the
target, calls ``find_spec``, or runs project configuration. Search roots are
candidate contexts, not assertions about the process's actual ``sys.path``.
"""
from __future__ import annotations

import ast
from collections import deque
from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
import re
import stat
import tokenize

from scar.ir.frontend_v2 import EXCLUDED_DIRECTORIES, source_reference
from scar.ir.program.call_edges import CallLinkStatus, CodeSourceLink
from scar.ir.program.discovery import (
    CandidateRole, DiscoveredFile, DiscoveryGap, DiscoveryGapKind,
    DiscoveryRootMode, DiscoveryStatus, ImportDependency, ModuleCandidate,
    ModuleMapping, SourceDiscovery, DiscoveryControlKind, ImportControlContext,
)
from scar.ir.semantics_v2 import ImportForm, SourceSnapshot
from scar.ir.record_codec import decode, encode
from scar.ir.v2.common import SourceReference


_EXCLUDED_DISCOVERY_DIRECTORIES = frozenset({
    *EXCLUDED_DIRECTORIES,
    "artifacts", "outputs", "output", "build", "dist", "coverage",
    ".cache", ".idea", ".next", "target",
})
_SOURCE_SUFFIX = ".py"
_PROJECT_MARKERS = frozenset({"pyproject.toml", "setup.cfg", "setup.py"})
_ATOM_NODE_TYPES = (ast.stmt, ast.expr, ast.arg, ast.alias, ast.keyword, ast.ExceptHandler)


@dataclass(frozen=True, slots=True)
class _ImportSyntax:
    node: ast.AST
    alias: ast.alias
    source: SourceReference
    alias_source: SourceReference
    requested: str
    relative_level: int
    symbol: str | None
    bound_name: str | None
    form: ImportForm
    owner_qualname: str
    deferred: bool
    control_context: tuple[ImportControlContext, ...] = ()


@dataclass(frozen=True, slots=True)
class _DynamicSyntax:
    node: ast.Call
    source: SourceReference
    owner_qualname: str
    deferred: bool
    reason: str
    kind: DiscoveryGapKind = DiscoveryGapKind.DYNAMIC_IMPORT


@dataclass(frozen=True, slots=True)
class _ModuleContext:
    source_root: Path
    module_name: str


def _positive_limit(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _path_has_symlink_below(path: Path, root: Path) -> bool:
    """Check existing components from root to path without following them."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    if current.is_symlink():
        return True
    for part in relative.parts:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return False
    return False


def _safe_directory(path: Path, project_root: Path) -> bool:
    return (_is_under(path, project_root) and not _path_has_symlink_below(path, project_root)
            and path.is_dir())


def _safe_file(path: Path, project_root: Path) -> bool:
    return (_is_under(path, project_root) and not _path_has_symlink_below(path, project_root)
            and path.is_file())


def _absolute_inside(path: str | Path, project_root: Path, *, relative_to_root: bool) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        if not relative_to_root:
            candidate = Path.cwd() / candidate
        else:
            candidate = project_root / candidate
    candidate = Path(os.path.abspath(candidate))
    if not _is_under(candidate, project_root):
        raise ValueError("path must be within project_root")
    if not _is_under(candidate.resolve(strict=False), project_root):
        raise ValueError("path resolves outside project_root")
    return candidate


def _discover_source_roots(project_root: Path, max_directories: int,
                           gaps: list[DiscoveryGap]) -> tuple[Path, ...]:
    roots = {project_root}
    root_src = project_root / "src"
    if _safe_directory(root_src, project_root):
        roots.add(root_src)
    elif root_src.is_symlink():
        gaps.append(DiscoveryGap(DiscoveryGapKind.SYMLINK,
            "Conventional src source root is a symbolic link and was not scanned.",
            path=str(root_src)))

    frontier: deque[Path] = deque([project_root])
    visited = 0
    while frontier and visited < max_directories:
        directory = frontier.popleft()
        if not _safe_directory(directory, project_root):
            continue
        visited += 1
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            gaps.append(DiscoveryGap(DiscoveryGapKind.FILE_UNAVAILABLE,
                f"Could not inspect directory: {type(exc).__name__}: {exc}", path=str(directory)))
            continue
        names = {item.name for item in entries
                 if not item.is_symlink() and item.is_file()}
        if directory != project_root and names & _PROJECT_MARKERS:
            roots.add(directory)
            child_src = directory / "src"
            if _safe_directory(child_src, project_root):
                roots.add(child_src)
            elif child_src.is_symlink():
                gaps.append(DiscoveryGap(DiscoveryGapKind.SYMLINK,
                    "Nested project src source root is a symbolic link and was not scanned.",
                    path=str(child_src)))
        children = []
        for item in entries:
            if item.name in _EXCLUDED_DISCOVERY_DIRECTORIES:
                continue
            if item.is_symlink():
                gaps.append(DiscoveryGap(DiscoveryGapKind.SYMLINK,
                    "Directory discovery skipped a symbolic link.", path=str(item)))
            elif item.is_dir():
                children.append(item)
        frontier.extend(children)

    if frontier:
        for path in sorted(set(frontier), key=str):
            gaps.append(DiscoveryGap(DiscoveryGapKind.DIRECTORY_BUDGET,
                f"Directory discovery reached max_directories={max_directories}; this subtree was not scanned.",
                path=str(path)))
    return tuple(sorted(roots, key=str))


def _explicit_source_roots(source_roots, project_root: Path,
                           gaps: list[DiscoveryGap]) -> tuple[Path, ...]:
    if isinstance(source_roots, (str, bytes, Path)):
        raise TypeError("source_roots must be an iterable of paths, not one path")
    result = set()
    for item in source_roots:
        candidate = Path(item)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        candidate = Path(os.path.abspath(candidate))
        resolved = candidate.resolve(strict=False)
        if not _is_under(resolved, project_root):
            gaps.append(DiscoveryGap(DiscoveryGapKind.SOURCE_ROOT_INVALID,
                f"Explicit source root {resolved} lies outside project_root and was not read."))
            continue
        if _path_has_symlink_below(candidate.absolute(), project_root):
            gaps.append(DiscoveryGap(DiscoveryGapKind.SYMLINK,
                "Explicit source root traverses a symbolic link and was not read.", path=str(candidate.absolute())))
            continue
        if not resolved.is_dir():
            gaps.append(DiscoveryGap(DiscoveryGapKind.SOURCE_ROOT_INVALID,
                "Explicit source root is not an existing directory.", path=str(resolved)))
            continue
        result.add(resolved)
    return tuple(sorted(result, key=str))


def _root_has_initializer(root: Path) -> bool:
    init = root / "__init__.py"
    return init.is_file() and not init.is_symlink()


def _module_name(path: Path, source_root: Path) -> str | None:
    try:
        relative = path.relative_to(source_root)
    except ValueError:
        return None
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    if _root_has_initializer(source_root):
        parts.insert(0, source_root.name)
    name = ".".join(parts) or source_root.name
    return name


def _module_mappings(path: Path, roots: tuple[Path, ...]) -> tuple[ModuleMapping, ...]:
    mappings = []
    for root in roots:
        name = _module_name(path, root)
        if name is not None:
            mappings.append(ModuleMapping(name, str(root)))
    return tuple(sorted(set(mappings), key=lambda item: (item.source_root, item.name)))


def _module_path_parts(name: str, root: Path) -> tuple[str, ...] | None:
    if not name or any(not part.isidentifier() for part in name.split(".")):
        return None
    parts = tuple(name.split("."))
    if _root_has_initializer(root):
        prefix = root.name
        if name == prefix:
            return ()
        if not name.startswith(prefix + "."):
            return None
        return tuple(name[len(prefix) + 1:].split("."))
    return parts


def _parent_initializers(path: Path, root: Path, project_root: Path,
                         *, namespace: bool, source: SourceReference | None,
                         gaps: list[DiscoveryGap]) -> tuple[str, ...]:
    if namespace:
        target_dir = path
        include_target = False
    elif path.name == "__init__.py":
        target_dir = path.parent
        include_target = False
    else:
        target_dir = path.parent
        include_target = True
    parents = []
    try:
        relative = target_dir.relative_to(root)
        dirs = [root]
        current = root
        for part in relative.parts:
            current = current / part
            dirs.append(current)
        if not include_target and dirs:
            dirs.pop()
        for directory in dirs:
            init = directory / "__init__.py"
            if _path_has_symlink_below(init, project_root):
                gaps.append(DiscoveryGap(DiscoveryGapKind.SYMLINK,
                    "Parent package initializer traverses a symbolic link and was not read.",
                    source=source, path=str(init)))
            elif _safe_file(init, project_root):
                parents.append(str(init))
    except ValueError:
        parents = []
    return tuple(parents)


def _candidate_for_path(name: str, path: Path, root: Path,
                        project_root: Path, role: CandidateRole,
                        *, namespace: bool, source: SourceReference | None,
                        gaps: list[DiscoveryGap]) -> ModuleCandidate:
    parents = _parent_initializers(path, root, project_root, namespace=namespace,
                                   source=source, gaps=gaps)
    return ModuleCandidate(name, str(path), str(root), parents, namespace, role)


def _resolve_module(name: str, root: Path, project_root: Path,
                    role: CandidateRole, source: SourceReference,
                    gaps: list[DiscoveryGap]) -> tuple[ModuleCandidate, ...]:
    parts = _module_path_parts(name, root)
    if parts is None:
        return ()
    candidates: list[ModuleCandidate] = []
    if not parts:
        init = root / "__init__.py"
        if _path_has_symlink_below(init, project_root):
            gaps.append(DiscoveryGap(DiscoveryGapKind.SYMLINK,
                "Module initializer is a symbolic link and was not read.", source=source,
                path=str(init)))
        elif _safe_file(init, project_root):
            candidates.append(_candidate_for_path(name, init, root, project_root, role,
                namespace=False, source=source, gaps=gaps))
        elif _safe_directory(root, project_root):
            candidates.append(_candidate_for_path(name, root, root, project_root, role,
                namespace=True, source=source, gaps=gaps))
    else:
        relative = Path(*parts)
        module_file = root / relative.with_suffix(".py")
        package_dir = root / relative
        package_init = package_dir / "__init__.py"
        if _path_has_symlink_below(module_file, project_root):
            gaps.append(DiscoveryGap(DiscoveryGapKind.SYMLINK,
                "Module source candidate traverses a symbolic link and was not read.",
                source=source, path=str(module_file)))
        elif _safe_file(module_file, project_root):
            candidates.append(_candidate_for_path(name, module_file, root, project_root, role,
                namespace=False, source=source, gaps=gaps))
        if _path_has_symlink_below(package_init, project_root):
            gaps.append(DiscoveryGap(DiscoveryGapKind.SYMLINK,
                "Package initializer candidate traverses a symbolic link and was not read.",
                source=source, path=str(package_init)))
        elif _safe_file(package_init, project_root):
            candidates.append(_candidate_for_path(name, package_init, root, project_root, role,
                namespace=False, source=source, gaps=gaps))
        elif (_safe_directory(package_dir, project_root)
                and not _path_has_symlink_below(package_init, project_root)):
            candidates.append(_candidate_for_path(name, package_dir, root, project_root, role,
                namespace=True, source=source, gaps=gaps))

        # Retain namespace parents explicitly; a child module can exist below
        # a directory without __init__.py, and that is not an ordinary package.
        prefix_parts = parts[:-1]
        for index in range(1, len(prefix_parts) + 1):
            prefix = ".".join(parts[:index])
            parent_dir = root / Path(*parts[:index])
            parent_init = parent_dir / "__init__.py"
            if (_safe_directory(parent_dir, project_root)
                    and not _safe_file(parent_init, project_root)
                    and not _path_has_symlink_below(parent_init, project_root)):
                candidates.append(_candidate_for_path(prefix, parent_dir, root,
                    project_root, CandidateRole.PARENT_NAMESPACE, namespace=True,
                    source=source, gaps=gaps))
    unique = {(item.name, item.path, item.source_root, item.parent_initializers,
               item.namespace, item.role): item for item in candidates}
    return tuple(sorted(unique.values(), key=lambda item:
        (item.name, item.source_root, item.path, item.role.value, item.namespace)))


def _scan_atoms(tree: ast.Module, path: Path, project_root: Path, fingerprint: str):
    refs = {}
    for index, node in enumerate(ast.walk(tree)):
        if isinstance(node, _ATOM_NODE_TYPES) and hasattr(node, "lineno"):
            refs[node] = source_reference(path, project_root, fingerprint, index, node)
    return refs


def _collect_syntax(tree: ast.Module, refs: dict[ast.AST, SourceReference],
                    path: Path, project_root: Path) -> tuple[tuple[_ImportSyntax, ...], tuple[_DynamicSyntax, ...]]:
    importlib_modules = {"importlib": "importlib"}
    import_module_names = {"import_module"}
    find_spec_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib" or alias.name.startswith("importlib."):
                    local_name = alias.asname or alias.name.split(".")[0]
                    imported_module = alias.name if alias.asname else alias.name.split(".")[0]
                    importlib_modules[local_name] = imported_module
        elif isinstance(node, ast.ImportFrom):
            if node.module == "importlib":
                for alias in node.names:
                    if alias.name == "import_module":
                        import_module_names.add(alias.asname or alias.name)
            if node.module == "importlib.util":
                for alias in node.names:
                    if alias.name == "find_spec":
                        find_spec_names.add(alias.asname or alias.name)

    imports: list[_ImportSyntax] = []
    dynamics: list[_DynamicSyntax] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.qualname: list[str] = []
            self.scope_kinds: list[str] = []
            self.deferred = False
            self.controls = []

        @property
        def owner(self):
            return ".".join(self.qualname) if self.qualname else "<module>"

        def push_named_scope(self, name: str):
            local_marker = bool(self.scope_kinds and self.scope_kinds[-1] == "function")
            if local_marker:
                self.qualname.append("<locals>")
            self.qualname.append(name)
            return local_marker

        def pop_named_scope(self, local_marker: bool):
            self.qualname.pop()
            if local_marker:
                self.qualname.pop()

        def visit_Import(self, node: ast.Import):
            for alias in node.names:
                imports.append(_ImportSyntax(node, alias, refs[node], refs[alias], alias.name, 0,
                    None, alias.asname or alias.name.split(".")[0], ImportForm.MODULE,
                    self.owner, self.deferred, tuple(self.controls)))

        def visit_ImportFrom(self, node: ast.ImportFrom):
            for alias in node.names:
                imports.append(_ImportSyntax(node, alias, refs[node], refs[alias], node.module or "",
                    node.level, alias.name, alias.asname or alias.name,
                    ImportForm.FROM, self.owner, self.deferred, tuple(self.controls)))

        def visit_Call(self, node: ast.Call):
            function = node.func
            reason = None
            kind = DiscoveryGapKind.DYNAMIC_IMPORT
            if isinstance(function, ast.Name) and function.id in {"exec", "eval", "compile"}:
                reason = "Potential dynamic execution/compilation syntax; callable binding and loaded source are unverified."
                kind = DiscoveryGapKind.DYNAMIC_EXECUTION
            elif isinstance(function, ast.Name) and function.id == "__import__":
                reason = "Potential dynamic import call by the name __import__; binding and shadowing are unresolved."
            elif isinstance(function, ast.Name) and function.id in import_module_names:
                reason = "importlib.import_module call is not resolved by source discovery."
            elif isinstance(function, ast.Name) and function.id in find_spec_names:
                reason = "find_spec call is a dynamic loader boundary."
            elif isinstance(function, ast.Attribute) and function.attr in {"import_module", "find_spec"}:
                current = function
                chain = []
                while isinstance(current, ast.Attribute):
                    chain.append(current.attr)
                    current = current.value
                if isinstance(current, ast.Name):
                    root_name = current.id
                    imported_root = importlib_modules.get(root_name)
                    dotted = ".".join(reversed(chain))
                    if (function.attr == "import_module" and len(chain) == 1
                            and imported_root == "importlib"):
                        reason = "importlib.import_module call is not resolved by source discovery."
                    elif (function.attr == "find_spec"
                            and imported_root in {"importlib", "importlib.util"}
                            and dotted.endswith(".find_spec")):
                        reason = "find_spec call is a dynamic loader boundary."
            if reason is not None and node in refs:
                dynamics.append(_DynamicSyntax(node, refs[node], self.owner,
                                               self.deferred, reason, kind))
            self.generic_visit(node)

        def _visit_function(self, node):
            # Visit definition expressions under their enclosing lexical owner.
            # Annotation timing varies with Python version and future imports;
            # this traversal records context, not runtime evaluation order.
            for expression in list(node.decorator_list) + list(node.args.defaults):
                self.visit(expression)
            for expression in node.args.kw_defaults:
                if expression is not None:
                    self.visit(expression)
            for argument in (node.args.posonlyargs + node.args.args + node.args.kwonlyargs
                             + [item for item in (node.args.vararg, node.args.kwarg) if item]):
                if argument.annotation is not None:
                    self.visit(argument.annotation)
            if node.returns is not None:
                self.visit(node.returns)
            local_marker = self.push_named_scope(node.name)
            self.scope_kinds.append("function")
            old_deferred = self.deferred
            old_controls, self.controls = self.controls, []
            self.deferred = True
            for statement in node.body:
                self.visit(statement)
            self.deferred = old_deferred
            self.controls = old_controls
            self.scope_kinds.pop()
            self.pop_named_scope(local_marker)

        def visit_FunctionDef(self, node: ast.FunctionDef):
            self._visit_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
            self._visit_function(node)

        def visit_ClassDef(self, node: ast.ClassDef):
            for expression in list(node.decorator_list) + list(node.bases):
                self.visit(expression)
            for keyword in node.keywords:
                self.visit(keyword.value)
            local_marker = self.push_named_scope(node.name)
            self.scope_kinds.append("class")
            for statement in node.body:
                self.visit(statement)
            self.scope_kinds.pop()
            self.pop_named_scope(local_marker)

        def visit_Lambda(self, node: ast.Lambda):
            for expression in list(node.args.defaults):
                self.visit(expression)
            for expression in node.args.kw_defaults:
                if expression is not None:
                    self.visit(expression)
            local_marker = self.push_named_scope("<lambda>")
            self.scope_kinds.append("function")
            old_deferred = self.deferred
            old_controls, self.controls = self.controls, []
            self.deferred = True
            self.visit(node.body)
            self.deferred = old_deferred
            self.controls = old_controls
            self.scope_kinds.pop()
            self.pop_named_scope(local_marker)

        def controlled(self, source, kind, statements, index=0):
            self.controls.append(ImportControlContext(refs[source], kind, index))
            for statement in statements:
                self.visit(statement)
            self.controls.pop()

        def visit_If(self, node):
            self.visit(node.test)
            self.controlled(node, DiscoveryControlKind.IF_TRUE, node.body)
            self.controlled(node, DiscoveryControlKind.IF_FALSE, node.orelse)

        def visit_For(self, node):
            self.visit(node.iter)
            self.visit(node.target)
            self.controlled(node, DiscoveryControlKind.LOOP_BODY, node.body)
            self.controlled(node, DiscoveryControlKind.LOOP_ELSE, node.orelse)

        visit_AsyncFor = visit_For

        def visit_While(self, node):
            self.visit(node.test)
            self.controlled(node, DiscoveryControlKind.LOOP_BODY, node.body)
            self.controlled(node, DiscoveryControlKind.LOOP_ELSE, node.orelse)

        def visit_Try(self, node):
            self.controlled(node, DiscoveryControlKind.TRY_BODY, node.body)
            for index, handler in enumerate(node.handlers):
                self.controlled(handler, DiscoveryControlKind.HANDLER,
                                ([handler.type] if handler.type else []) + handler.body, index)
            self.controlled(node, DiscoveryControlKind.TRY_ELSE, node.orelse)
            self.controlled(node, DiscoveryControlKind.FINALLY, node.finalbody)

        visit_TryStar = visit_Try

        def visit_With(self, node):
            for item in node.items:
                self.visit(item.context_expr)
                if item.optional_vars is not None:
                    self.visit(item.optional_vars)
            self.controlled(node, DiscoveryControlKind.WITH_BODY, node.body)

        visit_AsyncWith = visit_With

        def visit_Match(self, node):
            self.visit(node.subject)
            for index, case in enumerate(node.cases):
                self.controlled(node, DiscoveryControlKind.MATCH_CASE,
                                [case.pattern, *([case.guard] if case.guard else []), *case.body], index)

    Visitor().visit(tree)
    imports.sort(key=lambda item: (item.source.start_line, item.source.start_column,
                                   item.source.atom_id.wire, item.requested,
                                   item.symbol or ""))
    dynamics.sort(key=lambda item: (item.source.start_line, item.source.start_column,
                                    item.source.atom_id.wire))
    return tuple(imports), tuple(dynamics)


def _package_context(module_name: str, source_path: Path) -> str:
    return module_name if source_path.name == "__init__.py" else module_name.rpartition(".")[0]


def _resolve_import_base(syntax: _ImportSyntax, context: _ModuleContext,
                         source_path: Path) -> tuple[str | None, str | None]:
    if syntax.form is ImportForm.MODULE:
        return syntax.requested, None
    if syntax.relative_level == 0:
        return syntax.requested, None
    package = _package_context(context.module_name, source_path)
    parts = package.split(".") if package else []
    if syntax.relative_level > len(parts):
        return None, "relative import ascends above the indexed package boundary"
    ascents = syntax.relative_level - 1
    base = parts[:len(parts) - ascents]
    if syntax.requested:
        base.extend(syntax.requested.split("."))
    return ".".join(base), None


def _read_source(path: Path, remaining_bytes: int) -> tuple[str, str, int]:
    """Read at most the stat-reported file size after checking the byte cap."""
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise OSError("source path is not a regular file")
    if before.st_size > remaining_bytes:
        raise OverflowError("source byte budget reached")
    with path.open("rb") as stream:
        raw = stream.read(before.st_size)
    after = path.stat()
    if before.st_size != after.st_size or len(raw) != before.st_size:
        raise OSError("source changed while it was being read")
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    text = io.TextIOWrapper(io.BytesIO(raw), encoding=encoding).read()
    return text, encoding, len(raw)


def _gap_sort_key(item: DiscoveryGap):
    source = item.source
    if source is None:
        return ("", 0, 0, item.path or "", item.kind.value, item.detail)
    return (source.path, source.start_line, source.start_column,
            item.path or "", item.kind.value, item.detail)


def discover_sources(entry, *, project_root=None, source_roots=(), max_files=128,
                     max_bytes=8_000_000, max_directories=4096) -> SourceDiscovery:
    """Discover local Python imports from an entry file under a fixed boundary.

    All import statements are traversed, including deferred function bodies.
    The result is a lexical candidate closure, not runtime reachability or a
    statement about actual import search order.
    """
    return _discover_sources_from_entries(
        entry, project_root=project_root, source_roots=source_roots,
        max_files=max_files, max_bytes=max_bytes, max_directories=max_directories,
    )


def _discover_sources_from_call_sources(entry, *, source_witnesses,
                                       project_root=None, source_roots=(),
                                       max_files=128, max_bytes=8_000_000,
                                       max_directories=4096, _captured_source_session=None) -> SourceDiscovery:
    """Discover the entry closure before independent replayed call sources.

    The v6 coordinator supplies complete CodeSourceLinks from a replayed D0
    report. Their source hashes are checked again against the same bounded
    read used for discovery. This internal interface has no trust override.
    Unlike the original .py entry interface, witnessed additional source
    filenames need not have a particular suffix.
    """
    return _discover_sources_from_entries(
        entry, project_root=project_root, source_roots=source_roots,
        max_files=max_files, max_bytes=max_bytes, max_directories=max_directories,
        _call_source_witnesses=source_witnesses,
        _captured_source_session=_captured_source_session,
    )


def _call_source_fingerprints(witnesses, root):
    if type(witnesses) is not tuple:
        raise ValueError("source_witnesses must be a tuple of complete verified CodeSourceLinks")
    fingerprints = {}
    for witness in witnesses:
        if type(witness) is not CodeSourceLink:
            raise ValueError("source_witnesses require typed CodeSourceLinks")
        # Validate nested types as well as the outer dataclass. A constructed
        # record is not an escape from the strict source-witness interface.
        witness = decode(CodeSourceLink, encode(witness))
        if (witness.status is not CallLinkStatus.VERIFIED or witness.snapshot is None
                or witness.definition is None or witness.source is None
                or witness.snapshot.path != witness.source.path
                or witness.snapshot.fingerprint != witness.source.fingerprint
                or re.fullmatch(r"pycode-v2:[0-9a-f]{64}", witness.code) is None
                or not witness.optimize_levels
                or any(type(level) is not int or level not in (0, 1, 2)
                       for level in witness.optimize_levels)
                or len(set(witness.optimize_levels)) != len(witness.optimize_levels)):
            raise ValueError("call source witness must have complete verified source/definition evidence")
        raw_path = witness.snapshot.path
        if not Path(raw_path).is_absolute() or os.path.normpath(raw_path) != raw_path:
            raise ValueError("call source witness path must be absolute and normalized")
        path = _absolute_inside(raw_path, root, relative_to_root=False)
        fingerprint = witness.snapshot.fingerprint
        if path in fingerprints and fingerprints[path] != fingerprint:
            raise ValueError("call source witnesses have conflicting fingerprints for one path")
        fingerprints[path] = fingerprint
    return fingerprints


def _discover_sources_from_entries(entry, *, additional_entries=(), project_root=None,
                                  source_roots=(), max_files=128,
                                  max_bytes=8_000_000, max_directories=4096,
                                  _call_source_witnesses=None, _captured_source_session=None) -> SourceDiscovery:
    """Discover one candidate closure with a shared budget and fixed boundary.

    Additional entries are absolute paths selected by an internal evidence
    adapter. Their provenance belongs to that adapter's report; this source
    graph neither fabricates import statements nor establishes runtime source
    correspondence. An empty tuple preserves public discovery's v1 behavior.
    """
    if type(additional_entries) is not tuple or any(
            type(path) is not str or not Path(path).is_absolute()
            for path in additional_entries):
        raise ValueError("additional_entries must be a tuple of absolute path strings")
    if _captured_source_session is not None:
        from scar.analysis.call_seeds import _CapturedSourceSession
        if type(_captured_source_session) is not _CapturedSourceSession:
            raise TypeError("discovery requires a normal live captured source session")
        _captured_source_session.require_unchanged()
    max_files = _positive_limit(max_files, "max_files")
    max_bytes = _positive_limit(max_bytes, "max_bytes")
    max_directories = _positive_limit(max_directories, "max_directories")
    if project_root is None:
        entry_input = Path(entry)
        if not entry_input.is_absolute():
            entry_input = Path.cwd() / entry_input
        entry_input = Path(os.path.abspath(entry_input))
        root = entry_input.parent.resolve(strict=False)
        entry_abs = root / entry_input.name
    else:
        root_input = Path(project_root)
        root = root_input.resolve(strict=False)
        if not root.is_dir():
            raise ValueError("project_root must be an existing directory")
        entry_abs = _absolute_inside(entry, root, relative_to_root=not Path(entry).is_absolute())
    if not root.is_dir():
        raise ValueError("project_root must be an existing directory")
    root = root.resolve(strict=True)
    if not _is_under(entry_abs, root):
        raise ValueError("entry must be within project_root")

    gaps: list[DiscoveryGap] = []
    if entry_abs.suffix != _SOURCE_SUFFIX:
        raise ValueError("entry must be a .py source file")
    if _path_has_symlink_below(entry_abs, root):
        gaps.append(DiscoveryGap(DiscoveryGapKind.SYMLINK,
            "Entry traverses a symbolic link and was not read.", path=str(entry_abs)))

    source_fingerprints = {}
    if _call_source_witnesses is None:
        additional_paths = set()
        for item in additional_entries:
            path = _absolute_inside(item, root, relative_to_root=False)
            if path.suffix != _SOURCE_SUFFIX:
                raise ValueError("additional entry must be a .py source file")
            additional_paths.add(path)
    else:
        if additional_entries:
            raise ValueError("call source witnesses cannot be mixed with legacy additional entries")
        source_fingerprints = _call_source_fingerprints(_call_source_witnesses, root)
        additional_paths = set(source_fingerprints)
    ordered_additional = tuple(sorted(additional_paths, key=str))

    if isinstance(source_roots, (str, bytes, Path)):
        raise ValueError("source_roots must be an iterable of paths, not one path")
    explicit_roots = tuple(source_roots)
    if explicit_roots:
        roots = _explicit_source_roots(explicit_roots, root, gaps)
        root_mode = DiscoveryRootMode.DECLARED
    else:
        roots = _discover_source_roots(root, max_directories, gaps)
        root_mode = DiscoveryRootMode.INFERRED
    for search_root in roots:
        root_init = search_root / "__init__.py"
        if root_init.is_symlink():
            gaps.append(DiscoveryGap(DiscoveryGapKind.SYMLINK,
                "Source-root package initializer is a symbolic link and was not read.",
                path=str(root_init)))

    # The legacy policy queues additional entries before imports. The v6
    # witness policy holds them until the entry closure is exhausted. A file
    # outside selected roots still uses those roots for absolute imports.
    frontier: deque[tuple[Path, SourceReference | None]] = deque([(entry_abs, None)])
    additional_frontier: deque[tuple[Path, SourceReference | None]] = deque(
        (path, None) for path in ordered_additional if path != entry_abs)
    for path in ordered_additional:
        if _path_has_symlink_below(path, root):
            continue
        # Parent initializers are candidates under each selected source-root
        # mapping. A runtime-selected filename does not witness an import or
        # execution of these initializers, so the frontier source stays None.
        for mapping in _module_mappings(path, roots):
            parents = _parent_initializers(
                path, Path(mapping.source_root), root, namespace=False,
                source=None, gaps=gaps)
            additional_frontier.extend((Path(parent), None) for parent in parents)
    if _call_source_witnesses is None:
        frontier.extend(additional_frontier)
        additional_frontier.clear()
    attempted: set[Path] = set()
    attempted_count = 0
    parsed: dict[Path, tuple[str, str, str, ast.Module, dict[ast.AST, SourceReference],
                             tuple[_ImportSyntax, ...], tuple[_DynamicSyntax, ...]]] = {}
    imports: list[ImportDependency] = []
    total_bytes = 0

    while frontier or additional_frontier:
        if not frontier:
            # v6 gives the original entry/import closure the shared budget
            # first. Each later observation root then uses this same import
            # loop; no separate graph or uncharged discovery is introduced.
            frontier.append(additional_frontier.popleft())
        path, trigger_source = frontier.popleft()
        if path in attempted:
            continue
        attempted.add(path)
        if attempted_count >= max_files:
            gaps.append(DiscoveryGap(DiscoveryGapKind.FILE_BUDGET,
                f"File discovery reached max_files={max_files}; this source frontier was not read.",
                source=trigger_source, path=str(path)))
            continue
        attempted_count += 1
        if not _is_under(path, root):
            gaps.append(DiscoveryGap(DiscoveryGapKind.FILE_OUTSIDE_ROOT,
                "Candidate source lies outside project_root and was not read.",
                source=trigger_source, path=str(path)))
            continue
        if _path_has_symlink_below(path, root):
            gaps.append(DiscoveryGap(DiscoveryGapKind.SYMLINK,
                "Candidate source traverses a symbolic link and was not read.",
                source=trigger_source, path=str(path)))
            continue
        captured = (_captured_source_session is not None
                    and _captured_source_session.has_path(path))
        if not captured and not path.is_file():
            gaps.append(DiscoveryGap(DiscoveryGapKind.FILE_UNAVAILABLE,
                "Candidate source file is unavailable.", source=trigger_source, path=str(path)))
            continue
        remaining = max_bytes - total_bytes
        try:
            if captured:
                original = _captured_source_session.archived(path)
                source_size = original.raw_bytes
                if source_size > remaining:
                    raise OverflowError("source byte budget reached")
                total_bytes += source_size
                text, encoding, byte_count = original.text, original.snapshot.encoding, source_size
            else:
                source_size = path.stat().st_size
                if source_size > remaining:
                    raise OverflowError("source byte budget reached")
                total_bytes += source_size
                text, encoding, byte_count = _read_source(path, remaining)
                if _captured_source_session is not None:
                    _captured_source_session.record_static(path, text, encoding, byte_count)
        except OverflowError:
            gaps.append(DiscoveryGap(DiscoveryGapKind.BYTE_BUDGET,
                f"Source discovery reached max_bytes={max_bytes}; this source frontier was not read.",
                source=trigger_source, path=str(path)))
            continue
        except (OSError, UnicodeError, SyntaxError, LookupError) as exc:
            kind = (DiscoveryGapKind.FILE_UNAVAILABLE if captured else
                    DiscoveryGapKind.DECODE_ERROR if isinstance(exc, (UnicodeError, SyntaxError, LookupError))
                    else DiscoveryGapKind.FILE_UNAVAILABLE)
            gaps.append(DiscoveryGap(kind,
                f"Could not read/decode source: {type(exc).__name__}: {exc}",
                source=trigger_source, path=str(path)))
            continue
        fingerprint = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
        if path in source_fingerprints and fingerprint != source_fingerprints[path]:
            raise ValueError("call source witness fingerprint differs from current discovery read: " + str(path))
        try:
            tree = ast.parse(text, filename=str(path), type_comments=True)
        except (SyntaxError, ValueError) as exc:
            gaps.append(DiscoveryGap(DiscoveryGapKind.SYNTAX_ERROR,
                f"Source did not parse: {type(exc).__name__}: {exc}",
                source=trigger_source, path=str(path)))
            continue
        refs = _scan_atoms(tree, path, root, fingerprint)
        syntactic_imports, dynamic_syntax = _collect_syntax(tree, refs, path, root)
        mappings = _module_mappings(path, roots)
        contexts = tuple(_ModuleContext(Path(item.source_root), item.name) for item in mappings)
        if not contexts:
            contexts = (_ModuleContext(root, ""),)

        for dynamic in dynamic_syntax:
            gaps.append(DiscoveryGap(dynamic.kind,
                f"{dynamic.reason} owner={dynamic.owner_qualname}; inside_deferred_body={dynamic.deferred}.",
                source=dynamic.source, path=str(path)))

        for syntax in syntactic_imports:
            # Every source-root mapping of this physical file is a distinct
            # relative-import context; absolute candidates are searched across
            # the full declared/inferred source-root set.
            for context in contexts:
                resolved, relative_error = _resolve_import_base(syntax, context, path)
                candidate_records: list[ModuleCandidate] = []
                status: DiscoveryStatus
                if relative_error is not None:
                    status = DiscoveryStatus.RELATIVE_IMPORT_OVERFLOW
                    gaps.append(DiscoveryGap(DiscoveryGapKind.RELATIVE_IMPORT_OVERFLOW,
                        relative_error, source=syntax.source, path=str(path)))
                else:
                    role = CandidateRole.REQUESTED_MODULE
                    if resolved:
                        for search_root in roots:
                            candidate_records.extend(_resolve_module(resolved, search_root, root,
                                role, syntax.source, gaps))
                    if syntax.form is ImportForm.FROM and syntax.symbol not in (None, "*") and resolved:
                        child_name = f"{resolved}.{syntax.symbol}" if resolved else syntax.symbol
                        for search_root in roots:
                            candidate_records.extend(_resolve_module(child_name, search_root, root,
                                CandidateRole.FROM_SUBMODULE, syntax.source, gaps))
                    candidate_records = list({(item.name, item.path, item.source_root,
                        item.parent_initializers, item.namespace, item.role): item
                        for item in candidate_records}.values())
                    candidate_records.sort(key=lambda item: (item.name, item.source_root,
                        item.path, item.role.value, item.namespace))
                    main_candidates = [item for item in candidate_records
                                       if item.role is not CandidateRole.PARENT_NAMESPACE]
                    module_name_groups: dict[str, set[str]] = {}
                    for item in main_candidates:
                        module_name_groups.setdefault(item.name, set()).add(item.path)
                    duplicate_physical = any(len(paths) > 1 for paths in module_name_groups.values())
                    from_choice = (syntax.form is ImportForm.FROM
                                   and any(item.role is CandidateRole.REQUESTED_MODULE for item in main_candidates)
                                   and any(item.role is CandidateRole.FROM_SUBMODULE for item in main_candidates))
                    if syntax.form is ImportForm.FROM and syntax.symbol == "*":
                        status = DiscoveryStatus.STAR_IMPORT
                        gaps.append(DiscoveryGap(DiscoveryGapKind.STAR_IMPORT,
                            "Star import export set is not statically enumerable here.",
                            source=syntax.source, path=str(path)))
                    elif duplicate_physical or from_choice:
                        status = DiscoveryStatus.AMBIGUOUS
                        gaps.append(DiscoveryGap(DiscoveryGapKind.AMBIGUOUS,
                            "Import has multiple physical/module binding candidates; search order and export lookup are not assumed.",
                            source=syntax.source, path=str(path)))
                    elif main_candidates:
                        status = DiscoveryStatus.LOCAL_CANDIDATE
                    else:
                        status = DiscoveryStatus.EXTERNAL_OR_UNAVAILABLE
                        gaps.append(DiscoveryGap(DiscoveryGapKind.EXTERNAL_OR_UNAVAILABLE,
                            "No matching local Python source candidate was found under the selected source roots.",
                            source=syntax.source, path=str(path)))

                dependency = ImportDependency(
                    source=syntax.source,
                    alias_source=syntax.alias_source,
                    requested=syntax.requested,
                    relative_level=syntax.relative_level,
                    symbol=syntax.symbol,
                    bound_name=syntax.bound_name,
                    owner_qualname=syntax.owner_qualname,
                    deferred=syntax.deferred,
                    candidates=tuple(candidate_records),
                    status=status,
                    source_root=str(context.source_root),
                    importer_module=context.module_name,
                    resolved_module=resolved,
                    form=syntax.form,
                    control_context=syntax.control_context,
                )
                imports.append(dependency)

                # Preserve every candidate edge even when another candidate
                # is ambiguous. Parent initializers are queued before the
                # candidate module body, but imports are never discarded.
                for candidate in candidate_records:
                    for initializer in candidate.parent_initializers:
                        frontier.append((Path(initializer), syntax.source))
                    if not candidate.namespace and Path(candidate.path).suffix == _SOURCE_SUFFIX:
                        frontier.append((Path(candidate.path), syntax.source))

        parsed[path] = (text, encoding, fingerprint, tree, refs,
                        syntactic_imports, dynamic_syntax)

    discovered = []
    for path, (_, encoding, fingerprint, _, _, _, _) in parsed.items():
        mappings = _module_mappings(path, roots)
        discovered.append(DiscoveredFile(
            SourceSnapshot(str(path), fingerprint, encoding=encoding),
            tuple(sorted({item.name for item in mappings})), mappings))
    discovered.sort(key=lambda item: item.snapshot.path)
    imports.sort(key=lambda item: (item.source.path, item.source.start_line,
        item.source.start_column, item.importer_module, item.source_root,
        item.source.atom_id.wire, item.requested, item.symbol or ""))
    # Deduplicate repeated gap reports from the same source/frontier while
    # retaining distinct import edges and their source witnesses.
    gap_by_key = {}
    for gap in gaps:
        key = (gap.kind, gap.detail, gap.path, gap.source)
        gap_by_key[key] = gap
    ordered_gaps = tuple(sorted(gap_by_key.values(), key=_gap_sort_key))
    return SourceDiscovery(str(entry_abs), str(root), tuple(sorted(str(item) for item in roots)),
                           root_mode, tuple(discovered), tuple(imports), ordered_gaps)


__all__ = ["discover_sources"]
