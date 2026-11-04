"""Pattern captures and native arities derived from original F2/F3 references."""
from dataclasses import dataclass
from scar.ir.program import source_productions as P


FIELDS={'MatchValue':('value',),'MatchSingleton':('value',),'MatchSequence':('patterns',),
    'MatchMapping':('keys','patterns','rest'),'MatchClass':('cls','patterns','kwd_attrs','kwd_patterns'),
    'MatchStar':('name',),'MatchAs':('pattern','name'),'MatchOr':('patterns',)}


def _require(condition,path,detail):
    if not condition:
        from scar.analysis.source_productions import ProductionError
        raise ProductionError('PATTERN_INTERFACE',str(path),detail)


@dataclass(frozen=True,slots=True)
class Capture:
    source: P.SlotRef
    port: int
    name: str


class PatternInterfaceIndex:
    def __init__(self,source):
        self.source=source;self.roles=source.roles;self.nodes=source.context.syntax.nodes
        self._captures={};self._irrefutable={}
        self.ports={p.site:i for i,p in enumerate(source.frontend.roles.ports) if p.role in (
            'PATTERN_MAPPING_BINDING_SYNTAX','PATTERN_STAR_BINDING_SYNTAX','PATTERN_AS_BINDING_SYNTAX')}
        for kind,fields in FIELDS.items():
            _require(tuple(self.roles.fields[kind])==fields,kind,'pattern field grammar differs')

    def site(self,owner,name,item=None):
        return P.SlotRef(owner,'FIELD',self.roles.fields[self.nodes[owner].constructor][name],() if item is None else (item,))

    def items(self,owner,name):
        value=self.roles.field(owner,name)
        _require(value.kind=='LIST' and all(v.kind=='NODE' for v in value.items),owner,'pattern field requires original child nodes')
        return tuple(v.reference for v in value.items)

    def children(self,owner):
        kind=self.nodes[owner].constructor
        if kind in ('MatchSequence','MatchMapping','MatchOr'):return self.items(owner,'patterns')
        if kind=='MatchClass':return (*self.items(owner,'patterns'),*self.items(owner,'kwd_patterns'))
        if kind=='MatchAs':
            value=self.roles.field(owner,'pattern')
            return (value.reference,) if value.kind=='NODE' else ()
        return ()

    def capture(self,owner,name):
        site=self.site(owner,name);value=self.roles.locate(site)[1]
        _require(value.kind=='SCALAR',site,'capture name must be an optional scalar')
        raw=value.scalar.to_python()
        if raw is None:return None
        port=self.ports.get(site)
        _require(type(raw) is str and port is not None and self.source.frontend.bindings.ports[port].write_target is not None,
            site,'capture requires its original namespace write port')
        return Capture(site,port,raw)

    def wildcard(self,owner):
        return self.nodes[owner].constructor=='MatchAs' and not self.children(owner) and self.capture(owner,'name') is None

    def sequence(self,owner):
        children=self.items(owner,'patterns');stars=[i for i,c in enumerate(children) if self.nodes[c].constructor=='MatchStar']
        _require(len(stars)<=1,owner,'multiple starred sequence patterns')
        star=stars[0] if stars else None
        wildcard_star=star is not None and self.capture(children[star],'name') is None
        only=all(self.wildcard(c) or i==star and wildcard_star for i,c in enumerate(children))
        return children,star,wildcard_star,only

    def literal(self,owner):
        kind=self.nodes[owner].constructor
        if kind=='Constant':return self.roles.field(owner,'value').scalar.to_python()
        if kind=='UnaryOp':
            op=self.roles.field(owner,'op').reference
            value=self.literal(self.roles.field(owner,'operand').reference)
            _require(self.nodes[op].constructor=='USub' and type(value) in (int,float,complex),owner,'pattern unary literal must be numeric minus')
            return -value
        if kind=='BinOp':
            op=self.nodes[self.roles.field(owner,'op').reference].constructor
            left=self.literal(self.roles.field(owner,'left').reference);right=self.literal(self.roles.field(owner,'right').reference)
            _require(op in ('Add','Sub') and type(left) in (int,float) and type(right) is complex,
                owner,'pattern binary literal must be a real plus/minus imaginary literal')
            return left+right if op=='Add' else left-right
        _require(False,owner,'pattern values/keys require literals or attribute lookups')

    def captures(self,owner):
        pending=[(owner,False)]
        while pending:
            current,ready=pending.pop()
            if current in self._captures:continue
            kind=self.nodes[current].constructor
            _require(kind in FIELDS,current,'expected an original pattern node')
            children=self.children(current)
            if not ready:
                pending.append((current,True));pending.extend((c,False) for c in reversed(children));continue
            irrefutable=False
            if kind=='MatchOr':
                _require(len(children)>1,current,'or pattern requires at least two alternatives')
                captures=self._captures[children[0]];control={c.name:c for c in captures}
                for child in children[1:]:
                    alternative={c.name:c for c in self._captures[child]}
                    _require(control.keys()==alternative.keys(),current,'alternative patterns bind different names')
                    _require(all(self.source.frontend.bindings.ports[c.port].write_target==self.source.frontend.bindings.ports[alternative[name].port].write_target
                        for name,c in control.items()),current,'alternative captures resolve to different namespace targets')
                _require(not any(self._irrefutable[c] for c in children[:-1]),current,'irrefutable alternative must be last')
                irrefutable=self._irrefutable[children[-1]]
            else:
                captures=tuple(capture for child in children for capture in self._captures[child])
                if kind in ('MatchAs','MatchStar','MatchMapping'):
                    capture=self.capture(current,'rest' if kind=='MatchMapping' else 'name')
                    if capture is not None:captures=(*captures,capture)
                if kind=='MatchAs':irrefutable=not children or self._irrefutable[children[0]]
            _require(len({c.name for c in captures})==len(captures),current,'multiple assignments to the same name in a pattern')
            if kind=='MatchSequence':self.sequence(current)
            elif kind=='MatchStar':
                parent=self.roles.parents.get(current)
                _require(parent is not None and self.nodes[parent.occurrence].constructor=='MatchSequence',current,'star pattern requires a sequence parent')
            elif kind=='MatchSingleton':
                value=self.roles.field(current,'value').scalar.to_python()
                _require(value is None or type(value) is bool,current,'singleton must be None/True/False')
            elif kind=='MatchValue':
                value=self.roles.field(current,'value').reference
                if self.nodes[value].constructor!='Attribute':self.literal(value)
            elif kind=='MatchMapping':
                keys=self.items(current,'keys');_require(len(keys)==len(children),current,'mapping key/pattern lengths differ')
                seen=set()
                for key in keys:
                    if self.nodes[key].constructor=='Attribute':continue
                    value=self.literal(key)
                    _require(value not in seen,current,'duplicate literal mapping key');seen.add(value)
            elif kind=='MatchClass':
                attrs=self.roles.field(current,'kwd_attrs')
                _require(attrs.kind=='LIST' and len(attrs.items)==len(self.items(current,'kwd_patterns')),current,'class keyword lengths differ')
                names=tuple(v.scalar.to_python() for v in attrs.items)
                _require(all(type(n) is str for n in names) and len(set(names))==len(names),current,'repeated or invalid class keyword labels')
            self._captures[current]=captures;self._irrefutable[current]=irrefutable
        return self._captures[owner]

    def irrefutable(self,owner):
        self.captures(owner);return self._irrefutable[owner]

    def action(self,kind,source,abi):
        owner=source.occurrence;constructor=self.nodes[owner].constructor;K=P.PatternActionKind
        allowed={K.SEQUENCE_TEST:('MatchSequence',),K.MAPPING_TEST:('MatchMapping',),K.LENGTH_TEST:('MatchSequence','MatchMapping'),
            K.EQUAL:('MatchValue',),K.SEQUENCE_UNPACK:('MatchSequence',),K.CLASS_EXTRACT:('MatchClass',),
            K.KEYS_EXTRACT:('MatchMapping',),K.TUPLE_UNPACK:('MatchMapping','MatchClass')}
        if kind is K.SEQUENCE_ITEM:
            _require(type(source) is P.SlotRef and source.group=='FIELD' and len(source.item_path)==1
                and constructor=='MatchSequence' and self.roles.locate(source)[0].name=='patterns',source,'item extraction requires its original sequence item')
            children,star,wild,only=self.sequence(owner)
            _require(wild and not only and source.item_path[0]!=star and not self.wildcard(children[source.item_path[0]]),source,'item extraction requires the wildcard-star subscript path')
            count=1
        else:
            _require(type(source) is P.ProductionOccurrence and constructor in allowed.get(kind,()),source,'pattern operation has a different original constructor')
            self.captures(owner)
            count=0 if kind in (K.SEQUENCE_TEST,K.MAPPING_TEST,K.LENGTH_TEST) else 1
            if kind is K.SEQUENCE_UNPACK:
                children,star,wild,only=self.sequence(owner)
                _require(not wild and not only,source,'unpack requires a non-wildcard extraction path')
                _require(star is None or star<256 and len(children)-star-1<(((1<<31)-1)>>8),source,'star-unpack exceeds compiler operand limits')
                count=len(children)
            elif kind is K.TUPLE_UNPACK:count=len(self.children(owner))
            elif kind is K.LENGTH_TEST:
                _require(bool(self.items(owner,'keys')) if constructor=='MatchMapping' else (
                    self.sequence(owner)[1] is None or len(self.children(owner))>1),source,'compiler skips this length test')
        return P.ApplyPatternAction(kind,source,count,abi)
