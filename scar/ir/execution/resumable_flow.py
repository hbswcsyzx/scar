"""Original body ports linked to captured occurrences, without another SSA.

Prepared once per analyzed model. These are conditional projections of declared
links; no observation, native correspondence or value identity is invented.
"""
from collections import defaultdict

from scar.ir.program.model import CompletionResult, ExitKind, StateVersionValue
from scar.ir.program.queries import InstanceCaptureInput, ProgramIndex
from scar.ir.program.resumption import saved_actual_use

from .common import Unresolved
from .ids import BlockVisitID, OperationOccurrenceID, ValueOccurrenceID


def gap(ctx, target, code, path, message):
    from .validation import ExecutionIssue
    issue = ExecutionIssue(code, str(path), message)
    if issue not in target:
        target.append(issue)
    ctx.gap(code, path, message)


def value_for_use(ctx, use):
    return None if use is None else use.value if type(use.value) is Unresolved else ctx.values.get(use.value)


def use_binding(ctx, occurrence, static_use, formal, *, visit=None, role, recipe=None):
    use = None if occurrence is None else ctx.uses.get((occurrence.id, static_use.use.id))
    return {'binding': recipe, 'role': role, 'source_use_definition': static_use,
            'source_occurrence': occurrence, 'source_use': use, 'actual_use': use,
            'source_value': value_for_use(ctx, use), 'formal_definition': ctx.core_values[formal],
            'formal': None if visit is None else ctx.results.get((visit.id, formal))}


def _normal_create_handle(ctx, creation, declaration):
    """Project an actual NORMAL handle landing, independently of origin rows."""
    transfer = ctx.outgoing.get(creation.id)
    if transfer is None:
        return None
    edge = ctx.core_operations[creation.operation].terminator.successors[transfer.successor_index]
    if edge.kind is not ExitKind.NORMAL:
        return None
    landing = ctx.visits[transfer.target]
    # Canonical validation requires each CompletionResult slot exactly once.
    for actual, formal in zip(edge.arguments, ctx.blocks[landing.block].arguments):
        if type(actual) is CompletionResult and actual.index == declaration.handle_result.index:
            return ctx.results.get((landing.id, formal))
    return None


def prepare_resumables(ctx):
    ctx.body_drives = {row.operation: row for row in ctx.program.body_drives}
    ctx.body_creates = {row.operation: row for row in ctx.program.resumable_creates}
    ctx.resumable_bodies = {row.region: row for row in ctx.program.resumable_bodies}
    ctx.body_drive_executions, ctx.body_activation_origins = {}, {}
    for rows, key, registry in (
        (ctx.model.body_drive_executions, 'drive', ctx.body_drive_executions),
        (ctx.model.body_activation_origins, 'activation', ctx.body_activation_origins)):
        for row in rows:
            identity = getattr(row, key)
            if identity in registry:
                ctx.issue('body_duplicate_drive' if key == 'drive' else 'body_duplicate_origin',
                          identity, 'one natural key cannot have two body associations')
            registry[identity] = row
    ctx.body_drive_occurrences = {row.id: row for row in ctx.occurrences.values()
                                 if row.operation in ctx.body_drives}
    ctx.resolved_body_drives, ctx.resolved_body_origins = {}, {}
    ctx.body_drives_by_activation = defaultdict(list)
    ctx.body_outcomes_by_segment = defaultdict(list)
    ctx.body_occurrences_by_segment_site = {}
    ctx.body_segments_by_activation = defaultdict(list)
    ctx.body_known_create_handles = {}
    for segment in ctx.segments.values():
        ctx.body_segments_by_activation[segment.activation].append(segment)
    for occurrence in ctx.occurrences.values():
        creation = ctx.body_creates.get(occurrence.operation)
        if creation is not None:
            handle = _normal_create_handle(ctx, occurrence, creation)
            if handle is not None:
                ctx.body_known_create_handles[handle.id] = occurrence.id
        visit = ctx.visits[occurrence.visit]
        ctx.body_occurrences_by_segment_site.setdefault((visit.segment, occurrence.operation), []).append(occurrence)
        operation = ctx.core_operations[occurrence.operation]
        if (ctx.activations[ctx.activation_of(occurrence.id)].region in ctx.resumable_bodies
                and operation.terminator is not None
                and operation.terminator.kind.value in ('SUSPEND', 'RETURN', 'RAISE')):
            ctx.body_outcomes_by_segment[visit.segment].append(occurrence)
    # ProgramIndex owns the original port recipes. One instance per model, not
    # one per drive; static-site recipes are cached across dynamic occurrences.
    ctx.body_program_index = ProgramIndex(ctx.program) if (
        ctx.body_drive_occurrences or ctx.model.body_activation_origins) else None
    ctx.body_static_inputs, ctx.body_static_outputs, ctx.body_static_targets = {}, {}, {}
    if ctx.body_program_index is not None:
        from scar.ir.program.driver_flow import body_drive_target
        captured_sites = dict.fromkeys(row.operation for row in ctx.body_drive_occurrences.values())
        for identity in captured_sites:
            drive = ctx.body_drives[identity]
            ctx.body_static_inputs[identity] = ctx.body_program_index.drive_input_bindings(identity)
            ctx.body_static_targets[identity] = body_drive_target(ctx.program, drive)
            for edge in ctx.core_operations[identity].terminator.successors:
                ctx.body_static_outputs[identity, edge.source] = (
                    ctx.body_program_index.drive_bindings(identity, edge.source))
    ctx.body_preparation = {
        'program_indexes': int(ctx.body_program_index is not None),
        'static_drives': len(ctx.body_static_inputs),
        'captured_drives': len(ctx.body_drive_occurrences),
        'captured_create_handles': len(ctx.body_known_create_handles),
        'segments': len(ctx.segments), 'occurrences': len(ctx.occurrences),
        'cost_scope': 'record/FK checks, canonical port indexes and captured-route validation; '
                      'separate from bounded query traversal and detached result copying'}
    ctx.body_identity_preparation = {'binding_comparisons': 0, 'fresh_external_context': True}


def creation_view(ctx, activation):
    row = ctx.body_activation_origins.get(activation)
    gaps, captures, handle, creation = [], {}, None, None
    owner = ctx.activations.get(activation)
    if row is None:
        gap(ctx, gaps, 'body_origin_missing', activation, 'body activation has no declared Create or explicit external origin')
    elif type(row.creation) is Unresolved:
        check_unresolved(ctx, row.creation, activation, gaps)
        gap(ctx, gaps, 'body_creation_unobserved', activation, 'Create occurrence or external instance source is unresolved')
    else:
        creation = ctx.occurrences.get(row.creation)
        declared = None if creation is None else ctx.body_creates.get(creation.operation)
        if declared is None:
            ctx.issue('body_creation_kind', activation, 'known creation must be an actual ResumableCreate occurrence')
        elif owner is not None:
            if declared.body != owner.region:
                ctx.issue('body_creation_region', activation, 'Create produces another canonical body')
            if ctx.activations[ctx.activation_of(creation.id)].process != owner.process:
                ctx.issue('body_creation_process', activation, 'Create and body belong to different process incarnations')
            transfer = ctx.outgoing.get(creation.id)
            if transfer is None:
                gap(ctx, gaps, 'body_creation_transfer_unobserved', activation, 'Create NORMAL completion was not captured')
            else:
                edge = ctx.core_operations[creation.operation].terminator.successors[transfer.successor_index]
                if edge.kind is not ExitKind.NORMAL:
                    ctx.issue('body_creation_completion', activation, 'a failed Create cannot produce this body handle')
                else:
                    handle = _normal_create_handle(ctx, creation, declared)
                    if handle is None:
                        gap(ctx, gaps, 'body_creation_handle_unobserved', activation, 'Create NORMAL handle result has no captured value')
            for capture in declared.captures:
                site = ctx.body_program_index._uses[capture.source]
                use = ctx.uses.get((creation.id, capture.source))
                captures[capture.formal] = {'definition': capture, 'source_use_definition': site,
                    'source_occurrence': creation, 'source_use': use, 'source_value': value_for_use(ctx, use)}
    return {'association': row, 'activation': owner, 'creation': creation, 'handle': handle,
            'captures': captures, 'gaps': tuple(gaps)}


def check_unresolved(ctx, unresolved, activation, gaps):
    ctx.check_point(unresolved.point, activation)
    owner = ctx.activations.get(activation)
    if owner is None:
        return
    process = ctx.processes[owner.process]
    if unresolved.point.run != process.run:
        ctx.issue('body_unresolved_run', activation, 'unresolved endpoint is known to belong to another run')
    if unresolved.point.process is not None and unresolved.point.process != owner.process:
        ctx.issue('body_unresolved_process', activation, 'unresolved endpoint is known to belong to another process')
    if unresolved.point.process is None:
        gap(ctx, gaps, 'body_endpoint_process_unresolved', activation, 'unresolved endpoint has no process incarnation')


def input_views(ctx, caller, row, entry, resume_segment, origin, gaps):
    result = []
    for recipe in ctx.body_static_inputs[caller.operation]:
        source, formal = recipe.source, ctx.core_values[recipe.formal]
        if type(source) is InstanceCaptureInput:
            capture = origin['captures'].get(recipe.formal)
            if capture is None:
                binding = {'binding': recipe, 'role': 'capture', 'source_use_definition': source,
                    'source_occurrence': None, 'source_use': None, 'actual_use': None,
                    'source_value': None, 'formal_definition': formal,
                    'formal': None if entry is None else ctx.results.get((entry.id, recipe.formal))}
                gap(ctx, gaps, 'body_capture_source_unobserved', caller.id,
                    f'instance capture for original formal {recipe.formal} is unresolved')
            else:
                binding = {**capture, 'binding': recipe, 'role': 'capture',
                    'formal_definition': formal, 'actual_use': capture['source_use'],
                    'formal': None if entry is None else ctx.results.get((entry.id, recipe.formal))}
        else:
            if source.operation == caller.operation:
                occurrence = caller
                role = 'state' if type(formal) is StateVersionValue else 'delivered'
            else:
                role = 'saved'
                occurrence = None
                if resume_segment is not None:
                    from .coordinates import ResumeIngress
                    ingress = resume_segment.ingress
                    if type(ingress) is ResumeIngress:
                        occurrence = ctx.occurrences.get(ingress.suspension)
            binding = use_binding(ctx, occurrence, source, recipe.formal, visit=entry,
                                  role=role, recipe=recipe)
        if binding['source_use'] is None:
            gap(ctx, gaps, 'body_input_use_unobserved', caller.id, f'original {binding["role"]} Use is not captured: {recipe.formal}')
        if binding['formal'] is None:
            gap(ctx, gaps, 'body_input_formal_unobserved', caller.id, f'body entry formal is not captured: {recipe.formal}')
        result.append(binding)
    return tuple(result)


def output_views(ctx, caller, outcome, gaps):
    outputs, forwards = [], []
    transfer = ctx.outgoing.get(caller.id)
    operation = ctx.core_operations[caller.operation]
    selected = None if transfer is None else operation.terminator.successors[transfer.successor_index]
    landing = None if transfer is None else ctx.visits[transfer.target]
    if transfer is None:
        gap(ctx, gaps, 'body_drive_transfer_unobserved', caller.id, 'Drive selected source/landing transfer was not captured')
    if outcome is not None and selected is not None and selected.source != outcome.operation:
        ctx.issue('body_drive_source', caller.id, 'Drive selected a different original body outcome source')
    source = outcome.operation if outcome is not None else None if selected is None else selected.source
    recipes = () if source is None else ctx.body_static_outputs.get((caller.operation, source), ())
    if not recipes and source is not None and (caller.operation, source) not in ctx.body_static_outputs:
        ctx.issue('body_outcome_frontier', caller.id, 'actual outcome is not a declared first frontier source')
    for recipe in recipes:
        own = recipe.actual.operation == caller.operation
        actual = caller if own else outcome
        binding = use_binding(ctx, actual, recipe.actual, recipe.formal, visit=landing,
                              role='forward' if own else 'output', recipe=recipe)
        if binding['source_use'] is None:
            gap(ctx, gaps, 'body_output_use_unobserved', caller.id, f'original {binding["role"]} Use is not captured: {recipe.formal}')
        if binding['formal'] is None:
            gap(ctx, gaps, 'body_output_formal_unobserved', caller.id, f'Drive landing formal is not captured: {recipe.formal}')
        (forwards if own else outputs).append(binding)
    return tuple(outputs), tuple(forwards), transfer


def prepare_value_copies(ctx):
    """One predecessor index of declared original CFG/call/body copy recipes.

    It records no new value or SSA identity. Unknown producer interiors stop the
    route; different arbitrary roots do not establish unequal Python objects.
    """
    if not ctx.model.body_drive_executions:
        ctx.body_value_predecessors, ctx.body_value_roots, ctx.body_copy_recipes = {}, {}, {}
        return
    predecessors, recipes = {}, {}

    def copy(target, source, rule, support):
        previous = predecessors.get(target)
        if previous is not None and previous != source:
            ctx.issue('body_copy_source', target, 'original occurrence routes assign conflicting copy sources')
            return
        predecessors[target] = source
        old = recipes.get(target)
        recipes[target] = {'source': source, 'target': target, 'rule': rule,
                          'support': support if old is None else (*old['support'], *support)}
    formal_positions = {block.id: {formal: index for index, formal in enumerate(block.arguments)}
                        for block in ctx.blocks.values()}
    for value in ctx.values.values():
        if type(value.origin) is not BlockVisitID:
            continue
        transfer = ctx.incoming.get(value.origin)
        if transfer is None:
            continue
        occurrence = ctx.occurrences[transfer.operation]
        operation = ctx.core_operations[occurrence.operation]
        edge = operation.terminator.successors[transfer.successor_index]
        block = ctx.visits[value.origin].block
        actual = edge.arguments[formal_positions[block][value.value]]
        identity = saved_actual_use(operation, actual)
        use = None if identity is None else ctx.uses.get((occurrence.id, identity))
        if use is not None and type(use.value) is ValueOccurrenceID:
            copy(value.id, use.value, 'ORIGINAL_CFG_COPY', (transfer, use))
    for resolved in ctx.resolved_call_activations.values():
        for row in resolved['inputs']:
            actual, formal = row['actual'], row['formal']
            if actual is not None and formal is not None and type(actual.value) is ValueOccurrenceID:
                copy(formal.id, actual.value, 'ORIGINAL_CALL_INPUT', (resolved['association'], actual))
        for row in resolved['outputs']:
            actual = row['callee_use']
            formal = row['caller_result'] or row['caller_formal']
            if actual is not None and formal is not None and type(actual.value) is ValueOccurrenceID:
                copy(formal.id, actual.value, 'ORIGINAL_CALL_OUTPUT', (resolved['association'], actual))
    for resolved in ctx.resolved_body_drives.values():
        for row in (*resolved['inputs'], *resolved['outputs'], *resolved['forwards']):
            actual, formal = row['source_value'], row['formal']
            if actual is not None and type(actual) is not Unresolved and formal is not None:
                copy(formal.id, actual.id, 'ORIGINAL_BODY_BINDING',
                     (resolved['association'], row['binding'], row['source_use']))
    roots = {}
    for value in ctx.values:
        if value in roots:
            continue
        chain, seen, cursor = [], set(), value
        while cursor not in roots and cursor not in seen and cursor in predecessors:
            seen.add(cursor)
            chain.append(cursor)
            cursor = predecessors[cursor]
        root = roots.get(cursor, cursor if cursor not in seen else None)
        roots[cursor] = root
        for identity in chain:
            roots[identity] = root
        roots[value] = root
    needed, pending = set(), []
    for view in ctx.resolved_body_drives.values():
        if view['association'] is None:
            continue
        for binding in (*view['inputs'], *view['outputs'], *view['forwards']):
            for value in (binding['source_value'], binding['formal']):
                if value is not None and type(value) is not Unresolved:
                    pending.append(value.id)
        for value in (view['instance']['value'], view['instance']['creation_handle']):
            if value is not None and type(value) is not Unresolved:
                pending.append(value.id)
    from .resumable_sessions import session_endpoints
    for session in getattr(ctx, 'resolved_body_sessions', {}).values():
        for value in session_endpoints(session):
            if value is not None and type(value) is not Unresolved:
                pending.append(value.id)
    while pending:
        target = pending.pop()
        if target in needed or target not in predecessors:
            continue
        needed.add(target)
        pending.append(predecessors[target])
    ctx.body_value_predecessors, ctx.body_value_roots = predecessors, roots
    ctx.body_original_copy_recipes = recipes
    # Keep original recipe evidence. Only the ancestor closure actually used by
    # declared body links is checked; unrelated synchronous calls stay outside
    # this gate. No per-drive full-model scan or pair enumeration is required.
    ctx.body_copy_recipes = {target: recipes[target] for target in recipes if target in needed}


__all__ = ['prepare_resumables', 'creation_view', 'check_unresolved', 'input_views',
           'output_views', 'prepare_value_copies', 'value_for_use', 'gap']
