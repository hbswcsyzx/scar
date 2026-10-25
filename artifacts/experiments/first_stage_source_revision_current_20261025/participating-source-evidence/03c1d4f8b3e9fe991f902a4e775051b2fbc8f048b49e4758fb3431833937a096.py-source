"""Validate address refinements against the graph's original state ports.

This validator never adds state accesses or versions. It checks only typed
ownership and consistency with the original coarse summaries/invoke ports;
address metadata does not establish alias disjointness or runtime effects.
"""
from __future__ import annotations

from scar.ir.program.model import (
    AccessMode, ProgramGraph, ReferenceValue, StateVersionValue, TerminatorKind, UseRole,
)
from scar.ir.program.ids import OperationID, RegionID
from scar.ir.program.resources import ResourceUse
from scar.ir.program.state_addresses import (
    AddressCoverage, AddressEffect, DomainOwner, ExistingAccess,
    InvokeStateOperand, ReferenceOwner, ResourceOwner, StateAddressRefinement,
    UnknownOwner, WholeOwner, address_effect_uses,
)


def _mode_bits(mode):
    if mode is AccessMode.READ:
        return 1
    if mode is AccessMode.WRITE:
        return 2
    if mode is AccessMode.READ_WRITE:
        return 3
    return 0


def _root_replacement(effect):
    return (
        type(effect) is AddressEffect
        and type(effect.owner) is DomainOwner
        and len(effect.path) == 1
        and type(effect.path[0]) is WholeOwner
        and effect.mode is AccessMode.WRITE
    )


def state_address_errors(graph: ProgramGraph) -> tuple[tuple[str, str, str], ...]:
    """Return structural address issues without changing canonical state SSA.

    `graph` is expected to be a ProgramGraph. Malformed/foreign references are
    reported as bounded issues rather than used as dictionary indexes.
    """
    issues: list[tuple[str, str, str]] = []

    def error(code, path, message):
        issues.append((code, str(path), message))

    if type(graph) is not ProgramGraph:
        return (("address_graph", "graph", "expected ProgramGraph"),)

    operations = {row.id: row for row in graph.operations}
    values = {row.id: row for row in graph.values}
    requirements = {row.id: row for row in graph.resource_requirements}
    regions = {row.id: row for row in graph.regions}
    resource_definition_ids = {row.id for row in graph.resources}
    resources_by_operation: dict[object, list[ResourceUse]] = {}
    for row in graph.resource_uses:
        resources_by_operation.setdefault(row.operation, []).append(row)
    operation_region = {}
    for region in graph.regions:
        for block in region.blocks:
            for operation_id in block.operations:
                operation_region[operation_id] = region.id

    def requirement_owns_operation(requirement, operation_id):
        owner = requirement.owner
        if type(owner) is OperationID:
            return owner == operation_id
        if type(owner) is not RegionID:
            return False
        current = operation_region.get(operation_id)
        visited = set()
        while current in regions and current not in visited:
            if current == owner:
                return True
            visited.add(current)
            current = regions[current].parent
        return False

    seen_sites = set()
    seen_carriers = set()
    for row_index, row in enumerate(graph.state_address_refinements):
        base_path = f"state_address_refinements[{row_index}]"
        if type(row) is not StateAddressRefinement:
            error("address_record", base_path, "expected exact StateAddressRefinement")
            continue
        try:
            row.__post_init__()
        except (TypeError, ValueError) as exc:
            error("address_record", base_path, str(exc))
            continue

        if row.site in seen_sites:
            error("address_duplicate_site", base_path,
                  "an original state-effect site may have only one refinement")
        seen_sites.add(row.site)

        operation_id = row.site.operation
        operation = operations.get(operation_id)
        if operation is None:
            error("address_operation", base_path, "site operation is not in this graph")
            continue
        own_uses = {use.id: use for use in operation.uses}
        is_invoke = (
            operation.terminator is not None
            and operation.terminator.kind is TerminatorKind.INVOKE
        )

        access = None
        state_location = None
        if type(row.site) is ExistingAccess:
            if is_invoke:
                error("address_site_kind", base_path,
                      "ExistingAccess cannot name an INVOKE operation")
                continue
            if row.site.index >= len(operation.accesses):
                error("address_access_index", base_path,
                      "access index is not present on the operation")
                continue
            access = operation.accesses[row.site.index]
            state_location = access.location
            before_use = own_uses.get(access.before)
            if before_use is None:
                error("address_access_before", base_path,
                      "selected access has no owned before Use")
            else:
                before_value = values.get(before_use.value)
                expected_role = (UseRole.STATE_ORDER if access.full_overwrite
                                 else UseRole.STATE_CONTENT)
                if before_use.role is not expected_role:
                    error("address_access_role", base_path,
                          "selected access before Use disagrees with its overwrite role")
                if not isinstance(before_value, StateVersionValue):
                    error("address_access_state", base_path,
                          "selected access before Use is not a StateVersionValue")
                elif before_value.location != access.location:
                    error("address_access_state", base_path,
                          "selected access before state has the wrong location")
            if access.mode not in (AccessMode.READ, AccessMode.WRITE, AccessMode.READ_WRITE):
                error("address_access_mode", base_path, "selected access has an invalid mode")
        elif type(row.site) is InvokeStateOperand:
            if not is_invoke:
                error("address_site_kind", base_path,
                      "InvokeStateOperand must name an INVOKE operation")
                continue
            state_use = own_uses.get(row.site.state_use)
            if state_use is None:
                error("address_invoke_use", base_path,
                      "state operand is not an owned Use")
                continue
            if row.site.state_use not in operation.invoke_arguments:
                error("address_invoke_argument", base_path,
                      "state operand is not an actual invoke_arguments Use")
            if state_use.role is not UseRole.STATE_CONTENT:
                error("address_invoke_role", base_path,
                      "INVOKE state operands require the core STATE_CONTENT role")
            state_value = values.get(state_use.value)
            if not isinstance(state_value, StateVersionValue):
                error("address_invoke_state", base_path,
                      "invoke state operand does not carry a StateVersionValue")
            else:
                state_location = state_value.location
        else:
            error("address_site_kind", base_path, "unsupported state address site variant")
            continue

        if state_location is not None:
            carrier_key = (operation_id, state_location)
            if carrier_key in seen_carriers:
                error("address_duplicate_carrier", base_path,
                      "an operation may have only one refinement per derived state carrier")
            seen_carriers.add(carrier_key)

        resource_uses = resources_by_operation.get(operation_id, ())
        reference_envelope = None
        if access is not None and access.reference is not None:
            reference_use = own_uses.get(access.reference)
            if reference_use is None or reference_use.role is not UseRole.REFERENCE:
                error("address_reference_envelope", base_path,
                      "access reference is not an owned REFERENCE Use")
            else:
                reference_envelope = values.get(reference_use.value)
                if not isinstance(reference_envelope, ReferenceValue):
                    error("address_reference_envelope", base_path,
                          "access reference Use does not carry a ReferenceValue")
                elif (reference_envelope.targets is not None
                      and state_location is not None
                      and state_location not in reference_envelope.targets):
                    error("address_reference_target", base_path,
                          "access reference excludes the selected state location")

        covered_modes = 0
        for effect_index, effect in enumerate(row.effects):
            effect_path = f"{base_path}.effects[{effect_index}]"
            if type(effect) is not AddressEffect:
                error("address_effect", effect_path, "expected exact AddressEffect")
                continue
            try:
                effect.__post_init__()
            except (TypeError, ValueError) as exc:
                error("address_effect", effect_path, str(exc))
                continue

            effect_uses = []
            owner = effect.owner
            if type(owner) is ReferenceOwner:
                owner_use = own_uses.get(owner.use)
                if owner_use is None:
                    error("address_owner_use", effect_path,
                          "reference owner is not an owned Use")
                elif owner_use.role is not UseRole.REFERENCE:
                    error("address_owner_role", effect_path,
                          "reference owner Use must have REFERENCE role")
                else:
                    owner_value = values.get(owner_use.value)
                    if not isinstance(owner_value, ReferenceValue):
                        error("address_owner_value", effect_path,
                              "reference owner Use does not carry a ReferenceValue")
                    else:
                        if (owner_value.targets is not None and state_location is not None
                                and state_location not in owner_value.targets):
                            error("address_owner_target", effect_path,
                                  "reference owner excludes the selected state location")
                        if (reference_envelope is not None
                                and owner_value.id != reference_envelope.id):
                            error("address_reference_envelope", effect_path,
                                  "reference owner is outside the access reference envelope")
                effect_uses.append(owner.use)
            elif type(owner) is ResourceOwner:
                requirement = requirements.get(owner.requirement)
                if requirement is None:
                    error("address_resource_requirement", effect_path,
                          "resource owner requirement is not in this graph")
                else:
                    found = [item for item in resource_uses
                             if item.requirement == owner.requirement]
                    if not found:
                        error("address_resource_use", effect_path,
                              "resource owner has no ResourceUse on this operation")
                    for item in found:
                        if item.definition is not None and item.definition not in resource_definition_ids:
                            error("address_resource_definition", effect_path,
                                  "ResourceUse names a missing resource definition")
                        if reference_envelope is not None and item.handle is None:
                            error("address_reference_envelope", effect_path,
                                  "resource owner has no handle inside the access reference envelope")
                        if item.handle is not None:
                            handle = own_uses.get(item.handle)
                            if handle is None or handle.role is not UseRole.REFERENCE:
                                error("address_resource_handle", effect_path,
                                      "ResourceUse handle is not an owned REFERENCE Use")
                            else:
                                effect_uses.append(item.handle)
                                if (reference_envelope is not None
                                        and handle.value != reference_envelope.id):
                                    error("address_reference_envelope", effect_path,
                                          "resource handle is outside the access reference envelope")
            elif type(owner) is UnknownOwner:
                effect_uses.extend(owner.operands)
                if reference_envelope is not None:
                    error("address_reference_envelope", effect_path,
                          "UnknownOwner cannot bypass an explicit access reference envelope")
            elif type(owner) is DomainOwner:
                if reference_envelope is not None:
                    error("address_reference_envelope", effect_path,
                          "DomainOwner cannot bypass an explicit access reference envelope")
            else:
                error("address_owner", effect_path, "unsupported address owner variant")

            try:
                effect_uses.extend(address_effect_uses(effect))
            except (TypeError, ValueError) as exc:
                error("address_selector", effect_path, str(exc))

            for use_id in effect_uses:
                use = own_uses.get(use_id)
                if use is None:
                    error("address_operand_use", effect_path,
                          f"address operand {use_id} is not owned by this operation")
                    continue
                if use.role not in (UseRole.DATA, UseRole.REFERENCE):
                    error("address_operand_role", effect_path,
                          "owner/key/index/slice operands must be DATA or REFERENCE Uses")
                if is_invoke and use_id not in operation.invoke_arguments:
                    error("address_invoke_argument", effect_path,
                          "address operand must be an actual invoke_arguments Use")

            if type(owner) is ResourceOwner:
                # A resource requirement is owned either directly by this
                # operation or by a lexical ancestor region, matching the
                # canonical ResourceUse ownership rule. No resource identity
                # is inferred from a label or unrelated ResourceUse.
                requirement = requirements.get(owner.requirement)
                if (requirement is not None
                        and not requirement_owns_operation(requirement, operation_id)):
                    error("address_resource_scope", effect_path,
                          "resource requirement belongs to another operation/region")

            effect_bits = _mode_bits(effect.mode)
            covered_modes |= effect_bits
            if access is not None and effect_bits & ~_mode_bits(access.mode):
                error("address_mode_exceeds_summary", effect_path,
                      "address effect mode exceeds its selected StateAccess mode")

        if access is not None and row.coverage is AddressCoverage.DECLARED_COMPLETE:
            if covered_modes != _mode_bits(access.mode):
                error("address_mode_incomplete", base_path,
                      "complete address effects do not cover the original access mode")

        root_replacement = (
            len(row.effects) == 1 and _root_replacement(row.effects[0])
            and row.coverage is AddressCoverage.DECLARED_COMPLETE
        )
        if access is not None and access.full_overwrite and not root_replacement:
            error("address_full_overwrite", base_path,
                  "a refined full overwrite must remain a complete DomainOwner whole-root WRITE")
    return tuple(issues)


__all__ = ["state_address_errors"]
