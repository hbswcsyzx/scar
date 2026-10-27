"""Validate declared function environment ports in the canonical graph.

This checks interface well-formedness only. ``code_definition`` is a declared
symbol, not verified runtime code/environment identity. Member locations are
necessary state domains declared by this interface, not a complete read/alias
summary: omitted domains never mean NONE, shared/coarse domains remain legal,
and unknown reference targets never prove disjointness.

Actual environment arguments are exclusively the existing call/invoke operands.
The ordinary core validator checks their positional types, availability, state
currentness and completion flow; this module stores no parallel binding table.
Python formal ports are object references, not unboxed Data values. Their
declared signature order is independent of physical entry order: exact ValueIDs
partition the entry into formals, environment references and state parameters.
This structural declaration does not verify source signature/runtime binding.
"""
from __future__ import annotations

from scar.ir.program.model import BlockArgument, ReferenceValue, StateVersionValue


def _entry_value(value, region, entry, allowed):
    return (isinstance(value, allowed)
            and value.region == region.id
            and isinstance(value.origin, BlockArgument)
            and value.origin.block == entry.id
            and value.origin.index < len(entry.arguments)
            and entry.arguments[value.origin.index] == value.id)


def environment_errors(graph, operation_regions, uses):
    """Yield ``(code, path, message)`` for graph-level environment errors.

    The common validator passes operation/use indexes for interface validators;
    this aggregate has no independent operation-owned actual bindings to check.
    """
    del operation_regions, uses
    regions = {region.id: region for region in graph.regions}
    values = {value.id: value for value in graph.values}
    locations = {location.id for location in graph.locations}
    environments = {environment.id: environment for environment in graph.environments}
    owners = set()

    for index, environment in enumerate(graph.environments):
        path = f"environments[{index}]"
        if environment.region in owners:
            yield ("environment_region", path,
                   "one region may declare at most one function environment interface")
        owners.add(environment.region)
        region = regions.get(environment.region)
        if region is None:
            yield ("environment_owner", path, "environment owning region does not exist")
            continue
        entry = next((block for block in region.blocks if block.id == region.entry), None)
        if entry is None:
            yield ("environment_entry", path, "environment region has no matching entry block")
            continue
        entry_domains = {
            value.location for identity in entry.arguments
            if isinstance(value := values.get(identity), StateVersionValue)
        }
        member_ports = set()
        for member_index, member in enumerate(environment.members):
            member_path = f"{path}.members[{member_index}]"
            if member.reference in member_ports:
                yield ("environment_reference", member_path,
                       "independent environment members need distinct entry reference ports")
            member_ports.add(member.reference)
            reference = values.get(member.reference)
            if not _entry_value(reference, region, entry, ReferenceValue):
                yield ("environment_reference", member_path,
                       "member reference must be this region's exact entry ReferenceValue argument")
            for location in member.locations:
                if location not in locations:
                    yield ("environment_location", member_path,
                           "declared environment state location does not exist")
                if location not in entry_domains:
                    yield ("environment_state_domain", member_path,
                           "declared environment location needs a canonical entry state parameter")
                if (isinstance(reference, ReferenceValue)
                        and reference.targets is not None
                        and location not in reference.targets):
                    yield ("environment_reference_targets", member_path,
                           "declared environment location contradicts known reference targets")

    layouts = set()
    for index, layout in enumerate(graph.function_entries):
        path = f"function_entries[{index}]"
        if layout.environment in layouts:
            yield ("function_entry_duplicate", path,
                   "one environment may have only one function entry layout")
        layouts.add(layout.environment)
        environment = environments.get(layout.environment)
        if environment is None:
            yield ("function_entry_environment", path,
                   "function entry layout needs an existing environment interface")
            continue
        region = regions.get(environment.region)
        if region is None:
            continue  # Reported by the owning environment above.
        entry = next((block for block in region.blocks if block.id == region.entry), None)
        if entry is None:
            continue
        implicit = {member.reference for member in environment.members}
        free_slots = {member.cell_slot for member in environment.members
                      if member.cell_slot is not None}
        parameters = {parameter.value for parameter in layout.parameters}
        for parameter_index, parameter in enumerate(layout.parameters):
            if parameter.slot in free_slots:
                yield ("function_entry_slot", f"{path}.parameters[{parameter_index}]",
                       "a Python formal slot cannot also be this body's captured free-variable slot")
            value = values.get(parameter.value)
            if (parameter.value in implicit
                    or not _entry_value(value, region, entry, ReferenceValue)):
                yield ("function_entry_parameter", f"{path}.parameters[{parameter_index}]",
                       "Python formal must be an exact entry ReferenceValue port, not environment or state")
        expected = {identity for identity in entry.arguments
                    if not isinstance(values.get(identity), StateVersionValue)
                    and identity not in implicit}
        if parameters != expected:
            yield ("function_entry_partition", path,
                   "Python formal ports must cover exactly the non-state, non-environment entry arguments")
    for environment in graph.environments:
        if environment.id not in layouts:
            yield ("function_entry_missing", environment.id,
                   "each function environment needs an explicit formal/environment/state entry partition")


__all__ = ["environment_errors"]
