"""Source-bound variable annotation groups from static compiler queries.

The primary query replaces annotation expressions in a temporary AST restored
from original F2 references. Marker loads recover emission order, duplicate
finally emissions and conditional indices. Pruned source templates use an
explicitly marked ancestor-control projection. No source/name/line join,
parsing, target execution or query capture-layout reuse is involved.
"""
import ast
import dis
from copy import deepcopy
from types import CodeType
from scar.analysis.source_syntax import _restore_ast
from scar.ir.program import source_productions as P
from scar.ir.program.protocol_signatures import ExceptionABI


def _require(condition,path,detail):
    if not condition:
        from scar.analysis.source_productions import ProductionError
        raise ProductionError('SCOPE_ANNOTATION_INTERFACE',str(path),detail)


def _codes(root):
    pending=[root];seen=set()
    while pending:
        item=pending.pop()
        if id(item) in seen:continue
        seen.add(id(item));yield item
        pending.extend(c for c in item.co_consts if type(c) is CodeType)


class ScopeAnnotationIndex:
    def __init__(self,source):
        self.source=source;self._interfaces=None

    def _emissions(self,code,markers,level):
        by_scope={}
        for unit in _codes(code):
            ops=[op for op in dis.get_instructions(unit) if op.opname not in ('EXTENDED_ARG','NOT_TAKEN')]
            entries=[];scopes=set()
            for i,op in enumerate(ops):
                if op.opname!='LOAD_CONST' or type(op.argval) is not bytes or op.argval not in markers:continue
                publication=markers[op.argval]
                scope=self.source.context.context_at_slot(publication.annotation).state.environment
                scopes.add(scope);tail=ops[i+1:i+4]
                _require(len(tail)==3 and tail[0].opname=='COPY' and tail[0].arg==2
                    and tail[1].opname=='LOAD_CONST' and type(tail[1].argval) is str and tail[2].opname=='STORE_SUBSCR',
                    publication.annotation,'controlled compiler marker/store shape differs')
                registration=None
                if publication.conditional_registration:
                    guard=ops[i-4:i]
                    _require(len(guard)==4 and guard[0].opname in ('LOAD_CONST','LOAD_SMALL_INT')
                        and type(guard[0].argval) is int and guard[0].argval>=0
                        and guard[1].opname in ('LOAD_DEREF','LOAD_GLOBAL')
                        and guard[1].argval=='__conditional_annotations__'
                        and guard[2].opname=='CONTAINS_OP' and guard[2].arg==0
                        and guard[3].opname=='POP_JUMP_IF_FALSE',publication.annotation,
                        'controlled compiler conditional registration shape differs')
                    registration=P.AnnotationRegistration(scope,level,guard[0].argval)
                entries.append(P.ScopeAnnotationEntry(publication.annotation,publication.name,tail[1].argval,registration))
            if not entries:continue
            _require(len(scopes)==1,scopes,'one callback must not mix original source annotation groups')
            scope=scopes.pop();entries=tuple(entries)
            _require(scope not in by_scope or by_scope[scope]==entries,scope,
                'repeated code-unit emission has incompatible annotation interfaces')
            by_scope[scope]=entries
        return by_scope

    def _projection(self,objects,scope):
        """Admit an otherwise pruned class template, retaining its whole body.

        Only ancestor/sibling control is relaxed. Its query's capture/frame
        layout is discarded. An explicit flag distinguishes this source
        template from code retained by the original compilation.
        """
        source=self.source;roles=source.roles;syntax=source.context.syntax
        owner=source.context.material.scopes[scope].owner.occurrence
        protected={owner};pending=[owner]
        while pending:
            row=syntax.nodes[pending.pop()]
            for value in row.fields:
                children=(value.reference,) if value.kind=='NODE' else tuple(
                    v.reference for v in value.items if v.kind=='NODE') if value.kind=='LIST' else ()
                protected.update(children);pending.extend(children)
        query=deepcopy(objects)
        names={n.value for n in source.frontend.declarations.names};suffix=0
        while (name:='_scar_static_annotation_condition_'+str(suffix)) in names:suffix+=1
        def unknown(location):return ast.copy_location(ast.Name(id=name,ctx=ast.Load()),location)
        def condition(value):
            return ast.copy_location(ast.Compare(left=value,ops=[ast.Is()],comparators=[unknown(value)]),value)
        try_bodies=[]
        for original,node in query.items():
            if original in protected:continue
            if type(node) in (ast.If,ast.While,ast.Assert):node.test=condition(node.test)
            elif type(node) in (ast.For,ast.AsyncFor):
                node.iter=ast.copy_location(ast.Tuple(elts=[node.iter,unknown(node.iter)],ctx=ast.Load()),node.iter)
            elif type(node) is ast.match_case:
                if node.guard is not None:node.guard=condition(node.guard)
            elif type(node) is ast.Match:node.subject=condition(node.subject)
            elif type(node) in (ast.Try,ast.TryStar):
                try_bodies.append(node)
            elif type(node) in (ast.Return,ast.Raise,ast.Break,ast.Continue):
                edge=roles.parents[original];parent=query[edge.occurrence]
                field=tuple(roles.fields[syntax.nodes[edge.occurrence].constructor])[edge.ordinal]
                values=([node.value] if type(node) is ast.Return and node.value is not None else
                    [v for v in (node.exc,node.cause) if v is not None] if type(node) is ast.Raise else [])
                expression=values[0] if len(values)==1 else ast.copy_location(ast.Tuple(elts=values,ctx=ast.Load()),node)
                replacement=ast.copy_location(ast.Expr(value=expression) if values else ast.Pass(),node)
                if edge.item_path:
                    container=getattr(parent,field)
                    for i in edge.item_path[:-1]:container=container[i]
                    container[edge.item_path[-1]]=replacement
                else:setattr(parent,field,replacement)
        # Preserve original list-slot indices until every replacement is done.
        for node in try_bodies:node.body.insert(0,ast.copy_location(ast.Expr(value=unknown(node)),node))
        return query[syntax.root]

    def _collect(self):
        source=self.source;syntax=source.context.syntax;roles=source.roles
        publications={}
        for occurrence,node in enumerate(syntax.nodes):
            if node.constructor!='AnnAssign':continue
            publication=source.statements.annotation_publication(occurrence,ExceptionABI.EXCEPTION_WORLD)
            if publication is not None and publication.publication is P.AnnotationPublicationKind.DEFERRED:
                publications[occurrence]=publication
        if not publications:return {}
        # Restore once, then pair original field references with their restored
        # objects. Temporary object identities never escape into the IR.
        tree=_restore_ast(syntax.root,syntax.nodes);objects={syntax.root:tree};pending=[syntax.root]
        while pending:
            original=pending.pop();node=syntax.nodes[original];restored=objects[original]
            for name,value in zip(roles.fields[node.constructor],node.fields):
                if value.kind=='NODE':objects[value.reference]=getattr(restored,name);pending.append(value.reference)
                elif value.kind=='LIST':
                    for item,other in zip(value.items,getattr(restored,name)):
                        if item.kind=='NODE':objects[item.reference]=other;pending.append(item.reference)
        # Reserve markers absent from all original compiled constants, including
        # folded tuples/bytes, for every supported target optimization policy.
        constants=set()
        for level in (0,1,2):
            code=compile(tree,'<scar-static-original-annotations>',syntax.mode,dont_inherit=True,optimize=level)
            values=[c for unit in _codes(code) for c in unit.co_consts]
            while values:
                value=values.pop()
                if type(value) is bytes:constants.add(value)
                elif type(value) in (tuple,frozenset):values.extend(value)
        markers={};groups={}
        for occurrence,publication in publications.items():
            ordinal=0
            marker=('SCAR-ANNOTATION:'+str(occurrence)+':0').encode()
            while marker in constants:
                ordinal+=1;marker=('SCAR-ANNOTATION:'+str(occurrence)+':'+str(ordinal)).encode()
            constants.add(marker);markers[marker]=publication
            expression=objects[occurrence].annotation
            objects[occurrence].annotation=ast.copy_location(ast.Constant(value=marker),expression)
            scope=source.context.context_at_slot(publication.annotation).state.environment
            groups.setdefault(scope,{})
        for level in (0,1,2):
            code=compile(tree,'<scar-static-annotation-emissions>',syntax.mode,dont_inherit=True,optimize=level)
            by_scope=self._emissions(code,markers,level)
            for scope in groups:
                emitted=scope in by_scope
                if not emitted:
                    projection=self._projection(objects,scope)
                    selected=self._emissions(compile(projection,'<scar-static-annotation-template>',
                        syntax.mode,dont_inherit=True,optimize=level),markers,level)
                    _require(scope in selected,scope,'compiler template projection omitted a source annotation group')
                    by_scope[scope]=selected[scope]
                groups[scope][level]=P.ScopeAnnotationVariant(level,by_scope[scope],emitted)
        result={}
        for scope,variants in groups.items():
            creator=source.context.material.scopes[scope].parent
            # Use an eligible published annotation anchor, including when the
            # original shared group was first created by a non-simple annotation.
            anchor=variants[0].entries[0].source
            result[creator]=P.ScopeAnnotationInterface(anchor,scope,creator,
                tuple(source.capture_paths.captures[scope]),tuple(variants[i] for i in (0,1,2)))
        return result

    def interface(self,creator):
        if self._interfaces is None:self._interfaces=self._collect()
        return self._interfaces.get(creator)

    def request(self,scope):
        creator=self.source.context.material.scopes[scope].parent
        result=self.interface(creator)
        _require(result is not None and result.scope==scope,scope,'scope has no original variable annotation request')
        return result

    def registration(self,reference,site):
        request=self.request(reference.scope)
        _require(reference.optimization_level in (0,1,2) and reference.index>=0
            and any(e.source==site and e.registration==reference for e in request.variants[reference.optimization_level].entries),
            reference,'registration must identify a source-bound compiler/template emission of this slot')
        return reference
