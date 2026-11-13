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
from scar.analysis.source_observed_codes import replay_catalog_code
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
        self.compiled=tuple(compiled) or tuple(getattr(codes,'compiled',()))
        profiles={p.unit:p for p in self.compiled}
        replay_profiles=getattr(self.view.catalog,'replay_profiles',{})
        observed_compiled_units=frozenset(getattr(self.view.catalog.fact_store,'observed_compiled_units',()))
        self._callers={};self._syntax={};self._static={};self._owners={}
        self._calls={};self._plans={};self._contexts={}
        self.slicer=ReferenceSlicer(SimpleNamespace(fact_store=self.view.catalog.fact_store))
        roots={}
        if not hasattr(codes,'scope_records'):
            for unit,capture,scope,code in getattr(codes,'root_callers',()):
                self._admit(_Caller(unit,capture,scope,code,None))
        for row in (*codes.records.values(),*getattr(codes,'scope_records',{}).values()):
            profile=profiles.get(row.body.unit)
            compatible=replay_profiles.get(row.body.unit)
            if row.body.unit in observed_compiled_units and compatible is None:
                raise ValueError('observed compiled child caller requires a compatible replay profile')
            if row.body.unit in self.view.catalog.fact_store.original_source_units and profile is None and compatible is None:
                raise ValueError('compiled child caller requires its original compiler profile')
            key=row.source,row.compile_flags,row.body.unit
            if key not in roots:
                if profile is None and compatible is not None:
                    root,_,flags=replay_catalog_code(Path(row.source.uri).read_bytes(),compatible)
                    if row.compile_flags!=flags:
                        raise ValueError('observed compiled caller lost its compatible replay flags')
                elif profile is None:
                    root=compile(Path(row.source.uri).read_bytes(),row.compiled_root.filename,'exec',
                        flags=row.compile_flags,dont_inherit=True,optimize=0)
                else:
                    if (profile.catalog.path,profile.catalog.report)!=(self.view.catalog.path,self.view.catalog.report):
                        raise ValueError('compiled child caller uses a different original catalog')
                    profile.check()
                    if row.compile_flags!=profile.context.compiler_input_flags:
                        raise ValueError('compiled child caller lost its original compiler inputs')
                    root=profile.code
                if describe_code(root)!=encode(row.compiled_root):raise ValueError('original root replay differs from code correspondence')
                roots[key]=root
            code=roots[key]
            for offset in row.constant_path:
                code=code.co_consts[offset]
                if type(code) is not CodeType:raise ValueError('observed source code path is not a compiler child')
            branches=() if profile is None else tuple(b.evidence for p in profile.profiles for b in p.branches)
            for capture in row.captures:self._admit(_Caller(row.body.unit,capture,row.scope,code,row.id,branches))
        for profile in self.compiled:
            if (profile.catalog.path,profile.catalog.report)!=(self.view.catalog.path,self.view.catalog.report):
                raise ValueError('compiled caller profile uses a different original catalog')
            if hasattr(codes,'scope_records'):continue
            for capture in codes.trace.frame_scan.captures:
                if describe_code(profile.code)==encode(capture.code):
                    facts=self.view.catalog.fact_store.load(profile.unit)
                    if profile.root_scope!=facts.root_scope:raise ValueError('compiled caller root scope differs')
                    self._admit(_Caller(profile.unit,capture,facts.root_scope,profile.code,None,
                        tuple(b.evidence for p in profile.profiles for b in p.branches)))
        # Raw CALL evidence first selects real caller scopes. Fetch each unit's
        # relevant original recipes in one batch; do not normalize CommonCore
        # nodes/edges merely to match an instruction to its sealed source ABI.
        scopes=defaultdict(set)
        for attempt in codes.trace.attempts:
            for caller in self._callers.get((attempt.process_id,attempt.site.code),()):
                scopes[caller.unit].add(caller.scope.owner)
        from scar.analysis.source_declared_calls import _owners
        for unit,wanted in scopes.items():
            source=self.view.unit(unit);facts=source.facts
            owners=_owners(facts);self._owners[unit]=owners
            calls=tuple((i,call,source_port(facts,call.result)) for i,call in enumerate(facts.calls)
                if wanted.intersection(owners[i]))
            self._calls[unit]=calls
            keys=tuple(dict.fromkeys(gp.port.template for _,_,gp in calls))
            plans=source.material.plans(keys);self._plans[unit]=plans
            self._contexts[unit]={key:NamespacePlanView(unit,plan) for key,plan in plans.items()}
        targets={(t.caller.process_id,t.attempt_index):(a,t) for a,t in zip(codes.targets.target_anchors,codes.targets.targets)}
        for attempt in codes.trace.attempts:
            key=attempt.process_id,attempt.site.code
            for caller in self._callers.get(key,()):
                if encode(attempt.site)!=site(caller.code,attempt.site.offset):raise ValueError('real CALL differs from original compiler instruction')
                matches=self._index(caller).get(attempt.site.offset,())
                if len(matches)!=1:
                    self.frontiers.append(ObservedSourceCallsiteFrontier(caller.unit,attempt,
                        'CALLSITE_SOURCE_MAPPING_MISSING' if not matches else 'CALLSITE_SOURCE_MAPPING_AMBIGUOUS',
                        tuple(row[1] for row in matches)));continue
                query,evidence,owner,rule=matches[0];facts=self.view.catalog.fact_store.load(caller.unit);call=facts.calls[query]
                anchor,target=targets[attempt.process_id,attempt.index]
                identity=ProviderID(_digest(('scar.observed-source-callsite.v1',codes.targets.source_sha256,
                    evidence,attempt.process_id,attempt.index,caller.unit,caller.scope,caller.link,caller.profiles)))
                self.bindings.append(ObservedSourceCallsite(identity,caller.unit,query,evidence,
                    source_port(facts,call.callee),source_port(facts,call.result),owner,caller.capture,
                    attempt,target,anchor,rule,caller.link,caller.profiles))
        codes.fact_materials.admit(tuple(b.call for b in self.bindings))
        self.check()

    def _admit(self,caller):
        if describe_code(caller.code)!=encode(caller.capture.code):raise ValueError('caller code descriptor differs')
        key=caller.capture.process_id,caller.capture.code.key
        alternatives=self._callers.setdefault(key,[])
        if caller not in alternatives:alternatives.append(caller)

    def caller_for(self,observation):
        """Recover one relation's declared caller without choosing its world.

        Different source units/scopes may share a code descriptor. Each remains
        a separate correspondence alternative, including at downstream joins.
        """
        candidates=tuple(c for c in self._callers.get((observation.attempt.process_id,observation.attempt.site.code),())
            if c.unit==observation.unit and c.scope.owner==observation.owner.owner and c.link==observation.code_link
            and c.capture==observation.caller and c.profiles==observation.profile_alternatives)
        if len(candidates)!=1:raise ValueError('callsite relation has no unique declared caller alternative')
        return candidates[0]

    def _source_syntax(self,unit):
        if unit not in self._syntax:
            original=(unit if unit in getattr(self.view.catalog.fact_store,'observed_compiled_units',())
                else self.view.catalog.fact_store.original_source_units.get(unit,unit))
            model=self.view.catalog.fact_store.model_units[original]
            root=self.view.catalog.fact_store.model_for(original)
            self._syntax[unit]=decode(SourceSyntaxMaterial,_Fragments(root).read(model['artifacts']['source_syntax']))
        return self._syntax[unit]

    def _index(self,caller):
        cache_key=caller.unit,caller.scope.owner,caller.capture.code.key
        if cache_key in self._static:return self._static[cache_key]
        syntax=self._source_syntax(caller.unit);roles=SyntaxRoleView(syntax)
        source=self.view.unit(caller.unit);facts=source.facts
        owners=self._owners[caller.unit]
        # Scope-group ranges are an index. The selected bare F4 recipe still
        # independently checks exact owner and callee/result/world interfaces.
        calls=tuple(row for row in self._calls[caller.unit] if caller.scope.owner in owners[row[0]])
        instructions=tuple(dis.get_instructions(caller.code,adaptive=False,show_caches=False))
        call_instructions=tuple(i for i in instructions if i.opname in ('CALL','CALL_KW','CALL_FUNCTION_EX'))
        rows=[];decorator_offsets=set()
        for i,call,gp in calls:
            context=self._contexts[caller.unit][gp.port.template];step=context.steps[gp.port.owner]
            owner=context.owner(step.region)
            if owner.owner!=caller.scope.owner:continue
            if (context.result(step)!=gp or not step.arguments
                    or context.value(step.arguments[0])!=source_port(facts,call.callee)
                    or context.worlds(step)!=(source_port(facts,call.world),source_port(facts,call.result_world))):
                raise ValueError('observed source callsite differs from original callee/result/world ABI')
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
            caller_alternatives=sum(len(rows) for rows in self._callers.values()),
            units=len({r.unit for r in self.bindings}),source_bodies_copied=False,
            target_interfaces_connected=False,creator_instances_proven=False,first_stage_complete=False)
