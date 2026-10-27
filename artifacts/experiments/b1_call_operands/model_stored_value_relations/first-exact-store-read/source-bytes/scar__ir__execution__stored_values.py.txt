"""Demand-bound stored-value receipts over original accesses and state SSA.

Primitive-slot pre/post contracts are supplied model facts. They neither
interpret arbitrary Python attribute access nor establish stable tensor data.
No derived copy is installed in the canonical graph or an identity union.
"""
from scar.ir.program.model import (
    CompletionResult, DataValue, InvokeLiteralResult, LiteralOrigin,
    OperationResult, ReferenceValue, StateVersionValue, value_type,
)
from scar.ir.program.state_addresses import (
    CellContent, DynamicField, Element, ExistingAccess, NamespaceKey,
    ObjectField, ReferenceOwner,
)

from .common import Unresolved
from .coordinates import OccurrencePhase, OccurrencePoint
from .ids import OperationOccurrenceID
from .validity_budget import ValidityBudget


def _flags():
    return dict(source_runtime_verified=False, runtime_identity_verified=False,
                native_identity_verified=False, value_identity_verified=False,
                transformation_authorized=False)


def validate_request(site, occurrence, budget):
    ValidityBudget(budget)
    if type(site) not in (OperationResult, InvokeLiteralResult):
        raise TypeError('stored_value_sources requires an exact original result site')
    site.__post_init__()
    if type(occurrence) is not OperationOccurrenceID:
        raise TypeError('stored_value_sources requires an exact operation occurrence ID')


class _Sources:
    def __init__(self, ctx, shared):
        self.ctx, self.shared = ctx, shared
        self.gaps, self.cursor = [], None
        self.refinements = {row.site: row for row in ctx.program.state_address_refinements}
        self.by_operation = {}
        for row in ctx.model.operations:
            self.by_operation.setdefault(row.operation, []).append(row)

    def gap(self, code):
        if code not in self.gaps:
            self.gaps.append(code)

    def spend(self, kind, *, cost=1, path='stored_value_sources'):
        if self.shared.truncated or not self.shared.spend('stored_value_' + kind, cost, path):
            if self.cursor is None:
                self.cursor = {'phase': kind, 'path': path}
            self.gap('stored_value_budget_exhausted')
            return False
        return True

    def value(self, use):
        return (None if use is None or type(use.value) is Unresolved
                else self.ctx.values.get(use.value))

    def bind(self, row, occurrence, *, write=False):
        ctx = self.ctx
        original = ctx.core_operations[occurrence.operation]
        refinement = self.refinements[row.site]
        effect = refinement.effects[row.effect_index]
        local, inputs = [], {}
        result = {'declaration': row, 'operation': occurrence, 'effect': effect,
                  'inputs': (), 'before': None, 'current': None, 'post': None,
                  'post_point': None, 'result': None, 'source_value': None, 'source_use': None,
                  'selected': None, 'owner': None, 'selectors': (),
                  'completion': None, 'supported': False, 'gaps': ()}

        def gap(code):
            if code not in local:
                local.append(code)

        current = ctx.current(OccurrencePoint(occurrence.id, OccurrencePhase.BEFORE)) or {}
        for use in original.uses:
            if not self.spend('inputs', path=str(occurrence.id)):
                gap('stored_value_budget_exhausted')
                break
            actual = ctx.uses.get((occurrence.id, use.id))
            value = self.value(actual)
            inputs[use.id] = value
            if value is None:
                gap('stored_value_input_unobserved')
            definition = ctx.core_values[use.value]
            if type(definition) is StateVersionValue and (
                    value is None or current.get(definition.location) != value.id):
                gap('stored_value_current_state_unproved')
        result['inputs'] = tuple(inputs.items())
        state_use = (original.accesses[row.site.index].before
                     if type(row.site) is ExistingAccess else row.site.state_use)
        state_definition = ctx.core_values[ctx.core_uses[state_use][1].value]
        location = state_definition.location
        result['location'], result['before'] = location, inputs.get(state_use)
        result['current'] = ctx.values.get(current.get(location))
        if result['before'] is None or result['before'] != result['current']:
            gap('stored_value_current_state_unproved')

        if type(effect.owner) is ReferenceOwner:
            result['owner'] = inputs.get(effect.owner.use)
        else:
            gap('stored_value_single_slot_owner_unproved')
        selectors = []
        # A path through intermediate references may alias a different path.
        # This receipt only interprets one direct cell, never a range/aggregate.
        if len(effect.path) != 1:
            gap('stored_value_single_slot_path_unproved')
        for selector in effect.path:
            if not self.spend('selectors', path=str(occurrence.id)):
                gap('stored_value_budget_exhausted')
                break
            if type(selector) in (ObjectField, CellContent):
                selectors.append((selector, None))
            elif type(selector) in (DynamicField, Element, NamespaceKey):
                use = (selector.name if type(selector) is DynamicField else
                       selector.index if type(selector) is Element else selector.key)
                value = inputs.get(use)
                if value is None or type(ctx.core_values[value.value]) is not DataValue:
                    gap('stored_value_selector_value_unproved')
                selectors.append((selector, value))
            else:
                gap('stored_value_single_slot_path_unproved')
                selectors.append((selector, None))
        result['selectors'] = tuple(selectors)

        selected_edge = (row.completion if write else row.result.edge
                         if type(row.result) is InvokeLiteralResult else None)
        if type(row.site) is ExistingAccess:
            result['selected'] = True
            for identity in original.results:
                if not self.spend('results', path=str(occurrence.id)):
                    gap('stored_value_budget_exhausted')
                    break
                if ctx.results.get((occurrence.id, identity)) is None:
                    gap('stored_value_result_unobserved')
            if write:
                after = original.accesses[row.site.index].after
                result['post'] = ctx.results.get((occurrence.id, after))
                result['post_point'] = OccurrencePoint(occurrence.id, OccurrencePhase.AFTER)
            else:
                result['result'] = ctx.results.get((occurrence.id, original.results[row.result.index]))
        else:
            transfer = ctx.outgoing.get(occurrence.id)
            result['completion'] = transfer
            result['selected'] = (None if transfer is None else
                                  transfer.successor_index == selected_edge.successor_index)
            if result['selected'] is not True:
                gap('stored_value_completion_unobserved' if transfer is None
                    else 'stored_value_completion_not_taken')
            else:
                successor = original.terminator.successors[transfer.successor_index]
                block = ctx.blocks[successor.block]
                signature = next(sig for sig in original.completions if sig.kind is successor.kind)
                for formal_id, argument in zip(block.arguments, successor.arguments):
                    if not self.spend('completion_ports', path=str(occurrence.id)):
                        gap('stored_value_budget_exhausted')
                        break
                    formal = ctx.results.get((transfer.target, formal_id))
                    if formal is None:
                        gap('stored_value_result_unobserved')
                    if type(argument) is CompletionResult:
                        type_ = signature.types[argument.index]
                        if (getattr(type_, 'location', None) == location
                                and type(ctx.core_values[formal_id]) is StateVersionValue):
                            result['post'] = formal
                        if not write and argument.index == row.result.result.index:
                            result['result'] = formal
                    else:
                        actual = ctx.uses.get((occurrence.id, argument))
                        if self.value(actual) is None:
                            gap('stored_value_completion_input_unobserved')
                if write:
                    result['post_point'] = OccurrencePoint(occurrence.id, OccurrencePhase.EDGE,
                                                           transfer.successor_index)
        if write:
            result['source_use'] = ctx.uses.get((occurrence.id, row.payload))
            result['source_value'] = inputs.get(row.payload)
            if result['source_value'] is None:
                gap('stored_value_payload_unobserved')
            post, point = result['post'], result['post_point']
            after = {} if point is None else ctx.current(point) or {}
            if post is None or after.get(location) != post.id:
                gap('stored_value_post_state_unproved')
        elif result['result'] is None:
            gap('stored_value_result_unobserved')
        if result['owner'] is None:
            gap('stored_value_single_slot_owner_unproved')
        result['gaps'] = tuple(local)
        result['supported'] = not local and not self.shared.truncated
        return result

    def copies(self, source, target):
        """Compare original ancestors without asserting unrelated candidates copy."""
        from .pending_payloads import copy_recipe
        from .resumable_identity import compatible
        paths = []
        for value in (source, target):
            seen, links = {}, []
            cursor = None if value is None else value.id
            while cursor is not None and cursor not in seen:
                if not self.spend('copy_ancestors'):
                    return {'match': None, 'support': (), 'conflict': False}
                seen[cursor] = len(links)
                recipe, _, conflict = copy_recipe(self.ctx, cursor, self.shared)
                if conflict:
                    return {'match': None, 'support': (), 'conflict': True}
                if recipe is None:
                    break
                links.append(recipe)
                cursor = recipe['source']
            paths.append((seen, links))
        common = next((identity for identity in paths[0][0] if identity in paths[1][0]), None)
        if common is None:
            return {'match': None, 'support': (), 'conflict': False}
        local = []
        comparison = compatible(self.ctx, source, target, local, 'stored_value.original_copy')
        conflict = comparison['status'] == 'CONFLICT'
        support = tuple(link for seen, links in paths for link in links[:seen[common]])
        return {'match': None if conflict else True, 'support': support,
                'conflict': conflict, 'compatibility': comparison}

    def address(self, left, right):
        from .reference_identity import object_identity
        result = {'match': None, 'owner': None, 'selectors': ()}
        a, b = left['owner'], right['owner']
        if a is None or b is None:
            return result
        owner = self.copies(a, b)
        if owner['match'] is not True and not owner['conflict'] and not self.shared.truncated:
            identity = object_identity(self.ctx, a, b, shared=self.shared)
            owner = {**owner, 'identity': identity, 'match': identity['match']}
        result['owner'] = owner
        if owner['match'] is not True:
            result['match'] = owner['match']
            return result
        if len(left['selectors']) != 1 or len(right['selectors']) != 1:
            return result
        (p, x), (q, y) = left['selectors'][0], right['selectors'][0]
        if type(p) is not type(q):
            return result
        if not self.spend('address_comparisons'):
            return result
        if type(p) is ObjectField:
            result['match'] = p.name == q.name
        elif type(p) is CellContent:
            result['match'] = True
        elif type(p) in (DynamicField, Element, NamespaceKey) and x is not None and y is not None:
            a, b = self.ctx.core_values[x.value], self.ctx.core_values[y.value]
            if type(a) is not DataValue or type(b) is not DataValue:
                return result
            comparison = self.copies(x, y)
            result['selectors'] = (comparison,)
            result['match'] = comparison['match']
            if (result['match'] is None and type(a.origin) is LiteralOrigin
                    and type(b.origin) is LiteralOrigin
                    and type(a.origin.value) in (type(None), bool, int, float, str)
                    and type(a.origin.value) is type(b.origin.value)
                    and a.data_type == b.data_type):
                result['match'] = a.origin.value == b.origin.value
        return result


def stored_value_sources(ctx, site, occurrence, *, shared):
    """Conditionally link an original direct-slot load to actual store payloads."""
    if type(shared) is not ValidityBudget:
        raise TypeError('stored-value query requires exact shared ValidityBudget')
    validate_request(site, occurrence, shared.limit)
    original = ctx.occurrences.get(occurrence)
    if original is None:
        raise KeyError(occurrence)
    owner = site.operation if type(site) is OperationResult else site.edge.operation
    if original.operation != owner:
        raise ValueError('stored-value result site belongs to another original operation')
    definition = ctx.core_operations[owner]
    if type(site) is OperationResult:
        if site.index >= len(definition.results):
            raise KeyError(site)
    else:
        if (definition.terminator is None
                or site.edge.successor_index >= len(definition.terminator.successors)):
            raise KeyError(site)
        edge = definition.terminator.successors[site.edge.successor_index]
        signature = next((sig for sig in definition.completions if sig.kind is edge.kind), None)
        if signature is None or site.result.index >= len(signature.types):
            raise KeyError(site)
    query = _Sources(ctx, shared)
    reads = tuple(row for row in ctx.program.stored_value_reads if row.result == site)
    read = None
    if not reads:
        query.gap('stored_value_read_declaration_missing')
    elif query.spend('read'):
        read = query.bind(reads[0], original)
        for gap in read['gaps']:
            query.gap(gap)
    candidates = []
    for row in ctx.program.stored_value_writes:
        for operation in query.by_operation.get(row.site.operation, ()):
            if not query.spend('candidates', path=str(operation.id)):
                break
            binding = query.bind(row, operation, write=True)
            candidate = {'write': row, 'operation': operation, 'binding': binding,
                         'source_value': binding['source_value'], 'source_use': binding['source_use'],
                         'address': None,
                         'interval': None, 'match': None, 'gaps': binding['gaps']}
            candidates.append(candidate)
            if read is None:
                continue
            candidate['address'] = query.address(binding, read)
            if (not binding['supported'] or not read['supported']
                    or candidate['address']['match'] is not True or shared.truncated):
                continue
            if value_type(ctx.core_values[binding['source_value'].value]) != value_type(
                    ctx.core_values[read['result'].value]):
                candidate['gaps'] += ('stored_value_result_kind_mismatch',)
                continue
            from .state_preservation import state_preservation
            interval = state_preservation(ctx, binding['post_point'],
                OccurrencePoint(occurrence, OccurrencePhase.BEFORE), (read['location'],), shared=shared)
            candidate['interval'] = interval
            if interval['preserved'] is True and not shared.truncated:
                from .resumable_identity import compatible
                comparison = compatible(ctx, binding['source_value'], read['result'], [],
                                        'stored_value.payload_result')
                candidate['compatibility'] = comparison
                if comparison['status'] != 'CONFLICT':
                    candidate['match'] = True
        if shared.truncated:
            break
    # Separate final-post declarations cannot race to supply incompatible
    # payloads for an uncertain shared cell at that same completion.
    groups = {}
    if query.spend('post_groups', cost=len(candidates)):
        for candidate in candidates:
            key = candidate['operation'].id, candidate['write'].completion
            groups.setdefault(key, []).append(candidate)
    for candidate in candidates:
        if candidate['match'] is not True:
            continue
        for other in groups.get((candidate['operation'].id, candidate['write'].completion), ()):
            if not query.spend('post_consistency'):
                break
            if other is candidate:
                continue
            address = other['address']
            if ((address is None or address['match'] is not False)
                    and other['source_value'] != candidate['source_value']):
                candidate['match'] = None
                candidate['gaps'] += ('stored_value_multiple_post_alias_unproved',)
                query.gap('stored_value_multiple_post_alias_unproved')
                break
    proven = {}
    for candidate in candidates:
        if shared.truncated or ctx.issues:
            candidate['match'] = None
        if candidate['match'] is True:
            value = candidate['source_value']
            proven[value.id] = value
    sources = tuple(proven.values())
    match = True if len(sources) == 1 and not shared.truncated and not ctx.issues else None
    if len(sources) > 1:
        query.gap('stored_value_sources_ambiguous')
    if match is None and not query.gaps:
        query.gap('stored_value_source_unproved')
    if shared.truncated and query.cursor is None:
        query.cursor = {'phase': 'shared_interval', 'path': 'stored_value_sources'}
    source = sources[0] if match is True else None
    recipe = (None if source is None else {'source': source.id, 'target': read['result'].id,
        'rule': 'DECLARED_STORED_VALUE',
        'support': tuple(candidate for candidate in candidates if candidate['match'] is True)})
    return {'site': site, 'operation': original, 'read': read,
        'read_inventory': ctx.program.stored_value_reads,
        'write_inventory': ctx.program.stored_value_writes,
        'operation_inventory': ctx.model.operations,
        'candidates': tuple(candidates), 'sources': sources, 'source_value': source,
        'match': match, 'recipe': recipe, 'gaps': tuple(query.gaps), 'cursor': query.cursor,
        'budget': {'limit': shared.limit, 'used': shared.used,
                   'costs': dict(shared.costs), 'truncated': shared.truncated},
        'preparation': {'operations': len(ctx.model.operations),
                        'refinements': len(query.refinements),
                        'scope': 'original indexing, snapshot replay and detached copying are separate'},
        'conditions': ('direct-slot pre/post semantics are supplied declarations, not arbitrary Python attributes',
                       'object identity and stored-reference source do not establish stable object contents',
                       'selected original ports and interval effects remain independent requirements'),
        **_flags()}


__all__ = ['stored_value_sources', 'validate_request']
