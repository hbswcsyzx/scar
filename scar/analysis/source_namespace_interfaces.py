"""Recover ordered C2 namespace interfaces from original F4 operations.

No target execution or new source rules: each access retains the compiler
read plan, original world ports and the shared source scope witness.
"""
from collections import defaultdict, deque

from scar.analysis.normal_graph import _Emitter
from scar.analysis.source_namespace_captures import extract_captures
from scar.ir.program import normal_graph as G, normal_links as F, normal_targets as T
from scar.ir.program import source_productions as P, source_namespaces as N
from scar.ir.program.control import LanguageCompletionKind as K
from scar.ir.program.model import ValueType, ValueKind
from scar.ir.record_codec import decode


def _state(value_type):
    return type(value_type) is ValueType and value_type.kind is ValueKind.STATE


class NamespacePlanView:
    def __init__(self, unit, plan):
        self.unit, self.plan = unit, plan
        self.steps = {s.id:s for s in plan.steps}
        self.regions = {r.id:r for r in plan.regions}
        self.contexts = {p.region:p for p in plan.compilation_flow.ports}
        self.key = G.SourceTemplateKey(plan.source.occurrence, plan.purpose)
        self.emitter = _Emitter(plan, self.key, {})

    def gp(self, port):
        return T.GlobalPort(self.unit, port)

    def value(self, value):
        return self.gp(self.emitter.value(value)[0])

    def result(self, step, index=0):
        normal = next(c for c in step.completions if c.kind is K.FALLTHROUGH)
        return self.gp(self.emitter.port(step.id, G.PortKind.RESULT, index, normal))

    def site(self, step):
        return self.gp(self.emitter.port(step.id, G.PortKind.ENTER))

    def owner(self, region):
        context = self.contexts[region]
        return F.CodeScopeWitness(F.CodeScopeRef(self.unit, context.code_scope),
            self.key, region, context.source_scope)

    def worlds(self, step):
        inputs = [v for v in step.arguments if _state(self.emitter.value(v)[1])]
        normal = next(c for c in step.completions if c.kind is K.FALLTHROUGH)
        outputs = [i for i,t in enumerate(normal.types) if _state(t)]
        if len(inputs)!=1 or len(outputs)!=1:
            raise ValueError('namespace operation needs original single-world ABI')
        return self.value(inputs[0]), self.result(step, outputs[0])


def extract_namespace_interfaces(unit, plan, bindings, declarations):
    view = NamespacePlanView(unit, plan)
    accesses, explicit = [], []
    references, captures, obligations = extract_captures(view)
    for step in plan.steps:
        ins = step.instruction
        if type(ins) is P.ApplyNamespaceAction:
            before, after = view.worlds(step)
            explicit.append(N.ExplicitNamespaceAction(view.site(step), view.owner(step.region), ins.kind,
                tuple(view.value(v) for v in step.arguments if not _state(view.emitter.value(v)[1])), before, after))
        if type(ins) is not P.AccessBinding:
            continue
        port = bindings.ports[ins.port]
        if port.name is None:
            raise ValueError('namespace access lost original C2 name')
        name = port.name
        key = declarations.names[name.index].value if name.kind=='SOURCE' else name.symbol
        lookup, missing, read_plan, target = (), None, None, None
        value = None
        if ins.action is P.BindingActionKind.READ:
            read_plan = port.read_plan
            if read_plan is None:
                raise ValueError('namespace read has no C2 lookup plan')
            selected = bindings.plans[read_plan]
            lookup = tuple(N.NamespaceLookupStep(i, N.NamespaceInterfaceRef(unit,s.interface),
                s.on_hit, s.on_miss, s.on_exception) for i,s in enumerate(selected.steps))
            missing = selected.missing_outcome
            value = view.result(step)
        else:
            index = port.write_target if ins.action is P.BindingActionKind.WRITE else port.delete_target
            if index is None:
                raise ValueError('namespace write/delete has no original target')
            target = N.NamespaceInterfaceRef(unit,index)
            if ins.action is P.BindingActionKind.WRITE:
                value = view.value(step.arguments[0])
        before, after = view.worlds(step)
        accesses.append(N.NamespaceAccess(view.site(step), view.owner(step.region), ins.port, ins.action,
            name, key, read_plan, lookup, missing, target, value, before, after))
    return tuple(accesses), tuple(explicit), references, captures, obligations


def bind_exec_namespaces(connection, bindings, references, captures):
    """Root dict references and function globals stay separate from modules."""
    unit = connection.root.owner.unit
    root = connection.root
    formal = lambda i:T.GlobalPort(unit, G.Port(root.template, root.region, G.PortKind.PARAMETER, i))
    common = (*connection.conditions, 'SELECTED_EXEC_NAMESPACE_BRANCH')
    result = []
    for index, descriptor in enumerate(bindings.interfaces):
        ref = N.NamespaceInterfaceRef(unit, index)
        options = [None]
        if descriptor.kind=='ENV_GLOBALS':
            options = [c for c in captures if c.body.source_scope==descriptor.owner] or [None]
        for capture in options:
            actual, parameter = None, None
            if descriptor.kind=='ROOT_GLOBALS':
                actual,parameter,origin = connection.globals.value,formal(0),'ROOT_GLOBALS_ARGUMENT'
            elif descriptor.kind=='ROOT_LOCALS':
                actual,parameter,origin = connection.locals.value,formal(1),'ROOT_LOCALS_ARGUMENT'
            elif descriptor.kind=='ENV_GLOBALS':
                actual = None if capture is None else capture.globals
                origin = 'CAPTURED_FUNCTION_GLOBALS' if capture is not None else 'CAPTURED_GLOBALS_INTERFACE_UNRESOLVED'
            elif descriptor.kind=='BUILTINS':
                # Root frame builtins are selected at entry; a function retains
                # its builtins selected at creation, not a later dict lookup.
                origin = ('ROOT_FRAME_BUILTINS_SELECTED_AT_ENTRY' if descriptor.owner==root.source_scope else
                    'CALLABLE_FRAME_BUILTINS_SELECTED_AT_CREATION')
            else:
                origin = descriptor.kind+'_TEMPLATE'
            conditions = common if capture is None else (*common,'CURRENT_CALLABLE_IS_SELECTED_FUNCTION_CREATION')
            result.append(N.NamespaceInterfaceBinding(connection.id, ref, descriptor, origin, actual, parameter,
                conditions, None if capture is None else capture.function))
    reference_bindings = tuple(N.GlobalsReferenceBinding(connection.id, r.result, connection.globals.value,
        r.owner, (*common,'ACTIVE_FRAME_GLOBALS_FROM_SELECTED_ROOT_OR_ITS_CAPTURE_CHAIN'))
        for r in references if r.globals_scope==root.source_scope)
    return tuple(result), reference_bindings


class CallerReferencePaths:
    """Sparse directed aliases and factored name channels, with row witnesses."""
    def __init__(self, unit):
        self.unit = unit
        self.ports = {i:T.GlobalPort(unit.unit, decode(G.Port,p,record_tags=P.PRODUCTION_RECORD_TAGS)
            if type(p) is dict else p) for i,p in enumerate(unit.ports)}
        self.indices = {p:i for i,p in self.ports.items()}
        self.adj = defaultdict(list)
        for i,(a,b) in enumerate(unit.aliases):
            self.adj[a].append((b,F.FactTable.ALIASES,i))
        for i,row in enumerate(unit.names):
            channel = ('namespace',row.namespace)
            a,b = (row.value,channel) if row.write else (channel,row.value)
            self.adj[a].append((b,F.FactTable.NAMES,i))
        self.cache = {}

    def path(self, source, target):
        """None means not established, () means the same original port."""
        if target not in self.indices:
            return None
        if source not in self.cache:
            parents = {source:None}; queue = deque((source,))
            while queue:
                node = queue.popleft()
                for successor,table,row in self.adj.get(node,()):
                    if successor not in parents:
                        parents[successor] = (node,table,row); queue.append(successor)
            self.cache[source] = parents
        parents = self.cache[source]; end = self.indices[target]
        if end not in parents:
            return None
        reversed_edges = []
        while parents[end] is not None:
            before,table,row = parents[end]
            reversed_edges.append((before,end,table,row)); end = before
        edges = list(reversed(reversed_edges)); path = []; i = 0
        while i<len(edges):
            a,b,table,row = edges[i]
            if type(b) is tuple:
                _,c,other_table,other_row = edges[i+1]
                if table is not F.FactTable.NAMES or other_table is not table:
                    raise ValueError('invalid factored namespace path')
                path.append(N.NamespaceReferenceHop(self.ports[a],self.ports[c],table,(row,other_row))); i+=2
            else:
                path.append(N.NamespaceReferenceHop(self.ports[a],self.ports[b],table,(row,))); i+=1
        return tuple(path)
