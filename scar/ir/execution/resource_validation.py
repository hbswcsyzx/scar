"""Validate resource links against canonical program and execution occurrences.

This module checks typed declarations and their exact owners/current-state
references.  It does not establish physical identity, rights, availability,
capacity, readiness, or source/runtime correspondence.
"""
from __future__ import annotations

from scar.ir.program.model import DataValue, ProtocolValue, ReferenceValue
from scar.ir.program.ids import OperationID, RegionID
from scar.ir.program.providers import ProviderFactReference
from scar.ir.program.resources import (
    CreatedResource, ExternalResource, RequirementRelation, ResourceKind,
    ResourceRole,
)
from scar.ir.v2.common import Completeness
from .common import EvidencePoint, Unresolved
from .coordinates import (
    OccurrencePhase, OccurrencePoint, OperationOccurrenceID, RegionActivationID,
)
from .resources import (
    ActivationHolder, AllocationTarget, CapacityAt, CreatedAt, EndedAt,
    ExplicitHandle, ExternalRealm, HandleHolder, ImplicitBinding, ImportedAt,
    InstanceTarget, NativeHandle, ObjectHandle, ObjectHolder, ProcessRealm,
    ProcessTarget, ProtocolCondition, RelationAt, ResourceAccessBinding,
    ResourceInstance, ResourceRealization, RequirementBinding, RightsClaim,
    RunRealm, TargetHolder, ThreadTarget, UnresolvedHandle, ProviderHandle,
    ProviderAccessPurpose,
)


def resource_errors(ctx) -> None:
    """Append resource declaration errors and evidence gaps to ``ctx``.

    All joins are through existing ProgramGraph IDs and execution occurrence
    IDs.  An absent external graph, unsupported cross-activation pairing, or
    unknown order is recorded as a gap rather than treated as success.
    """
    program = ctx.program
    definitions = {row.id: row for row in program.resources}
    static_requirements = {row.id: row for row in program.resource_requirements}
    static_uses = {}
    for index, row in enumerate(program.resource_uses):
        static_uses.setdefault((row.operation, row.requirement), []).append((index, row))
    static_requirements_by_operation = {}
    for (operation, requirement), rows in static_uses.items():
        static_requirements_by_operation.setdefault(operation, []).extend(
            requirement for _ in rows
        )
    static_locations = tuple(program.resource_locations)
    regions = ctx.regions

    def issue(code, path, message):
        ctx.issue("resource_" + code, path, message)

    def gap(code, path, message):
        ctx.gap("resource_" + code, path, message)

    missing_selector = object()
    selector_results = {}

    def selector_value(selector, path):
        resolver = ctx.provider_selector_resolver
        if resolver is None:
            gap("provider_selector_unresolved", path, "selector bytes require an explicitly bound provider reader")
            return missing_selector
        if selector not in selector_results:
            try:
                resolution = resolver(selector)
                if type(resolution) is not dict or "value" not in resolution:
                    raise ValueError("provider resolver did not return its selected value/receipt")
                selector_results[selector] = resolution["value"]
            except (ValueError, TypeError, KeyError, IndexError, OSError) as error:
                issue("provider_selector", path, str(error))
                return missing_selector
        return selector_results[selector]

    def path_for(table, key):
        return f"{table}[{key}]"

    def activation_of_occurrence(occurrence, path):
        if occurrence not in ctx.occurrences:
            issue("occurrence", path, "unknown operation occurrence")
            return None
        try:
            activation = ctx.activation_of(occurrence)
        except (KeyError, TypeError, AttributeError):
            issue("occurrence_activation", path, "operation occurrence has no valid activation")
            return None
        if activation not in ctx.activations:
            issue("occurrence_activation", path, "operation occurrence has an unknown activation")
            return None
        return activation

    def point_scope(point, path):
        """Return (process, run), validating the point through the shared gate."""
        try:
            ctx.check_point(point, path)
        except (KeyError, TypeError, AttributeError, IndexError):
            issue("point", path, "execution point could not be resolved")
            return None, None
        if type(point) is EvidencePoint:
            process = point.process
            if process is not None and process not in ctx.processes:
                return None, None
            return process, point.run
        if type(point) is not OccurrencePoint or point.operation not in ctx.occurrences:
            return None, None
        activation = activation_of_occurrence(point.operation, path)
        if activation is None:
            return None, None
        process = ctx.activations[activation].process
        process_row = ctx.processes.get(process)
        return process, None if process_row is None else process_row.run

    def check_realm(realm, path, point=None):
        """Validate realm foreign keys and, when known, point membership."""
        realm_run = realm_process = None
        if type(realm) is RunRealm:
            if realm.run not in ctx.runs:
                issue("realm_run", path, "identity realm refers to an unknown run")
            else:
                realm_run = realm.run
        elif type(realm) is ProcessRealm:
            process = ctx.processes.get(realm.process)
            if process is None:
                issue("realm_process", path, "identity realm refers to an unknown process incarnation")
            else:
                realm_process, realm_run = realm.process, process.run
        elif type(realm) is ExternalRealm:
            # ProviderFactReference is a scoped locator.  The outer execution
            # validator scans it; it is not a registry key or runtime proof.
            return
        else:
            issue("realm", path, "identity realm has an unknown variant")
            return
        if point is None:
            return
        process, run = point_scope(point, path)
        if run is not None and realm_run is not None and run != realm_run:
            issue("realm_scope", path, "resource realm belongs to another execution run")
        if process is not None and realm_process is not None and process != realm_process:
            issue("realm_scope", path, "resource realm belongs to another process incarnation")
        if type(point) is EvidencePoint and point.process is None and realm_process is not None:
            gap("realm_scope_unknown", path, "evidence point has no process for process-realm comparison")

    def target_kind_role(target, path):
        if type(target) is InstanceTarget:
            resource = ctx.resources.get(target.instance)
            if resource is None:
                issue("target_instance", path, "target refers to an unknown resource instance")
                return None
            return resource.kind, resource.role
        if type(target) is AllocationTarget:
            graph = ctx.external_values(target.artifact, path)
            if graph is not None and target.allocation not in graph.allocations:
                issue("target_allocation", path, "allocation target is absent from its exact ValueGraph")
            # An allocation is storage, never a memory pool.  CPU/GPU/device
            # placement and physical denotation are deliberately not inferred.
            return ResourceKind.STORAGE, ResourceRole.STORAGE_ENDPOINT
        if type(target) is ProcessTarget:
            if target.process not in ctx.processes:
                issue("target_process", path, "target refers to an unknown process incarnation")
            return ResourceKind.PROCESS, ResourceRole.EXECUTOR
        if type(target) is ThreadTarget:
            if target.thread not in ctx.threads:
                issue("target_thread", path, "target refers to an unknown host-thread incarnation")
            return ResourceKind.THREAD, ResourceRole.EXECUTOR
        issue("target", path, "resource target has an unknown variant")
        return None

    def check_target_matches(target, kind, role, path, subject):
        actual = target_kind_role(target, path)
        if actual is None:
            return
        if type(target) is AllocationTarget:
            if role is ResourceRole.MEMORY_POOL:
                issue("allocation_pool", path, "an allocation cannot be used as a MEMORY_POOL")
            if kind not in (ResourceKind.MEMORY, ResourceKind.STORAGE) or role not in (
                    ResourceRole.STORAGE_ENDPOINT, ResourceRole.OPAQUE_RESOURCE):
                issue("target_role", path, f"{subject} allocation target is incompatible with its kind/role")
        elif type(target) in (ProcessTarget, ThreadTarget):
            if actual[0] is not kind or role not in (ResourceRole.EXECUTOR, ResourceRole.OPAQUE_RESOURCE):
                issue("target_role", path, f"{subject} process/thread target is incompatible with its kind/role")
        elif actual != (kind, role):
            issue("target_role", path, f"{subject} target kind/role does not match its declaration")

    def check_target_realm(target, point, path):
        if type(target) is InstanceTarget:
            resource = ctx.resources.get(target.instance)
            if resource is not None:
                if type(resource.realm) is ExternalRealm:
                    gap("target_realm_scope_unknown", path,
                        "external resource realm is not paired to this execution point")
                else:
                    check_realm(resource.realm, path, point)
        elif type(target) is ProcessTarget:
            if target.process in ctx.processes:
                check_realm(ProcessRealm(target.process), path, point)
        elif type(target) is ThreadTarget:
            thread = ctx.threads.get(target.thread)
            if thread is not None:
                check_realm(ProcessRealm(thread.process), path, point)

    def region_is_ancestor(ancestor, child):
        seen = set()
        while child in regions and child not in seen:
            if child == ancestor:
                return True
            seen.add(child)
            child = regions[child].parent
        return False

    def operation_region(occurrence, path):
        occurrence_row = ctx.occurrences.get(occurrence)
        if occurrence_row is None:
            issue("operation_region", path, "unknown operation occurrence")
            return None
        block = ctx.operation_blocks.get(occurrence_row.operation)
        if block is None:
            issue("operation_region", path, "canonical operation has no owning block")
            return None
        try:
            return ctx.block_regions[block.id]
        except KeyError:
            issue("operation_region", path, "canonical operation block has no owning region")
            return None

    def owner_matches_requirement(binding, requirement, path):
        owner = binding.owner
        if type(requirement.owner) is OperationID:
            if type(owner) is not OperationOccurrenceID:
                issue("binding_owner", path, "operation-owned requirement needs an operation occurrence owner")
                return False
            occurrence = ctx.occurrences.get(owner)
            if occurrence is None or occurrence.operation != requirement.owner:
                issue("binding_owner", path, "binding owner is not the exact static operation occurrence")
                return False
            return True
        if type(owner) is not RegionActivationID:
            issue("binding_owner", path, "region-owned requirement needs a region activation owner")
            return False
        activation = ctx.activations.get(owner)
        if activation is None or activation.region != requirement.owner:
            issue("binding_owner", path, "binding owner is not an activation of the exact owning region")
            return False
        return True

    def definition_target_relation(definition_id, target, activation, path):
        if definition_id not in definitions:
            issue("static_definition", path, "resource use references an unknown static definition")
            return
        rows = [row for row in ctx.realizations.values()
                if row.definition == definition_id and realization_activation(row, path) == activation]
        if not rows:
            gap("realization_missing", path, "no realization for this definition in the exact activation")
            return
        if not any(row.target == target for row in rows):
            issue("realization_target", path, "binding target contradicts the realization in this activation")

    def realization_activation(row, path):
        if type(row.site) is RegionActivationID:
            return row.site if row.site in ctx.activations else None
        if type(row.site) is OperationOccurrenceID:
            return activation_of_occurrence(row.site, path)
        return None

    def _target_for_instance(identity):
        return InstanceTarget(identity)

    def dynamic_value_type(value_occurrence, path):
        row = ctx.values.get(value_occurrence)
        if row is None:
            issue("value_occurrence", path, "unknown value occurrence")
            return None, None
        return row, ctx.core_values.get(row.value)

    def value_available_at(value_occurrence, point, path):
        row = ctx.values.get(value_occurrence)
        if row is None:
            issue("handle_value", path, "handle endpoint references an unknown value occurrence")
            return
        activation = None
        if type(point) is OccurrencePoint:
            activation = activation_of_occurrence(point.operation, path)
            if activation is not None and ctx.value_activation(value_occurrence) != activation:
                issue("handle_value_scope", path, "handle endpoint belongs to another region activation")
        origin = row.origin
        if type(origin) is OperationOccurrenceID and type(point) is OccurrencePoint:
            origin_point = OccurrencePoint(origin, OccurrencePhase.AFTER)
            try:
                ordered = ctx.point_precedes(origin_point, point)
            except (KeyError, TypeError, AttributeError, IndexError):
                ordered = None
            if ordered is False:
                issue("handle_value_order", path, "handle value is produced after its binding point")
            elif ordered is None:
                gap("handle_value_order", path, "handle value production order is not established")
        elif type(origin) is not RegionActivationID:
            # A BlockVisit formal is activation-local, but this context does
            # not establish its exact temporal ingress at arbitrary points.
            if type(point) is OccurrencePoint:
                gap("handle_value_order", path, "formal value availability at the binding point is not established")
        if type(point) is EvidencePoint:
            gap("handle_value_order", path, "evidence point does not order the handle value occurrence")

    def check_endpoint(endpoint, binding, path):
        if type(endpoint) is ObjectHandle:
            row, value = dynamic_value_type(endpoint.value, path)
            if value is not None and type(value) is not ReferenceValue:
                issue("object_handle_value", path, "ObjectHandle must reference a canonical ReferenceValue")
            graph = ctx.external_values(endpoint.artifact, path)
            if graph is not None and not graph.has_object(endpoint.object):
                issue("object_handle_identity", path, "object ID is absent from the exact external ValueGraph")
            value_available_at(endpoint.value, binding.start, path)
        elif type(endpoint) is NativeHandle:
            row, value = dynamic_value_type(endpoint.value, path)
            if value is not None and type(value) not in (DataValue, ProtocolValue):
                issue("native_handle_value", path, "NativeHandle must reference a DataValue or ProtocolValue")
            if type(endpoint.namespace.realm) is ExternalRealm:
                gap("handle_namespace_scope_unknown", path,
                    "external handle namespace is not paired to this execution point")
            else:
                check_realm(endpoint.namespace.realm, path, binding.start)
            value_available_at(endpoint.value, binding.start, path)
        elif type(endpoint) is ProviderHandle:
            check_realm(endpoint.namespace.realm, path, binding.start)
            if type(endpoint.container) is InstanceTarget:
                table = ctx.resources.get(endpoint.container.instance)
                if table is None or table.kind is not ResourceKind.OTHER or table.role is not ResourceRole.HANDLE_TABLE:
                    issue("provider_handle_table", path, "provider handle needs its exact HANDLE_TABLE resource")
                else:
                    check_target_realm(endpoint.container, binding.start, path)
            else:
                ctx.check_point(endpoint.container.point, path)
                gap("provider_handle_table_unresolved", path, endpoint.container.reason)
            # A generic provider handle may use structured or non-FD tokens.
            # Token-domain constraints belong to its concrete provider adapter.
            selector_value(endpoint.selector, path)
            gap("provider_handle_effect_alignment", path, "provider selector is not a canonical ValueOccurrence/state/effect route")
        elif type(endpoint) is UnresolvedHandle:
            if endpoint.value is not None and endpoint.value not in ctx.values:
                issue("unresolved_handle_value", path, "unresolved handle names an unknown value occurrence")
            elif endpoint.value is not None:
                value_available_at(endpoint.value, binding.start, path)
            ctx.check_point(endpoint.gap.point, path)
            gap("handle_unresolved", path, endpoint.gap.reason)
        else:
            issue("handle_endpoint", path, "handle binding has an unknown endpoint variant")

    def check_point_support(support, point, path, *, target=None, definition_ids=()):
        try:
            ctx.check_support(support, point, path)
        except (KeyError, TypeError, AttributeError, IndexError):
            issue("state_support", path, "state support could not be checked")
        expected_definitions = set(definition_ids)
        if target is not None and type(target) is InstanceTarget:
            point_activation = None
            if type(point) is OccurrencePoint:
                point_activation = activation_of_occurrence(point.operation, path)
            target_realizations = [row for row in ctx.realizations.values()
                                   if row.target == target
                                   and (point_activation is None
                                        or realization_activation(row, path) == point_activation)]
            if target_realizations:
                expected_definitions.update(row.definition for row in target_realizations)
            elif not expected_definitions:
                if point_activation is None:
                    gap("resource_state_mapping_unknown", path,
                        "resource-state definition is not paired to this external point")
                else:
                    gap("resource_state_mapping_unknown", path,
                        "resource target has no realization in this activation")
        relevant_locations = {row.location for row in static_locations
                              if row.resource in expected_definitions}
        if not relevant_locations:
            return
        current = ctx.current(point)
        if current is None:
            gap("current_state_unknown", path, "resource state cannot be resolved at this point")
            return
        supported = set(support)
        for location in relevant_locations:
            exact = current.get(location)
            if exact is None:
                gap("current_state_unknown", path, f"current state for {location} is not established")
            elif exact not in supported:
                issue("current_state_support", path, f"support omits the exact current resource state for {location}")

    # Validate resource instances and their identity realms/origins.
    external_realm_namespaces = {}
    for identity, row in ctx.resources.items():
        path = path_for("resources", identity)
        if row.id != identity:
            issue("table_key", path, "resource table key differs from row identity")
        check_realm(row.realm, path)
        if type(row.realm) is ExternalRealm:
            previous = external_realm_namespaces.setdefault(row.realm.id, row.realm.namespace)
            if previous != row.realm.namespace:
                issue("external_realm", path, "one external realm ID has conflicting namespace facts")
        if type(row.origin) is CreatedAt:
            activation = activation_of_occurrence(row.origin.operation, path)
            if activation is not None:
                check_realm(row.realm, path, OccurrencePoint(row.origin.operation, OccurrencePhase.AFTER))
            occurrence = ctx.occurrences.get(row.origin.operation)
            if occurrence is not None:
                creators = [item for item in definitions.values()
                            if type(item.origin) is CreatedResource
                            and item.origin.operation == occurrence.operation]
                if not creators:
                    issue("created_origin", path, "CreatedAt operation has no matching canonical CreatedResource")
                else:
                    at_site = [real for real in ctx.realizations.values()
                               if real.definition in {item.id for item in creators}
                               and real.site == row.origin.operation]
                    if not at_site:
                        gap("created_realization", path,
                            "no realization at this creator occurrence links the static definition to this instance")
                    elif not any(real.target == _target_for_instance(identity) for real in at_site):
                        issue("created_realization", path,
                              "explicit creation occurrence is realized to a different resource target")
        elif type(row.origin) is ImportedAt:
            check_realm(row.realm, path, row.origin.point)
        else:
            ctx.check_point(row.origin.point, path)
            gap("origin_unresolved", path, row.origin.reason)

    # Validate realization sites and target type/role against static definitions.
    realization_sites = set()
    for identity, row in ctx.realizations.items():
        path = path_for("realizations", identity)
        if row.id != identity:
            issue("table_key", path, "realization table key differs from row identity")
        definition = definitions.get(row.definition)
        if definition is None:
            issue("realization_definition", path, "realization references an unknown resource definition")
            continue
        site_key = row.definition, row.site
        if site_key in realization_sites:
            issue("realization_duplicate", path, "one definition/site has conflicting realization rows")
        realization_sites.add(site_key)
        if type(definition.origin) is CreatedResource:
            if type(row.site) is not OperationOccurrenceID:
                issue("realization_site", path, "CreatedResource realization needs an operation occurrence site")
            else:
                occurrence = ctx.occurrences.get(row.site)
                if occurrence is None or occurrence.operation != definition.origin.operation:
                    issue("realization_site", path, "realization site is not the exact creator operation occurrence")
        else:
            if type(row.site) is not RegionActivationID:
                issue("realization_site", path, "ExternalResource realization needs a region activation site")
            else:
                activation = ctx.activations.get(row.site)
                if activation is None or activation.region != definition.origin.region:
                    issue("realization_site", path, "realization is not at an activation of the external resource region")
        check_target_matches(row.target, definition.kind, definition.role, path, "realization")
        if type(row.target) is InstanceTarget:
            resource = ctx.resources.get(row.target.instance)
            if resource is not None:
                if (resource.kind, resource.role) != (definition.kind, definition.role):
                    issue("realization_instance", path, "realized instance kind/role differs from its definition")
                site_activation = realization_activation(row, path)
                if type(resource.origin) is CreatedAt and row.site != resource.origin.operation:
                    gap("realization_origin", path,
                        "this realization binds an instance created at another occurrence; acquisition identity is not established")
                elif type(resource.origin) is Unresolved:
                    gap("realization_origin", path, "instance origin is unresolved; realization identity is not established")
                elif type(resource.origin) is ImportedAt and site_activation is not None:
                    point_process, point_run = point_scope(resource.origin.point, path)
                    site_process = ctx.activations[site_activation].process
                    site_run = ctx.processes[site_process].run
                    if point_process is not None and point_process != site_process:
                        gap("realization_origin_scope", path, "imported instance and realization cross process activations")
                    elif point_run is not None and point_run != site_run:
                        issue("realization_origin_scope", path, "imported instance belongs to another run")

    # Validate requirement bindings and their exact owner category.
    binding_owner_keys = set()
    for identity, row in ctx.requirements.items():
        path = path_for("requirements", identity)
        if row.id != identity:
            issue("table_key", path, "requirement table key differs from row identity")
        requirement = static_requirements.get(row.requirement)
        if requirement is None:
            issue("binding_requirement", path, "binding references an unknown static requirement")
            continue
        owner_matches_requirement(row, requirement, path)
        key = row.requirement, row.owner
        if key in binding_owner_keys:
            issue("binding_duplicate", path, "one exact requirement owner has conflicting bindings")
        binding_owner_keys.add(key)
        check_target_matches(row.target, requirement.kind, requirement.role, path, "requirement")
        owner_point = None
        if type(row.owner) is OperationOccurrenceID and row.owner in ctx.occurrences:
            owner_point = OccurrencePoint(row.owner, OccurrencePhase.BEFORE)
        elif type(row.owner) is RegionActivationID:
            owner_activation = ctx.activations.get(row.owner)
            if owner_activation is not None:
                owner_point = owner_activation.entry
        if owner_point is not None:
            check_target_realm(row.target, owner_point, path)

    # Validate handle endpoints, state support, holder references and lifetimes.
    native_lifetimes = {}
    for identity, row in ctx.handles.items():
        if type(row.handle) not in (NativeHandle, ProviderHandle):
            continue
        endpoint = (row.target, row.handle.namespace, row.handle.container if type(row.handle) is ProviderHandle else None)
        previous = native_lifetimes.setdefault(row.handle.lifetime, endpoint)
        if previous != endpoint:
            issue("native_lifetime_target", path_for("handles", identity),
                  "one native handle lifetime cannot change target or namespace")

    for identity, access in ctx.provider_accesses.items():
        path = path_for("provider_accesses", identity)
        if access.id != identity:
            issue("table_key", path, "provider access table key differs from its row identity")
        ctx.check_point(access.point, path)
        kind_role = target_kind_role(access.target, path)
        check_target_realm(access.target, access.point, path)
        if access.purpose is ProviderAccessPurpose.EXECUTOR and kind_role is not None:
            if kind_role[1] is not ResourceRole.EXECUTOR:
                issue("provider_executor_role", path, "executor association must target an actual EXECUTOR")
        if type(access.handle) is ExplicitHandle:
            handle = ctx.handles.get(access.handle.binding)
            if handle is None or handle.target != access.target:
                issue("provider_access_handle", path, "explicit provider handle is absent or targets another resource")
        elif type(access.handle) is Unresolved:
            ctx.check_point(access.handle.point, path)
            gap("provider_access_handle_unresolved", path, access.handle.reason)
        selector_value(access.selector, path)
        gap("provider_access_state_alignment", path, "provider resource selection does not establish canonical resource state/effects")
    for identity, row in ctx.handles.items():
        path = path_for("handles", identity)
        if row.id != identity:
            issue("table_key", path, "handle table key differs from row identity")
        check_target_realm(row.target, row.start, path)
        ctx.check_point(row.start, path)
        check_point_support(row.support, row.start, path, target=row.target)
        check_endpoint(row.handle, row, path)
        if type(row.end) is EndedAt:
            ctx.check_point(row.end.point, path)
            end_order = ctx.point_precedes(row.start, row.end.point)
            if end_order is False:
                issue("handle_interval", path, "handle end precedes its start")
            elif end_order is None:
                gap("handle_interval", path, "handle start/end order is not established")
        else:
            ctx.check_point(row.end.point, path)
            gap("handle_end_unknown", path, row.end.reason)
        if type(row.rights) is RightsClaim:
            check_point_support(row.rights.support, row.start, path, target=row.target)
            if row.rights.completeness is not Completeness.COMPLETE:
                gap("rights_incomplete", path, "rights claim does not declare complete coverage")
        else:
            ctx.check_point(row.rights.point, path)
            gap("rights_unresolved", path, row.rights.reason)
        if type(row.ownership) is tuple:
            for claim_index, claim in enumerate(row.ownership):
                claim_path = f"{path}.ownership[{claim_index}]"
                check_point_support(claim.support, row.start, claim_path, target=row.target)
                if claim.authority.value == "UNKNOWN" or claim.sharing.value == "UNKNOWN":
                    gap("ownership_unknown", claim_path, "ownership authority or sharing is unknown")
                holder = claim.holder
                if type(holder) is ObjectHolder:
                    graph = ctx.external_values(holder.artifact, claim_path)
                    if graph is not None and not graph.has_object(holder.object):
                        issue("ownership_holder", claim_path, "object holder is absent from its ValueGraph")
                elif type(holder) is HandleHolder:
                    if holder.lifetime not in native_lifetimes:
                        issue("ownership_holder", claim_path, "native handle lifetime has no declared endpoint")
                elif type(holder) is ActivationHolder:
                    if holder.activation not in ctx.activations:
                        issue("ownership_holder", claim_path, "ownership holder activation is unknown")
                elif type(holder) is TargetHolder:
                    target_kind_role(holder.target, claim_path)
        else:
            ctx.check_point(row.ownership.point, path)
            gap("ownership_unresolved", path, row.ownership.reason)

    # Validate each dynamic access against the canonical ResourceUse and the
    # one exact RequirementBinding, preserving repeated uses by UseID.
    seen_accesses = set()
    for identity, access in ctx.accesses.items():
        path = path_for("accesses", identity)
        if access.id != identity:
            issue("table_key", path, "access table key differs from row identity")
        if access.operation not in ctx.occurrences:
            issue("access_operation", path, "access references an unknown operation occurrence")
            continue
        occurrence = ctx.occurrences[access.operation]
        binding = ctx.requirements.get(access.requirement)
        if binding is None:
            issue("access_binding", path, "access references an unknown requirement binding")
            continue
        requirement = static_requirements.get(binding.requirement)
        if requirement is None:
            issue("access_requirement", path, "requirement binding has no static requirement")
            continue
        key = access.operation, binding.requirement
        if key in seen_accesses:
            issue("access_duplicate", path, "operation occurrence has duplicate access bindings for one requirement")
        seen_accesses.add(key)
        use_rows = static_uses.get((occurrence.operation, binding.requirement), ())
        if not use_rows:
            issue("access_static_use", path, "operation occurrence has no matching canonical ResourceUse")
            static_use = None
        elif len(use_rows) != 1:
            issue("access_static_use", path, "canonical ResourceUse mapping is ambiguous")
            static_use = None
        else:
            static_use = use_rows[0][1]
        operation_act = activation_of_occurrence(access.operation, path)
        owner_matches_requirement(binding, requirement, path)
        if type(requirement.owner) is OperationID:
            if binding.owner != access.operation:
                issue("access_owner", path, "operation requirement access does not use its exact owner occurrence")
        elif type(binding.owner) is RegionActivationID and operation_act is not None:
            if binding.owner != operation_act:
                owner_activation = ctx.activations.get(binding.owner)
                child_region = operation_region(access.operation, path)
                if (owner_activation is not None and child_region is not None
                        and owner_activation.region != child_region
                        and region_is_ancestor(owner_activation.region, child_region)):
                    gap("access_activation_pairing", path,
                        "nested resource use has no explicit pairing to its ancestor requirement activation")
                else:
                    issue("access_owner", path,
                          "region requirement binding is not the exact activation or a declared lexical ancestor")
        if static_use is not None and static_use.definition is not None and operation_act is not None:
            definition_target_relation(static_use.definition, binding.target, operation_act, path)
        check_target_matches(binding.target, requirement.kind, requirement.role, path, "access")
        access_point = OccurrencePoint(access.operation, OccurrencePhase.BEFORE)
        check_target_realm(binding.target, access_point, path)
        check_point_support(access.support, access_point, path, target=binding.target,
                            definition_ids=(() if static_use is None or static_use.definition is None
                                            else (static_use.definition,)))
        if static_use is not None and static_use.handle is not None:
            if type(access.handle) is not ExplicitHandle:
                issue("access_handle", path, "declared canonical handle Use cannot be bypassed")
            else:
                handle_binding = ctx.handles.get(access.handle.binding)
                if handle_binding is None:
                    issue("access_handle", path, "explicit handle references an unknown HandleBinding")
                else:
                    if handle_binding.target != binding.target:
                        issue("access_handle_target", path, "handle and requirement bind different resource targets")
                    use_occurrence = ctx.uses.get((access.operation, static_use.handle))
                    if use_occurrence is None:
                        gap("access_handle_use", path, "exact dynamic handle Use occurrence is missing")
                    elif isinstance(use_occurrence.value, Unresolved):
                        gap("access_handle_use", path, use_occurrence.value.reason)
                    elif (type(handle_binding.handle) in (ObjectHandle, NativeHandle)
                          and use_occurrence.value != handle_binding.handle.value):
                        issue("access_handle_use", path, "HandleBinding endpoint differs from the exact dynamic handle Use")
                    elif type(handle_binding.handle) is UnresolvedHandle:
                        if handle_binding.handle.value is None:
                            gap("access_handle_use", path,
                                "unresolved handle has no endpoint value to join to the exact dynamic handle Use")
                        elif use_occurrence.value != handle_binding.handle.value:
                            issue("access_handle_use", path,
                                  "known unresolved-handle endpoint differs from the exact dynamic handle Use")
        elif static_use is not None:
            if type(access.handle) is ExplicitHandle:
                issue("access_handle", path, "explicit dynamic handle lacks a canonical ResourceUse handle port")
            elif type(access.handle) is ImplicitBinding:
                check_point_support(access.handle.support, access_point, path, target=binding.target,
                                    definition_ids=(() if static_use.definition is None
                                                    else (static_use.definition,)))
            else:
                ctx.check_point(access.handle.point, path)
                gap("access_handle_unresolved", path, access.handle.reason)

        if type(access.handle) is ExplicitHandle and (static_use is None or static_use.handle is None):
            # Also handle the malformed/missing-static-use path without
            # accidentally accepting an explicit endpoint by table order.
            issue("access_handle", path, "ExplicitHandle is not tied to a canonical handle Use")
        elif type(access.handle) is ImplicitBinding and static_use is not None and static_use.handle is not None:
            issue("access_handle", path, "ImplicitBinding cannot bypass a declared handle Use")

        if type(access.handle) is ExplicitHandle:
            handle_binding = ctx.handles.get(access.handle.binding)
            if handle_binding is not None:
                start_before_access = ctx.point_precedes(handle_binding.start, access_point)
                if start_before_access is False:
                    issue("handle_not_started", path, "handle binding starts after this resource access")
                elif start_before_access is None:
                    gap("handle_start_order", path, "handle start is not ordered before this access")
                if type(handle_binding.end) is EndedAt:
                    access_before_end = ctx.point_precedes(access_point, handle_binding.end.point)
                    if access_point == handle_binding.end.point or access_before_end is False:
                        issue("handle_ended", path, "resource access is at or after the handle end point")
                    elif access_before_end is None:
                        gap("handle_end_order", path, "handle end is not ordered after this access")
                else:
                    gap("handle_live_unknown", path, "unknown handle end does not establish that it is live here")

        _validate_constraints(
            ctx, access, binding, requirement, path, issue, gap,
            lambda support, point, support_path: check_point_support(
                support, point, support_path, target=binding.target,
                definition_ids=(() if static_use is None or static_use.definition is None
                                else (static_use.definition,))),
        )

    # A captured operation occurrence proves the operation happened, but a
    # missing resource-access association remains a coverage gap, not purity.
    for occurrence_id, occurrence in ctx.occurrences.items():
        for requirement_id in static_requirements_by_operation.get(occurrence.operation, ()):
            if (occurrence_id, requirement_id) not in seen_accesses:
                gap("access_missing", occurrence_id,
                    "canonical ResourceUse has no corresponding dynamic access binding")

    # Allocation placements reuse ValueGraph allocation IDs; pools are distinct
    # resource instances and never inferred from an allocation's storage.
    for index, placement in enumerate(ctx.model.placements):
        path = f"placements[{index}]"
        graph = ctx.external_values(placement.allocation.artifact, path)
        if graph is not None and placement.allocation.allocation not in graph.allocations:
            issue("placement_allocation", path, "placed allocation is absent from its exact ValueGraph")
        pool = ctx.resources.get(placement.pool.instance)
        if pool is None:
            issue("placement_pool", path, "allocation placement references an unknown pool resource")
        elif pool.kind is not ResourceKind.MEMORY or pool.role is not ResourceRole.MEMORY_POOL:
            issue("placement_pool", path, "allocation placement target must be a MEMORY_POOL instance")


def _validate_constraints(ctx, access, binding, requirement, path, issue, gap, check_support):
    """Validate exact static tuple positions without treating claims as results."""
    seen = set()
    expected_capacities = set(range(len(requirement.capacities)))
    expected_relations = set(range(len(requirement.relations)))
    point = OccurrencePoint(access.operation, OccurrencePhase.BEFORE)
    for index, row in enumerate(access.constraints):
        constraint = row.constraint
        item_path = f"{path}.constraints[{index}]"
        check_support(row.support, point, item_path)
        if type(constraint) is CapacityAt:
            if constraint.requirement != binding.requirement:
                issue("constraint_capacity_owner", item_path, "capacity evidence references another requirement")
                continue
            if constraint.index not in expected_capacities:
                issue("constraint_capacity_index", item_path, "capacity index is outside the exact requirement tuple")
                continue
            key = ("capacity", constraint.index)
            if key in seen:
                issue("constraint_duplicate", item_path, "capacity obligation has duplicate evidence")
            seen.add(key)
            gap("capacity_unverified", item_path,
                "a typed capacity reference is not a measurement that the bound is satisfied")
        elif type(constraint) is RelationAt:
            if constraint.requirement != binding.requirement:
                issue("constraint_relation_owner", item_path, "relation evidence references another requirement")
                continue
            if constraint.index not in expected_relations:
                issue("constraint_relation_index", item_path, "relation index is outside the exact requirement tuple")
                continue
            key = ("relation", constraint.index)
            if key in seen:
                issue("constraint_duplicate", item_path, "relation obligation has duplicate evidence")
            seen.add(key)
            declared = requirement.relations[constraint.index]
            other = ctx.requirements.get(constraint.other)
            if other is None:
                issue("constraint_relation_target", item_path, "relation evidence references an unknown binding")
                continue
            if other.requirement != declared.other or other.owner != binding.owner:
                issue("constraint_relation_target", item_path,
                      "relation binding is not the exact related requirement at this owner")
                continue
            if declared.relation is RequirementRelation.SAME_RESOURCE:
                if binding.target != other.target:
                    issue("constraint_same_resource", item_path, "SAME_RESOURCE targets differ")
            elif declared.relation is RequirementRelation.DISTINCT_RESOURCE:
                if binding.target == other.target:
                    issue("constraint_distinct_resource", item_path, "DISTINCT_RESOURCE targets are identical")
            else:
                gap("constraint_child_relation", item_path,
                    "CHILD_RESOURCE needs a typed containment relation not present in this model")
        elif type(constraint) is ProtocolCondition:
            for use_ref in constraint.uses:
                if use_ref.operation not in ctx.occurrences:
                    issue("constraint_protocol_use", item_path, "protocol condition references an unknown operation occurrence")
                elif (use_ref.operation, use_ref.use) not in ctx.uses:
                    issue("constraint_protocol_use", item_path, "protocol condition references a missing exact Use occurrence")
            gap("constraint_protocol_unverified", item_path,
                "protocol condition evaluation is not implemented by structural resource validation")
        else:
            issue("constraint_variant", item_path, "unknown resource constraint evidence variant")
    for index in sorted(expected_capacities - {item[1] for item in seen if item[0] == "capacity"}):
        gap("constraint_capacity_missing", path,
            f"capacity obligation at tuple index {index} has no evidence reference")
    for index in sorted(expected_relations - {item[1] for item in seen if item[0] == "relation"}):
        gap("constraint_relation_missing", path,
            f"relation obligation at tuple index {index} has no evidence reference")


__all__ = ["resource_errors"]
