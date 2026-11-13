"""Match real code observations to shared F4 definitions using compiler paths.

Reuse the established parent LOAD_CONST/span mapper and full code fingerprint.
This is a code-template correspondence, not a guessed function-name binding,
callsite selection, creator-instance identity or a static invocation frame.
"""
import argparse
import ast
import dis
from dataclasses import replace
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import CodeType

from scar.analysis.call_operand_reader import read_call_operands
from scar.analysis.python_call_targets import read_python_call_targets
from scar.analysis.static_compilation import _scope_nodes
from scar.analysis.static_query import _Fragments
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.source_value_flow import _artifact
from scar.analysis.program_view import ProgramView, _digest
from scar.analysis.source_observed_materials import ObservedFactMaterials
from scar.analysis.source_consumer_parents import _stamp
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_mkdir, _durable_bytes
from scar.analysis.source_template_links import _json
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.program.compiler_topology import CompilerTopologyMaterial
from scar.ir.program.source_observed_codes import (ObservedSourceCodeLink,
    ObservedSourceScopeKind as ScopeKind, ObservedSourceScopeLink)
from scar.ir.program import normal_targets as T, view as V
from scar.ir.program.call_edges import CapturedCode,CallEdgeBudget
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.ids import ProviderID
from scar.ir.program.dependencies import (
    DependencyPoint as Point, DependencyEdge as Edge, DependencyKind as K,
    DependencyMeaning as Meaning, DependencyStrength as Strength,
    DependencyCondition as Condition, DependencyEvidence as Evidence,
    DependencyNeighborhood as Neighborhood)
from scar.ir.record_codec import decode, encode
from scar.trace.code_snapshot import describe_code
from scar.trace.files import open_binary, resolve as resolve_trace_file


SCHEMA = 'scar.source-observed-code-view'
_EXPRESSION_BODIES = {'Lambda': ('LAMBDA_BODY', '<lambda>'),
    'GeneratorExp': ('GENERATOR_EXPRESSION', '<genexpr>')}


def replay_catalog_code(raw, profile):
    """Compile retained bytes under a compatible recipe; never execute them.

    The full root descriptor authenticates this representation. It does not
    establish the original compile request or the resulting callable's world.
    """
    if type(profile) is not dict or set(profile) != {'recipe', 'root_code'}:
        raise ValueError('compatible replay needs its explicit recipe and root code descriptor')
    recipe = profile['recipe']
    if (type(recipe) is not dict
            or set(recipe) != {'filename', 'mode', 'flags', 'dont_inherit', 'optimize'}
            or type(recipe['filename']) is not str or recipe['mode'] not in ('exec', 'eval', 'single')
            or type(recipe['flags']) is not int or recipe['flags'] < 0
            or recipe['dont_inherit'] is not True or type(recipe['optimize']) is not int
            or recipe['optimize'] not in (0, 1, 2)):
        raise ValueError('explicit compatible replay recipe required')
    code = compile(raw, recipe['filename'], recipe['mode'], flags=recipe['flags'],
        dont_inherit=True, optimize=recipe['optimize'])
    if describe_code(code) != profile['root_code']:
        raise ValueError('compatible replay root differs from the retained full code descriptor')
    tree = compile(raw, recipe['filename'], recipe['mode'], flags=recipe['flags'] | ast.PyCF_ONLY_AST,
        dont_inherit=True, optimize=0)
    return code, tree, recipe['flags']


def _expression_code_paths(root):
    """Index exact compiler child slots/positions, not names or first lines.

    F3's public expression-body projection admits a source occurrence
    separately. LOAD_CONST supplies its exact code path; the full captured
    descriptor is still checked by source-code correspondence below. A
    generator expression body is not a creation or resume-instance witness.
    """
    found = defaultdict(list); pending = [((), root)]; visited = set()
    while pending:
        path, code = pending.pop()
        if path in visited: continue
        visited.add(path)
        for instruction in dis.get_instructions(code, adaptive=False, show_caches=False):
            child = instruction.argval
            if instruction.opname != 'LOAD_CONST' or type(child) is not CodeType: continue
            if type(instruction.arg) is not int or code.co_consts[instruction.arg] is not child:
                raise ValueError('source expression compiler child lost its exact constant slot')
            child_path = (*path, instruction.arg)
            pending.append((child_path, child))
            span = tuple(instruction.positions)
            if child.co_name in ('<lambda>', '<genexpr>') and all(type(value) is int for value in span):
                item = child_path, child, None
                key = child.co_name, span
                if item not in found[key]: found[key].append(item)
    return found


class ObservedSourceCodeProvider:
    relation_kinds = frozenset((K.IMPLEMENTATION,))

    def __init__(self, view, trace, project_root, *, units=(), compiled=(),
                 target_max_bytes=32_000_000, target_max_rows=100_000,frame_budget=CallEdgeBudget()):
        self.view = view
        self.replay_profiles = dict(getattr(view.catalog, 'replay_profiles', {}))
        self._replay_profile_bytes = _json(self.replay_profiles)
        self.observed_compiled_units = frozenset(getattr(view.catalog.fact_store, 'observed_compiled_units', ()))
        if not self.replay_profiles.keys() <= self.observed_compiled_units:
            raise ValueError('compatible replay profiles must name observed compiled units')
        self.compiled = tuple(compiled)
        self._compiled = {}
        for profile in self.compiled:
            if (profile.catalog.path, profile.catalog.report) != (view.catalog.path, view.catalog.report):
                raise ValueError('compiled code correspondence uses a different original catalog')
            if profile.unit in self._compiled:
                raise ValueError('one compiled source unit needs one authenticated compiler profile')
            profile.check(); self._compiled[profile.unit] = profile
        self.trace = read_call_operands(trace, project_root,frame_budget=frame_budget)
        self.target_reader_budget = dict(target_max_bytes=target_max_bytes,target_max_rows=target_max_rows)
        self.targets = read_python_call_targets(self.trace,max_bytes=target_max_bytes,max_rows=target_max_rows)
        if any(m['python'] != sys.version for m in self.trace.frame_scan.metadata):
            raise ValueError('code correspondence needs the recorded compiler runtime')
        self.records = {}; self.scope_records = {}; self.points = {}; self.bodies = {}; self.issues = [];self.root_callers=[]
        self.fact_materials=ObservedFactMaterials(view.catalog)
        self._sources = {}; self._guard = {}; self._trace_guard = {}
        self._target_metas = tuple(sorted(Path(self.trace.directory).glob('python-call-target-meta.*.json')))
        digests=[]
        for meta in self._target_metas:
            raw=meta.read_bytes();self._guard[meta]=raw;receipt=json.loads(raw)['file']
            logical=Path(receipt['path'])
            self._admit_trace(logical,receipt['bytes'],receipt['sha256'])
            digests.append((str(meta),sha256(raw).hexdigest(),str(logical),receipt['sha256']))
        if sha256(json.dumps(digests,sort_keys=True).encode()).hexdigest() != self.targets.source_sha256:
            raise ValueError('observed target receipts differ from their original reader')
        for receipt in (*self.trace.files,*self.trace.frame_scan.files):
            self._admit_trace(Path(self.trace.directory)/receipt.path,receipt.raw_bytes,receipt.raw_sha256)
        captures = defaultdict(list)
        for capture in self.trace.frame_scan.captures:
            captures[capture.code.filename].append(capture)
        targets_by_code=defaultdict(list);entries_by_code=defaultdict(list)
        frame_entries=defaultdict(list)
        for entry in self.trace.entries:
            frame_entries[entry.invocation.process_id,entry.code].append(entry.anchor)
        for anchor,target in zip(self.targets.target_anchors,self.targets.targets):targets_by_code[target.code].append((anchor,target))
        for anchor,entry in zip(self.targets.entry_anchors,self.targets.entries):entries_by_code[entry.code].append((anchor,entry))
        selected = tuple(units or (u for u,r in view.catalog.fact_store.rows.items()
            if r['path'] in captures or u in self._compiled and self._compiled[u].compiled_root.filename in captures
            or u in self.replay_profiles and self.replay_profiles[u]['recipe']['filename'] in captures))
        slicer = ReferenceSlicer(type('SourceFacts', (), {'fact_store': view.catalog.fact_store})())
        for unit in selected:
            profile = self._compiled.get(unit)
            compatible = self.replay_profiles.get(unit)
            if unit in self.observed_compiled_units and compatible is None:
                self.issues.append(dict(unit=unit,reason='OBSERVED_COMPILED_SOURCE_REQUIRES_COMPATIBLE_REPLAY'));continue
            if unit in view.catalog.fact_store.original_source_units and profile is None and compatible is None:
                self.issues.append(dict(unit=unit,reason='COMPILED_CONTEXT_CODE_CORRESPONDENCE_REQUIRES_ORIGINAL_PROFILE'));continue
            original = unit if compatible is not None else view.catalog.fact_store.original_source_units.get(unit, unit)
            model = view.catalog.fact_store.model_units[original]
            path = Path(model['path'])
            filename = (profile.compiled_root.filename if profile is not None else
                compatible['recipe']['filename'] if compatible is not None else str(path))
            observed = captures.get(filename, ())
            if not observed:continue
            raw = path.read_bytes()
            if len(raw) > 1_000_000 or sha256(raw).hexdigest() != model['raw_sha256']:
                raise ValueError('observed code source differs from the original static source')
            self._guard[path] = raw
            root = view.catalog.fact_store.model_for(original)
            descriptor = model['artifacts']['source_syntax']
            syntax = decode(SourceSyntaxMaterial, _Fragments(root).read(descriptor))
            syntax_path = root/descriptor['path']; self._guard[syntax_path] = syntax_path.read_bytes()
            syntax_artifact = _artifact(syntax_path, 'scar.source-syntax')
            schemas = {s.name:s for s in syntax.profile.ast_schema}
            facts = view.catalog.fact_store.load(unit)
            # An exec child belongs to its retained effective compiler profile,
            # not to a fresh flags=0 import of the same source filename. The
            # authenticated profile replays its original payload, mode, flags,
            # dont_inherit=True and optimize; all exec branches stay separate.
            if profile is None and compatible is not None:
                code, tree, flags = replay_catalog_code(raw, compatible)
            elif profile is None:
                flags = 0
                code = compile(raw, str(path), 'exec', flags=flags, dont_inherit=True, optimize=0)
                tree = ast.parse(raw, filename=str(path))
            else:
                flags = profile.context.compiler_input_flags
                code = profile.code
                tree = ast.parse(profile.payload, filename=profile.context.filename, mode=profile.context.mode)
            mappings = {}; issues = []
            _scope_nodes(tree, code, (), ast.Module, mappings, issues)
            replay = {flags:(code,mappings)}
            expression_blocks = {}; expression_paths = {}
            if profile is None and any(syntax.nodes[f.template.occurrence].constructor in _EXPRESSION_BODIES
                    for f in facts.functions):
                descriptor = model['artifacts']['compiler_topology']
                topology = decode(CompilerTopologyMaterial, _Fragments(root).read(descriptor))
                if topology.status != 'PROJECTED':
                    raise ValueError('source expression correspondence needs its original compiler topology')
                topology_path = root/descriptor['path']; self._guard[topology_path] = topology_path.read_bytes()
                expression_blocks = {(block.origin.occurrence, block.origin.role): block for block in topology.blocks
                    if block.origin.role in ('LAMBDA_BODY', 'GENERATOR_EXPRESSION') and block.projection == 'PUBLIC'}
                expression_paths = _expression_code_paths(code)
            root_descriptor=decode(CapturedCode,describe_code(code))
            source_artifact=ProviderArtifact(str(path),sha256(raw).hexdigest(),len(raw),'python-source')
            scoped=[]
            matched_roots=tuple(capture for capture in observed if capture.code==root_descriptor)
            if profile is None:
                self.root_callers.extend((unit,capture,facts.root_scope,code) for capture in observed
                    if capture.code==root_descriptor)
            if matched_roots:
                root_fact=slicer.fact(facts,'root_scope')
                identity=ProviderID(_digest((SCHEMA+'.scope',self.targets.source_sha256,root_fact,root_descriptor)))
                scoped.append(ObservedSourceScopeLink(identity,ScopeKind.CODE_ROOT,root_fact,
                    T.Body(unit,facts.root_scope.template,facts.root_scope.region),facts.root_scope,matched_roots,
                    source_artifact,ProviderFactReference(syntax_artifact,'#/nodes/0'),root_descriptor,(),flags,
                    tuple(a for c in matched_roots for a in frame_entries[c.process_id,c.code.key])))
            for ordinal,declared in enumerate(facts.classes):
                node=syntax.nodes[declared.template.occurrence]
                if node.constructor!='ClassDef' or declared.body_scope is None:continue
                attributes=dict(zip(schemas[node.constructor].attributes,
                    (v.scalar.to_python() if v.kind=='SCALAR' else None for v in node.attributes)))
                span=tuple(attributes[k] for k in ('lineno','end_lineno','col_offset','end_col_offset'))
                for constant_path,child,_ in mappings.get(span,()):
                    expected=decode(CapturedCode,describe_code(child))
                    matched=tuple(c for c in observed if c.code==expected)
                    if not matched:continue
                    if declared.body_scope.source_scope!=declared.scope:
                        raise ValueError('class source/code-scope correspondence differs from its original fact')
                    definition=slicer.fact(facts,'classes',ordinal)
                    identity=ProviderID(_digest((SCHEMA+'.scope',self.targets.source_sha256,definition,expected)))
                    scoped.append(ObservedSourceScopeLink(identity,ScopeKind.CLASS_BODY,definition,
                        T.Body(unit,declared.template,declared.body),declared.body_scope,matched,source_artifact,
                        ProviderFactReference(syntax_artifact,'#/nodes/'+str(declared.template.occurrence)),
                        root_descriptor,constant_path,flags,
                        tuple(a for c in matched for a in frame_entries[c.process_id,c.code.key])))
            pending=[]
            for ordinal, function in enumerate(facts.functions):
                node = syntax.nodes[function.template.occurrence]
                if node.constructor not in ('FunctionDef', 'AsyncFunctionDef', *_EXPRESSION_BODIES):continue
                attributes = dict(zip(schemas[node.constructor].attributes,
                    (v.scalar.to_python() if v.kind == 'SCALAR' else None for v in node.attributes)))
                span = tuple(attributes[k] for k in ('lineno','end_lineno','col_offset','end_col_offset'))
                for flags,(root_code,mappings) in replay.items():
                    if node.constructor in _EXPRESSION_BODIES:
                        role, name = _EXPRESSION_BODIES[node.constructor]
                        block = expression_blocks.get((function.template.occurrence, role))
                        if (block is None or block.source_scope != function.environment.scope
                                or function.body_scope is None
                                or function.body_scope.source_scope != block.source_scope): continue
                        candidates = expression_paths.get((name, span), ())
                    else:
                        candidates = mappings.get(span, ())
                    for constant_path, child, _ in candidates:
                        expected = decode(CapturedCode, describe_code(child))
                        matched = tuple(c for c in observed if c.code == expected)
                        if not matched:continue
                        definition = slicer.fact(facts, 'functions', ordinal)
                        identity = ProviderID(_digest((SCHEMA,self.targets.source_sha256,definition,expected)))
                        row = ObservedSourceCodeLink(identity,definition,source_port(facts,function.value),
                            T.Body(unit,function.template,function.body),function.body_scope,matched,
                            tuple(targets_by_code[expected.key]),tuple(entries_by_code[expected.key]),
                            ProviderArtifact(str(path),sha256(raw).hexdigest(),len(raw),'python-source'),
                            ProviderFactReference(syntax_artifact,'#/nodes/'+str(function.template.occurrence)),
                            root_descriptor,constant_path,flags)
                        pending.append(row)
            if not pending and not scoped:continue
            source=view.unit(unit)
            for row in (*pending,*scoped):
                body = view.source_region_ref(unit,row.body.template,row.body.region)
                point = Point(body.namespace,row.id,None)
                key = self._key(point)
                records=self.records if type(row) is ObservedSourceCodeLink else self.scope_records
                if key in records and records[key] != row:
                    raise ValueError('observed code mapping has conflicting compiler paths')
                records[key] = row; self.points[key] = point; self.bodies[key] = body
                self._sources[unit] = source
        self.fact_materials.admit((*tuple(r.function_fact for r in self.records.values()),
            *tuple(r.source_fact for r in self.scope_records.values())))
        self.check(); view.register(self)

    @staticmethod
    def _key(point):return point.namespace,point.node

    def _admit_trace(self,logical,size,digest):
        """Hash every original stream once, then guard its immutable identity.

        The ordinary readers still independently verify their schemas, records
        and receipts. Query checks reuse this adapter's admitted dev/ino/size/
        mtime/ctime; a changed or newly shadowed plain/gzip artifact is rejected.
        No full trace payload is retained in the source adapter.
        """
        physical=resolve_trace_file(logical)
        if logical.is_symlink() or physical.is_symlink():
            raise ValueError('observed code capture input became a symlink')
        stamp=_stamp(physical)
        expected=(physical,stamp,size,digest)
        previous=self._trace_guard.get(logical)
        if previous is not None:
            if previous!=expected:raise ValueError('observed code capture receipt changed')
            return
        actual=sha256();length=0
        with open_binary(logical) as stream:
            for block in iter(lambda:stream.read(4*1024**2),b''):
                length+=len(block);actual.update(block)
        if (_stamp(physical)!=stamp or physical.is_symlink() or logical.is_symlink()
                or resolve_trace_file(logical)!=physical or (length,actual.hexdigest())!=(size,digest)):
            raise ValueError('observed code capture bytes changed during admission')
        self._trace_guard[logical]=expected

    def _check_trace(self):
        for logical,(physical,stamp,_,_) in self._trace_guard.items():
            if (logical.is_symlink() or physical.is_symlink() or resolve_trace_file(logical)!=physical
                    or _stamp(physical)!=stamp):
                raise ValueError('observed code capture bytes or identity changed')

    def check(self):
        self.view.catalog.fact_store.validate_parents()
        if _json(getattr(self.view.catalog, 'replay_profiles', {})) != self._replay_profile_bytes:
            raise ValueError('compatible replay profile declaration changed')
        for profile in self.compiled:profile.check()
        self.fact_materials.check()
        if tuple(sorted(Path(self.trace.directory).glob('python-call-target-meta.*.json'))) != self._target_metas:
            raise ValueError('observed target process inventory changed')
        for source in self._sources.values():source.check()
        if any(path.read_bytes() != raw for path,raw in self._guard.items()):
            raise ValueError('observed code/static source material changed')
        self._check_trace()

    def describe(self, point):
        if self._key(point) not in self.records and self._key(point) not in self.scope_records:return None
        if point.context is not None:raise ValueError('observed code evidence has no static invocation context')
        self.check()
        return V.ProgramNode(point,None,V.ProgramNodeRole.PROVIDER,self.bodies[self._key(point)],None)

    def original(self, point):
        key=self._key(point)
        return self.records[key] if key in self.records else self.scope_records[key]
    def expand(self, point):return ()
    def explain(self, point):
        row = self.original(point)
        return dict(original=row,code_template_matched=True,
            scope_kind=row.kind.value if type(row) is ObservedSourceScopeLink else 'FUNCTION_BODY',
            compatible_replay_used=row.body.unit in self.replay_profiles,
            original_compilation_request_proven=False,
            source_function_creation_proven=False,caller_site_selected=False,
            globals_or_cell_contents_proven=False)

    def _neighbors(self, point, incoming):
        if point.context is not None:return Neighborhood()
        keys = tuple(k for k,b in self.bodies.items() if b == point) if incoming else (self._key(point),)
        keys = tuple(k for k in keys if k in self.records or k in self.scope_records)
        if not keys:return Neighborhood()
        self.check(); edges=[]
        for key in keys:
            source,target=self.points[key],self.bodies[key];row=self.original(source)
            conditions = (
                'CODE_TEMPLATE_CORRESPONDENCE_NOT_SCOPE_EXECUTION_OR_CREATOR_IDENTITY',
                'F4_EXECUTION_PROFILE_AND_CALLER_INTERFACE_STILL_REQUIRED')
            if row.body.unit in self.replay_profiles:
                conditions += ('CODE_EQUIVALENT_REPLAY_NOT_ORIGINAL_COMPILATION_REQUEST',)
            guards=tuple(Condition(SCHEMA,c,source,None,(source,target)) for c in conditions)
            locators=(source.namespace.graph,)
            edges.append(Edge(source,target,K.IMPLEMENTATION,Meaning.STRUCTURE,
                (Evidence('scar.observed-code.original-source-body.v1',locators,(source,target)),),guards,Strength.MAY))
        return Neighborhood(tuple(edges))

    def incoming(self, point):return self._neighbors(point,True)
    def outgoing(self, point):return self._neighbors(point,False)

    def summary(self):
        matched={(c.process_id,c.code.key) for r in (*self.records.values(),*self.scope_records.values()) for c in r.captures}
        kinds=defaultdict(int)
        for row in self.scope_records.values():kinds[row.kind.value]+=1
        return dict(code_links=len(self.records),units=len(self._sources),
            scope_links=len(self.scope_records),scope_kinds=dict(kinds),
            captured_code_templates=len(self.trace.frame_scan.captures),matched_code_templates=len(matched),
            unmatched_code_templates=len(self.trace.frame_scan.captures)-len(matched),
            compiled_units=sorted(self._compiled),
            compatible_replay_units=sorted(self.replay_profiles),
            target_observations=sum(len(r.targets) for r in self.records.values()),
            entry_bindings=sum(len(r.entries) for r in self.records.values()),issues=self.issues,
            source_bodies_copied=False,creator_instances_proven=False,callsite_interfaces_connected=False,
            first_stage_complete=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',required=True);parser.add_argument('--trace',required=True)
    parser.add_argument('--project-root',required=True);parser.add_argument('--unit',action='append',default=[])
    parser.add_argument('--compiled-unit',action='append',default=[])
    parser.add_argument('--target-max-bytes',type=int,default=32_000_000)
    parser.add_argument('--target-max-rows',type=int,default=100_000)
    parser.add_argument('--frame-max-events',type=int,default=100_000)
    parser.add_argument('--out',required=True);args=parser.parse_args()
    from scar.analysis.source_compiled_code_profiles import CompiledCodeProfiles
    view=ProgramView(args.catalog)
    profiles=tuple(CompiledCodeProfiles(view.catalog,u) for u in args.compiled_unit)
    provider=ObservedSourceCodeProvider(view,args.trace,args.project_root,units=args.unit,compiled=profiles,
        target_max_bytes=args.target_max_bytes,target_max_rows=args.target_max_rows,
        frame_budget=replace(CallEdgeBudget(),max_events=args.frame_max_events))
    out=Path(args.out).absolute()
    if out.exists():raise ValueError('fresh observed source-code view output required')
    _durable_mkdir(out);table=write_table(out/'links.jsonl.gz',provider.records.values())
    scopes=write_table(out/'scope-links.jsonl.gz',provider.scope_records.values());provider.check()
    report=dict(schema=SCHEMA,schema_version=2,catalog=str(view.catalog.path),trace=provider.trace.directory,
        run_scope=provider.targets.source_sha256,compiled_units=[p.unit for p in profiles],
        target_reader_budget=provider.target_reader_budget,frame_reader_budget=encode(provider.trace.frame_budget),
        table=table,scope_table=scopes,summary=provider.summary())
    _durable_bytes(out/'result.json',_json(report),replace=False);print(json.dumps(report['summary']),flush=True)


if __name__=='__main__':main()
