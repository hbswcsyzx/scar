"""Structural and dependency validation for the bounded program core.

Well-formedness checks declared relationships; it does not certify operation
purity, recover unobserved effects, or authorize any transformation.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..v2._validation import cycle_errors, record_errors
from .ids import UseID
from .model import (
    AccessMode, Behavior, BlockArgument, CompletionResult, CompletionSuccessor,
    DataValue, ExitKind, FootprintKind, LocalBindingValue,
    LiteralOrigin, OperationResult, ProgramGraph, ProtocolValue, ReferenceValue,
    StateVersionValue, TerminatorKind, UseRole, ValueKind, value_type,
)
from .control import PendingDispatchTerminator
from .cleanup import CleanupRouteTerminator
from .resumption import (
    ResumeInput, SuspendTerminator, saved_actual_use, resume_slot_type,
)
from .drivers import BodyDriveResult, BodyDriveSuccessor, BodyDriveTerminator
from .driver_flow import body_outcome_types


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    path: str
    message: str


def validate(graph: ProgramGraph, *, _cleanup_facts=None, _resumption_facts=None) -> tuple[ValidationIssue, ...]:
    """Check exact uses, CFG availability, interfaces and explicit state SSA.

    The private output collector lets ProgramIndex reuse derived cleanup facts
    after every validator passes; it never accepts caller-supplied proof facts.
    """
    issues: list[ValidationIssue] = []

    def error(code, path, message):
        issues.append(ValidationIssue(code, str(path), message))

    schema = record_errors(graph, ProgramGraph, "graph")
    if schema:
        return tuple(ValidationIssue("schema", "graph", text) for text in schema)

    def registry(records, name):
        result = {}
        for record in records:
            if record.id in result:
                error("duplicate_id", name, str(record.id))
            result[record.id] = record
        return result

    regions = registry(graph.regions, "regions")
    body_regions = {row.region for row in graph.resumable_bodies}
    operations = registry(graph.operations, "operations")
    drives = {row.operation: row for row in graph.body_drives}
    values = registry(graph.values, "values")
    locations = registry(graph.locations, "locations")
    blocks = {}
    block_region = {}
    operation_block = {}
    positions = {}
    uses = {}
    if graph.root not in regions:
        error("missing_root", "root", str(graph.root))
    for region in graph.regions:
        if region.id == graph.root:
            if region.parent is not None:
                error("root_parent", region.id, "root must have no parent")
        elif region.parent not in regions:
            error("region_parent", region.id, "non-root region needs an existing parent")
        if region.entry not in {block.id for block in region.blocks}:
            error("region_entry", region.id, "entry must belong to region")
        for block in region.blocks:
            if block.id in blocks:
                error("duplicate_block", block.id, "block must have one owner")
            blocks[block.id] = block
            block_region[block.id] = region.id
            for index, operation_id in enumerate(block.operations):
                if operation_id not in operations:
                    error("missing_operation", block.id, str(operation_id))
                if operation_id in operation_block:
                    error("operation_owner", operation_id, "operation must occur in exactly one block")
                operation_block[operation_id] = block.id
                positions[operation_id] = index
    for operation in graph.operations:
        if operation.id not in operation_block:
            error("operation_owner", operation.id, "operation has no owning block")
        for use in operation.uses:
            if use.id in uses:
                error("duplicate_use", operation.id, str(use.id))
            uses[use.id] = (operation.id, use)
            if use.value not in values:
                error("missing_value", use.id, str(use.value))
        for value_id in operation.results:
            if value_id not in values:
                error("missing_result", operation.id, str(value_id))
        if operation.callee is not None and operation.callee not in regions:
            error("missing_callee", operation.id, str(operation.callee))
        if operation.callee in body_regions:
            error("resumption_direct_call", operation.id,
                  "a resumable body requires a dedicated driver ingress, not CALL/INVOKE")
    for value in graph.values:
        if value.region not in regions:
            error("value_region", value.id, str(value.region))
        if isinstance(value, StateVersionValue) and value.location not in locations:
            error("missing_location", value.id, str(value.location))
        if isinstance(value, ReferenceValue) and value.targets is not None:
            for target in value.targets:
                if target not in locations:
                    error("missing_location", value.id, str(target))
        if isinstance(value.origin, BlockArgument):
            block = blocks.get(value.origin.block)
            if (block is None or value.origin.index >= len(block.arguments)
                    or block.arguments[value.origin.index] != value.id
                    or value.region != block_region.get(value.origin.block)):
                error("argument_origin", value.id, "origin does not match owning argument")
        elif isinstance(value.origin, OperationResult):
            producer = operations.get(value.origin.operation)
            if (producer is None or value.origin.index >= len(producer.results)
                    or producer.results[value.origin.index] != value.id
                    or value.region != block_region.get(operation_block.get(value.origin.operation))):
                error("result_origin", value.id, "origin does not match owning result")
        elif not isinstance(value, (DataValue, ReferenceValue)):
            error("literal_type", value.id, "only data and immutable reference values can be literals")
    for block in blocks.values():
        for index, value_id in enumerate(block.arguments):
            value = values.get(value_id)
            if (value is None or value.origin != BlockArgument(block.id, index)
                    or value.region != block_region[block.id]):
                error("argument_definition", block.id, str(value_id))
    for operation in operations.values():
        for index, value_id in enumerate(operation.results):
            value = values.get(value_id)
            if value is not None and value.origin != OperationResult(operation.id, index):
                error("result_definition", operation.id, str(value_id))
    for text in cycle_errors(((r.parent, r.id) for r in graph.regions if r.parent is not None), "region ownership"):
        error("ownership_cycle", "regions", text)
    if issues:
        return tuple(issues)

    from .resource_validation import resource_errors
    for code, path, message in resource_errors(
            graph, {op: block_region[block] for op, block in operation_block.items()}, uses):
        error(code, path, message)

    from .environment_validation import environment_errors
    for code, path, message in environment_errors(
            graph, {op: block_region[block] for op, block in operation_block.items()}, uses):
        error(code, path, message)

    def check_footprint(footprint, location, path):
        extent = locations[location].extent
        if (footprint.kind is FootprintKind.INTERVAL and extent is not None
                and footprint.stop > extent):
            error("footprint_bounds", path, "interval exceeds location extent")

    def covers(outer, inner, location):
        if outer.kind is FootprintKind.WHOLE:
            return True
        if outer.kind is FootprintKind.UNKNOWN or inner.kind is FootprintKind.UNKNOWN:
            return None
        if inner.kind is FootprintKind.WHOLE:
            extent = locations[location].extent
            return None if extent is None else outer.start == 0 and outer.stop == extent
        return outer.start <= inner.start and outer.stop >= inner.stop

    for value in values.values():
        if isinstance(value, ReferenceValue) and value.targets is not None:
            for location in value.targets:
                check_footprint(value.selector, location, value.id)

    # Each use has one owner and a role matching the kind of the actual value.
    use_value_types = {
        UseRole.DATA: DataValue,
        UseRole.REFERENCE: ReferenceValue,
        UseRole.STATE_CONTENT: StateVersionValue,
        UseRole.STATE_ORDER: StateVersionValue,
        UseRole.LOCAL_BINDING: LocalBindingValue,
        UseRole.PROTOCOL: ProtocolValue,
    }
    for operation in operations.values():
        for use in operation.uses:
            value = values[use.value]
            expected = use_value_types[use.role]
            if not isinstance(value, expected):
                error("use_role", use.id, "input role does not match value kind")
            if value.region != block_region[operation_block[operation.id]]:
                error("cross_region_use", use.id, "cross-region values require explicit call ports")

    successors = {block: set() for block in blocks}
    predecessors = {block: set() for block in blocks}
    incoming_edges = {block: [] for block in blocks}
    terminators = {}
    for block in blocks.values():
        if not block.operations:
            error("missing_terminator", block.id, "block must end in a terminator")
            continue
        for index, operation_id in enumerate(block.operations):
            operation = operations[operation_id]
            if operation.terminator is not None and index != len(block.operations) - 1:
                error("terminator_position", operation_id, "terminator must be last")
        final = operations[block.operations[-1]]
        term = final.terminator
        if term is None:
            error("missing_terminator", block.id, "last operation is not a terminator")
            continue
        terminators[block.id] = final
        if Behavior.CONTROL not in final.behaviors:
            error("control_behavior", final.id, "terminator requires CONTROL")
        is_invoke = term.kind is TerminatorKind.INVOKE
        is_drive = type(term) is BodyDriveTerminator
        if (final.results or final.accesses or final.callee is not None) and not is_invoke:
            error("terminator_effect", final.id, "N1 terminators only bind control and interface uses")
        own_uses = {use.id: use for use in final.uses}
        for use in final.uses:
            if isinstance(values[use.value], StateVersionValue) and use.role is not UseRole.STATE_CONTENT:
                error("control_state_role", use.id, "state carried across control ports retains content dependence")
        bound = ([term.condition] if term.condition is not None else [])
        if isinstance(term, (PendingDispatchTerminator, CleanupRouteTerminator)):
            bound.append(term.pending)
        bound += [use for edge in term.successors for use in edge.arguments if isinstance(use, UseID)]
        bound += list(term.values)
        if is_invoke:
            bound += list(final.invoke_arguments)
        if is_drive:
            if final.id not in drives:
                error("driver_declaration_missing", final.id,
                      "a BodyDrive terminator requires its canonical driver record")
            else:
                bound += list(drives[final.id].actual_uses)
        if term.kind is TerminatorKind.RAISE:
            # A definitely-unbound LOAD_LOCAL reads its token as the reason
            # for raising, but that token is not part of the exception exit
            # interface. BindingRead is the sole typed exception to the usual
            # terminator-operand equality rule.
            bound += [item.binding for item in graph.binding_reads
                      if item.operation == final.id and item.normal_result is None]
        if len(set(bound)) != len(bound) or set(bound) != set(own_uses):
            error("control_binding", final.id, "each control input port needs its own exact use")
        signatures = {signature.kind: signature for signature in final.completions}
        for edge_index, edge in enumerate(term.successors):
            target = blocks.get(edge.block)
            if target is None or block_region.get(edge.block) != block_region[block.id]:
                error("control_target", final.id, "successor must belong to same region")
                continue
            successors[block.id].add(edge.block)
            predecessors[edge.block].add(block.id)
            incoming_edges[edge.block].append((final.id, edge_index))
            if len(edge.arguments) != len(target.arguments):
                error("edge_arity", final.id, "successor argument count mismatch")
            drive_types = None
            if isinstance(edge, BodyDriveSuccessor):
                try:
                    drive_types = body_outcome_types(graph, edge.source)
                except ValueError as exc:
                    error("driver_outcome_source", final.id, str(exc))
            for actual, formal in zip(edge.arguments, target.arguments):
                if isinstance(actual, ResumeInput):
                    if not isinstance(term, SuspendTerminator):
                        error("resumption_binding", final.id, "resume input requires SUSPEND")
                        continue
                    if value_type(values[formal]) != resume_slot_type(edge.inputs[actual.resume_slot]):
                        error("resumption_input_type", formal, "resume input signature differs from landing parameter")
                    ref = values[formal]
                    if isinstance(ref, ReferenceValue) and (
                            ref.targets is not None or ref.referent_identity is not None
                            or ref.selector.kind is not FootprintKind.UNKNOWN):
                        error("resumption_reference_precision", formal,
                              "a newly delivered reference grants no target, selector or identity facts")
                elif isinstance(actual, BodyDriveResult):
                    if not is_drive or not isinstance(edge, BodyDriveSuccessor):
                        error("driver_result_binding", final.id,
                              "a body projection requires a typed BodyDrive successor")
                        continue
                    if drive_types is None:
                        continue
                    if actual.index >= len(drive_types):
                        error("driver_result_index", final.id,
                              "body result index exceeds this source's actual signature")
                        continue
                    if value_type(values[formal]) != drive_types[actual.index]:
                        error("driver_result_type", formal,
                              "body projection type differs from this source's signature")
                    ref = values[formal]
                    if isinstance(ref, ReferenceValue) and (
                            ref.targets is not None or ref.referent_identity is not None
                            or ref.selector.kind is not FootprintKind.UNKNOWN):
                        error("driver_reference_precision", formal,
                              "a body reference result grants no identity or alias precision")
                elif isinstance(actual, CompletionResult):
                    if not isinstance(edge, CompletionSuccessor) or edge.kind not in signatures:
                        error("completion_binding", final.id, "produced value requires an invoke completion")
                        continue
                    signature = signatures[edge.kind]
                    if actual.index >= len(signature.types):
                        error("completion_index", final.id, "produced result index exceeds this completion signature")
                        continue
                    if value_type(values[formal]) != signature.types[actual.index]:
                        error("completion_type", formal, "produced result type differs from target parameter")
                    ref = values[formal]
                    if isinstance(ref, ReferenceValue) and (
                            ref.targets is not None or ref.referent_identity is not None
                            or ref.selector.kind is not FootprintKind.UNKNOWN):
                        error("completion_reference_precision", formal,
                              "produced references need verified summaries before gaining target or identity precision")
                else:
                    source = saved_actual_use(final, actual)
                    if source in own_uses and value_type(values[own_uses[source].value]) != value_type(values[formal]):
                        error("edge_type", source, "successor argument type mismatch")
            if isinstance(edge, CompletionSuccessor) and edge.kind in signatures:
                produced = [arg.index for arg in edge.arguments if isinstance(arg, CompletionResult)]
                if len(set(produced)) != len(produced) or set(produced) != set(range(len(signatures[edge.kind].types))):
                    error("completion_slots", final.id, "every produced completion slot must bind exactly once")
            if isinstance(edge, BodyDriveSuccessor) and drive_types is not None:
                produced = [arg.index for arg in edge.arguments if isinstance(arg, BodyDriveResult)]
                if len(set(produced)) != len(produced) or set(produced) != set(range(len(drive_types))):
                    error("driver_result_slots", final.id,
                          "every source outcome slot must bind exactly once")
        if term.kind is TerminatorKind.BRANCH and term.condition in own_uses:
            condition = values[own_uses[term.condition].value]
            if not isinstance(condition, DataValue) or condition.data_type != "builtins.bool":
                error("branch_condition", final.id, "branch condition must be builtin bool")
        if term.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
            region = regions[block_region[block.id]]
            exit_port = next((port for port in region.exits if port.name == term.exit), None)
            expected = ExitKind.NORMAL if term.kind is TerminatorKind.RETURN else ExitKind.RAISE
            if exit_port is None or exit_port.kind is not expected:
                error("exit_binding", final.id, "missing or wrong kind of exit")
            else:
                if len(term.values) != len(exit_port.types):
                    error("exit_arity", final.id, "exit value count mismatch")
                for actual, formal in zip(term.values, exit_port.types):
                    if actual in own_uses and value_type(values[own_uses[actual].value]) != formal:
                        error("exit_type", actual, "exit value type mismatch")
    if issues:
        return tuple(issues)

    for operation in terminators.values():
        if operation.terminator.kind in (
                TerminatorKind.INVOKE, TerminatorKind.SUSPEND, TerminatorKind.BODY_DRIVE):
            for edge in operation.terminator.successors:
                if len(incoming_edges[edge.block]) != 1:
                    error("completion_private_target", operation.id,
                          "each completion must enter its own target with one actual incoming edge")
    if issues:
        return tuple(issues)

    dominators = {}
    availability = {}
    for region in graph.regions:
        local = {block.id for block in region.blocks}
        if predecessors[region.entry]:
            error("entry_predecessor", region.id, "entry cannot have incoming control edges")
        seen, pending = set(), [region.entry]
        while pending:
            block = pending.pop()
            if block not in seen:
                seen.add(block)
                pending.extend(successors[block])
        if seen != local:
            error("unreachable_block", region.id, "every block must be reachable from entry")
            continue
        dom = {block: ({block} if block == region.entry else set(local)) for block in local}
        changed = True
        while changed:
            changed = False
            for block in local - {region.entry}:
                incoming = predecessors[block]
                updated = {block} | set.intersection(*(dom[p] for p in incoming))
                if updated != dom[block]:
                    dom[block] = updated
                    changed = True
        dominators.update(dom)
        # Logical edges preserve cleanup activation. Availability has additional
        # roots: a future drive cannot use an old definition without an explicit
        # saved slot and a fresh landing parameter, even through a loop/merge.
        roots = {region.entry} | {
            edge.block for block in local
            if isinstance(terminators[block].terminator, SuspendTerminator)
            for edge in terminators[block].terminator.successors
        }
        available = {block: ({block} if block in roots else set(local)) for block in local}
        changed = True
        while changed:
            changed = False
            for block in local - roots:
                updated = {block} | set.intersection(*(available[p] for p in predecessors[block]))
                if updated != available[block]:
                    available[block] = updated
                    changed = True
        availability.update(available)
        bound_exits = {terminators[block].terminator.exit for block in local
                       if terminators[block].terminator.exit is not None}
        # C1 can intercept a declared language target forever, or replace its
        # pending transfer. Its full validator checks support from the exact
        # cleanup entry token after stack/routing checks. Old schemas retain
        # their original requirement for an actual terminal site at every exit.
        c1_enabled = any(row.region == region.id for row in graph.handled_context_domains)
        if {port.name for port in region.exits} != bound_exits and not c1_enabled:
            error("unbound_exit", region.id, "declared exits must be bound to actual control exits")
    if issues:
        return tuple(issues)

    for operation in graph.operations:
        block = operation_block[operation.id]
        for use in operation.uses:
            origin = values[use.value].origin
            if isinstance(origin, LiteralOrigin):
                continue
            producer_block = (origin.block if isinstance(origin, BlockArgument)
                              else operation_block[origin.operation])
            if producer_block not in availability[block]:
                error("unavailable_value", use.id, "definition does not dominate use across all availability roots")
            elif (isinstance(origin, OperationResult) and producer_block == block
                  and positions[origin.operation] >= positions[operation.id]):
                error("use_before_definition", use.id, "result must be defined before use")

    # N1 state convention: each block carries every region state domain explicitly.
    region_domains = {}
    for region in graph.regions:
        entry = blocks[region.entry]
        domain_list = [values[v].location for v in entry.arguments if isinstance(values[v], StateVersionValue)]
        domains = set(domain_list)
        region_domains[region.id] = domains
        if len(domains) != len(domain_list):
            error("duplicate_state_parameter", region.entry, "one parameter per state location")
        for block in region.blocks:
            carried = [values[v].location for v in block.arguments if isinstance(values[v], StateVersionValue)]
            if set(carried) != domains or len(carried) != len(domains):
                error("state_parameters", block.id, "all blocks must carry exactly the region state domains")
        for port in region.exits:
            carried = [t.location for t in port.types if t.kind is ValueKind.STATE]
            if set(carried) != domains or len(carried) != len(domains):
                error("state_exit", region.id, "every exit must return all state domains exactly once")

    def reference_binding(actual, formal, path):
        if not isinstance(actual, ReferenceValue) or not isinstance(formal, ReferenceValue):
            return
        if formal.targets is not None:
            if actual.targets is None or not set(actual.targets).issubset(formal.targets):
                error("reference_binding", path, "actual targets exceed formal reference targets")
        if (formal.selector.kind is not FootprintKind.UNKNOWN
                and actual.selector != formal.selector):
            error("reference_selector", path, "port binding cannot change a known reference selector")
        if formal.referent_identity is not None and actual.referent_identity != formal.referent_identity:
            error("reference_identity", path, "actual reference does not satisfy declared identity")

    for block in blocks.values():
        current = {values[v].location: v for v in block.arguments if isinstance(values[v], StateVersionValue)}
        for operation_id in block.operations:
            operation = operations[operation_id]
            own_uses = {use.id: use for use in operation.uses}
            for use in operation.uses:
                value = values[use.value]
                if isinstance(value, StateVersionValue) and current.get(value.location) != value.id:
                    error("stale_state", use.id, "use must read the current version of this block's state")
            consumed_state = set()
            defined_state = set()
            accessed = set()
            referenced_accesses = {}
            for access in operation.accesses:
                if access.location not in locations:
                    error("missing_access_location", operation.id, str(access.location))
                    continue
                if access.location in accessed:
                    error("duplicate_state_access", operation.id, "one access summary per location and operation")
                accessed.add(access.location)
                check_footprint(access.footprint, access.location, operation.id)
                before = own_uses.get(access.before)
                if before is None:
                    error("access_use", operation.id, "access must reference an owned input use")
                else:
                    consumed_state.add(access.before)
                    before_value = values[before.value]
                    role = UseRole.STATE_ORDER if access.full_overwrite else UseRole.STATE_CONTENT
                    if (not isinstance(before_value, StateVersionValue)
                            or before_value.location != access.location or before.role is not role):
                        error("access_state", operation.id, "access location, version and content/order role disagree")
                if access.mode in (AccessMode.READ, AccessMode.READ_WRITE) and Behavior.READ not in operation.behaviors:
                    error("read_behavior", operation.id, "read access requires READ behavior")
                if access.mode in (AccessMode.WRITE, AccessMode.READ_WRITE):
                    if Behavior.WRITE not in operation.behaviors:
                        error("write_behavior", operation.id, "write access requires WRITE behavior")
                    after = values.get(access.after)
                    if (not isinstance(after, StateVersionValue) or after.location != access.location
                            or access.after not in operation.results):
                        error("access_result", operation.id, "write must define the next version of its location")
                    else:
                        defined_state.add(access.after)
                        current[access.location] = access.after
                if access.reference is not None:
                    ref_use = own_uses.get(access.reference)
                    ref = values.get(ref_use.value) if ref_use is not None else None
                    if not isinstance(ref, ReferenceValue):
                        error("access_reference", operation.id, "access reference must be an owned reference use")
                    else:
                        referenced_accesses.setdefault(ref.id, set()).add(access.location)
                        if ref.targets is not None and access.location not in ref.targets:
                            error("alias_target", operation.id, "access contradicts known reference targets")
                        covered = covers(ref.selector, access.footprint, access.location)
                        if covered is False:
                            error("alias_footprint", operation.id, "access exceeds known reference selection")
                        if covered is None and operation.effects_complete:
                            error("incomplete_alias", operation.id, "unknown reference range cannot certify complete access")
            if operation.effects_complete:
                for reference_id, targets in referenced_accesses.items():
                    ref = values[reference_id]
                    if ref.targets is None or not set(ref.targets).issubset(targets):
                        error("incomplete_alias", operation.id, "complete access requires covering possible alias targets")

            is_invoke = (operation.terminator is not None
                         and operation.terminator.kind is TerminatorKind.INVOKE)
            if is_invoke:
                argument_uses = {uid: own_uses[uid] for uid in operation.invoke_arguments}
                input_domains = {values[use.value].location for use in argument_uses.values()
                                 if isinstance(values[use.value], StateVersionValue)}
                signatures = {signature.kind: signature for signature in operation.completions}
                for use in argument_uses.values():
                    if isinstance(values[use.value], StateVersionValue):
                        consumed_state.add(use.id)
                for edge in operation.terminator.successors:
                    produced_domains = []
                    for actual, formal in zip(edge.arguments, blocks[edge.block].arguments):
                        formal_value = values[formal]
                        if isinstance(formal_value, StateVersionValue) and isinstance(actual, CompletionResult):
                            produced_domains.append(formal_value.location)
                            if formal_value.location not in input_domains:
                                error("completion_state_input", operation.id,
                                      "produced state needs the current location as an invoke operand")
                        elif isinstance(actual, UseID) and isinstance(values[own_uses[actual].value], StateVersionValue):
                            consumed_state.add(actual)
                    if not operation.effects_complete and set(produced_domains) != region_domains[block_region[block.id]]:
                        error("completion_unknown_state", operation.id,
                              "unknown effects must produce each state domain on both completion paths")
                if operation.callee is not None:
                    callee = regions[operation.callee]
                    formals = blocks[callee.entry].arguments
                    if len(formals) != len(operation.invoke_arguments):
                        error("invoke_callee_arity", operation.id, "invoke argument count differs from callee interface")
                    for actual, formal in zip(operation.invoke_arguments, formals):
                        actual_value = values[own_uses[actual].value]
                        if value_type(actual_value) != value_type(values[formal]):
                            error("invoke_callee_type", actual, "invoke parameter type differs from callee interface")
                        reference_binding(actual_value, values[formal], actual)
                    callee_types = {}
                    for port in callee.exits:
                        if port.kind in callee_types:
                            error("invoke_callee_exits", operation.id, "one interface per completion kind is required")
                        callee_types[port.kind] = port.types
                    if callee_types != {kind: signature.types for kind, signature in signatures.items()}:
                        error("invoke_callee_exits", operation.id, "callee completion interfaces differ from invocation")

            if operation.id in drives and type(operation.terminator) is BodyDriveTerminator:
                drive = drives[operation.id]
                input_domains = {
                    values[own_uses[item.source].value].location
                    for item in drive.state_inputs
                    if item.source in own_uses
                    and isinstance(values[own_uses[item.source].value], StateVersionValue)
                }
                for edge in operation.terminator.successors:
                    for actual, formal in zip(edge.arguments, blocks[edge.block].arguments):
                        value = values[formal]
                        if (isinstance(value, StateVersionValue)
                                and isinstance(actual, BodyDriveResult)
                                and value.location not in input_domains):
                            error("driver_state_input", operation.id,
                                  "produced body state requires its current location as a drive input")

            if operation.callee is not None and not is_invoke:
                callee = regions[operation.callee]
                if Behavior.CONTROL not in operation.behaviors:
                    error("call_behavior", operation.id, "call requires CONTROL")
                if operation.terminator is not None or operation.accesses:
                    error("call_access", operation.id, "N1 call state transitions are defined by its interface")
                if len(callee.exits) != 1 or callee.exits[0].kind is not ExitKind.NORMAL:
                    error("unsupported_call_exit", operation.id, "N1 direct call requires one normal exit")
                    continue
                formals = blocks[callee.entry].arguments
                if len(operation.call_arguments) != len(formals):
                    error("call_arity", operation.id, "call argument count mismatch")
                if len(set(operation.call_arguments)) != len(operation.call_arguments):
                    error("call_binding", operation.id, "call inputs need distinct use sites")
                if set(operation.call_arguments) != set(own_uses):
                    error("call_binding", operation.id, "each direct call input must bind one callee parameter")
                for actual, formal in zip(operation.call_arguments, formals):
                    use = own_uses.get(actual)
                    if use is None:
                        error("call_binding", operation.id, "actual must be an owned input use")
                        continue
                    actual_value, formal_value = values[use.value], values[formal]
                    if value_type(actual_value) != value_type(formal_value):
                        error("call_type", actual, "actual and formal types differ")
                    reference_binding(actual_value, formal_value, actual)
                    if isinstance(actual_value, StateVersionValue):
                        consumed_state.add(actual)
                        if use.role is not UseRole.STATE_CONTENT:
                            error("call_state_role", actual,
                                  "N1 calls preserve content dependence until callee overwrite summaries are verified")
                exit_types = callee.exits[0].types
                if len(operation.results) != len(exit_types):
                    error("call_results", operation.id, "result count differs from callee interface")
                for result, expected in zip(operation.results, exit_types):
                    value = values[result]
                    if value_type(value) != expected:
                        error("call_result_type", result, "result type differs from callee exit")
                    if isinstance(value, StateVersionValue):
                        if value.location not in current:
                            error("call_state_domain", result, "callee cannot introduce unbound caller state")
                        current[value.location] = result
                        defined_state.add(result)
                    elif isinstance(value, ReferenceValue) and (
                            value.targets is not None or value.referent_identity is not None
                            or value.selector.kind is not FootprintKind.UNKNOWN):
                        error("unsupported_call_reference_summary", result,
                              "N1 call reference results must remain unknown until a return summary is verified")
            elif operation.call_arguments:
                error("unbound_call", operation.id, "call arguments require a callee")

            if operation.terminator is not None:
                consumed_state.update(use.id for use in operation.uses
                                      if isinstance(values[use.value], StateVersionValue))
                for edge in operation.terminator.successors:
                    for actual, formal in zip(edge.arguments, blocks[edge.block].arguments):
                        source = saved_actual_use(operation, actual)
                        if source is not None:
                            reference_binding(values[own_uses[source].value], values[formal], source)
            actual_state_uses = {use.id for use in operation.uses if isinstance(values[use.value], StateVersionValue)}
            if actual_state_uses != consumed_state:
                error("unaccounted_state_use", operation.id, "state inputs require access, call or control bindings")
            actual_state_results = {v for v in operation.results if isinstance(values[v], StateVersionValue)}
            if actual_state_results != defined_state:
                error("unaccounted_state_result", operation.id, "state results require a write or callee interface")

    for edge in graph.ordering:
        if edge.before not in operations or edge.after not in operations:
            error("order_endpoint", "ordering", "order endpoint does not exist")
            continue
        first, second = operation_block[edge.before], operation_block[edge.after]
        if block_region[first] != block_region[second]:
            error("order_region", "ordering", "N1 order must remain inside one region")
        elif (first not in dominators[second]
              or (first == second and positions[edge.before] >= positions[edge.after])):
            error("order_direction", "ordering", "order must agree with mandatory control order")
    from .binding_validation import validate_bindings
    for issue in validate_bindings(graph):
        error(issue.code, issue.path, issue.message)
    if not issues:
        from .control_validation import control_errors
        for code, path, message in control_errors(graph):
            error(code, path, message)
    if not issues:
        from .cleanup_validation import analyze_cleanup
        cleanup_issues, cleanup_facts = analyze_cleanup(
                graph, operation_blocks=operation_block, dominators=dominators)
        for code, path, message in cleanup_issues:
            error(code, path, message)
    if not issues:
        from .resumption_validation import analyze_resumption
        resumption_issues, resumption_facts = analyze_resumption(
                graph, operation_blocks=operation_block, region_domains=region_domains,
                incoming_edges=incoming_edges)
        for code, path, message in resumption_issues:
            error(code, path, message)
    if not issues:
        from .driver_validation import driver_errors
        for code, path, message in driver_errors(
                graph, operation_blocks=operation_block, region_domains=region_domains,
                incoming_edges=incoming_edges):
            error(code, path, message)
    if not issues:
        from .provider_validation import provider_errors
        for code, path, message in provider_errors(
                graph, {op: block_region[block] for op, block in operation_block.items()}, uses):
            error(code, path, message)
    if not issues:
        from .native_validation import native_errors
        for code, path, message in native_errors(graph):
            error(code, path, message)
    if not issues and _cleanup_facts is not None:
        _cleanup_facts.append(cleanup_facts)
    if not issues and _resumption_facts is not None:
        _resumption_facts.append(resumption_facts)
    return tuple(issues)


def require_valid(graph: ProgramGraph) -> None:
    issues = validate(graph)
    if issues:
        raise ValueError("; ".join(f"{issue.code} at {issue.path}: {issue.message}" for issue in issues))


__all__ = ["ValidationIssue", "validate", "require_valid"]
