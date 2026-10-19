"""Await acquisition, qualification and held-body joins on canonical ports.

The inventory precedes optional links.  All analyses share the caller's index,
flow and budget.  Native interpretation remains a condition; no Reference
result becomes a global alias of an operand or of a hidden held object.
"""
from .control import ProtocolValueKind
from .evaluated_sources import evaluated_sources
from .model import (BlockArgument, CompletionResult, DataValue, ExitKind,
                    InvokeLiteralResult, OperationResult, ProtocolValue,
                    ReferenceValue, StateVersionValue, TerminatorKind)
from .protocol_connections import ProtocolOperationRef
from .protocols import (ContractResult, OwnedUse, ProtocolCall, ProtocolCallRule,
                        ProtocolClause, ProtocolProfile, StaticProtocolGap)
from .resumption import ResumableKind
from .state_addresses import ExistingAccess, InvokeStateOperand
from .structured import ControlEdgeReference


def _records():
    from .protocol_await_records import (AwaitAcquisition, AwaitBodyLink,
        AwaitIteratorQualification, CoroutineAwaitWrapper, ExpandedAwaitCallee,
        WrapperHeldBody)
    return (AwaitAcquisition, AwaitIteratorQualification, CoroutineAwaitWrapper,
            AwaitBodyLink, ExpandedAwaitCallee, WrapperHeldBody)


def _site(row):
    return ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)


def _kind(ctx, port):
    if type(port) is ContractResult:
        port = port.result_port
    if type(port) is OperationResult:
        return ExitKind.NORMAL
    if type(port) is InvokeLiteralResult:
        operation = ctx.operations[port.edge.operation]
        return operation.terminator.successors[port.edge.successor_index].kind
    return None


def _selected(ctx, *groups):
    return ctx.selected_edges(tuple(edge for group in groups for edge in ctx.selected_edges(group)))


def _normal_row(ctx, row):
    candidates = tuple(candidate for candidate in ctx.rows_by_clause.get((row.scope, row.clause), ())
                       if candidate.operation == row.operation
                       and hasattr(candidate.contract, 'result')
                       and _kind(ctx, candidate.contract.result) is ExitKind.NORMAL)
    return candidates[0] if len(candidates) == 1 else None


def success_source(ctx, row):
    """The semantic success port plus compulsory original choices.

    A bool qualifier supplies its original input on its accepting edge, never
    its bool result.  This projection does not alter ctx.port/ordinary copies.
    """
    Acquisition, Qualification, Wrapper, _, _, _ = _records()
    contract = row.contract
    if type(contract) not in (Acquisition, Qualification, Wrapper, ProtocolCall):
        return None, ()
    if type(contract) is ProtocolCall and not (
            row.clause is ProtocolClause.WRAPPER_CALL
            and ctx.scopes[row.scope].profile is ProtocolProfile.COROUTINE_AWAIT_WRAPPER_V1):
        return None, ()
    if type(contract) is Qualification and contract.branch is not None:
        return (OwnedUse(row.operation, contract.input_use),
                (ControlEdgeReference(contract.branch, 0 if contract.accepts_true else 1),))
    if _kind(ctx, contract.result) is not ExitKind.NORMAL:
        return None, ()
    return contract.result, ()


def _prepare(ctx):
    if hasattr(ctx, '_await_indexes'):
        return ctx._await_indexes
    Acquisition, Qualification, Wrapper, Link, Expanded, _ = _records()
    by_type = {kind: [] for kind in (Acquisition, Qualification, Wrapper)}
    advances, links, region_calls = [], [], {}
    qualification_parents, normal_terminals = {}, {}
    advance_rules = (ProtocolCallRule.DELEGATE_NEXT, ProtocolCallRule.DELEGATE_SEND,
                     ProtocolCallRule.DELEGATE_THROW, ProtocolCallRule.DELEGATE_CLOSE)
    for row in ctx.graph.protocol_operations:
        if type(row.contract) in by_type:
            by_type[type(row.contract)].append(row)
        if (type(row.contract) is Acquisition and type(row.contract.expansion) is Expanded
                and type(row.contract.expansion.qualification) is ProtocolOperationRef):
            qualification_parents.setdefault(row.contract.expansion.qualification, []).append(row)
        if type(row.contract) is ProtocolCall and row.contract.rule in advance_rules:
            advances.append(row)
    for binding in ctx.graph.protocol_bindings:
        if type(binding) is Link:
            links.append(binding)
    for operation in ctx.graph.operations:
        if operation.callee is not None:
            region_calls.setdefault(ctx.region_of[operation.id], []).append(operation)
        if operation.terminator is not None and operation.terminator.kind is TerminatorKind.RETURN:
            normal_terminals.setdefault(ctx.region_of[operation.id], []).append(operation.id)
    ctx._await_qualification_parents = qualification_parents
    ctx._await_normal_terminals = normal_terminals
    ctx._await_indexes = by_type, tuple(advances), tuple(links), region_calls
    ctx.preparation['await_local_contracts'] = sum(map(len, by_type.values()))
    ctx.preparation['await_advances'] = len(advances)
    ctx.preparation['await_body_links'] = len(links)
    from .await_inventory_originals import prepare as prepare_original_inventory
    prepare_original_inventory(ctx, advances, links)
    return ctx._await_indexes


def iterator_use(ctx, advance, case=None):
    """Independent iterator anchor, including expanded method lookup."""
    from .protocol_continuations import _iterator_use
    attachment = ctx.call_inputs.get(_site(advance))
    if case is not None:
        return _iterator_use(ctx, advance, case)
    if attachment is None or len(attachment.cases) != 1:
        return None
    return _iterator_use(ctx, advance, attachment.cases[0])


def _body_candidates(ctx, advance):
    """Original reachable callee regions, independent of supplied links."""
    _, _, _, region_calls = _prepare(ctx)
    operation = ctx.operations[advance.operation]
    if operation.callee is None:
        return (), False
    pending, seen, drives, complete = [operation.callee], set(), [], True
    while pending:
        if not ctx.spend('await_body_path_regions'):
            return tuple(drives), False
        region = pending.pop()
        if region in seen:
            continue
        seen.add(region)
        _, _, _, reached, _ = ctx._edges(region)
        for drive in ctx.drives_by_region.get(region, ()):
            if not ctx.spend('await_body_path_drives'):
                return tuple(drives), False
            if ctx.block_of[drive.operation] in reached:
                drives.append(drive.operation)
        for call in region_calls.get(region, ()):
            if not ctx.spend('await_body_path_calls'):
                return tuple(drives), False
            if ctx.block_of[call.id] in reached:
                pending.append(call.callee)
    return tuple(drives), complete


def _original_case_guards(ctx, advance, *, iterator=None):
    """Closest original copy-merge, independent of any expected tuple.

    Stop at producer/caller boundaries; distinct merges need joint reasoning.
    Never form a Cartesian product or choose a source from observed Drives.
    """
    merges, pending = [], []
    actuals = tuple(OwnedUse(advance.operation, identity) for identity in
                    (advance.contract.receiver_use, *advance.contract.argument_uses))
    if iterator is not None and iterator not in actuals:
        # An explicitly expanded method call consumes a bound method. Its
        # independently named lookup carries the iterator before that new
        # producer. Do not reverse-select a lookup when its anchor is absent.
        actuals = (iterator, *actuals)
    for actual in actuals:
        identity = actual.use
        value = ctx.values[ctx.owned_use(actual.operation, identity).value]
        seen = set()
        while value.id not in seen:
            if not ctx.spend('await_input_inventory_values'):
                pending.append((identity, 'budget'))
                break
            seen.add(value.id)
            origin = value.origin
            if type(origin) is not BlockArgument:
                pending.append((identity, 'producer_boundary'))
                break
            _, _, incoming, reached, _ = ctx._edges(value.region)
            if not ctx.spend('await_input_inventory_edges', len(incoming[origin.block])):
                pending.append((identity, 'budget'))
                break
            predecessors = tuple(edge for parent, edge in incoming[origin.block] if parent in reached)
            if len(predecessors) > 1:
                merges.append((origin.block, tuple(ControlEdgeReference(edge[0], edge[1])
                                                  for edge in predecessors)))
                break
            if not predecessors:
                pending.append((identity, 'caller_boundary'))
                break
            source = predecessors[0][3].get(value.id)
            if source is None:
                pending.append((identity, 'non_copy_port'))
                break
            value = ctx.values[source]
        else:
            pending.append((identity, 'copy_cycle'))
    unique = []
    for merge in merges:
        if merge not in unique:
            unique.append(merge)
    if len(unique) > 1:
        pending.append((None, 'multiple_merges_need_tuple_correlation'))
    guards = unique[0][1] if len(unique) == 1 else ()
    return guards, tuple(pending)


def _input_case_inventory(ctx, advance):
    """Keep original merge predecessors even after a case row is deleted.

    An absent case is a transient obligation, never a fabricated expected
    source tuple. The shared connection checker owns the guard inventory.
    """
    if not hasattr(ctx, '_await_input_case_inventory'):
        ctx._await_input_case_inventory = {}
        ctx._await_input_case_pending = {}
    site = _site(advance)
    if site not in ctx._await_input_case_inventory:
        attachment = ctx.call_inputs.get(site)
        if attachment is None:
            guards, pending = _original_case_guards(ctx, advance)
            cases = tuple((None, guard, True) for guard in guards or (None,))
            if pending:
                ctx._await_input_case_pending[site] = pending
        elif len(attachment.cases) == 1 and attachment.cases[0].guard is None:
            # A universal expected tuple is one declaration, not one original
            # control path. Keep its canonical case while independently
            # inventorying the actual operands' closest merge predecessors.
            guards, pending = _original_case_guards(ctx, advance,
                iterator=iterator_use(ctx, advance, attachment.cases[0]))
            cases = tuple((attachment.cases[0], guard, False) for guard in guards or (None,))
            unfinished = tuple(item for item in pending if item[1] not in (
                'producer_boundary', 'caller_boundary', 'non_copy_port'))
            if unfinished:
                ctx._await_input_case_pending[site] = unfinished
        else:
            from .protocol_connection_validation import _guard_inventory
            _, _, missing = _guard_inventory(ctx, advance, attachment)
            cases = tuple((case, case.guard, False) for case in attachment.cases)
            cases += tuple((None, ControlEdgeReference(operation, number), True)
                           for operation, number in missing)
        ctx._await_input_case_inventory[site] = cases
    return ctx._await_input_case_inventory[site]


def await_inventory(ctx, scope=None):
    """Source-first jobs, including missing rows/links and external boundaries.

    This is a transient query view.  Neither an actual Drive nor a supplied
    AwaitBodyLink selects an expected source or creates an inventory entry.
    """
    Acquisition, Qualification, Wrapper, _, _, _ = _records()
    by_type, advances, links, _ = _prepare(ctx)
    if not hasattr(ctx, '_await_inventory'):
        profiles = (ProtocolProfile.AWAIT_ACQUISITION_V1,
                    ProtocolProfile.COROUTINE_WRAPPER_CONSTRUCTION_V1)
        sources = []
        for declaration in ctx.graph.protocol_scopes:
            if declaration.profile not in profiles:
                continue
            owner = declaration.subject.operation
            rows = tuple(row for kind in (Acquisition, Wrapper) for row in by_type[kind]
                         if row.scope == declaration.id and row.operation == owner
                         and _kind(ctx, row.contract.result) is ExitKind.NORMAL)
            sources.extend((declaration.id, owner, row) for row in rows)
            if not rows:
                sources.append((declaration.id, owner, None))
        for declaration in ctx.graph.protocol_scopes:
            if declaration.profile is ProtocolProfile.AWAIT_METHOD_IMPLEMENTATION_V1:
                rows = tuple(row for row in by_type[Qualification] if row.scope == declaration.id)
                if not rows:
                    # The fixed method scope retains its qualification/source
                    # job even if every optional local contract was removed.
                    sources.append((declaration.id, declaration.subject.operation, None))
        for row in by_type[Qualification]:
            source, _ = success_source(ctx, row)
            if source is not None:
                sources.append((row.scope, row.operation, row))
        for row in ctx.graph.protocol_operations:
            if (type(row.contract) is ProtocolCall
                    and row.clause is ProtocolClause.WRAPPER_CALL
                    and ctx.scopes[row.scope].profile is ProtocolProfile.COROUTINE_AWAIT_WRAPPER_V1
                    and _kind(ctx, row.contract.result) is ExitKind.NORMAL):
                sources.append((row.scope, row.operation, row))
        ctx._await_source_inventory = tuple(sources)
        jobs, cursor = [], None
        for scope_id, owner, source_row in sources:
            source_ref = None if source_row is None else _site(source_row)
            source_port, forced = ((None, ()) if source_row is None else success_source(ctx, source_row))
            matched = False
            for advance in advances:
                if not ctx.spend('await_inventory_advances'):
                    cursor = {'phase': 'await_inventory', 'source': source_ref,
                              'source_operation': owner, 'advance': _site(advance)}
                    break
                for case, input_guard, case_missing in _input_case_inventory(ctx, advance):
                    actual = None if case_missing else iterator_use(ctx, advance, case)
                    conflict = False
                    try:
                        choices = _selected(ctx, forced, input_guard)
                    except ValueError:
                        choices, conflict = forced, True
                    report = ({'match': False, 'routes': (), 'gaps': ('await_accept_edge_conflict',)}
                              if conflict else None if source_port is None or actual is None else
                              ctx.bind(source_port, actual, guard=choices or None))
                    if report is not None and report['match'] is False:
                        possible = ctx.may_forwards(source_port, actual)
                        if possible is False and not conflict:
                            continue
                    # A missing source row cannot be paired with every Drive:
                    # retain its own obligation, not invented actual ownership.
                    if source_row is None:
                        continue
                    drives, complete = _body_candidates(ctx, advance)
                    for drive in drives or (None,):
                        attached = tuple(link for link in links if link.source == source_ref
                                         and link.advance == _site(advance) and link.drive == drive)
                        gaps = []
                        if case_missing:
                            gaps.append('await_input_case_missing')
                        if report is None or report['match'] is not True:
                            gaps.append('await_iterator_source_unresolved')
                        if drive is not None and not attached:
                            gaps.append('await_body_link_missing')
                        if drive is None:
                            gaps.append('await_external_iterator_body_boundary')
                        if not complete:
                            gaps.append('await_body_path_inventory_unresolved')
                        jobs.append({'scope': scope_id, 'source': source_ref,
                            'source_operation': owner, 'source_success': source_port,
                            'accepted_edges': forced, 'choices': choices, 'case': case,
                            'input_guard': input_guard, 'input_case_missing': case_missing,
                            'advance': _site(advance), 'advance_operation': advance.operation,
                            'iterator_use': actual, 'drive': drive, 'links': attached,
                            'binding': report, 'status': 'PARTIAL' if gaps else 'DECLARED',
                            'gaps': tuple(gaps), 'cursor': None, 'choice_conflict': conflict})
                        matched = True
            if not matched:
                operation = ctx.operations[owner]
                failure_only = (operation.terminator is not None
                    and operation.terminator.kind is TerminatorKind.INVOKE
                    and all(edge.kind is ExitKind.RAISE for edge in operation.terminator.successors))
                jobs.append({'scope': scope_id, 'source': source_ref,
                    'source_operation': owner, 'source_success': source_port,
                    'accepted_edges': forced, 'choices': forced, 'case': None,
                    'advance': None, 'advance_operation': None, 'iterator_use': None,
                    'drive': None, 'links': (), 'binding': None,
                    'status': 'DECLARED' if failure_only else 'MISSING',
                    'gaps': () if failure_only else
                            ('await_source_row_missing' if source_row is None else
                             'await_source_advance_unresolved',), 'cursor': cursor,
                    'failure_only': failure_only})
        if cursor is None and getattr(ctx, '_await_input_case_pending', None):
            site, pending = next(iter(ctx._await_input_case_pending.items()))
            cursor = {'phase': 'await_input_case_inventory', 'advance': site, 'pending': pending}
        if ctx.budget.truncated:
            from .await_inventory_originals import unchecked_suffix
            jobs.extend(unchecked_suffix(ctx, jobs))
        originals = {**ctx._await_original_anchor_inventory,
            'sources': tuple((scope_id, owner, None if row is None else _site(row))
                             for scope_id, owner, row in sources)}
        ctx._await_inventory = {'jobs': tuple(jobs), 'source_count': len(sources),
            'original_anchors': originals,
            'known_inventory_complete': cursor is None and not ctx.budget.truncated,
            'cursor': cursor, 'source_inventory_complete': False}
    result = ctx._await_inventory
    if scope is None:
        return result
    return {**result, 'jobs': tuple(job for job in result['jobs'] if job['scope'] == scope),
            'source_count': sum(item[0] == scope for item in ctx._await_source_inventory)}


def await_contract_errors(ctx, row):
    """Structural validation usable before the prepared connection context."""
    Acquisition, Qualification, Wrapper, _, _, _ = _records()
    if type(row.contract) not in (Acquisition, Qualification, Wrapper):
        return ()
    from .protocol_validation import _actual_protocol_use, _own_result, _state_sites
    operation, contract, errors = ctx.operations[row.operation], row.contract, []

    def error(code, message):
        errors.append((code, str(_site(row)), message))

    try:
        _state_sites(ctx, row)
        is_bool = type(contract) is Qualification and contract.branch is not None
        if not is_bool and (operation.terminator is None
                            or operation.terminator.kind is not TerminatorKind.INVOKE):
            raise ValueError('await native stage requires its original INVOKE')
        identity = (contract.operand_use if type(contract) is Acquisition else
                    contract.body_use if type(contract) is Wrapper else contract.input_use)
        actual = ctx.owned_use(operation.id, identity)
        if not isinstance(ctx.values[actual.value], ReferenceValue):
            raise ValueError('await input must be its original Reference Use')
        if not is_bool:
            _actual_protocol_use(ctx, operation, identity)
        expected = contract.expected_body if type(contract) is Wrapper else contract.expected
        if expected == OwnedUse(operation.id, identity):
            raise ValueError('await stage cannot justify its own input with the same OwnedUse')
        if type(expected) is BlockArgument and not hasattr(ctx, 'index'):
            block = ctx.blocks.get(expected.block)
            if block is None or expected.index >= len(block.arguments):
                raise ValueError('expected formal must exist in its original block')
        else:
            ctx.port(expected)
        if type(contract) in (Acquisition, Wrapper):
            scope = ctx.scopes[row.scope]
            if getattr(scope.subject, 'operation', None) != operation.id:
                raise ValueError('await acquisition/constructor must be its exact scope subject operation')
        result = _own_result(ctx, row, contract.result)
        if is_bool:
            if (operation.terminator is not None or operation.callee is not None
                    or type(contract.accepts_true) is not bool or row.slot != 0
                    or type(contract.result) is not OperationResult):
                raise ValueError('bool qualification requires its own ordinary bool and accepting branch')
            if result is not None and any(not isinstance(ctx.values[value], DataValue)
                    or ctx.values[value].data_type != 'builtins.bool' for value in result.values):
                raise ValueError('qualification result must be its own bool Data result')
            branch = ctx.operations.get(contract.branch)
            if (branch is None or branch.terminator is None
                    or branch.terminator.kind is not TerminatorKind.BRANCH
                    or ctx.region_of[branch.id] != ctx.region_of[operation.id]):
                raise ValueError('qualification branch must be its exact local BRANCH')
            if ctx.forwards(contract.result, OwnedUse(branch.id, branch.terminator.condition)) is False:
                error('protocol_await_qualification_branch', 'branch consumes another bool evaluation')
        else:
            if type(contract) is Qualification and contract.accepts_true is not None:
                raise ValueError('INVOKE qualification does not carry a bool accepting flag')
            selected = _kind(ctx, contract.result)
            if result is not None:
                valid = all(isinstance(ctx.values[value], ReferenceValue) for value in result.values)
                if selected is ExitKind.RAISE:
                    valid = all(isinstance(ctx.values[value], ProtocolValue)
                                and ctx.values[value].protocol is ProtocolValueKind.EXCEPTION_PACKET
                                for value in result.values)
                if not valid:
                    raise ValueError('await success is Reference; RAISE is its own whole exception packet')
        # Omitting a declared state site must not remove an original dependency.
        listed = {(site.operation, site.state_use) for site in contract.state_sites
                  if type(site) is InvokeStateOperand}
        if not is_bool:
            required = {(operation.id, use) for use in operation.invoke_arguments
                        if isinstance(ctx.values[ctx.owned_use(operation.id, use).value], StateVersionValue)}
            if not required.issubset(listed):
                error('protocol_await_state', 'await stage omits an original INVOKE state operand')
        else:
            accesses = {site.index for site in contract.state_sites if type(site) is ExistingAccess}
            if accesses != set(range(len(operation.accesses))):
                error('protocol_await_state', 'qualification must retain every original state access')
    except (KeyError, TypeError, ValueError) as exc:
        error('protocol_await_reference', str(exc))
    return tuple(errors)


def _result_copy(ctx, source, target, choices=()):
    """Exact source to a known call's kind/slot, all original terminal Uses."""
    if type(target) is ContractResult:
        target = target.result_port
    choices = ctx.selected_edges(choices)
    # Even an identical port cannot exist on the other selected completion.
    for endpoint in (source, target):
        endpoint = endpoint.result_port if type(endpoint) is ContractResult else endpoint
        if type(endpoint) is InvokeLiteralResult and any(
                edge.operation == endpoint.edge.operation and edge != endpoint.edge
                for edge in choices):
            return {'match': False, 'routes': (), 'gaps': ('await_result_edge_conflict',)}
    if type(target) is OwnedUse:
        return ctx.bind(source, target, guard=choices or None)
    if type(target) not in (OperationResult, InvokeLiteralResult):
        return {'match': None, 'routes': (), 'gaps': ('await_result_port_unresolved',)}
    port = ctx.port(source)
    target_port = ctx.port(target)
    if port is None or target_port is None or port.gap or target_port.gap:
        return {'match': None, 'routes': (), 'gaps': ('await_result_port_unresolved',)}
    if source == target:
        return {'match': True, 'routes': (), 'gaps': ()}
    operation = ctx.operations[target_port.operation]
    if operation.callee is None:
        return {'match': None, 'routes': (), 'gaps': ('await_result_callee_unresolved',)}
    kind = _kind(ctx, target)
    slot = target.index if type(target) is OperationResult else target.result.index
    previous = ctx._returns.guards
    try:
        from .await_outcome_flow import required_choices
        required, complete = required_choices(ctx, source)
        if not complete:
            return {'match': None, 'routes': (), 'gaps': ('await_result_source_prefix_unresolved',)}
        try:
            ctx._returns.guards = _selected(ctx, previous, choices, required)
        except ValueError:
            return {'match': False, 'routes': (), 'gaps': ('await_source_choice_conflict',)}
        if ctx.region_of[port.operation] != operation.callee:
            # Reuse the original known-callee exporter. Each intermediate
            # frame must still have one unambiguous caller; the requested
            # target never selects a caller by inspecting its data.
            return ctx._returns.export(source, port, None,
                guard=ctx._returns.guards, result=target)
        local = ctx.selected_edges(ctx._returns.guards, region=operation.callee)
        before = ctx._fresh_copies(port, guard=local or None)
        if before is None:
            return {'match': None, 'routes': (), 'gaps': ('await_result_flow_unresolved',)}
        evidence = []
        summary = ctx._returns.project(operation.callee, before, evidence_sink=evidence)
    finally:
        ctx._returns.guards = previous
    match = None if summary is None else summary.get((kind, slot))
    return {'match': match, 'routes': (), 'projection': tuple(evidence),
            'gaps': () if match is not None else ('await_result_terminal_unresolved',)}


class _Await:
    def __init__(self, ctx):
        self.ctx = ctx
        self.issues, self.gaps = [], []
        self.acquisitions, self.qualifications, self.wrappers, self.body_links = [], [], [], []

    def check(self, report, code, site, message):
        match = report.get('match')
        if match is False:
            self.issues.append((code, str(site), message))
        elif match is None:
            self.gaps.append({'code': code + '_unproved', 'site': site,
                              'gaps': report.get('gaps', ())})
        return match

    def missing(self, code, site):
        self.gaps.append({'code': code, 'site': site})

    def body_source(self, row):
        """Independent B source and original checking anchor, never a Drive."""
        Acquisition, Qualification, Wrapper, _, Expanded, _ = _records()
        contract = row.contract
        if type(contract) is Qualification:
            return contract.expected, OwnedUse(row.operation, contract.input_use), 'GENERAL_RETURN'
        if type(contract) is Wrapper:
            return contract.expected_body, OwnedUse(row.operation, contract.body_use), 'WRAPPER_BODY'
        if type(contract) is Acquisition:
            if type(contract.expansion) is Expanded and type(contract.expansion.qualification) is ProtocolOperationRef:
                qualifier = self.ctx.row(contract.expansion.qualification)
                if type(qualifier.contract) is Qualification:
                    return self.body_source(qualifier)
            return contract.expected, OwnedUse(row.operation, contract.operand_use), 'DIRECT_INPUT'
        return None, None, None

    def used_source(self, row, choices, iterator=None):
        """Eligibility only when a source is actually continued as success."""
        expected, anchor, role = self.body_source(row)
        if expected is None:
            return None
        source = dict(evaluated_sources(self.ctx, expected, anchor, choices, role=role))
        if role == 'GENERAL_RETURN':
            from .await_qualification import BAD_ITERATORS
            bad_kinds = BAD_ITERATORS
            code = 'protocol_await_return_qualification'
        elif role == 'WRAPPER_BODY':
            bad_kinds = (ResumableKind.GENERATOR, ResumableKind.GENERATOR_COROUTINE,
                         ResumableKind.ASYNC_GENERATOR, 'NON_ITERATOR')
            code = 'protocol_await_wrapper_body'
        else:
            bad_kinds = (ResumableKind.GENERATOR, ResumableKind.ASYNC_GENERATOR, 'NON_ITERATOR')
            code = 'protocol_await_acquisition_kind'
        bad = tuple(case for case in source['cases'] if case['kind'] in bad_kinds)
        protection = None
        if bad and role == 'GENERAL_RETURN':
            from .await_qualification import protected_advance
            protection = protected_advance(self.ctx, expected, iterator, choices)
            source['qualification_protection'] = protection
        for case in bad:
            if protection is not None and protection['match'] is True:
                continue
            if protection is not None and protection['match'] is None:
                self.missing('await_qualification_protection_unproved', _site(row))
            else:
                self.issues.append((code, str(_site(row)), 'known unsuitable source is continued through a successful iterator route'))
        if not source['classification_complete']:
            self.missing('await_continued_source_kind_unproved', _site(row))
        return source

    def classified(self, row, expected, actual, role):
        report = evaluated_sources(self.ctx, expected, actual, role=role)
        self.check(report['binding'], 'protocol_await_source', _site(row),
                   'await stage input is not its independently declared current source')
        return report

    def qualification(self, row):
        ctx, contract, start = self.ctx, row.contract, len(self.gaps)
        source = self.classified(row, contract.expected, OwnedUse(row.operation, contract.input_use), 'GENERAL_RETURN')
        accepted, choices = success_source(ctx, row)
        branch_binding = None
        if contract.branch is not None:
            branch = ctx.operations[contract.branch]
            branch_binding = ctx.bind(contract.result, OwnedUse(branch.id, branch.terminator.condition))
            self.check(branch_binding, 'protocol_await_qualification_branch', _site(row),
                       'qualification branch uses another bool evaluation')
        from .await_qualification import qualification_view
        feasibility = qualification_view(ctx, row)
        if feasibility['predicate_conflict']:
            self.issues.append(('protocol_await_predicate_result', str(_site(row)),
                'own bool literal contradicts the declared qualification for this exact source'))
        view = {'record': row, 'source': source, 'accepted_source': accepted,
                'accepted_edges': choices, 'branch_binding': branch_binding,
                'feasibility': feasibility,
                'status': 'PARTIAL' if len(self.gaps) > start else 'DECLARED',
                'gaps': tuple(self.gaps[start:])}
        self.qualifications.append(view)
        return view

    def wrapper(self, row):
        ctx, contract, start = self.ctx, row.contract, len(self.gaps)
        source = self.classified(row, contract.expected_body, OwnedUse(row.operation, contract.body_use), 'WRAPPER_BODY')
        # Bad construction inputs can legitimately take their RAISE path.
        # Successful use of a bad constructor is checked at its source jobs.
        if not source['classification_complete']:
            self.missing('await_wrapper_body_kind_unproved', _site(row))
        view = {'record': row, 'source': source,
                'status': 'PARTIAL' if len(self.gaps) > start else 'DECLARED',
                'gaps': tuple(self.gaps[start:])}
        self.wrappers.append(view)
        return view

    def acquisition(self, row):
        ctx, contract, start = self.ctx, row.contract, len(self.gaps)
        source = self.classified(row, contract.expected, OwnedUse(row.operation, contract.operand_use), 'DIRECT_INPUT')
        expansion = self.expansion(row)
        if not source['classification_complete']:
            self.missing('await_acquisition_kind_unproved', _site(row))
        view = {'record': row, 'source': source, 'expansion': expansion,
                'status': 'PARTIAL' if len(self.gaps) > start else 'DECLARED',
                'gaps': tuple(self.gaps[start:])}
        self.acquisitions.append(view)
        return view

    def expansion(self, row):
        ctx, expansion = self.ctx, row.contract.expansion
        _, Qualification, _, _, Expanded, _ = _records()
        if type(expansion) is not Expanded:
            self.missing('await_acquisition_expansion_unproved', _site(row))
            return {'status': 'PARTIAL', 'gaps': ('await_acquisition_expansion_unproved',)}
        parent, reports, stages = ctx.operations[row.operation], [], []
        if parent.callee is None:
            self.issues.append(('protocol_await_expansion', str(_site(row)), 'expanded acquisition requires its own real callee'))
            return {'status': 'CONTRADICTED', 'stages': ()}
        refs = (expansion.lookup, expansion.call, expansion.qualification)
        for ref in refs:
            if type(ref) is StaticProtocolGap:
                stages.append(None)
                self.missing('await_expansion_stage_missing', _site(row))
                continue
            stage = ctx.row(ref)
            if ctx.region_of[stage.operation] != parent.callee:
                self.issues.append(('protocol_await_expansion', str(ref), 'stage must belong to this exact callee'))
                stages.append(None)
            else:
                stages.append(stage)
        lookup, call, qualification = stages
        lookup_normal = None if lookup is None else _normal_row(ctx, lookup)
        call_normal = None if call is None else _normal_row(ctx, call)
        if lookup is not None:
            if type(lookup.contract) is not ProtocolCall or lookup.contract.rule is not ProtocolCallRule.AWAIT_LOOKUP:
                self.issues.append(('protocol_await_expansion', str(_site(lookup)), 'lookup ref must name its fixed lookup rule'))
            else:
                reports.append(ctx.bind(OwnedUse(parent.id, row.contract.operand_use),
                                        OwnedUse(lookup.operation, lookup.contract.receiver_use)))
        if call is not None and lookup is not None:
            if type(call.contract) is not ProtocolCall or call.contract.rule is not ProtocolCallRule.AWAIT_CALL:
                self.issues.append(('protocol_await_expansion', str(_site(call)), 'call ref must name its fixed await call'))
            else:
                if lookup_normal is None:
                    self.missing('await_lookup_normal_source_missing', _site(row))
                else:
                    reports.append(ctx.bind(lookup_normal.contract.result, OwnedUse(call.operation, call.contract.receiver_use)))
        if qualification is not None and call is not None:
            if type(qualification.contract) is not Qualification:
                self.issues.append(('protocol_await_expansion', str(_site(qualification)), 'qualification ref must name its exact typed check'))
            else:
                if call_normal is None:
                    self.missing('await_call_normal_source_missing', _site(row))
                else:
                    reports.append(ctx.bind(call_normal.contract.result, OwnedUse(qualification.operation, qualification.contract.input_use)))
                accepted, choices = success_source(ctx, qualification)
                if _kind(ctx, row.contract.result) is ExitKind.NORMAL and accepted is not None:
                    reports.append(_result_copy(ctx, accepted, row.contract.result, choices))
        for report in reports:
            self.check(report, 'protocol_await_expansion_copy', _site(row), 'expanded acquisition stage uses another source/current return')
        # Correlate only reports that expose original route contexts. Result
        # projections retain their separate all-terminal kind/slot evidence.
        routed = tuple(report for report in reports if report.get('routes'))
        joint = ctx.correlate(*routed) if routed else None
        if joint is not None:
            self.check(joint, 'protocol_await_expansion_tuple', _site(row), 'stage tuples belong to different callers or CFG cases')
        failures = []
        if _kind(ctx, row.contract.result) is ExitKind.RAISE:
            prefix = ()
            for stage in stages:
                if stage is None:
                    continue
                for sibling in ctx.rows_by_clause.get((stage.scope, stage.clause), ()):
                    if sibling.operation != stage.operation or not hasattr(sibling.contract, 'result'):
                        continue
                    if _kind(ctx, sibling.contract.result) is ExitKind.RAISE:
                        report = _result_copy(ctx, sibling.contract.result, row.contract.result,
                                              _selected(ctx, prefix, sibling.contract.result.edge))
                        failures.append({'record': sibling, 'binding': report})
                        self.check(report, 'protocol_await_expansion_packet', _site(row), 'early failure packet is not this parent RAISE result')
                normal = _normal_row(ctx, stage)
                if normal is not None and type(normal.contract.result) is InvokeLiteralResult:
                    prefix = _selected(ctx, prefix, normal.contract.result.edge)
        return {'stages': tuple(stages), 'bindings': tuple(reports), 'tuple': joint,
                'failures': tuple(failures), 'status': 'PARTIAL' if any(stage is None for stage in stages) else 'DECLARED'}

    def links(self, inventory):
        ctx = self.ctx
        Acquisition, Qualification, Wrapper, _, _, Held = _records()
        by_type, _, all_links, _ = _prepare(ctx)
        examined = set()
        for job in inventory['jobs']:
            for link in job['links']:
                if not ctx.spend('await_body_link_jobs'):
                    self.missing('await_body_link_not_checked', link.source)
                    continue
                examined.add(link)
                start, reports = len(self.gaps), []
                source_row, advance = ctx.row(link.source), ctx.row(link.advance)
                source, forced = success_source(ctx, source_row)
                choices = _selected(ctx, job['choices'], forced, link.guard)
                iterator = job['iterator_use']
                if source is None or iterator is None:
                    self.missing('await_link_success_source_missing', link.source)
                    continue
                reports.append(ctx.bind(source, iterator, guard=choices or None))
                drive = ctx.drives[link.drive]
                owner = OwnedUse(drive.operation, drive.instance)
                projection = link.projection
                body_expected = None
                body_anchor = None
                if type(projection) is Held:
                    constructor = ctx.row(projection.constructor)
                    if type(constructor.contract) is Wrapper:
                        body_expected = constructor.contract.expected_body
                        constructor_body = OwnedUse(constructor.operation, constructor.contract.body_use)
                        body_anchor = constructor_body
                    elif (type(constructor.contract) is ProtocolCall
                          and constructor.clause is ProtocolClause.WRAPPER_CALL
                          and ctx.scopes[constructor.scope].profile is ProtocolProfile.COROUTINE_AWAIT_WRAPPER_V1):
                        attachment = ctx.call_inputs.get(_site(constructor))
                        lookup_sources = [] if attachment is None else [case.receiver for case in attachment.cases]
                        lookup_rows = [ctx.rows.get((item.scope, item.clause, item.operation, item.slot))
                                       for item in lookup_sources if type(item) is ContractResult]
                        lookup_rows = [item for item in lookup_rows if item is not None
                                       and type(item.contract) is ProtocolCall
                                       and item.contract.rule is ProtocolCallRule.AWAIT_LOOKUP]
                        if len(lookup_rows) != 1:
                            self.missing('await_wrapper_lookup_source_unresolved', link.source)
                            constructor_body = None
                        else:
                            constructor_body = OwnedUse(lookup_rows[0].operation, lookup_rows[0].contract.receiver_use)
                            body_expected = projection.expected_body
                            body_anchor = constructor_body
                    else:
                        self.issues.append(('protocol_await_wrapper_constructor', str(link.source), 'held-body constructor is not a declared wrapper construction'))
                        constructor_body = None
                    if type(source_row.contract) is Wrapper and link.source != projection.constructor:
                        self.issues.append(('protocol_await_wrapper_constructor', str(link.source), 'wrapper source selects another constructor'))
                    if _kind(ctx, constructor.contract.result) is not ExitKind.NORMAL:
                        self.issues.append(('protocol_await_wrapper_constructor', str(link.source), 'RAISE cannot supply a wrapper W'))
                    if constructor_body is not None:
                        reports.extend((ctx.bind(body_expected, constructor_body, guard=choices or None),
                                        ctx.bind(body_expected, projection.body, guard=choices or None),
                                        ctx.bind(projection.expected_body, projection.body, guard=choices or None)))
                    reports.append(ctx.bind(constructor.contract.result, projection.wrapper_read, guard=choices or None))
                    if source_row != constructor:
                        self.check(_result_copy(ctx, constructor.contract.result, source, choices),
                                   'protocol_await_wrapper_constructor', link.source,
                                   'acquisition output is not the independently selected wrapper constructor result')
                    getter = projection.wrapper_read.operation
                    getter_op = ctx.operations[getter]
                    if not isinstance(ctx.values[ctx.owned_use(getter, projection.wrapper_read.use).value], ReferenceValue):
                        self.issues.append(('protocol_await_wrapper_read', str(link.source), 'getter W input must be Reference'))
                    if (getter_op.terminator is not None and getter_op.terminator.kind is TerminatorKind.INVOKE
                            and projection.wrapper_read.use not in getter_op.invoke_arguments):
                        self.issues.append(('protocol_await_wrapper_read', str(link.source), 'getter W input must be an actual invoke operand'))
                    for site in projection.state_sites:
                        if site.operation != getter:
                            self.issues.append(('protocol_await_wrapper_state', str(link.source), 'getter state site belongs to another operation'))
                        elif type(site) is ExistingAccess and site.index >= len(getter_op.accesses):
                            self.issues.append(('protocol_await_wrapper_state', str(link.source), 'getter state access is absent'))
                        elif type(site) is InvokeStateOperand:
                            state = ctx.owned_use(getter, site.state_use)
                            if (getter_op.terminator is None or getter_op.terminator.kind is not TerminatorKind.INVOKE
                                    or site.state_use not in getter_op.invoke_arguments
                                    or not isinstance(ctx.values[state.value], StateVersionValue)):
                                self.issues.append(('protocol_await_wrapper_state', str(link.source), 'getter state operand is not an actual current state input'))
                    listed_states = {site.state_use for site in projection.state_sites
                                     if type(site) is InvokeStateOperand and site.operation == getter}
                    required_states = {use for use in getter_op.invoke_arguments
                                       if isinstance(ctx.values[ctx.owned_use(getter, use).value], StateVersionValue)}
                    listed_accesses = {site.index for site in projection.state_sites
                                       if type(site) is ExistingAccess and site.operation == getter}
                    if (not required_states.issubset(listed_states)
                            or listed_accesses != set(range(len(getter_op.accesses)))):
                        self.issues.append(('protocol_await_wrapper_state', str(link.source), 'held-body read omits an original state dependency'))
                    produced = ctx.port(projection.body_result)
                    if (produced is not None and (produced.operation != getter
                            or _kind(ctx, projection.body_result) is not ExitKind.NORMAL
                            or any(not isinstance(ctx.values[value], ReferenceValue) for value in produced.values))):
                        self.issues.append(('protocol_await_wrapper_read', str(link.source), 'held-body result must be the getter own NORMAL Reference'))
                    reports.append(ctx.bind(projection.body_result, owner, guard=choices or None))
                elif projection is None:
                    body_expected, body_anchor, role = self.body_source(source_row)
                    if type(source_row.contract) is Wrapper:
                        self.issues.append(('protocol_await_wrapper_projection', str(link.source), 'wrapper W requires its own held-body projection'))
                    if body_expected is None:
                        self.missing('await_body_owner_source_unresolved', link.source)
                    else:
                        # Native self and qualification preserve the original
                        # object conditionally, not through the generic copy
                        # closure. Check both independent input and actual
                        # success-output-to-owner legs instead.
                        reports.append(ctx.bind(body_expected, body_anchor, guard=choices or None))
                        reports.append(ctx.bind(source, owner, guard=choices or None))
                else:
                    self.missing('await_wrapper_projection_unresolved', link.source)
                for report in reports:
                    self.check(report, 'protocol_await_body_copy', link.source, 'body link uses another iterator, wrapper or current B source')
                joint = ctx.correlate(*reports) if reports else None
                if joint is not None:
                    self.check(joint, 'protocol_await_body_tuple', link.source, 'body link inputs belong to different caller/CFG tuples')
                if body_expected is not None and body_anchor is not None:
                    classified = evaluated_sources(ctx, body_expected, body_anchor, choices, role='BODY_OWNER')
                    for case in classified['cases']:
                        interface = ctx.interfaces.get(ctx.region_of[drive.operation])
                        if (case['create'] is not None and interface is not None
                                and case['create'].body != interface.body):
                            self.issues.append(('protocol_await_body_owner', str(link.source), 'declared Create belongs to another body'))
                    actual_source = evaluated_sources(ctx,
                        projection.body_result if type(projection) is Held else source,
                        owner, choices, role='ACTUAL_BODY_SOURCE')
                    expected_creates = {item['create'].operation for item in classified['cases']
                                        if item['create'] is not None}
                    if (classified['classification_complete'] and len(expected_creates) == 1):
                        for item in actual_source['cases']:
                            if item['create'] is not None and item['create'].operation not in expected_creates:
                                self.issues.append(('protocol_await_body_owner', str(link.source),
                                                    'actual owner is another known Create, even if its body code is identical'))
                else:
                    classified, actual_source = None, None
                self.body_links.append({'record': link, 'job': job, 'bindings': tuple(reports),
                    'body_source': classified, 'actual_source': actual_source, 'tuple': joint,
                    'status': 'PARTIAL' if len(self.gaps) > start else 'DECLARED',
                    'gaps': tuple(self.gaps[start:]), 'source_runtime_verified': False,
                    'runtime_identity_verified': False, 'transformation_authorized': False})
        # Every supplied link is structurally checked even if no inventory job
        # accepts it. A bad source/advance/drive cannot disappear as unused.
        for link in all_links:
            if link in examined:
                continue
            try:
                ctx.row(link.source)
                source_row, advance = ctx.row(link.source), ctx.row(link.advance)
                if success_source(ctx, source_row)[0] is None:
                    raise ValueError('body link source is not a successful acquisition/qualification/wrapper')
                if type(advance.contract) is not ProtocolCall or advance.contract.rule not in (
                        ProtocolCallRule.DELEGATE_NEXT, ProtocolCallRule.DELEGATE_SEND,
                        ProtocolCallRule.DELEGATE_THROW, ProtocolCallRule.DELEGATE_CLOSE):
                    raise ValueError('body link advance must be an original fixed iterator request')
                if link.drive not in ctx.drives:
                    raise ValueError('body link must name an original BodyDrive')
                self.missing('await_body_link_path_unresolved', link.source)
            except (KeyError, TypeError, ValueError) as exc:
                self.issues.append(('protocol_await_body_link', str(link.source), str(exc)))


def _legacy_qualification(ctx):
    """Existing public await-call contract must not advance known bad results.

    A bad NORMAL return is legal until it is used as an accepted iterator. No
    issue is emitted merely because a method can return an unsuitable object.
    """
    from .protocol_continuations import _iterator_use
    creates = {row.operation for row in ctx.graph.resumable_creates}
    by_type, advances, _, _ = _prepare(ctx)
    issues, obligations = [], []
    for row in ctx.graph.protocol_operations:
        if (type(row.contract) is not ProtocolCall
                or row.contract.rule is not ProtocolCallRule.AWAIT_CALL
                or _kind(ctx, row.contract.result) is not ExitKind.NORMAL):
            continue
        op = ctx.operations[row.operation]
        # Preserve historical budgets for ordinary opaque helper profiles.
        if op.id not in creates and op.callee is None:
            continue
        for advance in advances:
            attachment = ctx.call_inputs.get(_site(advance))
            if attachment is None:
                continue
            for case in attachment.cases:
                if not ctx.spend('await_legacy_qualification_cases'):
                    return tuple(issues), tuple(obligations)
                actual = _iterator_use(ctx, advance, case)
                copied = ctx.bind(row.contract.result, actual, guard=case.guard)
                if copied['match'] is not True:
                    continue
                source = evaluated_sources(ctx, row.contract.result, actual,
                                           ctx.selected_edges(case.guard), role='GENERAL_RETURN')
                from .await_qualification import BAD_ITERATORS, protected_advance
                bad = tuple(item for item in source['cases'] if item['kind'] in BAD_ITERATORS)
                protection = (protected_advance(ctx, row.contract.result, actual,
                    ctx.selected_edges(case.guard)) if bad else None)
                if bad:
                    if protection['match'] is False:
                        issues.append(('protocol_await_return_qualification', str(_site(advance)),
                                       'general __await__ returned a known unsuitable object that is continued as an iterator'))
                obligations.append({'record': row, 'advance': advance, 'case': case,
                                    'source': source, 'binding': copied, 'known_bad_cases': bad,
                                    'qualification_protection': protection})
    return tuple(issues), tuple(obligations)


def await_connections(ctx):
    """Complete static await report, sharing the caller's one context/budget."""
    if 'await' in ctx._connection_reports:
        return ctx._connection_reports['await']
    analysis = _Await(ctx)
    Acquisition, Qualification, Wrapper, _, _, _ = _records()
    by_type, _, _, _ = _prepare(ctx)
    for kind, method in ((Acquisition, analysis.acquisition),
                         (Qualification, analysis.qualification), (Wrapper, analysis.wrapper)):
        for row in by_type[kind]:
            if not ctx.spend('await_contract_rows'):
                analysis.missing('await_contract_not_checked', _site(row))
                continue
            before = len(analysis.issues)
            structural = await_contract_errors(ctx, row)
            analysis.issues.extend(structural)
            if structural:
                continue
            try:
                method(row)
            except (KeyError, TypeError, ValueError) as exc:
                analysis.issues.append(('protocol_await_reference', str(_site(row)), str(exc)))
    inventory = await_inventory(ctx)
    checked_sources = set()
    for job in inventory['jobs']:
        if job.get('choice_conflict'):
            analysis.issues.append(('protocol_await_accept_edge', str(job['source']),
                                    'success iterator cannot be used on the rejecting qualification edge'))
        if job['source'] is None or job['advance'] is None or job['binding'] is None:
            continue
        key = job['source'], job['choices'], job['iterator_use']
        if key not in checked_sources and job['binding']['match'] is True:
            checked_sources.add(key)
            try:
                continued = analysis.used_source(ctx.row(job['source']), job['choices'], job['iterator_use'])
                protection = None if continued is None else continued.get('qualification_protection')
                if protection is not None:
                    job['qualification_protection'] = protection
                    if protection['match'] is True:
                        job['applicability'] = 'CONDITIONAL_ON_DECLARED_QUALIFICATION'
            except (KeyError, TypeError, ValueError) as exc:
                analysis.issues.append(('protocol_await_source', str(job['source']), str(exc)))
    try:
        analysis.links(inventory)
    except (KeyError, TypeError, ValueError) as exc:
        analysis.issues.append(('protocol_await_body_link', 'protocol_bindings', str(exc)))
    legacy_issues, legacy = _legacy_qualification(ctx)
    analysis.issues.extend(legacy_issues)
    for item in legacy:
        protection = item.get('qualification_protection')
        if protection is not None and protection['match'] is None:
            analysis.gaps.append({'code': 'await_qualification_protection_unproved',
                                  'site': _site(item['advance']), 'gaps': protection['gaps']})
    from .await_outcomes import outcome_connections
    from .await_failures import failure_paths
    outcomes = outcome_connections(ctx, inventory)
    failures = failure_paths(ctx)
    analysis.issues.extend((*outcomes['issues'], *failures['issues']))
    gaps = (*analysis.gaps, *(gap for job in inventory['jobs'] for gap in job['gaps']),
            *outcomes['gaps'], *failures['gaps'])
    result = {'issues': tuple(analysis.issues), 'gaps': gaps,
        'status': 'CONTRADICTED' if analysis.issues else 'PARTIAL' if gaps else 'DECLARED',
        'inventory': inventory, 'jobs': inventory['jobs'],
        'acquisitions': tuple(analysis.acquisitions), 'qualifications': tuple(analysis.qualifications),
        'wrappers': tuple(analysis.wrappers), 'body_links': tuple(analysis.body_links),
        'legacy_qualifications': legacy,
        'outcomes': outcomes['outcomes'], 'outcome_inventory': outcomes['outcome_inventory'],
        'failure_paths': failures['failure_paths'],
        'failure_path_inventory': failures['failure_path_inventory'],
        'obligations': (*analysis.acquisitions, *analysis.qualifications,
                        *analysis.wrappers, *inventory['jobs']),
        'cursor': inventory['cursor'] or ({'phase': 'await_connections'} if ctx.budget.truncated else None),
        'source_inventory_complete': False, 'source_runtime_verified': False,
        'runtime_identity_verified': False, 'value_identity_verified': False,
        'transformation_authorized': False}
    ctx._connection_reports['await'] = result
    return result


__all__ = ['await_connections', 'await_inventory', 'await_contract_errors',
           'success_source', 'iterator_use']
