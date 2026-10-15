"""Global, bounded source-body demand scheduling, separate from program effects."""
from collections import defaultdict, deque
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


def expand_inventory(discovery, runtime_builder, budget, context_budget, ordered_files):
    # Local import avoids a module cycle: the source adapter owns FileInventory
    # construction; this module owns only its global analysis work schedule.
    from scar.analysis.program_inventory import (
        _Inventory, _attach_bodies, _body_connections, _CallLinker, prepare_source,
    )
    files, unavailable, bodies, issues = [], {}, {}, defaultdict(list)
    with PreparedContextStore(context_budget) as store:
        # Index all files before spending the first body/operation allowance.
        for file in ordered_files:
            path = file.snapshot.path
            context = builder = None
            try:
                context = prepare_source(path, project_root=discovery.project_root)
                if context.semantics.sources[path].fingerprint != file.snapshot.fingerprint:
                    raise ValueError("source changed between discovery and preparation")
                builder = _Inventory(context, 0, 0, runtime_builder=runtime_builder)
                indexed = builder.index()
            except (OSError, ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
                runtime_builder.file_failed(path)
                indexed = FileInventory(file.snapshot, (), (), (), (),
                    (InventoryIssue(path, "file preparation/inventory failed: " + str(error)),))
            else:
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

        observations = defaultdict(list)
        for binding in runtime_builder.bindings.values():
            for definition in binding.candidate_definitions:
                if definition in functions:
                    observations[definition].append(binding.observation_index)
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

        # Conditional dependency closure is a priority policy, not evidence that
        # a function executed or that its target and effects have been proven.
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

        roots = set(runtime_builder.definition_index)
        roots.update(call.execution_owner for file in files if file.snapshot.path == discovery.entry
                     for call in file.calls if call.phase is ExecutionPhase.MODULE_INITIALIZATION)
        expand_owners(sorted(roots, key=lambda key: key.wire))
        for definition in sorted(functions, key=lambda key: key.wire):
            enqueue(definition, BodyDemandKind.REMAINDER)

        remaining_bodies, remaining_operations = budget.max_lowered_bodies, budget.max_operations
        loaded_path, loaded_context = None, None
        while pending:
            *_, request = heapq.heappop(pending)
            definition = request.definition
            if definition in finished or requests[definition] is not request:
                continue
            finished.add(definition)
            path = file_by_definition[definition]
            if path in unavailable:
                body = BodyInventory(definition, BodyStatus.NOT_ATTEMPTED, None, None, unavailable[path])
                bodies[definition] = body
                entries.append(request)
                continue
            if remaining_bodies < 1 or remaining_operations < 1:
                bodies[definition] = BodyInventory(definition, BodyStatus.NOT_ATTEMPTED, None, None, _BUDGET_REASON)
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
                entries.append(replace(request, attempted=True, status=BodyStatus.UNSUPPORTED))
                continue
            cost_known, charged = True, 0
            try:
                selected = functions[definition]
                result = loaded_context.lower(selected.qualname, source=selected.source,
                    max_operations=remaining_operations, expand_candidates=False)
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
            remaining_operations -= charged
            bodies[definition] = body
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
                    enqueue(target, BodyDemandKind.CANDIDATE_CALL, via_call=operation)
                    expand_owners((target,))
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
            runtime_builder.file_emitted(result)
        schedule = ExpansionSchedule(context_budget, tuple(entries),
            tuple(ContextUnavailable(path, reason) for path, reason in sorted(unavailable.items())))
        measurements = ExpansionMeasurements(store.restore_attempts, store.compressed_payload_bytes_restored,
                                             store.compressed_bytes_written, store.uncompressed_bytes_written)
        return tuple(final), schedule, measurements
