"""Bounded navigation of original source ports across recorded call layers.

This is a read-only view over SourceReturnSession's existing body indexes and
call overlay. It never merges body namespaces, invents value identities or
treats an arbitrary operation as a copy.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

from scar.analysis.source_return_bindings import SourceReturnSession
from scar.ir.program.bindings import BindingState
from scar.ir.program.ids import UseID
from scar.ir.program.model import BlockArgument, CompletionResult, ExitKind, OperationResult, TerminatorKind, UseRole
from scar.ir.program.native import ExitPortRef
from scar.ir.record_codec import encode


class SourceDependencySession(SourceReturnSession):
    def _normal_route(self, binding_index):
        binding = self._model.bindings[binding_index]
        callee = self._body(binding.callee_body)
        region = callee.index.regions[binding.callee_body.region]
        if not any(callee.index.exit_port_uses(ExitPortRef(region.id, exit_.name, 0))
                   for exit_ in region.exits if exit_.kind is ExitKind.NORMAL):
            return None
        return self.normal_return(binding_index)

    def _checked_ports(self, binding):
        """Validate body endpoints without requiring a normal callee return."""
        caller, callee = self._body(binding.caller_body), self._body(binding.callee_body)
        call = caller.index.operations[binding.call.core_operation]
        if not (binding.caller_code.source == binding.caller_body.source
                and binding.callee_code.source == binding.callee_body.source
                and binding.call.execution_owner == caller.interface.definition
                and binding.call.core_region == caller.index.graph.root
                and call.terminator is not None and call.terminator.kind is TerminatorKind.INVOKE
                and call.invoke_arguments and call.invoke_arguments[0] == binding.call.callee_use
                and caller.index.use_site(binding.call.callee_use).operation == call.id
                and caller.index.use_site(binding.call.callee_use).use.value == binding.call.callee_value):
            raise ValueError('source dependency call differs from original body interface')
        ports = getattr(binding, 'ports', None)
        if ports is None:
            ports = binding.arguments
        for port in ports:
            use = caller.index.use_site(port.actual_use)
            if not (port.actual_body == caller.namespace and port.formal_body == callee.namespace
                    and use.operation == call.id and use.use.value == port.actual_value
                    and any(p.slot == port.formal_slot and p.value == port.formal_value
                            for p in callee.interface.parameters)):
                raise ValueError('source dependency argument differs from original Use/formal')
        receiver = getattr(binding, 'receiver', None)
        if receiver is not None:
            use = caller.index.use_site(receiver.callable_use)
            if not (receiver.actual_body == caller.namespace and receiver.formal_body == callee.namespace
                    and receiver.operation == call.id and use.operation == call.id
                    and receiver.callable_use == binding.call.callee_use
                    and use.use.value == receiver.callable_value
                    and any(p.slot == receiver.formal_slot and p.value == receiver.formal_value
                            for p in callee.interface.parameters)):
                raise ValueError('source dependency receiver differs from original callable/formal')
        return ports

    def argument_origins(self, binding_index, actual_index=None, *, receiver=False,
                         max_nodes=256, max_depth=64, max_routes=1024, include_computations=False):
        """Follow conditional local copies and actual/formal/return interfaces.

        Computations, unknown binding writes and unselected call completions
        remain explicit boundaries. This establishes routes, not permission to
        hoist a computation or reuse its contents.
        """
        if type(include_computations) is not bool:
            raise ValueError('computation expansion must be an exact Boolean')
        if type(receiver) is not bool or (receiver and actual_index is not None):
            raise ValueError('select an explicit argument or the independent receiver')
        for value in (binding_index, max_nodes, max_depth, max_routes):
            if type(value) is not int or value < 0:
                raise ValueError('exact nonnegative dependency selector/bound required')
        if not receiver and (type(actual_index) is not int or actual_index < 0):
            raise ValueError('exact nonnegative actual argument index required')
        if (not 1 <= max_nodes <= 100_000 or not 1 <= max_depth <= 1024
                or not 1 <= max_routes <= 100_000):
            raise ValueError('dependency traversal bound out of range')
        if binding_index >= len(self._model.bindings):
            raise IndexError(binding_index)
        selected = self._model.bindings[binding_index]
        ports = self._checked_ports(selected)
        if not receiver and actual_index >= len(ports):
            raise IndexError(actual_index)
        caller = getattr(selected, 'caller', None)
        if caller is None:
            caller = selected.entry.caller
        if receiver:
            receiver_port = getattr(selected, 'receiver', None)
            if receiver_port is None:
                raise ValueError('selected call has no independent receiver port')
            selected_port = receiver_port
        else:
            port = ports[actual_index]
            selected_port = port
        callee = getattr(selected, 'callee', None)
        if callee is None:
            callee = selected.entry.callee
        # Begin at the selected formal, so the selected call's own boundary is
        # part of the route as well as any higher caller layers.
        start = callee, selected.callee_body, selected_port.formal_value, 0
        view = self._value_dependencies((start,), max_nodes=max_nodes, max_depth=max_depth,
                                        max_routes=max_routes, include_computations=include_computations)
        returned = self._normal_route(binding_index)
        caller_index = self._body(selected.caller_body).index
        return {'schema': 'scar.source-dependency-query', 'schema_version': 1,
                'model': encode(self._artifact),
                'selector': {'binding_index': binding_index, 'actual_index': actual_index,
                             'receiver': receiver},
                'selected_port': encode(selected_port),
                'qualification': 'CONDITIONAL_ORIGINAL_SOURCE_INTERFACE_ROUTES',
                **view,
                'overlay_summary': self._model.summary(),
                'normal_return': encode(returned),
                'caller_result_consumers': encode(caller_index.consumers(returned.landing_value)) if returned is not None else [],
                'normal_return_interface_present': returned is not None,
                'producer_inputs_replayed': False, 'runtime_branch_selected': False,
                'content_equivalence_established': False, 'transformation_authorized': False,
                'whole_program_complete': False, 'costs': dict(self._counts)}


    def _value_dependencies(self, starts, *, max_nodes, max_depth, max_routes,
                            include_computations):
        pending = deque(starts)
        seen, nodes, routes, leaves, frontiers = set(), [], [], [], []
        limits, checked = set(), set()
        local = {}
        incoming_calls, outgoing_calls = {}, {}
        for number, binding in enumerate(self._model.bindings):
            c = getattr(binding, 'caller', None)
            d = getattr(binding, 'callee', None)
            if c is None:
                c, d = binding.entry.caller, binding.entry.callee
            incoming_calls.setdefault((d, binding.callee_body), []).append((number, binding, c))
            outgoing_calls.setdefault((c, binding.caller_body, binding.call.core_operation), []).append((number, binding, d))

        def endpoint(invocation, body, value):
            return {'invocation': encode(invocation), 'body': encode(body), 'value': encode(value)}

        while pending and len(seen) < max_nodes:
            invocation, namespace, value_id, depth = pending.popleft()
            key = invocation, namespace, value_id
            if key in seen:
                continue
            seen.add(key)
            body = self._body(namespace)
            index = body.index
            value = index.values[value_id]
            current = endpoint(invocation, namespace, value_id)
            nodes.append(current)
            if depth >= max_depth:
                frontiers.append({'at': current, 'reason': 'DEPTH_BUDGET'})
                limits.add('DEPTH_BUDGET')
                continue
            if namespace not in local:
                incoming = {}
                for op in index.graph.operations:
                    for number, edge in enumerate(getattr(op.terminator, 'successors', ())):
                        incoming.setdefault(edge.block, []).append((op, number, edge))
                local[namespace] = (
                    {row.normal_result: row for row in index.graph.binding_reads
                     if row.normal_result is not None},
                    {row.value: row for row in index.graph.binding_definitions}, incoming)
            reads, definitions, incoming = local[namespace]

            def follow(kind, target_invocation, target_body, target_value, *, expand=True, **details):
                if len(routes) >= max_routes:
                    if 'ROUTE_BUDGET' not in limits:
                        frontiers.append({'at': current, 'reason': 'ROUTE_BUDGET'})
                        limits.add('ROUTE_BUDGET')
                    return
                target = endpoint(target_invocation, target_body, target_value)
                routes.append({'kind': kind, 'consumer': current, 'source': target, **details})
                if not expand:
                    return
                if (target_invocation, target_body, target_value) not in seen:
                    if len(pending) >= max_nodes:
                        if 'PENDING_NODE_BUDGET' not in limits:
                            frontiers.append({'at': current, 'reason': 'PENDING_NODE_BUDGET'})
                            limits.add('PENDING_NODE_BUDGET')
                        return
                    pending.append((target_invocation, target_body, target_value, depth + 1))

            read = reads.get(value_id)
            definition = definitions.get(value_id)
            if read is not None:
                source = index.use_site(read.binding)
                follow('LOCAL_BINDING_READ', invocation, namespace, source.use.value,
                       operation=encode(read.operation), use=encode(read.binding),
                       condition='READ_COMPLETES_NORMALLY')
            elif definition is not None:
                if definition.state is BindingState.BOUND:
                    source = index.use_site(definition.payload)
                    follow('LOCAL_BINDING_PAYLOAD', invocation, namespace, source.use.value,
                           use=encode(definition.payload))
                else:
                    frontiers.append({'at': current, 'reason': 'LOCAL_BINDING_' + definition.state.value})
            elif type(value.origin) is BlockArgument:
                origin = value.origin
                if origin.block == index.regions[namespace.region].entry:
                    matched = False
                    for number, binding, upstream in incoming_calls.get((invocation, namespace), ()):
                        arguments = self._checked_ports(binding) if number not in checked else getattr(binding, 'ports', None)
                        checked.add(number)
                        if arguments is None:
                            arguments = binding.arguments
                        for argument in arguments:
                            if argument.formal_value == value_id:
                                matched = True
                                follow('ACTUAL_TO_FORMAL', upstream, binding.caller_body,
                                       argument.actual_value, binding_index=number,
                                       actual_use=encode(argument.actual_use),
                                       conditions=encode(binding.conditions))
                        receiver_projection = getattr(binding, 'receiver', None)
                        if receiver_projection is not None and receiver_projection.formal_value == value_id:
                            matched = True
                            follow('BOUND_CALLABLE_RECEIVER_PROJECTION', upstream, binding.caller_body,
                                   receiver_projection.callable_value, binding_index=number,
                                   callable_use=encode(receiver_projection.callable_use),
                                   projection=receiver_projection.projection, observed_receiver=encode(receiver_projection.observed),
                                   is_reference_alias=False, conditions=encode(binding.conditions))
                    if not matched:
                        frontiers.append({'at': current, 'reason': 'ENTRY_NOT_BOUND_IN_SELECTED_OVERLAY'})
                else:
                    alternatives = incoming.get(origin.block, ())
                    if not alternatives:
                        frontiers.append({'at': current, 'reason': 'BLOCK_WITHOUT_INCOMING_ROUTE'})
                    for op, edge_number, edge in alternatives:
                        actual = edge.arguments[origin.index]
                        condition = self._edge_condition(index, op, edge_number)
                        if type(actual) is UseID:
                            source = index.use_site(actual)
                            follow('CFG_ARGUMENT', invocation, namespace, source.use.value,
                                   use=encode(actual), use_role=source.use.role.value, selected_edge_required=condition)
                        elif (type(actual) is CompletionResult and actual.index == 0
                              and edge.kind is ExitKind.NORMAL):
                            matched = False
                            for number, binding, downstream in outgoing_calls.get((invocation, namespace, op.id), ()):
                                returned = self._normal_route(number)
                                if (returned is None or returned.landing_value != value_id
                                        or returned.completion_edge.operation != op.id
                                        or returned.completion_edge.successor_index != edge_number):
                                    continue
                                matched = True
                                for site in returned.sites:
                                    follow('CALLEE_NORMAL_RETURN', downstream, binding.callee_body,
                                           site.value, binding_index=number,
                                           return_use=encode(site.use),
                                           conditions=encode(returned.conditions),
                                           return_site_condition=encode(site.condition),
                                           selected_edge_required=condition)
                            if not matched:
                                if include_computations:
                                    self._operation_dependencies(index, op, invocation, namespace, current, follow, frontiers,
                                        kind='COMPLETION_INPUT_DEPENDENCY', incoming=incoming, selected_edge_required=condition,
                                        completion=encode(actual))
                                else:
                                    frontiers.append({'at': current, 'reason': 'CALL_COMPLETION_NOT_BOUND_IN_SELECTED_OVERLAY',
                                                      'edge': condition, 'completion': encode(actual)})
                        elif type(actual) is CompletionResult and include_computations:
                            self._operation_dependencies(index, op, invocation, namespace, current, follow, frontiers,
                                kind='COMPLETION_INPUT_DEPENDENCY', incoming=incoming, selected_edge_required=condition,
                                completion=encode(actual))
                        else:
                            frontiers.append({'at': current, 'reason': 'NON_REFERENCE_OR_RESUMABLE_EDGE_INPUT',
                                              'edge': condition, 'argument': encode(actual)})
            elif type(value.origin) is OperationResult:
                producer = index.operations[value.origin.operation]
                if include_computations:
                    self._operation_dependencies(index, producer, invocation, namespace, current, follow, frontiers,
                        kind='OPERATION_INPUT_DEPENDENCY', incoming=incoming, result_index=value.origin.index)
                else:
                    frontiers.append({'at': current, 'reason': 'COMPUTATION_BOUNDARY',
                                      'producer': encode(producer.id),
                                      'operand_dependencies': encode(producer.uses)})
            else:
                leaves.append({'at': current, 'origin': encode(value.origin)})
        self._check()
        return {'nodes': nodes, 'routes': routes, 'leaves': leaves, 'frontiers': frontiers,
                'truncated': bool(pending) or bool(limits), 'pending_nodes': len(pending),
                'max_nodes': max_nodes, 'max_depth': max_depth, 'max_routes': max_routes,
                'limits_reached': sorted(limits), 'computations_expanded': include_computations,
                'runtime_occurrence_selected': False}

    @staticmethod
    def _edge_condition(index, operation, successor_index):
        term = operation.terminator
        edge = term.successors[successor_index]
        result = {'operation': encode(operation.id), 'successor_index': successor_index,
                  'kind': encode(getattr(edge, 'kind', None))}
        if term.condition is not None:
            site = index.use_site(term.condition)
            result['guard'] = encode(site)
        return result

    def _operation_dependencies(self, index, operation, invocation, namespace, current,
                                follow, frontiers, *, kind, incoming, **details):
        """Original operation inputs are conservative dependencies, never copies.

        State and protocol ports stay visible but their implementation is not
        expanded as though it were ordinary reference/data flow.
        """
        if not operation.effects_complete:
            frontiers.append({'at': current, 'reason': 'INCOMPLETE_OPERATION_EFFECTS',
                              'operation': encode(operation.id),
                              'internal_implementation_expanded': False})
        if not operation.uses:
            frontiers.append({'at': current, 'reason': 'OPERATION_WITHOUT_DECLARED_INPUTS',
                              'operation': encode(operation.id)})
        for use in operation.uses:
            state = use.role in (UseRole.STATE_CONTENT, UseRole.STATE_ORDER)
            protocol = use.role is UseRole.PROTOCOL
            follow(kind, invocation, namespace, use.value, expand=not(state or protocol),
                   operation=encode(operation.id), use=encode(use.id), use_role=use.role.value,
                   dependence_basis='CONSERVATIVE_ORIGINAL_OPERATION_INTERFACE',
                   is_reference_alias=False, result_specific_dependency_established=False,
                   effects_complete=operation.effects_complete,
                   accesses=encode(tuple(access for access in operation.accesses
                                         if use.id in (access.before, access.reference))),
                   implementation_boundary=('STATE_INPUT' if state else 'PROTOCOL_INPUT' if protocol else None),
                   **details)
        block = index._operation_blocks[operation.id]
        # Expose immediate original guards, without claiming postdominator-based
        # control dependence or a selected dynamic loop iteration.
        for predecessor, number, edge in incoming.get(block, ()):
            term = predecessor.terminator
            if term.condition is not None:
                site = index.use_site(term.condition)
                follow('CONTROL_GUARD_DEPENDENCY', invocation, namespace, site.use.value,
                       operation=encode(predecessor.id), use=encode(site.use.id),
                       use_role=site.use.role.value,
                       selected_edge_required=self._edge_condition(index, predecessor, number),
                       is_reference_alias=False, runtime_occurrence_selected=False)

    def normal_return_origins(self, binding_index, *, max_nodes=256, max_depth=64,
                              max_routes=1024):
        """Input dependencies of all original conditional normal return sites."""
        for value, maximum in ((max_nodes, 100_000), (max_depth, 1024), (max_routes, 100_000)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError('dependency traversal bound out of range')
        if type(binding_index) is not int or not 0 <= binding_index < len(self._model.bindings):
            raise ValueError('exact original binding ordinal required')
        returned = self._normal_route(binding_index)
        if returned is None:
            return {'normal_return': None, 'frontiers': [{'reason': 'NO_NORMAL_RETURN_INTERFACE'}]}
        starts = tuple((returned.callee, returned.callee_body, site.value, 0)
                       for site in returned.sites)
        view = self._value_dependencies(starts, max_nodes=max_nodes, max_depth=max_depth,
                                       max_routes=max_routes, include_computations=True)
        return {'normal_return': encode(returned), **view,
                'qualification': 'CONDITIONAL_ORIGINAL_OPERATION_INPUT_DEPENDENCIES',
                'return_site_conditions': [encode(site) for site in returned.sites],
                'content_equivalence_established': False, 'transformation_authorized': False}


def query_source_dependencies_cli(args):
    import json
    session = SourceDependencySession(args.model, expected_sha256=args.sha256)
    result = session.argument_origins(args.binding_index, args.actual_index,
                                     receiver=args.receiver,
                                     max_nodes=args.max_nodes, max_depth=args.max_depth,
                                     max_routes=args.max_routes)
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.out:
        with Path(args.out).open('x', encoding='utf-8') as stream:
            stream.write(payload)
    else:
        print(payload, end='')
    return 0
