"""Dictionary-display checks using the module's original exception/world ABI."""
from __future__ import annotations

import ast
from collections import defaultdict

from scar.ir.program.model import BlockArgument, ExitKind, OperationResult, ReferenceValue, StateVersionValue, TerminatorKind
from scar.ir.program.structured import PythonProtocolKind as K


def _need(condition, detail):
    if not condition:
        raise ValueError('module dictionary: ' + detail)


class ModuleDictionaryValidator:
    """Reuse existing primitives; rederive their order, operands and handoff."""
    def __init__(self, *, overlay, blocks, operations, values, protocols, invoke,
                 source_reference, exception_holds, ref_type, state_type):
        self.overlay, self.blocks, self.operations, self.values = overlay, blocks, operations, values
        self.protocols, self.invoke, self.source = protocols, invoke, source_reference
        self.exception_holds, self.ref_type, self.state_type = exception_holds, ref_type, state_type
        self.links = {row.operation: row for row in overlay.operation_links}
        self.use_links = {(row.operation, row.use): row for row in overlay.use_links}
        self.by_source = defaultdict(set)
        self.next, self.previous, self.producers, self.results = {}, defaultdict(list), defaultdict(list), {}
        self.transfer_uses = {}
        for row in overlay.operation_links:
            self.by_source[row.source].add(row.operation)
        for block in blocks.values():
            for number, identity in enumerate(block.operations):
                operation = operations[identity]
                term = operation.terminator
                successor = None
                if term is None and number + 1 < len(block.operations):
                    successor = block.operations[number + 1]
                elif term is not None:
                    edges = ([edge for edge in term.successors if edge.kind is ExitKind.NORMAL]
                             if term.kind is TerminatorKind.INVOKE else list(term.successors)
                             if term.kind is TerminatorKind.JUMP else [])
                    if len(edges) == 1 and blocks[edges[0].block].operations:
                        successor = blocks[edges[0].block].operations[0]
                    if term.kind is TerminatorKind.INVOKE:
                        for edge in edges:
                            for value in blocks[edge.block].arguments[:-1]:
                                self.producers[value].append(identity)
                if successor is not None:
                    self.next[identity] = successor
                    self.previous[successor].append(identity)

    def result(self, node, expression_value):
        source = self.source(node)
        if source in self.results:
            return self.results[source][0]
        primitives = {identity for identity in self.by_source[source]
            if identity in self.protocols and self.protocols[identity].kind in (K.BUILD_MAP, K.MAP_ADD, K.DICT_UPDATE)}
        _need(primitives, 'display has no original allocation/update primitives')
        local_sources = {self.source(child) for child in ast.walk(node) if isinstance(child, ast.expr)}
        local = set().union(*(self.by_source[reference] for reference in local_sources))
        cursor = next(iter(primitives))
        seen = set()
        while True:
            _need(cursor not in seen, 'display normal corridor cycles')
            seen.add(cursor)
            before = [identity for identity in self.previous[cursor] if identity in local]
            if not before:
                break
            _need(len(before) == 1, 'display has ambiguous normal entry ordering')
            cursor = before[0]
        corridor = []
        seen = set()
        while cursor in local:
            _need(cursor not in seen, 'display normal corridor revisits an operation')
            seen.add(cursor)
            corridor.append(cursor)
            cursor = self.next.get(cursor)
        ordered = [self.operations[identity] for identity in corridor if identity in primitives]
        _need({operation.id for operation in ordered} == primitives, 'display primitive lies outside its normal corridor')
        positions = {identity: index for index, identity in enumerate(corridor)}
        state = None
        for identity in corridor:
            operation = self.operations[identity]
            worlds = [use.value for use in operation.uses if type(self.values[use.value]) is StateVersionValue]
            if worlds:
                state = worlds[0] if state is None else state
                _need(all(value == state for value in worlds), 'normal action bypasses its preceding post-world')
            term = operation.terminator
            if term is not None and term.kind is TerminatorKind.INVOKE:
                edge, = (edge for edge in term.successors if edge.kind is ExitKind.NORMAL)
                state = self.blocks[edge.block].arguments[-1]
            else:
                states = [value for value in operation.results if type(self.values[value]) is StateVersionValue]
                if states:
                    _need(len(states) == 1, 'display action has multiple unmodeled state results')
                    state = states[0]
        held, local_values, events, failures = [], set(), [], []
        position = 0

        def child(expression):
            value = expression_value(expression)
            if isinstance(expression, ast.Dict) and self.source(expression) in self.results:
                producer = self.results[self.source(expression)][1]
            else:
                origin = self.values[value].origin
                candidates = ([origin.operation] if type(origin) is OperationResult else
                              self.producers[value] if type(origin) is BlockArgument else [])
                _need(len(candidates) <= 1, 'child result has ambiguous original producer')
                producer = candidates[0] if candidates else None
            if producer is not None:
                events.append(producer)
            child_sources = {self.source(part) for part in ast.walk(expression) if isinstance(part, ast.expr)}
            for identity in corridor:
                if self.links[identity].source not in child_sources:
                    continue
                operation = self.operations[identity]
                if operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE:
                    failed, = (edge.block for edge in operation.terminator.successors if edge.kind is ExitKind.RAISE)
                    failures.append((failed, tuple(held), set(held)))
            local_values.add(value)
            held.append(value)
            return value

        def take(kind, inputs=(), consumed=()):
            nonlocal position
            _need(position < len(ordered), 'display primitive sequence ended early')
            operation = ordered[position]
            position += 1
            _need(self.protocols[operation.id].kind is kind and operation.callee is None
                and self.links[operation.id].semantic_operation is None
                and tuple(use.value for use in operation.uses[:-1]) == tuple(inputs)
                and all(type(self.values[value]) is ReferenceValue for value in inputs),
                'allocation/update kind or ordered child references changed')
            normal, failure = self.invoke(operation,
                (self.ref_type, self.state_type) if kind is K.BUILD_MAP else (self.state_type,), memory=True)
            if consumed:
                _need(tuple(held[-len(consumed):]) == tuple(consumed), 'consumed inputs are not the current stack suffix')
                del held[-len(consumed):]
            failures.append((failure.id, tuple(held), None))
            events.append(operation.id)
            if kind is K.BUILD_MAP:
                value = normal.arguments[0]
                local_values.add(value)
                held.append(value)
                return value

        def run(begin, end):
            incremental = (end - begin) * 2 > 30
            receiver = take(K.BUILD_MAP) if incremental else None
            pairs = []
            for index in range(begin, end):
                key = child(node.keys[index])
                value = child(node.values[index])
                if incremental:
                    take(K.MAP_ADD, (receiver, key, value), (key, value))
                else:
                    pairs.extend((key, value))
            return receiver if incremental else take(K.BUILD_MAP, pairs, pairs)

        def append_run(receiver, begin, end):
            update = run(begin, end)
            if receiver is None:
                return update
            take(K.DICT_UPDATE, (receiver, update), (update,))
            return receiver

        receiver, elements = None, 0
        for index, key in enumerate(node.keys):
            if key is None:
                if elements:
                    receiver = append_run(receiver, index - elements, index)
                    elements = 0
                if receiver is None:
                    receiver = take(K.BUILD_MAP)
                update = child(node.values[index])
                take(K.DICT_UPDATE, (receiver, update), (update,))
            elif elements * 2 > 30:
                receiver = append_run(receiver, index - elements, index + 1)
                elements = 0
            else:
                elements += 1
        if elements:
            receiver = append_run(receiver, len(node.keys) - elements, len(node.keys))
        if receiver is None:
            receiver = take(K.BUILD_MAP)
        _need(position == len(ordered) and held == [receiver], 'display has extra primitives or untransferred references')
        _need(all(identity in positions for identity in events)
            and all(positions[left] < positions[right] for left, right in zip(events, events[1:])),
            'key/value evaluation, allocation or update order differs from the source protocol')
        for block, expected, selected in failures:
            actual = self.exception_holds(block, self.operations, self.protocols, self.blocks, self.use_links)
            selected = local_values if selected is None else selected
            _need(tuple(value for value in actual if value in selected) == expected,
                'exception handoff changed retained/consumed display references')
        # The final reference has legitimate construction/retention uses
        # before its outer consumer. Only these checked normal/error corridors
        # may precede STORE_NAME; a hold on either store outcome is not allowed.
        checked = set(corridor)
        for block, _, _ in failures:
            cursor, visited = (block, 0), set()
            while cursor not in visited:
                visited.add(cursor)
                current = self.blocks[cursor[0]]
                operation = self.operations[current.operations[cursor[1]]]
                checked.add(operation.id)
                marker = self.protocols.get(operation.id)
                if marker is not None and marker.kind.value in (
                        'FRAME_EXIT_EXCEPTION_PACKET', 'FRAME_EXIT', 'FUNCTION_HANDLED_CONTEXT_ENTER'):
                    break
                if operation.terminator is None:
                    cursor = current.id, cursor[1] + 1
                else:
                    edge, = operation.terminator.successors
                    cursor = edge.block, 0
        self.transfer_uses[receiver] = {(identity, use.id) for identity in checked
            for use in self.operations[identity].uses if use.value == receiver}
        self.results[source] = receiver, ordered[-1].id
        return receiver
