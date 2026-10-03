"""Non-executing import-to-literal provenance over typed SCAR graphs.

This module resolves only source-backed local module/export candidates and
immutable builtin literal paths.  It never imports a target, invokes a
descriptor, calls target code, or evaluates source text.  Local resolution is
conditional on runtime loader/cache/namespace contracts; it does not prove
that deleting an import preserves initialization effects.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json

from scar.analysis.constants_v2 import (
    BuiltinRuntime,
    ConstantRuntimeRequirement,
    EvaluationBudget,
    evaluate_constants,
)
from scar.analysis.source_semantics_v2 import validate_source_semantics
from scar.ir import semantics_v2 as sm
from scar.ir.record_codec import decode, encode, loads
from scar.ir.v2 import ModuleID, OperationDefinitionID, SemanticGraph, SourceReference, ValueSlotID
from scar.ir.v2._validation import record_errors
from scar.ir.v2.semantic import SemanticNodeKind, SemanticRelation


RULE_VERSION = "scar.import-values.v1"


class ImportValueStatus(str, Enum):
    EXACT_BUILTIN_LITERAL = "EXACT_BUILTIN_LITERAL"
    CONDITIONAL = "CONDITIONAL"
    UNRESOLVED = "UNRESOLVED"
    BLOCKED = "BLOCKED"


class ImportResolutionStatus(str, Enum):
    LOCAL_MODULE_CANDIDATE = "LOCAL_MODULE_CANDIDATE"
    LOCAL_EXPORT_CANDIDATE = "LOCAL_EXPORT_CANDIDATE"
    LOCAL_SUBMODULE_CANDIDATE = "LOCAL_SUBMODULE_CANDIDATE"
    AMBIGUOUS = "AMBIGUOUS"
    EXTERNAL = "EXTERNAL"
    UNRESOLVED = "UNRESOLVED"
    BLOCKED = "BLOCKED"


class ImportConditionKind(str, Enum):
    SOURCE_REPLAY = "SOURCE_REPLAY"
    SOURCE_FILE_SELECTION = "SOURCE_FILE_SELECTION"
    STANDARD_IMPORT_HOOKS = "STANDARD_IMPORT_HOOKS"
    IMPORT_CACHE_STATE = "IMPORT_CACHE_STATE"
    PACKAGE_INITIALIZATION_ORDER = "PACKAGE_INITIALIZATION_ORDER"
    MODULE_INITIALIZATION_COMPLETE = "MODULE_INITIALIZATION_COMPLETE"
    MODULE_INITIALIZATION_EFFECTS = "MODULE_INITIALIZATION_EFFECTS"
    MODULE_EXPORT_NAMESPACE = "MODULE_EXPORT_NAMESPACE"
    MODULE_TYPE_AND_ATTRIBUTE_LOOKUP = "MODULE_TYPE_AND_ATTRIBUTE_LOOKUP"
    LAZY_MODULE_ATTRIBUTE = "LAZY_MODULE_ATTRIBUTE"
    DYNAMIC_REBINDING = "DYNAMIC_REBINDING"
    EXTERNAL_NAMESPACE_MUTATION = "EXTERNAL_NAMESPACE_MUTATION"
    SUBMODULE_ATTRIBUTE_BINDING = "SUBMODULE_ATTRIBUTE_BINDING"
    CONDITIONAL_BINDING = "CONDITIONAL_BINDING"
    CALL_BOUNDARY = "CALL_BOUNDARY"
    CONTROL_BOUNDARY = "CONTROL_BOUNDARY"
    OPAQUE_BOUNDARY = "OPAQUE_BOUNDARY"
    ATTRIBUTE_BOUNDARY = "ATTRIBUTE_BOUNDARY"
    INDEX_BOUNDARY = "INDEX_BOUNDARY"
    IMPORT_BOUNDARY = "IMPORT_BOUNDARY"
    REBIND_BOUNDARY = "REBIND_BOUNDARY"
    STAR_IMPORT = "STAR_IMPORT"
    MUTABLE_VALUE = "MUTABLE_VALUE"
    IMPORT_CYCLE = "IMPORT_CYCLE"
    BUILTIN_INDEX = "BUILTIN_INDEX"
    BUILTIN_RUNTIME_MATCH = "BUILTIN_RUNTIME_MATCH"
    FLOATING_ENVIRONMENT_MATCH = "FLOATING_ENVIRONMENT_MATCH"
    VALUE_IDENTITY_AND_ALIAS = "VALUE_IDENTITY_AND_ALIAS"
    CONSUMER_CLOSURE = "CONSUMER_CLOSURE"
    UNSUPPORTED_IMPORT_FORM = "UNSUPPORTED_IMPORT_FORM"


class ImportConditionStatus(str, Enum):
    SOURCE_SUPPORTED = "SOURCE_SUPPORTED"
    REQUIRED_CONTRACT = "REQUIRED_CONTRACT"
    SOURCE_BLOCKER = "SOURCE_BLOCKER"
    UNKNOWN = "UNKNOWN"


class ImportStepKind(str, Enum):
    LITERAL = "LITERAL"
    BINDING = "BINDING"
    IMPORT_MODULE = "IMPORT_MODULE"
    IMPORT_EXPORT = "IMPORT_EXPORT"
    REEXPORT = "REEXPORT"
    ATTRIBUTE = "ATTRIBUTE"
    SUBMODULE = "SUBMODULE"
    INDEX = "INDEX"
    TUPLE_BUILD = "TUPLE_BUILD"
    BUILTIN_VALUE = "BUILTIN_VALUE"


class ImportGapKind(str, Enum):
    DEPENDENCY = "DEPENDENCY"
    BINDING = "BINDING"
    IMPORT = "IMPORT"
    EXPORT = "EXPORT"
    ATTRIBUTE = "ATTRIBUTE"
    INDEX = "INDEX"
    CYCLE = "CYCLE"
    BUDGET = "BUDGET"
    MUTABLE = "MUTABLE"
    DISPATCH = "DISPATCH"
    EFFECT = "EFFECT"


class SourceReplayStatus(str, Enum):
    NOT_CHECKED = "NOT_CHECKED"
    VALID = "VALID"


class ImportDeletionStatus(str, Enum):
    NOT_PROVEN = "NOT_PROVEN"


@dataclass(frozen=True, slots=True)
class ImportCondition:
    kind: ImportConditionKind
    status: ImportConditionStatus
    reason: str
    operation: OperationDefinitionID | None = None
    module: ModuleID | None = None
    source: SourceReference | None = None
    runtime_requirement: ConstantRuntimeRequirement | None = None
    runtime: BuiltinRuntime | None = None

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("import condition requires a concrete reason")


@dataclass(frozen=True, slots=True)
class ImportResolutionContract:
    operation: OperationDefinitionID
    result: sm.StaticValueID | None
    source: SourceReference
    form: sm.ImportForm
    requested: str
    relative_level: int
    symbol: str | None
    bound_name: str | None
    asname: str | None
    requested_module: ModuleID | None
    bound_module: ModuleID | None
    export_slot: ValueSlotID | None
    export_binding: sm.StaticBindingID | None
    status: ImportResolutionStatus
    conditions: tuple[ImportCondition, ...]

    def __post_init__(self) -> None:
        if self.relative_level < 0:
            raise ValueError("relative import level must be non-negative")
        if self.form is sm.ImportForm.FROM and self.symbol is None:
            raise ValueError("from-import contract requires a symbol")
        if self.form is sm.ImportForm.MODULE and self.symbol is not None:
            raise ValueError("module-import contract cannot carry a symbol")
        if self.form is sm.ImportForm.FROM and self.bound_module is not None:
            raise ValueError("from-import binds an export, not a module")


@dataclass(frozen=True, slots=True)
class ImportValueStep:
    kind: ImportStepKind
    value: sm.StaticValueID
    source: SourceReference
    operation: OperationDefinitionID | None = None
    module: ModuleID | None = None
    slot: ValueSlotID | None = None
    binding: sm.StaticBindingID | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ImportValueGap:
    kind: ImportGapKind
    reason: str
    operation: OperationDefinitionID | None = None
    source: SourceReference | None = None

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("import value gap requires a reason")


@dataclass(frozen=True, slots=True)
class ImportValueFact:
    value: sm.StaticValueID
    status: ImportValueStatus
    literal: sm.PythonLiteral | None = None
    source_value: sm.StaticValueID | None = None
    provenance_id: str | None = None
    conditions: tuple[ImportCondition, ...] = ()
    gaps: tuple[ImportValueGap, ...] = ()

    def __post_init__(self) -> None:
        if self.status in (ImportValueStatus.EXACT_BUILTIN_LITERAL, ImportValueStatus.CONDITIONAL):
            if self.literal is None or self.provenance_id is None:
                raise ValueError("literal fact requires a literal and provenance")
        elif self.literal is not None or self.provenance_id is not None:
            raise ValueError("unresolved/blocked fact cannot carry a replacement literal")


@dataclass(frozen=True, slots=True)
class ImportValueProvenance:
    id: str
    target: sm.StaticValueID
    source_value: sm.StaticValueID
    literal: sm.PythonLiteral
    steps: tuple[ImportValueStep, ...]
    conditions: tuple[ImportCondition, ...]


@dataclass(frozen=True, slots=True)
class ImportValueGuidance:
    target: sm.StaticValueID
    source: SourceReference
    status: ImportValueStatus
    literal: sm.PythonLiteral
    provenance_id: str
    guards: tuple[ImportCondition, ...]
    selection_status: str = "NOT_SELECTED"
    cost_status: str = "PENDING"
    applied: bool = False
    import_deletion: ImportDeletionStatus = ImportDeletionStatus.NOT_PROVEN
    deletion_gaps: tuple[str, ...] = (
        "Import/module initialization effects and exceptions require an independent proof.",
        "The deleted import region's complete consumer and effect closure is not proved.",
    )

    def __post_init__(self) -> None:
        if self.selection_status != "NOT_SELECTED" or self.cost_status != "PENDING" or self.applied:
            raise ValueError("import value guidance is report-only and not selected")
        if self.import_deletion is not ImportDeletionStatus.NOT_PROVEN:
            raise ValueError("constant provenance cannot prove import deletion")


@dataclass(frozen=True, slots=True)
class ImportEvaluationUsage:
    nodes: int
    steps: int
    work: int
    output_bytes: int


@dataclass(frozen=True, slots=True)
class _ReportRecord:
    schema: str
    schema_version: int
    rule_version: str
    semantic_digest: str
    source_semantics_digest: str
    budget: EvaluationBudget
    targets: tuple[sm.StaticValueID, ...]
    contracts: tuple[ImportResolutionContract, ...]
    facts: tuple[ImportValueFact, ...]
    provenances: tuple[ImportValueProvenance, ...]
    guidance: tuple[ImportValueGuidance, ...]
    usage: ImportEvaluationUsage
    source_replay: SourceReplayStatus
    required_source_preconditions: tuple[sm.SourceExecutionPrecondition, ...]


class ImportValueReport:
    """Deterministically rederived import provenance and guarded suggestions."""

    SCHEMA = "scar.import-values"
    SCHEMA_VERSION = 1

    def __init__(self, semantic, source_semantics, *, budget, targets, contracts,
                 facts, provenances, guidance, usage, source_replay=SourceReplayStatus.NOT_CHECKED):
        self.semantic = semantic
        self.source_semantics = source_semantics
        self.rule_version = RULE_VERSION
        self.semantic_digest = _digest(semantic.to_dict())
        self.source_semantics_digest = _digest(source_semantics.to_dict())
        self.budget = budget
        self.targets = targets
        self.contracts = contracts
        self.facts = facts
        self.provenances = provenances
        self.guidance = guidance
        self.usage = usage
        self.source_replay = source_replay
        self.required_source_preconditions = tuple(sorted(
            source_semantics.required_preconditions, key=lambda item: item.value))

    def _record(self):
        return _ReportRecord(self.SCHEMA, self.SCHEMA_VERSION, self.rule_version,
            self.semantic_digest, self.source_semantics_digest, self.budget, self.targets,
            tuple(self.contracts[key] for key in sorted(self.contracts, key=lambda item: item.wire)),
            tuple(self.facts[key] for key in sorted(self.facts, key=lambda item: item.wire)),
            tuple(self.provenances[key] for key in sorted(self.provenances)),
            tuple(self.guidance[key] for key in sorted(self.guidance, key=lambda item: item.wire)),
            self.usage, self.source_replay, self.required_source_preconditions)

    def validate(self, semantic=None, source_semantics=None, *,
                 verification_budget=EvaluationBudget()):
        semantic = self.semantic if semantic is None else semantic
        source_semantics = self.source_semantics if source_semantics is None else source_semantics
        try:
            _check_verification_budget(self.budget, verification_budget)
            if type(semantic) is not SemanticGraph or type(source_semantics) is not sm.SourceSemanticsGraph:
                return {"valid": False, "errors": ["semantic graph and source semantics are required"]}
            if not semantic.validate()["valid"]:
                return {"valid": False, "errors": ["semantic graph is invalid"]}
            if not source_semantics.validate(semantic)["valid"]:
                return {"valid": False, "errors": ["source semantics graph is invalid"]}
            errors = record_errors(self._record(), _ReportRecord, "import_value_report")
            if errors:
                return {"valid": False, "errors": errors}
            if self.semantic_digest != _digest(semantic.to_dict()):
                return {"valid": False, "errors": ["semantic graph digest differs"]}
            if self.source_semantics_digest != _digest(source_semantics.to_dict()):
                return {"valid": False, "errors": ["source semantics digest differs"]}
            if self.source_replay is SourceReplayStatus.VALID:
                replay = validate_source_semantics(source_semantics, semantic)
                if not replay["valid"]:
                    return {"valid": False, "errors": ["source replay no longer validates: " + "; ".join(replay["errors"])]}
            expected = _evaluate_import_values(semantic, source_semantics, targets=self.targets,
                budget=self.budget, source_replay=self.source_replay)
            if encode(self._record()) != encode(expected._record()):
                return {"valid": False, "errors": ["import facts/contracts/provenance differ from fixed-rule recomputation"]}
            return {"valid": True, "errors": []}
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError, SyntaxError) as error:
            return {"valid": False, "errors": [str(error)]}

    def assert_valid(self, semantic=None, source_semantics=None, *,
                     verification_budget=EvaluationBudget()):
        result = self.validate(semantic, source_semantics, verification_budget=verification_budget)
        if not result["valid"]:
            raise ValueError("invalid import value report: " + "; ".join(result["errors"]))
        return result

    def to_dict(self, *, verification_budget=EvaluationBudget()):
        self.assert_valid(verification_budget=verification_budget)
        return encode(self._record())

    def to_json(self, *, verification_budget=EvaluationBudget()):
        return json.dumps(self.to_dict(verification_budget=verification_budget), sort_keys=True,
                          separators=(",", ":"), ensure_ascii=True, allow_nan=False)

    @classmethod
    def from_dict(cls, document, *, semantic, source_semantics,
                  verification_budget=EvaluationBudget()):
        record = decode(_ReportRecord, document)
        if record.schema != cls.SCHEMA or record.schema_version != cls.SCHEMA_VERSION:
            raise ValueError("unsupported import value report schema/version")
        _check_verification_budget(record.budget, verification_budget)
        expected = _evaluate_import_values(semantic, source_semantics, targets=record.targets,
            budget=record.budget, source_replay=record.source_replay)
        if record != expected._record():
            raise ValueError("import report differs from fixed-rule recomputation")
        if record.source_replay is SourceReplayStatus.VALID:
            replay = validate_source_semantics(source_semantics, semantic)
            if not replay["valid"]:
                raise ValueError("source replay does not validate: " + "; ".join(replay["errors"]))
        return expected

    @classmethod
    def from_json(cls, payload, *, semantic, source_semantics,
                  verification_budget=EvaluationBudget()):
        return cls.from_dict(loads(payload), semantic=semantic,
            source_semantics=source_semantics, verification_budget=verification_budget)

    def validate_source_replay(self, *, sources=None):
        """Independently replay the source extractor; this says nothing about import effects."""
        replay = validate_source_semantics(self.source_semantics, self.semantic, sources=sources)
        if not replay["valid"]:
            raise ValueError("source replay failed: " + "; ".join(replay["errors"]))
        return _evaluate_import_values(self.semantic, self.source_semantics,
            targets=self.targets, budget=self.budget, source_replay=SourceReplayStatus.VALID)

    def summary(self):
        counts = {status.value: 0 for status in ImportValueStatus}
        for fact in self.facts.values():
            counts[fact.status.value] += 1
        return {
            "schema": self.SCHEMA,
            "schema_version": self.SCHEMA_VERSION,
            "rule_version": self.rule_version,
            "source_replay": self.source_replay.value,
            "semantic_digest": self.semantic_digest,
            "source_semantics_digest": self.source_semantics_digest,
            "counts": counts,
            "contract_count": len(self.contracts),
            "provenance_count": len(self.provenances),
            "guidance_count": len(self.guidance),
            "targets": [{
                "value": identifier.wire,
                "status": fact.status.value,
                "literal": _display_literal(fact.literal),
                "gap_reasons": [gap.reason for gap in fact.gaps],
                "condition_kinds": sorted({condition.kind.value for condition in fact.conditions}),
            } for identifier, fact in list(sorted(self.facts.items(), key=lambda item: item[0].wire))[:20]],
            "omitted_targets": max(0, len(self.facts) - 20),
            "usage": encode(self.usage),
            "guidance_policy": {
                "selection_status": "NOT_SELECTED",
                "cost_status": "PENDING",
                "applied": False,
                "import_deletion": "NOT_PROVEN",
            },
        }


@dataclass(frozen=True, slots=True)
class _Resolved:
    kind: str
    literal: sm.PythonLiteral | None = None
    module: ModuleID | None = None
    loaded_modules: tuple[ModuleID, ...] = ()
    source_value: sm.StaticValueID | None = None
    steps: tuple[ImportValueStep, ...] = ()
    conditions: tuple[ImportCondition, ...] = ()
    gaps: tuple[ImportValueGap, ...] = ()
    conditional: bool = False
    blocker: bool = False


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _check_verification_budget(stored, ceiling):
    if type(stored) is not EvaluationBudget or type(ceiling) is not EvaluationBudget:
        raise TypeError("budgets must be EvaluationBudget")
    stored.__post_init__()
    ceiling.__post_init__()
    if any(getattr(stored, name) > getattr(ceiling, name) for name in stored.__dataclass_fields__):
        raise ValueError("report budget exceeds verification budget")


def _display_literal(literal):
    if literal is None:
        return None
    if literal.kind is sm.LiteralKind.TUPLE:
        return "(" + ", ".join(_display_literal(item) for item in literal.items) + ("," if len(literal.items) == 1 else "") + ")"
    if literal.kind is sm.LiteralKind.STR:
        return repr(literal.payload)
    if literal.kind is sm.LiteralKind.BYTES:
        return repr(bytes.fromhex(literal.payload))
    if literal.kind is sm.LiteralKind.FLOAT64:
        return repr(literal.to_python())
    return repr(literal.to_python())


def _ids_of_kind(edges, kind):
    return tuple(edge.target.id for edge in edges if edge.target.kind is kind)


class _Resolver:
    def __init__(self, semantic, graph, budget, source_replay):
        self.semantic, self.graph, self.budget = semantic, graph, budget
        self.source_replay = source_replay
        self.operations = graph.operations
        self.producers = {value.id: self.operations.get(value.producer)
                          for value in graph.values.values()}
        self.module_by_id = semantic.modules
        self.module_by_initializer = {module.initializer: module.id
                                      for module in semantic.modules.values()
                                      if module.initializer is not None}
        self.module_names = {}
        for module in semantic.modules.values():
            self.module_names.setdefault(module.name, []).append(module.id)
        self.edges_by_source_relation = {}
        for edge in semantic.edges.values():
            self.edges_by_source_relation.setdefault((edge.relation, edge.source.id), []).append(edge)
        self.module_initializers = {module.initializer for module in semantic.modules.values()
                                    if module.initializer is not None}
        self.bindings_by_slot_scope = {}
        for binding in graph.bindings.values():
            self.bindings_by_slot_scope.setdefault((binding.slot, binding.scope), []).append(binding)
        self.cross_block_binding_slots = set()
        for items in self.bindings_by_slot_scope.values():
            items.sort(key=lambda binding: (binding.position, binding.epoch, binding.id.wire))
            if len({item.block for item in items}) > 1:
                self.cross_block_binding_slots.add((items[0].slot, items[0].scope))
        self.boundaries_by_scope_block = {}
        for boundary in graph.boundaries:
            self.boundaries_by_scope_block.setdefault((boundary.scope, boundary.block), []).append(boundary)
        for items in self.boundaries_by_scope_block.values():
            items.sort(key=lambda boundary: boundary.position)
        self.operations_by_scope = {}
        for operation in graph.operations.values():
            self.operations_by_scope.setdefault(operation.scope, []).append(operation)
        for items in self.operations_by_scope.values():
            items.sort(key=lambda operation: (operation.block, operation.position, operation.operation.wire))
        self.operation_module_cache = {}
        self.module_export_slots = {}
        for module in semantic.modules.values():
            if module.initializer is None:
                continue
            slots = {}
            for edge in self.edges_by_source_relation.get((SemanticRelation.REEXPORTS, module.id), ()):
                if edge.target.kind is SemanticNodeKind.VALUE_SLOT:
                    slot = semantic.slots.get(edge.target.id)
                    if slot is not None:
                        slots.setdefault(slot.name, []).append(slot.slot_id)
            self.module_export_slots[module.id] = {
                name: tuple(dict.fromkeys(items)) for name, items in slots.items()}
        direct_blocks = {}
        for operation in self.operations.values():
            definition = semantic.definitions.get(operation.operation)
            if definition is not None and definition.parent_id in self.module_by_initializer:
                direct_blocks.setdefault(definition.parent_id, set()).add(operation.block)
        self.module_main_blocks = {
            initializer: next(iter(blocks)) if len(blocks) == 1 else None
            for initializer, blocks in direct_blocks.items()}
        self.contracts = {}
        self.facts = {}
        self.provenances = {}
        self.guidance = {}
        self.active_values = set()
        self.active_imports = set()
        self.memo = {}
        self.resolve_depth_limit = 192
        self.base_report = None
        self._base_target_cache = {}
        self._base_safe_visits = 0
        self.base_target_values = ()
        self.import_graph = self._build_import_graph()
        self.module_cycle_cache = self._index_module_cycles()
        self.semantic_digest_value = _digest(semantic.to_dict())
        self.source_semantics_digest_value = _digest(graph.to_dict())
        self.usage = {"nodes": 0, "steps": 0, "work": 0, "output_bytes": 0}
        self.budget_exhausted = False
        self._requested_targets = ()

    def _spend(self, field, amount=1, limit=None):
        cap = getattr(self.budget, limit or {"nodes": "max_nodes", "steps": "max_steps",
                                             "work": "max_work", "output_bytes": "max_total_output_bytes"}[field])
        if amount > cap - self.usage[field]:
            self.budget_exhausted = True
            return False
        self.usage[field] += amount
        return True

    def _collect_base_targets(self):
        """Pick immutable local export/explicit targets for one bounded base pass."""
        selected = set()
        for target in self._requested_targets:
            if self._base_safe(target):
                selected.add(target)
        for module in self.semantic.modules.values():
            if module.initializer is None:
                continue
            for slot_ids in self.module_export_slots.get(module.id, {}).values():
                for slot_id in slot_ids:
                    binding = self._latest_export_binding(module.id, slot_id)
                    if binding is not None and self._base_safe(binding.value):
                        selected.add(binding.value)
        ordered = sorted(selected, key=lambda item: item.wire)
        return tuple(ordered[:self.budget.max_nodes])

    def _base_safe(self, value_id, seen=None, depth=0):
        if value_id in self._base_target_cache:
            return self._base_target_cache[value_id]
        self._base_safe_visits += 1
        if self._base_safe_visits > self.budget.max_nodes or depth >= self.resolve_depth_limit:
            self._base_target_cache[value_id] = False
            return False
        seen = set() if seen is None else seen
        if value_id in seen:
            self._base_target_cache[value_id] = False
            return False
        seen.add(value_id)
        operation = self.producers.get(value_id)
        if operation is None:
            self._base_target_cache[value_id] = False
            return False
        if operation.opcode is sm.Opcode.LITERAL:
            self._base_target_cache[value_id] = True
            return True
        if operation.opcode in {sm.Opcode.IMPORT, sm.Opcode.ATTRIBUTE, sm.Opcode.INDEX,
                                sm.Opcode.CALL, sm.Opcode.OPAQUE, sm.Opcode.BUILD_LIST,
                                sm.Opcode.BUILD_DICT, sm.Opcode.BUILD_SET, sm.Opcode.MATMUL}:
            self._base_target_cache[value_id] = False
            return False
        dependencies = tuple(item.value for item in operation.operands)
        if operation.opcode is sm.Opcode.READ:
            use = self.graph.uses.get(operation.binding_use)
            if use is None or use.status is not sm.BindingStatus.EXACT or len(use.reaching) != 1:
                self._base_target_cache[value_id] = False
                return False
            binding = self.graph.bindings.get(use.reaching[0])
            if binding is None:
                self._base_target_cache[value_id] = False
                return False
            dependencies += (binding.value,)
        if not dependencies:
            self._base_target_cache[value_id] = False
            return False
        result = all(self._base_safe(child, set(seen), depth + 1) for child in dependencies)
        self._base_target_cache[value_id] = result
        return result

    def _build_import_graph(self):
        graph = {}
        for operation in self.operations.values():
            if operation.opcode is not sm.Opcode.IMPORT or operation.scope not in self.module_initializers:
                continue
            targets = _ids_of_kind(self.edges_by_source_relation.get(
                (SemanticRelation.IMPORTS, operation.operation), ()), SemanticNodeKind.MODULE)
            spec = operation.import_spec
            if (spec is not None and spec.form is sm.ImportForm.FROM and spec.symbol
                    and len(targets) == 1
                    and targets[0] == self.module_by_initializer.get(operation.scope)):
                module_id = targets[0]
                module = self.module_by_id.get(module_id)
                main_block = self.module_main_blocks.get(operation.scope)
                own_scope = (module is not None and operation.block == main_block)
                slots = self._import_export_slots(operation, module_id, spec.symbol)
                current_namespace_hit = own_scope and any(
                    self._latest_export_binding(module_id, slot,
                        before_position=operation.position) is not None for slot in slots)
                if current_namespace_hit:
                    # IMPORT_FROM first reads the existing partially initialized
                    # package namespace; this does not initialize that package again.
                    continue
                child = self._submodule(module_id, spec.symbol)
                if child is not None:
                    targets = (child,)
                else:
                    # A missing self from-list name does not itself restart the
                    # current module. Lazy hooks remain an unresolved condition.
                    continue
            current_module = self.module_by_initializer.get(operation.scope)
            if current_module is not None and current_module in targets:
                # An ordinary import of the active module returns its partial
                # sys.modules object; it does not initialize that module again.
                targets = tuple(target for target in targets if target != current_module)
            if targets:
                graph.setdefault(operation.scope, set()).update(targets)
        return graph

    def _module_for_operation(self, operation):
        """Return the indexed source module enclosing this import operation."""
        if operation.operation in self.operation_module_cache:
            return self.operation_module_cache[operation.operation]
        current = operation.scope
        seen = set()
        result = None
        while current is not None and current not in seen:
            seen.add(current)
            result = self.module_by_initializer.get(current)
            if result is not None:
                break
            definition = self.semantic.definitions.get(current)
            current = definition.parent_id if definition is not None else None
        self.operation_module_cache[operation.operation] = result
        return result

    def _expected_requested_name(self, operation, spec):
        if spec.form is sm.ImportForm.MODULE or spec.relative_level == 0:
            return spec.requested
        current_id = self._module_for_operation(operation)
        current = self.module_by_id.get(current_id)
        if current is None or current.package not in self.semantic.packages:
            return None
        package_name = self.semantic.packages[current.package].name
        parts = package_name.split(".") if package_name else []
        if spec.relative_level > len(parts):
            return None
        ascents = spec.relative_level - 1
        base = parts[:len(parts) - ascents]
        if spec.requested:
            base.extend(spec.requested.split("."))
        return ".".join(base)

    def _import_source_mismatch(self, operation, spec, requested_ids):
        if spec.form is sm.ImportForm.FROM and spec.relative_level:
            current_id = self._module_for_operation(operation)
            current = self.module_by_id.get(current_id)
            package = self.semantic.packages.get(current.package) if current is not None and current.package is not None else None
            depth = len(package.name.split(".")) if package is not None and package.name else 0
            if spec.relative_level > depth:
                return "The relative import ascends beyond the indexed top-level package and cannot resolve at runtime."
        expected_name = self._expected_requested_name(operation, spec)
        if expected_name is None:
            return "The importing operation has no indexed package context for its relative import."
        if len(requested_ids) != 1:
            return "The semantic import relation does not identify exactly one requested module."
        requested_module = self.module_by_id.get(requested_ids[0])
        if requested_module is None or requested_module.name != expected_name:
            actual = requested_module.name if requested_module is not None else "<missing>"
            return f"The semantic import edge names {actual!r}, while source syntax requests {expected_name!r}."
        if len(self.module_names.get(expected_name, ())) != 1:
            return f"The requested module name {expected_name!r} does not identify one unique semantic module."
        return None

    def _module_cycle(self, start):
        """Return whether source-local module initializer imports form a cycle."""
        return self.module_cycle_cache.get(start, False)

    def _index_module_cycles(self):
        """Mark cycle members once with an iterative DFS over the indexed graph."""
        adjacency = {}
        local_ids = set(self.module_by_id)
        for module in self.module_by_id.values():
            if module.initializer is None:
                continue
            adjacency[module.id] = tuple(sorted(
                (target for target in self.import_graph.get(module.initializer, ()) if target in local_ids),
                key=lambda item: item.wire))
        color = {}
        cyclic = set()
        for root in sorted(adjacency, key=lambda item: item.wire):
            if color.get(root, 0):
                continue
            color[root] = 1
            stack = [root]
            positions = {root: 0}
            next_child = [0]
            while stack:
                node = stack[-1]
                children = adjacency.get(node, ())
                cursor = next_child[-1]
                if cursor >= len(children):
                    color[node] = 2
                    positions.pop(node, None)
                    stack.pop()
                    next_child.pop()
                    continue
                child = children[cursor]
                next_child[-1] += 1
                state = color.get(child, 0)
                if state == 0:
                    color[child] = 1
                    positions[child] = len(stack)
                    stack.append(child)
                    next_child.append(0)
                elif state == 1:
                    cyclic.update(stack[positions[child]:])
        return {identifier: identifier in cyclic for identifier in self.module_by_id}

    def _condition(self, kind, status, reason, *, operation=None, module=None, source=None,
                   runtime_requirement=None, runtime=None):
        record = ImportCondition(kind, status, reason, operation, module, source,
                                 runtime_requirement, runtime)
        size = len(reason.encode("utf-8", "surrogatepass"))
        if source is not None:
            size += len(source.path.encode("utf-8", "surrogatepass")) + len(source.fingerprint)
        if not self._spend("steps") or not self._spend("output_bytes", size, "max_total_output_bytes"):
            self.budget_exhausted = True
        return record

    def _append_step(self, steps, kind, value, *, operation=None, module=None,
                     slot=None, binding=None, detail=""):
        record = self.graph.values.get(value)
        source = record.source if record is not None else self.operations[operation].source
        item = ImportValueStep(kind, value, source, operation, module, slot, binding, detail)
        size = len(detail.encode("utf-8", "surrogatepass")) + len(source.path.encode("utf-8", "surrogatepass")) + len(source.fingerprint)
        if not self._spend("output_bytes", size, "max_total_output_bytes"):
            self.budget_exhausted = True
            return ()
        if len(steps) + 1 > self.budget.max_steps - self.usage["steps"]:
            self.budget_exhausted = True
            return ()
        if not self._spend("steps", len(steps) + 1):
            return ()
        return tuple(steps) + (item,)

    def _join_steps(self, *groups):
        count = sum(len(group) for group in groups)
        if count > self.budget.max_steps - self.usage["steps"]:
            self.budget_exhausted = True
            return ()
        if not self._spend("steps", count):
            return ()
        return tuple(item for group in groups for item in group)

    def _record_steps(self, *groups):
        return self._join_steps(*groups)

    def _with_steps(self, resolved, steps):
        return replace(resolved, steps=self._record_steps(resolved.steps, steps))

    def _merge_resolved(self, items, reason, operation):
        if not items:
            return _Resolved("unresolved", gaps=(ImportValueGap(ImportGapKind.DEPENDENCY,
                reason, operation.operation, operation.source),))
        condition_count = sum(len(item.conditions) for item in items)
        gap_count = sum(len(item.gaps) for item in items)
        if (condition_count > self.budget.max_steps - self.usage["steps"]
                or gap_count > self.budget.max_nodes - self.usage["nodes"]):
            self.budget_exhausted = True
            return _Resolved("blocked", gaps=(ImportValueGap(ImportGapKind.BUDGET,
                "Import merge output exceeds the remaining condition/node budget.",
                operation.operation, operation.source),), blocker=True)
        self._spend("steps", condition_count)
        self._spend("nodes", gap_count)
        conditions = _unique_conditions(condition for item in items for condition in item.conditions)
        gaps = tuple(gap for item in items for gap in item.gaps)
        steps = self._record_steps(*(item.steps for item in items))
        if self.budget_exhausted:
            return _Resolved("blocked", steps=steps, conditions=conditions,
                gaps=(ImportValueGap(ImportGapKind.BUDGET,
                    "Import provenance output or step budget exceeded.", operation.operation,
                    operation.source),), blocker=True)
        if any(item.kind == "blocked" or item.blocker for item in items):
            return _Resolved("blocked", steps=steps, conditions=conditions,
                gaps=gaps or (ImportValueGap(ImportGapKind.DEPENDENCY, reason, operation.operation, operation.source),), blocker=True)
        literals = [item.literal for item in items if item.kind == "literal"]
        if len(literals) == len(items) and literals and all(item == literals[0] for item in literals[1:]):
            return _Resolved("literal", literals[0], source_value=items[0].source_value,
                steps=steps, conditions=conditions, gaps=gaps, conditional=True)
        modules = [item.module for item in items]
        if all(item.kind == "module" for item in items) and modules and all(item == modules[0] for item in modules[1:]):
            return _Resolved("module", module=modules[0],
                loaded_modules=tuple(dict.fromkeys(module for item in items for module in item.loaded_modules)),
                source_value=items[0].source_value, steps=steps, conditions=conditions,
                gaps=gaps, conditional=True)
        return _Resolved("unresolved", steps=steps, conditions=conditions,
            gaps=gaps + (ImportValueGap(ImportGapKind.BINDING,
                reason, operation.operation, operation.source),), conditional=True)

    def _remaining_budget(self):
        limits = {}
        for name, attr in (("max_nodes", "nodes"), ("max_steps", "steps"),
                           ("max_work", "work"), ("max_total_output_bytes", "output_bytes")):
            remaining = getattr(self.budget, name) - self.usage[attr]
            if remaining < 1:
                return None
            limits[name] = remaining
        for name in ("max_int_bits", "max_sequence_items", "max_bytes", "max_literal_depth"):
            limits[name] = getattr(self.budget, name)
        return EvaluationBudget(**limits)

    def _operation_boundary(self, operation, kind):
        for boundary in self.boundaries_by_scope_block.get((operation.scope, operation.block), ()):
            if boundary.operation == operation.operation and boundary.kind is kind:
                return boundary
        return None

    def _ensure_base_report(self):
        if self.base_report is not None:
            return self.base_report
        if not self.base_target_values:
            self.base_report = False
            return self.base_report
        remaining = self._remaining_budget()
        if remaining is None:
            self.budget_exhausted = True
            self.base_report = False
            return self.base_report
        try:
            report = evaluate_constants(self.graph, targets=self.base_target_values, budget=remaining)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            self.base_report = False
            self.base_error = str(error)
            return self.base_report
        self.base_report = report
        self._spend("nodes", report.usage.nodes, "max_nodes")
        self._spend("steps", report.usage.steps, "max_steps")
        self._spend("work", report.usage.work, "max_work")
        self._spend("output_bytes", report.usage.output_bytes, "max_total_output_bytes")
        return self.base_report

    def _source_fingerprint_condition(self, module_id, operation):
        module = self.module_by_id.get(module_id)
        if module is None or module.path is None or module.fingerprint is None or module.initializer is None:
            return self._condition(ImportConditionKind.SOURCE_FILE_SELECTION,
                ImportConditionStatus.SOURCE_BLOCKER, "The imported module has no indexed local source file.",
                operation=operation, module=module_id)
        snapshot = self.graph.sources.get(module.path)
        if snapshot is None or snapshot.fingerprint != module.fingerprint:
            return self._condition(ImportConditionKind.SOURCE_FILE_SELECTION,
                ImportConditionStatus.SOURCE_BLOCKER,
                "The source semantics snapshot does not match the indexed module fingerprint.",
                operation=operation, module=module_id)
        return self._condition(ImportConditionKind.SOURCE_FILE_SELECTION,
            ImportConditionStatus.REQUIRED_CONTRACT,
            "Prove the runtime import loader selects this indexed source file.",
            operation=operation, module=module_id)

    def _module_import_conditions(self, operation, requested_module):
        result = [self._condition(ImportConditionKind.SOURCE_REPLAY,
            ImportConditionStatus.SOURCE_SUPPORTED if self.source_replay is SourceReplayStatus.VALID
            else ImportConditionStatus.REQUIRED_CONTRACT,
            "Replay the fixed source extractor independently before treating syntax links as source facts.",
            operation=operation.operation, source=operation.source)]
        result.append(self._condition(ImportConditionKind.STANDARD_IMPORT_HOOKS,
            ImportConditionStatus.REQUIRED_CONTRACT,
            "Prove builtins.__import__, meta_path and path_hooks select the indexed local module.",
            operation=operation.operation, module=requested_module, source=operation.source))
        result.append(self._condition(ImportConditionKind.IMPORT_CACHE_STATE,
            ImportConditionStatus.REQUIRED_CONTRACT,
            "Prove sys.modules/cache state and reload timing match ordinary source initialization.",
            operation=operation.operation, module=requested_module, source=operation.source))
        result.append(self._condition(ImportConditionKind.PACKAGE_INITIALIZATION_ORDER,
            ImportConditionStatus.REQUIRED_CONTRACT,
            "Prove parent packages and the requested module initialize in the source-indexed order.",
            operation=operation.operation, module=requested_module, source=operation.source))
        result.append(self._condition(ImportConditionKind.MODULE_INITIALIZATION_EFFECTS,
            ImportConditionStatus.REQUIRED_CONTRACT,
            "Preserve module initialization effects, exceptions, registrations and externally visible state independently of the value path.",
            operation=operation.operation, module=requested_module, source=operation.source))
        result.append(self._condition(ImportConditionKind.EXTERNAL_NAMESPACE_MUTATION,
            ImportConditionStatus.REQUIRED_CONTRACT,
            "Exclude callbacks, cycles, threads and external code that mutate the importing or exporting namespace.",
            operation=operation.operation, module=requested_module, source=operation.source))
        if requested_module is not None:
            result.append(self._source_fingerprint_condition(requested_module, operation.operation))
            requested = self.module_by_id.get(requested_module)
            owner = self._module_for_operation(operation)
            same_initializer = (requested is not None and owner == requested_module
                and operation.scope == requested.initializer)
            if not same_initializer:
                result.append(self._condition(ImportConditionKind.MODULE_INITIALIZATION_COMPLETE,
                    ImportConditionStatus.REQUIRED_CONTRACT,
                    "Prove this import use observes the requested module after its initializer has completed, rather than a partial sys.modules entry in a cycle or callback.",
                    operation=operation.operation, module=requested_module, source=operation.source))
            if self._module_cycle(requested_module):
                result.append(self._condition(ImportConditionKind.IMPORT_CYCLE,
                    ImportConditionStatus.SOURCE_BLOCKER,
                    "The indexed module initialization graph contains a cycle and may expose a partial namespace.",
                    operation=operation.operation, module=requested_module, source=operation.source))
        return tuple(result)

    def _requested_modules(self, operation):
        return _ids_of_kind(self.edges_by_source_relation.get(
            (SemanticRelation.IMPORTS, operation.operation), ()), SemanticNodeKind.MODULE)

    def _import_contract(self, operation):
        if operation.operation in self.contracts:
            return self.contracts[operation.operation]
        spec = operation.import_spec
        if spec is None or operation.result is None:
            contract = ImportResolutionContract(operation.operation,
                operation.result, operation.source,
                sm.ImportForm.MODULE, "", 0, None, None, None, None, None, None, None,
                ImportResolutionStatus.UNRESOLVED,
                (self._condition(ImportConditionKind.UNSUPPORTED_IMPORT_FORM,
                    ImportConditionStatus.SOURCE_BLOCKER,
                    "Import operation is missing a typed import specification or result.",
                    operation=operation.operation, source=operation.source),))
            self.contracts[operation.operation] = contract
            return contract
        if spec.form is sm.ImportForm.FROM and spec.symbol == "*":
            contract = ImportResolutionContract(operation.operation, operation.result,
                operation.source, spec.form, spec.requested, spec.relative_level,
                spec.symbol, spec.bound_name, spec.asname, None, None, None, None,
                ImportResolutionStatus.BLOCKED,
                (self._condition(ImportConditionKind.STAR_IMPORT,
                    ImportConditionStatus.SOURCE_BLOCKER,
                    "Star import can bind an arbitrary runtime namespace and has no finite static export target.",
                    operation=operation.operation, source=operation.source),))
            self.contracts[operation.operation] = contract
            return contract
        requested_ids = self._requested_modules(operation)
        source_mismatch = self._import_source_mismatch(operation, spec, requested_ids)
        requested_id = requested_ids[0] if len(requested_ids) == 1 else None
        if source_mismatch is not None:
            conditions = [self._condition(ImportConditionKind.SOURCE_FILE_SELECTION,
                ImportConditionStatus.SOURCE_BLOCKER, source_mismatch,
                operation=operation.operation, source=operation.source)]
            contract = ImportResolutionContract(operation.operation, operation.result,
                operation.source, spec.form, spec.requested, spec.relative_level,
                spec.symbol, spec.bound_name, spec.asname, requested_id,
                spec.bound_module, None, None, ImportResolutionStatus.BLOCKED,
                tuple(conditions))
            self.contracts[operation.operation] = contract
            return contract
        conditions = list(self._module_import_conditions(operation, requested_id))
        export_slot = None
        export_binding = None
        status = ImportResolutionStatus.UNRESOLVED
        bound_module = spec.bound_module
        if spec.form is sm.ImportForm.MODULE:
            expected_bound_name = spec.asname or spec.requested.split(".")[0]
            expected_bound_module = spec.requested if spec.asname else expected_bound_name
            bound_record = self.module_by_id.get(bound_module)
            bound_candidates = self.module_names.get(expected_bound_module, ())
            if (spec.bound_name != expected_bound_name or bound_record is None
                    or bound_record.name != expected_bound_module or len(bound_candidates) != 1
                    or bound_candidates[0] != bound_module):
                status = ImportResolutionStatus.BLOCKED
                conditions.append(self._condition(ImportConditionKind.UNSUPPORTED_IMPORT_FORM,
                    ImportConditionStatus.SOURCE_BLOCKER,
                    "The typed root-versus-alias binding disagrees with the import syntax.",
                    operation=operation.operation, source=operation.source))
            elif len(requested_ids) > 1 or len(self.module_names.get(spec.requested, ())) > 1:
                status = ImportResolutionStatus.AMBIGUOUS
                conditions.append(self._condition(ImportConditionKind.SOURCE_FILE_SELECTION,
                    ImportConditionStatus.SOURCE_BLOCKER,
                    "More than one module candidate matches the import edge/name.",
                    operation=operation.operation, source=operation.source))
            elif requested_id is None:
                status = ImportResolutionStatus.EXTERNAL if requested_ids else ImportResolutionStatus.UNRESOLVED
                conditions.append(self._condition(ImportConditionKind.SOURCE_FILE_SELECTION,
                    ImportConditionStatus.SOURCE_BLOCKER if not requested_ids else ImportConditionStatus.UNKNOWN,
                    "No unique indexed local module candidate is linked to this import.",
                    operation=operation.operation, source=operation.source))
            elif requested_id not in self.module_by_id or self.module_by_id[requested_id].path is None:
                status = ImportResolutionStatus.EXTERNAL
                conditions.append(self._condition(ImportConditionKind.SOURCE_FILE_SELECTION,
                    ImportConditionStatus.SOURCE_BLOCKER,
                    "The linked import target is external or lacks a local source file.",
                    operation=operation.operation, module=requested_id, source=operation.source))
            elif bound_module is None or bound_module not in self.module_by_id:
                status = ImportResolutionStatus.UNRESOLVED
                conditions.append(self._condition(ImportConditionKind.UNSUPPORTED_IMPORT_FORM,
                    ImportConditionStatus.SOURCE_BLOCKER,
                    "The module import has no unique typed bound-module identity (root versus alias).",
                    operation=operation.operation, module=requested_id, source=operation.source))
            else:
                status = ImportResolutionStatus.LOCAL_MODULE_CANDIDATE
                conditions.append(self._condition(ImportConditionKind.SUBMODULE_ATTRIBUTE_BINDING,
                    ImportConditionStatus.REQUIRED_CONTRACT,
                    "For a dotted import bound to a package root, prove normal parent-package child-module attribute binding.",
                    operation=operation.operation, module=requested_id, source=operation.source))
        elif spec.form is sm.ImportForm.FROM:
            expected_bound_name = spec.asname or spec.symbol
            if spec.bound_name != expected_bound_name:
                status = ImportResolutionStatus.BLOCKED
                conditions.append(self._condition(ImportConditionKind.UNSUPPORTED_IMPORT_FORM,
                    ImportConditionStatus.SOURCE_BLOCKER,
                    "The typed from-import bound name disagrees with its imported symbol and alias.",
                    operation=operation.operation, source=operation.source))
            elif requested_id is None:
                status = ImportResolutionStatus.UNRESOLVED
                conditions.append(self._condition(ImportConditionKind.SOURCE_FILE_SELECTION,
                    ImportConditionStatus.UNKNOWN,
                    "The from-import source module has no unique typed local import edge.",
                    operation=operation.operation, source=operation.source))
            elif requested_id not in self.module_by_id or self.module_by_id[requested_id].path is None:
                status = ImportResolutionStatus.EXTERNAL
                conditions.append(self._condition(ImportConditionKind.SOURCE_FILE_SELECTION,
                    ImportConditionStatus.SOURCE_BLOCKER,
                    "The from-import source module is external or has no indexed source.",
                    operation=operation.operation, module=requested_id, source=operation.source))
            else:
                export_slots = self._import_export_slots(operation, requested_id, spec.symbol)
                owner_module = self._module_for_operation(operation)
                same_module_init = (owner_module == requested_id
                    and operation.scope == self.module_by_id[requested_id].initializer)
                if len(export_slots) == 1:
                    export_slot = export_slots[0]
                    if same_module_init:
                        main_block = self.module_main_blocks.get(operation.scope)
                        if main_block is None or operation.block != main_block:
                            binding = None
                            status = ImportResolutionStatus.BLOCKED
                            conditions.append(self._condition(ImportConditionKind.CONTROL_BOUNDARY,
                                ImportConditionStatus.SOURCE_BLOCKER,
                                "A self from-import occurs outside the direct module initializer block, so the namespace state at this point is not a single ordered binding.",
                                operation=operation.operation, module=requested_id, source=operation.source))
                        elif (export_slot, operation.scope) in self.cross_block_binding_slots:
                            binding = None
                            status = ImportResolutionStatus.BLOCKED
                            conditions.append(self._condition(ImportConditionKind.CONTROL_BOUNDARY,
                                ImportConditionStatus.SOURCE_BLOCKER,
                                "A self from-import export has candidate writes in another control block.",
                                operation=operation.operation, module=requested_id, source=operation.source))
                        else:
                            binding = self._latest_export_binding(requested_id, export_slot,
                                before_position=operation.position)
                    else:
                        binding = self._latest_export_binding(requested_id, export_slot)
                    export_binding = binding.id if binding else None
                    if binding is not None:
                        status = ImportResolutionStatus.LOCAL_EXPORT_CANDIDATE
                        conditions.append(self._condition(ImportConditionKind.MODULE_EXPORT_NAMESPACE,
                            ImportConditionStatus.SOURCE_SUPPORTED,
                            "The SG links a direct module export slot at the import's point in the initializer.",
                            operation=operation.operation, module=requested_id, source=operation.source))
                        if not same_module_init:
                            conditions.append(self._condition(ImportConditionKind.MODULE_INITIALIZATION_COMPLETE,
                                ImportConditionStatus.REQUIRED_CONTRACT,
                                "Prove the exporting module initializer completed before this from-import reads its final namespace binding.",
                                operation=operation.operation, module=requested_id, source=operation.source))
                    elif status is not ImportResolutionStatus.BLOCKED and same_module_init:
                        # IMPORT_FROM first observes the package's current
                        # namespace, then may fall back to loading a child.
                        child = self._submodule(requested_id, spec.symbol)
                        if child is not None:
                            status = ImportResolutionStatus.LOCAL_SUBMODULE_CANDIDATE
                            conditions.append(self._condition(ImportConditionKind.LAZY_MODULE_ATTRIBUTE,
                                ImportConditionStatus.REQUIRED_CONTRACT,
                                "Prove no module __getattr__ or custom module type supplies the missing from-list attribute first.",
                                operation=operation.operation, module=requested_id, source=operation.source))
                            conditions.append(self._condition(ImportConditionKind.SUBMODULE_ATTRIBUTE_BINDING,
                                ImportConditionStatus.REQUIRED_CONTRACT,
                                "The package has no preceding namespace binding; prove ordinary from-list fallback loads and binds this indexed child module.",
                                operation=operation.operation, module=child, source=operation.source))
                            conditions.append(self._condition(ImportConditionKind.MODULE_INITIALIZATION_COMPLETE,
                                ImportConditionStatus.REQUIRED_CONTRACT,
                                "Prove the indexed child module completed initialization before its from-list binding is consumed.",
                                operation=operation.operation, module=child, source=operation.source))
                        else:
                            status = ImportResolutionStatus.UNRESOLVED
                            conditions.append(self._condition(ImportConditionKind.MODULE_EXPORT_NAMESPACE,
                                ImportConditionStatus.SOURCE_BLOCKER,
                                "No preceding self-module binding or unique child module exists; a later binding cannot satisfy this from-import.",
                                operation=operation.operation, module=requested_id, source=operation.source))
                    elif status is not ImportResolutionStatus.BLOCKED:
                        status = ImportResolutionStatus.UNRESOLVED
                        conditions.append(self._condition(ImportConditionKind.MODULE_EXPORT_NAMESPACE,
                            ImportConditionStatus.SOURCE_BLOCKER,
                            "The export slot has no module-scope static binding.",
                            operation=operation.operation, module=requested_id, source=operation.source))
                elif len(export_slots) > 1:
                    status = ImportResolutionStatus.AMBIGUOUS
                    conditions.append(self._condition(ImportConditionKind.MODULE_EXPORT_NAMESPACE,
                        ImportConditionStatus.SOURCE_BLOCKER,
                        "Multiple module slots match the imported symbol.", operation=operation.operation,
                        module=requested_id, source=operation.source))
                else:
                    child = self._submodule(requested_id, spec.symbol)
                    if child is not None:
                        status = ImportResolutionStatus.LOCAL_SUBMODULE_CANDIDATE
                        conditions.append(self._condition(ImportConditionKind.LAZY_MODULE_ATTRIBUTE,
                            ImportConditionStatus.REQUIRED_CONTRACT,
                            "Prove no module __getattr__ or custom module type supplies the missing from-list attribute first.",
                            operation=operation.operation, module=requested_id, source=operation.source))
                        conditions.append(self._condition(ImportConditionKind.SUBMODULE_ATTRIBUTE_BINDING,
                            ImportConditionStatus.REQUIRED_CONTRACT,
                            "Prove ordinary from-list fallback imports and binds this indexed child module.",
                            operation=operation.operation, module=child, source=operation.source))
                        conditions.append(self._condition(ImportConditionKind.MODULE_INITIALIZATION_COMPLETE,
                            ImportConditionStatus.REQUIRED_CONTRACT,
                            "Prove the indexed child module completed initialization before its from-list binding is consumed.",
                            operation=operation.operation, module=child, source=operation.source))
                    else:
                        status = ImportResolutionStatus.UNRESOLVED
                        conditions.append(self._condition(ImportConditionKind.MODULE_EXPORT_NAMESPACE,
                            ImportConditionStatus.UNKNOWN,
                            "Neither a direct source binding nor a unique local child-module candidate is indexed.",
                            operation=operation.operation, module=requested_id, source=operation.source))
        contract = ImportResolutionContract(operation.operation, operation.result, operation.source,
            spec.form, spec.requested, spec.relative_level, spec.symbol, spec.bound_name,
            spec.asname, requested_id, bound_module, export_slot, export_binding,
            status, _unique_conditions(conditions))
        self.contracts[operation.operation] = contract
        return contract

    def _import_export_slots(self, operation, module_id, symbol):
        slots = []
        for identifier in _ids_of_kind(self.edges_by_source_relation.get(
                (SemanticRelation.READS_SLOT, operation.operation), ()), SemanticNodeKind.VALUE_SLOT):
            slot = self.semantic.slots[identifier]
            module = self.module_by_id[module_id]
            if slot.name == symbol and slot.owner == module.initializer:
                slots.append(identifier)
        if slots:
            return tuple(dict.fromkeys(slots))
        module = self.module_by_id[module_id]
        return self.module_export_slots.get(module_id, {}).get(symbol, ())

    def _export_slots(self, module_id, name):
        module = self.module_by_id.get(module_id)
        if module is None or module.initializer is None:
            return ()
        return self.module_export_slots.get(module_id, {}).get(name, ())

    def _latest_export_binding(self, module_id, slot_id, *, before_position=None):
        module = self.module_by_id.get(module_id)
        if module is None or module.initializer is None:
            return None
        candidates = self.bindings_by_slot_scope.get((slot_id, module.initializer), ())
        if not candidates:
            return None
        main_block = self.module_main_blocks.get(module.initializer)
        if main_block is None:
            return None
        direct = [binding for binding in candidates if binding.block == main_block]
        if not direct:
            return None
        # A branch/alternate block write prevents treating one arbitrary
        # position as the runtime reaching definition.
        if (slot_id, module.initializer) in self.cross_block_binding_slots:
            return None
        if before_position is None:
            return direct[-1]
        for binding in reversed(direct):
            if binding.position < before_position:
                return binding
        return None

    def _submodule(self, package_id, name):
        package = self.module_by_id.get(package_id)
        if package is None:
            return None
        candidates = self.module_names.get(package.name + "." + name, ())
        local = [identifier for identifier in candidates
                 if self.module_by_id[identifier].path is not None and self.module_by_id[identifier].initializer is not None]
        return local[0] if len(local) == 1 else None

    def _boundary_conditions(self, binding, use):
        result = []
        for boundary in self.boundaries_by_scope_block.get((use.scope, use.block), ()):
            if not (binding.position < boundary.position <= use.position):
                continue
            kind_map = {
                sm.BoundaryKind.IMPORT: (ImportConditionKind.IMPORT_BOUNDARY, ImportConditionStatus.REQUIRED_CONTRACT),
                sm.BoundaryKind.ATTRIBUTE: (ImportConditionKind.ATTRIBUTE_BOUNDARY, ImportConditionStatus.REQUIRED_CONTRACT),
                sm.BoundaryKind.INDEX: (ImportConditionKind.INDEX_BOUNDARY, ImportConditionStatus.REQUIRED_CONTRACT),
                sm.BoundaryKind.REBIND: (ImportConditionKind.REBIND_BOUNDARY, ImportConditionStatus.REQUIRED_CONTRACT),
                sm.BoundaryKind.CALL: (ImportConditionKind.CALL_BOUNDARY, ImportConditionStatus.SOURCE_BLOCKER),
                sm.BoundaryKind.CONTROL: (ImportConditionKind.CONTROL_BOUNDARY, ImportConditionStatus.SOURCE_BLOCKER),
                sm.BoundaryKind.OPAQUE: (ImportConditionKind.OPAQUE_BOUNDARY, ImportConditionStatus.SOURCE_BLOCKER),
                sm.BoundaryKind.COMPARISON_DISPATCH: (ImportConditionKind.OPAQUE_BOUNDARY, ImportConditionStatus.SOURCE_BLOCKER),
                sm.BoundaryKind.COMPARISON_SHORT_CIRCUIT: (ImportConditionKind.CONTROL_BOUNDARY, ImportConditionStatus.SOURCE_BLOCKER),
            }
            kind, status = kind_map[boundary.kind]
            result.append(self._condition(kind, status, boundary.reason,
                operation=boundary.operation, source=boundary.source))
        return tuple(result)

    def _module_export_conditions(self, module_id, binding, operation, *, at_position=None):
        module = self.module_by_id[module_id]
        boundaries = [boundary for boundary in self.boundaries_by_scope_block.get(
                      (module.initializer, binding.block), ())
                     if boundary.position > binding.position
                     and not (boundary.kind is sm.BoundaryKind.REBIND
                              and boundary.operation == binding.definition)
                     and (at_position is None or boundary.position <= at_position)]
        # Branch/loop assignments live in sibling blocks whose local positions
        # cannot be compared to this straight-line module export.
        other_block_writes = [candidate for candidate in self.bindings_by_slot_scope.get(
            (binding.slot, module.initializer), ()) if candidate.block != binding.block]
        if other_block_writes:
            conditions = [self._condition(ImportConditionKind.CONTROL_BOUNDARY,
                ImportConditionStatus.SOURCE_BLOCKER,
                "The module export has candidate writes in another control block; block-local positions do not establish one initializer result.",
                operation=operation, module=module_id, source=candidate.source)
                for candidate in other_block_writes]
        else:
            conditions = []
        conditions.insert(0, self._condition(ImportConditionKind.MODULE_EXPORT_NAMESPACE,
            ImportConditionStatus.SOURCE_SUPPORTED,
            "A source binding for this module export is indexed.", operation=operation,
            module=module_id, source=binding.source))
        for boundary in boundaries:
            mapping = {
                sm.BoundaryKind.IMPORT: (ImportConditionKind.IMPORT_BOUNDARY, ImportConditionStatus.REQUIRED_CONTRACT),
                sm.BoundaryKind.ATTRIBUTE: (ImportConditionKind.ATTRIBUTE_BOUNDARY, ImportConditionStatus.REQUIRED_CONTRACT),
                sm.BoundaryKind.INDEX: (ImportConditionKind.INDEX_BOUNDARY, ImportConditionStatus.REQUIRED_CONTRACT),
                sm.BoundaryKind.REBIND: (ImportConditionKind.DYNAMIC_REBINDING, ImportConditionStatus.SOURCE_BLOCKER),
                sm.BoundaryKind.CALL: (ImportConditionKind.CALL_BOUNDARY, ImportConditionStatus.SOURCE_BLOCKER),
                sm.BoundaryKind.CONTROL: (ImportConditionKind.CONTROL_BOUNDARY, ImportConditionStatus.SOURCE_BLOCKER),
                sm.BoundaryKind.OPAQUE: (ImportConditionKind.OPAQUE_BOUNDARY, ImportConditionStatus.SOURCE_BLOCKER),
                sm.BoundaryKind.COMPARISON_DISPATCH: (ImportConditionKind.OPAQUE_BOUNDARY, ImportConditionStatus.SOURCE_BLOCKER),
                sm.BoundaryKind.COMPARISON_SHORT_CIRCUIT: (ImportConditionKind.CONTROL_BOUNDARY, ImportConditionStatus.SOURCE_BLOCKER),
            }
            kind, status = mapping[boundary.kind]
            conditions.append(self._condition(kind, status, boundary.reason,
                operation=boundary.operation, module=module_id, source=boundary.source))
        for boundary in self.boundaries_by_scope_block.get((module.initializer, binding.block), ()):
            if (boundary.kind is sm.BoundaryKind.REBIND
                    and boundary.operation == binding.definition):
                conditions.append(self._condition(ImportConditionKind.DYNAMIC_REBINDING,
                    ImportConditionStatus.REQUIRED_CONTRACT,
                    "The export assignment can replace a prior value and run its finalizer; prove the indexed fresh-namespace and no-external-mutation preconditions cover this binding event.",
                    operation=boundary.operation, module=module_id, source=boundary.source))
        conditions.append(self._condition(ImportConditionKind.MODULE_TYPE_AND_ATTRIBUTE_LOOKUP,
            ImportConditionStatus.REQUIRED_CONTRACT,
            "Prove the runtime object is an ordinary module with standard attribute lookup.",
            operation=operation, module=module_id, source=binding.source))
        return tuple(conditions)

    def resolve(self, value_id, depth=0):
        if value_id in self.memo:
            return self.memo[value_id]
        if value_id in self.active_values:
            value = self.graph.values.get(value_id)
            return _Resolved("blocked", source_value=value_id, gaps=(ImportValueGap(
                ImportGapKind.CYCLE, "Cyclic static value/import provenance.",
                value.producer if value else None, value.source if value else None),), blocker=True)
        if depth >= self.resolve_depth_limit:
            value = self.graph.values.get(value_id)
            return _Resolved("blocked", source_value=value_id, gaps=(ImportValueGap(
                ImportGapKind.BUDGET, "Import provenance depth budget exceeded.",
                value.producer if value else None, value.source if value else None),), blocker=True)
        if not self._spend("nodes", limit="max_nodes"):
            value = self.graph.values.get(value_id)
            return _Resolved("blocked", source_value=value_id, gaps=(ImportValueGap(
                ImportGapKind.BUDGET, "Import provenance node budget exceeded.",
                value.producer if value else None, value.source if value else None),), blocker=True)
        value = self.graph.values.get(value_id)
        if value is None:
            return _Resolved("unresolved", gaps=(ImportValueGap(ImportGapKind.DEPENDENCY,
                "Static value is absent from the source semantics graph."),))
        operation = self.producers.get(value_id)
        if operation is None or value.external:
            return _Resolved("unresolved", source_value=value_id, gaps=(ImportValueGap(
                ImportGapKind.DEPENDENCY, "External static value has no source producer.",
                value.producer, value.source),))
        self.active_values.add(value_id)
        try:
            result = self._resolve_operation(value_id, operation, depth)
            if not self.budget_exhausted:
                self.memo[value_id] = result
            return result
        finally:
            self.active_values.remove(value_id)

    def _resolve_operation(self, value_id, operation, depth):
        if not self._spend("steps", limit="max_steps"):
            return _Resolved("blocked", source_value=value_id, gaps=(ImportValueGap(
                ImportGapKind.BUDGET, "Import provenance step budget exceeded.", operation.operation, operation.source),), blocker=True)
        opcode = operation.opcode
        if opcode is sm.Opcode.LITERAL and operation.literal is not None:
            try:
                size = _literal_size(operation.literal, self.budget)
            except ValueError as error:
                return _Resolved("blocked", source_value=value_id, gaps=(ImportValueGap(
                    ImportGapKind.BUDGET, str(error), operation.operation, operation.source),), blocker=True)
            if not self._spend("work", max(1, size), "max_work") or not self._spend("output_bytes", size, "max_total_output_bytes"):
                return _Resolved("blocked", source_value=value_id, gaps=(ImportValueGap(
                    ImportGapKind.BUDGET, "Import literal output/work budget exceeded.", operation.operation, operation.source),), blocker=True)
            return _Resolved("literal", operation.literal, source_value=value_id,
                steps=self._append_step((), ImportStepKind.LITERAL, value_id, operation=operation.operation))
        if opcode is sm.Opcode.IMPORT:
            return self._resolve_import_value(value_id, operation, depth)
        if opcode is sm.Opcode.READ:
            return self._resolve_read(value_id, operation, depth)
        if opcode in {sm.Opcode.ALIAS, sm.Opcode.RETURN}:
            if len(operation.operands) != 1:
                return self._gap_result(ImportGapKind.BINDING, "Alias/return operation does not have one ordered input.", operation)
            input_value = operation.operands[0].value
            result = self.resolve(input_value, depth + 1)
            return self._with_steps(result, self._append_step((), ImportStepKind.BINDING, value_id,
                operation=operation.operation, detail="alias/return"))
        if opcode is sm.Opcode.ATTRIBUTE:
            return self._resolve_attribute(value_id, operation, depth)
        if opcode is sm.Opcode.INDEX:
            return self._resolve_index(value_id, operation, depth)
        if opcode is sm.Opcode.BUILD_TUPLE:
            return self._resolve_tuple(value_id, operation, depth)
        if opcode in {sm.Opcode.BUILD_LIST, sm.Opcode.BUILD_DICT, sm.Opcode.BUILD_SET}:
            return _Resolved("blocked", source_value=value_id, steps=self._append_step((), ImportStepKind.BUILTIN_VALUE,
                value_id, operation=operation.operation), conditions=(self._condition(
                    ImportConditionKind.MUTABLE_VALUE, ImportConditionStatus.SOURCE_BLOCKER,
                    "Mutable container construction is not an immutable replacement literal.",
                    operation=operation.operation, source=operation.source),),
                gaps=(ImportValueGap(ImportGapKind.MUTABLE,
                    "Mutable list/dict/set construction cannot be shared as an immutable literal.",
                    operation.operation, operation.source),), blocker=True)
        if opcode in {sm.Opcode.CALL, sm.Opcode.OPAQUE} or operation.dispatch is sm.DispatchKind.USER_DEFINED:
            return _Resolved("blocked", source_value=value_id, gaps=(ImportValueGap(
                ImportGapKind.DISPATCH, "User call, opaque operation or user-defined dispatch blocks static import value resolution.",
                operation.operation, operation.source),), conditions=(self._condition(
                    ImportConditionKind.CALL_BOUNDARY if opcode is sm.Opcode.CALL else ImportConditionKind.OPAQUE_BOUNDARY,
                    ImportConditionStatus.SOURCE_BLOCKER,
                    "The value path crosses a call/opaque operation whose value and effects are not modeled.",
                    operation=operation.operation, source=operation.source),), blocker=True)
        # A single bounded base report covers ordinary source constants; its
        # usage is charged to the same resolver budget.
        base = self._ensure_base_report()
        if base is False:
            kind = ImportGapKind.BUDGET if self.budget_exhausted else ImportGapKind.DEPENDENCY
            reason = ("No global budget remains for the bounded base constant pass." if self.budget_exhausted
                      else getattr(self, "base_error", "Value is not among immutable base-evaluation targets."))
            return self._gap_result(kind, reason, operation)
        fact = base.facts.get(value_id)
        if fact is None:
            return self._gap_result(ImportGapKind.DEPENDENCY,
                "Value is not in the bounded base constant target set.", operation)
        if fact.status.name == "CONSTANT" and fact.literal is not None:
            try:
                size = _literal_size(fact.literal, self.budget)
            except ValueError as error:
                return self._gap_result(ImportGapKind.BUDGET, str(error), operation)
            if not self._spend("work", max(1, size), "max_work") or not self._spend("output_bytes", size, "max_total_output_bytes"):
                return self._gap_result(ImportGapKind.BUDGET, "Import literal output/work budget exceeded.", operation)
            proof = base.proofs.get(fact.proof_id)
            if proof is None:
                return self._gap_result(ImportGapKind.DEPENDENCY,
                    "The base constant fact has no typed proof record.", operation)
            runtime = base.runtime
            base_conditions = tuple(self._condition(
                ImportConditionKind.BUILTIN_RUNTIME_MATCH
                    if requirement is ConstantRuntimeRequirement.BUILTIN_RUNTIME_MATCH
                    else ImportConditionKind.FLOATING_ENVIRONMENT_MATCH,
                ImportConditionStatus.REQUIRED_CONTRACT,
                ("Prove the target builtin implementation and Python version match the recorded constant evaluator runtime."
                 if requirement is ConstantRuntimeRequirement.BUILTIN_RUNTIME_MATCH else
                 "Prove the target floating-point environment matches the recorded constant evaluator format and runtime."),
                operation=operation.operation, source=operation.source,
                runtime_requirement=requirement, runtime=runtime)
                for requirement in proof.runtime_requirements)
            return _Resolved("literal", fact.literal, source_value=value_id,
                steps=self._append_step((), ImportStepKind.BUILTIN_VALUE, value_id, operation=operation.operation,
                                        detail=fact.proof_id or ""), conditions=base_conditions)
        return self._gap_result(ImportGapKind.DEPENDENCY,
            "Static value is not an exact immutable builtin constant under the bounded G7.1 evaluator.", operation)

    def _gap_result(self, kind, reason, operation):
        return _Resolved("blocked" if kind in {ImportGapKind.BUDGET, ImportGapKind.MUTABLE,
                ImportGapKind.DISPATCH, ImportGapKind.CYCLE} else "unresolved",
            source_value=operation.result,
            gaps=(ImportValueGap(kind, reason, operation.operation, operation.source),),
            blocker=kind in {ImportGapKind.BUDGET, ImportGapKind.MUTABLE, ImportGapKind.DISPATCH,
                             ImportGapKind.CYCLE})

    def _resolve_read(self, value_id, operation, depth):
        use = self.graph.uses.get(operation.binding_use)
        if use is None:
            return self._gap_result(ImportGapKind.BINDING, "READ operation has no binding-use record.", operation)
        if use.status is sm.BindingStatus.EXACT and len(use.reaching) == 1:
            binding_id = use.reaching[0]
            binding = self.graph.bindings.get(binding_id)
            if binding is None:
                return self._gap_result(ImportGapKind.BINDING, "Exact reaching binding is missing.", operation)
            boundaries = self._boundary_conditions(binding, use)
            if any(item.status is ImportConditionStatus.SOURCE_BLOCKER for item in boundaries):
                return _Resolved("blocked", source_value=value_id, conditions=boundaries,
                    gaps=(ImportValueGap(ImportGapKind.BINDING,
                        "Exact source binding crosses a call/control/opaque boundary.", operation.operation,
                        operation.source),), blocker=True)
            resolved = self.resolve(binding.value, depth + 1)
            return self._with_steps(_combine_with_conditions(resolved, boundaries,
                    conditional=bool(boundaries)), self._append_step((), ImportStepKind.BINDING,
                    value_id, operation=operation.operation, slot=binding.slot, binding=binding_id,
                    detail="EXACT"))
        candidates = use.conditional_reaching
        if not candidates:
            return self._gap_result(ImportGapKind.BINDING,
                "READ has neither an EXACT nor a typed conditional reaching binding.", operation)
        resolved_candidates = []
        candidate_conditions = []
        for binding_id in candidates:
            binding = self.graph.bindings.get(binding_id)
            if binding is None:
                continue
            boundaries = self._boundary_conditions(binding, use)
            candidate_conditions.extend(boundaries)
            if any(item.status is ImportConditionStatus.SOURCE_BLOCKER for item in boundaries):
                return _Resolved("blocked", source_value=value_id,
                    conditions=_unique_conditions(candidate_conditions),
                    gaps=(ImportValueGap(ImportGapKind.BINDING,
                        "Conditional reaching binding crosses call/control/opaque boundary.", operation.operation,
                        operation.source),), blocker=True)
            resolved = self.resolve(binding.value, depth + 1)
            resolved_candidates.append(_combine_with_conditions(resolved, boundaries, conditional=True))
        if not resolved_candidates:
            return self._gap_result(ImportGapKind.BINDING, "Conditional reaching definitions are unavailable.", operation)
        merged = self._merge_resolved(resolved_candidates,
            "Conditional definitions do not establish one immutable value.", operation)
        return self._with_steps(_combine_with_conditions(merged, _unique_conditions(candidate_conditions), conditional=True),
            self._append_step((), ImportStepKind.BINDING, value_id, operation=operation.operation,
                slot=use.slot, binding=candidates[-1], detail="CONDITIONAL"))

    def _resolve_import_value(self, value_id, operation, depth):
        if operation.operation in self.active_imports:
            return _Resolved("blocked", source_value=value_id,
                conditions=(self._condition(ImportConditionKind.IMPORT_CYCLE,
                    ImportConditionStatus.SOURCE_BLOCKER, "Re-export traversal revisited an import operation.",
                    operation=operation.operation, source=operation.source),),
                gaps=(ImportValueGap(ImportGapKind.CYCLE, "Cyclic re-export/import value path.",
                    operation.operation, operation.source),), blocker=True)
        self.active_imports.add(operation.operation)
        try:
            contract = self._import_contract(operation)
            if contract.status in {ImportResolutionStatus.EXTERNAL, ImportResolutionStatus.UNRESOLVED,
                                   ImportResolutionStatus.AMBIGUOUS, ImportResolutionStatus.BLOCKED}:
                kind = ImportGapKind.IMPORT
                reason = "Import target is external, unresolved or ambiguous under the typed source graph."
                if contract.status is ImportResolutionStatus.EXTERNAL:
                    reason = "External dependencies are never loaded or guessed by this resolver."
                return _Resolved("blocked" if contract.status in {ImportResolutionStatus.AMBIGUOUS,
                                                                  ImportResolutionStatus.BLOCKED} else "unresolved",
                    source_value=value_id, conditions=contract.conditions,
                    gaps=(ImportValueGap(kind, reason, operation.operation, operation.source),),
                    blocker=contract.status in {ImportResolutionStatus.AMBIGUOUS,
                                                ImportResolutionStatus.BLOCKED})
            conditions = list(contract.conditions)
            if contract.requested_module is not None and self._module_cycle(contract.requested_module):
                return _Resolved("blocked", source_value=value_id, conditions=tuple(conditions),
                    gaps=(ImportValueGap(ImportGapKind.CYCLE,
                        "Import module participates in an initialization cycle; partial exports are not resolved.",
                        operation.operation, operation.source),), blocker=True)
            if contract.form is sm.ImportForm.MODULE:
                if contract.bound_module is None:
                    return _Resolved("unresolved", source_value=value_id, conditions=contract.conditions,
                        gaps=(ImportValueGap(ImportGapKind.IMPORT,
                            "Module import lacks a typed bound-module identity.", operation.operation,
                            operation.source),))
                target = self.module_by_id.get(contract.requested_module)
                # Ordinary dotted import initializes its requested module and
                # all parent package modules. The source graph supplies which
                # module object is actually bound (root or as-name target).
                loaded = self._module_prefixes(contract.requested_module)
                step = self._append_step((), ImportStepKind.IMPORT_MODULE, value_id,
                    operation=operation.operation, module=contract.bound_module,
                    detail="requested=" + (target.name if target else contract.requested))
                return _Resolved("module", module=contract.bound_module, loaded_modules=loaded,
                    source_value=value_id, steps=step, conditions=contract.conditions, conditional=True)
            if contract.status is ImportResolutionStatus.LOCAL_EXPORT_CANDIDATE:
                binding = self.graph.bindings.get(contract.export_binding)
                if binding is None or contract.export_slot is None or contract.requested_module is None:
                    return _Resolved("unresolved", source_value=value_id, conditions=contract.conditions,
                        gaps=(ImportValueGap(ImportGapKind.EXPORT,
                            "Typed import contract lost its direct export binding.", operation.operation,
                            operation.source),))
                owner_module = self._module_for_operation(operation)
                point_in_module = (operation.position if owner_module == contract.requested_module
                    and operation.scope == self.module_by_id[contract.requested_module].initializer
                    else None)
                export_conditions = self._module_export_conditions(contract.requested_module,
                    binding, operation.operation, at_position=point_in_module)
                resolved = self.resolve(binding.value, depth + 1)
                is_reexport = bool(owner_module is not None and contract.bound_name
                    and self._export_slots(owner_module, contract.bound_name))
                step = self._append_step((), ImportStepKind.IMPORT_EXPORT, value_id, operation=operation.operation,
                    module=contract.requested_module, slot=contract.export_slot,
                    binding=binding.id, detail=contract.symbol or "")
                reexport_step = (self._append_step((), ImportStepKind.REEXPORT, value_id,
                    operation=operation.operation, module=owner_module,
                    slot=contract.export_slot, binding=binding.id,
                    detail=contract.bound_name or "") if is_reexport else ())
                conditions.extend(export_conditions)
                conditions.extend(resolved.conditions)
                combined = _combine_with_conditions(resolved,
                    _unique_conditions(conditions), conditional=True)
                return replace(combined, steps=self._record_steps(step, reexport_step, resolved.steps))
            if contract.status is ImportResolutionStatus.LOCAL_SUBMODULE_CANDIDATE:
                child = self._submodule(contract.requested_module, contract.symbol)
                if child is None:
                    return _Resolved("unresolved", source_value=value_id, conditions=contract.conditions,
                        gaps=(ImportValueGap(ImportGapKind.IMPORT,
                            "No unique local submodule candidate remains after contract construction.",
                            operation.operation, operation.source),))
                return _Resolved("module", module=child, loaded_modules=self._module_prefixes(child) + (child,),
                    source_value=value_id,
                    steps=self._append_step((), ImportStepKind.SUBMODULE, value_id,
                        operation=operation.operation, module=child, detail=contract.symbol or ""),
                    conditions=contract.conditions, conditional=True)
            return _Resolved("unresolved", source_value=value_id, conditions=contract.conditions,
                gaps=(ImportValueGap(ImportGapKind.IMPORT, "Unsupported import resolution status.",
                    operation.operation, operation.source),))
        finally:
            self.active_imports.remove(operation.operation)

    def _module_prefixes(self, module_id):
        module = self.module_by_id.get(module_id)
        if module is None:
            return ()
        parts = module.name.split(".")
        result = []
        for size in range(1, len(parts) + 1):
            candidates = self.module_names.get(".".join(parts[:size]), ())
            if len(candidates) == 1 and self.module_by_id[candidates[0]].path is not None:
                result.append(candidates[0])
        return tuple(result)

    def _resolve_attribute(self, value_id, operation, depth):
        if len(operation.operands) != 1:
            return self._gap_result(ImportGapKind.ATTRIBUTE, "ATTRIBUTE must have one ordered receiver.", operation)
        receiver = self.resolve(operation.operands[0].value, depth + 1)
        step = self._append_step((), ImportStepKind.ATTRIBUTE, value_id,
            operation=operation.operation, detail=operation.attribute or "")
        if receiver.kind != "module" or receiver.module is None:
            return _Resolved("blocked" if receiver.blocker else "unresolved", source_value=value_id,
                steps=self._record_steps(receiver.steps, step), conditions=receiver.conditions,
                gaps=receiver.gaps + (ImportValueGap(ImportGapKind.ATTRIBUTE,
                    "Attribute receiver is not a source-resolved local module object.",
                    operation.operation, operation.source),), blocker=receiver.blocker)
        module_id, name = receiver.module, operation.attribute
        slots = self._export_slots(module_id, name)
        if len(slots) == 1:
            owner_module = self._module_for_operation(operation)
            same_module_init = (owner_module == module_id
                and operation.scope == self.module_by_id[module_id].initializer)
            if same_module_init and (operation.block != self.module_main_blocks.get(operation.scope)
                    or (slots[0], operation.scope) in self.cross_block_binding_slots):
                binding = None
            else:
                binding = self._latest_export_binding(module_id, slots[0],
                    before_position=operation.position if same_module_init else None)
            if binding is None:
                conditions = receiver.conditions
                if same_module_init:
                    child = self._submodule(module_id, name)
                    if child is not None and child in receiver.loaded_modules:
                        return _Resolved("module", module=child,
                            loaded_modules=receiver.loaded_modules, source_value=value_id,
                            steps=self._record_steps(receiver.steps, self._append_step((),
                                ImportStepKind.SUBMODULE, value_id,
                                operation=operation.operation, module=child, detail=name or "")),
                            conditions=receiver.conditions + (self._condition(
                                ImportConditionKind.SUBMODULE_ATTRIBUTE_BINDING,
                                ImportConditionStatus.REQUIRED_CONTRACT,
                                "Prove the prior dotted import attached this indexed child to the current package.",
                                operation=operation.operation, module=child, source=operation.source),),
                            conditional=True)
                    conditions += (self._condition(ImportConditionKind.MODULE_EXPORT_NAMESPACE,
                        ImportConditionStatus.SOURCE_BLOCKER,
                        "No unique preceding namespace binding exists at this same-module attribute access.",
                        operation=operation.operation, module=module_id, source=operation.source),)
                return _Resolved("blocked" if same_module_init else "unresolved", source_value=value_id,
                    steps=self._record_steps(receiver.steps, step), conditions=conditions,
                    gaps=(ImportValueGap(ImportGapKind.EXPORT,
                        "Module attribute has no unique static reaching binding at this execution point.",
                        operation.operation, operation.source),), blocker=same_module_init)
            point_in_module = (operation.position if owner_module == module_id
                and operation.scope == self.module_by_id[module_id].initializer else None)
            module_conditions = self._module_export_conditions(module_id, binding,
                operation.operation, at_position=point_in_module)
            resolved = self.resolve(binding.value, depth + 1)
            conditions = _unique_conditions(receiver.conditions + module_conditions + resolved.conditions + (
                self._condition(ImportConditionKind.LAZY_MODULE_ATTRIBUTE,
                    ImportConditionStatus.SOURCE_SUPPORTED,
                    "A direct source namespace binding exists; module __getattr__ is only a missing-attribute fallback under ordinary module lookup.",
                    operation=operation.operation, module=module_id, source=operation.source),))
            resolved = _combine_with_conditions(resolved, conditions, conditional=True)
            attribute_step = self._append_step((), ImportStepKind.ATTRIBUTE,
                value_id, operation=operation.operation, module=module_id,
                slot=slots[0], binding=binding.id, detail=name or "")
            resolved = replace(resolved, steps=self._record_steps(receiver.steps,
                attribute_step, resolved.steps))
            boundary = self._operation_boundary(operation, sm.BoundaryKind.ATTRIBUTE)
            if boundary is not None:
                resolved = _combine_with_conditions(resolved, (self._condition(
                    ImportConditionKind.ATTRIBUTE_BOUNDARY, ImportConditionStatus.REQUIRED_CONTRACT,
                    boundary.reason, operation=boundary.operation, module=module_id,
                    source=boundary.source),), conditional=True)
            return resolved
        if len(slots) > 1:
            return _Resolved("blocked", source_value=value_id, steps=self._record_steps(receiver.steps, step),
                conditions=receiver.conditions + (self._condition(ImportConditionKind.MODULE_EXPORT_NAMESPACE,
                    ImportConditionStatus.SOURCE_BLOCKER, "Multiple source slots match the module attribute.",
                    operation=operation.operation, module=module_id, source=operation.source),),
                gaps=(ImportValueGap(ImportGapKind.EXPORT, "Module attribute source slot is ambiguous.",
                    operation.operation, operation.source),), blocker=True)
        child = self._submodule(module_id, name)
        if child is not None and child in receiver.loaded_modules:
            conditions = receiver.conditions + (
                self._condition(ImportConditionKind.SUBMODULE_ATTRIBUTE_BINDING,
                    ImportConditionStatus.REQUIRED_CONTRACT,
                    "Prove the prior dotted import loaded and attached this child module to its parent package.",
                    operation=operation.operation, module=child, source=operation.source),
                self._condition(ImportConditionKind.LAZY_MODULE_ATTRIBUTE,
                    ImportConditionStatus.REQUIRED_CONTRACT,
                    "Prove no missing-attribute hook supplies a different value before child-module access.",
                    operation=operation.operation, module=module_id, source=operation.source))
            return _Resolved("module", module=child,
                loaded_modules=receiver.loaded_modules + (child,), source_value=value_id,
                steps=self._record_steps(receiver.steps, self._append_step((), ImportStepKind.SUBMODULE,
                    value_id, operation=operation.operation, module=child, detail=name or "")),
                conditions=_unique_conditions(conditions), conditional=True)
        return _Resolved("blocked", source_value=value_id, steps=self._record_steps(receiver.steps, step),
            conditions=receiver.conditions + (self._condition(ImportConditionKind.LAZY_MODULE_ATTRIBUTE,
                ImportConditionStatus.REQUIRED_CONTRACT,
                "No direct source binding exists; runtime module __getattr__, custom module type, or package child loading may determine this attribute.",
                operation=operation.operation, module=module_id, source=operation.source),),
            gaps=(ImportValueGap(ImportGapKind.ATTRIBUTE,
                "Attribute is missing from the direct module namespace and is not a previously loaded local child.",
                operation.operation, operation.source),), blocker=True)

    def _resolve_index(self, value_id, operation, depth):
        operands = {item.role: item.value for item in operation.operands}
        receiver_id = operands.get("receiver")
        index_id = operands.get("index")
        if receiver_id is None or index_id is None:
            ordered = tuple(item.value for item in operation.operands)
            if len(ordered) != 2:
                return self._gap_result(ImportGapKind.INDEX, "INDEX requires receiver and index operands.", operation)
            receiver_id, index_id = ordered
        receiver, index = self.resolve(receiver_id, depth + 1), self.resolve(index_id, depth + 1)
        conditions = _unique_conditions(receiver.conditions + index.conditions)
        steps = self._record_steps(receiver.steps, index.steps, self._append_step(
            (), ImportStepKind.INDEX, value_id, operation=operation.operation))
        boundary = self._operation_boundary(operation, sm.BoundaryKind.INDEX)
        if boundary is not None and receiver.kind == "literal" and index.kind == "literal":
            conditions = _unique_conditions(conditions + (self._condition(
                ImportConditionKind.INDEX_BOUNDARY, ImportConditionStatus.SOURCE_SUPPORTED,
                "The index boundary is discharged for these exact immutable builtin operands by the fixed index rule.",
                operation=boundary.operation, source=boundary.source),))
        if receiver.kind != "literal" or index.kind != "literal":
            blocker = receiver.blocker or index.blocker
            return _Resolved("blocked" if blocker else "unresolved", source_value=value_id,
                steps=steps, conditions=conditions,
                gaps=receiver.gaps + index.gaps + (ImportValueGap(ImportGapKind.INDEX,
                    "Immutable literal receiver and exact integer index are required.",
                    operation.operation, operation.source),), blocker=blocker)
        try:
            sequence = receiver.literal.to_python()
            subscript = index.literal.to_python()
            if type(sequence) not in (tuple, str, bytes) or type(subscript) is not int:
                return _Resolved("blocked", source_value=value_id, steps=steps,
                    conditions=conditions + (self._condition(ImportConditionKind.BUILTIN_INDEX,
                        ImportConditionStatus.SOURCE_BLOCKER,
                        "Index dispatch is not exact tuple/string/bytes with exact int.",
                        operation=operation.operation, source=operation.source),),
                    gaps=(ImportValueGap(ImportGapKind.INDEX,
                        "Only immutable tuple/string/bytes with exact int indexing is allowed.",
                        operation.operation, operation.source),), blocker=True)
            if not self._spend("work", 1, "max_work"):
                raise ValueError("import index work budget exceeded")
            if subscript < -len(sequence) or subscript >= len(sequence):
                return _Resolved("blocked", source_value=value_id, steps=steps,
                    conditions=conditions + (self._condition(ImportConditionKind.BUILTIN_INDEX,
                        ImportConditionStatus.SOURCE_SUPPORTED,
                        "Exact builtin indexing is out of bounds and would raise IndexError.",
                        operation=operation.operation, source=operation.source),),
                    gaps=(ImportValueGap(ImportGapKind.INDEX,
                        "Exact builtin indexing raises IndexError; replacement is not emitted.",
                        operation.operation, operation.source),), blocker=True)
            if type(sequence) is tuple:
                result_literal = receiver.literal.items[subscript]
            elif type(sequence) is str:
                result_literal = sm.PythonLiteral.from_python(sequence[subscript])
            else:
                result_literal = sm.PythonLiteral.from_python(sequence[subscript])
            size = _literal_size(result_literal, self.budget)
            if not self._spend("output_bytes", size, "max_total_output_bytes"):
                raise ValueError("import index output byte budget exceeded")
        except (ValueError, IndexError, TypeError) as error:
            return _Resolved("blocked", source_value=value_id, steps=steps,
                conditions=conditions, gaps=(ImportValueGap(ImportGapKind.INDEX,
                    str(error), operation.operation, operation.source),), blocker=True)
        index_condition = self._condition(ImportConditionKind.BUILTIN_INDEX,
            ImportConditionStatus.SOURCE_SUPPORTED,
            "The traced inputs are exact immutable builtin values; this fixed index rule performs no user dispatch.",
            operation=operation.operation, source=operation.source)
        return _Resolved("literal", result_literal, source_value=value_id,
            steps=steps, conditions=_unique_conditions(conditions + (index_condition,)),
            conditional=receiver.conditional or index.conditional)

    def _resolve_tuple(self, value_id, operation, depth):
        items = sorted(operation.operands, key=lambda item: (item.index, item.role))
        resolved = [self.resolve(item.value, depth + 1) for item in items]
        if any(item.kind != "literal" for item in resolved):
            merged = self._merge_resolved(resolved,
                "Tuple elements do not all resolve to immutable literals.", operation)
            return self._with_steps(merged, self._append_step((), ImportStepKind.TUPLE_BUILD,
                value_id, operation=operation.operation))
        literals = tuple(item.literal for item in resolved)
        result = sm.PythonLiteral(sm.LiteralKind.TUPLE, items=literals)
        try:
            size = _literal_size(result, self.budget)
        except ValueError as error:
            return self._gap_result(ImportGapKind.BUDGET, str(error), operation)
        if not self._spend("output_bytes", size, "max_total_output_bytes") or not self._spend("work", max(1, len(literals)), "max_work"):
            return self._gap_result(ImportGapKind.BUDGET, "Tuple import value budget exceeded.", operation)
        conditions = _unique_conditions(tuple(condition for item in resolved for condition in item.conditions))
        return _Resolved("literal", result, source_value=value_id,
            steps=self._record_steps(*(item.steps for item in resolved), self._append_step(
                (), ImportStepKind.TUPLE_BUILD, value_id, operation=operation.operation)),
            conditions=conditions, conditional=any(item.conditional for item in resolved))

    def run(self, targets=None):
        selected = tuple(self.graph.values) if targets is None else tuple(targets)
        if any(type(item) is not sm.StaticValueID or item not in self.graph.values for item in selected):
            raise ValueError("targets must reference source semantics values")
        selected = tuple(sorted(set(selected), key=lambda item: item.wire))
        if len(selected) > self.budget.max_nodes:
            raise ValueError("target count exceeds import-value max_nodes budget")
        self._requested_targets = selected
        self.base_target_values = self._collect_base_targets()
        for target in selected:
            if self.budget_exhausted:
                self._budget_fact(target,
                    "Global import provenance budget was exhausted before this target.")
                continue
            resolved = self.resolve(target)
            if self.budget_exhausted:
                self._budget_fact(target,
                    "Global import provenance budget was exhausted while deriving this target.", resolved)
                continue
            if resolved.kind == "literal" and resolved.literal is not None:
                if resolved.blocker or any(condition.status is ImportConditionStatus.SOURCE_BLOCKER
                                            for condition in resolved.conditions):
                    status = ImportValueStatus.BLOCKED
                    gaps = resolved.gaps or (ImportValueGap(ImportGapKind.DEPENDENCY,
                        "A typed source blocker prevents a replacement value proof."),)
                    self.facts[target] = ImportValueFact(target, status,
                        conditions=_unique_conditions(resolved.conditions), gaps=gaps)
                    continue
                elif resolved.conditional or resolved.conditions:
                    status = ImportValueStatus.CONDITIONAL
                else:
                    status = ImportValueStatus.EXACT_BUILTIN_LITERAL
                provenance_id = "import-value-proof:" + _digest((
                    self.semantic_digest_value, self.source_semantics_digest_value, RULE_VERSION,
                    target.wire, resolved.source_value.wire if resolved.source_value else None,
                    encode(resolved.literal), [encode(item) for item in resolved.steps],
                    [encode(item) for item in resolved.conditions]))
                provenance = ImportValueProvenance(provenance_id, target,
                    resolved.source_value or target, resolved.literal,
                    resolved.steps, _unique_conditions(resolved.conditions))
                self.provenances[provenance_id] = provenance
                fact = ImportValueFact(target, status, resolved.literal,
                    resolved.source_value, provenance_id,
                    _unique_conditions(resolved.conditions), resolved.gaps)
                self.facts[target] = fact
                path_kinds = {step.kind for step in resolved.steps}
                import_backed = bool(path_kinds & {ImportStepKind.IMPORT_MODULE,
                    ImportStepKind.IMPORT_EXPORT, ImportStepKind.REEXPORT,
                    ImportStepKind.ATTRIBUTE, ImportStepKind.SUBMODULE})
                producer = self.producers.get(target)
                if (import_backed and producer is not None and producer.opcode is not sm.Opcode.LITERAL
                        and status in {ImportValueStatus.EXACT_BUILTIN_LITERAL, ImportValueStatus.CONDITIONAL}):
                    self._build_guidance(fact, provenance)
                    if self.budget_exhausted:
                        self.guidance.pop(target, None)
                        self.provenances.pop(provenance_id, None)
                        self._budget_fact(target,
                            "Global condition/output budget was exhausted while deriving replacement guards.")
            elif resolved.kind == "blocked" or resolved.blocker:
                self.facts[target] = ImportValueFact(target, ImportValueStatus.BLOCKED,
                    conditions=_unique_conditions(resolved.conditions), gaps=resolved.gaps)
            else:
                self.facts[target] = ImportValueFact(target, ImportValueStatus.UNRESOLVED,
                    conditions=_unique_conditions(resolved.conditions), gaps=resolved.gaps)
        report = ImportValueReport(self.semantic, self.graph, budget=self.budget,
            targets=selected, contracts=self.contracts, facts=self.facts,
            provenances=self.provenances, guidance=self.guidance,
            usage=ImportEvaluationUsage(**self.usage), source_replay=self.source_replay)
        return self._charge_serialized_report(report)

    def _budget_fact(self, target, reason, resolved=None):
        gap = ImportValueGap(ImportGapKind.BUDGET, reason,
            resolved.gaps[0].operation if resolved and resolved.gaps else None,
            resolved.gaps[0].source if resolved and resolved.gaps else None)
        conditions = _unique_conditions(resolved.conditions) if resolved is not None else ()
        self.facts[target] = ImportValueFact(target, ImportValueStatus.BLOCKED,
            conditions=conditions, gaps=(gap,))
        for provenance_id, provenance in tuple(self.provenances.items()):
            if provenance.target == target:
                del self.provenances[provenance_id]
        self.guidance.pop(target, None)
        self._spend("output_bytes", len(target.wire.encode("utf-8")) + len(reason.encode("utf-8")) + 64,
                    "max_total_output_bytes")
        if self.usage["output_bytes"] > self.budget.max_total_output_bytes:
            raise ValueError("import-value blocked-target output exceeds max_total_output_bytes")

    def _charge_serialized_report(self, report):
        """Charge full final report bytes; never return a truncated proof."""
        base_output = self.usage["output_bytes"]
        candidate_total = base_output
        for _ in range(4):
            report = ImportValueReport(self.semantic, self.graph, budget=self.budget,
                targets=report.targets, contracts=report.contracts, facts=report.facts,
                provenances=report.provenances, guidance=report.guidance,
                usage=replace(report.usage, output_bytes=candidate_total), source_replay=self.source_replay)
            encoded_size = len(json.dumps(encode(report._record()), sort_keys=True,
                separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8"))
            total = base_output + encoded_size
            if total > self.budget.max_total_output_bytes:
                raise ValueError("serialized import-value report exceeds max_total_output_bytes")
            if total == candidate_total:
                self.usage["output_bytes"] = total
                return report
            candidate_total = total
        raise ValueError("import-value report size did not stabilize within the output budget")

    def _build_guidance(self, fact, provenance):
        operation = self.producers.get(fact.value)
        source = operation.source if operation is not None else self.graph.values[fact.value].source
        guards = list(fact.conditions)
        guards.append(self._condition(ImportConditionKind.VALUE_IDENTITY_AND_ALIAS,
            ImportConditionStatus.REQUIRED_CONTRACT,
            "Prove the replacement preserves observable identity, aliasing and allocation behavior under Q.",
            operation=operation.operation if operation else None, source=source))
        guards.append(self._condition(ImportConditionKind.CONSUMER_CLOSURE,
            ImportConditionStatus.REQUIRED_CONTRACT,
            "Check the replacement region's consumers and exception timing under Q.",
            operation=operation.operation if operation else None, source=source))
        self.guidance[fact.value] = ImportValueGuidance(fact.value, source, fact.status,
            fact.literal, provenance.id, _unique_conditions(guards))


def _literal_size(literal, budget):
    """Bound recursive literal cost before converting or indexing Python values."""
    pending = [(literal, 1)]
    count = 0
    size = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > budget.max_sequence_items * 4:
            raise ValueError("literal node count exceeds import-value budget")
        if depth > budget.max_literal_depth:
            raise ValueError("literal nesting depth exceeds import-value budget")
        if item.kind is sm.LiteralKind.INT:
            bits = abs(int(item.payload)).bit_length()
            if bits > budget.max_int_bits:
                raise ValueError("integer literal exceeds import-value bit budget")
            size += max(1, (bits + 7) // 8)
        elif item.kind in (sm.LiteralKind.STR, sm.LiteralKind.BYTES):
            raw = item.payload.encode("utf-8", "surrogatepass") if item.kind is sm.LiteralKind.STR else bytes.fromhex(item.payload)
            if len(raw) > budget.max_bytes:
                raise ValueError("string/bytes literal exceeds import-value byte budget")
            size += len(raw)
        elif item.kind is sm.LiteralKind.FLOAT64:
            size += 8
        elif item.kind in (sm.LiteralKind.TUPLE,):
            if len(item.items) > budget.max_sequence_items:
                raise ValueError("tuple exceeds import-value item budget")
            size += 8 * len(item.items)
            pending.extend((child, depth + 1) for child in item.items)
        else:
            size += 1
        if size > budget.max_total_output_bytes:
            raise ValueError("literal exceeds import-value output budget")
    return size


def _unique_conditions(items):
    result = []
    seen = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return tuple(result)


def _combine_with_conditions(resolved, conditions, *, conditional=False):
    conditions = _unique_conditions(resolved.conditions + tuple(conditions))
    return replace(resolved, conditions=conditions,
        conditional=resolved.conditional or conditional or bool(conditions))


def _evaluate_import_values(semantic, source_semantics, *, targets=None, budget=EvaluationBudget(),
                            source_replay=SourceReplayStatus.NOT_CHECKED):
    if type(semantic) is not SemanticGraph or type(source_semantics) is not sm.SourceSemanticsGraph:
        raise TypeError("semantic and source semantics must be typed SCAR graphs")
    if type(budget) is not EvaluationBudget:
        raise TypeError("budget must be EvaluationBudget")
    budget.__post_init__()
    semantic.assert_valid()
    source_semantics.assert_valid(semantic)
    resolver = _Resolver(semantic, source_semantics, budget, source_replay)
    return resolver.run(targets)


def resolve_import_values(semantic, source_semantics, *, targets=None,
                          budget=EvaluationBudget()):
    """Resolve local import/re-export/attribute/index paths without execution.

    `EXACT_BUILTIN_LITERAL` and `CONDITIONAL` facts concern value content only.
    The report always carries separate unresolved loader/cache/initialization and
    source-replay conditions; it never certifies import deletion.
    """
    return _evaluate_import_values(semantic, source_semantics, targets=targets,
                                   budget=budget, source_replay=SourceReplayStatus.NOT_CHECKED)


__all__ = [
    "ImportCondition", "ImportConditionKind", "ImportConditionStatus",
    "ImportDeletionStatus", "ImportEvaluationUsage", "ImportGapKind",
    "ImportResolutionContract", "ImportResolutionStatus", "ImportStepKind",
    "ImportValueFact", "ImportValueGap", "ImportValueGuidance",
    "ImportValueProvenance", "ImportValueReport", "ImportValueStatus",
    "SourceReplayStatus", "resolve_import_values",
]
