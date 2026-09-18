"""Conservative source-level rewrites selected by explicit graph contracts."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SourceRewrite:
    source: str
    changed: bool
    removed_lines: list[int]
    reason: str


def eliminate_dead_expressions(source: str | Path, lines: set[int], *,
                               closed_world: bool = False,
                               pure_lines: set[int] | None = None) -> SourceRewrite:
    """Remove only discarded call statements under explicit contracts.

    This is intentionally a source transformation, not a claim that a trace
    alone proves dead work. Every selected line must be in ``pure_lines`` and
    ``closed_world`` must be true; otherwise the original source is returned.
    Expressions whose call result is assigned, returned, awaited, yielded or
    embedded in another expression are never removed.
    """
    text = Path(source).read_text() if isinstance(source, Path) else str(source)
    requested = {int(line) for line in lines}
    reviewed = set() if pure_lines is None else {int(line) for line in pure_lines}
    if not closed_world:
        return SourceRewrite(text, False, [], "closed-world contract is required")
    if not requested or not requested.issubset(reviewed):
        return SourceRewrite(text, False, [], "every selected line needs a reviewed pure contract")
    tree = ast.parse(text)
    removed: list[int] = []

    class _Remove(ast.NodeTransformer):
        def visit_Expr(self, node: ast.Expr):
            self.generic_visit(node)
            if (isinstance(node.value, ast.Call) and node.lineno in requested and
                    node.lineno in reviewed):
                removed.append(int(node.lineno))
                return None
            return node

    transformed = _Remove().visit(tree)
    if not removed:
        return SourceRewrite(text, False, [], "no discarded Call matched the selected lines")
    ast.fix_missing_locations(transformed)
    return SourceRewrite(ast.unparse(transformed) + "\n", True, sorted(set(removed)),
                         "dead discarded calls removed under explicit contract")


__all__ = ["SourceRewrite", "eliminate_dead_expressions"]
