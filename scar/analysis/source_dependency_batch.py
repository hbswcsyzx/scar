"""Bounded dependency views over original source bodies and call interfaces.

No graph is owned here beyond SourceReturnSession's existing private indexes.
An operation input is a conservative dependence, not an alias or proof that
its contents, effects, or one loop occurrence were observed.
"""
from __future__ import annotations

from collections import deque

from scar.analysis.source_dependencies import _DependencyFrontiers, SourceDependencySession
from scar.analysis.source_return_bindings import SourceReturnBudget
from scar.ir.program.ids import UseID
from scar.ir.program.model import CompletionResult, ProtocolValue, StateVersionValue, Terminator, UseRole
from scar.ir.record_codec import encode


def _positive(value, maximum, label):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(label + ' requires an exact positive independent ceiling')


def _keys(binding):
    caller = getattr(binding, 'caller', None)
    return ((caller, binding.callee) if caller is not None
            else (binding.entry.caller, binding.entry.callee))


def _endpoint(invocation, body, value):
    return {'invocation': encode(invocation), 'body': encode(body), 'value': encode(value)}


class SourceDependencyBatchSession(SourceDependencySession):
    """Reuse ordinary body/port validation in one local retained-model session."""

    def return_consumers(self, binding_index, *, max_nodes=128, max_depth=32, max_routes=512):
        """Follow original consumers/outputs, retaining operation uncertainty."""
        for value, ceiling, name in ((max_nodes, 100_000, 'nodes'), (max_depth, 1024, 'depth'),
                                      (max_routes, 100_000, 'routes')):
            _positive(value, ceiling, name)
        if type(binding_index) is not int or not 0 <= binding_index < len(self._model.bindings):
            raise ValueError('exact original binding ordinal required')
        returned = self._normal_route(binding_index)
        if returned is None:
            return {'normal_return': None, 'frontiers': [{'reason': 'NO_NORMAL_RETURN_INTERFACE'}]}
        pending = deque([(returned.caller, returned.caller_body, returned.landing_value, 0)])
        seen, nodes, routes, limits = set(), [], [], set()
        frontiers = _DependencyFrontiers(max_nodes + max_routes, limits)
        outgoing = {}
        for number, binding in enumerate(self._model.bindings):
            caller, callee = _keys(binding)
            outgoing.setdefault((caller, binding.caller_body, binding.call.core_operation), []).append((number, binding, callee))

        def append(kind, source, target, depth, *, expand=True, **details):
            if len(routes) >= max_routes:
                limits.add('ROUTE_BUDGET')
                return
            routes.append({'kind': kind, 'source': _endpoint(*source), 'consumer': _endpoint(*target),
                           'is_reference_alias': False, **details})
            if expand and target not in seen:
                if len(pending) >= max_nodes:
                    limits.add('PENDING_NODE_BUDGET')
                else:
                    pending.append((*target, depth + 1))

        while pending and len(seen) < max_nodes:
            invocation, namespace, value_id, depth = pending.popleft()
            key = invocation, namespace, value_id
            if key in seen:
                continue
            seen.add(key)
            body = self._body(namespace)
            index = body.index
            nodes.append(_endpoint(*key))
            if depth >= max_depth:
                limits.add('DEPTH_BUDGET')
                continue
            for site in index.consumers(value_id):
                if len(routes) >= max_routes:
                    limits.add('ROUTE_BUDGET')
                    break
                operation = index.operations[site.operation]
                state_or_protocol = site.use.role in (UseRole.STATE_CONTENT, UseRole.STATE_ORDER, UseRole.PROTOCOL)
                details = {'operation': encode(operation.id), 'use': encode(site.use.id),
                           'use_role': site.use.role.value, 'effects_complete': operation.effects_complete,
                           'dependence_basis': 'CONSERVATIVE_ORIGINAL_OPERATION_INTERFACE'}
                # A terminal Use is itself a consumer, even without an output.
                routes.append({'kind': 'ORIGINAL_USE_CONSUMER', 'source': _endpoint(*key),
                               'consumer_use': encode(site), 'consumer_body': encode(namespace),
                               'consumer_invocation': encode(invocation), 'is_reference_alias': False,
                               **details})
                if state_or_protocol:
                    frontiers.append({'at': _endpoint(*key), 'reason': 'STATE_OR_PROTOCOL_CONSUMER_NOT_EXPANDED',
                                      'use': encode(site.use.id), 'operation': encode(operation.id)})
                    continue
                if not operation.effects_complete:
                    frontiers.append({'at': _endpoint(*key), 'reason': 'INCOMPLETE_OPERATION_EFFECTS',
                                      'operation': encode(operation.id), 'internal_implementation_expanded': False})
                for number, binding, callee in outgoing.get((invocation, namespace, operation.id), ()):
                    for port in self._checked_ports(binding):
                        if port.actual_use == site.use.id:
                            append('ACTUAL_TO_FORMAL_CONSUMER', key,
                                   (callee, binding.callee_body, port.formal_value), depth,
                                   binding_index=number, conditions=encode(binding.conditions), **details)
                    receiver = getattr(binding, 'receiver', None)
                    if receiver is not None and receiver.callable_use == site.use.id:
                        append('BOUND_RECEIVER_PROJECTION_CONSUMER', key,
                               (callee, binding.callee_body, receiver.formal_value), depth,
                               binding_index=number, projection=receiver.projection,
                               observed_receiver=encode(receiver.observed), conditions=encode(binding.conditions), **details)
                for result in operation.results:
                    # Preserve the actual result type; world/protocol internals
                    # remain ports instead of recursively becoming data flow.
                    kind = type(index.values[result])
                    append('OPERATION_OUTPUT_DEPENDENCY', key, (invocation, namespace, result), depth,
                           expand=kind not in (StateVersionValue, ProtocolValue),
                           result_specific_dependency_established=False, **details)
                term = operation.terminator
                if term is None:
                    continue
                if type(term) is not Terminator:
                    frontiers.append({'at': _endpoint(*key), 'reason': 'SPECIAL_CONTROL_NOT_EXPANDED',
                                      'operation': encode(operation.id), 'terminator': type(term).__name__})
                for number, edge in enumerate(term.successors):
                    for position, actual in enumerate(edge.arguments):
                        if type(actual) is UseID and actual != site.use.id:
                            continue
                        if type(actual) not in (UseID, CompletionResult):
                            continue
                        value = index._block_records[edge.block].arguments[position]
                        kind = type(index.values[value])
                        append('CFG_CONSUMER_ARGUMENT' if type(actual) is UseID else 'COMPLETION_OUTPUT_DEPENDENCY',
                               key, (invocation, namespace, value), depth,
                               expand=kind not in (StateVersionValue, ProtocolValue),
                               selected_edge_required=self._edge_condition(index, operation, number),
                               completion=encode(actual) if type(actual) is CompletionResult else None,
                               result_specific_dependency_established=type(actual) is UseID, **details)
        if pending:
            limits.add('NODE_BUDGET')
        self._check()
        return {'normal_return': encode(returned), 'nodes': nodes, 'routes': routes, 'frontiers': frontiers,
                'limits_reached': sorted(limits), 'truncated': bool(limits), 'pending_nodes': len(pending),
                'max_nodes': max_nodes, 'max_depth': max_depth, 'max_routes': max_routes,
                'max_frontiers': frontiers.maximum,
                'runtime_occurrence_selected': False, 'content_equivalence_established': False}

    def query_bindings(self, binding_indices=None, *, max_bindings=16, max_queries=64,
                       max_nodes=128, max_depth=32, max_routes=512):
        """Query explicit ports, independent receivers, returns and consumers."""
        _positive(max_bindings, 1024, 'bindings'); _positive(max_queries, 4096, 'queries')
        indices = tuple(range(len(self._model.bindings))) if binding_indices is None else binding_indices
        if (type(indices) is not tuple or len(indices) > max_bindings or len(set(indices)) != len(indices)
                or any(type(i) is not int or not 0 <= i < len(self._model.bindings) for i in indices)):
            raise ValueError('bounded distinct original binding ordinals required')
        required = sum(len(getattr(self._model.bindings[i], 'ports', getattr(self._model.bindings[i], 'arguments', ())))
                       + int(getattr(self._model.bindings[i], 'receiver', None) is not None) + 2 for i in indices)
        if required > max_queries:
            raise ValueError('selected dependency queries exceed the independent ceiling')
        bounds = {'max_nodes': max_nodes, 'max_depth': max_depth, 'max_routes': max_routes}
        queries = []
        for ordinal in indices:
            binding = self._model.bindings[ordinal]
            ports = self._checked_ports(binding)
            for index in range(len(ports)):
                queries.append({'kind': 'EXPLICIT_ARGUMENT', 'binding_index': ordinal, 'actual_index': index,
                    'view': self.argument_origins(ordinal, index, include_computations=True, **bounds)})
            if getattr(binding, 'receiver', None) is not None:
                queries.append({'kind': 'RECEIVER', 'binding_index': ordinal,
                    'view': self.argument_origins(ordinal, receiver=True, include_computations=True, **bounds)})
            queries.append({'kind': 'NORMAL_RETURN_INPUTS', 'binding_index': ordinal,
                            'view': self.normal_return_origins(ordinal, **bounds)})
            queries.append({'kind': 'NORMAL_RETURN_CONSUMERS', 'binding_index': ordinal,
                            'view': self.return_consumers(ordinal, **bounds)})
        self._check()
        return {'schema': 'scar.source-dependency-batch-query', 'schema_version': 1,
                'model': encode(self._artifact), 'binding_indices': list(indices), 'queries': queries,
                'available_overlay_summary': self._model.summary(),
                'qualification': 'CONDITIONAL_CONSERVATIVE_ORIGINAL_INTERFACE_DEPENDENCIES',
                'max_queries': max_queries, 'max_bindings': max_bindings, 'per_query_bounds': bounds,
                'truncated': any(row['view'].get('truncated', False) for row in queries),
                'producer_inputs_replayed': False, 'runtime_occurrence_selected': False,
                'reference_identity_established': False, 'content_equivalence_established': False,
                'effects_or_ready_established': False, 'transformation_authorized': False,
                'whole_program_complete': False, 'costs': dict(self._counts)}


def query_source_dependency_batch(model, *, expected_sha256, binding_indices=None,
                                  budget=SourceReturnBudget(), **limits):
    return SourceDependencyBatchSession(model, expected_sha256=expected_sha256,
                                        budget=budget).query_bindings(binding_indices, **limits)
