"""Expandable patterns with capture-bearing success and capture-free failure.

Patterns do not publish namespace bindings. A case publishes only after its
whole pattern succeeds; a false guard keeps those writes and tries the next
case with the original subject reference and the delivered current world.
"""
from scar.analysis.source_expression_rules import _REF, _BOOL, _require
from scar.analysis.source_pattern_interfaces import FIELDS
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.signature_patterns import CountBinding
from scar.ir.program.structured import PythonProtocolKind as K


FAIL=P.PatternCompletionKind.FAIL
A=P.PatternActionKind


def _action(b,region,kind,source,arguments,world):
    instruction=b.rules.source.patterns.action(kind,source,b.rules.exception_abi)
    predicate=kind in (A.SEQUENCE_TEST,A.MAPPING_TEST,A.LENGTH_TEST)
    types=(_BOOL,b.world) if predicate else (*(_REF for _ in range(instruction.reference_results)),b.world)
    return b.emit(region,instruction,(*arguments,world),types,
        may_raise=kind not in (A.SEQUENCE_TEST,A.MAPPING_TEST,A.TUPLE_UNPACK),source=source)


def _guard(b,region,source,decision,world,*,fail_on_true=False):
    yes=b.region(source,(b.world,),region);no=b.region(source,(b.world,),region)
    b.finish(yes,(b.parameter(yes,0),),(b.world,))
    b.transfer(no,FAIL,(b.parameter(no,0),),(b.world,))
    branches=(no,yes) if fail_on_true else (yes,no)
    result=b.control(region,P.BranchControl(*(P.ProductionRegionCall(r.id,(world,)) for r in branches)),
        (decision,),b.union(b.completions(yes),b.completions(no)))
    return result[0]


def _present(b,region,source,value,world):
    absent,=b.emit(region,P.ReferenceIsNone(),(value,),(_BOOL,),may_raise=False,source=source)
    return _guard(b,region,source,absent,world,fail_on_true=True)


def _fields(b,owner):
    index=b.rules.source.patterns
    for name in FIELDS[index.nodes[owner].constructor]:
        b.slots[index.site(owner,name)]=P.ProductionDispositionKind.METADATA
    for name in ('name','rest'):
        if name in FIELDS[index.nodes[owner].constructor]:
            capture=index.capture(owner,name)
            if capture is not None:b.slots[capture.source]=P.ProductionDispositionKind.ROLE_PORT


def _metadata(b,owner):
    pending=[owner]
    while pending:
        current=pending.pop();_fields(b,current);pending.extend(b.rules.source.patterns.children(current))


def _child(b,region,site,subject,world):
    index=b.rules.source.patterns;owner=b.value(site).reference
    b.slots[site]=P.ProductionDispositionKind.EVALUATED_CHILD
    child=_pattern(b,region,owner)
    result=b.control(region,P.ApplyRegion(P.ProductionRegionCall(child.id,(subject,world))),(),b.completions(child))
    return result[:-1],result[-1]


def _pattern(b,parent,owner):
    index=b.rules.source.patterns;captures=index.captures(owner);kind=index.nodes[owner].constructor
    region=b.region(P.ProductionOccurrence(owner),(_REF,b.world),parent,P.ProductionRegionKind.PATTERN)
    _fields(b,owner);subject,world=b.parameter(region,0),b.parameter(region,1);values=[]
    source=P.ProductionOccurrence(owner)
    if kind in ('MatchAs','MatchStar'):
        if kind=='MatchAs' and index.children(owner):
            inner,world=_child(b,region,index.site(owner,'pattern'),subject,world);values.extend(inner)
        if index.capture(owner,'name') is not None:values.append(subject)
    elif kind=='MatchValue':
        site=index.site(owner,'value');b.slots[site]=P.ProductionDispositionKind.EVALUATED_CHILD
        expected,world=b.evaluate(region,site,world)
        compared,world=_action(b,region,A.EQUAL,source,(subject,expected),world)
        matched,world=b.protocol(region,K.TRUTH,(compared,),world)
        world,=b.protocol(region,K.FRAME_RELEASE_TEMPORARY,(compared,),world)
        world=_guard(b,region,source,matched,world)
    elif kind=='MatchSingleton':
        literal=index.roles.field(owner,'value').scalar.to_python()
        expected,world=b.literal(region,literal,world,source=index.site(owner,'value'))
        matched,=b.emit(region,P.ReferenceIdentical(),(subject,expected),(_BOOL,),may_raise=False)
        world=_guard(b,region,source,matched,world)
    elif kind=='MatchSequence':
        matched,world=_action(b,region,A.SEQUENCE_TEST,source,(subject,),world)
        world=_guard(b,region,source,matched,world)
        children,star,wild,only=index.sequence(owner)
        if star is None or len(children)>1:
            matched,world=_action(b,region,A.LENGTH_TEST,source,(subject,),world)
            world=_guard(b,region,source,matched,world)
        b.slots[index.site(owner,'patterns')]=P.ProductionDispositionKind.EVALUATED_CHILD
        extracted=()
        if not only and not wild:
            *extracted,world=_action(b,region,A.SEQUENCE_UNPACK,source,(subject,),world)
        for ordinal,child in enumerate(children):
            site=index.site(owner,'patterns',ordinal)
            if only or wild and (ordinal==star or index.wildcard(child)):
                b.slots[site]=P.ProductionDispositionKind.METADATA;_metadata(b,child);continue
            if wild:value,world=_action(b,region,A.SEQUENCE_ITEM,site,(subject,),world)
            else:value=extracted[ordinal]
            inner,world=_child(b,region,site,value,world);values.extend(inner)
    elif kind in ('MatchClass','MatchMapping'):
        if kind=='MatchClass':
            site=index.site(owner,'cls');b.slots[site]=P.ProductionDispositionKind.EVALUATED_CHILD
            cls,world=b.evaluate(region,site,world)
            unpacked,world=_action(b,region,A.CLASS_EXTRACT,source,(subject,cls),world)
            fields=('patterns','kwd_patterns')
            for ordinal in range(len(index.roles.field(owner,'kwd_attrs').items)):
                b.slots[index.site(owner,'kwd_attrs',ordinal)]=P.ProductionDispositionKind.ROLE_PORT
        else:
            matched,world=_action(b,region,A.MAPPING_TEST,source,(subject,),world)
            world=_guard(b,region,source,matched,world)
            keys=index.items(owner,'keys');rest=index.capture(owner,'rest')
            if not keys and rest is None:
                b.finish(region,(world,),(b.world,));return region
            if keys:
                matched,world=_action(b,region,A.LENGTH_TEST,source,(subject,),world)
                world=_guard(b,region,source,matched,world)
            b.slots[index.site(owner,'keys')]=P.ProductionDispositionKind.EVALUATED_CHILD;key_values=[]
            for ordinal in range(len(keys)):
                site=index.site(owner,'keys',ordinal);b.slots[site]=P.ProductionDispositionKind.EVALUATED_CHILD
                value,world=b.evaluate(region,site,world);key_values.append(value)
            packed,world=b.protocol(region,K.BUILD_CALL_POSITIONALS,tuple(key_values),world,
                (CountBinding('item_count',len(keys)),),selectors=(index.site(owner,'keys'),))
            unpacked,world=_action(b,region,A.KEYS_EXTRACT,source,(subject,packed),world)
            fields=('patterns',)
        world=_present(b,region,source,unpacked,world)
        *attributes,world=_action(b,region,A.TUPLE_UNPACK,source,(unpacked,),world)
        ordinal=0
        for name in fields:
            b.slots[index.site(owner,name)]=P.ProductionDispositionKind.EVALUATED_CHILD
            for item in range(len(index.items(owner,name))):
                inner,world=_child(b,region,index.site(owner,name,item),attributes[ordinal],world)
                values.extend(inner);ordinal+=1
        if kind=='MatchMapping' and rest is not None:
            copied,world=b.protocol(region,K.BUILD_MAP,(),world,(CountBinding('pair_count',0),),selectors=(rest.source,))
            world,=b.protocol(region,K.DICT_UPDATE,(copied,subject),world,selectors=(rest.source,))
            for ordinal,key in enumerate(key_values):
                world,=b.action(region,P.LanguageActionKind.ITEM_DELETE,(index.site(owner,'keys',ordinal),),(copied,key,world),(b.world,))
            values.append(copied)
    elif kind=='MatchOr':
        _or_pattern(b,region,owner);return region
    _require(len(values)==len(captures),'RULE_INTERFACE',str(owner),'pattern results differ from original capture interface')
    b.finish(region,(*values,world),(*(_REF for _ in captures),b.world))
    return region


def _or_pattern(b,region,owner):
    index=b.rules.source.patterns;alternatives=index.children(owner);control=index.captures(owner)
    b.slots[index.site(owner,'patterns')]=P.ProductionDispositionKind.EVALUATED_CHILD
    blocks=[b.region(index.site(owner,'patterns',i),(_REF,b.world),region,P.ProductionRegionKind.SHARED) for i in range(len(alternatives))]
    for ordinal in reversed(range(len(blocks))):
        block=blocks[ordinal];subject,world=b.parameter(block,0),b.parameter(block,1)
        child=_pattern(b,block,alternatives[ordinal]);child_captures=index.captures(alternatives[ordinal])
        routes=[];outputs=[]
        for completion in b.completions(child):
            if completion.kind is C.RAISE:outputs.append(completion);continue
            failed=completion.kind is FAIL
            has_next=failed and ordinal+1<len(blocks)
            handler=b.region(child.source,(*completion.types,*((_REF,) if has_next else ())),block,P.ProductionRegionKind.HANDLER)
            state=b.parameter(handler,len(completion.types)-1)
            if not failed:
                positions={capture.name:i for i,capture in enumerate(child_captures)}
                b.finish(handler,(*(b.parameter(handler,positions[capture.name]) for capture in control),state),(*(_REF for _ in control),b.world))
            elif has_next:
                next_block=blocks[ordinal+1]
                result=b.control(handler,P.ApplyRegion(P.ProductionRegionCall(next_block.id,(b.parameter(handler,len(completion.types)),state))),(),b.completions(next_block))
                if result:b.finish(handler,result,(*(_REF for _ in control),b.world))
            else:b.transfer(handler,FAIL,(state,),(b.world,))
            routes.append(P.CompletionRoute(completion.kind,completion.target,handler.id,(subject,) if has_next else ()))
            outputs.extend(b.completions(handler))
        result=b.control(block,P.HandleCompletions(P.ProductionRegionCall(child.id,(subject,world)),tuple(routes)),(),b.union(tuple(outputs)))
        if result:b.finish(block,result,(*(_REF for _ in control),b.world))
    result=b.control(region,P.ApplyRegion(P.ProductionRegionCall(blocks[0].id,(b.parameter(region,0),b.parameter(region,1)))),(),b.completions(blocks[0]))
    if result:b.finish(region,result,(*(_REF for _ in control),b.world))


def _next_case(b,region,following,subject,world):
    if following is None:b.finish(region,(world,),(b.world,));return
    result=b.control(region,P.ApplyRegion(P.ProductionRegionCall(following.id,(subject,world))),(),b.completions(following))
    if result:b.finish(region,result,(b.world,))


def emit_match_statement(b,root,world):
    index=b.rules.source.patterns;cases=b.rules.source.statements.node_items(b.occurrence,'cases')
    _require(bool(cases),'RULE_SHAPE',str(b.occurrence),'match requires cases')
    b.mark('subject',P.ProductionDispositionKind.EVALUATED_CHILD)
    subject,world=b.evaluate(root,b.site('subject'),world)
    b.mark('cases',P.ProductionDispositionKind.EVALUATED_CHILD)
    blocks=[b.region(b.site('cases',i),(_REF,b.world),root,P.ProductionRegionKind.SHARED) for i in range(len(cases))]
    for ordinal in reversed(range(len(cases))):
        case=cases[ordinal];block=blocks[ordinal];following=blocks[ordinal+1] if ordinal+1<len(cases) else None
        b.slots[b.site('cases',ordinal)]=P.ProductionDispositionKind.EVALUATED_CHILD
        pattern=b.auxiliary(case,'pattern',P.ProductionDispositionKind.EVALUATED_CHILD)
        guard=b.auxiliary(case,'guard',P.ProductionDispositionKind.METADATA)
        body=b.auxiliary(case,'body',P.ProductionDispositionKind.EVALUATED_CHILD)
        owner=b.value(pattern).reference;captures=index.captures(owner);guarded=b.value(guard).kind=='NODE'
        _require(not index.irrefutable(owner) or guarded or following is None,'SOURCE_CODEGEN_CONFLICT',str(owner),'unguarded irrefutable case must be last')
        matcher=_pattern(b,block,owner);routes=[];outputs=[]
        for completion in b.completions(matcher):
            if completion.kind is C.RAISE:outputs.append(completion);continue
            failed=completion.kind is FAIL
            needs_subject=following is not None and (failed or guarded)
            handler=b.region(pattern,(*completion.types,*((_REF,) if needs_subject else ())),block,P.ProductionRegionKind.HANDLER)
            current=b.parameter(handler,len(completion.types)-1)
            retained=b.parameter(handler,len(completion.types)) if needs_subject else None
            if failed:_next_case(b,handler,following,retained,current)
            else:
                for position,capture in enumerate(captures):
                    current,=b.emit(handler,P.AccessBinding(P.BindingActionKind.WRITE,capture.port),
                        (b.parameter(handler,position),current),(b.world,),source=capture.source)
                if guarded:
                    b.slots[guard]=P.ProductionDispositionKind.EVALUATED_CHILD
                    decision,current=b.condition(handler,guard,current)
                    accepted=b.region(body,(b.world,),handler);b.suite_at(accepted,body,b.parameter(accepted,0))
                    rejected=b.region(guard,(_REF,b.world) if needs_subject else (b.world,),handler)
                    _next_case(b,rejected,following,b.parameter(rejected,0) if needs_subject else None,
                        b.parameter(rejected,1 if needs_subject else 0))
                    result=b.control(handler,P.BranchControl(P.ProductionRegionCall(accepted.id,(current,)),
                        P.ProductionRegionCall(rejected.id,(retained,current) if needs_subject else (current,))),
                        (decision,),b.union(b.completions(accepted),b.completions(rejected)))
                    if result:b.finish(handler,result,(b.world,))
                else:b.suite_at(handler,body,current)
            routes.append(P.CompletionRoute(completion.kind,completion.target,handler.id,(b.parameter(block,0),) if needs_subject else ()))
            outputs.extend(b.completions(handler))
        result=b.control(block,P.HandleCompletions(P.ProductionRegionCall(matcher.id,(b.parameter(block,0),b.parameter(block,1))),tuple(routes)),(),b.union(tuple(outputs)))
        if result:b.finish(block,result,(b.world,))
    result=b.control(root,P.ApplyRegion(P.ProductionRegionCall(blocks[0].id,(subject,world))),(),b.completions(blocks[0]))
    if result:b.finish(root,result,(b.world,))
