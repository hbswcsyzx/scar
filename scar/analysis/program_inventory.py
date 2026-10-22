"""Automatic source scope -> interfaces/coverage -> bounded core body graphs.

The inventory describes source candidates. It never executes the target, proves
an import result or accepts an optimization. Old source layers are prepared once
per file; their digests bind the compact report without repeating those layers
for every body.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from scar.analysis.program_lowering import prepare_source
from scar.analysis.source_discovery import discover_sources, _discover_sources_from_entries
from scar.analysis.runtime_inventory import (
    RuntimeScope, RuntimeScopeBuilder, available_paths, check_compile_limit, check_runtime_ceiling,
)
from scar.analysis.runtime_sources import read_runtime_trace, resolve_runtime_seeds
from scar.ir.program.runtime_sources import RuntimeTraceBudget
from scar.ir.program.expansion import ContextStoreBudget, ExpansionMeasurements, ExpansionSchedule
from scar.ir.program.call_demand import ExpansionScheduleV6, CallSourceScope
from scar.ir.program.call_edges import CallEdgeBudget
from scar.ir.program.functions import BodyLoweringProfile, FunctionInterfaces
from scar.ir.program.frames import FrameModel
from scar.ir.program.ids import RegionID
from scar.ir.program.structured import StructuredBodyModel
from scar.ir.program.codec import dumps as dump_graph
from scar.ir.program.model import LiteralOrigin
from scar.ir.program.discovery import DiscoveryRootMode, SourceDiscovery
from scar.ir.program.inventory import (
    BodyInventory, BodyStatus, CallCandidateWitness, CallInventory, CandidateCondition,
    CoverageEntry, CoverageStatus,
    DefinitionInput, DefinitionInputRole, DefinitionInventory, DefinitionKind,
    ExecutionPhase, FileInventory, ImplicitInvocation, InventoryBudget,
    ImportBindingWitness, InventoryIssue, ParameterInventory, ParameterKind, SourceContextDigest,
)
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.ids import OperationDefinitionID

if TYPE_CHECKING:
    from scar.analysis.call_seeds import CallSourceSeedReport


def _canonical(document):
    return json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _digest(document):
    digest = hashlib.sha256()
    for chunk in json.JSONEncoder(sort_keys=True, ensure_ascii=False, allow_nan=False,
                                  separators=(",", ":")).iterencode(document):
        digest.update(chunk.encode())
    return digest.hexdigest()


def _file_document(file):
    return {
        "snapshot": encode(file.snapshot), "definitions": encode(file.definitions),
        "calls": encode(file.calls), "coverage": encode(file.coverage), "gaps": encode(file.gaps),
        "context": encode(file.context), "implicit_invocations": encode(file.implicit_invocations),
        "bodies": [{"definition": encode(body.definition), "status": body.status.value,
                    "graph": json.loads(dump_graph(body.graph)) if body.graph else None,
                    "metadata": encode(body.metadata), "reason": body.reason,
                    "construction_operations": body.construction_operations} for body in file.bodies],
    }


@dataclass(frozen=True)
class ProgramInventory:
    discovery: SourceDiscovery
    files: tuple[FileInventory, ...]
    budget: InventoryBudget
    runtime_scope: RuntimeScope | None = None
    expansion: ExpansionSchedule | ExpansionScheduleV6 | None = None
    analysis_measurements: ExpansionMeasurements | None = field(default=None, compare=False)
    interfaces: FunctionInterfaces | None = None
    profile: BodyLoweringProfile | None = None
    frames: tuple[FrameModel, ...] = ()
    call_sources: CallSourceSeedReport | None = None
    call_source_scope: CallSourceScope | None = None
    source_analysis_measurements: dict | None = field(default=None, compare=False)
    structured: tuple[StructuredBodyModel, ...] = ()

    def _check_profile(self):
        if self.call_sources is not None:
            from scar.analysis.call_seeds import CallSourceSeedReport
            from scar.analysis.call_demand import _call_source_scope
            if (type(self.call_sources) is not CallSourceSeedReport
                    or type(self.expansion) is not ExpansionScheduleV6
                    or type(self.call_source_scope) is not CallSourceScope
                    or self.profile not in (BodyLoweringProfile.BOUND_FRAME, BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV)
                    or self.runtime_scope is not None):
                raise ValueError("inventory v6 requires calls, typed scope, v6 expansion and frame profile")
            self.call_sources.model.__post_init__()
            self.expansion.__post_init__()
            if self.call_source_scope != _call_source_scope(self.call_sources, self.files):
                raise ValueError("call source admissions differ from the final indexed bodies")
        elif self.call_source_scope is not None or type(self.expansion) is ExpansionScheduleV6:
            raise ValueError("v6 call records require their bound raw/source report")
        if type(self.frames) is not tuple or any(type(model) is not FrameModel for model in self.frames):
            raise ValueError("inventory frames must be typed frame records")
        if type(self.structured) is not tuple or any(type(model) is not StructuredBodyModel for model in self.structured):
            raise ValueError("inventory structured bodies must be typed records")
        if self.profile in (BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV):
            if self.frames or self.interfaces is None or self.interfaces.profile is not self.profile or self.expansion is None:
                raise ValueError("structured inventories need matching interfaces, expansion and no legacy frames")
            if self.call_sources is None and type(self.expansion) is not ExpansionSchedule:
                raise ValueError("static/runtime structured inventories need a source expansion schedule")
            bodies = {body.definition: body for file in self.files for body in file.bodies if body.graph is not None}
            ports = {interface.definition: interface for interface in self.interfaces.bodies}
            definitions = {definition.id: definition for file in self.files for definition in file.definitions}
            models = {model.definition: model for model in self.structured}
            if len(models) != len(self.structured) or set(models) != set(bodies) or set(ports) != set(bodies):
                raise ValueError("structured inventories require one model and interface per emitted body")
            for definition, model in models.items():
                model.__post_init__()
                if (model.region != bodies[definition].graph.root or model.region != ports[definition].region
                        or model.source != definitions[definition].source):
                    raise ValueError("structured inventory model differs from its body/interface/source")
            return
        if self.structured:
            raise ValueError("historical inventories cannot contain structured models")
        if self.profile is None:
            if self.frames or (self.interfaces is not None and self.interfaces.profile is not BodyLoweringProfile.BOUND_FORMALS):
                raise ValueError("historical inventories cannot contain frame-profile records")
            return
        if self.profile is not BodyLoweringProfile.BOUND_FRAME:
            raise ValueError("inventory v5 requires BOUND_FRAME_V1 profile")
        if self.interfaces is None or self.interfaces.profile is not self.profile or self.expansion is None:
            raise ValueError("frame inventories need matching interfaces and global root-only expansion")
        bodies = {body.definition: body for file in self.files for body in file.bodies if body.graph is not None}
        ports = {interface.definition: interface for interface in self.interfaces.bodies}
        models = {model.definition: model for model in self.frames}
        if len(models) != len(self.frames) or set(models) != set(bodies) or set(ports) != set(bodies):
            raise ValueError("frame inventories require one frame and interface per emitted body")
        for definition, model in models.items():
            model.to_dict()
            if model.region != bodies[definition].graph.root or model.region != ports[definition].region:
                raise ValueError("frame inventory root differs from its body/interface")

    def summary(self):
        bodies = [body for file in self.files for body in file.bodies]
        summary = {
            "source_files": len(self.files),
            "definitions": sum(len(file.definitions) for file in self.files),
            "source_calls": sum(len(file.calls) for file in self.files),
            "source_calls_with_candidates": sum(bool(call.candidates) for file in self.files for call in file.calls),
            "cross_file_call_witnesses": sum(bool(witness.through_imports) for file in self.files
                                            for call in file.calls for witness in call.candidate_witnesses),
            "implicit_invocations": sum(len(file.implicit_invocations) for file in self.files),
            "coverage_atoms": sum(len(file.coverage) for file in self.files),
            "coverage_statuses": dict(sorted(Counter(entry.status.value for file in self.files for entry in file.coverage).items())),
            "body_statuses": dict(sorted(Counter(body.status.value for body in bodies).items())),
            "core_operations": sum(len(body.graph.operations) for body in bodies if body.graph),
            "construction_operations": sum(body.construction_operations for body in bodies),
            "core_values": sum(len(body.graph.values) for body in bodies if body.graph),
            "discovery_gaps": len(self.discovery.gaps),
            "inventory_issues": sum(len(file.gaps) for file in self.files),
            "runtime_reachability_established": False, "whole_program_graph_established": False,
            "fine_state_effects_established": False, "transformation_authorized": False,
            "annotation_evaluation_policy_established": False,
        }
        if self.runtime_scope is not None:
            summary["runtime"] = self.runtime_scope.summary()
        if self.expansion is not None:
            summary["expansion"] = {
                "demand_kinds": dict(sorted(Counter(origin.kind.value
                    for entry in self.expansion.entries for origin in entry.origins).items()))
                    if self.call_sources is not None else dict(sorted(Counter(entry.kind.value
                        for entry in self.expansion.entries).items())),
                "attempted": sum(entry.attempted for entry in self.expansion.entries),
                "operation_budget_charged": sum(entry.operation_budget_charged for entry in self.expansion.entries),
                "unknown_construction_costs": sum(not entry.construction_cost_known for entry in self.expansion.entries),
                "unavailable_contexts": len(self.expansion.unavailable_contexts),
            }
        if self.call_sources is not None:
            summary["call_sources"] = self.call_sources.summary()
            summary["call_source_scope"] = dict(sorted(Counter(
                admission.status.value for admission in self.call_source_scope.admissions).items()))
        if self.interfaces is not None:
            summary["interfaces"] = {
                "signatures": len(self.interfaces.signatures),
                "bound_bodies": len(self.interfaces.bodies),
                "binding_statuses": dict(sorted(Counter(b.status.value for b in self.interfaces.bindings).items())),
                "issues": len(self.interfaces.issues),
                "live_call_binding_established": False,
            }
        if self.profile in (BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV):
            summary["structured"] = {
                "profile": self.profile.value, "bodies": len(self.structured),
                "protocols": sum(len(model.protocols) for model in self.structured),
                "loops": sum(len(model.loops) for model in self.structured),
                "runtime_conditions_established": False, "release_established": False,
                "completion_guaranteed": False,
            }
        elif self.profile is not None:
            summary["frames"] = {
                "profile": self.profile.value, "bodies": len(self.frames),
                "transitions": dict(sorted(Counter(transition.kind.value for model in self.frames
                                                    for transition in model.transitions).items())),
                "runtime_conditions_established": False, "release_established": False,
                "completion_guaranteed": False,
            }
        return summary

    def to_dict(self):
        self._check_profile()
        document = {
            "schema": "scar.program-inventory", "schema_version": 8 if self.profile is BodyLoweringProfile.STRUCTURED_ENV else 7 if self.profile is BodyLoweringProfile.STRUCTURED_BODY else 6 if self.call_sources is not None else 5 if self.profile is not None else 4 if self.interfaces is not None else 3 if self.expansion is not None else 2 if self.runtime_scope is not None else 1,
            "scope": "source-discovered candidate files, scoped interfaces and bounded automatic body lowering",
            "discovery": encode(self.discovery), "files": [_file_document(file) for file in self.files],
            "budget": encode(self.budget), "summary": self.summary(),
            "target_executed": False, "transformation_authorized": False,
        }
        if self.runtime_scope is not None:
            document["runtime_scope"] = encode(self.runtime_scope)
        if self.expansion is not None:
            document["expansion"] = encode(self.expansion)
        if self.interfaces is not None:
            if self.expansion is None:
                raise ValueError("interface reports require global root-only expansion")
            document["runtime_scope"] = encode(self.runtime_scope)
            document["interfaces"] = encode(self.interfaces)
        if self.profile is not None:
            document["profile"] = self.profile.value
            if self.profile in (BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV):
                document["structured"] = encode(self.structured)
                document["call_sources"] = self.call_sources.to_dict() if self.call_sources is not None else None
                document["call_source_scope"] = encode(self.call_source_scope)
            else:
                document["frames"] = encode(self.frames)
        if self.call_sources is not None:
            document["call_sources"] = self.call_sources.to_dict()
            document["call_source_scope"] = encode(self.call_source_scope)
        return document

    @classmethod
    def from_dict(cls, document, *, max_files=128, max_bytes=8_000_000, max_directories=4096,
                  max_lowered_bodies=256, max_operations=10000, max_call_witnesses=4096,
                  runtime_verification_budget=RuntimeTraceBudget(), max_compile_attempts=1024,
                  context_verification_budget=ContextStoreBudget(),
                  call_verification_budget=CallEdgeBudget()):
        if type(document) is not dict:
            raise ValueError("inventory fields mismatch")
        version = document.get("schema_version")
        if type(version) is not int or version not in (1, 2, 3, 4, 5, 6, 7, 8):
            raise ValueError("inventory schema/version mismatch")
        expected_fields = {
                "schema", "schema_version", "scope", "discovery", "files", "budget", "summary",
                "target_executed", "transformation_authorized"}
        if version >= 2:
            expected_fields.add("runtime_scope")
        if version >= 3:
            expected_fields.add("expansion")
        if version >= 4:
            expected_fields.add("interfaces")
        if version in (5, 6):
            expected_fields.update(("profile", "frames"))
        if version in (6, 7, 8):
            expected_fields.update(("call_sources", "call_source_scope"))
        if version in (7, 8):
            expected_fields.update(("profile", "structured"))
        if set(document) != expected_fields:
            raise ValueError("inventory fields mismatch")
        if document["schema"] != "scar.program-inventory":
            raise ValueError("inventory schema/version mismatch")
        if version in (7, 8):
            if (document["scope"] != "source-discovered candidate files, scoped interfaces and bounded automatic body lowering"
                    or document["target_executed"] is not False or document["transformation_authorized"] is not False
                    or type(document["files"]) is not list or type(document["summary"]) is not dict):
                raise ValueError("structured inventory header/type/authority mismatch")
            required_profile = (BodyLoweringProfile.STRUCTURED_ENV if version == 8 else BodyLoweringProfile.STRUCTURED_BODY)
            if decode(BodyLoweringProfile, document["profile"]) is not required_profile:
                raise ValueError("inventory version requires its exact structured profile")
            interfaces = decode(FunctionInterfaces, document["interfaces"])
            if interfaces.profile is not required_profile:
                raise ValueError("structured inventory interface profile mismatch")
            models = decode(tuple[StructuredBodyModel, ...], document["structured"])
            if len({model.definition for model in models}) != len(models):
                raise ValueError("duplicate structured inventory model")
            if document["call_sources"] is None:
                if document["call_source_scope"] is not None:
                    raise ValueError("structured source inventory cannot carry an unbound call scope")
            elif document["runtime_scope"] is not None:
                raise ValueError("structured calls and legacy runtime observations are separate modes")
            else:
                decode(CallSourceScope, document["call_source_scope"])
        requested = decode(InventoryBudget, document["budget"])
        ceiling = InventoryBudget(max_files, max_bytes, max_directories, max_lowered_bodies, max_operations, max_call_witnesses)
        _check_budget(requested); _check_budget(ceiling)
        for field in requested.__dataclass_fields__:
            if getattr(requested, field) > getattr(ceiling, field):
                raise ValueError("report exceeds independent verifier budget: " + field)
        if version in (7, 8):
            _check_structured_declarations(document, interfaces, models, requested)
        discovery = decode(SourceDiscovery, document["discovery"])
        roots = discovery.source_roots if discovery.root_mode is DiscoveryRootMode.DECLARED else ()
        if version == 6 or version in (7, 8) and document["call_sources"] is not None:
            from scar.analysis.call_demand import replay_inventory_from_calls
            rebuilt = replay_inventory_from_calls(document, discovery=discovery, roots=roots,
                budget=requested, context_ceiling=context_verification_budget,
                call_ceiling=call_verification_budget)
            if _canonical(rebuilt.to_dict()) != _canonical(document):
                raise ValueError("inventory differs from current raw call/source/discovery/context replay")
            return rebuilt
        if version >= 3:
            expansion = decode(ExpansionSchedule, document["expansion"])
            _check_context_budget(expansion.budget, context_verification_budget)
        runtime_options = {}
        if version >= 4:
            # Decode and validate typed interfaces before expensive source replay.
            interfaces = decode(FunctionInterfaces, document["interfaces"])
            expected_profile = (BodyLoweringProfile.STRUCTURED_ENV if version == 8 else
                                BodyLoweringProfile.STRUCTURED_BODY if version == 7 else
                                BodyLoweringProfile.BOUND_FRAME if version == 5 else BodyLoweringProfile.BOUND_FORMALS)
            if interfaces.profile is not expected_profile:
                raise ValueError("inventory version differs from its interface profile")
            runtime_options["interface_model"] = True
        if version == 5:
            if decode(BodyLoweringProfile, document["profile"]) is not BodyLoweringProfile.BOUND_FRAME:
                raise ValueError("inventory v5 requires BOUND_FRAME_V1 profile")
            decode(tuple[FrameModel, ...], document["frames"])
        if version >= 2 and not (version >= 4 and document["runtime_scope"] is None):
            runtime = decode(RuntimeScope, document["runtime_scope"])
            check_runtime_ceiling(runtime.trace.budget, runtime_verification_budget)
            check_compile_limit(max_compile_attempts)
            if runtime.max_compile_attempts > max_compile_attempts:
                raise ValueError("report exceeds independent verifier max_compile_attempts")
            current_trace = read_runtime_trace(runtime.trace.manifest.logical_path, budget=runtime.trace.budget)
            if encode(current_trace) != encode(runtime.trace):
                raise ValueError("runtime trace differs from its bound raw evidence replay")
            runtime_options = {"runtime": current_trace,
                               "max_compile_attempts": runtime.max_compile_attempts,
                               "global_expansion": version >= 3,
                               "interface_model": version >= 4}
        # Apply the historical profile after runtime options are assembled: a
        # trace-bearing report must not silently replace it with a new default.
        if version >= 4:
            runtime_options["body_profile"] = expected_profile
        if version >= 3:
            runtime_options["context_budget"] = expansion.budget
        rebuilt = _inventory_from_inputs(discovery.entry, project_root=discovery.project_root,
                                         source_roots=roots, budget=requested, **runtime_options)
        if _canonical(rebuilt.to_dict()) != _canonical(document):
            raise ValueError("inventory differs from current source/discovery/context replay")
        return rebuilt


def _check_structured_declarations(document, interfaces, models, budget):
    """Reject contradictory v7 ownership before reading source or raw evidence.

    This checks declared endpoints, not source truth. Exact construction is
    independently replayed after the header, types and ceilings are admitted.
    """
    if len(document["files"]) > budget.max_files:
        raise ValueError("structured inventory file count exceeds its budget")
    definitions, bodies, operations = {}, {}, 0
    body_fields = {"definition", "status", "graph", "metadata", "reason", "construction_operations"}
    for file in document["files"]:
        if type(file) is not dict or type(file.get("bodies")) is not list:
            raise ValueError("structured inventory file/body fields mismatch")
        for definition in decode(tuple[DefinitionInventory, ...], file.get("definitions")):
            if definition.id in definitions:
                raise ValueError("duplicate structured inventory definition")
            definitions[definition.id] = definition
        for body in file["bodies"]:
            if type(body) is not dict or set(body) != body_fields:
                raise ValueError("structured inventory body fields mismatch")
            definition = decode(OperationDefinitionID, body["definition"])
            status = decode(BodyStatus, body["status"])
            if body["graph"] is None:
                if status is BodyStatus.LOWERED_WITH_GAPS:
                    raise ValueError("lowered structured body has no graph")
                continue
            graph = body["graph"]
            if (status is not BodyStatus.LOWERED_WITH_GAPS or type(graph) is not dict
                    or type(graph.get("operations")) is not list or definition in bodies):
                raise ValueError("structured body graph/status/identity mismatch")
            bodies[definition] = decode(RegionID, graph.get("root"))
            operations += len(graph["operations"])
    ports = {interface.definition: interface for interface in interfaces.bodies}
    overlays = {model.definition: model for model in models}
    if (len(bodies) > budget.max_lowered_bodies or operations > budget.max_operations):
        raise ValueError("structured inventory graphs exceed construction budget")
    if set(overlays) != set(bodies) or set(ports) != set(bodies):
        raise ValueError("structured inventories require one model and interface per emitted body")
    for definition, root in bodies.items():
        if (definition not in definitions or overlays[definition].region != root
                or ports[definition].region != root or overlays[definition].source != definitions[definition].source):
            raise ValueError("structured inventory model differs from its body/interface/source")


def _check_budget(budget):
    for name in budget.__dataclass_fields__:
        value = getattr(budget, name)
        if type(value) is not int or value < 1:
            raise ValueError("inventory budget must contain positive integers: " + name)
    if budget.max_operations > 100000:
        raise ValueError("operation budget exceeds core construction ceiling")


def _check_context_budget(requested, ceiling=None):
    if type(requested) is not ContextStoreBudget:
        raise TypeError("context budget must be a ContextStoreBudget")
    requested.__post_init__()
    if ceiling is not None:
        _check_context_budget(ceiling)
        for field in requested.__dataclass_fields__:
            if getattr(requested, field) > getattr(ceiling, field):
                raise ValueError("report exceeds independent context verifier budget: " + field)


def _unsupported(node):
    """Coverage classification only. The lowerer remains the construction authority."""
    if isinstance(node, ast.stmt):
        if isinstance(node, ast.Assign):
            return "only a single local Name assignment is connected" if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name) else ""
        if not isinstance(node, (ast.Expr, ast.Pass, ast.Return, ast.If)):
            return "statement/interface not connected by current body lowerer: " + type(node).__name__
    if isinstance(node, ast.expr):
        if isinstance(node, ast.Constant):
            try:
                LiteralOrigin(node.value)
            except (TypeError, ValueError):
                return "literal is outside the core's exact scalar representation"
        if isinstance(node, (ast.Attribute, ast.Subscript)) and not isinstance(node.ctx, ast.Load):
            return "state write/delete location is not connected"
        if isinstance(node, ast.Call):
            if any(isinstance(arg, ast.Starred) for arg in node.args) or any(k.arg is None for k in node.keywords):
                return "expanded call binding is not connected"
        elif isinstance(node, ast.Compare):
            if len(node.ops) != 1:
                return "chained comparison control is not connected"
        elif isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Slice):
                return "slice representation is not connected"
        elif not isinstance(node, (ast.Name, ast.Constant, ast.BinOp, ast.UnaryOp, ast.Attribute, ast.Tuple, ast.List)):
            return "expression/control not connected by current body lowerer: " + type(node).__name__
    return ""


@dataclass(frozen=True, slots=True)
class _SourceWitnessIndex:
    """Small source projection consumed by call/source matching.

    It deliberately has no SourceContextDigest: the call matcher does not
    consume the three serialized semantic/control layer digests.
    """

    snapshot: SourceSnapshot
    definitions: tuple[DefinitionInventory, ...]
    calls: tuple[CallInventory, ...]
    coverage: tuple[CoverageEntry, ...]


class _Inventory:
    def __init__(self, context, remaining_bodies, remaining_operations, runtime_builder=None):
        self.context = context
        self.remaining_bodies, self.remaining_operations = remaining_bodies, remaining_operations
        self.runtime_builder = runtime_builder
        self.definitions, self.calls, self.coverage, self.bodies, self.gaps, self.implicit = [], [], [], [], [], []
        self.nodes = {}
        self.refs = {(atom.kind, atom.reference.start_line, atom.reference.end_line,
                      atom.reference.start_column, atom.reference.end_column): atom.reference
                     for atom in context.semantic.source_atoms.values()}
        self.by_atom = defaultdict(list)
        for definition in context.semantic.definitions.values():
            self.by_atom[definition.code_id].append(definition)
        self.old_semantics = defaultdict(list)
        for operation in context.semantics.operations.values():
            self.old_semantics[operation.source.atom_id].append(operation)
        self.bindings_by_slot = defaultdict(list)
        for binding in context.semantics.bindings.values():
            self.bindings_by_slot[binding.slot].append(binding)
        self.module = next(module.initializer for module in context.semantic.modules.values()
                           if module.path == str(context.path))

    def source(self, node):
        return self.refs[(type(node).__name__, node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)]

    def identity(self, node, *, body=False):
        ref = self.source(node)
        matches = self.by_atom[ref.atom_id.wire]
        if body:
            matches = [definition for definition in matches if definition.metadata.get("phase") == "call_time"]
        if len(matches) == 1:
            return matches[0].id
        if not matches or not body:
            # An annotation subtree can have one opaque legacy operation for
            # many AST calls. Inventory identities never claim to be that op.
            return OperationDefinitionID("inventory:" + _digest([ref.path, ref.atom_id.wire, "body" if body else "operation"])[:32])
        raise ValueError("definition body source has ambiguous legacy identity")

    def parameters(self, node):
        args = node.args
        positional = args.posonlyargs + args.args
        defaults = dict(zip([arg.arg for arg in positional[len(positional)-len(args.defaults):]], args.defaults))
        defaults.update({arg.arg:default for arg, default in zip(args.kwonlyargs, args.kw_defaults) if default is not None})
        groups = ((args.posonlyargs, ParameterKind.POSITIONAL_ONLY), (args.args, ParameterKind.POSITIONAL),
                  ((args.vararg,) if args.vararg else (), ParameterKind.VAR_POSITIONAL),
                  (args.kwonlyargs, ParameterKind.KEYWORD_ONLY), ((args.kwarg,) if args.kwarg else (), ParameterKind.VAR_KEYWORD))
        return tuple(ParameterInventory(arg.arg, kind, self.source(arg),
                     self.source(defaults[arg.arg]) if arg.arg in defaults else None,
                     self.source(arg.annotation) if arg.annotation is not None else None)
                     for values, kind in groups for arg in values)

    def define(self, node, owner, phase, prefix):
        is_class = isinstance(node, ast.ClassDef)
        is_lambda = isinstance(node, ast.Lambda)
        kind = (DefinitionKind.CLASS if is_class else DefinitionKind.LAMBDA if is_lambda else
                DefinitionKind.ASYNC_FUNCTION if isinstance(node, ast.AsyncFunctionDef) else DefinitionKind.FUNCTION)
        name = node.name if not is_lambda else f"<lambda@{node.lineno}:{node.col_offset}>"
        qualname = prefix + name
        identifier = self.identity(node, body=not is_class)
        lexical_owner = None if owner == self.module else owner
        inputs = []
        def input_nodes(nodes, role, execution_owner=owner, input_phase=phase):
            for index, value in enumerate(nodes):
                inputs.append(DefinitionInput(role, index, self.source(value)))
                self.walk(value, execution_owner, input_phase, prefix)
        input_nodes(getattr(node, "decorator_list", ()), DefinitionInputRole.DECORATOR)
        for decorator in getattr(node, "decorator_list", ()):
            self.implicit.append(ImplicitInvocation(self.source(decorator), identifier, owner, phase, "DECORATOR_APPLICATION"))
        if is_class:
            input_nodes(node.bases, DefinitionInputRole.BASE)
            for index, keyword in enumerate(node.keywords):
                role = DefinitionInputRole.METACLASS if keyword.arg == "metaclass" else DefinitionInputRole.CLASS_KEYWORD
                inputs.append(DefinitionInput(role, index, self.source(keyword.value)))
                self.walk(keyword, owner, phase, prefix)
            parameters = ()
            self.implicit.append(ImplicitInvocation(self.source(node), identifier, owner, phase, "CLASS_CONSTRUCTION"))
        else:
            parameters = self.parameters(node)
            input_nodes(node.args.defaults, DefinitionInputRole.DEFAULT)
            input_nodes((value for value in node.args.kw_defaults if value is not None), DefinitionInputRole.KEYWORD_DEFAULT)
            for parameter in parameters:
                self.coverage.append(CoverageEntry(parameter.source, identifier, ExecutionPhase.FUNCTION_BODY,
                    "arg", CoverageStatus.INVENTORY_ONLY, "formal interface inventoried; body construction checked separately"))
            annotations = [arg.annotation for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
                           *((node.args.vararg,) if node.args.vararg else ()), *((node.args.kwarg,) if node.args.kwarg else ())) if arg.annotation is not None]
            if getattr(node, "returns", None) is not None:
                annotations.append(node.returns)
            input_nodes(annotations, DefinitionInputRole.ANNOTATION, owner, ExecutionPhase.ANNOTATION)
            for annotation in annotations:
                self.gaps.append(InventoryIssue(str(self.context.path),
                    "annotation declaration context retained; eager/lazy timing and annotation-thunk scope remain unverified",
                    self.source(annotation)))
        for parameter in getattr(node, "type_params", ()):
            self.walk(parameter, identifier, ExecutionPhase.ANNOTATION, prefix)
        definition = DefinitionInventory(identifier, self.source(node), name, qualname, kind,
                                         lexical_owner, parameters, tuple(inputs))
        self.definitions.append(definition)
        self.nodes[identifier] = node
        body_phase = ExecutionPhase.CLASS_BODY if is_class else ExecutionPhase.FUNCTION_BODY
        body = (node.body,) if is_lambda else node.body
        for child in body:
            self.walk(child, identifier, body_phase, qualname + ".")

    def walk(self, node, owner, phase, prefix):
        if not isinstance(node, ast.AST):
            return
        if hasattr(node, "lineno") and isinstance(node, (ast.stmt, ast.expr, ast.arg, ast.alias, ast.keyword, ast.ExceptHandler)):
            reason = _unsupported(node)
            status = CoverageStatus.UNSUPPORTED if reason else CoverageStatus.INVENTORY_ONLY
            self.coverage.append(CoverageEntry(self.source(node), owner, phase, type(node).__name__, status,
                                               reason or "source syntax inventoried; core connection/effects checked separately"))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            self.define(node, owner, phase, prefix)
            return
        if isinstance(node, ast.Call):
            old = [op for op in self.old_semantics[self.source(node).atom_id] if op.opcode.value == "call"]
            old_id = old[0].operation if len(old) == 1 else None
            binding, imports, attributes = self.import_inputs(node.func)
            self.calls.append(CallInventory(old_id or self.identity(node), self.source(node), owner, phase,
                semantic_operation=old_id, callee_binding=binding, import_bindings=imports, attribute_path=attributes))
        if isinstance(node, ast.AnnAssign):
            self.walk(node.target, owner, phase, prefix)
            if node.value is not None:
                self.walk(node.value, owner, phase, prefix)
            self.walk(node.annotation, owner, ExecutionPhase.ANNOTATION, prefix)
            return
        if isinstance(node, getattr(ast, "TypeAlias", ())):
            self.walk(node.name, owner, phase, prefix)
            for parameter in node.type_params:
                self.walk(parameter, owner, ExecutionPhase.ANNOTATION, prefix)
            self.walk(node.value, owner, ExecutionPhase.ANNOTATION, prefix)
            self.gaps.append(InventoryIssue(str(self.context.path),
                "type-alias evaluation scope/timing remains unverified", self.source(node)))
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            identifier = self.identity(node)
            kind = type(node).__name__
            qualname = prefix + f"<{kind}@{node.lineno}:{node.col_offset}>"
            self.definitions.append(DefinitionInventory(identifier, self.source(node), kind, qualname,
                DefinitionKind.COMPREHENSION, None if owner == self.module else owner))
            self.nodes[identifier] = node
            for index, generator in enumerate(node.generators):
                self.walk(generator.iter, owner if index == 0 else identifier,
                          phase if index == 0 else ExecutionPhase.COMPREHENSION_BODY, prefix)
                self.walk(generator.target, identifier, ExecutionPhase.COMPREHENSION_BODY, qualname + ".")
                for condition in generator.ifs:
                    self.walk(condition, identifier, ExecutionPhase.COMPREHENSION_BODY, qualname + ".")
            for key in ("elt", "key", "value"):
                value = getattr(node, key, None)
                if value is not None:
                    self.walk(value, identifier, ExecutionPhase.COMPREHENSION_BODY, qualname + ".")
            return
        for child in ast.iter_child_nodes(node):
            self.walk(child, owner, phase, prefix)

    def import_inputs(self, expression):
        attributes = []
        while isinstance(expression, ast.Attribute):
            attributes.append(expression.attr)
            expression = expression.value
        if not isinstance(expression, ast.Name):
            return None, (), tuple(reversed(attributes))
        reads = [op for op in self.old_semantics[self.source(expression).atom_id] if op.binding_use is not None]
        if len(reads) != 1:
            return None, (), tuple(reversed(attributes))
        use = self.context.semantics.uses[reads[0].binding_use]
        witnesses = []
        for binding in self.bindings_by_slot[use.slot]:
            operation = self.context.semantics.operations.get(binding.definition)
            if operation is None or operation.import_spec is None:
                continue
            if binding.scope == use.scope and binding.id not in (*use.reaching, *use.conditional_reaching):
                continue
            spec = operation.import_spec
            if spec.bound_name == expression.id:
                witnesses.append(ImportBindingWitness(operation.source, expression.id, spec.requested, spec.symbol, spec.asname))
        return reads[0].binding_use, tuple(dict.fromkeys(witnesses)), tuple(reversed(attributes))

    def run(self):
        for node in self.context.tree.body:
            self.walk(node, self.module, ExecutionPhase.MODULE_INITIALIZATION, "")
        preferred = self.runtime_builder.bind(self.context) if self.runtime_builder is not None else frozenset()
        for definition in sorted(self.definitions, key=lambda definition: definition.id not in preferred):
            if definition.kind not in (DefinitionKind.FUNCTION, DefinitionKind.ASYNC_FUNCTION):
                self.bodies.append(BodyInventory(definition.id, BodyStatus.NOT_ATTEMPTED, None, None,
                                                "this scope requires a class/lambda/comprehension interface beyond the current body lowerer"))
                continue
            if self.remaining_bodies < 1 or self.remaining_operations < 1:
                self.bodies.append(BodyInventory(definition.id, BodyStatus.NOT_ATTEMPTED, None, None,
                                                "independent body/aggregate operation construction budget exhausted"))
                continue
            self.remaining_bodies -= 1
            try:
                result = self.context.lower(definition.qualname, source=definition.source,
                                            max_operations=self.remaining_operations)
            except (ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
                detail = "body construction error: " + str(error)
                self.gaps.append(InventoryIssue(str(self.context.path), detail, definition.source))
                self.bodies.append(BodyInventory(definition.id, BodyStatus.UNSUPPORTED, None, None, detail))
                self.remaining_operations = 0
                continue
            graph, metadata = result.graph, result.metadata
            self.remaining_operations -= result.operations_emitted
            reason = "; ".join(dict.fromkeys(gap.detail for gap in metadata.gaps))
            self.bodies.append(BodyInventory(definition.id,
                BodyStatus.LOWERED_WITH_GAPS if graph else BodyStatus.UNSUPPORTED, graph, metadata, reason,
                result.operations_emitted))
        return _attach_bodies(self.snapshot(), tuple(self.bodies))

    def index(self):
        """Publish only lightweight source structure; do not lower a body."""
        self._walk_source()
        return self.snapshot()

    def source_witness_index(self):
        """Publish the call-matcher projection without serializing full layers."""
        self._walk_source()
        self._validate_coverage()
        return _SourceWitnessIndex(
            self.context.semantics.sources[str(self.context.path)],
            tuple(self.definitions), tuple(self.calls), tuple(self.coverage),
        )

    def _walk_source(self):
        for node in self.context.tree.body:
            self.walk(node, self.module, ExecutionPhase.MODULE_INITIALIZATION, "")
        if self.runtime_builder is not None:
            self.runtime_builder.bind(self.context)

    def _validate_coverage(self):
        # A source atom receives exactly one execution-owner/phase inventory.
        expected = {atom.id for atom in self.context.semantic.source_atoms.values()}
        actual = [entry.source.atom_id for entry in self.coverage]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise ValueError("inventory source coverage has missing or duplicate atoms")

    def snapshot(self):
        self._validate_coverage()
        digest = SourceContextDigest(str(self.context.root), _digest(self.context.semantic.to_dict()),
                                     _digest(self.context.semantics.to_dict()), _digest(self.context.control.to_dict()))
        return FileInventory(self.context.semantics.sources[str(self.context.path)], tuple(self.definitions),
                             tuple(self.calls), tuple(self.coverage), tuple(self.bodies), tuple(self.gaps), digest,
                             tuple(self.implicit))


def _body_connections(bodies):
    linked, candidates, supported = set(), {}, set()
    for body in bodies:
        if body.graph is None:
            continue
        supported.add(body.definition)
        metadata = body.metadata
        linked.update(link.source.atom_id for link in (*metadata.operation_links, *metadata.value_links, *metadata.use_links))
        op_sources = {link.operation:link for link in metadata.operation_links}
        for target in metadata.call_targets:
            link = op_sources[target.operation]
            if link.semantic_operation is not None and target.source_definition is not None:
                candidates[link.semantic_operation] = (target.source_definition,)
    return linked, candidates, supported


def _attach_bodies(file, bodies, *, call_witnesses=None, body_profile=None):
    linked, candidates, supported = _body_connections(bodies)
    definitions = tuple(replace(definition, body_supported=definition.id in supported) for definition in file.definitions)
    by_id = {definition.id:definition for definition in definitions}
    if call_witnesses is None:
        call_witnesses = {call.operation:tuple(CallCandidateWitness(identifier, by_id[identifier].source, (),
            (CandidateCondition.SOURCE_BINDING_REACHES_READ, CandidateCondition.SOURCE_BODY_MATCHES_LIVE_CALLABLE,
             CandidateCondition.NO_EXTERNAL_NAMESPACE_MUTATION))
            for identifier in candidates.get(call.operation, ()) if identifier in by_id) for call in file.calls}
    calls = tuple(replace(call, candidate_witnesses=call_witnesses.get(call.operation, ()),
                          candidates=tuple(dict.fromkeys(w.definition for w in call_witnesses.get(call.operation, ()))))
                  for call in file.calls)
    coverage = tuple(replace(entry, status=CoverageStatus.CONNECTED,
        reason="source atom connected to a generated body graph; dynamic effects/target may remain unknown")
        if entry.source.atom_id in linked and (entry.status is not CoverageStatus.UNSUPPORTED
                                              or body_profile in (BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV))
        and entry.phase is not ExecutionPhase.ANNOTATION
        and entry.ast_kind not in {"FunctionDef", "AsyncFunctionDef", "ClassDef", "Lambda"} else entry
        for entry in file.coverage)
    return replace(file, definitions=definitions, calls=calls, coverage=coverage, bodies=bodies)


def inventory_program(entry, *, project_root=None, source_roots=(), max_files=128, max_bytes=8_000_000,
                      max_directories=4096, max_lowered_bodies=256, max_operations=10000, max_call_witnesses=4096,
                      runtime_trace=None, runtime_budget=RuntimeTraceBudget(), max_compile_attempts=1024,
                      context_budget=ContextStoreBudget(), calls_trace=None, call_budget=CallEdgeBudget(),
                      body_profile=BodyLoweringProfile.BOUND_FRAME):
    budget = InventoryBudget(max_files, max_bytes, max_directories, max_lowered_bodies, max_operations, max_call_witnesses)
    _check_budget(budget)
    _check_context_budget(context_budget)
    if type(body_profile) is not BodyLoweringProfile or body_profile not in (
            BodyLoweringProfile.BOUND_FRAME, BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV):
        raise ValueError("public inventory requires an explicit frame or structured body profile")
    if calls_trace is not None:
        if runtime_trace is not None:
            raise ValueError("calls input and legacy runtime trace are separate inventory modes")
        from scar.analysis.call_demand import inventory_from_calls
        return inventory_from_calls(entry, project_root=project_root, source_roots=source_roots,
            budget=budget, call_trace=calls_trace, call_budget=call_budget, context_budget=context_budget,
            body_profile=body_profile)
    trace = read_runtime_trace(runtime_trace, budget=runtime_budget) if runtime_trace is not None else None
    return _inventory_from_inputs(entry, project_root=project_root, source_roots=source_roots,
                                  budget=budget, runtime=trace, max_compile_attempts=max_compile_attempts,
                                  context_budget=context_budget, interface_model=True,
                                  body_profile=body_profile)


def _inventory_from_inputs(entry, *, project_root, source_roots, budget, runtime=None, max_compile_attempts=1024,
                           global_expansion=True, context_budget=ContextStoreBudget(), interface_model=False,
                           body_profile=None):
    """Construct from raw-source settings and observations read by the adapter.

    Public report replay re-reads the bound trace before calling here. This
    shares that bounded read with construction, without accepting report seeds.
    """
    _check_budget(budget)
    if type(interface_model) is not bool:
        raise ValueError("interface_model must be an exact boolean")
    if interface_model and not global_expansion:
        raise ValueError("bound interfaces require global root-only expansion")
    if body_profile is not None and (type(body_profile) is not BodyLoweringProfile
            or body_profile not in (BodyLoweringProfile.BOUND_FORMALS, BodyLoweringProfile.BOUND_FRAME,
                                    BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV)
            or not interface_model):
        raise ValueError("explicit bound profile requires the corresponding interface model")
    runtime_builder, paths = None, ()
    limits = {"project_root": project_root, "source_roots": source_roots,
              "max_files": budget.max_files, "max_bytes": budget.max_bytes,
              "max_directories": budget.max_directories}
    if runtime is None:
        discovery = discover_sources(entry, **limits)
    else:
        root = Path(project_root).resolve() if project_root is not None else Path(entry).absolute().parent.resolve()
        seeds = resolve_runtime_seeds(runtime, root)
        paths = available_paths(seeds)
        discovery = _discover_sources_from_entries(entry, additional_entries=paths, **limits)
        runtime_builder = RuntimeScopeBuilder(runtime, seeds, max_compile_attempts)
    if interface_model or (runtime_builder is not None and global_expansion):
        from scar.analysis.program_expansion import expand_inventory
        _check_context_budget(context_budget)
        files, expansion, measurements, interfaces, frames, structured = expand_inventory(discovery, runtime_builder, budget, context_budget,
                                            _ordered_files(discovery, runtime_paths=paths), interface_model=interface_model,
                                            body_profile=body_profile)
        result = ProgramInventory(discovery, files, budget, runtime_builder.finish() if runtime_builder is not None else None,
                                  expansion, measurements, interfaces,
                                  body_profile if body_profile in (BodyLoweringProfile.BOUND_FRAME,
                                                                  BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV) else None,
                                  frames, structured=structured)
        result._check_profile()
        return result
    files = []
    remaining_bodies, remaining_operations = budget.max_lowered_bodies, budget.max_operations
    for file in _ordered_files(discovery, runtime_paths=paths):
        try:
            context = prepare_source(file.snapshot.path, project_root=discovery.project_root)
            if context.semantics.sources[file.snapshot.path].fingerprint != file.snapshot.fingerprint:
                raise ValueError("source changed between discovery and preparation")
            builder = _Inventory(context, remaining_bodies, remaining_operations, runtime_builder=runtime_builder)
            result = builder.run()
            if runtime_builder is not None:
                runtime_builder.file_emitted(result)
            remaining_bodies, remaining_operations = builder.remaining_bodies, builder.remaining_operations
        except (OSError, ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
            if runtime_builder is not None:
                runtime_builder.file_failed(file.snapshot.path)
            result = FileInventory(file.snapshot, (), (), (), (),
                                   (InventoryIssue(file.snapshot.path, "file preparation/inventory failed: " + str(error)),))
        files.append(result)
    return ProgramInventory(discovery, _link_import_calls(discovery, tuple(files), max_witnesses=budget.max_call_witnesses), budget,
                            runtime_builder.finish() if runtime_builder is not None else None)


def _ordered_files(discovery, *, runtime_paths=()):
    """Spend bounded lowering work near the entry before distant dependencies."""
    adjacency = defaultdict(set)
    for edge in discovery.imports:
        for candidate in edge.candidates:
            if not candidate.namespace:
                adjacency[edge.source.path].add(candidate.path)
            adjacency[edge.source.path].update(candidate.parent_initializers)
    distance = {path:0 for path in (discovery.entry, *runtime_paths)}
    pending = deque(distance)
    while pending:
        path = pending.popleft()
        for following in sorted(adjacency[path]):
            if following not in distance:
                distance[following] = distance[path] + 1
                pending.append(following)
    def key(file):
        path = file.snapshot.path
        rank = (0 if path == discovery.entry else 1 if path in runtime_paths else 2) if runtime_paths else 0
        return rank, distance.get(path, float("inf")), path
    return sorted(discovery.files, key=key)


def _link_import_calls(discovery, files, *, max_witnesses=4096):
    """Conditional source witnesses, never lookup by a global function name."""
    linker = _CallLinker(discovery, files, max_witnesses)
    return linker.finish()


class _CallLinker:
    """Shared resolver with demand-driven admission to one witness budget."""
    def __init__(self, discovery, files, max_witnesses):
        self.files = files
        self.by_path = {file.snapshot.path:file for file in files}
        self.edges = defaultdict(list)
        for dependency in discovery.imports:
            self.edges[dependency.source.path].append(dependency)
        self.exports, self.linked = {}, {}
        self.issues = defaultdict(list)
        self.max_witnesses = self.remaining = max_witnesses

    def export(self, path, symbol):
        key = (path, symbol)
        if key in self.exports:
            return self.exports[key]
        pending = deque([(path, symbol, ())])
        seen, found = set(), {}
        while pending and len(found) <= self.max_witnesses:
            current, name, through = pending.popleft()
            if (current, name) in seen or current not in self.by_path:
                continue
            seen.add((current, name))
            for definition in self.by_path[current].definitions:
                if (definition.lexical_owner is None and definition.name == name
                        and definition.kind in (DefinitionKind.FUNCTION, DefinitionKind.ASYNC_FUNCTION, DefinitionKind.CLASS)):
                    found.setdefault(definition.id, (definition, through))
                    if len(found) > self.max_witnesses:
                        break
            for edge in self.edges[current]:
                if edge.deferred or edge.owner_qualname != "<module>" or edge.bound_name != name or edge.symbol is None:
                    continue
                for candidate in edge.candidates:
                    if not candidate.namespace and candidate.role.value == "REQUESTED_MODULE":
                        pending.append((candidate.path, edge.symbol, (*through, edge.source)))
        self.exports[key] = tuple(found.values())
        return self.exports[key]

    def imported(self, call):
        for binding in call.import_bindings:
            # An unaliased `import p.child` binds p, not p.child.
            if binding.symbol is None and "." in binding.requested and binding.asname is None:
                continue
            for edge in self.edges[binding.source.path]:
                if (edge.source != binding.source or edge.bound_name != binding.bound_name
                        or edge.requested != binding.requested or edge.symbol != binding.symbol):
                    continue
                for candidate in edge.candidates:
                    if candidate.namespace or candidate.role.value == "PARENT_NAMESPACE":
                        continue
                    if binding.symbol is not None and candidate.role.value == "REQUESTED_MODULE" and not call.attribute_path:
                        symbol = binding.symbol
                    elif len(call.attribute_path) == 1 and (binding.symbol is None or candidate.role.value == "FROM_SUBMODULE"):
                        symbol = call.attribute_path[0]
                    else:
                        continue
                    for definition, through in self.export(candidate.path, symbol):
                        yield CallCandidateWitness(definition.id, definition.source,
                            (edge.source, *through), tuple(CandidateCondition))

    def link(self, call):
        if call.operation in self.linked:
            return self.linked[call.operation]
        remaining = self.remaining
        witnesses = list(call.candidate_witnesses)
        if remaining == 0:
            if call.import_bindings or witnesses:
                self.issues[call.source.path].append(InventoryIssue(call.source.path,
                    "call-candidate witness budget exhausted; source-call expansion not attempted", call.source))
            witnesses = ()
        else:
            unique = dict.fromkeys(witnesses[:remaining + 1])
            for witness in self.imported(call):
                unique.setdefault(witness, None)
                if len(unique) > remaining:
                    break
            witnesses = tuple(unique)
            if len(witnesses) > remaining:
                self.exhausted(call)
                witnesses = witnesses[:remaining]
            self.remaining -= len(witnesses)
        result = replace(call, candidates=tuple(dict.fromkeys(w.definition for w in witnesses)),
                         candidate_witnesses=tuple(witnesses))
        self.linked[call.operation] = result
        return result

    def exhausted(self, call):
        self.issues[call.source.path].append(InventoryIssue(call.source.path,
            "call-candidate witness budget exhausted; additional source candidates were not retained", call.source))

    def admit(self, call, witness):
        current = self.link(call)
        if witness in current.candidate_witnesses:
            return True
        if not self.remaining:
            self.exhausted(call)
            return False
        self.remaining -= 1
        witnesses = (*current.candidate_witnesses, witness)
        self.linked[call.operation] = replace(current, candidate_witnesses=witnesses,
                                            candidates=tuple(dict.fromkeys(w.definition for w in witnesses)))
        return True

    def finish(self):
        result = []
        for file in self.files:
            calls = tuple(self.link(call) for call in file.calls)
            result.append(replace(file, calls=calls, gaps=(*file.gaps, *self.issues[file.snapshot.path])))
        return tuple(result)


__all__ = ["ProgramInventory", "inventory_program"]
