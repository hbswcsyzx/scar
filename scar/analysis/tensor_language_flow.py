"""Conditional Tensor special-method declarations at source language operations.

The tables encode Python protocols, not ATen names or inferred return types.
Each result comes from a recorded declaration or an explicit truth conversion.
Candidate branches retain priority/NotImplemented obligations; they are neither
an execution schedule nor reference, storage, or in-place identity proofs.
"""
from collections import defaultdict, deque
from dataclasses import dataclass

from scar.analysis.tensor_return_flow import value_shape
from scar.ir.program import normal_links as F, tensor_values as V, binding_returns as R, python_bindings as B
from scar.ir.program.providers import ProviderFactReference


# AST constructor -> Python forward/reflected/in-place protocol names.
_BINARY = {
    'Add': ('__add__', '__radd__', '__iadd__'),
    'Sub': ('__sub__', '__rsub__', '__isub__'),
    'Mult': ('__mul__', '__rmul__', '__imul__'),
    'MatMult': ('__matmul__', '__rmatmul__', '__imatmul__'),
    'Div': ('__truediv__', '__rtruediv__', '__itruediv__'),
    'FloorDiv': ('__floordiv__', '__rfloordiv__', '__ifloordiv__'),
    'Mod': ('__mod__', '__rmod__', '__imod__'),
    'Pow': ('__pow__', '__rpow__', '__ipow__'),
    'LShift': ('__lshift__', '__rlshift__', '__ilshift__'),
    'RShift': ('__rshift__', '__rrshift__', '__irshift__'),
    'BitOr': ('__or__', '__ror__', '__ior__'),
    'BitXor': ('__xor__', '__rxor__', '__ixor__'),
    'BitAnd': ('__and__', '__rand__', '__iand__'),
}
_UNARY = {'UAdd': '__pos__', 'USub': '__neg__', 'Invert': '__invert__'}
# Rich comparisons reflect by swapping the comparison, not by an __r*__ name.
_COMPARE = {
    'Eq': ('__eq__', '__eq__'), 'NotEq': ('__ne__', '__ne__'),
    'Lt': ('__lt__', '__gt__'), 'LtE': ('__le__', '__ge__'),
    'Gt': ('__gt__', '__lt__'), 'GtE': ('__ge__', '__le__'),
}
_BASE_CONDITIONS = (
    'SPECIAL_METHOD_LOOKUP_USES_OPERAND_TYPE_DESCRIPTOR',
    'DECLARED_SIGNATURE_ACCEPTS_ACTUAL_ARGUMENTS',
    'NORMAL_LANGUAGE_PROTOCOL_COMPLETION',
)
_NATIVE_CONDITIONS = (
    'PARSER_SIGNATURE_ACCEPTS_ACTUAL_ARGUMENTS',
    'NORMAL_NATIVE_WRAPPER_RETURN',
    'NO_TORCH_FUNCTION_OVERRIDE_OR_MODE',
    'NO_TORCH_DISPATCH_OVERRIDE_OR_MODE',
)


@dataclass(frozen=True, slots=True)
class _Declaration:
    key: tuple
    declaration: ProviderFactReference
    return_source: ProviderFactReference
    shape: R.ValueShape
    conditions: tuple[str, ...]
    binding: B.PythonBindingID | None = None


class TensorLanguageFlow:
    def __init__(self, solver, units, return_flow):
        self.s, self.returns = solver, return_flow
        self.operations = []
        self.registered_units = set()
        self.admitted = set()
        self.watch = defaultdict(set)
        self.tensor_points = set()
        self.queue, self.pending = deque(), set()
        self.calls, self.frontiers = {}, {}
        self.events = 0
        self.method_symbols, self.alias_symbols, self.alias_members = defaultdict(list), defaultdict(list), defaultdict(list)
        self.registrations, self.method_wrappers = defaultdict(list), defaultdict(list)
        for index, row in enumerate(return_flow.stub['methods']):
            self.method_symbols[row['owner'] + '.' + row['name']].append((index, row))
        for index, row in enumerate(return_flow.stub.get('aliases', ())):
            self.alias_symbols[row['owner'] + '.' + row['name']].append((index, row))
            self.alias_members[row['name']].append((index, row))
        for index, row in enumerate(return_flow.stub.get('registrations', ())):
            self.registrations[row['name']].append((index, row))
        for definition in getattr(solver, 'bindings', {}).values():
            symbol = getattr(definition, 'cpp_symbol', None)
            if definition.kind is B.BindingKind.METHOD and symbol:
                self.method_wrappers[symbol].append(definition)
        for unit in units:
            self.register_unit(unit)
        self.drain()

    def register_unit(self, unit, *, eager=True):
        if unit.unit in self.registered_units:
            return
        self.registered_units.add(unit.unit)
        if eager:
            for index in range(len(getattr(unit, 'operations', ()))):
                self.admit(unit, index)

    def admit(self, unit, local_index):
        identity = unit.unit, local_index
        if identity in self.admitted:
            return
        self.admitted.add(identity)
        offset = self.s.offsets[unit.unit]
        operation = unit.operations[local_index]
        index = len(self.operations)
        self.operations.append((offset, operation))
        for operand in operation.operands:
            point = offset + operand
            self.watch[point].add(index)
            if point in self.tensor_points or any(self.is_tensor(value) for value in tuple(self.s.values.get(point, ()))):
                self.tensor_points.add(point)
                self.schedule(index)
        self.drain()

    def is_tensor(self, value):
        return (value[0] == 'declared_result'
                and self.returns.shapes[value[1], value[2]].kind
                in (R.ValueShapeKind.TENSOR, R.ValueShapeKind.SELF))

    def schedule(self, index):
        if index not in self.pending:
            self.pending.add(index)
            self.queue.append(index)

    def consume(self, point, value):
        if point in self.tensor_points or not self.is_tensor(value):
            return
        self.tensor_points.add(point)
        for index in self.watch[point]:
            self.schedule(index)
        self.drain()

    def drain(self):
        while self.queue:
            index = self.queue.popleft()
            self.pending.remove(index)
            self.events += 1
            self.visit(index)

    def declarations(self, member):
        """Resolve recorded direct aliases without evaluating their expressions."""
        for index, row in self.returns.methods.get(member, ()):
            if row['binding'] == 'INSTANCE':
                yield self.method_declaration(index, row)
        for index, row in self.alias_members.get(member, ()):
            yield from self.alias_declarations(index, row, frozenset())
        for index, row in self.registrations.get(member, ()):
            adapter = row.get('adapter')
            symbol = row.get('cpp_symbol')
            if adapter not in ('DIRECT', 'TYPE_ERROR_TO_NOT_IMPLEMENTED') or not symbol:
                continue
            conditions = (*row.get('conditions', ()),
                'CURRENT_TENSOR_REGISTRATION_TABLE_ADMISSION',
                'REGISTERED_CPP_SYMBOL_MATCHES_DECLARED_METHOD_WRAPPER')
            if adapter == 'TYPE_ERROR_TO_NOT_IMPLEMENTED':
                conditions += ('TYPE_ERROR_ADAPTER_CONVERTS_TYPE_ERROR_TO_NOT_IMPLEMENTED',
                               'REGISTERED_WRAPPER_DID_NOT_RAISE_TYPE_ERROR')
            source = ProviderFactReference(self.returns.artifact, '#/registrations/' + str(index))
            for definition in self.method_wrappers.get(symbol, ()):
                if definition.python_return is not None:
                    yield self.native_declaration(definition, source,
                        ('registration', index, definition.id.value), conditions)

    def method_declaration(self, index, row):
        source = ProviderFactReference(self.returns.artifact, '#/methods/' + str(index))
        return _Declaration(('method', row['id']), source, source,
                            value_shape(row['returns']), tuple(row['conditions']))

    def native_declaration(self, definition, source, key, conditions=()):
        return_source = ProviderFactReference(definition.source.artifact,
                                              definition.source.locator + '/python_return')
        return _Declaration(key, source, return_source, definition.python_return,
                            (*definition.conditions, *_NATIVE_CONDITIONS, *conditions), definition.id)

    def alias_declarations(self, index, row, visited):
        if index in visited or row['reference'] is None:
            return
        visited = visited | {index}
        source = ProviderFactReference(self.returns.artifact, '#/aliases/' + str(index))
        reference = row['reference']
        targets = [self.method_declaration(i, method)
                   for i, method in self.method_symbols.get(reference, ())
                   if method['binding'] == 'INSTANCE']
        for target_index, alias in self.alias_symbols.get(reference, ()):
            targets.extend(self.alias_declarations(target_index, alias, visited))
        if not targets:
            for definition in self.s.binding_symbols.get(reference, ()):
                if definition.python_return is None:
                    continue
                targets.append(self.native_declaration(definition, source, ('binding', definition.id.value)))
        for target in targets:
            yield _Declaration(('alias', row['id'], target.key), source, target.return_source,
                target.shape, (*row['conditions'], *target.conditions,
                    'DIRECT_DECLARED_ALIAS_REFERENCE_MATCHES_CURRENT_BINDING',
                    'ALIAS_TARGET_SPECIAL_METHOD_DESCRIPTOR_BINDING_ADMISSION'), target.binding)

    def routes(self, operation):
        """Yield receiver ordinal, member, branch, conversion and obligations."""
        action, selector = operation.action, operation.selector.value
        branch, conversion = V.OperatorBranch, V.OperatorResultConversion
        direct = conversion.DIRECT
        success = ('METHOD_RESULT_IS_NOT_NOT_IMPLEMENTED',)
        if action is F.LanguageOperationKind.UNARY:
            if selector in _UNARY:
                yield 0, _UNARY[selector], branch.UNARY, direct, ()
            elif selector == 'Not':
                yield 0, '__bool__', branch.TRUTH_BOOL, conversion.NEGATED_TRUTH_VALUE, (
                    'BOOL_METHOD_RETURNS_BOOL', 'TRUTH_CONVERSION_SUCCEEDS')
                yield 0, '__len__', branch.TRUTH_LENGTH, conversion.NEGATED_TRUTH_VALUE, (
                    'BOOL_METHOD_ABSENT', 'LENGTH_RESULT_IS_NONNEGATIVE_INDEX',
                    'TRUTH_CONVERSION_SUCCEEDS')
            return
        if action in (F.LanguageOperationKind.BINARY, F.LanguageOperationKind.INPLACE_BINARY):
            names = _BINARY.get(selector)
            if names is None:
                return
            forward, reflected, inplace = names
            fallback = ()
            if action is F.LanguageOperationKind.INPLACE_BINARY:
                yield 0, inplace, branch.INPLACE, direct, success
                fallback = ('INPLACE_METHOD_ABSENT_OR_RETURNED_NOT_IMPLEMENTED',)
            yield 0, forward, branch.FORWARD, direct, (*fallback, *success,
                'RHS_REFLECTED_HAS_NO_SUBTYPE_PRIORITY_OR_RETURNED_NOT_IMPLEMENTED')
            yield 1, reflected, branch.REFLECTED_SUBTYPE_PRIORITY, direct, (*fallback, *success,
                'RHS_TYPE_IS_STRICT_SUBCLASS_OF_LHS_TYPE',
                'DISTINCT_REFLECTED_IMPLEMENTATION_HAS_SUBTYPE_PRIORITY')
            yield 1, reflected, branch.REFLECTED_FALLBACK, direct, (*fallback, *success,
                'OPERAND_RUNTIME_TYPES_DIFFER', 'NO_REFLECTED_SUBTYPE_PRIORITY',
                'FORWARD_METHOD_ABSENT_OR_RETURNED_NOT_IMPLEMENTED')
            return
        if action is F.LanguageOperationKind.COMPARE:
            if selector in _COMPARE:
                forward, reflected = _COMPARE[selector]
                yield 0, forward, branch.FORWARD, direct, (*success,
                    'RHS_NOT_STRICT_SUBTYPE_OR_REFLECTED_COMPARISON_RETURNED_NOT_IMPLEMENTED')
                # Rich comparison gives the subtype priority even when the
                # implementation is inherited; unlike arithmetic, fallback
                # can also call the other operand when their types are equal.
                yield 1, reflected, branch.REFLECTED_SUBTYPE_PRIORITY, direct, (*success,
                    'RHS_TYPE_IS_STRICT_SUBCLASS_OF_LHS_TYPE')
                yield 1, reflected, branch.REFLECTED_FALLBACK, direct, (*success,
                    'NO_REFLECTED_SUBTYPE_PRIORITY',
                    'FORWARD_COMPARISON_ABSENT_OR_RETURNED_NOT_IMPLEMENTED')
            elif selector in ('In', 'NotIn'):
                converted = conversion.TRUTH_VALUE if selector == 'In' else conversion.NEGATED_TRUTH_VALUE
                yield 1, '__contains__', branch.CONTAINS, converted, (
                    'CONTAINS_METHOD_SELECTED_INSTEAD_OF_ITERATION_FALLBACK',
                    'MEMBERSHIP_RESULT_TRUTH_CONVERSION_SUCCEEDS')
            # Is/IsNot and exhausted Eq/NotEq identity fallbacks do not call a
            # Tensor special method. Their original language operation stays.

    def visit(self, index):
        offset, operation = self.operations[index]
        expected = 1 if operation.action is F.LanguageOperationKind.UNARY else 2
        if len(operation.operands) != expected:
            self.frontiers[index, 'arity'] = 'LANGUAGE_OPERATION_ARITY_DIFFERS'
            return
        operands = tuple(offset + p for p in operation.operands)
        result = offset + operation.result
        for ordinal, member, branch, conversion, obligations in self.routes(operation):
            receiver = operands[ordinal]
            if receiver not in self.tensor_points:
                continue
            declarations = tuple(self.declarations(member))
            if not declarations:
                self.frontiers[index, branch, member] = ('TENSOR_ALIAS_TARGET_UNRESOLVED'
                    if member in self.alias_members else 'TENSOR_METHOD_DECLARATION_UNAVAILABLE')
            for declaration in declarations:
                identity = index, branch, declaration.key
                if identity in self.calls:
                    continue
                conditions = (*declaration.conditions, *_BASE_CONDITIONS, *obligations)
                arguments = tuple(point for i, point in enumerate(operands) if i != ordinal)
                self.calls[identity] = V.DeclaredOperatorCall(
                    action=operation.action, selector=operation.selector,
                    operands=tuple(self.s.gp(p) for p in operands), receiver=self.s.gp(receiver),
                    arguments=tuple(self.s.gp(p) for p in arguments), result=self.s.gp(result),
                    world=self.s.gp(offset + operation.world),
                    result_world=self.s.gp(offset + operation.result_world), member=member,
                    branch=branch, declaration=declaration.declaration, conditions=conditions,
                    result_conversion=conversion, binding=declaration.binding,
                    native_selector=(None if declaration.binding is None
                                     else self.s.bindings[declaration.binding.value].selector))
                shape = (declaration.shape if conversion is V.OperatorResultConversion.DIRECT
                         else R.ValueShape(R.ValueShapeKind.SCALAR, python_type='bool'))
                self.returns.emit(('operator', *identity), result, result, shape,
                                  declaration.return_source, conditions)
