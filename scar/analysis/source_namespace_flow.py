"""Admit namespace content constraints without turning exec dicts into modules.

The published overlay retains lookup order and worlds. Transfer-domain facts
remain conditional may alternatives; no singleton is a constant proof here.
"""
from collections import defaultdict
from scar.analysis.source_namespace_builtins import BuiltinNamespaceFlow

from scar.ir.program import source_productions as P, normal_links as F, normal_graph as G
from scar.ir.program.normal_targets import GlobalPort
from scar.ir.program.source_exec_roots import ExecNamespaceKind


class NamespaceFlow:
    def __init__(self, solver, graph):
        self.s,self.graph = solver,graph
        self.accesses = defaultdict(list)
        self.bindings = defaultdict(list)
        self.references = defaultdict(list)
        self.watchers = defaultdict(set)
        self.admitted = set(); self.connections = {}; self.mapping_requests = set()
        self.globals_by_owner = defaultdict(set)
        for access in graph.records('accesses'):
            self.accesses[access.owner.owner].append(access)
        for binding in graph.records('bindings'):
            self.bindings[binding.connection,binding.interface].append(binding)
        for reference in graph.records('globals_bindings'):
            self.references[reference.connection].append(reference)
        self.captures = tuple(graph.records('captures'))
        self.builtins = BuiltinNamespaceFlow(self)

    def point(self, endpoint):
        return self.s.original_point(endpoint)

    def formal(self, connection, index):
        root = connection.root
        return self.point(GlobalPort(root.owner.unit,G.Port(root.template,root.region,G.PortKind.PARAMETER,index)))

    def admit_connection(self, connection):
        if connection.id in self.connections:
            return
        self.connections[connection.id]=connection
        globals_point,locals_point = self.formal(connection,0),self.formal(connection,1)
        if type(connection.globals.value) is GlobalPort:
            self.s.edge(self.point(connection.globals.value),globals_point)
        else:
            # Preserve the unresolved frame handle. A source module is not
            # evidence of the caller's actual globals dictionary identity.
            self.s.add(globals_point,('external_value',None))
        if type(connection.locals.value) is GlobalPort:
            self.s.edge(self.point(connection.locals.value),locals_point)
        else:
            # Snapshot content is not fabricated from the caller's fast locals.
            self.s.add(locals_point,('external_value',None))
        self.globals_by_owner[connection.root.owner].add(globals_point)
        for reference in self.references[connection.id]:
            self.s.edge(globals_point,self.point(reference.reference))
        for capture in self.captures:
            if capture.function.unit==connection.root.owner.unit:
                self.globals_by_owner[capture.body.owner].add(self.point(capture.globals))
        for owner in tuple(self.s.active_scopes):
            if owner.unit==connection.root.owner.unit:
                self.admit_scope(owner)

    def _lexical(self, descriptor, key):
        if descriptor.kind in ('LEXICAL_BINDING','CLASS_PROTOCOL_CELL'):
            return F.Namespace(F.NamespaceKind.LEXICAL,descriptor.binding,key)
        if descriptor.kind in ('CLASS_PREPARED_MAPPING','CLASS_ANNOTATION_NAMESPACE'):
            return F.Namespace(F.NamespaceKind.CLASS,descriptor.owner,key)

    def _register(self, receiver, key, value, write):
        request = key,value,write
        if request in self.watchers[receiver]:
            return
        self.watchers[receiver].add(request)
        for token in tuple(self.s.values.get(receiver,())):
            self._request(token,key,value,write)

    def _access(self, connection, access, interface):
        value = None if access.value is None else self.point(access.value)
        write = access.action is P.BindingActionKind.WRITE
        for binding in self.bindings[connection.id,interface]:
            descriptor = binding.descriptor
            lexical = self._lexical(descriptor,access.key)
            if lexical is not None:
                # Existing primitive facts already admit these same channels.
                continue
            if access.action is P.BindingActionKind.DELETE:
                # Deletion stays a state operation in the source graph. This
                # monotone may domain never treats it as a strong kill.
                continue
            if descriptor.kind=='BUILTINS':
                if not write:
                    self.builtins.admit(connection,access,binding)
                continue
            if descriptor.kind=='ROOT_GLOBALS':
                receiver = self.formal(connection,0)
            elif descriptor.kind=='ROOT_LOCALS':
                receiver = self.formal(connection,1)
            elif binding.actual is not None:
                receiver = self.point(binding.actual)
            else:
                if not write:
                    self.s.add(value,('external_value',None))
                continue
            self._register(receiver,access.key,value,write)

    def admit_scope(self, owner):
        for connection in tuple(self.connections.values()):
            if connection.root.owner.unit!=owner.unit or (connection.id,owner) in self.admitted:
                continue
            self.admitted.add((connection.id,owner))
            for access in self.accesses.get(owner,()):
                if access.lookup:
                    for lookup in access.lookup:
                        self._access(connection,access,lookup.interface)
                elif access.target is not None:
                    self._access(connection,access,access.target)

    def consume(self, point, token):
        self.builtins.consume(point,token)
        for key,target,write in tuple(self.watchers.get(point,())):
            self._request(token,key,target,write)

    def _request(self, token, key, target, write):
        request = token,key,target,write
        if request in self.mapping_requests:
            return
        self.mapping_requests.add(request)
        if token[0] in ('container','namespace_mapping'):
            self.s.containers.access(token,('str',key),target,write)
        elif not write:
            self.s.add(target,('external_value',None))
