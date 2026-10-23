"""Derive a bounded Q ledger for explicit composition query scopes.

The scope is an analysis request, not an execution row. This module keeps the
original observation requirements, roots, and content reads as source
inventory; its derived ledger never replaces those canonical rows.
"""
from __future__ import annotations

from .common import EvidencePoint, Unresolved
from .composition import CompositionScope
from .coordinates import OccurrencePoint
from .content import ObservationConsumer
from .ids import BlockVisitID, OperationOccurrenceID, RegionActivationID, RunID
from .observations import RequiredEndpoint, RequiredOutput
from .validation import ExecutionIssue


def _contract_key(reference):
    artifact = reference.artifact
    # URI is a locator. Snapshot identity is the exact artifact tuple.
    return artifact.sha256, artifact.schema, artifact.size_bytes, reference.contract


def _scope_key(scope):
    return _contract_key(scope.contract), type(scope.owner), scope.owner


def validate_scopes(scopes):
    """Validate a query-scope tuple without consulting execution or artifacts."""
    if type(scopes) is not tuple:
        raise TypeError("composition scopes must be an exact tuple")
    seen = set()
    for scope in scopes:
        if type(scope) is not CompositionScope:
            raise TypeError("composition scopes must contain exact CompositionScope records")
        scope.__post_init__()
        key = _scope_key(scope)
        if key in seen:
            raise ValueError("composition scope is duplicated")
        seen.add(key)
    return scopes


def prepare_scopes(ctx, scopes):
    """Resolve local owner foreign keys without opening external artifacts.

    A public query can call this before refreshing external snapshots so a bad
    owner fails before any provider artifact is inspected. Contract loading is
    deferred to requirements().
    """
    validate_scopes(scopes)
    prepared = []
    for scope in scopes:
        owner = scope.owner
        run = activation = operation = None
        if type(owner) is RunID:
            if owner not in ctx.runs:
                raise KeyError(f"unknown composition run: {owner.wire}")
            run = owner
        elif type(owner) is RegionActivationID:
            activation_row = ctx.activations.get(owner)
            if activation_row is None:
                raise KeyError(f"unknown composition activation: {owner.wire}")
            activation = owner
            process = ctx.processes.get(activation_row.process)
            if process is None:
                raise KeyError(f"composition activation has unknown process: {activation_row.process.wire}")
            run = process.run
        elif type(owner) is OperationOccurrenceID:
            if owner not in ctx.occurrences:
                raise KeyError(f"unknown composition operation occurrence: {owner.wire}")
            operation = owner
            activation = ctx.activation_of(owner)
            activation_row = ctx.activations.get(activation)
            if activation_row is None:
                raise KeyError(f"composition operation has unknown activation: {activation.wire}")
            process = ctx.processes.get(activation_row.process)
            if process is None:
                raise KeyError(f"composition operation has unknown process: {activation_row.process.wire}")
            run = process.run
        else:
            raise TypeError("invalid composition scope owner")
        prepared.append({
            "scope": scope, "owner": owner, "run": run,
            "activation": activation, "operation": operation,
        })
    return tuple(prepared)


def _point_owner(ctx, point):
    if type(point) is Unresolved:
        point = point.point
    if type(point) is OccurrencePoint:
        if point.operation not in ctx.occurrences:
            return None, None, None
        activation = ctx.activation_of(point.operation)
        activation_row = ctx.activations.get(activation)
        process = None if activation_row is None else ctx.processes.get(activation_row.process)
        return (None if process is None else process.run, activation, point.operation)
    if type(point) is EvidencePoint:
        return point.run, None, None
    return None, None, None


def _actual_owner(ctx, actual):
    from .observations import BoundEndpoint, ExternalEndpoint, OutputValue

    if type(actual) is Unresolved:
        return _point_owner(ctx, actual.point)
    if type(actual) is OutputValue:
        value = ctx.values.get(actual.value)
        if value is None:
            return None, None, None
        origin = value.origin
        if type(origin) is OperationOccurrenceID:
            activation = ctx.activation_of(origin) if origin in ctx.occurrences else None
            operation = origin
        elif type(origin) is BlockVisitID:
            visit = ctx.visits.get(origin)
            segment = None if visit is None else ctx.segments.get(visit.segment)
            activation = None if segment is None else segment.activation
            operation = None
        elif type(origin) is RegionActivationID:
            activation, operation = origin, None
        else:
            activation = operation = None
        activation_row = None if activation is None else ctx.activations.get(activation)
        process = None if activation_row is None else ctx.processes.get(activation_row.process)
        return (None if process is None else process.run, activation, operation)
    if type(actual) is BoundEndpoint:
        binding = ctx.requirements.get(actual.binding)
        if binding is None:
            return None, None, None
        owner = binding.owner
        if type(owner) is OperationOccurrenceID and owner in ctx.occurrences:
            activation = ctx.activation_of(owner)
            operation = owner
        elif type(owner) is RegionActivationID:
            activation, operation = owner, None
        else:
            activation = operation = None
        activation_row = None if activation is None else ctx.activations.get(activation)
        process = None if activation_row is None else ctx.processes.get(activation_row.process)
        return (None if process is None else process.run, activation, operation)
    if type(actual) is ExternalEndpoint:
        # The resource target may establish a run/process, but never an
        # activation or operation correspondence.
        from .resources import (
            ExternalRealm, InstanceTarget, ProcessRealm, ProcessTarget,
            RunRealm, ThreadTarget,
        )
        target = actual.target
        process_id = run = None
        if type(target) is InstanceTarget:
            resource = ctx.resources.get(target.instance)
            if resource is not None:
                if type(resource.realm) is RunRealm:
                    run = resource.realm.run
                elif type(resource.realm) is ProcessRealm:
                    process_id = resource.realm.process
                elif type(resource.realm) is ExternalRealm:
                    return None, None, None
        elif type(target) is ProcessTarget:
            process_id = target.process
        elif type(target) is ThreadTarget:
            thread = ctx.threads.get(target.thread)
            process_id = None if thread is None else thread.process
        process = None if process_id is None else ctx.processes.get(process_id)
        if process is not None:
            run = process.run
        return run, None, None
    return None, None, None


def _root_owner_match(ctx, prepared, root):
    """Classify anchor, interval, and actual scope without identity inference."""
    owner = prepared["owner"]
    points = [root.anchor, root.interval.start, root.interval.end]
    point_scopes = [_point_owner(ctx, point) for point in points]
    actual_scope = _actual_owner(ctx, root.actual)
    known_scopes = [row for row in (*point_scopes, actual_scope) if any(part is not None for part in row)]
    if type(owner) is RunID:
        known_runs = [row[0] for row in known_scopes if row[0] is not None]
        if not known_runs:
            return "UNRESOLVED"
        if any(run != owner for run in known_runs):
            return "NO_MATCH"
        return "MATCH"
    if type(owner) is RegionActivationID:
        owner_row = ctx.activations.get(owner)
        owner_process = None if owner_row is None else ctx.processes.get(owner_row.process)
        owner_run = None if owner_process is None else owner_process.run
        known_runs = [row[0] for row in known_scopes if row[0] is not None]
        if owner_run is not None and any(run != owner_run for run in known_runs):
            return "NO_MATCH"
        known_activations = [row[1] for row in known_scopes if row[1] is not None]
        if not known_activations:
            return "UNRESOLVED"
        return ("MATCH" if all(activation == owner for activation in known_activations)
                and point_scopes[0][1] == owner else "UNRESOLVED")
    if type(owner) is OperationOccurrenceID:
        owner_activation = ctx.activation_of(owner) if owner in ctx.occurrences else None
        owner_row = None if owner_activation is None else ctx.activations.get(owner_activation)
        owner_process = None if owner_row is None else ctx.processes.get(owner_row.process)
        owner_run = None if owner_process is None else owner_process.run
        known_runs = [row[0] for row in known_scopes if row[0] is not None]
        if owner_run is not None and any(run != owner_run for run in known_runs):
            return "NO_MATCH"
        known_activations = [row[1] for row in known_scopes if row[1] is not None]
        if owner_activation is not None and any(
                activation != owner_activation for activation in known_activations):
            return "UNRESOLVED"
        anchor_run, anchor_activation, anchor_operation = point_scopes[0]
        if anchor_operation == owner:
            return "MATCH"
        if anchor_run is None and anchor_activation is None and anchor_operation is None:
            return "UNRESOLVED"
        return "UNRESOLVED"
    return "UNRESOLVED"


def _resolve_contracts(ctx, prepared):
    """Load exact requested definitions, retaining missing artifacts as gaps."""
    resolved, cache = [], {}
    for index, item in enumerate(prepared):
        scope = item["scope"]
        key = _contract_key(scope.contract)
        if key not in cache:
            graph = ctx.external_semantic(scope.contract.artifact,
                                          f"composition_scopes[{index}].contract")
            definition = None
            if graph is not None:
                definition = graph.contracts.get(scope.contract.contract)
                if definition is None:
                    raise KeyError(
                        "unknown contract in exact semantic artifact: "
                        f"{scope.contract.contract.wire}")
            cache[key] = graph, definition
        graph, definition = cache[key]
        resolved.append({
            **item,
            "contract": definition,
            "expected_outputs": None if definition is None else definition.required_outputs,
            "required_facets": None if definition is None else tuple(
                facet for facet in definition.facets if facet.required is True),
            "contract_status": "UNRESOLVED" if definition is None else "DECLARED",
        })
    return tuple(resolved)


def _scan_index(rows, budget, cost_kind, key_fn):
    """Build one linear index; return inspected count and an exact cursor."""
    index = {}
    for ordinal, row in enumerate(rows):
        if not budget.spend(cost_kind, path=f"{cost_kind}[{ordinal}]"):
            return index, ordinal, {"stage": cost_kind, "index": ordinal,
                                    "pending": len(rows) - ordinal}
        key = key_fn(row)
        if key is not None:
            index.setdefault(key, []).append(row)
    return index, len(rows), None


def _root_read_links(root, reads_by_root, budget, reads_complete):
    if not reads_complete:
        return {"root": root, "content_reads": (), "status": "READ_SCAN_TRUNCATED",
                "pending_reads": None}
    candidates = reads_by_root.get(root.id, ())
    selected = []
    for index, read in enumerate(candidates):
        if not budget.spend("composition_root_read_joins",
                            path=f"observation_roots[{root.id}].content_reads[{index}]"):
            return {"root": root, "content_reads": tuple(selected),
                    "status": "TRUNCATED", "pending_reads": len(candidates) - index}
        selected.append(read)
    status = ("DECLARED_READS" if selected else
              "NO_CONTENT_READ_DECLARED_PROTOCOL_UNCLASSIFIED")
    return {"root": root, "content_reads": tuple(selected), "status": status,
            "pending_reads": 0}


def requirements(ctx, scopes, *, budget):
    """Return Q obligations, original inventories, and conservative join status.

    The budget charges derived Q scans and joins. The returned top-level
    requirement/root/content-read tuples remain the exact original model tuples,
    including unvisited rows when a derived scan stops. Facets carry no
    endpoint target or cardinality, so they always remain uninterpreted.
    """
    from .resources import _exact
    from .validity_budget import ValidityBudget

    validate_scopes(scopes)
    _exact(budget, ValidityBudget, "composition validity budget")
    prepared = prepare_scopes(ctx, scopes)
    issue_start = len(ctx.issues)
    resolved = _resolve_contracts(ctx, prepared)
    scope_issues = ctx.issues[issue_start:]
    if scope_issues:
        raise ValueError("; ".join(
            f"{item.code} at {item.path}: {item.message}" for item in scope_issues))

    all_requirements = ctx.model.observation_requirements
    all_roots = ctx.model.observation_roots
    all_reads = ctx.model.content_reads

    req_output, req_facet = {}, {}
    req_count = 0 if scopes else len(all_requirements)
    req_cursor = None
    if scopes:
        for ordinal, row in enumerate(all_requirements):
            if not budget.spend("composition_requirement_rows",
                                path=f"observation_requirements[{ordinal}]"):
                req_cursor = {"stage": "requirements", "index": ordinal,
                              "pending": len(all_requirements) - ordinal}
                break
            req_count += 1
            contract_key = _contract_key(row.contract)
            if type(row.target) is RequiredOutput:
                req_output.setdefault((contract_key, row.target.slot), []).append(row)
            elif type(row.target) is RequiredEndpoint:
                req_facet.setdefault((contract_key, row.target.facet), []).append(row)
    requirements_complete = req_count == len(all_requirements)

    roots_by_requirement = {}
    root_count = 0 if scopes else len(all_roots)
    root_cursor = None
    if scopes and not budget.truncated:
        for ordinal, root in enumerate(all_roots):
            if not budget.spend("composition_root_rows", path=f"observation_roots[{ordinal}]"):
                root_cursor = {"stage": "roots", "index": ordinal,
                               "pending": len(all_roots) - ordinal}
                break
            root_count += 1
            roots_by_requirement.setdefault(root.requirement, []).append(root)
    roots_complete = root_count == len(all_roots)

    reads_by_root = {}
    read_count = 0 if scopes else len(all_reads)
    read_cursor = None
    if scopes and not budget.truncated:
        for ordinal, read in enumerate(all_reads):
            if not budget.spend("composition_content_read_rows", path=f"content_reads[{ordinal}]"):
                read_cursor = {"stage": "content_reads", "index": ordinal,
                               "pending": len(all_reads) - ordinal}
                break
            read_count += 1
            if type(read.consumer) is ObservationConsumer:
                reads_by_root.setdefault(read.consumer.root, []).append(read)
    reads_complete = read_count == len(all_reads)

    cursor = req_cursor or root_cursor or read_cursor
    stopped = budget.truncated
    obligations, scope_rows = [], []
    any_incomplete = False
    for scope_index, item in enumerate(resolved):
        contract = item["contract"]
        planned = (() if contract is None else
                   tuple(("OUTPUT", row) for row in item["expected_outputs"]) +
                   tuple(("FACET", row) for row in item["required_facets"]))
        entry = {
            **item, "obligation_start": len(obligations),
            "obligation_count": len(planned), "pending_obligations": (),
            "ledger_status": item["contract_status"],
        }
        if contract is None:
            any_incomplete = True
            scope_rows.append(entry)
            continue
        if stopped:
            entry["ledger_status"] = "TRUNCATED"
            entry["pending_obligations"] = planned
            entry["obligation_cursor"] = 0
            any_incomplete = True
            scope_rows.append(entry)
            continue

        entry_incomplete = False
        for local_index, (kind, target) in enumerate(planned):
            path = f"composition_scopes[{scope_index}].obligations[{local_index}]"
            if not budget.spend("composition_obligations", path=path):
                cursor = {"stage": "obligations", "scope": scope_index,
                          "index": local_index, "pending": len(planned) - local_index}
                entry["ledger_status"] = "TRUNCATED"
                entry["pending_obligations"] = planned[local_index:]
                entry["obligation_cursor"] = local_index
                any_incomplete = stopped = True
                break

            contract_key = _contract_key(item["scope"].contract)
            if kind == "OUTPUT":
                candidate_requirements = tuple(req_output.get((contract_key, target), ()))
            else:
                candidate_requirements = tuple(req_facet.get((contract_key, target.facet), ()))
            matched_roots, unresolved_roots = [], []
            owner_scan_complete = roots_complete and requirements_complete
            root_pending = 0
            pending_requirement_groups = 0
            for requirement_ordinal, requirement in enumerate(candidate_requirements):
                if not roots_complete:
                    continue
                candidates = roots_by_requirement.get(requirement.id, ())
                for root_index, root in enumerate(candidates):
                    if not budget.spend("composition_root_owner_joins",
                                        path=f"{path}.roots[{root_index}]"):
                        pending_requirement_groups = (
                            len(candidate_requirements) - requirement_ordinal - 1)
                        cursor = {"stage": "root_owner_joins", "scope": scope_index,
                                  "obligation": local_index,
                                  "requirement": requirement.id,
                                  "requirement_ordinal": requirement_ordinal,
                                  "index": root_index,
                                  "pending": len(candidates) - root_index,
                                  "pending_root_joins": len(candidates) - root_index,
                                  "pending_requirement_groups": pending_requirement_groups}
                        owner_scan_complete = False
                        root_pending += len(candidates) - root_index
                        stopped = any_incomplete = True
                        break
                    match = _root_owner_match(ctx, item, root)
                    if match == "MATCH":
                        matched_roots.append(root)
                    elif match == "UNRESOLVED":
                        unresolved_roots.append(root)
                if stopped:
                    break

            root_read_rows = []
            for root in (*matched_roots, *unresolved_roots):
                root_read_rows.append(_root_read_links(root, reads_by_root, budget, reads_complete))
                if budget.truncated:
                    cursor = cursor or {"stage": "root_read_joins", "scope": scope_index,
                                        "obligation": local_index}
                    owner_scan_complete = False
                    stopped = any_incomplete = True

            if kind == "OUTPUT":
                if not requirements_complete:
                    status = "REQUIREMENT_SCAN_TRUNCATED"
                elif not candidate_requirements:
                    status = "REQUIREMENT_MISSING"
                elif not owner_scan_complete:
                    status = "ROOT_JOIN_TRUNCATED"
                elif matched_roots:
                    status = "ROOT_PRESENT_OUTPUT_SLOT_UNVERIFIED"
                elif unresolved_roots:
                    status = "ROOT_SCOPE_UNRESOLVED"
                else:
                    status = "ROOT_MISSING"
            else:
                status = "FACET_TARGETS_UNINTERPRETED"
                if not requirements_complete or not owner_scan_complete:
                    status += ":JOIN_TRUNCATED"
                elif candidate_requirements and matched_roots:
                    status += ":DECLARED_ENDPOINT_CANDIDATE"
                elif candidate_requirements and unresolved_roots:
                    status += ":ENDPOINT_SCOPE_UNRESOLVED"
                elif not candidate_requirements:
                    status += ":NO_ENDPOINT_CANDIDATE"

            obligations.append({
                "scope": item["scope"], "kind": kind, "target": target,
                "requirements": candidate_requirements,
                "roots": tuple(matched_roots),
                "unresolved_roots": tuple(unresolved_roots),
                "root_content_reads": tuple(root_read_rows),
                "status": status,
                "requirements_scan_complete": requirements_complete,
                "roots_scan_complete": roots_complete,
                "content_reads_scan_complete": reads_complete,
                "pending_root_joins": root_pending,
                "pending_requirement_groups": pending_requirement_groups,
            })
            if status != "ROOT_PRESENT_OUTPUT_SLOT_UNVERIFIED":
                entry_incomplete = True
            if stopped:
                entry["ledger_status"] = "TRUNCATED"
                entry["pending_obligations"] = planned[local_index + 1:]
                entry["obligation_cursor"] = local_index + 1
                any_incomplete = True
                break

        if entry["ledger_status"] != "TRUNCATED":
            entry["ledger_status"] = "PARTIAL" if entry_incomplete else "DERIVED_FOR_REQUEST"
            any_incomplete = any_incomplete or entry_incomplete
        scope_rows.append(entry)

    if not scopes:
        scope_status = "UNRESOLVED"
    elif budget.truncated:
        scope_status = "TRUNCATED"
    elif any_incomplete:
        scope_status = "PARTIAL"
    else:
        scope_status = "DERIVED_FOR_REQUESTED_SCOPES"

    gaps = list(ctx.gaps)
    for item in budget.gaps:
        issue = ExecutionIssue(item["code"], item["path"], item["message"])
        if issue not in gaps:
            gaps.append(issue)
    if not scopes:
        gaps.append(ExecutionIssue("composition_scope_unresolved", "composition_scopes",
                                   "no exact contract/owner request established the Q denominator"))
    if any(item["contract"] is None for item in resolved):
        gaps.append(ExecutionIssue("composition_contract_unresolved", "composition_scopes",
                                   "an exact semantic contract artifact is unavailable"))
    if any(item["kind"] == "FACET" for item in obligations):
        gaps.append(ExecutionIssue("composition_facet_targets_uninterpreted", "composition_scopes",
                                   "required facets do not declare endpoint targets or cardinality"))
    if any(item["status"] == "ROOT_MISSING" for item in obligations):
        gaps.append(ExecutionIssue("composition_root_missing", "composition_scopes",
                                   "an expected output slot has no scope-matched observation root"))
    if any(read["status"] == "NO_CONTENT_READ_DECLARED_PROTOCOL_UNCLASSIFIED"
           for item in obligations for read in item["root_content_reads"]):
        gaps.append(ExecutionIssue("composition_content_protocol_unclassified", "content_reads",
                                   "a Q root has no linked ContentRead; this does not imply no content dependency"))

    return {
        "scopes": tuple(scope_rows),
        "obligations": tuple(obligations),
        "requirements": all_requirements,
        "roots": all_roots,
        "content_reads": all_reads,
        "gaps": tuple(gaps),
        "scope_status": scope_status,
        "scope_complete_for_request": scope_status == "DERIVED_FOR_REQUESTED_SCOPES",
        "budget": budget,
        "budget_truncated": budget.truncated,
        "cursor": cursor,
        "pending": {
            "requirements": len(all_requirements) - req_count,
            "roots": len(all_roots) - root_count,
            "content_reads": len(all_reads) - read_count,
        },
    }


__all__ = ["prepare_scopes", "requirements", "validate_scopes"]
