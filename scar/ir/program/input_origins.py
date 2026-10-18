"""Bounded static source routes for canonical program input Uses.

The result is a read-only recipe over original Values, Uses, results and CFG
edges. It keeps each possible route separate and never creates a second
producer/use/state graph or claims a runtime call, source match, object
identity, or transformation.
"""
from __future__ import annotations

from types import MappingProxyType

from scar.ir.execution.validity_budget import ValidityBudget

from .control import PendingPayload
from .drivers import BodyDriveResult, BodyResume, BodyStart
from .ids import OperationID, UseID
from .literal_sources import ExactLiteralOrigin
from .model import (
    BlockArgument, CompletionResult, DataValue, InvokeLiteralResult,
    LiteralOrigin, OperationResult, ProgramGraph, ProtocolValue,
    ReferenceValue, StateVersionValue, TerminatorKind,
)
from .protocol_flow import ProtocolFlow
from .protocols import OwnedUse
from .resumption import ResumeInput, SavedInput, SuspendTerminator, saved_actual_use
from .structured import ControlEdgeReference


def _exact(value, expected, name):
    if type(value) is not expected:
        raise TypeError(f"{name} must be exact {expected.__name__}")


def _positive(value, name):
    _exact(value, int, name)
    if value < 1:
        raise ValueError(f"{name} must be positive")


def input_origins(graph: ProgramGraph, operation_id: OperationID, use_id: UseID,
                  *, budget: int = 4096) -> dict:
    """Derive bounded, independent source recipes for one exact owned Use.

    This convenience entry validates the graph once by building ProgramIndex.
    Prepared query paths should call :func:`_input_origins` with their existing
    index and shared validity budget instead of rebuilding validation state.
    """
    from .queries import ProgramIndex

    _exact(graph, ProgramGraph, "graph")
    _exact(operation_id, OperationID, "operation_id")
    _exact(use_id, UseID, "use_id")
    _positive(budget, "budget")
    index = ProgramIndex(graph)
    return _input_origins(index, operation_id, use_id,
                          accounting=ValidityBudget(budget))


def _input_origins(index, operation_id: OperationID, use_id: UseID,
                   *, accounting: ValidityBudget) -> dict:
    """Trace one exact Use over a previously validated ProgramIndex."""
    return _input_origins_with_flow(index, operation_id, use_id,
                                    accounting=accounting, _copy_flow=None)


def _build_origin_route_indexes(index):
    """Build reverse indexes over the original ProgramIndex records once."""
    graph = index.graph
    all_uses = {identity: (site.operation, site.use)
                for identity, site in index._uses.items()}
    callers_by_region, incoming = {}, {block_id: [] for block_id in index._block_records}
    operation_region = {
        identity: index._blocks[block]
        for identity, block in index._operation_blocks.items()
    }
    body_starts, body_resumes, raw_by_value, evaluations_by_site = {}, {}, {}, {}

    for candidate in graph.operations:
        if candidate.callee is not None:
            callers_by_region.setdefault(candidate.callee, []).append(candidate)
        if candidate.terminator is not None:
            for successor_index, successor in enumerate(candidate.terminator.successors):
                incoming.setdefault(successor.block, []).append(
                    (candidate, successor_index, successor))
    for drive in graph.body_drives:
        if type(drive.target) is BodyStart:
            body_starts.setdefault(drive.target.body, []).append(drive)
        elif type(drive.target) is BodyResume:
            body_resumes.setdefault((drive.target.suspend, drive.target.successor), []).append(drive)
    for row in graph.raw_driver_requests:
        raw_by_value.setdefault(row.value, []).append(row)
    for row in graph.literal_evaluations:
        evaluations_by_site.setdefault(row.site, []).append(row)

    # The values are private query indexes. Freeze nested collections so a
    # query cannot accidentally mutate the cache used by a later query.
    indexes = {
        "all_uses": MappingProxyType(all_uses),
        "block_by_id": index._block_records,
        "region_by_block": index._blocks,
        "operation_block": index._operation_blocks,
        "operation_region": MappingProxyType(operation_region),
        "callers_by_region": MappingProxyType({
            key: tuple(rows) for key, rows in callers_by_region.items()}),
        "incoming": MappingProxyType({key: tuple(rows) for key, rows in incoming.items()}),
        "body_starts": MappingProxyType({key: tuple(rows) for key, rows in body_starts.items()}),
        "body_resumes": MappingProxyType({key: tuple(rows) for key, rows in body_resumes.items()}),
        "raw_by_value": MappingProxyType({key: tuple(rows) for key, rows in raw_by_value.items()}),
        "evaluations_by_site": MappingProxyType({
            key: tuple(rows) for key, rows in evaluations_by_site.items()}),
    }
    counts = {
        "operations": len(index.operations),
        "values": len(index.values),
        "uses": len(all_uses),
        "regions": len(index.regions),
        "blocks": len(index._block_records),
        "static_call_sites": sum(map(len, indexes["callers_by_region"].values())),
        "incoming_edges": sum(map(len, indexes["incoming"].values())),
        "body_drives": len(graph.body_drives),
        "raw_driver_requests": len(graph.raw_driver_requests),
        "literal_evaluations": len(graph.literal_evaluations),
    }
    return indexes, counts


def _origin_route_indexes(index):
    """Return graph-scoped reverse indexes, cached on this validated index."""
    graph = index.graph
    cached = getattr(index, "_input_origin_route_indexes", None)
    if type(cached) is tuple and len(cached) == 3 and cached[0] is graph:
        return cached[1], cached[2], "REUSED"
    indexes, counts = _build_origin_route_indexes(index)
    index._input_origin_route_indexes = (graph, indexes, counts)
    return indexes, counts, "BUILT"


def _input_origins_with_flow(index, operation_id: OperationID, use_id: UseID,
                             *, accounting: ValidityBudget, _copy_flow, _guard=None) -> dict:
    """Private shared-budget/context implementation used by paired traces."""
    from .queries import InstanceCaptureInput, ProgramIndex

    _exact(index, ProgramIndex, "index")
    _exact(operation_id, OperationID, "operation_id")
    _exact(use_id, UseID, "use_id")
    _exact(accounting, ValidityBudget, "accounting")

    graph = index.graph
    operations, values = index.operations, index.values
    operation = operations.get(operation_id)
    if operation is None:
        raise KeyError(operation_id)
    use_site = index._uses.get(use_id)
    if use_site is None or use_site.operation != operation_id:
        raise KeyError(f"{use_id} is not owned by {operation_id}")
    use = use_site.use
    value = values.get(use.value)
    if value is None:
        raise KeyError(use.value)

    # Reuse the original ProgramIndex ownership maps and cache the additional
    # reverse indexes on this immutable graph index. The cache records which
    # query paid the preparation cost and the source-table sizes it scanned.
    (route_indexes, route_index_counts,
     route_index_cache) = _origin_route_indexes(index)
    all_uses = route_indexes["all_uses"]
    block_by_id = route_indexes["block_by_id"]
    region_by_block = route_indexes["region_by_block"]
    operation_block = route_indexes["operation_block"]
    operation_region = route_indexes["operation_region"]
    callers_by_region = route_indexes["callers_by_region"]
    incoming = route_indexes["incoming"]
    body_starts = route_indexes["body_starts"]
    body_resumes = route_indexes["body_resumes"]
    raw_by_value = route_indexes["raw_by_value"]
    evaluations_by_site = route_indexes["evaluations_by_site"]

    copy_flow = (ProtocolFlow(graph, budget=accounting)
                 if _copy_flow is None else _copy_flow)
    if copy_flow.graph is not graph or copy_flow.budget is not accounting:
        raise ValueError("copy flow must share this ProgramIndex graph and accounting")
    guard_edges = copy_flow.selected_edges(_guard)
    guard_ambiguity = copy_flow.selection_ambiguity(guard_edges)
    guard_sources = {edge.operation: edge.successor_index for edge in guard_edges}
    guard_targets = {operations[edge.operation].terminator.successors[edge.successor_index].block:
                     (edge.operation, edge.successor_index) for edge in guard_edges}

    def fresh(source, target):
        relevant = copy_flow.selected_edges(guard_edges, region=operation_region.get(target.operation)) or None
        return (copy_flow.forwards(source, target) if relevant is None else
                copy_flow.forwards(source, target, guard=relevant))
    recipes, gaps, pending, missing_routes = [], [], [], []
    if guard_ambiguity is not None:
        gaps.append({**guard_ambiguity, "message": "distinct incoming visits cannot be flattened into one source route"})
    cursor = None

    def gap(code, message, **details):
        return {"code": code, "message": message, **details}

    def missing(item):
        # An alternative with no emitted recipe must remain in the AND
        # denominator. Ordinary occurrence/identity conditions are separate.
        gaps.append(item)
        missing_routes.append(item)

    def spend(kind, path):
        if accounting.truncated:
            return False
        return accounting.spend(kind, 1, f"input_origins.{path}")

    def emit(kind, source_value, origin, *, producer=None, boundary=None,
             path_back=(), route_gaps=(), freshness=None, freshness_target=None,
             source_port=None):
        nonlocal cursor
        path = tuple(reversed(path_back))
        local_gaps = list(route_gaps)
        if any(step.get("kind") == "CFG_COPY" for step in path
               if type(step) is dict):
            local_gaps.append(gap(
                "cfg_visit_unselected",
                "the original CFG route is preserved, but no dynamic visit or loop iteration is selected"))
        if freshness is False:
            local_gaps.append(gap(
                "producer_not_current_at_use",
                "ProtocolFlow does not prove this producer value must reach the exact original Use",
                producer=None if producer is None else producer.id))
        elif freshness is None and type(origin) in (OperationResult, InvokeLiteralResult):
            local_gaps.append(gap(
                "producer_currentness_unresolved",
                "fresh-copy currentness is unknown for this producer-to-Use route"))

        raw_rows = tuple(raw_by_value.get(source_value.id, ()))
        raw_details = []
        metadata_complete = cursor is None
        for definition_index, definition in enumerate(raw_rows):
            if not metadata_complete:
                break
            if not spend("raw_definitions", "raw_definitions"):
                if cursor is None:
                    cursor = {"phase": "raw_definitions", "value": source_value.id,
                              "candidate_index": definition_index,
                              "candidate_total": len(raw_rows),
                              "pending_raw_definitions": len(raw_rows) - definition_index,
                              "pending_tasks": len(pending)}
                metadata_complete = False
                break
            operand_rows = []
            for operand_index, operand in enumerate(definition.operands):
                if not spend("raw_operands", "raw_request_operands"):
                    raw_details.append({
                        "definition": definition,
                        "pack_operation": producer if type(origin) is OperationResult else None,
                        "operands": tuple(operand_rows),
                        "pending_operands": len(definition.operands) - operand_index,
                    })
                    if cursor is None:
                        cursor = {"phase": "raw_request_operands", "value": source_value.id,
                                  "definition": definition, "candidate_index": operand_index,
                                  "candidate_total": len(definition.operands),
                                  "pending_raw_operands": len(definition.operands) - operand_index,
                                  "pending_raw_definitions": len(raw_rows) - definition_index - 1,
                                  "pending_tasks": len(pending)}
                    metadata_complete = False
                    break
                owner = all_uses.get(operand)
                operand_rows.append({
                    "operation": None if owner is None else operations.get(owner[0]),
                    "use": None if owner is None else owner[1],
                    "use_id": operand,
                })
            pack = producer if type(origin) is OperationResult else None
            if metadata_complete or len(operand_rows) == len(definition.operands):
                raw_details.append({"definition": definition, "pack_operation": pack,
                                    "operands": tuple(operand_rows),
                                    "pending_operands": 0})
            if not metadata_complete:
                break

        if source_port is None and type(origin) in (OperationResult, InvokeLiteralResult):
            source_port = origin
        literal_rows = []
        literal_sources = (() if source_port is None else
                           tuple(evaluations_by_site.get(source_port, ())))
        if metadata_complete:
            for evaluation_index, evaluation in enumerate(literal_sources):
                if not spend("literal_evaluations", "literal_evaluations"):
                    if cursor is None:
                        cursor = {"phase": "literal_evaluations", "value": source_value.id,
                                  "source_port": source_port,
                                  "candidate_index": evaluation_index,
                                  "candidate_total": len(literal_sources),
                                  "pending_literal_evaluations": len(literal_sources) - evaluation_index,
                                  "pending_tasks": len(pending)}
                    metadata_complete = False
                    break
                literal_rows.append(evaluation)
        recipes.append({
            "kind": kind,
            "leaf": source_value,
            "origin": origin,
            "producer": producer,
            "boundary": boundary,
            "path": path,
            "raw_requests": tuple(raw_details),
            "literal_evaluations": tuple(literal_rows),
            "freshness": freshness,
            "freshness_oracle": "ProtocolFlow.forwards" if freshness is not None else None,
            "freshness_target": freshness_target,
            "freshness_scope": ("PRODUCER_TO_EXACT_LOCAL_USE"
                                if freshness_target is not None else "NOT_CHECKED"),
            "freshness_is_runtime_identity": False,
            "gaps": tuple(local_gaps),
            "source_runtime_verified": False,
            "runtime_identity_verified": False,
            "value_identity_verified": False,
            "transformation_authorized": False,
        })

    def schedule(task, *, phase, at, index_number, total):
        nonlocal cursor
        if not spend("candidates", phase):
            cursor = {"phase": phase, "at": at, "candidate_index": index_number,
                      "candidate_total": total,
                      "pending_candidates": max(0, total - index_number),
                      "pending_tasks": len(pending)}
            return False
        pending.append(task)
        return True

    first = (value.id, operation.id, use.id, (), frozenset(), ())
    schedule(first, phase="start", at=use.id, index_number=0, total=1)

    while pending and cursor is None and guard_ambiguity is None:
        task = pending.pop()
        current_id, anchor_op_id, anchor_use_id, path_back, trail, route_gaps = task
        if not spend("nodes", current_id):
            cursor = {"phase": "trace", "value": current_id,
                      "pending_candidates": 0, "pending_tasks": len(pending) + 1}
            break
        current = values.get(current_id)
        anchor = operations.get(anchor_op_id)
        anchor_pair = all_uses.get(anchor_use_id)
        if current is None or anchor is None or anchor_pair is None:
            missing(gap("source_port_missing", "route references a missing original row",
                            value=current_id, operation=anchor_op_id, use=anchor_use_id))
            continue
        if anchor_pair[0] != anchor_op_id:
            missing(gap("source_use_owner_mismatch", "route anchor Use is not owned by its operation",
                            operation=anchor_op_id, use=anchor_use_id))
            continue
        if current_id in trail:
            emit("STATIC_CYCLE", current, current.origin,
                 path_back=path_back,
                 route_gaps=(*route_gaps, gap(
                     "static_route_cycle", "route revisits a canonical ValueID; dynamic iteration is unresolved",
                     value=current_id)))
            continue
        next_trail = trail | {current_id}
        origin = current.origin

        if type(origin) is LiteralOrigin:
            local = route_gaps
            if type(current) is ReferenceValue and origin.value is not None:
                local = (*local, gap("reference_literal_not_none",
                                     "a literal ReferenceValue source must be exact None",
                                     value=current.id))
            emit("LITERAL_ORIGIN", current, origin, path_back=path_back,
                 route_gaps=local)
            continue
        if type(origin) is ExactLiteralOrigin:
            if type(current) is not DataValue:
                route_gaps = (*route_gaps, gap(
                    "exact_literal_not_data", "ExactLiteralOrigin is valid only for DataValue",
                    value=current.id))
                emit("INVALID_EXACT_LITERAL_ORIGIN", current, origin,
                     path_back=path_back, route_gaps=route_gaps)
            else:
                emit("EXACT_LITERAL_ORIGIN", current, origin,
                     path_back=path_back, route_gaps=route_gaps)
            continue
        if type(origin) is OperationResult:
            producer = operations.get(origin.operation)
            if producer is None or origin.index >= len(producer.results):
                missing(gap("producer_port_missing", "OperationResult is absent",
                                value=current.id, origin=origin))
                continue
            if producer.results[origin.index] != current.id:
                missing(gap("producer_port_mismatch", "OperationResult selects another ValueID",
                                value=current.id, origin=origin))
                continue
            freshness = None
            freshness_target = None
            if operation_region.get(producer.id) == operation_region.get(anchor.id):
                freshness_target = OwnedUse(anchor.id, anchor_use_id)
                try:
                    freshness = fresh(origin, freshness_target)
                except (TypeError, ValueError, KeyError):
                    freshness = None
            if freshness is None and accounting.truncated and cursor is None:
                cursor = {"phase": "fresh_copy", "producer": producer.id,
                          "consumer": anchor.id, "use": anchor_use_id,
                          "pending_candidates": 0, "pending_tasks": len(pending)}
            emit("OPERATION_RESULT", current, origin, producer=producer,
                 path_back=path_back, route_gaps=route_gaps, freshness=freshness,
                 freshness_target=freshness_target)
            continue
        if type(origin) is not BlockArgument:
            missing(gap("unsupported_origin", "origin has no supported static reverse recipe",
                            value=current.id, origin=origin))
            continue

        block = block_by_id.get(origin.block)
        region_id = region_by_block.get(origin.block)
        if block is None or region_id is None or origin.index >= len(block.arguments):
            missing(gap("block_argument_missing", "BlockArgument port is absent",
                            value=current.id, origin=origin))
            continue
        if block.arguments[origin.index] != current.id:
            missing(gap("block_argument_mismatch", "BlockArgument ordinal selects another ValueID",
                            value=current.id, origin=origin))
            continue

        region = index.regions[region_id]
        if origin.block == region.entry:
            static_callers = callers_by_region.get(region_id, ())
            start_drives = body_starts.get(region_id, ())
            total = len(static_callers) + len(start_drives)
            if not total:
                local = (*route_gaps, gap(
                    "external_entry_unmapped",
                    "no supplied CALL/INVOKE or BodyStart binds this region entry",
                    region=region_id, formal_index=origin.index,
                    scope="SUPPLIED_STATIC_CALLERS_ONLY"))
                emit("EXTERNAL_ENTRY", current, origin, path_back=path_back,
                     route_gaps=local)
                continue
            candidate = 0
            for caller in static_callers:
                if not spend("candidates", "callers"):
                    cursor = {"phase": "callers", "at": current.id,
                              "candidate_index": candidate, "candidate_total": total,
                              "pending_candidates": total - candidate,
                              "pending_tasks": len(pending)}
                    break
                arguments = (caller.invoke_arguments if caller.terminator is not None
                             and caller.terminator.kind is TerminatorKind.INVOKE
                             else caller.call_arguments)
                if origin.index >= len(arguments):
                    missing(gap("call_actual_missing", "caller lacks this formal ordinal",
                                    caller=caller.id, callee=region_id,
                                    formal_index=origin.index))
                    candidate += 1
                    continue
                actual_id = arguments[origin.index]
                actual_pair = all_uses.get(actual_id)
                if actual_pair is None or actual_pair[0] != caller.id:
                    missing(gap("call_actual_unowned", "actual is not an owned Use of caller",
                                    caller=caller.id, callee=region_id, use=actual_id))
                    candidate += 1
                    continue
                formal_values = index.entry_arguments(region_id)
                formal = formal_values[origin.index]
                call_kind = ("INVOKE" if caller.terminator is not None
                             and caller.terminator.kind is TerminatorKind.INVOKE else "CALL")
                environment_call = (index.environment_call(caller.id)
                                    if index.environment_interface(region_id) is not None else None)
                step = {"kind": "CALL_ACTUAL_TO_FORMAL", "call_kind": call_kind,
                        "caller": caller, "callee": region_id, "ordinal": origin.index,
                        "actual": actual_pair[1], "formal": formal,
                        "environment_call": environment_call}
                pending.append((actual_pair[1].value, caller.id, actual_id,
                                (*path_back, step), next_trail,
                                (*route_gaps, gap(
                                    "static_call_occurrence_unlinked",
                                    "positional call mapping is static and does not select a dynamic activation",
                                    caller=caller.id, callee=region_id))))
                candidate += 1
            if cursor is not None:
                break

            for drive in start_drives:
                if not spend("candidates", "body_start"):
                    cursor = {"phase": "body_start", "at": current.id,
                              "candidate_index": candidate, "candidate_total": total,
                              "pending_candidates": total - candidate,
                              "pending_tasks": len(pending)}
                    break
                binding = next((item for item in index.drive_input_bindings(drive.operation)
                                if item.formal == current.id), None)
                if binding is None:
                    missing(gap("body_start_binding_missing",
                                    "BodyStart has no derived source for this formal",
                                    drive=drive.operation, formal=current.id))
                    candidate += 1
                    continue
                if type(binding.source) is InstanceCaptureInput:
                    step = {"kind": "BODY_START_INSTANCE_CAPTURE",
                            "drive": operations[drive.operation],
                            "formal": current, "instance": binding.source.instance}
                    emit("BODY_START_CAPTURE", current, origin, boundary=step,
                         path_back=(*path_back, step), route_gaps=(*route_gaps, gap(
                             "body_start_instance_unresolved",
                             "the frame projection is known but no current Create instance is selected",
                             drive=drive.operation, formal=current.id)))
                else:
                    source = binding.source
                    step = {"kind": "BODY_START_STATE_INPUT", "drive": operations[drive.operation],
                            "formal": current, "actual": source}
                    pending.append((source.use.value, source.operation, source.use.id,
                                    (*path_back, step), next_trail,
                                    (*route_gaps, gap(
                                        "body_start_occurrence_unlinked",
                                        "BodyStart binding is static; dynamic instance occurrence is not selected",
                                        drive=drive.operation))))
                candidate += 1
            if cursor is not None:
                break
            continue

        predecessors = incoming.get(block.id, ())
        if not predecessors:
            local = (*route_gaps, gap("block_argument_has_no_incoming_edge",
                                      "non-entry argument has no supplied predecessor",
                                      block=block.id, value=current.id))
            emit("UNMAPPED_BLOCK_ARGUMENT", current, origin,
                 path_back=path_back, route_gaps=local)
            continue
        total = len(predecessors)
        for candidate, (pred, successor_index, successor) in enumerate(predecessors):
            if not spend("candidates", "cfg_predecessors"):
                cursor = {"phase": "cfg_predecessors", "at": current.id,
                          "candidate_index": candidate, "candidate_total": total,
                          "pending_candidates": total - candidate,
                          "pending_tasks": len(pending)}
                break
            if ((block.id in guard_targets and guard_targets[block.id] != (pred.id, successor_index))
                    or pred.id in guard_sources and guard_sources[pred.id] != successor_index):
                continue
            if origin.index >= len(successor.arguments):
                missing(gap("cfg_actual_missing", "incoming successor lacks the formal ordinal",
                                operation=pred.id, successor_index=successor_index,
                                formal_index=origin.index))
                continue
            actual = successor.arguments[origin.index]
            edge_step = {"kind": "CFG_COPY", "operation": pred,
                         "successor_index": successor_index,
                         "source_block": operation_block.get(pred.id),
                         "target_block": block.id, "formal": current,
                         "actual": actual}
            if type(actual) is UseID:
                actual_pair = all_uses.get(actual)
                if actual_pair is None or actual_pair[0] != pred.id:
                    missing(gap("cfg_actual_unowned", "edge actual is not owned by its terminator",
                                    operation=pred.id, use=actual,
                                    successor_index=successor_index))
                    continue
                pending.append((actual_pair[1].value, pred.id, actual,
                                (*path_back, edge_step), next_trail, route_gaps))
            elif type(actual) is CompletionResult and pred.terminator.kind is TerminatorKind.INVOKE:
                port = InvokeLiteralResult(ControlEdgeReference(pred.id, successor_index), actual)
                freshness_target = None
                freshness = None
                if operation_region.get(pred.id) == operation_region.get(anchor.id):
                    freshness_target = OwnedUse(anchor.id, anchor_use_id)
                    try:
                        freshness = fresh(port, freshness_target)
                    except (TypeError, ValueError, KeyError):
                        freshness = None
                local_gaps = (*route_gaps, gap(
                    "invoke_completion_dynamic_unlinked",
                    "this is the original INVOKE completion port, not a selected dynamic execution",
                    operation=pred.id, successor_index=successor_index))
                emit("INVOKE_COMPLETION", current, port, producer=pred,
                     boundary=edge_step, path_back=(*path_back, edge_step),
                     route_gaps=local_gaps, freshness=freshness,
                     freshness_target=freshness_target, source_port=port)
            elif type(actual) in (ResumeInput, SavedInput):
                if type(pred.terminator) is not SuspendTerminator:
                    missing(gap("resume_input_without_suspend",
                                    "resume slot projection is not on SuspendTerminator",
                                    operation=pred.id, successor_index=successor_index))
                    continue
                if type(actual) is ResumeInput:
                    matching = body_resumes.get((pred.id, successor_index), ())
                    matched = 0
                    for drive_index, drive in enumerate(matching):
                        if not spend("candidates", "resume_drives"):
                            cursor = {"phase": "resume_drives", "suspend": pred.id,
                                      "successor_index": successor_index,
                                      "candidate_index": drive_index,
                                      "candidate_total": len(matching),
                                      "pending_candidates": len(matching) - drive_index,
                                      "pending_tasks": len(pending)}
                            break
                        binding = next((item for item in index.drive_input_bindings(drive.operation)
                                        if item.formal == current.id), None)
                        if binding is None:
                            continue
                        matched += 1
                        drive_step = {"kind": "RESUME_INPUT_BODY_DRIVE",
                                      "suspend": pred.id, "successor_index": successor_index,
                                      "resume_slot": actual.resume_slot,
                                      "drive": operations[drive.operation],
                                      "source": binding.source}
                        drive_gap = gap(
                            "resume_drive_occurrence_unlinked",
                            "the static Drive/Resume route does not select a dynamic suspension occurrence",
                            drive=drive.operation, suspend=pred.id)
                        if type(binding.source) is InstanceCaptureInput:
                            emit("RESUME_INSTANCE_CAPTURE", current, actual,
                                 boundary=drive_step,
                                 path_back=(*path_back, edge_step, drive_step),
                                 route_gaps=(*route_gaps, drive_gap))
                        else:
                            source = binding.source
                            pending.append((source.use.value, source.operation, source.use.id,
                                            (*path_back, edge_step, drive_step), next_trail,
                                            (*route_gaps, drive_gap)))
                    gaps.append(gap(
                        "resume_input_dynamic_unresolved",
                        "ResumeInput requires a selected dynamic drive source",
                        operation=pred.id, successor_index=successor_index,
                        resume_slot=actual.resume_slot, matching_drives=matched))
                    if matched == 0:
                        emit("RESUME_INPUT", current, actual,
                             path_back=(*path_back, edge_step),
                             route_gaps=(*route_gaps, gap(
                                 "resume_input_dynamic_unresolved",
                                 "no supplied BodyDrive binds this resume successor")))
                else:
                    saved_use = saved_actual_use(pred, actual)
                    found = all_uses.get(saved_use)
                    if found is None or found[0] != pred.id:
                        missing(gap("saved_input_use_unresolved",
                                        "SavedInput does not select an original Suspend Use",
                                        operation=pred.id, successor_index=successor_index,
                                        saved_slot=actual.saved_slot))
                        continue
                    saved_step = {"kind": "SAVED_SLOT_AT_SUSPEND", "suspend": pred.id,
                                  "successor_index": successor_index,
                                  "saved_slot": actual.saved_slot,
                                  "source_use": found[1]}
                    pending.append((found[1].value, pred.id, saved_use,
                                    (*path_back, edge_step, saved_step), next_trail,
                                    (*route_gaps, gap(
                                        "saved_resume_occurrence_unlinked",
                                        "saved source Use is exact but no later resume occurrence is selected",
                                        suspend=pred.id, successor_index=successor_index))))
            elif type(actual) is BodyDriveResult:
                emit("BODY_DRIVE_RESULT", current, actual, producer=pred,
                     boundary=edge_step, path_back=(*path_back, edge_step),
                     route_gaps=(*route_gaps, gap(
                         "body_drive_result_dynamic_unlinked",
                         "BodyDriveResult has no selected dynamic body outcome occurrence",
                         operation=pred.id, index=actual.index)))
            elif type(actual) is PendingPayload:
                emit("PENDING_PAYLOAD", current, actual, producer=pred,
                     boundary=edge_step, path_back=(*path_back, edge_step),
                     route_gaps=(*route_gaps, gap(
                         "pending_payload_dynamic_unlinked",
                         "PendingPayload has no selected dynamic pending value",
                         operation=pred.id, successor_index=successor_index)))
            else:
                missing(gap("cfg_source_kind_unresolved", "unsupported original edge input kind",
                                operation=pred.id, successor_index=successor_index,
                                actual=actual))
        if cursor is not None:
            break

    runtime_gaps = tuple(gaps) + tuple(
        item for recipe in recipes for item in recipe["gaps"])
    inventory_complete = (not missing_routes and guard_ambiguity is None
                          and cursor is None and not accounting.truncated)
    for recipe in recipes:
        recipe['origin_inventory_complete'] = inventory_complete
    return {
        "consumer": {"operation": operation, "use": use, "value": value},
        "recipes": tuple(recipes),
        "source_inventory_complete": inventory_complete,
        "missing_origin_routes": tuple(missing_routes),
        "gaps": runtime_gaps,
        "caller_scope": "SUPPLIED_STATIC_CALLERS_ONLY",
        "caller_scope_complete": False,
        "status": ("TRUNCATED" if cursor is not None or accounting.truncated else
                   "PARTIAL" if runtime_gaps else "DERIVED"),
        "cursor": cursor,
        "budget": {"limit": accounting.limit, "used": accounting.used,
                   "remaining": accounting.remaining, "truncated": accounting.truncated,
                   "costs": dict(accounting.costs)},
        "preparation": {"operations": len(operations), "values": len(values),
                         "uses": len(all_uses), "blocks": len(block_by_id),
                         "static_call_sites": route_index_counts["static_call_sites"],
                         "incoming_edges": route_index_counts["incoming_edges"],
                         "origin_route_index_cache": route_index_cache,
                         "origin_route_index_rows": dict(route_index_counts),
                         "copy_oracle": "ProtocolFlow.forwards"},
        "source_runtime_verified": False,
        "runtime_identity_verified": False,
        "value_identity_verified": False,
        "transformation_authorized": False,
    }


def _owned_use(index, value, name):
    from .queries import ProgramIndex
    _exact(index, ProgramIndex, "index")
    _exact(value, OwnedUse, name)
    value.__post_init__()
    operation = index.operations.get(value.operation)
    if operation is None:
        raise KeyError(value.operation)
    site = index._uses.get(value.use)
    if site is None or site.operation != value.operation:
        raise KeyError(f"{value.use} is not owned by {value.operation}")
    return operation, site.use


def _call_step_key(index, step):
    caller = step["caller"]
    caller_block = index._operation_blocks.get(caller.id)
    caller_region = None if caller_block is None else index._blocks.get(caller_block)
    actual = step["actual"]
    formal = step["formal"]
    return (caller.id, caller_region, step["callee"], step["ordinal"],
            actual.id, formal.id)


def _call_chain(index, source_region, path, target_region):
    """Validate and retain the exact static CALL/INVOKE chain in one recipe."""
    current = source_region
    keys = []
    for step in path:
        if step.get("kind") != "CALL_ACTUAL_TO_FORMAL":
            continue
        key = _call_step_key(index, step)
        if key[1] != current:
            return tuple(keys), False, current
        keys.append(key)
        current = step["callee"]
    return tuple(keys), current == target_region, current


def _cfg_edge_keys(path):
    return tuple((step["operation"].id, step["successor_index"],
                  step["source_block"], step["target_block"],
                  step["formal"].id, step["actual"])
                 for step in path if step.get("kind") == "CFG_COPY")


def _consumer_call_edges(index, operation, use):
    """Return every exact call slot using a consumer Use (duplicates included)."""
    if operation.callee is None:
        return ((),)
    invoke = (operation.terminator is not None
              and operation.terminator.kind is TerminatorKind.INVOKE)
    arguments = operation.invoke_arguments if invoke else operation.call_arguments
    formals = index.entry_arguments(operation.callee)
    caller_block = index._operation_blocks.get(operation.id)
    caller_region = None if caller_block is None else index._blocks.get(caller_block)
    return tuple((operation.id, caller_region, operation.callee, ordinal,
                  use.id, formals[ordinal].id)
                 for ordinal, actual in enumerate(arguments) if actual == use.id)


def paired_input_origins(index, left: OwnedUse, right: OwnedUse, *,
                         budget: int | None = None,
                         accounting: ValidityBudget | None = None) -> dict:
    """Join exact raw-request consumers to exact operand Uses conservatively.

    ``left`` is a Use carrying a raw request toward its consumer. ``right``
    must be the exact pack-operand Use named by that same request's
    RawRequestDefinition. This joins the raw pack record to its operand
    recipe; it does not join the operand to a separate admission-predicate
    input or establish a raw-request/``is None`` relation.
    Pairing is by the original definition and owned Use, then by complete
    static caller and CFG route keys. Equal ValueIDs, roles, or ordinals alone
    never form a pair. Results remain static recipes; dynamic activations and
    runtime identity are unproved.
    """
    from .queries import ProgramIndex

    _exact(index, ProgramIndex, "index")
    left_operation, left_use = _owned_use(index, left, "left")
    right_operation, right_use = _owned_use(index, right, "right")
    if accounting is None:
        budget = 4096 if budget is None else budget
        _positive(budget, "budget")
        accounting = ValidityBudget(budget)
    else:
        _exact(accounting, ValidityBudget, "accounting")
        if budget is not None:
            raise TypeError("pass budget or accounting, not both")

    graph = index.graph
    copy_flow = ProtocolFlow(graph, budget=accounting)
    left_view = _input_origins_with_flow(
        index, left.operation, left.use, accounting=accounting, _copy_flow=copy_flow)
    right_view = _input_origins_with_flow(
        index, right.operation, right.use, accounting=accounting, _copy_flow=copy_flow)
    pairs, gaps, cursor = [], [], None
    route_indexes, route_index_counts, route_index_cache = _origin_route_indexes(index)
    callers_by_region = route_indexes["callers_by_region"]

    left_consumer_call_edges = _consumer_call_edges(index, left_operation, left_use)
    for left_recipe_index, left_recipe in enumerate(left_view["recipes"]):
        if accounting.truncated:
            cursor = {"phase": "pair_recipes", "left_recipe_index": left_recipe_index,
                      "left_recipe_count": len(left_view["recipes"]),
                      "right_recipe_count": len(right_view["recipes"]),
                      "left_trace_cursor": left_view["cursor"],
                      "right_trace_cursor": right_view["cursor"],
                      "pair_enumeration_incomplete": True}
            break
        for raw_index, raw in enumerate(left_recipe["raw_requests"]):
            definition = raw["definition"]
            pack_operation = raw["pack_operation"]
            for operand_index, operand in enumerate(raw["operands"]):
                for right_recipe_index, right_recipe in enumerate(right_view["recipes"]):
                    if not accounting.spend("pair_candidates", 1,
                                            "input_origins.pair_candidates"):
                        cursor = {"phase": "pair_candidates",
                                  "left_recipe_index": left_recipe_index,
                                  "left_recipe_count": len(left_view["recipes"]),
                                  "raw_definition_index": raw_index,
                                  "raw_definition_count": len(left_recipe["raw_requests"]),
                                  "raw_operand_index": operand_index,
                                  "raw_operand_count": len(raw["operands"]),
                                  "right_recipe_index": right_recipe_index,
                                  "right_recipe_count": len(right_view["recipes"]),
                                  "pending_right_recipes_in_current_operand": (
                                      len(right_view["recipes"]) - right_recipe_index),
                                  "pending_operands_in_current_definition": (
                                      len(raw["operands"]) - operand_index - 1),
                                  "pending_definitions_in_current_recipe": (
                                      len(left_recipe["raw_requests"]) - raw_index - 1),
                                  "pending_left_recipes": (
                                      len(left_view["recipes"]) - left_recipe_index - 1),
                                  "left_trace_cursor": left_view["cursor"],
                                  "right_trace_cursor": right_view["cursor"]}
                        break
                    if (operand["operation"] is None or operand["use"] is None
                            or operand["operation"].id != right.operation
                            or operand["use"].id != right.use):
                        continue
                    if pack_operation is None:
                        gaps.append({"code": "raw_pack_producer_unresolved",
                                     "message": "raw request operand has no exact OperationResult pack producer",
                                     "definition": definition, "operand": right})
                        continue
                    if (left_recipe["producer"] is None
                            or left_recipe["producer"].id != pack_operation.id
                            or definition.value != left_recipe["leaf"].id
                            or pack_operation.id != right_operation.id
                            or definition.operands[operand_index] != right_use.id):
                        gaps.append({"code": "raw_pack_result_unlinked",
                                     "message": "raw definition is not the exact output of the traced pack producer",
                                     "definition": definition, "operand": right})
                        continue
                    pack_region = index._blocks[
                        index._operation_blocks[pack_operation.id]]
                    right_region = index._blocks[index._operation_blocks[right.operation]]
                    left_region = index._blocks[index._operation_blocks[left.operation]]
                    right_calls, right_contiguous, right_end = _call_chain(
                        index, right_recipe["leaf"].region, right_recipe["path"], right_region)
                    left_calls, left_contiguous, left_end = _call_chain(
                        index, left_recipe["leaf"].region, left_recipe["path"], left_region)
                    if (right_region != pack_region or left_recipe["leaf"].region != pack_region
                            or not right_contiguous or right_end != pack_region
                            or not left_contiguous or left_end != left_region):
                        gaps.append({"code": "raw_pack_caller_context_unresolved",
                                     "message": "the raw pack input and consumer routes do not join at the exact pack region",
                                     "definition": definition, "pack_operation": pack_operation,
                                     "right_calls": right_calls, "left_calls": left_calls})
                        continue
                    # A path starting inside a shared callee does not identify
                    # which outer CALL/INVOKE activation owned this raw pack.
                    # Only a chain rooted at the selected program entry, or a
                    # pack directly in that entry with no incoming caller, can
                    # form a conservative static context key here.
                    root_region = graph.root
                    pack_callers = tuple(callers_by_region.get(pack_region, ()))
                    route_rooted = (
                        (bool(right_calls) and right_calls[0][1] == root_region)
                        or (not right_calls and pack_region == root_region
                            and not pack_callers and bool(left_calls)
                            and left_calls[0][1] == root_region))
                    if not route_rooted:
                        gaps.append({"code": "raw_pack_caller_context_unresolved",
                                     "message": "the raw operand recipe does not contain a complete supplied CALL/INVOKE path from the program root to this pack activation",
                                     "definition": definition, "pack_operation": pack_operation,
                                     "right_calls": right_calls,
                                     "program_root": root_region,
                                     "pack_callers": tuple(row.id for row in pack_callers)})
                        continue
                    for consumer_call in left_consumer_call_edges:
                        pair_calls = (*right_calls, *left_calls, consumer_call)
                        pair_gaps = (*right_recipe["gaps"], *left_recipe["gaps"])
                        pairs.append({
                            "pairing_scope": "RAW_REQUEST_PACK_OPERAND_ONLY",
                            "raw_definition": definition,
                            "pack_operation": pack_operation,
                            "left_consumer": {"operation": left_operation, "use": left_use},
                            "right_operand": {"operation": right_operation, "use": right_use},
                            "left_recipe": left_recipe,
                            "right_recipe": right_recipe,
                            "caller_chain": pair_calls,
                            "caller_chain_segments": {
                                "operand_to_pack": right_calls,
                                "pack_to_consumer": left_calls,
                                "consumer_forward": consumer_call,
                            },
                            "caller_chain_scope": "SUPPLIED_STATIC_PATH_FROM_PROGRAM_ROOT",
                            "caller_chain_complete": False,
                            "cfg_edges": {"input_to_pack": _cfg_edge_keys(right_recipe["path"]),
                                          "pack_to_consumer": _cfg_edge_keys(left_recipe["path"])},
                            "pair_key": (left_operation.id, left_use.id,
                                         definition.value, pack_operation.id,
                                         right_operation.id, right_use.id,
                                         right_calls, left_calls, consumer_call,
                                         _cfg_edge_keys(right_recipe["path"]),
                                         _cfg_edge_keys(left_recipe["path"])),
                            "gaps": pair_gaps,
                            "source_runtime_verified": False,
                            "runtime_identity_verified": False,
                            "value_identity_verified": False,
                            "transformation_authorized": False,
                        })
                if cursor is not None:
                    break
            if cursor is not None:
                break
        if cursor is not None:
            break

    if not pairs and cursor is None:
        gaps.append({"code": "raw_operand_not_paired",
                     "message": "the right exact Use is not an operand of a traced left RawRequestDefinition",
                     "left": left, "right": right})
    if left_view["cursor"] is not None or right_view["cursor"] is not None:
        cursor = cursor or {"phase": "origin_trace",
                            "left_cursor": left_view["cursor"],
                            "right_cursor": right_view["cursor"],
                            "left_recipe_count": len(left_view["recipes"]),
                            "right_recipe_count": len(right_view["recipes"]),
                            "pair_enumeration_incomplete": True}
    trace_gaps = (*left_view["gaps"], *right_view["gaps"])
    all_gaps = tuple(gaps) + tuple(trace_gaps)
    return {
        "pairing_scope": "RAW_REQUEST_PACK_OPERAND_ONLY",
        "admission_predicate_pairing_supported": False,
        "left": left_view,
        "right": right_view,
        "pairs": tuple(pairs),
        "gaps": all_gaps,
        "caller_scope": "SUPPLIED_STATIC_CALLERS_ONLY",
        "caller_scope_complete": False,
        "status": ("TRUNCATED" if cursor is not None or accounting.truncated else
                   "PARTIAL" if all_gaps or left_view["gaps"] or right_view["gaps"] else "DERIVED"),
        "cursor": cursor,
        "budget": {"limit": accounting.limit, "used": accounting.used,
                   "remaining": accounting.remaining, "truncated": accounting.truncated,
                   "costs": dict(accounting.costs)},
        "preparation": {"origin_route_index_cache": route_index_cache,
                         "origin_route_index_rows": dict(route_index_counts)},
        "source_runtime_verified": False,
        "runtime_identity_verified": False,
        "value_identity_verified": False,
        "transformation_authorized": False,
    }


__all__ = ["input_origins", "paired_input_origins"]
