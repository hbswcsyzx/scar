"""Source-root schedules after external namespace admission; no target execution."""
from hashlib import sha256
from pathlib import Path
from scar.analysis.source_expression_rules import SourceExpressionRules,_REF,_BOOL,_require
from scar.analysis.source_statement_rules import SourceStatementRules,_StatementBuilder
from scar.analysis.source_root_interfaces import FIELDS,clean_docstring
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.signature_patterns import CountBinding
from scar.ir.program.structured import PythonProtocolKind as K


class SourceRootRules(SourceStatementRules):
    def catalog(self):
        catalog=SourceExpressionRules.catalog(self)
        for row in catalog['rules']:
            row['status']='LOCAL_ROOT_RULE' if row['constructor'] in FIELDS else (
                'NON_EXECUTABLE_GRAMMAR' if row['constructor']=='FunctionType' else 'OUTSIDE_DOMAIN')
            row['purposes']=[P.ProductionPurpose.ROOT.value] if row['constructor'] in FIELDS else []
        return {**catalog,'schema':'scar.source-root-rule-catalog',
            'root_implementation_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
            'scope':'ADMITTED_SOURCE_ROOT_RECIPES_ONLY',
            'entry_contract':'GLOBALS_REFERENCE,LOCALS_REFERENCE,CURRENT_WORLD;NOT_EXTERNAL_ADMISSION_PROOF',
            'child_interfaces':'STATEMENT:(WORLD)->MAY_COMPLETIONS;VALUE:(WORLD)->(REFERENCE,WORLD)'}

    def descriptor_owner(self,occurrence):return None

    def build(self,occurrence=None,purpose=P.ProductionPurpose.ROOT,*,max_steps=100_000,max_regions=100_000):
        syntax=self.source.context.syntax
        occurrence=syntax.root if occurrence is None else occurrence
        _require(type(occurrence) is int and occurrence==syntax.root,'SOURCE_REFERENCE',str(occurrence),
            'root rule requires the original F2 entry occurrence')
        _require(purpose is P.ProductionPurpose.ROOT,'PURPOSE_FRONTIER',str(occurrence),'root requires its entry interface')
        for name,value in (('max_steps',max_steps),('max_regions',max_regions)):
            _require(type(value) is int and value>=0,'QUERY_ARGUMENT',name,'expected an exact nonnegative integer')
        _require(syntax.nodes[occurrence].constructor in FIELDS,'RULE_FRONTIER',str(occurrence),
            'type grammar has no executable root')
        result=_RootBuilder(self,occurrence,purpose,max_steps,max_regions).build()
        self.source.match(result)
        return result


class _RootBuilder(_StatementBuilder):
    def store(self,region,name,value,world,*,fixed_name=False):
        kind=P.NamespaceActionKind.STORE_NAME if fixed_name else self.rules.source.roots.store_kind(name)
        namespace=self.parameter(region,1 if kind is P.NamespaceActionKind.STORE_NAME else 0)
        key,world=self.literal(region,name,world)
        world,=self.emit(region,P.ApplyNamespaceAction(kind,self.rules.exception_abi),(namespace,key,value,world),(self.world,))
        return world

    def build(self):
        source=P.ProductionOccurrence(self.occurrence);index=self.rules.source.roots
        interface=index.interface(self.world,self.rules.exception_abi)
        root=self.region(source,(_REF,_REF,self.world))
        world,=self.emit(root,P.EnterRootBody(interface),tuple(self.parameter(root,i) for i in range(3)),(self.world,),may_raise=False)
        for name in FIELDS[self.node.constructor]:self.mark(name,P.ProductionDispositionKind.METADATA)
        if self.node.constructor=='Expression':
            self.mark('body',P.ProductionDispositionKind.EVALUATED_CHILD)
            value,world=self.evaluate(root,self.site('body'),world)
            self.transfer(root,C.RETURN,(value,world),(_REF,self.world));return self.plan(root,source)
        # CPython installs the module annotate callable before user code,
        # including when user statements later raise and leave a partial module.
        if index.deferred and not index.future:
            from scar.analysis.source_evaluation_rules import build_request_body
            request=self.rules.source.scope_annotations.interface(interface.scope)
            _require(request is not None,'SOURCE_ANNOTATION',str(source),'deferred root requires its annotation group')
            body=build_request_body(self,root,request);cells=[]
            for relay in request.captures:
                cell,world=self.environment(root,P.ClosureEnvironment(relay),world,source=source);cells.append(cell)
            value,world=self.emit(root,P.BuildScopeAnnotations(interface,request,body.id),
                (self.parameter(root,0),*cells,world),(_REF,self.world))
            world=self.store(root,'__annotate__',value,world)
            world,=self.protocol(root,K.FRAME_RELEASE_TEMPORARY,(value,),world)
        if index.annotations:
            value,world=self.protocol(root,K.BUILD_SET_DISPLAY,(),world,(CountBinding('item_count',0),))
            world=self.store(root,'__conditional_annotations__',value,world,fixed_name=True)
            world,=self.protocol(root,K.FRAME_RELEASE_TEMPORARY,(value,),world)
        if index.annotations and index.future:
            world,=self.emit(root,P.ApplyNamespaceAction(P.NamespaceActionKind.ENSURE_ANNOTATIONS,self.rules.exception_abi),
                (self.parameter(root,1),world),(self.world,))
        docstring=self.rules.source.statements.declaration_docstring(self.occurrence)
        if docstring is not None:
            enabled,=self.emit(root,P.ReadCompilationOption(P.CompilationOption.DOCSTRINGS_ENABLED),(),
                (_BOOL,),may_raise=False)
            # Carry both namespace references explicitly across the option branch.
            yes=self.region(docstring,root.parameters,root);no=self.region(docstring,(self.world,),root)
            raw=self.value(docstring).scalar.to_python()
            try:cleaned=clean_docstring(raw)
            except UnicodeEncodeError as error:
                _require(False,'SOURCE_CODEGEN_CONFLICT',str(docstring),str(error))
            value,state=self.literal(yes,cleaned,self.parameter(yes,2),source=docstring)
            state=self.store(yes,'__doc__',value,state)
            state,=self.protocol(yes,K.FRAME_RELEASE_TEMPORARY,(value,),state)
            self.finish(yes,(state,),(self.world,));self.finish(no,(self.parameter(no,0),),(self.world,))
            world,=self.control(root,P.BranchControl(
                P.ProductionRegionCall(yes.id,(self.parameter(root,0),self.parameter(root,1),world)),
                P.ProductionRegionCall(no.id,(world,))), (enabled,),self.union(self.completions(yes),self.completions(no)))
            self.slots[docstring]=P.ProductionDispositionKind.METADATA
        self.mark('body',P.ProductionDispositionKind.EVALUATED_CHILD)
        body=self.region(self.site('body'),(self.world,),root)
        self.suite(body,'body',self.parameter(body,0),metadata_prefix=int(docstring is not None))
        result=self.control(root,P.ApplyRegion(P.ProductionRegionCall(body.id,(world,))),(),self.completions(body))
        if result:
            value,world=self.literal(root,None,result[0])
            self.transfer(root,C.RETURN,(value,world),(_REF,self.world))
        return self.plan(root,source)
