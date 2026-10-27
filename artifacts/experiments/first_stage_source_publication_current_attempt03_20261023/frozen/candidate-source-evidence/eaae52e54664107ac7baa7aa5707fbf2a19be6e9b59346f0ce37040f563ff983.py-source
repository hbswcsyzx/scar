"""Check explicit Q associations without inventing consumers or runtime proof."""
from __future__ import annotations

from scar.ir.program.ids import ResourceRequirementID
from .common import EvidencePoint, Unresolved
from .coordinates import OccurrencePhase, OccurrencePoint
from .ids import OperationOccurrenceID, RegionActivationID
from .observations import (
    BoundEndpoint, ExternalEndpoint, OutputValue, RequiredEndpoint, RequiredOutput,
)
from .resources import (
    ExternalRealm, InstanceTarget, ProcessRealm, ProcessTarget, RunRealm, ThreadTarget,
)


def observation_errors(ctx) -> None:
    """Append structural issues and unresolved correspondence to ``ctx``.

    The caller has checked canonical coordinates, resource bindings and flow.
    A valid declaration remains conditional: an artifact locator does not parse
    a protocol, prove an output denotation, or establish endpoint visibility.
    """
    from .content_validation import check_interval, check_target

    static_requirements = {row.id: row for row in ctx.program.resource_requirements}

    def issue(code, path, message):
        ctx.issue("observation_" + code, path, message)

    def gap(code, path, message):
        ctx.gap("observation_" + code, path, message)

    def scope(point):
        if type(point) is EvidencePoint:
            return point.run, point.process, None
        if type(point) is OccurrencePoint and point.operation in ctx.occurrences:
            activation = ctx.activation_of(point.operation)
            process = ctx.activations[activation].process
            return ctx.processes[process].run, process, activation
        return None, None, None

    def same_run(left, right, path):
        a, b = scope(left)[0], scope(right)[0]
        if a is not None and b is not None and a != b:
            issue("run", path, "observation references different execution runs")

    def owner_scope(owner):
        if type(owner) is OperationOccurrenceID and owner in ctx.occurrences:
            activation = ctx.activation_of(owner)
        elif type(owner) is RegionActivationID and owner in ctx.activations:
            activation = owner
        else:
            return None, None, None
        process = ctx.activations[activation].process
        return ctx.processes[process].run, process, activation

    def check_target_scope(target, point, path):
        run, process, _ = scope(point)
        target_run = target_process = None
        if type(target) is InstanceTarget:
            resource = ctx.resources.get(target.instance)
            if resource is None:
                return
            if type(resource.realm) is RunRealm:
                target_run = resource.realm.run
            elif type(resource.realm) is ProcessRealm:
                target_process = resource.realm.process
                row = ctx.processes.get(target_process)
                target_run = None if row is None else row.run
            elif type(resource.realm) is ExternalRealm:
                gap("endpoint_realm_unverified", path, "external realm is not paired to this observation")
        elif type(target) is ProcessTarget:
            target_process = target.process
            row = ctx.processes.get(target.process)
            target_run = None if row is None else row.run
        elif type(target) is ThreadTarget:
            row = ctx.threads.get(target.thread)
            target_process = None if row is None else row.process
            row = None if row is None else ctx.processes.get(row.process)
            target_run = None if row is None else row.run
        if run is not None and target_run is not None and run != target_run:
            issue("endpoint_run", path, "endpoint belongs to another execution run")
        if process is not None and target_process is not None and process != target_process:
            issue("endpoint_process", path, "process-realm endpoint belongs to another process")
        if process is None and target_process is not None:
            gap("endpoint_process_unverified", path, "observation point has no process for endpoint pairing")

    for row in ctx.observation_requirements.values():
        path = f"observation_requirements[{row.id}]"
        graph = ctx.external_semantic(row.contract.artifact, path)
        contract = None
        if graph is not None:
            contract = graph.contracts.get(row.contract.contract)
            if contract is None:
                issue("contract", path, "contract is absent from the exact SemanticGraph")
        if type(row.target) is RequiredOutput:
            if graph is not None and row.target.slot not in graph.slots:
                issue("output_slot", path, "required output slot is absent from the exact SemanticGraph")
            if contract is not None and row.target.slot not in contract.required_outputs:
                issue("required_output", path, "slot is not an exact required output of this contract")
        else:
            if type(row.target.requirement) is ResourceRequirementID:
                if row.target.requirement not in static_requirements:
                    issue("endpoint_requirement", path, "endpoint references an unknown core resource requirement")
            else:
                ctx.check_point(row.target.requirement.point, path)
                gap("endpoint_requirement_unresolved", path, "external endpoint has no known core requirement")
            if contract is not None and not any(
                    facet.facet is row.target.facet and facet.required is True for facet in contract.facets):
                issue("required_facet", path, "endpoint facet is not explicitly required by this contract")
            ctx.gap("contract_endpoint_protocol_unverified", path,
                    "explicit endpoint/facet association is not parsed protocol or original-contract correspondence")
        gap("requirement_protocol_unverified", path, "protocol/source references do not establish requirement applicability")

    for row in ctx.observation_roots.values():
        path = f"observation_roots[{row.id}]"
        requirement = ctx.observation_requirements.get(row.requirement)
        if requirement is None:
            issue("requirement", path, "root references an unknown observation requirement")
        check_interval(ctx, row.interval, path)
        anchor = row.anchor if type(row.anchor) is OccurrencePoint else row.anchor.point
        ctx.check_support(row.support, anchor, path)
        for point in (row.interval.start, row.interval.end):
            same_run(anchor, point, path)
        if type(row.anchor) is Unresolved:
            if row.support:
                issue("anchor_support", path, "nonempty current-state support requires an exact canonical anchor")
            gap("anchor_unresolved", path, "observation has no exact canonical current-state anchor")
        elif ctx.point_precedes(row.anchor, row.interval.end) is False:
            issue("anchor_after_interval", path, "state anchor is known to occur after the observation interval")

        actual = row.actual
        if type(actual) is Unresolved:
            ctx.check_point(actual.point, path)
            same_run(actual.point, anchor, path)
            gap("actual_unresolved", path, "actual output or endpoint observation is unresolved")
        elif type(actual) is OutputValue:
            if requirement is not None and type(requirement.target) is not RequiredOutput:
                issue("actual_kind", path, "an output value cannot fulfill an endpoint requirement")
            value = ctx.values.get(actual.value)
            if value is None:
                issue("output_value", path, "observed output value occurrence is absent")
            else:
                run, _, activation = owner_scope(ctx.value_activation(actual.value))
                point_run, _, point_activation = scope(anchor)
                if run is not None and point_run is not None and run != point_run:
                    issue("output_run", path, "output value belongs to another execution run")
                if point_activation is not None and activation != point_activation:
                    gap("output_activation_unverified", path, "cross-activation output transfer/observation is not established")
                if type(value.origin) is OperationOccurrenceID:
                    produced = OccurrencePoint(value.origin, OccurrencePhase.AFTER)
                    if ctx.point_precedes(produced, row.interval.start) is False:
                        issue("output_before_definition", path, "observation starts before the actual output definition")
            gap("output_correspondence_unverified", path, "value occurrence is not proof of exact required-output slot denotation")
        elif type(actual) is BoundEndpoint:
            if requirement is not None and type(requirement.target) is not RequiredEndpoint:
                issue("actual_kind", path, "an endpoint binding cannot fulfill an output requirement")
            binding = ctx.requirements.get(actual.binding)
            if binding is None:
                issue("binding", path, "observed endpoint binding is absent")
            else:
                if (requirement is not None and type(requirement.target) is RequiredEndpoint
                        and type(requirement.target.requirement) is ResourceRequirementID
                        and binding.requirement != requirement.target.requirement):
                    issue("binding_requirement", path, "binding does not fulfill the exact core endpoint requirement")
                run, _, activation = owner_scope(binding.owner)
                point_run, _, point_activation = scope(anchor)
                if run is not None and point_run is not None and run != point_run:
                    issue("binding_run", path, "endpoint binding owner belongs to another execution run")
                if point_activation is not None and activation != point_activation:
                    gap("binding_activation_unverified", path, "cross-activation endpoint transfer/observation is not established")
                if type(binding.owner) is OperationOccurrenceID:
                    bound = OccurrencePoint(binding.owner, OccurrencePhase.BEFORE)
                    if ctx.point_precedes(bound, row.interval.start) is False:
                        issue("binding_before_owner", path, "observation starts before its binding owner occurrence")
                check_target(ctx, binding.target, path)
                for point in (anchor, row.interval.start, row.interval.end):
                    check_target_scope(binding.target, point, path)
        elif type(actual) is ExternalEndpoint:
            if requirement is not None:
                if type(requirement.target) is not RequiredEndpoint:
                    issue("actual_kind", path, "an external endpoint cannot fulfill an output requirement")
                elif type(requirement.target.requirement) is ResourceRequirementID:
                    issue("external_binding", path, "a known core endpoint requires its actual requirement binding")
            check_target(ctx, actual.target, path)
            for point in (anchor, row.interval.start, row.interval.end):
                check_target_scope(actual.target, point, path)
            gap("external_endpoint_unverified", path, "external endpoint observation lacks parsed protocol correspondence")
        gap("source_protocol_unverified", path,
            "declared observation/interval/current-state references do not prove source, native pairing, visibility or readiness")


__all__ = ["observation_errors"]
