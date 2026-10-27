"""Conservative static control-flow graph construction for Python ASTs."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field

from .graph import GraphNode, NodeKind, ProgramGraph


@dataclass
class _Flow:
    entry: str | None = None
    exits: list[tuple[str, str]] = field(default_factory=list)
    breaks: list[str] = field(default_factory=list)
    continues: list[str] = field(default_factory=list)


class _CFGBuilder:
    def __init__(self, graph: ProgramGraph, ast_nodes: dict[int, str]):
        self.graph = graph
        self.ast_nodes = ast_nodes

    def node(self, value: ast.AST) -> str | None:
        return self.ast_nodes.get(id(value))

    def edge(self, source: str | None, target: str | None, relation: str, **attrs):
        if source is not None and target is not None:
            self.graph.add_edge(source, target, relation, evidence="Inferred", **attrs)

    def block(self, statements: list[ast.stmt], loop_header: str | None = None) -> _Flow:
        flow = _Flow()
        for statement in statements:
            current = self.statement(statement, loop_header)
            if current.entry is None:
                continue
            if flow.entry is None:
                flow.entry = current.entry
            else:
                for source, relation in flow.exits:
                    self.edge(source, current.entry, relation)
                # A continue only has a target inside a loop. If it escaped
                # this block, retain it as an unresolved control fact rather
                # than pretending it is a normal fall-through edge.
            flow.exits = list(current.exits)
            flow.breaks.extend(current.breaks)
            flow.continues.extend(current.continues)
        return flow

    def statement(self, statement: ast.stmt, loop_header: str | None) -> _Flow:
        node = self.node(statement)
        if node is None:
            return _Flow()

        if isinstance(statement, (ast.Break,)):
            return _Flow(entry=node, breaks=[node])
        if isinstance(statement, (ast.Continue,)):
            if loop_header is not None:
                self.edge(node, loop_header, "cfg_continue")
                return _Flow(entry=node)
            return _Flow(entry=node, continues=[node])
        if isinstance(statement, (ast.Return, ast.Raise)):
            return _Flow(entry=node)

        if isinstance(statement, ast.If):
            body = self.block(statement.body, loop_header)
            orelse = self.block(statement.orelse, loop_header)
            self.edge(node, body.entry, "cfg_true")
            if orelse.entry is not None:
                self.edge(node, orelse.entry, "cfg_false")
            true_exits = body.exits or ([(body.entry, "cfg_join")] if body.entry else [])
            false_exits = (orelse.exits or ([(orelse.entry, "cfg_join")] if orelse.entry else []))
            exits = [(source, "cfg_join") for source, _ in true_exits]
            if orelse.entry is None:
                exits.append((node, "cfg_false"))
            else:
                exits.extend((source, "cfg_join") for source, _ in false_exits)
            return _Flow(node, exits, body.breaks + orelse.breaks,
                         body.continues + orelse.continues)

        if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
            body = self.block(statement.body, node)
            self.edge(node, body.entry, "cfg_true")
            for source, _ in body.exits:
                self.edge(source, node, "cfg_backedge")
            for source in body.continues:
                self.edge(source, node, "cfg_continue")
            # Use an explicit join node so a break does not accidentally flow
            # into the next statement in the loop body. The surrounding block
            # connects this join to the statement after the loop.
            exit_id = f"cfg_loop_exit:{node}"
            self.graph.add_node(GraphNode(exit_id, NodeKind.CONTROL, "loop_exit",
                                          labels=["CTRL"], attrs={"header": node,
                                                                  "evidence": "Inferred"}))
            self.edge(node, exit_id, "cfg_false")
            for source in body.breaks:
                self.edge(source, exit_id, "cfg_break")
            return _Flow(node, [(exit_id, "cfg_next")], [], [])

        if isinstance(statement, ast.Try):
            body = self.block(statement.body, loop_header)
            self.edge(node, body.entry, "cfg_try")
            exits = [(source, "cfg_join") for source, _ in body.exits]
            breaks, continues = list(body.breaks), list(body.continues)
            for handler in statement.handlers:
                handler_flow = self.block(handler.body, loop_header)
                handler_node = self.node(handler)
                self.edge(node, handler_node, "cfg_exception")
                self.edge(handler_node, handler_flow.entry, "cfg_handler")
                exits.extend((source, "cfg_join") for source, _ in handler_flow.exits)
                breaks.extend(handler_flow.breaks)
                continues.extend(handler_flow.continues)
            if statement.finalbody:
                final = self.block(statement.finalbody, loop_header)
                for source, _ in exits:
                    self.edge(source, final.entry, "cfg_finally")
                exits = list(final.exits)
            return _Flow(node, exits, breaks, continues)

        if isinstance(statement, (ast.With, ast.AsyncWith)):
            body = self.block(statement.body, loop_header)
            self.edge(node, body.entry, "cfg_context")
            return _Flow(node, [(source, "cfg_join") for source, _ in body.exits],
                         body.breaks, body.continues)

        if isinstance(statement, ast.Match):
            exits: list[tuple[str, str]] = []
            breaks: list[str] = []
            continues: list[str] = []
            for case in statement.cases:
                case_node = self.node(case)
                case_flow = self.block(case.body, loop_header)
                self.edge(node, case_node, "cfg_case")
                self.edge(case_node, case_flow.entry, "cfg_case_body")
                exits.extend((source, "cfg_join") for source, _ in case_flow.exits)
                breaks.extend(case_flow.breaks)
                continues.extend(case_flow.continues)
            return _Flow(node, exits or [(node, "cfg_false")], breaks, continues)

        # A simple statement falls through to the next statement. Expressions
        # nested in it remain represented by AST nodes and data dependencies;
        # CFG edges intentionally connect statement-level control points.
        return _Flow(node, [(node, "cfg_next")])

    def function(self, definition: ast.AST):
        body = getattr(definition, "body", None)
        if not isinstance(body, list):
            return
        definition_node = self.node(definition)
        flow = self.block(body)
        self.edge(definition_node, flow.entry, "cfg_function_entry")

    def build(self, tree: ast.Module):
        top = self.block(tree.body)
        # Function/class definitions are executed as statements in their
        # enclosing block, but each function body also has its own CFG.
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.function(node)
        return top


def add_static_cfg(graph: ProgramGraph, tree: ast.Module,
                   ast_nodes: dict[int, str]) -> None:
    """Add conservative statement-level CFG edges to a static graph."""
    _CFGBuilder(graph, ast_nodes).build(tree)
