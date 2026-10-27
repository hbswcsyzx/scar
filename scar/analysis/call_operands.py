"""Replayable, conditional cross-call routes from original operand evidence.

The report stores manifests and thin core templates. Instruction transcripts
remain in their bounded raw sidecar instead of being duplicated in each report.
Public replay always reads those inputs and rebuilds the routes from source.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from scar.analysis.call_edges import CallEdgeReport, _canonical, _link_call_model
from scar.ir.program.call_edges import (
    CallEdgeBudget, CallEdgeModel, CallLinkStatus, ReferenceOccurrence, ReferenceRole,
)
from scar.ir.program.call_operand_routes import OperandRouteBudget, OperandRouteModel
from scar.ir.program.call_operands import CallOperandBudget
from scar.ir.program.compilation import CallCompilationProfile
from scar.ir.record_codec import decode, encode

if TYPE_CHECKING:
    from scar.analysis.call_operand_reader import CallOperandTrace


_AUTHORITY = (
    "target_executed_by_linker", "function_environment_established",
    "contents_or_effects_established", "world_equivalence_established",
    "whole_program_complete", "transformation_authorized",
)
_FIELDS = {
    "schema", "schema_version", "trace", "project_root", "compilation_profile",
    "frame_budget", "operand_budget", "route_budget", "frame_files", "code_links",
    "operand_files", "operand_metadata", "inventory_sha256", "routing", "summary",
    *_AUTHORITY,
}
_PARTITION_FIELDS = {"source_body_access", "entry_parameters", "environments"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _bounded_budget(kind, value, ceiling):
    _require(type(ceiling) is kind, "independent verifier budget must be typed")
    ceiling.__post_init__()
    result = decode(kind, value)
    for name in result.__dataclass_fields__:
        _require(getattr(result, name) <= getattr(ceiling, name),
                 "operand report exceeds independent verifier budget: " + name)
    return result


@dataclass(frozen=True)
class CallOperandReport:
    frame_model: CallEdgeModel
    operands: CallOperandTrace
    routing: OperandRouteModel
    # Independent raw sidecar projection.  The historical v1 operand report
    # remains byte-compatible; callers explicitly retain this separate record.
    environments: dict | None = None
    source_body_access: dict | None = None
    entry_parameters: tuple[ReferenceOccurrence, ...] = ()

    def summary(self):
        result = {
            "frame": CallEdgeReport(self.frame_model).summary(),
            "operand_events": len(self.operands.events),
            "routing": self.routing.summary(),
            "scope": "conditional reference provenance; state, contents and effects remain separate",
            **{name: False for name in _AUTHORITY},
        }
        if self.source_body_access is not None:
            result["entry_parameter_occurrences"] = len(self.entry_parameters)
            result["source_body_storage"] = "PARTITIONED"
        return result

    def to_dict(self):
        result = {
            "schema": "scar.call-operand-links", "schema_version": 1,
            "trace": self.frame_model.trace,
            "project_root": self.frame_model.project_root,
            "compilation_profile": CallCompilationProfile.RECORDED_FUTURE_FLAGS.value,
            "frame_budget": encode(self.frame_model.budget),
            "operand_budget": encode(self.operands.budget),
            "route_budget": encode(self.routing.budget),
            "frame_files": encode(self.frame_model.files),
            "code_links": encode(self.frame_model.code_links),
            "operand_files": encode(self.operands.files),
            "operand_metadata": encode(self.operands.metadata),
            "inventory_sha256": self.frame_model.inventory_sha256,
            "routing": encode(self.routing), "summary": self.summary(),
            **{name: False for name in _AUTHORITY},
        }
        if self.source_body_access is not None:
            result.update({"schema_version": 2, "source_body_access": self.source_body_access,
                           "entry_parameters": encode(self.entry_parameters), "environments": self.environments})
        return result

    @staticmethod
    def check_replay_header(document, *, frame_ceiling=CallEdgeBudget(),
                            operand_ceiling=CallOperandBudget(), route_ceiling=OperandRouteBudget()):
        """Validate versions, authority and independent limits before input I/O."""
        _require(type(document) is dict and type(document.get("schema_version")) is int
                 and document["schema_version"] in (1, 2), "operand link report version mismatch")
        partitioned = document["schema_version"] == 2
        _require(set(document) == (_FIELDS | _PARTITION_FIELDS if partitioned else _FIELDS),
                 "operand link report fields mismatch")
        _require(document["schema"] == "scar.call-operand-links"
                 and type(document["schema_version"]) is int and document["schema_version"] in (1, 2),
                 "operand link report schema/version mismatch")
        _require(document["compilation_profile"] == CallCompilationProfile.RECORDED_FUTURE_FLAGS.value,
                 "operand link report compilation profile mismatch")
        _require(all(document[name] is False for name in _AUTHORITY),
                 "operand link report cannot establish execution or optimization authority")
        for name in ("trace", "project_root", "inventory_sha256"):
            _require(type(document[name]) is str and bool(document[name]),
                     "operand report requires nonempty " + name)
        frame = _bounded_budget(CallEdgeBudget, document["frame_budget"], frame_ceiling)
        operand = _bounded_budget(CallOperandBudget, document["operand_budget"], operand_ceiling)
        route = _bounded_budget(OperandRouteBudget, document["route_budget"], route_ceiling)
        # The model is untrusted. Decode with its independent limits already
        # checked, then rebuild it rather than consuming its claimed edges.
        routing = OperandRouteModel.from_dict(document["routing"])
        _require(routing.budget == route, "route model and report budgets disagree")
        if partitioned:
            _require(type(document["source_body_access"]) is dict
                     and document["source_body_access"].get("current_raw_scan_verified") is True
                     and document["source_body_access"].get("transformation_authorized") is False,
                     "partition report lacks its bounded source/current-capture receipts")
            decode(tuple[ReferenceOccurrence, ...], document["entry_parameters"])
        return frame, operand, route

    @classmethod
    def from_dict(cls, document, *, inventory=None, composition=None, source_bindings=None,
                  coordinates=None, code_witnesses=None, frame_ceiling=CallEdgeBudget(),
                  operand_ceiling=CallOperandBudget(), route_ceiling=OperandRouteBudget()):
        frame, operand, route = cls.check_replay_header(
            document, frame_ceiling=frame_ceiling, operand_ceiling=operand_ceiling,
            route_ceiling=route_ceiling,
        )
        partitioned = document["schema_version"] == 2
        if partitioned:
            _require(code_witnesses is not None and not code_witnesses.writable
                     and not code_witnesses.compile_missing, "public v2 replay needs a read-only CodeWitnessStore")
        else:
            _require(all(value is None for value in (composition, source_bindings, coordinates, code_witnesses)),
                     "legacy v1 replay cannot accept partitioned inputs")
        rebuilt = link_call_operands(document["trace"], document["project_root"], inventory,
            composition=composition, source_bindings=source_bindings, coordinates=coordinates,
            code_witnesses=code_witnesses, frame_budget=frame, operand_budget=operand, route_budget=route,
            include_environments=partitioned and document["environments"] is not None)
        _require(_canonical(rebuilt.to_dict()) == _canonical(document),
                 "operand links differ from current raw/source/inventory replay")
        return rebuilt

    def trace_reference(self, invocation, *, max_steps=4096):
        from scar.analysis.call_operand_routes import query_operand_routes
        return query_operand_routes(self.frame_model, self.routing, invocation, max_steps=max_steps)


def link_call_operands(trace, project_root, inventory=None, *, frame_budget=CallEdgeBudget(),
                       operand_budget=CallOperandBudget(), route_budget=OperandRouteBudget(),
                       include_environments=False, composition=None, source_bindings=None,
                       coordinates=None, code_witnesses=None, progress=None,
                       source_port_consumer=None, source_port_budget=None,
                       python_source_port_consumer=None, python_source_port_budget=None,
                       python_source_body_composition=None, python_source_inventory_artifact=None):
    """Own one raw replay; optional consumer(model, check) gets a separate sidecar.

    ``check`` verifies a selected typed source-port record against this same
    fresh session. The historical CallOperandReport/wire is unchanged.
    """
    return _link_call_operands(trace, project_root, inventory, frame_budget=frame_budget,
        operand_budget=operand_budget, route_budget=route_budget, include_environments=include_environments,
        composition=composition, source_bindings=source_bindings, coordinates=coordinates,
        code_witnesses=code_witnesses, progress=progress,
        source_port_consumer=source_port_consumer, source_port_budget=source_port_budget,
        python_source_port_consumer=python_source_port_consumer, python_source_port_budget=python_source_port_budget,
        python_source_body_composition=python_source_body_composition,
        python_source_inventory_artifact=python_source_inventory_artifact)


def _link_call_operands_owned(owner, trace, project_root, **kwargs):
    from scar.analysis.current_source_evidence import _OwnedCurrent
    _require(type(owner) is _OwnedCurrent, "private operand owner was not created by current orchestration")
    return _link_call_operands(trace, project_root, _owner=owner, **kwargs)


def _link_call_operands(trace, project_root, inventory=None, *, frame_budget=CallEdgeBudget(),
                        operand_budget=CallOperandBudget(), route_budget=OperandRouteBudget(),
                        include_environments=False, composition=None, source_bindings=None,
                        coordinates=None, code_witnesses=None, progress=None, _owner=None,
                        source_port_consumer=None, source_port_budget=None,
                        python_source_port_consumer=None, python_source_port_budget=None,
                        python_source_body_composition=None, python_source_inventory_artifact=None):
    """Automatically reconstruct original call operands and typed core routes."""
    from scar.analysis.call_operand_reader import read_call_operands
    from scar.analysis.call_operand_routes import build_operand_routes

    from scar.analysis.source_body_access import SourceBodyAccess
    _require(progress is None or callable(progress), "progress must be callable or None")
    _require(source_port_consumer is None or callable(source_port_consumer),
             "source-port consumer must be callable or None")
    _require(source_port_consumer is not None or source_port_budget is None,
             "source-port budget requires its explicit consumer")
    if source_port_consumer is not None:
        from scar.ir.program.source_call_bindings import SourceCallPortBudget
        source_port_budget = SourceCallPortBudget() if source_port_budget is None else source_port_budget
        _require(type(source_port_budget) is SourceCallPortBudget, "source-port budget must be typed")
        source_port_budget.__post_init__()
    _require(python_source_port_consumer is None or callable(python_source_port_consumer),
             "Python source-port consumer must be callable or None")
    _require(python_source_port_consumer is not None or all(x is None for x in
        (python_source_port_budget, python_source_body_composition, python_source_inventory_artifact)),
        "Python source-port inputs require the explicit v2 consumer")
    if python_source_port_consumer is not None:
        from scar.ir.program.python_call_targets import PythonSourcePortBudget
        python_source_port_budget = PythonSourcePortBudget() if python_source_port_budget is None else python_source_port_budget
        _require(type(python_source_port_budget) is PythonSourcePortBudget, "Python source-port budget must be typed")
        python_source_port_budget.__post_init__()
        if python_source_body_composition is not None:
            from scar.analysis.program_composition import CompositionIndex
            _require(type(python_source_body_composition) is CompositionIndex
                     and python_source_body_composition.has_source_entry_publication,
                     "Python body input requires an ordinary qualified entry composition")
        if python_source_inventory_artifact is not None:
            from scar.ir.program.source_references import SourceArtifactLocator
            _require(type(python_source_inventory_artifact) is SourceArtifactLocator,
                     "Python inventory artifact must be its exact typed original locator")
            python_source_inventory_artifact.__post_init__()
    def notify(stage, **fields):
        if progress is not None:
            progress({"stage": stage, **fields})
    partitioned = composition is not None
    if partitioned:
        _require(inventory is None and all(value is not None for value in
                     (source_bindings, coordinates, code_witnesses)),
                 "partition path requires explicit composition/source bindings/coordinates/witnesses and no inventory")
    else:
        _require(inventory is not None and all(value is None for value in
                     (source_bindings, coordinates, code_witnesses)),
                 "legacy operand/core linking requires its original automatic inventory")
    _require(type(include_environments) is bool, "include_environments must be an exact bool")
    _require(type(route_budget) is OperandRouteBudget, "route budget must be typed")
    route_budget.__post_init__()
    root = Path(project_root).resolve()
    notify("OPERAND_READ_BEGIN")
    operands = (read_call_operands(trace, root, budget=operand_budget, frame_budget=frame_budget)
                if _owner is None else _owner.require(trace, root, frame_budget, operand_budget, coordinates))
    notify("OPERAND_READ_END", invocations=len(operands.entries), events=len(operands.events))
    access = None
    if partitioned:
        access = (_owner.checked_source_access(composition, source_bindings, coordinates, code_witnesses)
                  if _owner is not None else None)
        if access is None:
            access = SourceBodyAccess(composition, source_bindings, coordinates, code_witnesses)
            access.bind_scan(operands.frame_scan, operands.entries, operands.exits)
        _require(root == access.root, "partition source project root differs from current operand replay")
        inventory = access
        notify("SOURCE_BODY_ACCESS_BOUND", counts=access.scan_counts, selected_bodies=len(access.selected))
    model, sources = _link_call_model(
        trace, root, inventory, frame_budget,
        compilation_profile=CallCompilationProfile.RECORDED_FUTURE_FLAGS,
        frame_scan=operands.frame_scan, entries=operands.entries, exits=operands.exits,
        allow_v6=True, include_identity_routes=False,
    )
    notify("CALL_MODEL_LINKED", invocations=len(model.edges))
    routing = build_operand_routes(call_model=model, operand_model=operands, inventory=inventory,
                                   sources=sources, budget=route_budget)
    notify("OPERAND_ROUTES_BUILT", summary=routing.summary())
    environments = None
    if include_environments:
        from scar.analysis.callable_environment_import import import_callable_environments
        environments = import_callable_environments(trace, inventory=inventory, sources=sources,
            call_model=model, operand_model=operands,
            max_raw_bytes=operand_budget.max_raw_bytes,
            max_events=operand_budget.max_events,
            max_line_bytes=operand_budget.max_line_bytes,
            max_references=operand_budget.max_references)
        notify("CALLABLE_ENVIRONMENTS_BOUND", summary=environments["summary"])
    entry_parameters = []
    if access is not None:
        for edge in model.edges:
            if (edge.target.status is not CallLinkStatus.VERIFIED or edge.entry.suspended
                    or not edge.entry.parameters_complete or edge.entry.code not in sources.objects
                    or edge.entry.invocation.process_id in access.unbound_processes
                    or edge.target.definition not in sources.ports):
                continue
            signature = sources.signatures[edge.target.definition]
            if {parameter.name for parameter in edge.entry.parameters} != {parameter.name for parameter in signature.parameters}:
                continue
            for parameter in edge.entry.parameters:
                source, value = sources.parameter_port(edge.target.definition, parameter.name)
                if value is not None:
                    entry_parameters.append(ReferenceOccurrence(edge.entry.anchor, edge.entry.invocation,
                        edge.entry.invocation, ReferenceRole.PARAMETER, parameter.name, parameter.ref,
                        source_reference=source, core_value=value))
    if source_port_consumer is not None:
        from scar.analysis.source_call_bindings import build_source_call_port_bindings
        source_ports = build_source_call_port_bindings(call_model=model, operand_model=operands,
            inventory=inventory, sources=sources, budget=source_port_budget, consumer=source_port_consumer)
        notify("SOURCE_CALL_PORTS_BUILT", summary=source_ports.summary())
    if python_source_port_consumer is not None:
        from scar.analysis.python_call_targets import build_python_source_ports
        python_ports = build_python_source_ports(trace=operands, call_model=model, inventory=inventory,
            sources=sources, inventory_artifact=python_source_inventory_artifact,
            body_composition=python_source_body_composition, budget=python_source_port_budget,
            consumer=python_source_port_consumer)
        notify("PYTHON_SOURCE_CALL_PORTS_V2_BUILT", summary=python_ports.summary())
    return CallOperandReport(model, operands, routing, environments,
                             access.receipt() if access is not None else None, tuple(entry_parameters))


__all__ = ["CallOperandReport", "link_call_operands"]
