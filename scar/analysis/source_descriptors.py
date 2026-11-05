"""Conditional builtin-property and storage routes at original attribute sites.

Property versions are static constructor origins, not runtime ObjectIDs.
Namespace values are a monotone may-union; MRO/descriptor/slot conditions are
retained on published routes, never interpreted as proven value identities.
"""
from collections import defaultdict
from dataclasses import dataclass,replace
from enum import Enum

from scar.analysis.source_function_connections import Invocation,connect
from scar.ir.program import normal_links as F,normal_targets as T


class _OpenAccessor(str,Enum):
    PACK='PACK'


@dataclass(frozen=True,slots=True)
class _Property:
    origin: int
    accessors: tuple[int | None | _OpenAccessor,...]


@dataclass(frozen=True,slots=True)
class _Access:
    key: tuple
    origin: T.AttributeOrigin
    action: F.AttributeAction
    receiver: int
    member: str
    result: int | None
    assigned: int | None
    world: int
    result_world: int
    dynamic_member: int | None=None


_PROPERTY_CONDITIONS=('BUILTIN_PROPERTY_IDENTITY_ADMISSION','DEFAULT_INSTANCE_ATTRIBUTE_SLOT_ADMISSION',
    'CURRENT_CLASS_MRO_SELECTS_THIS_PROPERTY_VERSION','PROPERTY_DATA_DESCRIPTOR_PRECEDENCE',
    'NORMAL_ATTRIBUTE_PROTOCOL_COMPLETION')
_FIELD_CONDITIONS=('DEFAULT_INSTANCE_ATTRIBUTE_SLOT_ADMISSION','CURRENT_CLASS_MRO_HAS_NO_SELECTED_DATA_DESCRIPTOR',
    'INSTANCE_DICTIONARY_PATH_SELECTED','FLOW_INSENSITIVE_MAY_FIELD_CONTENT_NOT_VERSION_IDENTITY')


class DescriptorFlow:
    def __init__(self,solver,units):
        self.s=solver;self.accesses=defaultdict(list);self.reads=defaultdict(list)
        self.lookups={};self.sinks={};self.targets=defaultdict(set)
        self.property_accesses={};self.property_templates={};self.storage_accesses={};self.connected=set()
        self.content_links={};self.field_writes=defaultdict(dict);self.field_reads=defaultdict(dict);self.call_ordinals={}
        for unit in units:
            for i in range(len(unit.attributes)):self.admit(unit,i)

    def admit(self,unit,index):
        o=self.s.offsets[unit.unit];a=unit.attributes[index]
        read=a.action in (F.AttributeAction.GET,F.AttributeAction.IMPORT_MEMBER)
        access=_Access((unit.unit,index),T.AttributeOrigin.IMPORT_MEMBER if a.action is F.AttributeAction.IMPORT_MEMBER
            else T.AttributeOrigin.ATTRIBUTE,a.action,o+a.receiver,a.name,
            o+a.value if read else None,o+a.value if a.action is F.AttributeAction.SET else None,
            o+a.world,o+a.result_world)
        self.register(access);return access

    def register(self,access):
        if access in self.accesses[access.receiver]:return
        self.accesses[access.receiver].append(access)
        if access.result is not None:self.reads[access.receiver,access.member,access.result].append(access)

    def site(self,a):
        gp=self.s.gp
        return T.AttributeSite(a.origin,a.action,gp(a.receiver),a.member,
            None if a.result is None else gp(a.result),None if a.assigned is None else gp(a.assigned),
            gp(a.world),gp(a.result_world),None if a.dynamic_member is None else gp(a.dynamic_member))

    def construct(self,index):
        unit,call=self.s.call_rows[index];o=self.s.offsets[unit.unit];result=o+call.result
        names=('fget','fset','fdel','doc');values=dict(call.keywords)
        if len(values)!=len(call.keywords) or len(call.positional)>4 or set(values)-set(names):return
        if any(n in values for n in names[:len(call.positional)]):return
        packed=call.positional_pack is not None or call.keyword_pack is not None
        endpoints=tuple(o+call.positional[i] if i<len(call.positional) else o+values[n] if n in values
            else _OpenAccessor.PACK if packed else None for i,n in enumerate(names[:3]))
        self.s.add(result,('property',_Property(result,endpoints)))

    def attribute(self,point,value,name,target):
        if value[0]!='property':return False
        prop=value[1]
        if name in ('getter','setter','deleter'):
            self.s.add(target,('property_method',prop,('getter','setter','deleter').index(name)))
        elif name in ('fget','fset','fdel'):
            endpoint=prop.accessors[('fget','fset','fdel').index(name)]
            if type(endpoint) is int:self.s.edge(endpoint,target)
            elif endpoint is None:self.s.add(target,('constant','NoneType',None))
            else:self.s.add(target,('external_value',target))
        else:self.s.add(target,('external_member',target,name))
        return True

    def call(self,index,value):
        unit,call=self.s.call_rows[index];o=self.s.offsets[unit.unit]
        if len(call.positional)!=1 or call.keywords or call.positional_pack is not None or call.keyword_pack is not None:return
        prop,slot=value[1:];endpoints=list(prop.accessors);endpoints[slot]=o+call.positional[0]
        result=o+call.result
        self.s.add(result,('property',_Property(result,tuple(endpoints))))

    def builtin_getattr(self,index,name):
        unit,call=self.s.call_rows[index];o=self.s.offsets[unit.unit]
        if len(call.positional) not in (2,3) or call.keywords or call.positional_pack is not None or call.keyword_pack is not None:return
        access=_Access(('getattr',index,name),T.AttributeOrigin.BUILTIN_GETATTR,F.AttributeAction.GET,
            o+call.positional[0],name,o+call.result,None,o+call.world,o+call.result_world,o+call.positional[1])
        self.register(access)
        # Builtin call targets/names may be learned after the receiver's queue
        # event. Replay the source receiver instead of depending on event order.
        for value in tuple(self.s.values[access.receiver]):self.consume(access.receiver,value)

    def storage(self,a,kind,owner,namespace_unit,conditions,receiver_class=None):
        key=(a.key,kind,owner,namespace_unit,receiver_class)
        if key not in self.storage_accesses:
            self.storage_accesses[key]=T.AttributeStorageAccess(self.site(a),kind,self.s.gp(owner),namespace_unit,conditions,
                None if receiver_class is None else self.s.gp(receiver_class))

    def reference(self,a):
        if a.origin is T.AttributeOrigin.BUILTIN_GETATTR:
            index=a.key[1]
            if index not in self.call_ordinals:
                unit,call=self.s.call_rows[index]
                self.call_ordinals[index]=(unit.unit,unit.calls.index(call))
            unit,ordinal=self.call_ordinals[index]
        else:unit,ordinal=a.key
        return T.AttributeFactReference(unit,ordinal,a.origin,a.member)

    def contents(self,key,a,kind,owner,receiver_class=None,namespace_unit=None,conditions=()):
        """Publish content dependencies; existing namespace transfer stays intact."""
        if a.action is F.AttributeAction.SET:
            if a.key in self.field_writes[key]:return
            self.field_writes[key][a.key]=a
            pairs=((a,read) for read in tuple(self.field_reads[key].values()))
        elif a.action is F.AttributeAction.GET:
            if a.key in self.field_reads[key]:return
            self.field_reads[key][a.key]=a
            pairs=((write,a) for write in tuple(self.field_writes[key].values()))
        else:return
        for write,read in pairs:
            identity=key,write.key,read.key
            if identity not in self.content_links:
                self.content_links[identity]=T.AttributeContentLink(self.reference(write),self.reference(read),
                    self.s.gp(write.assigned),self.s.gp(read.result),kind,self.s.gp(owner),
                    None if receiver_class is None else self.s.gp(receiver_class),namespace_unit,
                    (*conditions,'MAY_REACHING_STORE_NOT_SELECTED_STATE_VERSION','NO_SOURCE_ORDER_OR_RUNTIME_IDENTITY_PROOF'))

    def write_namespace(self,key,source):
        if source is None:return
        self.s.writes[source].add(key)
        for value in tuple(self.s.values[source]):self.s.namespace_value(key,value)

    def instance_storage(self,a,value):
        key=('field',value,a.member)
        self.storage(a,T.AttributeStorageKind.INSTANCE_FIELDS,value[2],None,_FIELD_CONDITIONS,value[1])
        self.contents(key,a,T.AttributeStorageKind.INSTANCE_FIELDS,value[2],value[1],conditions=_FIELD_CONDITIONS)
        if a.action is F.AttributeAction.SET:self.write_namespace(key,a.assigned)
        elif a.action is F.AttributeAction.GET:
            self.s.reads[key].add(a.result)
            for item in tuple(self.s.ns_values[key]):self.s.add(a.result,item)
        # DELETE is an explicit state transition in the original graph. The
        # may-union cannot erase values from earlier or alternative versions.

    def lookup(self,a,cls):
        key=(a.key,cls)
        if key in self.lookups:return
        sink=('attribute_descriptor_lookup',*key);self.lookups[key]=sink;self.sinks[sink]=(a,cls)
        self.s.class_lookup(cls,a.member,sink,a.receiver)

    def read(self,point,value,name,target):
        matches=self.reads.get((point,name,target),())
        for a in matches:
            if a.origin is T.AttributeOrigin.IMPORT_MEMBER:continue
            self.instance_storage(a,value);self.lookup(a,value[1])
        if not matches:
            # Do not return a property object as the result of an instance
            # read when the original state ABI has not been recovered.
            self.s.add(target,('external_member',target,name))

    def property(self,a,cls,prop):
        slot={F.AttributeAction.GET:0,F.AttributeAction.SET:1,F.AttributeAction.DELETE:2}[a.action]
        accessor=prop.accessors[slot];identity=(a.key,cls,prop)
        state=(T.PropertyAccessState.ACCESSOR_ARGUMENT_PACK_OPEN if accessor is _OpenAccessor.PACK
            else T.PropertyAccessState.ACCESSOR_ABSENT if accessor is None else T.PropertyAccessState.ACCESSOR_TARGET_OPEN)
        endpoint=self.s.gp(accessor) if type(accessor) is int else None
        if identity not in self.property_accesses:
            self.property_accesses[identity]=T.PropertyAccess(self.site(a),self.s.gp(prop.origin),self.s.gp(cls),endpoint,None,_PROPERTY_CONDITIONS,state)
        self.property_templates[identity]=self.property_accesses[identity]
        if type(accessor) is not int:return
        self.targets[accessor].add((a,cls,prop))
        for value in tuple(self.s.values[accessor]):self.accessor_target(a,cls,prop,accessor,value)

    def accessor_target(self,a,cls,prop,accessor,value):
        if value[0] not in ('function','bound','classbound'):
            base=(a.key,cls,prop)
            prior=self.property_templates[base]
            if value[0]=='constant':
                state=T.PropertyAccessState.ACCESSOR_ABSENT if value[1]=='NoneType' else T.PropertyAccessState.ACCESSOR_NOT_CALLABLE
                self.property_accesses[(*base,'constant',value[1],value[2])]=replace(prior,state=state)
            else:self.property_accesses[base]=prior
            if all(v[0] in ('function','bound','classbound','constant') for v in self.s.values[accessor]):
                self.property_accesses.pop(base,None)
            return
        fid=value[1];receiver=value[2] if value[0]=='bound' else value[3] if value[0]=='classbound' else None
        class_receiver=value[2] if value[0]=='classbound' else None
        identity=(a.key,cls,prop,fid,receiver,class_receiver)
        if identity in self.connected:return
        self.connected.add(identity)
        args=(a.receiver,) if a.assigned is None else (a.receiver,a.assigned)
        invocation=Invocation(accessor,args,(),a.result,a.world,a.result_world)
        connection=connect(self.s,fid,invocation,receiver,class_receiver=class_receiver,environment_source=fid,
            conditions=(*_PROPERTY_CONDITIONS,'PROPERTY_ACCESSOR_PRESENT_AND_CALLABLE'))
        base=(a.key,cls,prop);prior=self.property_templates[base]
        state=T.PropertyAccessState.CONNECTED if connection is not None else T.PropertyAccessState.SIGNATURE_INAPPLICABLE
        self.property_accesses[identity]=replace(prior,connection=connection,state=state)
        if connection is not None and all(v[0] in ('function','bound','classbound','constant') for v in self.s.values[accessor]):
            self.property_accesses.pop(base,None)

    def consume(self,point,value):
        if point in self.sinks:
            a,cls=self.sinks[point]
            if value[0]=='property':self.property(a,cls,value[1])
            elif a.result is not None:self.s.add(a.result,value)
        for a,cls,prop in tuple(self.targets.get(point,())):self.accessor_target(a,cls,prop,point,value)
        if value[0] not in ('instance','class','module'):return
        for a in self.accesses.get(point,()):
            if value[0]=='instance':
                if a.action in (F.AttributeAction.SET,F.AttributeAction.DELETE):
                    self.instance_storage(a,value);self.lookup(a,value[1])
            elif value[0]=='class':
                unit,descriptor=self.s.classes[value[1]]
                self.storage(a,T.AttributeStorageKind.CLASS_NAMESPACE,value[1],unit.unit,
                    ('DEFAULT_TYPE_ATTRIBUTE_SLOT_ADMISSION','METACLASS_DESCRIPTOR_PATH_NOT_SELECTED','FLOW_INSENSITIVE_MAY_NAMESPACE_VERSION'))
                if a.action is F.AttributeAction.SET:
                    self.write_namespace((unit.unit,F.NamespaceKind.CLASS.value,descriptor.scope,a.member),a.assigned)
            else:
                for unit in self.s.module_units.get(value[1],()):
                    self.storage(a,T.AttributeStorageKind.MODULE_NAMESPACE,point,unit,
                        ('STANDARD_MODULE_ATTRIBUTE_SLOT_ADMISSION','MODULE_DESCRIPTOR_PATH_NOT_SELECTED','FLOW_INSENSITIVE_MAY_NAMESPACE_VERSION'))
                    if a.action is F.AttributeAction.SET:self.write_namespace((unit,F.NamespaceKind.MODULE.value,0,a.member),a.assigned)
