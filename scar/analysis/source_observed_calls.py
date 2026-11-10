"""Connect selected real CALL offsets to source callsites without name rules.

Compiler CALL positions alone are ambiguous for decorators. The original
ApplyDecorator slot and the source-bound LOAD_CONST for the declared child
separate decorator evaluation from application. Repeated occurrences refer
to one original operation; raw invocation evidence is not a cloned body.
"""
from collections import defaultdict
from dataclasses import dataclass
import dis
from pathlib import Path
from types import CodeType, SimpleNamespace

from scar.analysis.program_view import _digest
from scar.analysis.source_roles import SyntaxRoleView
from scar.analysis.source_reference_slice import ReferenceSlicer,source_port
from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.analysis.static_query import _Fragments
from scar.ir.program import source_productions as P, normal_targets as T
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.program.source_observed_calls import ObservedSourceCallsite,ObservedSourceCallsiteFrontier
from scar.ir.program.ids import ProviderID
from scar.ir.program.call_edges import CodeCapture
from scar.ir.program.normal_links import CodeScopeWitness
from scar.ir.program.providers import ProviderFactReference
from scar.ir.program.structured import PythonProtocolKind
from scar.ir.record_codec import decode,encode
from scar.trace.code_snapshot import describe_code,site


@dataclass(frozen=True,slots=True)
class _Caller:
    unit: str
    capture: CodeCapture
    scope: CodeScopeWitness
    code: CodeType
    link: ProviderID | None
    profiles: tuple[ProviderFactReference,...] = ()


def _span(syntax,occurrence):
    node=syntax.nodes[occurrence]
    schema=next(s for s in syntax.profile.ast_schema if s.name==node.constructor)
    attrs=dict(zip(schema.attributes,(v.scalar.to_python() if v.kind=='SCALAR' else None for v in node.attributes)))
    return tuple(attrs.get(k) for k in ('lineno','end_lineno','col_offset','end_col_offset'))


class ObservedSourceCallsiteIndex:
    def __init__(self,codes,*,compiled=()):
        self.codes=codes;self.view=codes.view;self.bindings=[];self.frontiers=[]
        self.compiled=tuple(compiled)
        self._callers={};self._syntax={};self._static={}
        self.slicer=ReferenceSlicer(SimpleNamespace(fact_store=self.view.catalog.fact_store))
        roots={}
        for row in codes.records.values():
            key=row.source,row.compile_flags
            if key not in roots:
                root=compile(Path(row.source.uri).read_bytes(),row.compiled_root.filename,'exec',
                    flags=row.compile_flags,dont_inherit=True,optimize=0)
                if describe_code(root)!=encode(row.compiled_root):raise ValueError('ordinary root replay differs from code correspondence')
                roots[key]=root
            code=roots[key]
            for offset in row.constant_path:
                code=code.co_consts[offset]
                if type(code) is not CodeType:raise ValueError('observed source code path is not a compiler child')
            for capture in row.captures:self._admit(_Caller(row.body.unit,capture,row.scope,code,row.id))
        for profile in self.compiled:
            if (profile.catalog.path,profile.catalog.report)!=(self.view.catalog.path,self.view.catalog.report):
                raise ValueError('compiled caller profile uses a different original catalog')
            for capture in codes.trace.frame_scan.captures:
                if describe_code(profile.code)==encode(capture.code):
                    facts=self.view.catalog.fact_store.load(profile.unit)
                    if profile.root_scope!=facts.root_scope:raise ValueError('compiled caller root scope differs')
                    self._admit(_Caller(profile.unit,capture,facts.root_scope,profile.code,None,
                        tuple(b.evidence for p in profile.profiles for b in p.branches)))
        targets={(t.caller.process_id,t.attempt_index):(a,t) for a,t in zip(codes.targets.target_anchors,codes.targets.targets)}
        for attempt in codes.trace.attempts:
            key=attempt.process_id,attempt.site.code
            caller=self._callers.get(key)
            if caller is None:continue
            if encode(attempt.site)!=site(caller.code,attempt.site.offset):raise ValueError('real CALL differs from original compiler instruction')
            matches=self._index(caller).get(attempt.site.offset,())
            if len(matches)!=1:
                self.frontiers.append(ObservedSourceCallsiteFrontier(caller.unit,attempt,
                    'CALLSITE_SOURCE_MAPPING_MISSING' if not matches else 'CALLSITE_SOURCE_MAPPING_AMBIGUOUS',
                    tuple(row[1] for row in matches)));continue
            query,evidence,owner,rule=matches[0];facts=self.view.catalog.fact_store.load(caller.unit);call=facts.calls[query]
            anchor,target=targets[attempt.process_id,attempt.index]
            identity=ProviderID(_digest(('scar.observed-source-callsite.v1',codes.targets.source_sha256,evidence,attempt.process_id,attempt.index)))
            self.bindings.append(ObservedSourceCallsite(identity,caller.unit,query,evidence,
                source_port(facts,call.callee),source_port(facts,call.result),owner,caller.capture,
                attempt,target,anchor,rule,caller.link,caller.profiles))
        codes.fact_materials.admit(tuple(b.call for b in self.bindings))
        self.check()

    def _admit(self,caller):
        if describe_code(caller.code)!=encode(caller.capture.code):raise ValueError('caller code descriptor differs')
        key=caller.capture.process_id,caller.capture.code.key
        old=self._callers.setdefault(key,caller)
        if old!=caller:raise ValueError('caller code has different static scope/profile alternatives')

    def _source_syntax(self,unit):
        if unit not in self._syntax:
            original=self.view.catalog.fact_store.original_source_units.get(unit,unit)
            model=self.view.catalog.fact_store.model_units[original]
            root=self.view.catalog.fact_store.model_for(original)
            self._syntax[unit]=decode(SourceSyntaxMaterial,_Fragments(root).read(model['artifacts']['source_syntax']))
        return self._syntax[unit]

    def _index(self,caller):
        cache_key=caller.unit,caller.scope.owner,caller.capture.code.key
        if cache_key in self._static:return self._static[cache_key]
        syntax=self._source_syntax(caller.unit);roles=SyntaxRoleView(syntax)
        source=self.view.unit(caller.unit);facts=source.facts
        calls=tuple((i,call,source_port(facts,call.result)) for i,call in enumerate(facts.calls))
        source._expand(tuple(dict.fromkeys(gp.port.template for _,_,gp in calls)))
        instructions=tuple(dis.get_instructions(caller.code,adaptive=False,show_caches=False))
        call_instructions=tuple(i for i in instructions if i.opname in ('CALL','CALL_KW','CALL_FUNCTION_EX'))
        rows=[];decorator_offsets=set()
        for i,call,gp in calls:
            plan=source.plans[gp.port.template];context=NamespacePlanView(caller.unit,plan);step=context.steps[gp.port.owner]
            owner=context.owner(step.region)
            if owner.owner!=caller.scope.owner:continue
            if context.result(step)!=gp or context.value(step.arguments[0])!=source_port(facts,call.callee):
                raise ValueError('observed source callsite differs from original callee/result ABI')
            ins=step.instruction;fact=self.slicer.fact(facts,'calls',i)
            if type(ins) is P.ApplyDecorator:
                _,value=roles.locate(ins.source)
                if value.kind!='NODE':raise ValueError('original decorator slot is not a source expression')
                span=_span(syntax,value.reference);definition_span=_span(syntax,ins.source.occurrence)
                markers=[x.offset for x in instructions if x.opname=='LOAD_CONST' and type(x.argval) is CodeType
                    and tuple(x.positions)==definition_span]
                candidates=[x.offset for x in call_instructions if tuple(x.positions)==span
                    and any(marker<x.offset for marker in markers)]
                if len(candidates)==1:
                    decorator_offsets.update(candidates);rows.append((i,fact,owner,'DECORATOR_AFTER_DECLARED_CODE_CONSTANT',candidates))
                continue
            explicit=(type(ins) is P.ApplyLanguageAction and ins.action is P.LanguageActionKind.CALL
                or type(ins) is P.ApplyPythonProtocol and ins.protocol is PythonProtocolKind.CALL_FUNCTION_EX)
            if not explicit:continue
            occurrence=ins.selectors[0].occurrence
            if syntax.nodes[occurrence].constructor!='Call':continue
            span=_span(syntax,occurrence)
            rows.append((i,fact,owner,'EXPLICIT_SOURCE_CALL',
                [x.offset for x in call_instructions if tuple(x.positions)==span]))
        index=defaultdict(list)
        for i,fact,owner,rule,offsets in rows:
            for offset in offsets:
                if rule=='EXPLICIT_SOURCE_CALL' and offset in decorator_offsets:continue
                index[offset].append((i,fact,owner,rule))
        self._static[cache_key]=dict(index);return self._static[cache_key]

    def check(self):
        self.codes.check()
        for profile in self.compiled:profile.check()
        for source in self.view.namespaces.values():source.check()

    def summary(self):
        return dict(bindings=len(self.bindings),frontiers=len(self.frontiers),caller_codes=len(self._callers),
            units=len({r.unit for r in self.bindings}),source_bodies_copied=False,
            target_interfaces_connected=False,creator_instances_proven=False,first_stage_complete=False)
