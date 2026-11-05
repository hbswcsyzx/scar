"""Entry-driven may-activation over retained, shared source templates.

Unloaded units remain in the receipt-bound source catalog. Activation admits
constraints; it neither selects a runtime branch nor authorizes a transform.
"""
from collections import defaultdict,deque

from scar.analysis.normal_facts import SourceFactStore,SourcePointSpace
from scar.analysis.normal_targets import _Solver,_star_imports
from scar.ir.program import normal_links as F,normal_entry as E


class EntrySolver(_Solver):
    def __init__(self,store,entries):
        super().__init__([],())
        self.store=store;self.offsets=store.offsets
        self.owner=SourcePointSpace(store,owners=True);self.port=SourcePointSpace(store)
        for row in store.rows.values():self.module_units[row['module']].append(row['unit'])
        self.groups=defaultdict(list);self.pending=deque();self.requested=set();self.active_scopes=set()
        self.activations={};self.module_demands={};self.body_demands={};self.call_demands={}
        self.admitted=set();self.active_call_indices=set();self.resolved_interface_calls=set()
        self.local_calls={};self.stars=[];self._metadata_loaded=set()
        for entry in entries:
            identities=store.units_for_source(entry)
            if not identities:raise ValueError('entry source is not in the declared catalog')
            for identity in identities:
                unit=self.load_unit(identity);self.activate(unit.root_scope.owner,None,E.EntryReason.PROGRAM_ENTRY)

    def load_unit(self,identity):
        unit=self.store.load(identity)
        if identity in self._metadata_loaded:return unit
        self._metadata_loaded.add(identity);self.units.append(unit);o=self.offsets[identity]
        self.functions.update((o+f.value,(unit,f)) for f in unit.functions)
        self.classes.update((o+c.value,(unit,c)) for c in unit.classes)
        for group in unit.scope_groups:self.groups[group.owner].append(group)
        for i,call in enumerate(unit.calls):
            self.local_calls[identity,i]=len(self.call_rows);self.call_rows.append((unit,call))
        row=_star_imports(str(self.store.model_for(identity)),self.store.model_units[identity],unit.module);self.stars.append(row)
        for module in row[1]:
            for source in self.module_units.get(module,()):
                self.star_forward[source].add(identity)
                # The exporter may have initialized before the importer.
                for key,values in tuple(self.ns_values.items()):
                    if len(key)==4 and key[:3]==(source,F.NamespaceKind.MODULE.value,0):
                        for value in tuple(values):self.namespace_value((identity,key[1],0,key[3]),value)
        for module in row[2]:
            parts=module.split('.')
            self.imported_modules.update('.'.join(parts[:i]) for i in range(1,len(parts)+1))
        return unit

    def activate(self,owner,cause,reason):
        record=E.ScopeActivationEvidence(owner,cause,reason)
        self.activations[owner,cause,reason]=record
        if owner not in self.requested:self.requested.add(owner);self.pending.append(owner)

    def activate_module(self,name,cause,reason):
        identities=self.module_units.get(name,())
        if not identities:
            self.module_demands[name,cause]=E.ModuleEntryDemand(name,cause)
        for identity in identities:
            unit=self.load_unit(identity);self.activate(unit.root_scope.owner,cause,reason)

    def add(self,point,value):
        super().add(point,value)
        if value[0]=='module' and hasattr(self,'store'):
            cause=self.gp(point) if type(point) is int else None
            self.activate_module(value[1],cause,E.EntryReason.MODULE_REFERENCE)

    def activate_function(self,fid,callee):
        unit,function=self.functions[fid]
        if function.body_scope is None:raise ValueError('source function has no original body scope')
        self.activate(function.body_scope.owner,self.gp(callee),E.EntryReason.SOURCE_FUNCTION_CALL)

    def body_demand(self,fid,callee,kind):
        unit,function=self.functions[fid]
        if function.body_scope is None:raise ValueError('deferred source body missing its scope')
        demand=E.BodyEntryDemand(function.body_scope,self.gp(callee),E.BodyDemandKind(kind))
        self.body_demands[demand]=demand

    def call(self,index,value):
        super().call(index,value)
        if value[0]=='property_method':
            unit,call=self.call_rows[index]
            if len(call.positional)==1 and not call.keywords and call.positional_pack is None and call.keyword_pack is None:
                self.resolved_interface_calls.add(index)
        if value[0] in ('external','external_member','external_value'):
            unit,call=self.call_rows[index];o=self.offsets[unit.unit]
            symbol=value[1] if value[0]=='external' else 'member:'+value[2] if value[0]=='external_member' else None
            d=E.CallEntryDemand(self.gp(o+call.callee),self.gp(o+call.result),symbol)
            self.call_demands[d]=d

    def complete_call_demands(self):
        known={link.result for link in self.links.values()}
        for index in self.active_call_indices-self.resolved_interface_calls:
            unit,call=self.call_rows[index];o=self.offsets[unit.unit]
            if self.gp(o+call.result) not in known:
                d=E.CallEntryDemand(self.gp(o+call.callee),self.gp(o+call.result),None,
                    ('ACTIVE_CALL_VALUE_OR_SPECIAL_METHOD_TARGET_UNRESOLVED',))
                self.call_demands[d]=d

    def admit(self,unit,table,index):
        key=unit.unit,table,index
        if key in self.admitted:return
        self.admitted.add(key);o=self.offsets[unit.unit];item=getattr(unit,table)[index]
        if table=='aliases':self.edge(o+item[0],o+item[1])
        elif table=='names':
            ns=self.ns(unit.unit,item.namespace);point=o+item.value
            if item.write:
                self.writes[point].add(ns);self.containers.namespace_sources[ns].add(point)
                for value in tuple(self.values.get(point,())):self.namespace_value(ns,value)
            else:
                self.reads[ns].add(point)
                for value in tuple(self.ns_values.get(ns,())):self.add(point,value)
                if item.namespace.kind is F.NamespaceKind.BUILTINS and item.namespace.name in self.builtin_names:
                    self.add(point,('external','builtins.'+item.namespace.name))
        elif table=='functions':self.add(o+item.value,('function',o+item.value))
        elif table=='classes':
            self.add(o+item.value,('class',o+item.value))
            if item.body_scope is None:raise ValueError('source class body missing its scope')
            self.activate(item.body_scope.owner,self.gp(o+item.value),E.EntryReason.CLASS_BUILD)
        elif table=='attributes':
            access=self.descriptors.admit(unit,index)
            if item.action in (F.AttributeAction.GET,F.AttributeAction.IMPORT_MEMBER):
                self.gets[o+item.receiver].add((item.name,o+item.value))
                for value in tuple(self.values.get(o+item.receiver,())):self.attribute(o+item.receiver,value,item.name,o+item.value)
            for value in tuple(self.values.get(access.receiver,())):self.descriptors.consume(access.receiver,value)
        elif table=='imports':
            self.add(o+item.value,('module',item.module))
            requested=item.requested_module or item.module;parts=requested.split('.')
            for i in range(1,len(parts)+1):
                self.activate_module('.'.join(parts[:i]),self.gp(o+item.value),E.EntryReason.REQUESTED_MODULE)
        elif table=='constants':
            literal=item.literal.to_python();self.add(o+item.value,('constant',type(literal).__name__,literal))
        elif table=='calls':
            row=self.local_calls[unit.unit,index];self.active_call_indices.add(row)
            self.call_watch[o+item.callee].append(row)
            for value in tuple(self.values.get(o+item.callee,())):self.call(row,value)
        elif table in ('containers','items','updates','iterations'):self.containers.admit(unit,table,index)
        elif table=='activations':self.activate(item.target.owner,item.source,E.EntryReason.EAGER_REGION)
        elif table!='operations':raise ValueError('unknown source constraint table')

    def prepare(self):
        while self.pending:
            owner=self.pending.popleft()
            if owner in self.active_scopes:continue
            unit=self.load_unit(owner.unit);self.active_scopes.add(owner)
            for group in self.groups.get(owner,()):
                for span in group.tables:
                    for i in range(span.start,span.stop):self.admit(unit,span.table.value,i)

    def solve(self,max_events=20_000_000):
        self.prepare()
        while self.queue and self.events<max_events:
            super().solve(max_events);self.prepare()
        return not self.queue and not self.pending
