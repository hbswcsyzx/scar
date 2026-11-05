"""Finite, conditional return-type and Tensor descriptor propagation.

Type/projection tags identify declarations at static ports. They are not
ObjectID, StorageID, logical versions, new allocations, or reference aliases.
"""
from collections import defaultdict

from scar.ir.literals import PythonLiteral
from scar.ir.program import binding_returns as R,tensor_values as V,python_bindings as B
from scar.ir.program.providers import ProviderFactReference


def schema_type(row):
    return R.SchemaType(row['text'],row['kind'],row.get('name'),
        None if row.get('element') is None else schema_type(row['element']),row.get('size'))


def value_shape(row):
    kind=row['kind'];element=row.get('element');items=row.get('items',())
    converted={'TENSOR_LIST':'SEQUENCE','LIST':'SEQUENCE','PRIMITIVE':'SCALAR','NUMBER':'SCALAR','NDARRAY':'OBJECT'}
    if kind=='TUPLE' and row.get('variadic'):kind='SEQUENCE'
    kind=converted.get(kind,kind)
    return R.ValueShape(R.ValueShapeKind(kind),tuple(value_shape(v) for v in items),
        None if element is None else value_shape(element),tuple(row.get('fields',())),row.get('container'),
        row.get('native_ordinal'),row.get('native_name'),row.get('python_type',row.get('scalar_type')),row.get('parser_index'))


class _ContainerAdapter:
    def __init__(self,base,flow):self.base=base;self.flow=flow;self.observers=()
    def __getattr__(self,name):return getattr(self.base,name)
    def consume(self,point,value):
        self.base.consume(point,value);self.flow.consume(point,value)
        for observer in self.observers:observer(point,value)
    def external(self,unit,call,name):
        self.base.external(unit,call,name);self.flow.replay_call_update(unit,call)
    def call(self,unit,call,value):
        self.base.call(unit,call,value);self.flow.replay_call_update(unit,call)


class TensorReturnFlow:
    def __init__(self,solver,units,stub,artifact):
        self.s=solver;self.stub=stub;self.artifact=artifact;self.methods=defaultdict(list);self.attributes=defaultdict(list)
        self.containers=solver.containers
        # Definition owners and conditional public-package exports come from
        # the recorded class declarations, not a guessed Tensor class list.
        self.descriptors={name for row in stub.get('classes',())
            for name in (row['qualified_name'],row['qualified_name'].split('.')[0]+'.'+row['name'])}
        self.shapes={};self.origins={};self.facts={};self.member_calls={};self.protocol_calls={}
        self.item_watch=defaultdict(list);self.key_watch=defaultdict(list);self.iterators=defaultdict(set);self.iter_reads=defaultdict(set)
        self.registered_units=set();self.admitted=set()
        for i,row in enumerate(stub['methods']):self.methods[row['name']].append((i,row))
        for i,row in enumerate(stub['attributes']):self.attributes[row['name']].append((i,row))
        solver.containers=_ContainerAdapter(solver.containers,self)
        for unit in units:self.register_unit(unit)

    def register_unit(self,unit,*,eager=True):
        if unit.unit in self.registered_units:return
        self.registered_units.add(unit.unit)
        if eager:
            for table in ('items','iterations','updates'):
                for index in range(len(getattr(unit,table))):self.admit(unit,table,index)

    def admit(self,unit,table,index):
        identity=unit.unit,table,index
        if identity in self.admitted:return
        self.admitted.add(identity);offset=self.s.offsets[unit.unit];item=getattr(unit,table)[index]
        if table=='items':
            key=offset+item.key if type(item.key) is int else item.key
            row=(offset+item.receiver,key,offset+item.value,item.write,offset+item.world,offset+item.result_world)
            self.item_watch[row[0]].append(row)
            if type(key) is int:self.key_watch[key].append(row)
            for value in tuple(self.s.values.get(row[0],())):self._item(value,row)
        elif table=='iterations':
            if item.advance:
                point=offset+item.source;self.iterators[point].add(offset+item.value)
                for value in tuple(self.s.values.get(point,())):self.consume(point,value)
        elif table=='updates':
            if not item.append:self.copy_content(offset+item.source,offset+item.target)
        else:raise ValueError('unknown Tensor return constraint table')

    def emit(self,key,origin,target,shape,source,conditions,path=()):
        self.origins.setdefault(key,(origin,source,conditions));self.shapes[key,path]=shape
        if shape.kind is R.ValueShapeKind.OPTIONAL:
            self.s.add(target,('constant','NoneType',None))
            if shape.element:self.emit(key,origin,target,shape.element,source,conditions,(*path,('OPTIONAL',None)))
            return
        if shape.kind is R.ValueShapeKind.UNION:
            for i,item in enumerate(shape.items):self.emit(key,origin,target,item,source,conditions,(*path,('ALTERNATIVE',i)))
            return
        identity=(key,target,path)
        if identity not in self.facts:
            projections=tuple(V.ReturnProjection(V.ProjectionKind(k),i) for k,i in path)
            self.facts[identity]=V.ReturnTypeEvidence(self.s.gp(origin),self.s.gp(target),projections,shape.kind,source,conditions)
        if shape.kind is R.ValueShapeKind.NONE:self.s.add(target,('constant','NoneType',None))
        else:self.s.add(target,('declared_result',key,path))

    def project(self,value,target,index=None,field=None,iterate=False,extra_conditions=()):
        key,path=value[1:];shape=self.shapes[key,path];origin,source,conditions=self.origins[key]
        conditions=(*conditions,*extra_conditions)
        chosen=[]
        if shape.kind in (R.ValueShapeKind.TUPLE,R.ValueShapeKind.NAMED_TUPLE):
            if field is not None:
                chosen=[shape.fields.index(field)] if field in shape.fields else []
            elif iterate or index is None:chosen=list(range(len(shape.items)))
            else:
                index=index+len(shape.items) if index<0 else index
                if 0<=index<len(shape.items):chosen=[index]
            for i in chosen:self.emit(key,origin,target,shape.items[i],source,conditions,(*path,('INDEX',i)))
        elif shape.kind in (R.ValueShapeKind.SEQUENCE,R.ValueShapeKind.ITERATOR) and shape.element is not None:
            self.emit(key,origin,target,shape.element,source,conditions,(*path,('ELEMENT',None)))

    def attribute(self,point,value,name,target):
        if value[0] in ('module','external') and value[1] in self.descriptors:
            generated=self.s.binding_symbols.get('torch.Tensor.'+name,())
            if not generated:
                for index,row in self.methods[name]:
                    if row['binding']=='INSTANCE':self.s.add(target,('declared_member',index,None))
        if value[0]!='declared_result':return
        shape=self.shapes[value[1],value[2]]
        if shape.kind is R.ValueShapeKind.NAMED_TUPLE:
            self.project(value,target,field=name);return
        if shape.kind not in (R.ValueShapeKind.TENSOR,R.ValueShapeKind.SELF):return
        generated=[d for d in self.s.binding_symbols.get('torch.Tensor.'+name,()) if d.kind is B.BindingKind.METHOD]
        for definition in generated:self.s.add(target,('generated_bound',definition.id.value,point))
        # A stub describes interfaces absent from generated tables, not a
        # substitute ATen selector or proof of the live Tensor descriptor.
        if not generated:
            for index,row in self.methods[name]:
                if row['binding']=='INSTANCE':self.s.add(target,('declared_member',index,point))
        for index,row in self.attributes[name]:
            self.emit(('attribute',target,row['id']),target,target,value_shape(row['returns']),
                ProviderFactReference(self.artifact,'#/attributes/'+str(index)),tuple(row['conditions']))

    def _site(self,index):
        unit,call=self.s.call_rows[index];o=self.s.offsets[unit.unit];gp=lambda p:self.s.gp(o+p)
        return B.SourceCallSite(gp(call.callee),tuple(map(gp,call.positional)),tuple((n,gp(p)) for n,p in call.keywords),
            gp(call.result),gp(call.world),gp(call.result_world),None if call.positional_pack is None else gp(call.positional_pack),
            None if call.keyword_pack is None else gp(call.keyword_pack))

    def call_member(self,index,value):
        row_index,receiver=value[1:];row=self.stub['methods'][row_index]
        mode=R.ReceiverMode.BOUND if receiver is not None else R.ReceiverMode.UNBOUND
        if mode is R.ReceiverMode.UNBOUND:
            unit,call=self.s.call_rows[index]
            if call.positional:receiver=self.s.offsets[unit.unit]+call.positional[0]
        identity=(index,row['id'],receiver,mode)
        if identity in self.member_calls:return
        site=self._site(index);source=ProviderFactReference(self.artifact,'#/methods/'+str(row_index));conditions=tuple(row['conditions'])
        if mode is R.ReceiverMode.UNBOUND:conditions+=('CURRENT_NAMESPACE_EXPORT_ADMISSION',)
        self.member_calls[identity]=V.DeclaredMemberCall(site,None if receiver is None else self.s.gp(receiver),
            row['name'],source,conditions,receiver_mode=mode)
        unit,call=self.s.call_rows[index];point=self.s.offsets[unit.unit]+call.result
        self.emit(('member',*identity),point,point,value_shape(row['returns']),source,conditions)

    def native_return(self,index,definition,candidate,point):
        shape=definition.python_return
        if shape is None:return
        source=ProviderFactReference(definition.source.artifact,definition.source.locator+'/python_return')
        if shape.kind is R.ValueShapeKind.ARGUMENT:
            parameter=next((a for a in definition.arguments if a.parser_index==shape.parser_index),None)
            unit,call=self.s.call_rows[index];offset=self.s.offsets[unit.unit]
            if parameter is not None:
                values=dict(call.keywords);actual=values.get(parameter.name)
                shift=1 if candidate.receiver_mode=='UNBOUND' else 0
                if actual is None and parameter.position is not None and parameter.position+shift<len(call.positional):actual=call.positional[parameter.position+shift]
                if actual is not None:
                    # Explicit wrapper return-input relation, not inferred from
                    # a Tensor type or schema alias annotation. Flow remains may.
                    self.s.edge(offset+actual,point)
        self.emit(('native',index,definition.id.value,candidate.receiver),point,point,shape,source,candidate.conditions)

    def copy_content(self,source,target):
        if not any(v[0]=='container' and v[2]=='SEQUENCE' for v in self.s.values[target]):return
        for value in tuple(self.s.values[source]):
            if value[0]=='declared_content':self.s.add(target,value)
            elif value[0]=='declared_result' and self.shapes[value[1],value[2]].kind in (
                    R.ValueShapeKind.TUPLE,R.ValueShapeKind.NAMED_TUPLE,
                    R.ValueShapeKind.SEQUENCE,R.ValueShapeKind.ITERATOR):
                # A finite element-type summary, never the type of the copied
                # container itself or an entry in reference-content storage.
                self.s.add(target,('declared_content',value))

    def replay_call_update(self,unit,call):
        if not call.positional:return
        source=self.s.offsets[unit.unit]+call.positional[0]
        for target in tuple(self.containers.updates[source]):self.copy_content(source,target)

    def indices(self,key):
        if type(key) is PythonLiteral:
            literal=key.to_python()
            if type(literal) in (int,bool):yield int(literal),()
        elif type(key) is int:
            for literal in tuple(self.s.values[key]):
                if literal[0]=='constant' and type(literal[2]) in (int,bool):yield int(literal[2]),()
                elif literal[0] in ('external_value','external_member'):yield None,('INTEGER_INDEX_PROTOCOL_ADMISSION',)
                elif literal[0]=='declared_result':
                    shape=self.shapes[literal[1],literal[2]]
                    if shape.kind is R.ValueShapeKind.SCALAR and shape.python_type in (None,'int','bool'):
                        yield None,('INTEGER_INDEX_PROTOCOL_ADMISSION',)

    def _item(self,value,row):
        receiver,key,target,write,world,result_world=row
        if value[0]=='declared_content':
            if not write:
                for _,conditions in self.indices(key):self.project(value[1],target,iterate=True,extra_conditions=conditions)
            return
        if value[0]!='declared_result':return
        shape=self.shapes[value[1],value[2]]
        if shape.kind in (R.ValueShapeKind.TENSOR,R.ValueShapeKind.SELF):
            member='__setitem__' if write else '__getitem__'
            for index,decl in self.methods[member]:
                if decl['binding']!='INSTANCE':continue
                source=ProviderFactReference(self.artifact,'#/methods/'+str(index));conditions=tuple(decl['conditions'])
                argument=self.s.gp(key) if type(key) is int else key
                identity=(receiver,target,write,decl['id'])
                self.protocol_calls[identity]=V.DeclaredProtocolCall(self.s.gp(receiver),member,argument,None if write else self.s.gp(target),
                    self.s.gp(world),self.s.gp(result_world),source,conditions,self.s.gp(target) if write else None)
                if not write:self.emit(('item',*identity),target,target,value_shape(decl['returns']),source,conditions)
            return
        if write:return
        for index,conditions in self.indices(key):self.project(value,target,index=index,extra_conditions=conditions)

    def consume(self,point,value):
        for target in tuple(self.containers.updates[point]):self.copy_content(point,target)
        if value[0]=='container':
            for source in tuple(self.containers.update_targets[point]):self.copy_content(source,point)
        for row in self.item_watch[point]:self._item(value,row)
        for row in self.key_watch[point]:
            for receiver in tuple(self.s.values[row[0]]):self._item(receiver,row)
        for target in tuple(self.iterators[point]):
            if value[0]=='iterator':
                self.iter_reads[value[1]].add(target)
                for item in tuple(self.s.values[value[1]]):
                    if item[0]=='declared_result':self.project(item,target,iterate=True)
                    elif item[0]=='declared_content':self.project(item[1],target,iterate=True)
        if value[0] in ('declared_result','declared_content'):
            projected=value if value[0]=='declared_result' else value[1]
            for target in tuple(self.iter_reads[point]):self.project(projected,target,iterate=True)
