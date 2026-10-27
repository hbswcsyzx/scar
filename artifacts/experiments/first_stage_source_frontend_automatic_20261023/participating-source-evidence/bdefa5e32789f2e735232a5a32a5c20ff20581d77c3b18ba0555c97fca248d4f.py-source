"""Static constant provenance facts across Python module boundaries.

This is deliberately a fact collector, not a code rewriter.  It resolves
literal module attributes through local imports without importing or executing
the target program.  A fact such as ``spt.data.dataset_stats.ImageNet`` being
literal is useful evidence, but removing the package still requires an import
side-effect, exception and validation proof.
"""
from __future__ import annotations

import ast
import json
import operator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from scar.ir import Opportunity, ProofStatus, proof


_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_SAFE_SCALARS = (str, int, float, bool, type(None))


def _jsonable(value: Any) -> bool:
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


def _literal(node: ast.AST, env: dict[str, Any]) -> tuple[bool, Any]:
    """Evaluate the small literal subset safe for static provenance."""
    if isinstance(node, ast.Constant) and isinstance(node.value, _SAFE_SCALARS):
        return True, node.value
    if isinstance(node, ast.Name) and node.id in env:
        return True, env[node.id]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values = []
        for item in node.elts:
            known, value = _literal(item, env)
            if not known:
                return False, None
            values.append(value)
        return True, {ast.List: list, ast.Tuple: tuple, ast.Set: set}[type(node)](values)
    if isinstance(node, ast.Dict):
        result: dict[Any, Any] = {}
        for key, value_node in zip(node.keys, node.values):
            if key is None:
                return False, None
            key_known, key_value = _literal(key, env)
            value_known, value = _literal(value_node, env)
            if not key_known or not value_known:
                return False, None
            result[key_value] = value
        return True, result
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        known, value = _literal(node.operand, env)
        if known and isinstance(value, (int, float)):
            return True, _UNARYOPS[type(node.op)](value)
        return False, None
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left_known, left = _literal(node.left, env)
        right_known, right = _literal(node.right, env)
        if left_known and right_known and isinstance(left, (int, float)) and isinstance(right, (int, float)):
            try:
                return True, _BINOPS[type(node.op)](left, right)
            except (ArithmeticError, TypeError):
                return False, None
        return False, None
    # ``dict(mean=[...], std=[...])`` is a common constant declaration and is
    # safe here because only the builtin spelling with literal arguments is
    # accepted.  Arbitrary calls are never executed by this analyzer.
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
        if node.args:
            return False, None
        result: dict[str, Any] = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                return False, None
            known, value = _literal(keyword.value, env)
            if not known:
                return False, None
            result[keyword.arg] = value
        return True, result
    return False, None


def _module_name(path: Path, root: Path) -> str:
    """Derive a best-effort import name without assuming one repository layout."""
    path = path.resolve()
    root = root.resolve()
    if path.name == "__init__.py":
        directory = path.parent
        suffix = directory.name
    else:
        directory = path.parent
        suffix = path.stem
    package_parts = [suffix] if suffix != "__init__" else []
    current = directory if path.name != "__init__.py" else directory.parent
    while (current / "__init__.py").is_file():
        package_parts.append(current.name)
        current = current.parent
    if package_parts and current != root:
        # A project can contain multiple distributions under a monorepo
        # directory (for example stable-pretraining/stable_pretraining).  The
        # first package marker is the import root; do not include a hyphenated
        # distribution directory in the import name.
        package_parts = package_parts
    elif not package_parts:
        package_parts = [path.stem]
    return ".".join(reversed(package_parts))


@dataclass(slots=True)
class ConstantDefinition:
    module: str
    name: str
    source: str
    line: int
    value: Any
    dependencies: tuple[str, ...] = ()

    @property
    def qualified_name(self) -> str:
        return f"{self.module}.{self.name}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "source": self.source,
            "line": self.line,
            "value": self.value,
            "dependencies": list(self.dependencies),
            "evidence": "Inferred literal source",
        }


@dataclass(slots=True)
class ModuleEffectSummary:
    """Top-level initialization facts for one locally indexed module."""

    module: str
    source: str | None
    status: str
    effects: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "source": self.source,
            "status": self.status,
            "effects": [dict(item) for item in self.effects],
            "evidence": "Inferred top-level source scan",
        }


@dataclass(slots=True)
class ConstantUse:
    source: str
    line: int
    expression: str
    local_name: str
    definition: ConstantDefinition
    import_module: str
    import_line: int
    dependency_chain: tuple[str, ...] = ()
    module_effects: tuple[ModuleEffectSummary, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "line": self.line,
            "expression": self.expression,
            "local_name": self.local_name,
            "definition": self.definition.as_dict(),
            "import_module": self.import_module,
            "import_line": self.import_line,
            "dependency_chain": list(self.dependency_chain),
            "module_effects": [item.as_dict() for item in self.module_effects],
            "metadata": self.metadata,
            "evidence": "Inferred literal provenance",
        }


def _all_sources(root: Path) -> list[Path]:
    return sorted(path.resolve() for path in root.rglob("*.py")
                  if path.is_file() and ".git" not in path.parts
                  and "__pycache__" not in path.parts)


def _index_definitions(root: Path) -> dict[str, ConstantDefinition]:
    definitions: dict[str, ConstantDefinition] = {}
    for path in _all_sources(root):
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except (OSError, UnicodeError, SyntaxError):
            continue
        module = _module_name(path, root)
        env: dict[str, Any] = {}
        statements = tree.body if isinstance(tree, ast.Module) else []
        for statement in statements:
            targets: list[str] = []
            value_node: ast.AST | None = None
            if isinstance(statement, ast.Assign):
                targets = [item.id for item in statement.targets if isinstance(item, ast.Name)]
                value_node = statement.value
            elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                targets = [statement.target.id]
                value_node = statement.value
            if not targets or value_node is None:
                continue
            known, value = _literal(value_node, env)
            if not known or not _jsonable(value):
                continue
            for name in targets:
                env[name] = value
                definitions[f"{module}.{name}"] = ConstantDefinition(
                    module=module, name=name, source=str(path),
                    line=int(getattr(statement, "lineno", 1) or 1), value=value,
                )
    return definitions


def _module_sources(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in _all_sources(root):
        result.setdefault(_module_name(path, root), path)
    return result


def _effect_item(kind: str, node: ast.AST, source: str, *, status: str = "UNKNOWN") -> dict[str, Any]:
    try:
        text = ast.unparse(node)
    except (AttributeError, ValueError):
        text = type(node).__name__
    return {"kind": kind, "line": int(getattr(node, "lineno", 1) or 1),
            "source": source, "text": text, "status": status}


def _module_effect_summary(module: str, source: Path | None) -> ModuleEffectSummary:
    if source is None:
        return ModuleEffectSummary(module, None, "UNKNOWN", (
            {"kind": "module_source_missing", "status": "UNKNOWN"},))
    try:
        tree = ast.parse(source.read_text(), filename=str(source))
    except (OSError, UnicodeError, SyntaxError):
        return ModuleEffectSummary(module, str(source), "UNKNOWN", (
            {"kind": "module_parse_failed", "status": "UNKNOWN"},))
    effects: list[dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            effects.append(_effect_item("import", node, str(source)))
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # A plain definition does not execute the body during import, but
            # decorators and default expressions do execute at module import.
            if node.decorator_list or getattr(node, "args", None) and (
                    node.args.defaults or node.args.kw_defaults):
                effects.append(_effect_item("definition_initialization", node, str(source)))
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value if isinstance(node, ast.AnnAssign) else node.value
            known, _ = _literal(value, {}) if value is not None else (False, None)
            has_attribute_target = any(isinstance(target, (ast.Attribute, ast.Subscript))
                                       for target in (
                                           [node.target] if isinstance(node, ast.AnnAssign)
                                           else node.targets))
            if has_attribute_target:
                effects.append(_effect_item("state_or_external_write", node, str(source)))
            elif not known:
                effects.append(_effect_item("dynamic_assignment", node, str(source)))
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            effects.append(_effect_item("top_level_call", node, str(source)))
            continue
        if isinstance(node, (ast.If, ast.Try, ast.For, ast.AsyncFor, ast.While,
                             ast.With, ast.AsyncWith, ast.Match)):
            effects.append(_effect_item("dynamic_top_level_control", node, str(source)))
            continue
        effects.append(_effect_item("opaque_top_level_statement", node, str(source)))
    return ModuleEffectSummary(
        module=module, source=str(source),
        status="PROVEN_PURE" if not effects else "UNKNOWN",
        effects=tuple(effects),
    )


def _effects_for_use(use: ConstantUse, module_sources: dict[str, Path]) -> tuple[ModuleEffectSummary, ...]:
    modules: list[str] = []
    # Include package parents because importing a.b.c executes a, a.b and
    # a.b.c initializers in order.
    parts = use.import_module.split(".")
    for size in range(1, len(parts) + 1):
        modules.append(".".join(parts[:size]))
    definition_parts = use.definition.module.split(".")
    for size in range(1, len(definition_parts) + 1):
        modules.append(".".join(definition_parts[:size]))
    return tuple(_module_effect_summary(module, module_sources.get(module))
                 for module in dict.fromkeys(modules))


def _attribute_parts(node: ast.AST) -> list[str] | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return list(reversed(parts))


def _imports(tree: ast.AST) -> tuple[dict[str, tuple[str, int]], dict[str, tuple[str, int]]]:
    aliases: dict[str, tuple[str, int]] = {}
    imported_names: dict[str, tuple[str, int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                local = item.asname or item.name.split(".")[0]
                aliases[local] = (item.name, int(getattr(node, "lineno", 1) or 1))
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                if item.name == "*":
                    continue
                local = item.asname or item.name
                imported_names[local] = (
                    f"{node.module}.{item.name}", int(getattr(node, "lineno", 1) or 1))
    return aliases, imported_names


def _resolve_definition(parts: list[str], definitions: dict[str, ConstantDefinition]) -> tuple[ConstantDefinition, str] | None:
    for split in range(len(parts), 0, -1):
        key = ".".join(parts[:split])
        definition = definitions.get(key)
        if definition is not None and split == len(parts):
            return definition, key
        module = ".".join(parts[:split])
        name = ".".join(parts[split:])
        definition = definitions.get(f"{module}.{name}") if name else None
        if definition is not None:
            return definition, f"{module}.{name}"
    return None


def find_constant_uses(source: str | Path, *, project_root: str | Path | None = None) -> list[ConstantUse]:
    """Find local-import attribute uses whose source is a literal definition."""
    source_path = Path(source).resolve()
    root = Path(project_root).resolve() if project_root else source_path.parent
    definitions = _index_definitions(root)
    try:
        tree = ast.parse(source_path.read_text(), filename=str(source_path))
    except (OSError, UnicodeError, SyntaxError):
        return []
    aliases, imported_names = _imports(tree)
    uses: list[ConstantUse] = []
    seen: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        parts = _attribute_parts(node)
        if not parts or parts[0] not in aliases:
            continue
        module, import_line = aliases[parts[0]]
        resolved = _resolve_definition(module.split(".") + parts[1:], definitions)
        if resolved is None:
            continue
        definition, _ = resolved
        key = (int(getattr(node, "lineno", 1) or 1), definition.qualified_name)
        if key in seen:
            continue
        seen.add(key)
        uses.append(ConstantUse(
            source=str(source_path), line=key[0],
            expression=ast.unparse(node), local_name=parts[0],
            definition=definition, import_module=module, import_line=import_line,
            dependency_chain=(module, definition.qualified_name),
        ))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or node.id not in imported_names:
            continue
        module_attr, import_line = imported_names[node.id]
        definition = definitions.get(module_attr)
        if definition is None:
            continue
        key = (int(getattr(node, "lineno", 1) or 1), definition.qualified_name)
        if key in seen:
            continue
        seen.add(key)
        uses.append(ConstantUse(
            source=str(source_path), line=key[0], expression=node.id,
            local_name=node.id, definition=definition,
            import_module=module_attr.rsplit(".", 1)[0], import_line=import_line,
            dependency_chain=(module_attr, definition.qualified_name),
        ))
    module_sources = _module_sources(root)
    for use in uses:
        use.module_effects = _effects_for_use(use, module_sources)
    return sorted(uses, key=lambda item: (item.line, item.expression))


def constant_candidates(uses: Iterable[ConstantUse]) -> list[Opportunity]:
    """Turn constant facts into guarded, report-only optimization hypotheses."""
    result: list[Opportunity] = []
    for index, use in enumerate(uses):
        source_id = f"{use.source}:{use.line}:{use.definition.qualified_name}"
        effect_status = ("PROVEN" if use.module_effects and
                         all(item.status == "PROVEN_PURE" for item in use.module_effects)
                         else "UNKNOWN")
        effect_reason = ("all indexed module initializers are syntactically literal"
                         if effect_status == "PROVEN" else
                         "one or more imported module initializers contain calls, imports, "
                         "dynamic control or state writes")
        result.append(Opportunity(
            kind="ConstantProvenanceCandidate", code_id=source_id,
            evidence="Inferred", applicability="literal_imported_value",
            guard=("module import side effects, dynamic attribute hooks, exceptions, "
                   "reload/monkey-patching, and visible initialization order must be proven"),
            reason=(f"{use.expression} resolves to literal {use.definition.qualified_name}; "
                    "the value may be inlinable at this use"),
            supporting_events=[], decision="rejected",
            rejection_reason="constant value is proven, but package initialization/effect equivalence is not",
            proof_obligations=[
                proof("literal_value", "applicability",
                      "the referenced definition is made only from static literals",
                      ProofStatus.PROVEN, evidence="Inferred",
                      reason=f"resolved {use.definition.qualified_name}",
                      details={"value": use.definition.value,
                               "source": use.definition.source,
                               "line": use.definition.line}),
                proof("import_effects_preserved", "legality",
                      "removing the package import preserves initialization and external effects",
                      ProofStatus.PROVEN if effect_status == "PROVEN" else ProofStatus.UNKNOWN,
                      evidence="Inferred" if effect_status == "PROVEN" else "UNKNOWN",
                      reason=effect_reason,
                      details={"module_effects": [item.as_dict() for item in use.module_effects]}),
                proof("replacement_validated", "legality",
                      "the inlined value preserves the complete program result and visible state",
                      ProofStatus.UNKNOWN, evidence="UNKNOWN",
                      reason="no transformed execution has been validated"),
            ],
        ))
    return result


def constant_report(source: str | Path, *, project_root: str | Path | None = None) -> dict[str, Any]:
    uses = find_constant_uses(source, project_root=project_root)
    candidates = constant_candidates(uses)
    return {
        "schema": "scar.constant_provenance",
        "schema_version": 1,
        "source": str(Path(source).resolve()),
        "uses": [item.as_dict() for item in uses],
        "candidates": [item.as_dict() for item in candidates],
        "counts": {"uses": len(uses), "candidates": len(candidates)},
    }


__all__ = ["ConstantDefinition", "ConstantUse", "ModuleEffectSummary", "find_constant_uses",
           "constant_candidates", "constant_report"]
