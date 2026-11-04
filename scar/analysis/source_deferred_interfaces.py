"""Deferred logical entry interfaces over original accepted F2/F3 tables.

Capture forwarding is shared per original hop, not reconstructed from names.
Source-order formals and cell handles are not native frame/freevar layouts.
"""
from collections import defaultdict
from dataclasses import replace

from scar.ir.program import source_productions as P


class DeferredInterfaceIndex:
    def __init__(self, source):
        self.source = source
        self.scopes = {}
        for index, scope in enumerate(source.context.material.scopes):
            if scope.kind in ('FUNCTION', 'LAMBDA', 'GENERATOR_EXPRESSION'):
                self.scopes[scope.owner.occurrence] = index
        self.ports = defaultdict(list)
        for ordinal, port in enumerate(source.frontend.roles.ports):
            self.ports[port.site].append(ordinal)
        data = source.frontend.bindings
        active = set()
        for demand in data.captures:
            if demand.activation in ('TEMPLATE_ONLY', 'TYPE_GRAMMAR'):
                continue
            hop = demand.hop
            while hop is not None and hop not in active:
                active.add(hop)
                hop = data.relays[hop].parent
        self.captures = defaultdict(list)
        for ordinal, hop in enumerate(data.relays):
            if ordinal in active:
                self.captures[hop.scope].append(ordinal)
        self.yield_owners, self.await_owners = set(), set()
        for ordinal, node in enumerate(source.context.syntax.nodes):
            if node.constructor in ('Yield', 'YieldFrom', 'Await'):
                target = self.await_owners if node.constructor == 'Await' else self.yield_owners
                target.add(source.context.entry_context(ordinal).owner.occurrence)
        self._parameters = {}

    def parameters(self, occurrence):
        if occurrence in self._parameters:
            return self._parameters[occurrence]
        roles, syntax = self.source.roles, self.source.context.syntax
        node = syntax.nodes[occurrence]
        if node.constructor == 'GeneratorExp':
            generators = roles.field(occurrence, 'generators')
            clause = generators.items[0].reference
            site = P.SlotRef(clause, 'FIELD', roles.fields['comprehension']['iter'])
            result = (P.DeferredParameter(P.DeferredParameterKind.INITIAL_ITERATOR, site, None),)
        elif node.constructor in ('Lambda', 'FunctionDef', 'AsyncFunctionDef'):
            arguments = roles.field(occurrence, 'args').reference
            result = []
            for field, kind in (
                ('posonlyargs', P.DeferredParameterKind.POSITIONAL_ONLY),
                ('args', P.DeferredParameterKind.POSITIONAL_OR_KEYWORD),
                ('vararg', P.DeferredParameterKind.VAR_POSITIONAL),
                ('kwonlyargs', P.DeferredParameterKind.KEYWORD_ONLY),
                ('kwarg', P.DeferredParameterKind.VAR_KEYWORD)):
                value = roles.field(arguments, field)
                members = value.items if value.kind == 'LIST' else (value,) if value.kind == 'NODE' else ()
                for item in members:
                    site = P.SlotRef(item.reference, 'FIELD', roles.fields['arg']['arg'])
                    ports = []
                    data = self.source.frontend.bindings
                    declarations = self.source.frontend.declarations
                    for p in self.ports[site]:
                        port = data.ports[p]
                        if port.declref is None or port.resolution is None:
                            continue
                        contribution = declarations.contributions[port.declref]
                        binding = data.resolutions[port.resolution].binding
                        if ('PARAMETER_INTERFACE' in contribution.operations and binding is not None
                                and data.bindings[binding].owner == self.scopes[occurrence]):
                            ports.append(p)
                    if len(ports) != 1:
                        raise ValueError('formal has no unique original F3 admission/binding port')
                    result.append(P.DeferredParameter(kind, site, ports[0]))
            positional = [i for i, p in enumerate(result) if p.kind in (
                P.DeferredParameterKind.POSITIONAL_ONLY, P.DeferredParameterKind.POSITIONAL_OR_KEYWORD)]
            defaults = roles.field(arguments, 'defaults').items
            if len(defaults) > len(positional):
                raise ValueError('positional defaults exceed original positional formals')
            for ordinal, index in enumerate(positional[len(positional)-len(defaults):]):
                result[index] = replace(result[index], default_source=P.SlotRef(arguments, 'FIELD',
                    roles.fields['arguments']['defaults'], (ordinal,)))
            keywords = [i for i, p in enumerate(result) if p.kind is P.DeferredParameterKind.KEYWORD_ONLY]
            default_values = roles.field(arguments, 'kw_defaults').items
            if len(keywords) != len(default_values):
                raise ValueError('keyword default slots differ from original keyword-only formals')
            for ordinal, (index, value) in enumerate(zip(keywords, default_values)):
                if value.kind == 'NODE':
                    result[index] = replace(result[index], default_source=P.SlotRef(arguments, 'FIELD',
                        roles.fields['arguments']['kw_defaults'], (ordinal,)))
            result = tuple(result)
        else:
            raise ValueError('source occurrence has no declared deferred interface')
        self._parameters[occurrence] = result
        return result

    def interface(self, occurrence, world, exception_abi):
        if occurrence not in self.scopes:
            raise ValueError('deferred body has no original child scope')
        syntax, roles = self.source.context.syntax, self.source.roles
        node = syntax.nodes[occurrence]
        asynchronous = node.constructor == 'AsyncFunctionDef'
        generator = node.constructor == 'GeneratorExp' or occurrence in self.yield_owners
        if node.constructor == 'GeneratorExp':
            asynchronous = occurrence in self.await_owners or any(roles.field(item.reference, 'is_async').scalar.to_python()
                for item in roles.field(occurrence, 'generators').items)
        kind = (P.DeferredBodyKind.ASYNC_GENERATOR if generator else P.DeferredBodyKind.COROUTINE) if asynchronous else (
            P.DeferredBodyKind.GENERATOR if generator else P.DeferredBodyKind.FUNCTION)
        scope = self.scopes[occurrence]
        return P.DeferredEnvironment(scope, self.source.context.material.root_context.environment,
            self.parameters(occurrence), tuple(self.captures[scope]), kind, world, exception_abi)
