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
from scar.ir.program.call_edges import CallEdgeBudget, CallEdgeModel
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

    def summary(self):
        return {
            "frame": CallEdgeReport(self.frame_model).summary(),
            "operand_events": len(self.operands.events),
            "routing": self.routing.summary(),
            "scope": "conditional reference provenance; state, contents and effects remain separate",
            **{name: False for name in _AUTHORITY},
        }

    def to_dict(self):
        return {
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

    @staticmethod
    def check_replay_header(document, *, frame_ceiling=CallEdgeBudget(),
                            operand_ceiling=CallOperandBudget(), route_ceiling=OperandRouteBudget()):
        """Validate versions, authority and independent limits before input I/O."""
        _require(type(document) is dict and set(document) == _FIELDS,
                 "operand link report fields mismatch")
        _require(document["schema"] == "scar.call-operand-links"
                 and type(document["schema_version"]) is int and document["schema_version"] == 1,
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
        return frame, operand, route

    @classmethod
    def from_dict(cls, document, *, inventory, frame_ceiling=CallEdgeBudget(),
                  operand_ceiling=CallOperandBudget(), route_ceiling=OperandRouteBudget()):
        frame, operand, route = cls.check_replay_header(
            document, frame_ceiling=frame_ceiling, operand_ceiling=operand_ceiling,
            route_ceiling=route_ceiling,
        )
        rebuilt = link_call_operands(document["trace"], document["project_root"], inventory,
                                     frame_budget=frame, operand_budget=operand, route_budget=route)
        _require(_canonical(rebuilt.to_dict()) == _canonical(document),
                 "operand links differ from current raw/source/inventory replay")
        return rebuilt

    def trace_reference(self, invocation, *, max_steps=4096):
        from scar.analysis.call_operand_routes import query_operand_routes
        return query_operand_routes(self.frame_model, self.routing, invocation, max_steps=max_steps)


def link_call_operands(trace, project_root, inventory, *, frame_budget=CallEdgeBudget(),
                       operand_budget=CallOperandBudget(), route_budget=OperandRouteBudget(),
                       include_environments=False):
    """Automatically reconstruct original call operands and typed core routes."""
    from scar.analysis.call_operand_reader import read_call_operands
    from scar.analysis.call_operand_routes import build_operand_routes

    _require(inventory is not None, "operand/core linking requires an automatic frame inventory")
    _require(type(include_environments) is bool, "include_environments must be an exact bool")
    _require(type(route_budget) is OperandRouteBudget, "route budget must be typed")
    route_budget.__post_init__()
    root = Path(project_root).resolve()
    operands = read_call_operands(trace, root, budget=operand_budget, frame_budget=frame_budget)
    model, sources = _link_call_model(
        trace, root, inventory, frame_budget,
        compilation_profile=CallCompilationProfile.RECORDED_FUTURE_FLAGS,
        frame_scan=operands.frame_scan, entries=operands.entries, exits=operands.exits,
        allow_v6=True, include_identity_routes=False,
    )
    routing = build_operand_routes(call_model=model, operand_model=operands, inventory=inventory,
                                   sources=sources, budget=route_budget)
    environments = None
    if include_environments:
        from scar.analysis.callable_environment_import import import_callable_environments
        environments = import_callable_environments(trace, inventory=inventory, sources=sources,
            call_model=model, operand_model=operands,
            max_raw_bytes=operand_budget.max_raw_bytes,
            max_events=operand_budget.max_events,
            max_line_bytes=operand_budget.max_line_bytes,
            max_references=operand_budget.max_references)
    return CallOperandReport(model, operands, routing, environments)


__all__ = ["CallOperandReport", "link_call_operands"]
