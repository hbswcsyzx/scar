"""Persistent plain-input evaluation and version-scoped configuration reads.

Only the analysis tool's immutable cells are evaluated. No target containers,
custom constructors, resolvers, callbacks or user functions are invoked.
"""
from dataclasses import dataclass,replace
import re

from scar.ir.literals import PythonLiteral
from scar.ir.program import configuration_values as V
from scar.ir.program.data_materials import DataNodeKind
from scar.ir.program.configuration_overrides import OverrideExpressionKind


K=V.ConfigurationValueKind
E=V.ConfigurationExpressionKind


@dataclass(frozen=True,slots=True)
class _Cell:
    kind: K
    literal: PythonLiteral | None = None
    origins: tuple[V.ConfigurationInput,...] = ()
    entries: tuple[tuple[str,'_Cell'],...] = ()
    items: tuple['_Cell',...] = ()
    open_keys: bool = False


_ABSENT=_Cell(K.ABSENT)
_OPEN=_Cell(K.OPEN)
_EMPTY=_Cell(K.MAPPING)


def _unique(items):return tuple(dict.fromkeys(items))


def _split_key(key):
    first=re.match(r'(\.)*[^.[]*',key);stop=first.end()
    tokens=key[:stop].split('.')
    if stop==len(key):return tokens
    if key[stop]=='[' and not tokens[-1]:tokens.pop()
    tokens.extend(dot if dot else bracket for dot,bracket in re.findall(r'\.([^.[]*)|\[(.*?)\]',key[stop:]))
    return tokens


def _scalar(literal,origin):
    if literal is None:return _Cell(K.OPEN,origins=(origin,))
    value=literal.to_python()
    kind=K.MISSING if value=='???' else K.INTERPOLATION if type(value) is str and '${' in value else K.SCALAR
    return _Cell(kind,literal if kind in (K.SCALAR,K.INTERPOLATION) else None,(origin,))


class ConfigurationValueQuery:
    def __init__(self,expressions,materials,overrides,override_sha,syntax,conditions,*,max_projections=20000):
        self.expressions=tuple(expressions);self.materials=materials;self.overrides=overrides
        self.override_sha=override_sha;self.syntax=syntax;self.conditions=conditions
        self.max_projections=max_projections;self.cells={};self.source_cells={};self.source_active=set()
        self.projections=[];self.query_ids={};self.resolved={};self.locations={}
        self.interpolations=[];self.read_demands=[];self.obligations=[];self.obligation_keys=set()
        self.texts={}

    def obligation(self,code,expression=None,projection=None,detail=''):
        key=(code,expression,projection,detail)
        if key not in self.obligation_keys:
            self.obligation_keys.add(key)
            self.obligations.append(V.ConfigurationValueObligation(*key))

    def _input(self,source):
        if source in self.source_cells:return self.source_cells[source]
        if source.table=='MATERIAL_REFERENCE':
            material=self.materials[source.owner]
            node=material.nodes[material.references[source.ordinal].target]
            active=(source.owner,node.ordinal)
            if active in self.source_active:
                self.obligation('CYCLIC_INPUT_CONSTRUCTION_PENDING',detail=repr(source))
                return _Cell(K.OPEN,origins=(source,))
            self.source_active.add(active)
            child=lambda ref:self._input(V.ConfigurationInput(source.table,source.owner,ref))
            if node.kind is DataNodeKind.SCALAR:cell=_scalar(node.representation_literal,source)
            elif node.kind is DataNodeKind.SEQUENCE:
                cell=_Cell(K.SEQUENCE,origins=(source,),items=tuple(child(ref) for ref in node.items))
            else:
                entries={};open_keys=False
                for pair in node.entries:
                    key=material.nodes[material.references[pair.key].target].representation_literal
                    value=None if key is None else key.to_python()
                    if type(value) is str:entries[value]=child(pair.value)
                    else:
                        open_keys=True
                        self.obligation('NON_STRING_MAPPING_SELECTOR_PENDING',detail=repr(source))
                cell=_Cell(K.MAPPING,origins=(source,),entries=tuple(entries.items()),open_keys=open_keys)
            self.source_active.remove(active)
        else:
            if source.table!='OVERRIDE_EXPRESSION' or source.owner!=self.override_sha:
                raise ValueError('input expression belongs to a different graph')
            node=self.overrides.expressions[source.ordinal]
            child=lambda ref:self._input(V.ConfigurationInput(source.table,source.owner,ref))
            if node.kind is OverrideExpressionKind.SCALAR:cell=_scalar(node.literal,source)
            elif node.kind is OverrideExpressionKind.SEQUENCE:
                cell=_Cell(K.SEQUENCE,origins=(source,),items=tuple(child(ref) for ref in node.children))
            elif node.kind is OverrideExpressionKind.MAPPING:
                entries={};open_keys=False
                for key,value in node.entries:
                    literal=self.overrides.expressions[key].literal
                    text=None if literal is None else literal.to_python()
                    if type(text) is str:entries[text]=child(value)
                    else:open_keys=True;self.obligation('NON_STRING_MAPPING_SELECTOR_PENDING',detail=repr(source))
                cell=_Cell(K.MAPPING,origins=(source,),entries=tuple(entries.items()),open_keys=open_keys)
            else:
                self.obligation('UNEVALUATED_INPUT_EXPRESSION',detail=repr(source))
                cell=_Cell(K.OPEN,origins=(source,))
        self.source_cells[source]=cell
        return cell

    @staticmethod
    def _member(cell,key,*,negative=False):
        if cell.kind is K.MAPPING:return dict(cell.entries).get(key,_OPEN if cell.open_keys else _ABSENT)
        if cell.kind is K.SEQUENCE:
            try:index=int(key)
            except ValueError:return _Cell(K.TYPE_CONFLICT)
            return cell.items[index] if (0<=index<len(cell.items) or negative and -len(cell.items)<=index<0) else _ABSENT
        if cell.kind in (K.OPEN,K.CYCLE,K.TYPE_CONFLICT):return cell
        if cell.kind in (K.ABSENT,K.MISSING):return cell
        return _Cell(K.NONCONTAINER,origins=cell.origins)

    def _demand(self,operation,path,cell,*,snapshot=None,phase='MERGE_INTERNAL_STATE_PENDING',projection=None):
        self.read_demands.append(V.ConfigurationReadDemand(len(self.read_demands),operation,snapshot,path,phase,
            cell.origins[0] if cell.origins else None,projection))

    def _merge(self,left,right,operation,path=()):
        if right.kind is K.ABSENT:return left
        if left.kind is K.INTERPOLATION:
            self._demand(operation,path,left)
            self.obligation('EAGER_MERGE_DESTINATION_STATE_PENDING',operation,detail=repr(path))
            return _Cell(K.OPEN,origins=_unique((*left.origins,*right.origins)))
        if right.kind is K.INTERPOLATION and left.kind in (K.MAPPING,K.SEQUENCE,K.OPEN):
            self._demand(operation,path,right)
            self.obligation('EAGER_MERGE_SOURCE_VALIDATION_PENDING',operation,detail=repr(path))
            if left.kind is not K.OPEN:return _Cell(K.OPEN,origins=_unique((*left.origins,*right.origins)))
            # The raw lazy candidate remains useful under the explicit open-
            # destination/no-eager-side-effect guard. The demand is not erased.
        if right.kind is K.MISSING:
            if left.kind is K.ABSENT:return right
            if left.kind is K.OPEN:
                self.obligation('MISSING_FALLTHROUGH_TO_OPEN_INPUT',operation,detail=repr(path))
                return _Cell(K.OPEN,origins=_unique((*left.origins,*right.origins)))
            return left
        if right.kind is K.MAPPING:
            if left.kind is K.SEQUENCE:return _Cell(K.TYPE_CONFLICT,origins=_unique((*left.origins,*right.origins)))
            if left.kind in (K.ABSENT,K.MISSING,K.SCALAR):return right
            if left.kind not in (K.MAPPING,K.OPEN):return _Cell(K.OPEN,origins=_unique((*left.origins,*right.origins)))
            entries=dict(left.entries);open_keys=left.open_keys or left.kind is K.OPEN
            if right.open_keys:
                entries={key:_OPEN for key in entries};open_keys=True
            for key,value in right.entries:
                entries[key]=self._merge(entries.get(key,_OPEN if open_keys else _ABSENT),value,operation,(*path,key))
            return _Cell(K.MAPPING,origins=_unique((*left.origins,*right.origins)),
                entries=tuple(entries.items()),open_keys=open_keys)
        if right.kind is K.SEQUENCE and left.kind is K.MAPPING:
            return _Cell(K.TYPE_CONFLICT,origins=_unique((*left.origins,*right.origins)))
        return right

    def _update(self,cell,path,value,operation,*,merge=False,delete=False,prefix=()):
        if not path:return value
        if cell.kind is K.INTERPOLATION:
            snapshot=self.expressions[operation].inputs[0]
            query=self.project(snapshot,prefix)
            self._demand(operation,prefix,cell,snapshot=snapshot,phase='UPDATE_INTERMEDIATE',projection=query)
            self.obligation('INTERMEDIATE_UPDATE_ALIAS_EFFECT_PENDING',operation,query,repr(prefix))
            # An aliased container can redirect writes outside the requested
            # path. Do not preserve unrelated field facts across this effect.
            raise _OpenUpdate
        if cell.kind is K.OPEN:
            snapshot=self.expressions[operation].inputs[0]
            query=self.project(snapshot,prefix)
            self._demand(operation,prefix,cell,snapshot=snapshot,phase='UPDATE_INTERMEDIATE',projection=query)
            self.obligation('OPEN_UPDATE_ADDRESS_SELECTION_PENDING',operation,query,repr(prefix))
            cell=_Cell(K.MAPPING,open_keys=True)
        if cell.kind not in (K.MAPPING,K.SEQUENCE):cell=_EMPTY
        key,*rest=path;old=self._member(cell,key,negative=not rest)
        if rest:new=self._update(old,tuple(rest),value,operation,merge=merge,delete=delete,prefix=(*prefix,key))
        elif delete:new=_ABSENT
        elif merge:
            new=self._merge(old,value,operation,(*prefix,key)) if old.kind in (K.MAPPING,K.SEQUENCE,K.OPEN) else value
        else:new=value
        if cell.kind is K.SEQUENCE:
            try:index=int(key)
            except ValueError:return _Cell(K.TYPE_CONFLICT)
            if not -len(cell.items)<=index<len(cell.items):return _Cell(K.TYPE_CONFLICT)
            items=list(cell.items)
            if delete and not rest:items.pop(index)
            else:items[index]=new
            return replace(cell,items=tuple(items))
        entries=dict(cell.entries);entries[key]=new
        return replace(cell,entries=tuple(entries.items()))

    def compute(self,ordinal):
        if ordinal in self.cells:return self.cells[ordinal]
        expression=self.expressions[ordinal];inputs=[self.compute(i) for i in expression.inputs]
        if expression.kind is E.EMPTY:cell=_EMPTY
        elif expression.kind is E.OPEN_PROVIDER:cell=_Cell(K.MAPPING,open_keys=True)
        elif expression.kind is E.INPUT:
            cell=self._input(expression.source)
            if expression.exclude_root_keys:
                if cell.kind is not K.MAPPING:cell=_Cell(K.TYPE_CONFLICT,origins=cell.origins)
                else:cell=replace(cell,entries=tuple((k,v) for k,v in cell.entries if k not in expression.exclude_root_keys))
        elif expression.kind is E.EMBED:
            cell=inputs[0]
            for key in reversed(expression.path):cell=_Cell(K.MAPPING,entries=((key,cell),))
        elif expression.kind is E.MERGE:cell=self._merge(*inputs,ordinal)
        else:
            row=self.overrides.overrides[expression.parent_ordinal]
            if row.action.value in ('ADD','DELETE'):
                snapshot=expression.inputs[0];dependencies=[]
                target,_=self._locate(snapshot,expression.path,dependencies)
                if target.kind is K.INTERPOLATION:
                    query=self.project(snapshot,expression.path)
                    self._demand(ordinal,expression.path,target,snapshot=snapshot,phase='UPDATE_INTERMEDIATE',projection=query)
            try:cell=self._update(inputs[0],expression.path,inputs[1] if len(inputs)>1 else _ABSENT,ordinal,
                merge=expression.kind is E.UPDATE,delete=expression.kind is E.DELETE)
            except _OpenUpdate:cell=_Cell(K.MAPPING,open_keys=True)
        self.cells[ordinal]=cell
        return cell

    def _locate(self,root,path,dependencies):
        cell=self.compute(root);location=()
        for key in path:
            if cell.kind is K.INTERPOLATION:
                query=self.project(root,location);dependencies.append(query)
                cell=self.resolved.get(query,_Cell(K.CYCLE));target=self.locations.get(query)
                if target is None:return cell,None
                location=target
            cell=self._member(cell,key);location=(*location,key)
        return cell,location

    def _node_interpolation(self,node,root,owner,projection):
        pieces=[];dependencies=[];unknown=False
        for child in node.children:
            if type(child).__name__=='ConfigKeyContext':
                key=child.getChild(0)
                if type(key).__name__=='InterpolationContext':
                    value,_,nested=self._interpolation(key,root,owner,projection)
                    dependencies.extend(nested)
                    if value.kind is not K.SCALAR or type(value.literal.to_python()) is not str:
                        unknown=True
                    else:pieces.append(value.literal.to_python())
                else:pieces.append(child.getText())
            elif child.getText() in ('.','[',']'):pieces.append(child.getText())
        if unknown:return _OPEN,None,tuple(dependencies),'DYNAMIC'
        inter_key=''.join(pieces);dots=len(inter_key)-len(inter_key.lstrip('.'))
        parent=owner[:-1]
        if dots:
            if dots-1>len(parent):
                self.obligation('RELATIVE_INTERPOLATION_ABOVE_ROOT',root,projection,node.getText())
                return _OPEN,None,tuple(dependencies),'NODE'
            base=parent[:len(parent)-(dots-1)]
        else:base=()
        rest=inter_key[dots:];target=(*base,*(_split_key(rest) if rest else ()))
        if len(target)<len(owner) and owner[:len(target)]==target:
            self.obligation('INTERPOLATION_TO_ANCESTOR_PENDING',root,projection,node.getText())
            return _OPEN,target,tuple(dependencies),'NODE'
        query=self.project(root,target);dependencies.append(query)
        value=self.resolved.get(query,_Cell(K.CYCLE))
        if value.kind in (K.MISSING,K.ABSENT):
            self.obligation('INTERPOLATION_TARGET_'+value.kind.value,root,projection,repr(target))
            return _OPEN,target,tuple(dependencies),'NODE'
        return value,target,tuple(dependencies),'NODE'

    def _interpolation(self,ctx,root,owner,projection):
        node=ctx.getChild(0)
        if type(node).__name__=='InterpolationNodeContext':
            value,target,dependencies,kind=self._node_interpolation(node,root,owner,projection)
        else:
            # Record nested reads even when a resolver's value/effects are open.
            dependencies=[];pending=list(reversed(node.children or ()))
            while pending:
                child=pending.pop()
                if type(child).__name__=='InterpolationContext':
                    _,_,nested=self._interpolation(child,root,owner,projection);dependencies.extend(nested)
                elif hasattr(child,'children'):pending.extend(reversed(child.children or ()))
            value=_OPEN;target=None;dependencies=tuple(dependencies);kind='RESOLVER'
            self.obligation('CUSTOM_RESOLVER_VALUE_AND_EFFECT_PENDING',root,projection,node.getText())
        start,end=ctx.start.start,ctx.stop.stop+1
        self.interpolations.append(V.ConfigurationInterpolation(len(self.interpolations),projection,
            start,end,self.texts[projection][start:end],kind,target,dependencies))
        return value,target,dependencies

    def _resolve(self,cell,root,owner,projection):
        text=cell.literal.to_python();self.texts[projection]=text
        tree=self.syntax.parse(text);parts=tree.text().children
        if len(parts)==1 and type(parts[0]).__name__=='InterpolationContext':
            value,target,dependencies=self._interpolation(parts[0],root,owner,projection)
            location=self.locations.get(dependencies[-1],target) if dependencies else target
            return value,location,dependencies
        values=[];dependencies=[];unknown=False
        for index,part in enumerate(parts):
            if type(part).__name__=='InterpolationContext':
                value,_,nested=self._interpolation(part,root,owner,projection);dependencies.extend(nested)
                if value.kind is not K.SCALAR:
                    self.obligation('NON_SCALAR_TEMPLATE_RENDERING_PENDING',root,projection,part.getText())
                    unknown=True
                else:values.append(str(value.literal.to_python()))
            else:
                symbol=part.symbol;following=parts[index+1] if index+1<len(parts) else None
                if symbol.type==self.syntax.lexer.ESC_INTER:values.append(symbol.text[-(len(symbol.text)//2+1):])
                elif symbol.type==self.syntax.lexer.ESC or (symbol.type in (self.syntax.lexer.TOP_ESC,self.syntax.lexer.QUOTED_ESC)
                        and (type(following).__name__=='InterpolationContext' or (following is None and symbol.type==self.syntax.lexer.QUOTED_ESC))):
                    values.append(symbol.text[1::2])
                else:values.append(symbol.text)
        value=_OPEN if unknown else _Cell(K.SCALAR,PythonLiteral.from_python(''.join(values),exact=True),cell.origins)
        return value,owner,tuple(dependencies)

    def project(self,root,path):
        path=tuple(path);key=(root,path)
        if key in self.query_ids:return self.query_ids[key]
        if len(self.projections)>=self.max_projections:raise ValueError('configuration projection budget reached')
        ordinal=len(self.projections);self.query_ids[key]=ordinal;self.projections.append(None)
        dependencies=[];cell,location=self._locate(root,path,dependencies)
        if cell.kind is K.INTERPOLATION:
            raw=cell;cell,location,nested=self._resolve(cell,root,location,ordinal);dependencies.extend(nested)
            origins=_unique((*raw.origins,*cell.origins))
        else:origins=cell.origins
        if cell.kind is K.CYCLE:self.obligation('CYCLIC_INTERPOLATION_DEPENDENCY',root,ordinal,repr(path))
        self.resolved[ordinal]=cell;self.locations[ordinal]=location
        complete=not cell.open_keys if cell.kind is K.MAPPING else True if cell.kind is K.SEQUENCE else None
        self.projections[ordinal]=V.ConfigurationProjection(ordinal,root,path,cell.kind,
            cell.literal if cell.kind is K.SCALAR else None,complete,origins,tuple(dependencies),(root,),location,self.conditions)
        return ordinal

    def known_paths(self,root,*,max_paths=10000):
        pending=[((),self.compute(root))];result=[]
        while pending:
            path,cell=pending.pop();result.append(path)
            if len(result)>=max_paths:
                self.obligation('KNOWN_PATH_ENUMERATION_BUDGET',root,detail=str(max_paths));break
            pending.extend(((*path,key),value) for key,value in reversed(cell.entries))
            pending.extend(((*path,str(i)),value) for i,value in reversed(tuple(enumerate(cell.items))))
        return tuple(result)


class _OpenUpdate(Exception):pass
