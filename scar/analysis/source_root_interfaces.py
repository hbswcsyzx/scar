"""Admitted program roots and implicit namespace decisions from original facts."""
from scar.ir.program import source_productions as P
from scar.ir.program.protocol_signatures import ExceptionABI


FIELDS={'Module':('body','type_ignores'),'Interactive':('body',),'Expression':('body',)}


def _require(condition,path,detail):
    if not condition:
        from scar.analysis.source_productions import ProductionError
        raise ProductionError('ROOT_INTERFACE',str(path),detail)


def clean_docstring(value):
    """Pinned _PyCompile_CleanDoc, retaining blank lines and ASCII-space rules."""
    value=value.expandtabs()
    value.encode('utf-8')  # the compiler requires a valid UTF-8 representation
    lines=value.split('\n')
    nonblank=[len(line)-len(line.lstrip(' ')) for line in lines[1:] if line.lstrip(' ')]
    margin=min(nonblank,default=0)
    return '\n'.join((lines[0].lstrip(' '),*(line[min(margin,len(line)-len(line.lstrip(' '))):] for line in lines[1:])))


class RootInterfaceIndex:
    def __init__(self,source):
        self.source=source;self.syntax=source.context.syntax;self.root=self.syntax.root
        self.scope=source.context.material.root_context.environment
        self.kind=self.syntax.nodes[self.root].constructor
        self.annotations=tuple(i for i,node in enumerate(self.syntax.nodes) if node.constructor=='AnnAssign'
            and source.context.entry_context(i).environment==self.scope)
        self.publications=tuple(p for i in self.annotations if (p:=source.statements.annotation_publication(
            i,ExceptionABI.EXCEPTION_WORLD)) is not None)
        self.deferred=any(p.publication is P.AnnotationPublicationKind.DEFERRED for p in self.publications)
        self.future=False
        if self.kind in ('Module','Interactive'):
            for ordinal,value in enumerate(source.roles.field(self.root,'body').items):
                owner=value.reference
                if ordinal==0 and self.syntax.nodes[owner].constructor=='Expr':
                    child=source.roles.field(owner,'value').reference
                    if self.syntax.nodes[child].constructor=='Constant' and type(source.roles.field(child,'value').scalar.to_python()) is str:continue
                if self.syntax.nodes[owner].constructor!='ImportFrom':break
                module=source.roles.field(owner,'module').scalar.to_python()
                if module!='__future__' or source.roles.field(owner,'level').scalar.to_python()!=0:break
                self.future |= any(source.roles.field(v.reference,'name').scalar.to_python()=='annotations'
                    for v in source.roles.field(owner,'names').items)
        for kind,fields in FIELDS.items():
            _require(tuple(source.roles.fields[kind])==fields,kind,'original root field grammar differs')

    def interface(self,world,abi):
        _require(self.kind in FIELDS and self.syntax.mode=={'Module':'exec','Interactive':'single','Expression':'eval'}[self.kind],
            self.root,'root constructor and original parser mode differ')
        _require(self.source.context.material.scopes[self.scope].kind=={
            'Module':'ROOT_EXEC','Interactive':'ROOT_INTERACTIVE','Expression':'ROOT_EVAL'}[self.kind],
            self.root,'root requires its original external namespace scope')
        return P.RootBodyInterface(P.ProductionOccurrence(self.root),self.scope,world,abi)

    def store_kind(self,name):
        """Implicit codegen_nameop honors an explicit root global directive."""
        declarations=self.source.frontend.declarations;bindings=self.source.frontend.bindings
        explicit=any(row.scope==self.scope and row.classification=='GLOBAL_EXPLICIT' and row.name.kind=='SOURCE'
            and declarations.names[row.name.index].value==name for row in bindings.resolutions)
        return P.NamespaceActionKind.STORE_GLOBAL if explicit else P.NamespaceActionKind.STORE_NAME

    def interactive_expression(self,occurrence):
        context=self.source.context.entry_context(occurrence)
        return self.kind=='Interactive' and context.owner.kind=='ROOT' and context.environment==self.scope
