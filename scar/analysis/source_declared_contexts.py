"""Expand source method bodies using guarded class inputs and shared regions."""
from collections import defaultdict, deque

from scar.analysis.source_field_interfaces import _InterfaceOnly
from scar.analysis.source_function_connections import Invocation, connect
from scar.analysis.source_reference_slice import DECLARED, source_port
from scar.ir.program import declared_contexts as D, normal_links as F, normal_targets as T


MEMBER_GUARDS = ('SOURCE_CLASS_NAMESPACE_SELECTS_DECLARED_MEMBER',
    'CURRENT_ATTRIBUTE_SLOT_AND_MRO_SELECT_DECLARED_DESCRIPTOR',
    'SOURCE_FUNCTION_CREATION_AND_DEFAULT_VERSIONS_MATCH_DECLARATION')
BUILTIN_GUARDS = ('ALL_EARLIER_C2_LOOKUP_STEPS_MISS_AT_READ_WORLD',
    'STANDARD_BUILTIN_MAP_AND_BINDING_SELECTED', 'STANDARD_DESCRIPTOR_WRAPPER_IDENTITY_SELECTED')


class DeclaredResolver:
    def __init__(self, slicer):
        self.slicer = slicer; self.cache = {}; self.alias_cache = {}; self.member_cache = {}

    def unit(self, identity):
        if identity not in self.cache:
            unit, _, aliases, reads, writes, _, _ = self.slicer.unit(identity)
            owners = defaultdict(set)
            for group in unit.scope_groups:
                for span in group.tables:
                    if span.table is not F.FactTable.NAMES: continue
                    for i in range(span.start, span.stop): owners[span.table, i].add(group.owner)
            self.cache[identity] = unit, aliases, reads, writes, owners
        return self.cache[identity]

    def aliases(self, unit, point):
        """Original directed copy paths, indexed by their upstream source."""
        key = unit.unit, point
        if key in self.alias_cache: return self.alias_cache[key]
        _, incoming, *_ = self.unit(unit.unit)
        found = {point: ()}; pending = deque((point,))
        while pending:
            target = pending.popleft()
            for source, ordinal in incoming.get(target, ()):
                if source not in found:
                    edge = D.CopyStep(source_port(unit, source), source_port(unit, target), D.CopyKind.ALIAS,
                        (self.slicer.fact(unit, 'aliases', ordinal),), DECLARED)
                    found[source] = (edge, *found[target]); pending.append(source)
        self.alias_cache[key] = found
        return found

    def references(self, context, point):
        unit, local = self.slicer.local(point)
        _, incoming, reads, writes, owners = self.unit(unit.unit)
        fn = next(f for f in unit.functions if source_port(unit, f.value) == context.source_callable)
        seeds = defaultdict(list)
        for i, item in enumerate(context.class_inputs): seeds[item.formal].append((i, item))
        classes = {c.value: c for c in unit.classes}
        seen = {local}; pending = deque(((local, (), ()),)); result = []
        while pending:
            target, path, guards = pending.popleft(); origin = source_port(unit, target)
            for ordinal, item in seeds.get(origin, ()):
                result.append(D.ClassReference(point, origin, item.source_class, item.kind, ordinal, path,
                    (*guards, 'DECLARED_CLASS_INPUT_ALTERNATIVE_SELECTED')))
            if target in classes:
                result.append(D.ClassReference(point, origin, origin, D.ClassValueKind.CLASS_OBJECT, None,
                    path, (*guards, 'CURRENT_SOURCE_CLASS_DEFINITION_SELECTED')))
            for source, index in incoming.get(target, ()):
                if source not in seen:
                    edge = D.CopyStep(source_port(unit, source), origin, D.CopyKind.ALIAS,
                        (self.slicer.fact(unit, 'aliases', index),), DECLARED)
                    seen.add(source); pending.append((source, (edge, *path), guards))
            for ns, read_index in reads.get(target, ()):
                if ns.kind not in (F.NamespaceKind.LEXICAL, F.NamespaceKind.MODULE): continue
                if ns.kind is F.NamespaceKind.MODULE and unit.unit in self.slicer.store.original_source_units: continue
                for source, write_index in writes.get(ns, ()):
                    if ns.kind is F.NamespaceKind.LEXICAL and fn.body_scope.owner not in owners[F.FactTable.NAMES, write_index]:
                        continue  # A captured creation frame needs a separate environment interface.
                    if source in seen: continue
                    kind = D.CopyKind.LEXICAL_BINDING if ns.kind is F.NamespaceKind.LEXICAL else D.CopyKind.MODULE_DECLARATION
                    extra = ('CURRENT_LEXICAL_READ_SELECTS_DECLARED_WRITE',) if kind is D.CopyKind.LEXICAL_BINDING else (
                        'CURRENT_FRAME_GLOBALS_SELECT_SOURCE_MODULE_DECLARATION',)
                    edge = D.CopyStep(source_port(unit, source), origin, kind,
                        (self.slicer.fact(unit, 'names', write_index), self.slicer.fact(unit, 'names', read_index)),
                        (*DECLARED, *extra))
                    seen.add(source); pending.append((source, (edge, *path), (*guards, *extra)))
        return tuple(result)

    def descriptors(self, source_class, member):
        key = source_class, member
        if key in self.member_cache: return self.member_cache[key]
        unit, local = self.slicer.local(source_class)
        _, _, reads, writes, _ = self.unit(unit.unit)
        cls = next(c for c in unit.classes if c.value == local)
        namespace = F.Namespace(F.NamespaceKind.CLASS, cls.scope, member)
        functions = {f.value: f for f in unit.functions}; result = []
        for value, name_index in writes.get(namespace, ()):
            binding = self.slicer.fact(unit, 'names', name_index)
            ancestors = self.aliases(unit, value)
            for point, path in ancestors.items():
                if point in functions:
                    result.append(D.DescriptorReference(binding, source_port(unit, point), D.DescriptorKind.FUNCTION,
                        path, None, None, (), (), MEMBER_GUARDS))
            for call_index, call in enumerate(unit.calls):
                if (call.result not in ancestors or len(call.positional) != 1 or call.keywords
                        or call.positional_pack is not None or call.keyword_pack is not None): continue
                for callee, callee_path in self.aliases(unit, call.callee).items():
                    for ns, read_index in reads.get(callee, ()):
                        if ns.kind is not F.NamespaceKind.BUILTINS or ns.name not in ('staticmethod', 'classmethod'): continue
                        for wrapped, function_path in self.aliases(unit, call.positional[0]).items():
                            if wrapped not in functions: continue
                            result.append(D.DescriptorReference(binding, source_port(unit, wrapped),
                                D.DescriptorKind(ns.name.upper()), ancestors[call.result],
                                self.slicer.fact(unit, 'calls', call_index), self.slicer.fact(unit, 'names', read_index),
                                callee_path, function_path, (*MEMBER_GUARDS, *BUILTIN_GUARDS)))
        self.member_cache[key] = tuple(result)
        return self.member_cache[key]

    def body_calls(self, context):
        unit, local = self.slicer.local(context.source_callable)
        fn = next(f for f in unit.functions if f.value == local)
        calls = {i for group in unit.scope_groups if group.owner == fn.body_scope.owner for span in group.tables
            if span.table is F.FactTable.CALLS for i in range(span.start, span.stop)}
        reads = defaultdict(list)
        for i, access in enumerate(unit.attributes):
            if access.action is F.AttributeAction.GET: reads[access.value].append((i, access))
        for ordinal in sorted(calls):
            call = unit.calls[ordinal]
            alternatives = tuple((i, access, path) for value, path in self.aliases(unit, call.callee).items()
                for i, access in reads.get(value, ()))
            yield unit, ordinal, call, alternatives

    def bind(self, context, unit, call, access, receiver, descriptor):
        provider, local = self.slicer.local(descriptor.function)
        fn = next(f for f in provider.functions if f.value == local)
        mini = _InterfaceOnly(self.slicer, provider, fn); offset = mini.offsets[unit.unit]
        invocation = Invocation(offset+call.callee, tuple(offset+p for p in call.positional),
            tuple((name, offset+p) for name, p in call.keywords), offset+call.result, offset+call.world,
            offset+call.result_world, None if call.positional_pack is None else offset+call.positional_pack,
            None if call.keyword_pack is None else offset+call.keyword_pack)
        instance = offset+access.receiver if (descriptor.kind is D.DescriptorKind.FUNCTION
            and receiver.kind is D.ClassValueKind.INSTANCE) else None
        class_receiver = None
        if descriptor.kind is D.DescriptorKind.CLASSMETHOD:
            owner, class_local = self.slicer.local(receiver.source_class)
            class_receiver = mini.offsets[owner.unit]+class_local
        conditions = (*DECLARED, *receiver.conditions, *descriptor.conditions,
            'PARENT_DECLARED_CONTEXT_AND_CALL_PATH_SELECTED', 'DESCRIPTOR_BINDING_KIND_SELECTED')
        connection = connect(mini, mini.offsets[provider.unit]+fn.value, invocation,
            receiver=instance, class_receiver=class_receiver, conditions=conditions)
        if connection is None: return None
        inputs = []; proofs = []
        for route in connection.parameters:
            if route.kind is T.RouteKind.CLASS_RECEIVER:
                inputs.append(D.ClassInput(route.formal, receiver.source_class, D.ClassValueKind.CLASS_OBJECT))
            elif route.kind is T.RouteKind.ARGUMENT:
                for actual in route.actuals:
                    for ref in self.references(context, actual):
                        item = D.ClassInput(route.formal, ref.source_class, ref.kind)
                        if item not in inputs: inputs.append(item)
                        if ref not in proofs: proofs.append(ref)
        return connection, tuple(inputs), tuple(proofs), conditions


def expand_contexts(resolver, roots, *, max_contexts=64, max_edges=1024):
    contexts = []; entries = []; edges = []; frontiers = []; ids = {}; pending = deque(); scheduled = set()
    def intern(value, enter=True):
        if value in ids:
            index = ids[value]
            if enter and index not in scheduled: scheduled.add(index); pending.append(index)
            return index
        if len(contexts) >= max_contexts: return None
        index = len(contexts); contexts.append(value); ids[value] = index
        if enter: scheduled.add(index); pending.append(index)
        return index
    for context, connection, evidence in roots:
        enter = connection.activation is T.FunctionActivation.NORMAL
        target = intern(context, enter)
        if target is None: raise ValueError('declared roots exceed context budget')
        entries.append(D.DeclaredContextEntry(target, evidence, connection))
        if not enter: frontiers.append(D.ContextFrontier(target, None, 'DEFERRED_BODY_CREATION_IS_NOT_BODY_ENTRY'))
    while pending:
        caller = pending.popleft(); context = contexts[caller]
        for unit, call_index, call, alternatives in resolver.body_calls(context):
            evidence = resolver.slicer.fact(unit, 'calls', call_index); linked = False
            for attr_index, access, path in alternatives:
                for receiver in resolver.references(context, source_port(unit, access.receiver)):
                    for descriptor in resolver.descriptors(receiver.source_class, access.name):
                        result = resolver.bind(context, unit, call, access, receiver, descriptor)
                        if result is None: continue
                        connection, inputs, proofs, conditions = result
                        if len(edges) >= max_edges:
                            frontiers.append(D.ContextFrontier(caller, evidence, 'DECLARED_EDGE_BUDGET_FRONTIER')); continue
                        child = D.DeclaredContext(connection.source_callable, connection.body, inputs)
                        enter = connection.activation is T.FunctionActivation.NORMAL
                        target = intern(child, enter)
                        if target is None:
                            frontiers.append(D.ContextFrontier(caller, evidence, 'DECLARED_CONTEXT_BUDGET_FRONTIER')); continue
                        edges.append(D.DeclaredContextEdge(caller, target, evidence,
                            resolver.slicer.fact(unit, 'attributes', attr_index), path, receiver, descriptor,
                            connection, proofs, conditions)); linked = True
                        if not enter:
                            frontiers.append(D.ContextFrontier(target, evidence, 'DEFERRED_BODY_CREATION_IS_NOT_BODY_ENTRY'))
            if not linked:
                frontiers.append(D.ContextFrontier(caller, evidence, 'CALLEE_OR_CLASS_INPUT_OR_DESCRIPTOR_UNRESOLVED'))
    return D.DeclaredContextGraph(tuple(contexts), tuple(entries), tuple(edges), tuple(frontiers))
