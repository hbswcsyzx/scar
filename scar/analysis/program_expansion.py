"""Global, bounded source-body demand scheduling, separate from program effects."""
from collections import defaultdict, deque
from contextlib import nullcontext
from dataclasses import replace
import heapq
import pickle

from scar.analysis.program_context_store import ContextStoreLimit, PreparedContextStore
from scar.ir.program.expansion import (
    BodyDemandKind, BodyExpansion, ContextUnavailable, ExpansionMeasurements, ExpansionSchedule,
)
from scar.ir.program.inventory import (
    BodyInventory, BodyStatus, CallCandidateWitness, CandidateCondition,
    DefinitionKind, ExecutionPhase, FileInventory, InventoryIssue,
)


_FUNCTIONS = (DefinitionKind.FUNCTION, DefinitionKind.ASYNC_FUNCTION)
_RANK = {BodyDemandKind.OBSERVED_CODE: 0, BodyDemandKind.CANDIDATE_CALL: 1,
         BodyDemandKind.REMAINDER: 2}
_BUDGET_REASON = "independent body/aggregate operation construction budget exhausted"
_SCOPE_REASON = "this scope requires a class/lambda/comprehension interface beyond the current body lowerer"


def _error_reason(error):
    # Never persist a private/random scratch filename in a replayed report.
    if isinstance(error, ContextStoreLimit):
        return str(error)
    return "private context unavailable: " + type(error).__name__


def expand_inventory(discovery, runtime_builder, budget, context_budget, ordered_files, *, interface_model=False,
                     body_profile=None, call_source_report=None, source_workspace=None):
    # Local import avoids a module cycle: the source adapter owns FileInventory
    # construction; this module owns only its global analysis work schedule.
    from scar.analysis.program_inventory import (
        _Inventory, _attach_bodies, _body_connections, _CallLinker, prepare_source,
    )
    from scar.analysis.function_interfaces import FunctionInterfaceBuilder
    from scar.ir.program.functions import BodyLoweringProfile
    from scar.ir.program.frame_validation import require_valid_frame_model
    selected_profile = body_profile or BodyLoweringProfile.BOUND_FORMALS
    interfaces = FunctionInterfaceBuilder(profile=selected_profile) if interface_model else None
    frames = []
    is_v6 = call_source_report is not None
    if is_v6:
        from scar.analysis.call_demand_schedule import (
            CallDemandQueue, _matched_call_sources, entry_frontier_initializers, entry_roots_for,
        )
        from scar.ir.program.call_demand import EnteredCallCode, LegacyObservation, SourceCallCandidate
    files, unavailable, bodies, issues = [], {}, {}, defaultdict(list)
    module_initializers = {}
    store_scope = (nullcontext(source_workspace.store) if source_workspace is not None
                   else PreparedContextStore(context_budget))
    with store_scope as store:
        # Index all files before spending the first body/operation allowance.
        for file in ordered_files:
            path = file.snapshot.path
            context = builder = None
            try:
                context = (source_workspace.prepare(path) if source_workspace is not None
                           else prepare_source(path, project_root=discovery.project_root))
                if context.semantics.sources[path].fingerprint != file.snapshot.fingerprint:
                    raise ValueError("source changed between discovery and preparation")
                builder = _Inventory(context, 0, 0, runtime_builder=runtime_builder)
                indexed = builder.index()
                module_initializers[path] = builder.module
                if interfaces is not None:
                    interfaces.index_file(context, indexed, builder.nodes)
            except (OSError, ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
                if runtime_builder is not None:
                    runtime_builder.file_failed(path)
                if is_v6 and source_workspace is not None:
                    unavailable[path] = "source workspace unavailable: " + str(error)
                indexed = FileInventory(file.snapshot, (), (), (), (),
                    (InventoryIssue(path, "file preparation/inventory failed: " + str(error)),))
            else:
                if source_workspace is None:
                    try:
                        # Files without a supported scope never need a heavy body
                        # context, though their light/source evidence is preserved.
                        if any(d.kind in _FUNCTIONS for d in indexed.definitions):
                            store.put(context)
                    except (OSError, ValueError, TypeError, KeyError, RecursionError, pickle.PickleError) as error:
                        unavailable[path] = _error_reason(error)
            finally:
                context = builder = None
            files.append(indexed)

        # Admit witnesses only as an owner is demanded. Eagerly admitting all
        # unobserved calls would spend this budget before dynamic local targets
        # of an observed body become available.
        linker = _CallLinker(discovery, tuple(files), budget.max_call_witnesses)
        definitions = {definition.id: definition for file in files for definition in file.definitions}
        functions = {key: value for key, value in definitions.items() if value.kind in _FUNCTIONS}
        file_by_definition = {d.id: file.snapshot.path for file in files for d in file.definitions}
        calls = {call.operation: call for file in files for call in file.calls}
        by_owner = defaultdict(list)
        for file in files:
            for call in file.calls:
                by_owner[call.execution_owner].append(call)

        def enqueue_v6_direct_calls(owner, priority):
            for call in by_owner[owner]:
                for witness in linker.link(call).candidate_witnesses:
                    if witness.definition in functions:
                        demand_queue.add(witness.definition, priority, SourceCallCandidate(call.operation))

        observations = defaultdict(list)
        for binding in runtime_builder.bindings.values() if runtime_builder is not None else ():
            for definition in binding.candidate_definitions:
                if definition in functions:
                    observations[definition].append(binding.observation_index)
        demand_queue = None
        entry_roots = ()

        if is_v6:
            demand_queue = CallDemandQueue(functions)
            entry_roots = entry_roots_for(files, module_initializers, discovery.entry)

            for definition in sorted(observations, key=lambda key: key.wire):
                for observation_index in sorted(set(observations[definition])):
                    demand_queue.add(definition, CallDemandQueue.OBSERVED,
                                     LegacyObservation(observation_index))

            # A D0 seed is admitted only when its replayed path/fingerprint and
            # exact definition/source match this complete source inventory.
            for (process_id, code), match in sorted(_matched_call_sources(call_source_report, files).items()):
                if match is None:
                    continue
                _, definition = match
                if definition.kind in _FUNCTIONS:
                    demand_queue.add(definition.id, CallDemandQueue.OBSERVED,
                                     EnteredCallCode(process_id, code))

            # Entry and statically discovered import-module initializers form
            # the source frontier. Only entry itself is recorded as EntryRoot;
            # imported modules remain candidate scopes, not claimed executions.
            for initializer in entry_frontier_initializers(discovery, source_workspace, module_initializers):
                enqueue_v6_direct_calls(initializer, CallDemandQueue.ENTRY)

            for definition in sorted(functions, key=lambda key: key.wire):
                demand_queue.add_remainder(definition)
        else:
            requests, pending, finished, entries = {}, [], set(), []
            serial = 0

            def enqueue(definition, kind, *, via_call=None, observed=()):
                nonlocal serial
                if definition not in functions or definition in finished:
                    return
                previous = requests.get(definition)
                if previous is not None and _RANK[previous.kind] <= _RANK[kind]:
                    return
                source = functions[definition].source
                request = BodyExpansion(definition, source, kind, tuple(sorted(set(observed))), via_call)
                requests[definition] = request
                serial += 1
                heapq.heappush(pending, (_RANK[kind], source.path, source.start_line,
                                        source.start_column, definition.wire, serial, request))

            for definition in sorted(observations, key=lambda key: key.wire):
                enqueue(definition, BodyDemandKind.OBSERVED_CODE, observed=observations[definition])

            # Preserve the historical v1-v5 closure, sorting and admission order.
            expanded_owners = set()

            def expand_owners(owners):
                frontier = deque(owners)
                while frontier:
                    owner = frontier.popleft()
                    if owner in expanded_owners:
                        continue
                    expanded_owners.add(owner)
                    for call in by_owner[owner]:
                        for witness in linker.link(call).candidate_witnesses:
                            if witness.definition in functions:
                                enqueue(witness.definition, BodyDemandKind.CANDIDATE_CALL, via_call=call.operation)
                                frontier.append(witness.definition)

            roots = set(runtime_builder.definition_index) if runtime_builder is not None else set()
            roots.update(call.execution_owner for file in files if file.snapshot.path == discovery.entry
                         for call in file.calls if call.phase is ExecutionPhase.MODULE_INITIALIZATION)
            expand_owners(sorted(roots, key=lambda key: key.wire))
            for definition in sorted(functions, key=lambda key: key.wire):
                enqueue(definition, BodyDemandKind.REMAINDER)

        remaining_bodies, remaining_operations = budget.max_lowered_bodies, budget.max_operations
        loaded_path, loaded_context = None, None
        while True:
            v6_task = None
            if is_v6:
                v6_task = demand_queue.pop()
                if v6_task is None:
                    break
                request = v6_task
            else:
                if not pending:
                    break
                *_, request = heapq.heappop(pending)
                definition = request.definition
                if definition in finished or requests[definition] is not request:
                    continue
                finished.add(definition)
            definition = request.definition
            path = file_by_definition[definition]
            if path in unavailable:
                body = BodyInventory(definition, BodyStatus.NOT_ATTEMPTED, None, None, unavailable[path])
                bodies[definition] = body
                if not is_v6:
                    entries.append(request)
                continue
            if remaining_bodies < 1 or remaining_operations < 1:
                bodies[definition] = BodyInventory(definition, BodyStatus.NOT_ATTEMPTED, None, None, _BUDGET_REASON)
                if not is_v6:
                    entries.append(request)
                continue
            remaining_bodies -= 1
            try:
                if path != loaded_path:
                    # Release the previous heavy context before unpickling one.
                    loaded_context, loaded_path = None, None
                    loaded_context = store.get(path)
                    loaded_path = path
            except (OSError, ValueError, TypeError, KeyError, EOFError, RecursionError, pickle.PickleError) as error:
                unavailable[path] = _error_reason(error)
                bodies[definition] = BodyInventory(definition, BodyStatus.UNSUPPORTED, None, None, unavailable[path])
                if is_v6:
                    demand_queue.mark_result(v6_task, status=BodyStatus.UNSUPPORTED,
                        construction_operations=0, operation_budget_charged=0,
                        construction_cost_known=True)
                    # The body context failed to restore, but the completed
                    # source inventory still supports direct conditional call
                    # candidates from this one owner.
                    enqueue_v6_direct_calls(definition, v6_task.priority)
                else:
                    entries.append(replace(request, attempted=True, status=BodyStatus.UNSUPPORTED))
                continue
            cost_known, charged = True, 0
            try:
                selected = functions[definition]
                options = {"profile": selected_profile} if interface_model else {}
                result = loaded_context.lower(selected.qualname, source=selected.source,
                    max_operations=remaining_operations, expand_candidates=False, **options)
                charged = result.operations_emitted
                if type(charged) is not int or not 0 <= charged <= remaining_operations:
                    raise ValueError("lowerer returned an invalid construction count")
                body = BodyInventory(definition, BodyStatus.LOWERED_WITH_GAPS if result.graph else BodyStatus.UNSUPPORTED,
                    result.graph, result.metadata, "; ".join(dict.fromkeys(g.detail for g in result.metadata.gaps)), charged)
            except (ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
                # Construction may have happened before the lowerer raised. Its
                # exact count is unavailable, so consume the remaining allowance.
                charged, cost_known = remaining_operations, False
                body = BodyInventory(definition, BodyStatus.UNSUPPORTED, None, None,
                                     "body construction error: " + str(error))
                issues[path].append(InventoryIssue(path, body.reason, request.source))
            else:
                if interfaces is not None:
                    try:
                        if selected_profile is BodyLoweringProfile.BOUND_FRAME:
                            if body.graph is None:
                                if result.frame is not None:
                                    raise ValueError("failed body cannot retain frame correspondence")
                            elif result.frame is None:
                                raise ValueError("frame body needs explicit frame correspondence")
                            else:
                                require_valid_frame_model(result.frame, body.graph, interface=result.interface,
                                                          semantic=loaded_context.semantic)
                                if result.frame.definition != body.definition or result.interface.profile is not selected_profile:
                                    raise ValueError("frame correspondence differs from the selected body/profile")
                        interfaces.record_body(body, result.interface)
                        if selected_profile is BodyLoweringProfile.BOUND_FRAME and result.frame is not None:
                            frames.append(result.frame)
                    except (ValueError, TypeError, KeyError) as error:
                        body = BodyInventory(definition, BodyStatus.UNSUPPORTED, None, None,
                            "body interface correspondence failed: " + str(error), charged)
                        issues[path].append(InventoryIssue(path, body.reason, request.source))
            remaining_operations -= charged
            bodies[definition] = body
            if is_v6:
                demand_queue.mark_result(v6_task, status=body.status,
                    construction_operations=body.construction_operations,
                    operation_budget_charged=charged, construction_cost_known=cost_known)
                # Link only this processed owner's direct source calls. Its
                # children inherit the parent's frontier and wait their turn.
                enqueue_v6_direct_calls(definition, v6_task.priority)
            else:
                entries.append(replace(request, attempted=True, construction_operations=body.construction_operations,
                                       status=body.status, operation_budget_charged=charged,
                                       construction_cost_known=cost_known))

            _, new_candidates, _ = _body_connections((body,))
            for operation, targets in new_candidates.items():
                if operation not in calls:
                    continue
                for target in targets:
                    if target not in definitions:
                        continue
                    witness = CallCandidateWitness(target, definitions[target].source, (),
                        (CandidateCondition.SOURCE_BINDING_REACHES_READ, CandidateCondition.SOURCE_BODY_MATCHES_LIVE_CALLABLE,
                         CandidateCondition.NO_EXTERNAL_NAMESPACE_MUTATION))
                    if not linker.admit(calls[operation], witness):
                        continue
                    if is_v6:
                        demand_queue.add(target, v6_task.priority, SourceCallCandidate(operation))
                    else:
                        enqueue(target, BodyDemandKind.CANDIDATE_CALL, via_call=operation)
                        expand_owners((target,))
            if not is_v6:
                expand_owners((definition,))

        loaded_context = None
        final = []
        files = linker.finish()
        frozen_witnesses = {call.operation:call.candidate_witnesses for file in files for call in file.calls}
        for file in files:
            path = file.snapshot.path
            file_bodies = tuple(bodies[d.id] if d.id in bodies else
                BodyInventory(d.id, BodyStatus.NOT_ATTEMPTED, None, None, _SCOPE_REASON) for d in file.definitions)
            file_issues = [*file.gaps, *issues[path]]
            if path in unavailable:
                file_issues.append(InventoryIssue(path, unavailable[path]))
            result = _attach_bodies(replace(file, gaps=tuple(file_issues)), file_bodies,
                                    call_witnesses=frozen_witnesses)
            final.append(result)
            if runtime_builder is not None:
                runtime_builder.file_emitted(result)
        unavailable_records = tuple(ContextUnavailable(path, reason)
                                     for path, reason in sorted(unavailable.items()))
        schedule = (demand_queue.schedule(context_budget, entry_roots, unavailable_records) if is_v6
                    else ExpansionSchedule(context_budget, tuple(entries), unavailable_records))
        measurements = ExpansionMeasurements(store.restore_attempts, store.compressed_payload_bytes_restored,
                                             store.compressed_bytes_written, store.uncompressed_bytes_written)
        return tuple(final), schedule, measurements, interfaces.finish(final) if interfaces is not None else None, tuple(frames)
