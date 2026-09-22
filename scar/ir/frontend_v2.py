"""Conservative Python AST frontend for the SCAR v2 semantic graph.

The target is parsed, never imported.  This graph records possible definition
and value flow; it is neither an execution trace nor a purity proof.  Every
executable AST atom has an owner, including syntax whose semantics are kept as
an explicit opaque boundary.  Slots describe lexical locations and expression
results; mutable bindings are not asserted to be SSA or logical value versions.
"""
from __future__ import annotations

import ast
from collections import deque
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import tokenize
from typing import Any

from .v2 import (
    ControlRegion, ControlRegionID, EffectSummary, EffectSummaryID, EvidenceClaim,
    EvidenceKind, ModuleDefinition, ModuleID, OperationDefinition,
    OperationDefinitionID, OperationKind, PackageDefinition, PackageID,
    SemanticEdge, SemanticEndpoint, SemanticGraph, SemanticNodeKind,
    SemanticRelation, SourceAtom, SourceAtomID, SourceReference, ValueSlot,
    ValueSlotID,
)


EXCLUDED_DIRECTORIES = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__",
    "node_modules", "site-packages", ".tox", ".mypy_cache", ".pytest_cache",
})
_INFERRED = EvidenceClaim(EvidenceKind.INFERRED,
                          assumptions=("static Python binding and control model; runtime effects unknown",))
_K = SemanticNodeKind
_R = SemanticRelation


@dataclass
class FrontendResult:
    graph: SemanticGraph
    coverage: dict[str, Any]

    def value_path(self, source: ValueSlotID | OperationDefinitionID,
                   target: ValueSlotID | OperationDefinitionID) -> tuple[str, ...]:
        """Return one possible data path, never a claim that it executed.

        READS/CONSUMES edges are stored operation -> input slot by the SG
        schema; this query reverses those edges to follow producer -> consumer.
        Control, lexical containment and call-target edges are excluded.
        """
        adjacency: dict[Any, set] = {}
        for edge in self.graph.edges.values():
            if edge.relation in (_R.READS_SLOT, _R.CONSUMES):
                left, right = edge.target.id, edge.source.id
            elif edge.relation in (_R.WRITES_SLOT, _R.PRODUCES):
                left, right = edge.source.id, edge.target.id
            else:
                continue
            adjacency.setdefault(left, set()).add(right)
        pending = deque([(source, (source.wire,))])
        seen = {source}
        while pending:
            current, path = pending.popleft()
            if current == target:
                return path
            for following in sorted(adjacency.get(current, ()), key=lambda item: item.wire):
                if following not in seen:
                    seen.add(following)
                    pending.append((following, path + (following.wire,)))
        return ()


@dataclass
class _Scope:
    operation: OperationDefinitionID
    module: str
    parent: _Scope | None
    kind: str
    locals: set[str] = field(default_factory=set)
    globals: set[str] = field(default_factory=set)
    nonlocals: set[str] = field(default_factory=set)
    slots: dict[str, ValueSlotID] = field(default_factory=dict)
    hints: dict[str, tuple] = field(default_factory=dict)
    writes: dict[str, int] = field(default_factory=dict)
    wildcard_import: bool = False


class _Bindings(ast.NodeVisitor):
    """Collect one lexical scope, without leaking nested scope bindings."""

    def __init__(self) -> None:
        self.names: set[str] = set()
        self.globals: set[str] = set()
        self.nonlocals: set[str] = set()

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_Global(self, node):
        self.globals.update(node.names)

    def visit_Nonlocal(self, node):
        self.nonlocals.update(node.names)

    def visit_FunctionDef(self, node):
        self.names.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Lambda(self, node):
        pass

    def visit_Import(self, node):
        self.names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node):
        self.names.update(alias.asname or alias.name for alias in node.names if alias.name != "*")

    def visit_ExceptHandler(self, node):
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_ListComp(self, node):
        # The comprehension target has its own scope.  Named expressions may
        # bind outward; their exact rules remain an opaque boundary below.
        pass

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp


class _Frontend:
    def __init__(self, paths: list[Path], root: Path) -> None:
        self.graph = SemanticGraph()
        self.root = root
        self.paths = paths
        self.trees: dict[str, ast.Module] = {}
        self.texts: dict[str, str] = {}
        self.fingerprints: dict[str, str] = {}
        self.files: dict[str, Path] = {}
        self.scopes: dict[str, _Scope] = {}
        self.modules: dict[str, ModuleDefinition] = {}
        self.atoms: dict[ast.AST, SourceAtomID] = {}
        self.atom_owners: dict[SourceAtomID, set[OperationDefinitionID]] = {}
        self.operation_atoms: dict[OperationDefinitionID, set[SourceAtomID]] = {}
        self.functions: dict[OperationDefinitionID, dict[str, Any]] = {}
        self.slot_locations: dict[ValueSlotID, tuple[_Scope, str]] = {}
        self.pending_imports: list[tuple[OperationDefinitionID, str, str | None]] = []
        self.pending_attributes: list[tuple[OperationDefinitionID, tuple, str]] = []
        self.pending_calls: list[tuple[OperationDefinitionID, tuple, list[ValueSlotID], dict[str, ValueSlotID]]] = []
        self.diagnostics: list[dict[str, Any]] = []
        self._serials: dict[str, int] = {}
        self.current_module = ""
        self.current_control: ControlRegionID | None = None

    def key(self, category: str, payload: str) -> str:
        return category + ":" + hashlib.sha256(payload.encode()).hexdigest()[:24]

    def edge(self, relation, source, target) -> None:
        types = {OperationDefinitionID: _K.OPERATION, ModuleID: _K.MODULE,
                 PackageID: _K.PACKAGE, ValueSlotID: _K.VALUE_SLOT,
                 ControlRegionID: _K.CONTROL, EffectSummaryID: _K.EFFECT,
                 SourceAtomID: _K.SOURCE_ATOM}
        key = self.key("edge", relation.value + ":" + source.wire + ":" + target.wire)
        if key not in self.graph.edges:
            self.graph.add_edge(SemanticEdge(key, relation,
                SemanticEndpoint(types[type(source)], source),
                SemanticEndpoint(types[type(target)], target), _INFERRED))

    def own(self, node: ast.AST, operation: OperationDefinitionID) -> None:
        atom = self.atoms.get(node)
        if atom is not None:
            self.atom_owners.setdefault(atom, set()).add(operation)
            self.operation_atoms.setdefault(operation, set()).add(atom)
            self.edge(_R.HAS_SOURCE, operation, atom)

    def operation(self, node, kind, label, scope, *, parent=None, metadata=None, suffix=""):
        atom = self.atoms.get(node)
        base = (atom.wire if atom else scope.operation.wire) + ":" + label + ":" + suffix
        serial = self._serials.get(base, 0)
        self._serials[base] = serial + 1
        operation_id = OperationDefinitionID(self.key("op", base + ":" + str(serial)))
        effect_id = EffectSummaryID(operation_id.value)
        self.graph.add_effect(EffectSummary(effect_id, evidence=(_INFERRED,)))
        definition = OperationDefinition(
            operation_id, kind, label, parent_id=parent or scope.operation,
            control_region=self.current_control, effect_summary=effect_id,
            source_file=str(self.files[self.current_module]),
            source_start=getattr(node, "lineno", None), source_end=getattr(node, "end_lineno", None),
            code_id=atom.wire if atom else None,
            metadata={"frontend": "python_ast_v2", "evidence": "Inferred",
                      "module": self.current_module, **(metadata or {})})
        self.graph.add_definition(definition)
        self.own(node, operation_id)
        self.edge(_R.HAS_EFFECT, operation_id, effect_id)
        if self.current_control:
            self.edge(_R.CONTROLS, self.current_control, operation_id)
        return operation_id

    def slot(self, operation, name, direction="temporary", **metadata):
        slot_id = ValueSlotID(self.key("slot", operation.wire + ":" + name))
        if slot_id not in self.graph.slots:
            self.graph.add_slot(ValueSlot(slot_id, name, direction, owner=operation,
                                          metadata=metadata))
        return slot_id

    def output(self, operation):
        slot = self.slot(operation, "$result", "output")
        self.graph.definitions[operation].output_slots = (slot,)
        self.edge(_R.PRODUCES, operation, slot)
        return slot

    def read(self, operation, slot):
        self.edge(_R.READS_SLOT, operation, slot)

    def local_slot(self, scope, name):
        if name not in scope.slots:
            scope.slots[name] = self.slot(scope.operation, name, "binding", scope_kind=scope.kind)
            self.slot_locations[scope.slots[name]] = (scope, name)
        return scope.slots[name]

    def binding_scope(self, scope, name):
        if name in scope.globals:
            return self.scopes[scope.module]
        if name in scope.nonlocals:
            current = scope.parent
            while current and current.kind != "module":
                if name in current.locals and current.kind != "class":
                    return current
                current = current.parent
            return scope  # invalid/open source scope is retained, never executed
        if name in scope.locals or scope.kind == "module":
            return scope
        current = scope.parent
        while current:
            if current.kind != "class" and (name in current.locals or current.kind == "module"):
                return current
            current = current.parent
        return scope

    def name(self, scope, name):
        owner = self.binding_scope(scope, name)
        slot = self.local_slot(owner, name)
        if scope.kind in ("function", "lambda", "comprehension") and owner is not scope:
            hint = ("slot", slot)
        else:
            hint = owner.hints.get(name, ("unknown",))
        return slot, hint

    def bind(self, scope, name, operation, hint=("unknown",)):
        owner = self.binding_scope(scope, name)
        slot = self.local_slot(owner, name)
        # Analysing a deferred body does not execute its global/nonlocal writes
        # at declaration time.  Such writes make the outer target ambiguous.
        owner.hints[name] = hint if owner is scope else ("unknown",)
        owner.writes[name] = owner.writes.get(name, 0) + 1
        self.edge(_R.WRITES_SLOT, operation, slot)
        if owner.kind == "module":
            self.edge(_R.REEXPORTS, self.modules[owner.module].id, slot)
        return slot

    def discover(self):
        for path in self.paths:
            relative = path.relative_to(self.root)
            parts = list(relative.with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            if (self.root / "__init__.py").is_file():
                parts.insert(0, self.root.name)
            name = ".".join(parts) or self.root.name
            with tokenize.open(path) as source_file:
                text = source_file.read()
            tree = ast.parse(text, filename=str(path), type_comments=True)
            fingerprint = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
            self.trees[name], self.texts[name] = tree, text
            self.files[name], self.fingerprints[name] = path, fingerprint
            for index, node in enumerate(ast.walk(tree)):
                if isinstance(node, (ast.stmt, ast.expr, ast.arg, ast.alias, ast.keyword,
                                     ast.ExceptHandler)) and hasattr(node, "lineno"):
                    atom_id = SourceAtomID(self.key("atom", f"{relative}:{fingerprint}:{index}:{type(node).__name__}"))
                    reference = SourceReference(atom_id, str(path), fingerprint, node.lineno,
                        node.end_lineno or node.lineno, node.col_offset, node.end_col_offset)
                    # File content digest + AST position identify the atom.
                    # Re-dumping every subtree would revisit the same source
                    # repeatedly and can be quadratic on deeply nested syntax.
                    self.graph.add_source_atom(SourceAtom(atom_id, reference, type(node).__name__))
                    self.atoms[node] = atom_id
        for name in sorted(self.trees):
            path = self.files[name]
            package_name = name if path.name == "__init__.py" else name.rpartition(".")[0]
            package_id = None
            if package_name:
                package_id = PackageID(self.key("package", str(self.root) + ":" + package_name))
                if package_id not in self.graph.packages:
                    self.graph.add_package(PackageDefinition(package_id, package_name, str(path.parent)))
            fingerprint = self.fingerprints[name]
            init_id = OperationDefinitionID(self.key("init", name + ":" + fingerprint))
            effect_id = EffectSummaryID(init_id.value)
            self.graph.add_effect(EffectSummary(effect_id, evidence=(_INFERRED,)))
            self.graph.add_definition(OperationDefinition(init_id, OperationKind.MODULE,
                f"initialize {name}", source_file=str(path), effect_summary=effect_id,
                metadata={"module": name, "phase": "module_initialization", "evidence": "Inferred"}))
            module = ModuleDefinition(ModuleID(self.key("module", name + ":" + fingerprint)),
                                      name, package_id, str(path), fingerprint, init_id)
            self.graph.add_module(module)
            self.modules[name] = module
            self.edge(_R.INITIALIZES_MODULE, init_id, module.id)
            self.edge(_R.HAS_EFFECT, init_id, effect_id)
            if package_id:
                self.edge(_R.CONTAINS, package_id, module.id)
            scope = self.new_scope(init_id, name, None, "module", self.trees[name].body)
            self.scopes[name] = scope
            namespace = self.slot(init_id, "$module_namespace", "output")
            self.edge(_R.PRODUCES, init_id, namespace)
            self.graph.definitions[init_id].output_slots = (namespace,)

    def new_scope(self, operation, module, parent, kind, body):
        bindings = _Bindings()
        for statement in body:
            bindings.visit(statement)
        scope = _Scope(operation, module, parent, kind, bindings.names - bindings.globals - bindings.nonlocals,
                       bindings.globals, bindings.nonlocals)
        for name in sorted(scope.locals):
            self.local_slot(scope, name)
        return scope

    def external_module(self, name):
        if name not in self.modules:
            module = ModuleDefinition(ModuleID(self.key("external", name)), name)
            self.graph.add_module(module)
            self.modules[name] = module
        return self.modules[name]

    def import_name(self, node, scope):
        package = scope.module if self.files[scope.module].name == "__init__.py" else scope.module.rpartition(".")[0]
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".") if package else []
                base = base[:len(base) - node.level + 1] if node.level <= len(base) else []
                module_name = ".".join(base + ([node.module] if node.module else []))
            else:
                module_name = node.module or ""
        for alias in node.names:
            requested = alias.name if isinstance(node, ast.Import) else module_name
            operation = self.operation(node, OperationKind.IMPORT, f"import {requested}", scope,
                metadata={"requested_module": requested, "symbol": None if isinstance(node, ast.Import) else alias.name,
                          "import_effects": "UNKNOWN"}, suffix=alias.name)
            self.own(alias, operation)
            module = self.external_module(requested)
            self.edge(_R.IMPORTS, operation, module.id)
            imported_symbol = None if isinstance(node, ast.Import) else alias.name
            self.pending_imports.append((operation, requested, imported_symbol))
            if alias.name == "*":
                scope.wildcard_import = True
                self.graph.definitions[operation].kind = OperationKind.OPAQUE
                self.graph.definitions[operation].metadata["opaque_reason"] = "star import may bind arbitrary names"
                continue
            if isinstance(node, ast.Import):
                local_name = alias.asname or alias.name.split(".")[0]
                bound_module = requested if alias.asname else requested.split(".")[0]
                self.external_module(bound_module)
                hint = ("module", bound_module)
            else:
                local_name = alias.asname or alias.name
                hint = ("export", requested, alias.name)
            self.bind(scope, local_name, operation, hint)
            self.output(operation)

    def store(self, target, value, hint, scope, parent):
        operation = self.operation(target, OperationKind.OPERATOR, "bind " + ast.unparse(target),
                                   scope, parent=parent, metadata={"role": "binding"})
        self.read(operation, value)
        if isinstance(target, ast.Name):
            self.bind(scope, target.id, operation, hint)
        elif isinstance(target, (ast.Tuple, ast.List)):
            self.graph.definitions[operation].metadata["unpack_may_raise"] = True
            for child in target.elts:
                self.store(child, value, ("unknown",), scope, operation)
        else:
            # Attribute/subscript stores can invoke descriptors and arbitrary
            # user code; evaluate receiver/index and keep the write opaque.
            self.graph.definitions[operation].kind = OperationKind.OPAQUE
            self.graph.definitions[operation].metadata["opaque_reason"] = "descriptor or indexed mutation"
            for child in ast.iter_child_nodes(target):
                if isinstance(child, ast.expr):
                    slot, _ = self.expression(child, scope)
                    self.read(operation, slot)
        return operation

    def expression(self, node, scope):
        if isinstance(node, ast.Lambda):
            return self.function(node, scope)
        if isinstance(node, ast.Name):
            operation = self.operation(node, OperationKind.OPERATOR, "read " + node.id, scope)
            source, hint = self.name(scope, node.id)
            self.read(operation, source)
            return self.output(operation), hint
        kind = {ast.Constant: OperationKind.CONSTANT, ast.Attribute: OperationKind.ATTRIBUTE,
                ast.Subscript: OperationKind.INDEX}.get(type(node), OperationKind.OPERATOR)
        opaque = isinstance(node, (ast.Call, ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr,
                                   ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        if opaque:
            kind = OperationKind.OPAQUE
        operation = self.operation(node, kind, type(node).__name__, scope,
            metadata={"ast_type": type(node).__name__, **({"opaque_reason": "dynamic Python semantics"} if opaque else {})})
        hint = ("unknown",)
        if isinstance(node, ast.Constant):
            self.graph.definitions[operation].metadata["literal_repr"] = repr(node.value)
        elif isinstance(node, ast.Call):
            function_slot, hint = self.expression(node.func, scope)
            self.read(operation, function_slot)
            arguments, keywords = [], {}
            dynamic = False
            for argument in node.args:
                argument_slot, _ = self.expression(argument, scope)
                self.read(operation, argument_slot)
                arguments.append(argument_slot)
                dynamic |= isinstance(argument, ast.Starred)
            for keyword in node.keywords:
                self.own(keyword, operation)
                slot, _ = self.expression(keyword.value, scope)
                self.read(operation, slot)
                if keyword.arg is None:
                    dynamic = True
                else:
                    keywords[keyword.arg] = slot
            if dynamic:
                self.graph.definitions[operation].metadata["opaque_reason"] = "dynamic argument unpacking"
            else:
                self.pending_calls.append((operation, hint, arguments, keywords))
            hint = ("unknown",)
        elif isinstance(node, ast.Attribute):
            receiver, base = self.expression(node.value, scope)
            self.read(operation, receiver)
            self.pending_attributes.append((operation, base, node.attr))
            self.graph.definitions[operation].metadata["attribute"] = node.attr
            self.graph.definitions[operation].metadata["dispatch"] = "descriptor_or_module_attribute"
            hint = ("attribute", base, node.attr)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            # Outer iterable is evaluated in the enclosing scope.  Iteration,
            # filters and elements belong to a distinct lexical scope.
            child_scope = self.new_scope(operation, scope.module, scope, "comprehension", [])
            for generator in node.generators:
                child_scope.locals.update(n.id for n in ast.walk(generator.target) if isinstance(n, ast.Name))
            for index, generator in enumerate(node.generators):
                iterator, _ = self.expression(generator.iter, scope if index == 0 else child_scope)
                self.read(operation, iterator)
                self.store(generator.target, iterator, ("unknown",), child_scope, operation)
                for condition in generator.ifs:
                    value, _ = self.expression(condition, child_scope)
                    self.read(operation, value)
            for attribute in ("elt", "key", "value"):
                child = getattr(node, attribute, None)
                if child is not None:
                    value, _ = self.expression(child, child_scope)
                    self.read(operation, value)
        elif isinstance(node, ast.NamedExpr):
            value, hint = self.expression(node.value, scope)
            self.read(operation, value)
            self.store(node.target, value, ("unknown",), scope, operation)
            hint = ("unknown",)
        else:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.expr):
                    value, _ = self.expression(child, scope)
                    self.read(operation, value)
        return self.output(operation), hint

    def function(self, node, scope):
        name = getattr(node, "name", "<lambda>")
        declaration = self.operation(node, OperationKind.OPERATOR, "define " + name, scope,
            metadata={"phase": "definition_time"})
        decorators = getattr(node, "decorator_list", [])
        for expression in list(decorators) + list(node.args.defaults) + [item for item in node.args.kw_defaults if item]:
            value, _ = self.expression(expression, scope)
            self.read(declaration, value)
        # Annotation evaluation differs with future annotations and Python
        # versions; preserve an explicit definition-time opaque boundary.
        arguments = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        arguments += [item for item in (node.args.vararg, node.args.kwarg) if item]
        for annotation in [arg.annotation for arg in arguments if arg.annotation] + ([node.returns] if getattr(node, "returns", None) else []):
            annotation_op = self.operation(annotation, OperationKind.OPAQUE, "annotation", scope,
                parent=declaration, metadata={"opaque_reason": "annotation evaluation policy is version dependent"})
            for descendant in ast.walk(annotation):
                self.own(descendant, annotation_op)
        saved_control = self.current_control
        self.current_control = None
        body_operation = self.operation(node, OperationKind.METHOD if scope.kind == "class" else OperationKind.FUNCTION,
            name, scope, metadata={"phase": "call_time", "callable_name": name,
                                   "async": isinstance(node, ast.AsyncFunctionDef)})
        body = [node.body] if isinstance(node, ast.Lambda) else node.body
        child_scope = self.new_scope(body_operation, scope.module, scope,
                                    "lambda" if isinstance(node, ast.Lambda) else "function", body)
        parameters = {}
        for argument in arguments:
            child_scope.locals.add(argument.arg)
            slot = self.local_slot(child_scope, argument.arg)
            self.graph.slots[slot].direction = "input"
            self.own(argument, body_operation)
            parameters[argument.arg] = slot
        self.graph.definitions[body_operation].input_slots = tuple(parameters.values())
        return_slot = self.slot(body_operation, "$return", "output")
        self.graph.definitions[body_operation].output_slots = (return_slot,)
        self.functions[body_operation] = {"scope": child_scope, "parameters": parameters,
            "positional": [arg.arg for arg in node.args.posonlyargs + node.args.args],
            "positional_only": {arg.arg for arg in node.args.posonlyargs},
            "required": {arg.arg for arg in (node.args.posonlyargs + node.args.args)[:len(node.args.posonlyargs + node.args.args) - len(node.args.defaults)]}
                | {arg.arg for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults) if default is None},
            "varargs": node.args.vararg is not None or node.args.kwarg is not None,
            "return": return_slot, "defaults": bool(node.args.defaults or any(node.args.kw_defaults))}
        if isinstance(node, ast.Lambda):
            value, _ = self.expression(node.body, child_scope)
            self.read(body_operation, value)
            self.edge(_R.PRODUCES, body_operation, return_slot)
        else:
            self.statements(node.body, child_scope)
        self.current_control = saved_control
        hint = ("function", body_operation) if not decorators else ("unknown",)
        if not isinstance(node, ast.Lambda):
            self.bind(scope, name, declaration, hint)
        return self.output(declaration), hint

    def controlled(self, node, scope, operation, name, statements):
        previous = self.current_control
        control_id = ControlRegionID(self.key("control", operation.wire + ":" + name))
        self.graph.add_control(ControlRegion(control_id, name, previous, operation,
            source_atoms=(self.atoms[node],) if node in self.atoms else (),
            metadata={"evidence": "Inferred", "path_condition": name}))
        self.edge(_R.CONTROLS, operation, control_id)
        self.current_control = control_id
        self.statements(statements, scope)
        self.current_control = previous

    def statements(self, statements, scope):
        for node in statements:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.function(node, scope)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                self.import_name(node, scope)
            elif isinstance(node, ast.ClassDef):
                operation = self.operation(node, OperationKind.OPAQUE, "class " + node.name, scope,
                    metadata={"opaque_reason": "metaclass, descriptor and class construction effects"})
                for expression in list(node.decorator_list) + list(node.bases) + [keyword.value for keyword in node.keywords]:
                    value, _ = self.expression(expression, scope)
                    self.read(operation, value)
                for keyword in node.keywords:
                    self.own(keyword, operation)
                child = self.new_scope(operation, scope.module, scope, "class", node.body)
                self.statements(node.body, child)
                self.bind(scope, node.name, operation)
                self.output(operation)
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                operation = self.operation(node, OperationKind.OPERATOR, type(node).__name__, scope)
                if isinstance(node, ast.AnnAssign) and node.annotation:
                    annotation = self.operation(node.annotation, OperationKind.OPAQUE, "annotation", scope,
                        parent=operation, metadata={"opaque_reason": "annotation evaluation policy"})
                    for descendant in ast.walk(node.annotation):
                        self.own(descendant, annotation)
                if node.value is not None:
                    value, hint = self.expression(node.value, scope)
                    self.read(operation, value)
                    if isinstance(node, ast.AugAssign):
                        old, _ = self.expression(node.target, scope)
                        self.read(operation, old)
                        value, hint = self.output(operation), ("unknown",)
                    for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                        self.store(target, value, hint, scope, operation)
            elif isinstance(node, ast.Return):
                operation = self.operation(node, OperationKind.OPERATOR, "return", scope)
                if node.value is not None:
                    value, _ = self.expression(node.value, scope)
                    self.read(operation, value)
                if scope.operation in self.functions:
                    self.edge(_R.PRODUCES, operation, self.functions[scope.operation]["return"])
            elif isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While)):
                operation = self.operation(node, OperationKind.BRANCH if isinstance(node, ast.If) else OperationKind.LOOP,
                                           type(node).__name__, scope)
                expression = node.test if isinstance(node, (ast.If, ast.While)) else node.iter
                value, _ = self.expression(expression, scope)
                self.read(operation, value)
                if isinstance(node, (ast.For, ast.AsyncFor)):
                    self.store(node.target, value, ("unknown",), scope, operation)
                prior_hints = dict(scope.hints)
                self.controlled(node, scope, operation, "if_true" if isinstance(node, ast.If) else "loop_body", node.body)
                scope.hints = dict(prior_hints)
                self.controlled(node, scope, operation, "if_false" if isinstance(node, ast.If) else "loop_else", node.orelse)
                # Do not pick one branch's target.  A merge explicitly marks
                # path-sensitive bindings as unresolved, with lexical may-flow.
                changed = _Bindings()
                for statement in node.body + node.orelse:
                    changed.visit(statement)
                for name in sorted(changed.names):
                    merge = self.operation(node, OperationKind.OPERATOR, "merge " + name, scope,
                        metadata={"role": "phi_like_merge", "path_sensitive": True})
                    slot, _ = self.name(scope, name)
                    self.read(merge, slot)
                    self.bind(scope, name, merge)
            elif isinstance(node, (ast.Try, getattr(ast, "TryStar", ast.Try))):
                operation = self.operation(node, OperationKind.REGION, "try", scope)
                prior_hints = dict(scope.hints)
                self.controlled(node, scope, operation, "try_body", node.body)
                body_hints = dict(scope.hints)
                for index, handler in enumerate(node.handlers):
                    scope.hints = dict(prior_hints)
                    handler_op = self.operation(handler, OperationKind.OPAQUE, "except", scope,
                        parent=operation, metadata={"opaque_reason": "exception matching and binding"})
                    if handler.type:
                        value, _ = self.expression(handler.type, scope)
                        self.read(handler_op, value)
                    if handler.name:
                        self.bind(scope, handler.name, handler_op)
                    self.edge(_R.MAY_RAISE, operation, self.graph.definitions[handler_op].effect_summary)
                    self.controlled(handler, scope, handler_op, f"except_{index}", handler.body)
                scope.hints = body_hints
                self.controlled(node, scope, operation, "try_else", node.orelse)
                changed = _Bindings()
                for statement in node.body + node.orelse + [statement for handler in node.handlers for statement in handler.body]:
                    changed.visit(statement)
                for name in changed.names | {handler.name for handler in node.handlers if handler.name}:
                    scope.hints[name] = ("unknown",)
                self.controlled(node, scope, operation, "finally", node.finalbody)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                operation = self.operation(node, OperationKind.OPAQUE, type(node).__name__, scope,
                    metadata={"opaque_reason": "context manager enter/exit and exception suppression"})
                for item in node.items:
                    value, _ = self.expression(item.context_expr, scope)
                    self.read(operation, value)
                    if item.optional_vars:
                        self.store(item.optional_vars, value, ("unknown",), scope, operation)
                self.controlled(node, scope, operation, "with_body", node.body)
            else:
                supported = isinstance(node, (ast.Expr, ast.Pass, ast.Global, ast.Nonlocal))
                operation = self.operation(node, OperationKind.OPERATOR if supported else OperationKind.OPAQUE,
                    type(node).__name__, scope,
                    metadata={} if supported else {"opaque_reason": "unsupported or abrupt control syntax"})
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, ast.expr):
                        value, _ = self.expression(child, scope)
                        self.read(operation, value)
                    elif isinstance(child, ast.stmt):
                        self.statements([child], scope)
                # Match/pattern and other auxiliary AST nodes are still owned
                # by the opaque statement; do not invent evaluation semantics.
                for descendant in ast.walk(node):
                    if descendant in self.atoms and self.atoms[descendant] not in self.atom_owners:
                        self.own(descendant, operation)
                if isinstance(node, ast.Delete):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self.bind(scope, target.id, operation)
                elif not supported and not isinstance(node, (ast.Raise, ast.Break, ast.Continue, ast.Assert)):
                    # Unsupported constructs may bind names; never retain a
                    # specific callable target through that opaque boundary.
                    scope.hints = {name: ("unknown",) for name in scope.hints}

    def resolve(self, hint, seen=None):
        seen = set() if seen is None else seen
        if hint in seen:
            return ("unknown",)
        seen.add(hint)
        if hint[0] == "slot":
            scope, name = self.slot_locations[hint[1]]
            if scope.wildcard_import or scope.writes.get(name, 0) != 1:
                return ("unknown",)
            return self.resolve(scope.hints.get(name, ("unknown",)), seen)
        if hint[0] == "attribute":
            base = self.resolve(hint[1], seen)
            return self.resolve(("export", base[1], hint[2]), seen) if base[0] == "module" else ("unknown",)
        if hint[0] == "export":
            scope = self.scopes.get(hint[1])
            if scope and hint[2] in scope.locals:
                return self.resolve(("slot", self.local_slot(scope, hint[2])), seen)
            submodule = hint[1] + "." + hint[2]
            return ("module", submodule) if submodule in self.scopes else ("unknown",)
        return hint

    def link(self):
        for operation, module_name, symbol in self.pending_imports:
            module = self.modules[module_name]
            if module.initializer:
                namespace = self.slot(module.initializer, "$module_namespace", "output")
                self.read(operation, namespace)
            if symbol and symbol != "*" and module_name in self.scopes:
                source = self.local_slot(self.scopes[module_name], symbol)
                self.read(operation, source)
        for operation, hint, attribute in self.pending_attributes:
            resolved = self.resolve(hint)
            if resolved[0] == "module":
                module_name = resolved[1]
                self.edge(_R.ACCESSES_ATTRIBUTE, operation, self.modules[module_name].id)
                if module_name in self.scopes:
                    slot = self.local_slot(self.scopes[module_name], attribute)
                    self.read(operation, slot)
                    self.edge(_R.ACCESSES_ATTRIBUTE, operation, slot)
            self.graph.definitions[operation].metadata["attribute_resolution"] = (
                "local_module_candidate" if resolved[0] == "module" and resolved[1] in self.scopes
                else "opaque_descriptor_or_lazy_attribute")
        for operation, hint, arguments, keywords in self.pending_calls:
            resolved = self.resolve(hint)
            if resolved[0] != "function":
                continue
            target = resolved[1]
            info = self.functions[target]
            self.edge(_R.CALLS, operation, target)
            definition = self.graph.definitions[operation]
            definition.metadata["target_candidate"] = target.wire
            definition.metadata["target_status"] = "Inferred"
            if info["varargs"] or len(arguments) > len(info["positional"]):
                definition.metadata["binding_status"] = "opaque_variadic_or_arity"
                continue
            bound = dict(zip(info["positional"], arguments))
            if (set(bound) & set(keywords) or not set(keywords) <= set(info["parameters"])
                    or set(keywords) & info["positional_only"]):
                definition.metadata["binding_status"] = "may_raise_argument_binding"
                continue
            bound.update(keywords)
            if not info["required"] <= set(bound):
                definition.metadata["binding_status"] = "may_raise_missing_argument"
                continue
            for name, actual in bound.items():
                binding = OperationDefinitionID(self.key("argument", operation.wire + ":" + name))
                effect_id = EffectSummaryID(binding.value)
                self.graph.add_effect(EffectSummary(effect_id, evidence=(_INFERRED,)))
                self.graph.add_definition(OperationDefinition(binding, OperationKind.REGION,
                    "bind argument " + name, parent_id=operation, effect_summary=effect_id,
                    metadata={"role": "actual_to_formal", "evidence": "Inferred"}))
                self.edge(_R.HAS_EFFECT, binding, effect_id)
                self.read(binding, actual)
                self.edge(_R.PRODUCES, binding, info["parameters"][name])
            self.read(operation, info["return"])
            definition.metadata["binding_status"] = "partial_defaults" if len(bound) < len(info["parameters"]) else "explicit_arguments"

    def build(self):
        self.discover()
        for name in sorted(self.trees):
            self.current_module = name
            self.statements(self.trees[name].body, self.scopes[name])
        self.link()
        # Any atom omitted by a specialized handler is covered by an explicit
        # opaque node.  This fallback reports the gap rather than hiding it.
        for name in sorted(self.trees):
            self.current_module = name
            for node in ast.walk(self.trees[name]):
                atom = self.atoms.get(node)
                if atom is not None and atom not in self.atom_owners:
                    self.operation(node, OperationKind.OPAQUE, "unmodeled " + type(node).__name__, self.scopes[name],
                        metadata={"opaque_reason": "frontend coverage fallback"})
                    self.diagnostics.append({"kind": "opaque_coverage_fallback", "source_atom": atom.wire})
        for operation, atoms in self.operation_atoms.items():
            self.graph.definitions[operation].source_atoms = tuple(sorted(atoms, key=lambda item: item.wire))
        validation = self.graph.assert_valid()
        opaque = [item for item in self.graph.definitions.values() if item.kind is OperationKind.OPAQUE]
        coverage = {
            "schema": "scar.frontend.v2.coverage", "schema_version": 1,
            "files": [str(path) for path in self.paths], "target_executed": False,
            "selection_scope": "all_selected_project_python_files_not_entry_reachability",
            "source_atoms": len(self.atoms), "owned_source_atoms": len(self.atom_owners),
            "unowned_source_atoms": 0, "opaque_operations": len(opaque),
            "owners": {atom.wire: sorted(owner.wire for owner in owners)
                       for atom, owners in sorted(self.atom_owners.items(), key=lambda item: item[0].wire)},
            "diagnostics": self.diagnostics, "validation": validation,
            "limitations": [
                "Static may-flow, not SSA, execution evidence, consumer closure or a purity proof.",
                "Dynamic dispatch, descriptors, lazy imports, star imports and unsupported syntax stay opaque.",
                "Exception feasibility, async ordering, generators, context managers and argument defaults require later semantic analysis.",
                "No built-in or PyTorch purity contracts are asserted by this frontend.",
            ],
        }
        return FrontendResult(self.graph, coverage)


def build_semantic(source: Path | str, project_root: Path | str | None = None) -> FrontendResult:
    """Parse a file or bounded project directory into a deterministic SG.

    A file input includes local Python modules under project_root, when given,
    so imports can resolve without importing the target.  Directory selection
    excludes environments and caches; symbolic links are not traversed.
    """
    source = Path(source).resolve()
    root = Path(project_root).resolve() if project_root is not None else (source if source.is_dir() else source.parent)
    if not source.exists():
        raise FileNotFoundError(source)
    if not source.is_relative_to(root):
        raise ValueError("source must be within project_root")
    scan = root if source.is_dir() or project_root is not None else None
    if scan is None:
        paths = [source]
    else:
        paths = []
        for directory, subdirectories, filenames in os.walk(scan, followlinks=False):
            subdirectories[:] = sorted(name for name in subdirectories
                if name not in EXCLUDED_DIRECTORIES and not (Path(directory) / name).is_symlink())
            paths.extend(Path(directory) / name for name in filenames
                         if name.endswith(".py") and not (Path(directory) / name).is_symlink())
        paths.sort()
    if not paths:
        raise ValueError("no Python source files selected")
    return _Frontend(paths, root).build()


__all__ = ["EXCLUDED_DIRECTORIES", "FrontendResult", "build_semantic"]
