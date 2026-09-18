"""Conservative AST-to-graph model for arbitrary Python source files."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

from .graph import GraphNode, NodeKind, ProgramGraph
from .cfg import add_static_cfg
from .ids import CodeID, _hash


def _labels(node: ast.AST) -> tuple[NodeKind, list[str]]:
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return NodeKind.CONTROL, ["CTRL", "IO", "ORDER"]
    if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Match,
                         ast.Try, ast.Break, ast.Continue, ast.Pass)):
        return NodeKind.CONTROL, ["CTRL"]
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return NodeKind.CONTROL, ["CTRL", "IO"]
    if isinstance(node, (ast.Raise, ast.Assert)):
        return NodeKind.CONTRACT, ["CTRL", "OPAQUE"]
    if isinstance(node, (ast.Await, ast.Yield, ast.YieldFrom)):
        return NodeKind.ACTION, ["CTRL", "ORDER", "OPAQUE"]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                         ast.Lambda)):
        return NodeKind.CONTROL, ["CTRL", "VAL"]
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
        return NodeKind.STATE, ["STATE", "VAL"]
    if isinstance(node, ast.Call):
        return NodeKind.ACTION, ["CTRL", "VAL", "OPAQUE"]
    if isinstance(node, (ast.AugLoad, ast.AugStore, ast.Delete)):
        return NodeKind.STATE, ["STATE", "VAL"]
    if isinstance(node, (ast.Attribute, ast.Subscript)):
        # Attribute and subscript operations may be user-defined and may
        # allocate a view/copy; preserve both the state access and the
        # possible representation change until runtime evidence refines it.
        return NodeKind.STATE, ["STATE", "REP", "OPAQUE"]
    if isinstance(node, (ast.BinOp, ast.BoolOp, ast.UnaryOp, ast.Compare,
                         ast.IfExp, ast.NamedExpr, ast.JoinedStr,
                         ast.FormattedValue)):
        return NodeKind.ACTION, ["VAL"]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict,
                         ast.ListComp, ast.SetComp, ast.DictComp,
                         ast.GeneratorExp)):
        return NodeKind.ACTION, ["VAL", "MEM"]
    if isinstance(node, (ast.Constant, ast.Name)):
        return NodeKind.STATE if isinstance(node, ast.Name) else NodeKind.ACTION, ["STATE"] if isinstance(node, ast.Name) else ["VAL"]
    if isinstance(node, ast.Return):
        return NodeKind.CONTROL, ["CTRL", "STATE"]
    return NodeKind.OPAQUE, ["OPAQUE"]


# These are syntax-level hints, not claims about the implementation of a
# method.  A user function named ``to`` can have arbitrary effects, and a
# same-device ``Tensor.to`` may not copy anything.  Runtime dispatch and
# profiler evidence must refine or reject these labels before a backend uses
# them.
_TRANSFER_CALLS = {
    "to", "cuda", "cpu", "xpu", "mps", "copy", "copy_", "move",
    "pin_memory", "send", "recv",
}
_MEMORY_CALLS = {
    "empty", "empty_like", "empty_strided", "zeros", "zeros_like", "ones",
    "ones_like", "full", "full_like", "new_empty", "new_zeros", "new_ones",
    "clone", "detach", "allocate", "alloc", "free", "release",
}
_REPRESENTATION_CALLS = {
    "reshape", "view", "view_as", "expand", "flatten", "squeeze", "unsqueeze",
    "permute", "transpose", "t", "contiguous", "as_strided", "cast", "type",
    "to_dtype", "astype", "deserialize", "serialize", "encode", "decode",
}
_ORDERING_CALLS = {
    "synchronize", "sync", "wait", "barrier", "join", "event_wait", "wait_event",
}
_IO_CALLS = {
    "open", "read", "read_text", "read_bytes", "write", "write_text", "write_bytes",
    "save", "load", "dump", "dumps", "log", "print", "flush", "unlink",
}
_STATE_CALLS = {
    "manual_seed", "seed", "set_rng_state", "get_rng_state", "setdefault",
    "update", "append", "extend", "insert", "pop", "clear", "setattr",
}


def _call_name(node: ast.Call) -> str | None:
    callee = node.func
    if isinstance(callee, ast.Name):
        return callee.id
    if isinstance(callee, ast.Attribute):
        return callee.attr
    return None


def _call_labels(node: ast.Call) -> tuple[NodeKind, list[str]]:
    """Classify a call with conservative multi-label syntax hints."""
    name = _call_name(node)
    lowered = name.lower() if name else ""
    labels = ["CTRL"]
    if lowered in _TRANSFER_CALLS:
        labels.append("XFER")
        # A transfer commonly also changes representation.  This is still a
        # syntax hint: same-device ``to`` may return its input unchanged.
        if lowered in {"to", "cuda", "cpu", "xpu", "mps", "copy", "copy_", "move"}:
            labels.append("REP")
    if lowered in _MEMORY_CALLS:
        labels.extend(["MEM", "VAL"])
    if lowered in _REPRESENTATION_CALLS:
        labels.extend(["REP", "VAL"])
    if lowered in _ORDERING_CALLS:
        labels.append("ORDER")
    if lowered in _IO_CALLS:
        labels.append("IO")
        if lowered in {"save", "load", "dump", "dumps"}:
            labels.append("REP")
    if lowered in _STATE_CALLS:
        labels.append("STATE")
    if len(labels) == 1:
        labels.append("VAL")
    labels.append("OPAQUE")
    return NodeKind.ACTION, list(dict.fromkeys(labels))


def from_source(path: str | Path) -> ProgramGraph:
    """Model every physical source line and AST statement.

    A line with no AST statement (comments/blank lines) is represented as an
    opaque source node so coverage is explicit instead of silently omitted.
    """
    path = Path(path).resolve()
    text = path.read_text()
    source_version = "source-sha256:" + _hash(text)
    tree = ast.parse(text, filename=str(path))
    graph = ProgramGraph()
    module_id = CodeID(str(path), "module", version=source_version).key()
    graph.add_node(GraphNode(
        module_id, NodeKind.CONTROL, "module", str(path), None,
        ["CTRL", "IO", "OPAQUE"], {
            "source_version": source_version,
            "label_provenance": "static_syntax",
            "label_status": "Inferred",
            "labels_are_hints": True,
            "label_evidence": "Observed source file",
        }))
    by_line: dict[int, str] = {}
    ast_nodes: dict[int, str] = {}
    ast_items = list(ast.walk(tree))
    parents: dict[int, ast.AST] = {}
    for parent in ast_items:
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent

    def definition_qualname(node: ast.AST) -> str:
        names = [getattr(node, "name", "<anonymous>")]
        current = parents.get(id(node))
        while current is not None:
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(getattr(current, "name", "<anonymous>"))
            current = parents.get(id(current))
        return ".".join(reversed(names))

    for ordinal, node in enumerate(ast_items):
        if not hasattr(node, "lineno"):
            continue
        line = int(node.lineno)
        kind, labels = _call_labels(node) if isinstance(node, ast.Call) else _labels(node)
        # The ordinal is required because a line may contain several AST
        # nodes of the same type (for example nested calls).  A line number
        # alone is not a stable or injective program identity.
        node_id = CodeID(str(path), f"ast:{type(node).__name__}:{ordinal}",
                         line, getattr(node, "col_offset", None), source_version).key()
        # Static labels are a hypothesis layer, not a runtime effect summary.
        # Keep that distinction in the serialized node so a consumer cannot
        # mistake a ``.to``/``clone`` hint for a physical copy or allocation.
        # Dynamic nodes carry their own observed evidence in
        # ``ProgramGraph.merge_execution``.
        attrs = {"source_text": text.splitlines()[line - 1].strip(),
                 "source_version": source_version,
                 "label_provenance": "static_syntax",
                 "label_status": "Inferred",
                 "labels_are_hints": True,
                 "label_evidence": "Inferred syntax" if isinstance(node, ast.Call)
                 else "Observed source syntax"}
        if isinstance(node, ast.Import):
            attrs["imports"] = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            attrs["import_module"] = node.module
            attrs["import_level"] = int(node.level)
            attrs["import_names"] = [alias.name for alias in node.names]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            attrs.update({"qualname": definition_qualname(node),
                          "span_start": line,
                          "span_end": int(getattr(node, "end_lineno", line) or line),
                          "span_evidence": "Observed source syntax"})
        graph.add_node(GraphNode(node_id, kind, type(node).__name__, str(path), line,
                                 labels, attrs))
        ast_nodes[id(node)] = node_id
        by_line.setdefault(line, node_id)
        if isinstance(parents.get(id(node)), ast.Module):
            graph.add_edge(module_id, node_id, "module_contains",
                           evidence="Inferred", source_version=source_version)
    # Preserve syntax and nesting dependencies in addition to source order.
    # Analysis can use these edges to distinguish a call nested in a branch
    # from an unrelated call that happens to share a line range.
    for parent in ast_items:
        parent_id = ast_nodes.get(id(parent))
        if parent_id is None:
            continue
        for child in ast.iter_child_nodes(parent):
            child_id = ast_nodes.get(id(child))
            if child_id is not None:
                graph.add_edge(parent_id, child_id, "ast_contains")
    for line_no in range(1, len(text.splitlines()) + 1):
        if line_no not in by_line:
            node_id = CodeID(str(path), "OpaqueLine", line_no,
                             version=source_version).key()
            graph.add_node(GraphNode(node_id, NodeKind.OPAQUE, "source_line", str(path),
                                     line_no, ["OPAQUE"], {
                                         "source_text": text.splitlines()[line_no - 1],
                                         "source_version": source_version,
                                         "label_provenance": "static_syntax",
                                         "label_status": "Inferred",
                                         "labels_are_hints": True,
                                         "label_evidence": "Observed source syntax",
                                     }))
            by_line[line_no] = node_id
            graph.add_edge(module_id, node_id, "module_contains",
                           evidence="Inferred", source_version=source_version)
    ordered = [by_line[i] for i in sorted(by_line)]
    for a, b in zip(ordered, ordered[1:]):
        graph.add_edge(a, b, "source_order")

    # Add a conservative data-flow view.  This is deliberately based on
    # syntax, not on guessed runtime values: a Name in load context reads a
    # state slot and a Name in store/delete context writes it.  The slot is
    # namespaced by the nearest lexical definition so unrelated local
    # variables do not alias merely because they share a spelling.  These
    # edges are evidence for later passes; they are not proof that a write is
    # the only alias or that a call has no hidden effects.
    class _Dependencies(ast.NodeVisitor):
        def __init__(self):
            self.scope = [str(path), source_version]
            self.controls: list[str] = []

        def _state(self, name: str) -> str:
            scope = "/".join(self.scope)
            state_id = f"static_state:{scope}:{name}"
            graph.add_node(GraphNode(state_id, NodeKind.STATE, "variable",
                                     str(path), None, ["STATE"],
                                     {"name": name, "scope": scope,
                                      "evidence": "Inferred syntax",
                                      "label_provenance": "static_dataflow",
                                      "label_status": "Inferred",
                                      "labels_are_hints": True}))
            return state_id

        def _visit_children(self, node, control: str | None = None):
            if control is not None:
                self.controls.append(control)
            for child in ast.iter_child_nodes(node):
                self.visit(child)
            if control is not None:
                self.controls.pop()

        def visit_Name(self, node: ast.Name):
            node_id = ast_nodes.get(id(node))
            if node_id is None:
                return
            state_id = self._state(node.id)
            relation = "writes" if isinstance(node.ctx, (ast.Store, ast.Del)) else "reads"
            graph.add_edge(state_id if relation == "reads" else node_id,
                           node_id if relation == "reads" else state_id,
                           relation, context=type(node.ctx).__name__)
            for control_id in self.controls:
                if control_id != node_id:
                    graph.add_edge(control_id, node_id, "control_depends")

        def visit_FunctionDef(self, node: ast.FunctionDef):
            node_id = ast_nodes.get(id(node))
            if node_id is None:
                return
            self.scope.append(f"function:{node.name}:{node.lineno}")
            # Arguments and body belong to the new lexical scope.  The
            # definition itself remains in its parent scope.
            for child in ast.iter_child_nodes(node):
                self.visit(child)
            self.scope.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node: ast.ClassDef):
            self.scope.append(f"class:{node.name}:{node.lineno}")
            for child in ast.iter_child_nodes(node):
                self.visit(child)
            self.scope.pop()

        def visit_If(self, node: ast.If):
            node_id = ast_nodes.get(id(node))
            if node_id is None:
                return
            self.visit(node.test)
            self._visit_children(ast.Module(body=node.body, type_ignores=[]), node_id)
            self._visit_children(ast.Module(body=node.orelse, type_ignores=[]), node_id)

        def visit_For(self, node: ast.For):
            node_id = ast_nodes.get(id(node))
            if node_id is None:
                return
            # The induction target is assigned once per iteration by the
            # loop machinery, even though it is syntactically outside the
            # body. Mark its Name nodes as controlled by the loop so static
            # invariant analysis cannot mistake ``i`` for an invariant input.
            for target_node in ast.walk(node.target):
                target_id = ast_nodes.get(id(target_node))
                if target_id is not None:
                    graph.add_edge(node_id, target_id, "control_depends",
                                   implicit_write=True)
            self.visit(node.target); self.visit(node.iter)
            self._visit_children(ast.Module(body=node.body, type_ignores=[]), node_id)
            self._visit_children(ast.Module(body=node.orelse, type_ignores=[]), node_id)

        visit_AsyncFor = visit_For

        def visit_While(self, node: ast.While):
            node_id = ast_nodes.get(id(node))
            if node_id is None:
                return
            self.visit(node.test)
            self._visit_children(ast.Module(body=node.body, type_ignores=[]), node_id)
            self._visit_children(ast.Module(body=node.orelse, type_ignores=[]), node_id)

        def generic_visit(self, node):
            node_id = ast_nodes.get(id(node))
            for control_id in self.controls:
                if node_id is not None and control_id != node_id:
                    graph.add_edge(control_id, node_id, "control_depends")
            super().generic_visit(node)

    _Dependencies().visit(tree)
    add_static_cfg(graph, tree, ast_nodes)
    return graph


_PROJECT_EXCLUDED_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "build", "dist",
})


def _python_sources(root: Path) -> list[Path]:
    """Return deterministic project sources without following build/cache trees."""
    sources: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in _PROJECT_EXCLUDED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file():
            sources.append(path.resolve())
    return sorted(set(sources))


def _module_name(path: Path, root: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_import(name: str, current: str, level: int,
                    *, current_is_package: bool = False) -> list[str]:
    """Resolve a static import to possible dotted module names.

    This is intentionally a name-to-file hypothesis.  Python import hooks,
    namespace packages and dynamic imports can invalidate it; callers must
    keep the edge's ``Inferred`` provenance and refine it at runtime.
    """
    if level <= 0:
        return [name] if name else []
    # ``current`` is the module name of the importing file.  An ``__init__.py``
    # file names the package itself, while a normal module names a child of
    # that package.  Treating both forms as ``current.split('.')[:-1]`` loses
    # the package for ``pkg/__init__.py: from .worker import ...``.
    package = (current.split(".") if current_is_package
               else current.split(".")[:-1])
    if level > 1:
        package = package[:max(0, len(package) - level + 1)]
    prefix = ".".join(package)
    return [".".join(part for part in (prefix, name) if part)]


def from_project(path: str | Path) -> ProgramGraph:
    """Build one static graph for a Python file or source project.

    A directory is traversed recursively in deterministic order.  Each file
    contributes its own physical-line/AST/data-flow graph and module node;
    statically resolvable imports add ``imports`` edges between module nodes.
    Import resolution is only a syntax hint: dynamic import hooks and package
    execution are not claimed to be represented.
    """
    root = Path(path).resolve()
    if root.is_file():
        return from_source(root)
    if not root.is_dir():
        raise FileNotFoundError(root)
    sources = _python_sources(root)
    graph = ProgramGraph()
    module_nodes: dict[str, str] = {}
    source_modules: dict[str, str] = {}
    source_is_package: dict[str, bool] = {}
    for source in sources:
        child = from_source(source)
        graph.merge_graph(child)
        module_name = _module_name(source, root)
        module_id = CodeID(str(source), "module", version=child.nodes[
            next(node_id for node_id, node in child.nodes.items()
                 if node.label == "module")].attrs["source_version"]).key()
        module_nodes[module_name] = module_id
        source_modules[str(source)] = module_name
        source_is_package[str(source)] = source.name == "__init__.py"

    # Link imports only after every module has been indexed.  The target may
    # be a package or a module prefix; choose an exact module first and then
    # the longest known prefix.  Unresolved imports remain represented by the
    # Import action and are deliberately not converted to a false edge.
    for node in list(graph.nodes.values()):
        if node.label not in {"Import", "ImportFrom"} or node.source is None:
            continue
        importer_id = module_nodes.get(source_modules.get(node.source, ""))
        if importer_id is None:
            continue
        names: Iterable[str]
        if node.label == "Import":
            names = node.attrs.get("imports", [])
            level = 0
        else:
            module = node.attrs.get("import_module") or ""
            names = [module]
            level = int(node.attrs.get("import_level", 0))
        for name in names:
            candidates = _resolve_import(
                str(name), source_modules[node.source], level,
                current_is_package=source_is_package.get(node.source, False))
            target_name = next((candidate for candidate in candidates
                                if candidate in module_nodes), None)
            if target_name is None and node.label == "Import":
                # ``import package.submodule`` may resolve to a package node
                # even when the imported suffix is not a local file.
                pieces = str(name).split(".")
                for end in range(len(pieces), 0, -1):
                    candidate = ".".join(pieces[:end])
                    if candidate in module_nodes:
                        target_name = candidate
                        break
            if target_name is not None:
                graph.add_edge(importer_id, module_nodes[target_name], "imports",
                               evidence="Inferred", import_name=str(name),
                               import_level=level)
    return graph


__all__ = ["from_source", "from_project"]
