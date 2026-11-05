"""Entry-scoped solving with shared compiled roots and actual namespace flow.

The original source solver and all sealed parents remain unchanged. The
extension admits compiled contexts through their exec evidence, never through
the import registry or a guessed filename-to-body relation.
"""
from collections import defaultdict, deque

from scar.analysis.normal_entry import EntrySolver
from scar.analysis.source_context_fact_store import ContextFactStore
from scar.analysis.source_context_interfaces import ContextInterfaceStore
from scar.analysis.source_namespace_flow import NamespaceFlow
from scar.analysis.source_relation_replay import SharedConstructionFlow, SharedContainerFlow
from scar.ir.program import normal_links as F, normal_entry as E


class ContextEntrySolver(EntrySolver):
    def __init__(self, base, namespace_graph, entries, *, interfaces, jobs=None):
        self.namespace_graph = namespace_graph
        self.namespace_flow = None; self.namespace_pending = deque(); self.namespace_scopes = set()
        self.exec_by_result = defaultdict(list); self.call_owners = {}
        for connection in namespace_graph.exec_graph.connections():
            self.exec_by_result[connection.site.result].append(connection)
        store = ContextFactStore(base,namespace_graph.exec_graph)
        summaries = ContextInterfaceStore(interfaces,store,namespace_graph.exec_graph)
        super().__init__(store,entries,jobs=jobs,interface_store=summaries)
        # A compile-context body is not an importable module instance.
        for module in tuple(self.module_units):
            self.module_units[module] = [u for u in self.module_units[module] if u in store.importable_units]
            if not self.module_units[module]:
                del self.module_units[module]
        self.containers = SharedContainerFlow(self,[])
        self.constructions = SharedConstructionFlow(self)
        self.namespace_flow = NamespaceFlow(self,namespace_graph)

    def load_unit(self, identity):
        fresh = identity not in self._metadata_loaded
        result = super().load_unit(identity)
        if not fresh:
            return result
        for group in result.scope_groups:
            for span in group.tables:
                if span.table is F.FactTable.CALLS:
                    for index in range(span.start,span.stop):
                        self.call_owners[self.local_calls[identity,index]]=group.owner
        return result

    def add(self, point, value):
        normalized = ('external_value',None) if value[0]=='external_value' else (
            ('external',value[1]) if value[0]=='external' else value)
        fresh = normalized not in self.values.get(point,())
        super().add(point,value)
        flow = self.namespace_flow
        if fresh and flow is not None and (point in flow.watchers or point in flow.builtins.watchers):
            self.namespace_pending.append((point,normalized))

    def admit(self, unit, table, index):
        if (table=='names' and unit.unit in self.store.original_source_units
                and unit.names[index].namespace.kind in (F.NamespaceKind.MODULE,F.NamespaceKind.BUILTINS)):
            # These lossy MODULE rows are replaced by ordered C2 interfaces.
            self.admitted.add((unit.unit,table,index))
            return
        return super().admit(unit,table,index)

    def prepare(self):
        super().prepare()
        if self.namespace_flow is not None:
            for owner in self.active_scopes-self.namespace_scopes:
                self.namespace_scopes.add(owner)
                self.namespace_flow.admit_scope(owner)

    def call(self, index, value):
        unit,call = self.call_rows[index]; offset = self.offsets[unit.unit]
        if value[:2]==('external','builtins.exec'):
            connections = self.exec_by_result.get(self.gp(offset+call.result),())
            if connections:
                for connection in connections:
                    self.load_unit(connection.root.owner.unit)
                    self.namespace_flow.admit_connection(connection)
                    self.activate(connection.root.owner,connection.site.result,E.EntryReason.EAGER_REGION)
                self.add(offset+call.result,('constant','NoneType',None))
                self.resolved_interface_calls.add(index)
                return
        if (unit.unit in self.store.original_source_units and value[:2]==('external','builtins.globals')
                and not call.positional and not call.keywords
                and call.positional_pack is None and call.keyword_pack is None):
            owner = self.call_owners[index]
            for source in self.namespace_flow.globals_by_owner.get(owner,()):
                self.edge(source,offset+call.result)
            if not self.namespace_flow.globals_by_owner.get(owner):
                self.add(offset+call.result,('external_value',None))
            self.resolved_interface_calls.add(index)
            return
        return super().call(index,value)

    def solve(self, max_events=20_000_000):
        self.prepare()
        while (self.queue or self.pending or self.namespace_pending) and self.events<max_events:
            while self.namespace_pending:
                point,value = self.namespace_pending.popleft()
                self.namespace_flow.consume(point,value)
            self.prepare()
            if self.queue:
                super().solve(min(max_events,self.events+65_536))
        return not self.queue and not self.pending and not self.namespace_pending
