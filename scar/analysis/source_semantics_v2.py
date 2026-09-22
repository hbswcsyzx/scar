"""Nonexecuting, source-version-bound computational semantics over the SG.

The SG owns program structure. This overlay supplies operand order and distinct
binding definitions for a bounded Python subset. It does not infer runtime
values, import a module, or declare a source change legal. Exact local bindings
stop at unsupported control/dispatch boundaries. A separate replay checker
rejects a structurally valid overlay whose opcodes were edited after capture.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
import sys
import tokenize

from scar.ir.semantics_v2 import (
    BindingStatus, BindingUse, BindingUseID, DispatchKind, ImportSpec, Opcode,
    OperandUse, OperationSemantics, PythonLiteral, SemanticGap, SourceSemanticsGraph,
    SourceSnapshot, StaticBinding, StaticBindingID, StaticValue, StaticValueID,
)
from scar.ir.v2 import OperationKind, SemanticGraph
from scar.ir.v2.semantic import SemanticRelation


def _key(*parts):
    return hashlib.sha256("\x00".join(str(part) for part in parts).encode()).hexdigest()[:32]


def _span(node):
    return (type(node).__name__, getattr(node, "lineno", None),
            getattr(node, "end_lineno", None), getattr(node, "col_offset", None),
            getattr(node, "end_col_offset", None))


@dataclass
class _Block:
    scope: object
    key: str
    kind: str
    env: dict = field(default_factory=dict)
    position: int = 0

    def tick(self):
        self.position += 1
        return self.position


_BINARY = {
    ast.Add: "ADD", ast.Sub: "SUB", ast.Mult: "MUL", ast.Div: "TRUE_DIV",
    ast.FloorDiv: "FLOOR_DIV", ast.Mod: "MOD", ast.Pow: "POW",
    ast.LShift: "LSHIFT", ast.RShift: "RSHIFT", ast.BitAnd: "BIT_AND",
    ast.BitOr: "BIT_OR", ast.BitXor: "BIT_XOR",
}
_UNARY = {ast.UAdd: "POS", ast.USub: "NEG", ast.Invert: "INVERT"}


class _Extractor:
    def __init__(self, semantic, sources):
        self.semantic, self.supplied = semantic, sources
        self.result = SourceSemanticsGraph()
        self.atoms = defaultdict(list)
        self.primary = defaultdict(list)
        self.reads, self.writes = defaultdict(set), defaultdict(set)
        self.gaps = []
        self.epochs = defaultdict(int)
        self.builtin = {}  # Exact builtin *type* hints, never equality proofs.
        self.release_safe = {}  # Dropping an owned reference cannot call user finalizers.
        self.open_namespaces = set()
        self.block_serial = defaultdict(int)
        self.path = None
        for atom in semantic.source_atoms.values():
            r = atom.reference
            self.atoms[(r.path, atom.kind, r.start_line, r.end_line,
                        r.start_column, r.end_column)].append(atom)
        for definition in semantic.definitions.values():
            if definition.code_id:
                self.primary[definition.code_id].append(definition)
        for edge in semantic.edges.values():
            if edge.relation is SemanticRelation.READS_SLOT:
                self.reads[edge.source.id].add(edge.target.id)
            elif edge.relation is SemanticRelation.WRITES_SLOT:
                self.writes[edge.source.id].add(edge.target.id)

    def gap(self, reason, *, operation=None, use=None, source=None, required_fact=""):
        self.gaps.append(SemanticGap(reason, operation, use, source, required_fact))

    def block(self, scope, kind, tag, env=None):
        serial = self.block_serial[scope]
        self.block_serial[scope] += 1
        return _Block(scope, f"{scope.wire}:{tag}:{serial}", kind, dict(env or {}))

    def barrier(self, block, reason, operation=None, source=None):
        block.env.clear()
        # Source write counts cannot prove absence after code that can insert
        # arbitrary namespace entries (including objects with finalizers).
        self.open_namespaces.add(block.scope)
        self.gap(reason, operation=operation, source=source,
                 required_fact="Prove reaching definitions across this control or dispatch boundary.")

    def atom(self, node):
        candidates = self.atoms.get((self.path, *_span(node)), ())
        if len(candidates) != 1:
            self.gap("Source AST span has missing or ambiguous SG ownership.",
                     required_fact="Preserve an unambiguous structural AST/source-atom correspondence.")
            return None
        return candidates[0]

    def operation(self, node, role="expression", alias=None):
        atom = self.atom(node)
        if atom is None:
            return None
        definitions = self.primary.get(atom.id.wire, ())
        if role == "expression":
            candidates = [item for item in definitions if item.output_slots and
                          item.kind not in {OperationKind.FUNCTION, OperationKind.METHOD} and
                          item.metadata.get("role") != "binding"]
        elif role == "binding":
            candidates = [item for item in definitions if item.metadata.get("role") == "binding"]
        elif role == "function":
            candidates = [item for item in definitions if item.kind in
                          {OperationKind.FUNCTION, OperationKind.METHOD} and
                          item.metadata.get("phase") == "call_time"]
        elif role == "import":
            alias_atom = self.atom(alias)
            candidates = [item for item in definitions if alias_atom is not None and
                          alias_atom.id in item.source_atoms and item.kind in
                          {OperationKind.IMPORT, OperationKind.OPAQUE}]
        else:
            candidates = [item for item in definitions if item.metadata.get("role") != "phi_like_merge"]
        if len(candidates) != 1:
            self.gap("Source operation correspondence is missing or ambiguous for " + role,
                     source=atom.reference,
                     required_fact="Select the operation by source ownership and semantic phase.")
            return None
        return candidates[0], atom.reference

    def emit(self, pair, block, opcode, operands=(), *, literal=None, binding_use=None,
             attribute=None, import_spec=None, builtin=None, position=None):
        if pair is None:
            return None
        definition, reference = pair
        if definition.id in self.result.operations:
            # A source expression has one definition. Encountering it twice in
            # extraction is not a second dynamic execution or a new value.
            return self.result.operations[definition.id].result
        position = block.tick() if position is None else position
        identity = StaticValueID(_key("value", definition.id.wire))
        uses = tuple(OperandUse(role, index, value) for role, index, value in operands
                     if value is not None)
        if any(value is None for _, _, value in operands):
            opcode = Opcode.OPAQUE
            self.gap("An operand lacks computational semantics.", operation=definition.id,
                     source=reference, required_fact="Model each ordered operand before evaluating its parent.")
            builtin = None
        if opcode is Opcode.OPAQUE:
            self.gap("Operation has no exact computational semantics in this subset.",
                     operation=definition.id, source=reference,
                     required_fact="Supply a checked semantic rule with ordered operands and dispatch preconditions.")
        self.result.values[identity] = StaticValue(identity, definition.id, block.scope, reference)
        self.result.operations[definition.id] = OperationSemantics(
            definition.id, block.scope, block.key, position, opcode, uses, identity, reference,
            literal=literal, binding_use=binding_use, attribute=attribute,
            dispatch=DispatchKind.BUILTIN if builtin is not None else DispatchKind.UNRESOLVED,
            import_spec=import_spec)
        if builtin is not None:
            self.builtin[identity] = builtin
        if literal is not None:
            self.release_safe[identity] = True
        elif opcode is Opcode.ALIAS and uses:
            self.release_safe[identity] = self.release_safe.get(uses[0].value, False)
        elif opcode in {Opcode.BUILD_TUPLE, Opcode.BUILD_LIST}:
            self.release_safe[identity] = all(self.release_safe.get(use.value, False) for use in uses)
        elif builtin in {"int", "bool", "float", "str", "bytes"}:
            self.release_safe[identity] = True
        return identity

    def expr(self, node, block):
        pair = self.operation(node)
        if pair is None:
            self.barrier(block, "Unmapped expression may have effects.")
            return None
        definition, reference = pair
        if isinstance(node, ast.Constant):
            try:
                literal = PythonLiteral.from_python(node.value)
            except (ValueError, TypeError):
                self.gap("Literal representation is outside the supported exact subset.",
                         operation=definition.id, source=reference,
                         required_fact="Add an exact typed literal representation.")
                return self.emit(pair, block, Opcode.OPAQUE)
            return self.emit(pair, block, Opcode.LITERAL, literal=literal,
                             builtin=type(node.value).__name__)
        if isinstance(node, ast.Name):
            slots = self.reads.get(definition.id, set())
            if len(slots) != 1:
                self.gap("Name use has no unique lexical slot.", operation=definition.id, source=reference)
                return self.emit(pair, block, Opcode.OPAQUE)
            slot = next(iter(slots))
            reaching = (block.env[slot],) if slot in block.env else ()
            binding = self.result.bindings[reaching[0]] if reaching else None
            exact = (binding is not None and binding.scope == block.scope and
                     binding.block == block.key and block.kind in {"module", "function"} and
                     self.semantic.slots[slot].owner == block.scope)
            uid = BindingUseID(_key("use", definition.id.wire))
            position = block.tick()
            self.result.uses[uid] = BindingUse(uid, definition.id, slot, block.scope,
                block.key, position, reaching, BindingStatus.EXACT if exact else BindingStatus.UNRESOLVED,
                reference)
            if not exact:
                self.gap("Use has no unique preceding definition in this straight-line scope.",
                         operation=definition.id, use=uid, source=reference,
                         required_fact="Resolve parameters, merges, deferred/global state or import bindings.")
            value = self.emit(pair, block, Opcode.READ, binding_use=uid, position=position,
                              builtin=self.builtin.get(binding.value) if exact else None)
            self.release_safe[value] = bool(exact and self.release_safe.get(binding.value, False))
            return value
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            items = [("element", index, self.expr(child, block)) for index, child in enumerate(node.elts)]
            opcode = {ast.Tuple: Opcode.BUILD_TUPLE, ast.List: Opcode.BUILD_LIST,
                      ast.Set: Opcode.BUILD_SET}[type(node)]
            value = self.emit(pair, block, opcode, items, builtin=type(node).__name__.lower())
            if isinstance(node, ast.Set):
                self.barrier(block, "Set construction may invoke element hashing.", definition.id, reference)
            return value
        if isinstance(node, ast.Dict):
            operands = []
            for index, (key, value) in enumerate(zip(node.keys, node.values)):
                if key is not None:
                    key_value = self.expr(key, block)
                    operands.append(("key", index, key_value))
                    if self.builtin.get(key_value) not in {"int", "bool", "float", "str", "bytes", "NoneType"}:
                        self.barrier(block, "Dictionary key hashing/equality may call user code.", definition.id, reference)
                operands.append(("value" if key is not None else "unpack", index, self.expr(value, block)))
                if key is None:
                    self.barrier(block, "Mapping unpacking can mutate bindings before the next entry.", definition.id, reference)
            value = self.emit(pair, block, Opcode.BUILD_DICT, operands, builtin="dict")
            self.barrier(block, "Dictionary construction may invoke hashing or mapping unpacking.", definition.id, reference)
            return value
        if isinstance(node, ast.BinOp):
            left, right = self.expr(node.left, block), self.expr(node.right, block)
            opcode = getattr(Opcode, _BINARY.get(type(node.op), "OPAQUE"))
            left_type, right_type = self.builtin.get(left), self.builtin.get(right)
            # This hint is used only to invalidate possible namespace writes.
            # The evaluator independently checks exact operand values/types.
            numeric = {"int", "bool", "float"}
            scalar = numeric | {"str", "bytes"}
            safe = left_type in scalar and right_type in scalar
            result_type = None
            if left_type in numeric and right_type in numeric:
                result_type = "float" if "float" in {left_type, right_type} or opcode is Opcode.TRUE_DIV else "int"
            elif left_type == right_type and opcode is Opcode.ADD and left_type in {"str", "bytes"}:
                result_type = left_type
            value = self.emit(pair, block, opcode, (("left", 0, left), ("right", 1, right)),
                              builtin=result_type if safe else None)
            if not safe:
                self.barrier(block, "Binary dispatch may call user code.", definition.id, reference)
            return value
        if isinstance(node, ast.UnaryOp):
            child = self.expr(node.operand, block)
            opcode = getattr(Opcode, _UNARY.get(type(node.op), "OPAQUE"))
            kind = self.builtin.get(child)
            safe = kind in {"int", "bool", "float"} and opcode is not Opcode.OPAQUE
            value = self.emit(pair, block, opcode, (("operand", 0, child),),
                              builtin=("int" if kind == "bool" else kind) if safe else None)
            if not safe:
                self.barrier(block, "Unary/truth dispatch is not proven builtin.", definition.id, reference)
            return value
        if isinstance(node, ast.Subscript):
            receiver, index = self.expr(node.value, block), self.expr(node.slice, block)
            value = self.emit(pair, block, Opcode.INDEX, (("receiver", 0, receiver), ("index", 1, index)))
            if self.builtin.get(receiver) not in {"tuple", "list", "str", "bytes"} or self.builtin.get(index) not in {"int", "bool"}:
                self.barrier(block, "Index dispatch is not proven builtin.", definition.id, reference)
            return value
        if isinstance(node, ast.Attribute):
            receiver = self.expr(node.value, block)
            value = self.emit(pair, block, Opcode.ATTRIBUTE, (("receiver", 0, receiver),), attribute=node.attr)
            self.barrier(block, "Attribute lookup may invoke a descriptor or lazy module attribute.", definition.id, reference)
            return value
        if isinstance(node, ast.Call):
            operands = [("callee", 0, self.expr(node.func, block))]
            operands.extend(("argument", index, self.expr(child, block)) for index, child in enumerate(node.args))
            for index, child in enumerate(node.keywords):
                operands.append(("keyword:" + child.arg if child.arg else "keyword_unpack", index,
                                 self.expr(child.value, block)))
                if child.arg is None:
                    self.barrier(block, "Keyword mapping expansion can mutate bindings before later arguments.",
                                 definition.id, reference)
            value = self.emit(pair, block, Opcode.CALL, operands)
            self.barrier(block, "Opaque call may mutate accessible state or bindings.", definition.id, reference)
            return value
        # These expressions have path-, iteration-, suspension- or binding-
        # sensitive evaluation. Their independent children stay in isolated
        # blocks, so an unexecuted walrus/branch cannot update the outer scope.
        operands = []
        if not isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for index, child in enumerate(ast.iter_child_nodes(node)):
                if isinstance(child, ast.expr):
                    nested = self.block(block.scope, block.kind, "opaque-expression")
                    operands.append(("possible_operand", index, self.expr(child, nested)))
        value = self.emit(pair, block, Opcode.OPAQUE, operands)
        self.barrier(block, "Unsupported expression control or dispatch: " + type(node).__name__, definition.id, reference)
        return value

    def bind(self, target, value, block):
        pair = self.operation(target, "binding")
        if pair is None:
            self.barrier(block, "Assignment target lacks unique source correspondence.")
            return
        definition, reference = pair
        assigned = self.emit(pair, block, Opcode.ALIAS if isinstance(target, ast.Name) and value is not None else Opcode.OPAQUE,
                             (("value", 0, value),), builtin=self.builtin.get(value))
        if isinstance(target, ast.Name):
            slots = self.writes.get(definition.id, set())
            if len(slots) == 1 and assigned is not None:
                slot = next(iter(slots))
                self.bind_slot(slot, definition.id, assigned, block, reference)
            else:
                self.barrier(block, "Assignment has no single destination slot.", definition.id, reference)
        elif isinstance(target, (ast.Tuple, ast.List)):
            self.barrier(block, "Unpacking bindings and exceptions need element-level semantics.", definition.id, reference)
            for child in target.elts:
                self.bind(child, None, block)
        else:
            self.barrier(block, "Attribute/index assignment may mutate aliases and user state.", definition.id, reference)

    def bind_slot(self, slot, definition, value, block, reference):
        previous_id = block.env.get(slot)
        previous = self.result.bindings.get(previous_id)
        replacing_unknown = ((previous is not None and not self.release_safe.get(previous.value, False)) or
                             (previous is None and (self.epochs[slot] > 0 or
                              block.scope in self.open_namespaces or
                              self.semantic.slots[slot].direction == "input")))
        if replacing_unknown:
            self.barrier(block, "Overwriting a possibly finalizable value may mutate bindings, including the destination.",
                         definition, reference)
        epoch = self.epochs[slot]
        self.epochs[slot] += 1
        binding = StaticBindingID(_key("binding", definition.wire, slot.wire, epoch))
        position = self.result.operations[definition].position
        self.result.bindings[binding] = StaticBinding(binding, slot, definition, value, block.scope,
                                                    block.key, position, epoch, reference)
        if replacing_unknown:
            return
        if self.semantic.slots[slot].owner == block.scope and block.kind in {"module", "function"}:
            block.env[slot] = binding
        else:
            self.barrier(block, "Nonlocal/global/custom-namespace write remains open.", definition, reference)

    def imports(self, node, block):
        for alias in node.names:
            pair = self.operation(node, "import", alias)
            if pair is None:
                self.barrier(block, "Import lacks source/alias correspondence.")
                continue
            definition, reference = pair
            self.barrier(block, "Loader, module initialization, cache and lazy export semantics are unproven.",
                         definition.id, reference)
            spec = ImportSpec(requested=alias.name if isinstance(node, ast.Import) else node.module or "",
                              symbol=None if isinstance(node, ast.Import) else alias.name,
                              relative_level=0 if isinstance(node, ast.Import) else node.level)
            value = self.emit(pair, block, Opcode.IMPORT, import_spec=spec)
            for slot in self.writes.get(definition.id, ()):
                self.bind_slot(slot, definition.id, value, block, reference)

    def function(self, node, block):
        # Defaults/decorators belong to definition time. Deferred bodies begin
        # with parameter/global bindings unresolved, never with the outer env.
        for expression in list(node.decorator_list) + list(node.args.defaults) + [x for x in node.args.kw_defaults if x]:
            self.expr(expression, block)
        pair = self.operation(node, "function")
        if pair is not None:
            definition, reference = pair
            child = self.block(definition.id, "function", "call")
            self.statements(node.body, child)
        self.barrier(block, "Definition-time decorators/annotations and exported function state remain open.")

    def statements(self, nodes, block):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.function(node, block)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                self.imports(node, block)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                if isinstance(node, ast.AnnAssign):
                    self.barrier(block, "Annotation evaluation policy is not contracted.")
                if node.value is not None:
                    value = self.expr(node.value, block)
                    for target in node.targets if isinstance(node, ast.Assign) else (node.target,):
                        self.bind(target, value, block)
            elif isinstance(node, ast.AugAssign):
                self.expr(node.value, block)
                self.barrier(block, "Augmented assignment may mutate a shared object.")
                self.bind(node.target, None, block)
            elif isinstance(node, (ast.Expr, ast.Return)):
                if node.value is not None:
                    self.expr(node.value, block)
                if isinstance(node, ast.Return):
                    self.barrier(block, "Following source is not proved reachable after return.")
            elif isinstance(node, ast.If):
                self.expr(node.test, block)
                for name, body in (("if", node.body), ("else", node.orelse)):
                    self.statements(body, self.block(block.scope, block.kind, name, block.env))
                self.barrier(block, "Conditional reaching-definition merge is unresolved.")
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                test_block = self.block(block.scope, block.kind, "loop-test") if isinstance(node, ast.While) else block
                self.expr(node.test if isinstance(node, ast.While) else node.iter, test_block)
                for name, body in (("loop", node.body), ("loop-else", node.orelse)):
                    self.statements(body, self.block(block.scope, block.kind, name))
                self.barrier(block, "Loop-carried bindings and zero-trip behavior are unresolved.")
            elif isinstance(node, (ast.Try, getattr(ast, "TryStar", ast.Try))):
                for name, body in (("try", node.body), ("try-else", node.orelse), ("finally", node.finalbody)):
                    self.statements(body, self.block(block.scope, block.kind, name))
                for handler in node.handlers:
                    self.statements(handler.body, self.block(block.scope, block.kind, "except"))
                self.barrier(block, "Exceptional control and reaching-definition merge are unresolved.")
            elif isinstance(node, (ast.Pass, ast.Global, ast.Nonlocal)):
                continue
            elif isinstance(node, ast.ClassDef):
                # Custom class namespaces stay open. Deferred method bodies
                # still have ordinary function scopes and can contain local
                # computations independent of class construction effects.
                for expression in list(node.decorator_list) + list(node.bases) + [item.value for item in node.keywords]:
                    self.expr(expression, block)
                pair = self.operation(node)
                if pair is not None:
                    definition, reference = pair
                    self.emit(pair, block, Opcode.OPAQUE)
                    self.barrier(block, "Class construction/custom namespace is outside the exact subset.",
                                 definition.id, reference)
                    child = self.block(definition.id, "class", "class-definition")
                    self.barrier(child, "Custom class namespace reads and writes are not ordinary local bindings.",
                                 definition.id, reference)
                    self.statements(node.body, child)
                else:
                    self.barrier(block, "Class operation lacks source correspondence.")
            else:
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, ast.expr):
                        self.expr(child, self.block(block.scope, block.kind, "opaque-statement"))
                    elif isinstance(child, ast.stmt):
                        self.statements([child], self.block(block.scope, block.kind, "opaque-body"))
                self.barrier(block, "Unsupported or abrupt statement: " + type(node).__name__)

    def run(self):
        modules = sorted((item for item in self.semantic.modules.values() if item.path and item.fingerprint),
                         key=lambda item: (item.path, item.id.wire))
        seen = set()
        for module in modules:
            if module.path in seen:
                raise ValueError("source path has multiple module identities")
            seen.add(module.path)
            if self.supplied is not None:
                if module.path not in self.supplied or type(self.supplied[module.path]) is not str:
                    raise ValueError("missing decoded source snapshot: " + module.path)
                text = self.supplied[module.path]
            else:
                with tokenize.open(module.path) as source:
                    text = source.read()
            fingerprint = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
            if fingerprint != module.fingerprint:
                raise ValueError("source fingerprint mismatch: " + module.path)
            self.result.sources[module.path] = SourceSnapshot(
                module.path, fingerprint, python_version=f"{sys.version_info.major}.{sys.version_info.minor}")
            self.path = module.path
            tree = ast.parse(text, filename=module.path, type_comments=True)
            self.statements(tree.body, self.block(module.initializer, "module", "initialization"))
        unmodeled = []
        for definition in self.semantic.definitions.values():
            if definition.id not in self.result.operations:
                unmodeled.append(definition.id)
                self.gap("SG operation has no computational rule in this bounded semantic overlay.",
                         operation=definition.id,
                         required_fact="Keep original SG operation; add semantics before treating its result or effects as known.")
        self.result.unmodeled_operations = tuple(sorted(unmodeled, key=lambda item: item.wire))
        self.result.gaps = tuple(self.gaps)
        self.result.assert_valid(self.semantic)
        return self.result


def extract_source_semantics(semantic: SemanticGraph, *, sources: dict[str, str] | None = None):
    """Read exact snapshots and construct ordered computational/binding records."""
    semantic.assert_valid()
    return _Extractor(semantic, sources).run()


def validate_source_semantics(model, semantic: SemanticGraph, *, sources=None):
    """Replay the fixed extractor; record well-formedness alone is not evidence."""
    try:
        model.assert_valid(semantic)
        expected = extract_source_semantics(semantic, sources=sources)
        if model.to_dict() != expected.to_dict():
            return {"valid": False, "errors": ["semantic overlay differs from source replay"]}
    except (ValueError, TypeError, KeyError, OSError, SyntaxError) as exc:
        return {"valid": False, "errors": [str(exc)]}
    return {"valid": True, "errors": []}


__all__ = ["extract_source_semantics", "validate_source_semantics"]
