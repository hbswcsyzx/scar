"""Match real code observations to shared F4 definitions using compiler paths.

Reuse the established parent LOAD_CONST/span mapper and full code fingerprint.
This is a code-template correspondence, not a guessed function-name binding,
callsite selection, creator-instance identity or a static invocation frame.
"""
import argparse
import ast
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

from scar.analysis.call_operand_reader import read_call_operands
from scar.analysis.python_call_targets import read_python_call_targets
from scar.analysis.static_compilation import _scope_nodes
from scar.analysis.static_query import _Fragments
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.source_value_flow import _artifact
from scar.analysis.program_view import ProgramView, _digest
from scar.analysis.source_observed_materials import ObservedFactMaterials
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_mkdir, _durable_bytes
from scar.analysis.source_template_links import _json
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.program.source_observed_codes import ObservedSourceCodeLink
from scar.ir.program import normal_targets as T, view as V
from scar.ir.program.call_edges import CapturedCode
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


class ObservedSourceCodeProvider:
    relation_kinds = frozenset((K.IMPLEMENTATION,))

    def __init__(self, view, trace, project_root, *, units=()):
        self.view = view
        self.trace = read_call_operands(trace, project_root)
        self.targets = read_python_call_targets(self.trace)
        if any(m['python'] != sys.version for m in self.trace.frame_scan.metadata):
            raise ValueError('code correspondence needs the recorded compiler runtime')
        self.records = {}; self.points = {}; self.bodies = {}; self.issues = []
        self.fact_materials=ObservedFactMaterials(view.catalog)
        self._sources = {}; self._guard = {}
        self._target_metas = tuple(sorted(Path(self.trace.directory).glob('python-call-target-meta.*.json')))
        digests=[]
        for meta in self._target_metas:
            raw=meta.read_bytes();self._guard[meta]=raw;receipt=json.loads(raw)['file']
            logical=Path(receipt['path']);physical=resolve_trace_file(logical)
            self._guard[physical]=physical.read_bytes()
            with open_binary(logical) as stream:payload=stream.read()
            if (len(payload),sha256(payload).hexdigest()) != (receipt['bytes'],receipt['sha256']):
                raise ValueError('observed target material changed while being admitted')
            digests.append((str(meta),sha256(raw).hexdigest(),str(logical),sha256(payload).hexdigest()))
        if sha256(json.dumps(digests,sort_keys=True).encode()).hexdigest() != self.targets.source_sha256:
            raise ValueError('observed target receipts differ from their original reader')
        captures = defaultdict(list)
        for capture in self.trace.frame_scan.captures:
            captures[capture.code.filename].append(capture)
        selected = tuple(units or (u for u,r in view.catalog.fact_store.rows.items() if r['path'] in captures))
        slicer = ReferenceSlicer(type('SourceFacts', (), {'fact_store': view.catalog.fact_store})())
        for unit in selected:
            if unit in view.catalog.fact_store.original_source_units:
                self.issues.append(dict(unit=unit,reason='COMPILED_CONTEXT_CODE_CORRESPONDENCE_REQUIRES_ORIGINAL_PROFILE'));continue
            model = view.catalog.fact_store.model_units[unit]
            path = Path(model['path']); observed = captures.get(str(path), ())
            if not observed:continue
            raw = path.read_bytes()
            if len(raw) > 1_000_000 or sha256(raw).hexdigest() != model['raw_sha256']:
                raise ValueError('observed code source differs from the original static source')
            self._guard[path] = raw
            root = view.catalog.fact_store.model_for(unit)
            descriptor = model['artifacts']['source_syntax']
            syntax = decode(SourceSyntaxMaterial, _Fragments(root).read(descriptor))
            syntax_path = root/descriptor['path']; self._guard[syntax_path] = syntax_path.read_bytes()
            syntax_artifact = _artifact(syntax_path, 'scar.source-syntax')
            schemas = {s.name:s for s in syntax.profile.ast_schema}
            facts = view.catalog.fact_store.load(unit)
            # Match the existing ordinary source compiler contract. Source
            # future directives are handled by compile itself. Runtime flags
            # such as CO_NESTED are not inherited compiler input flags.
            code = compile(raw, str(path), 'exec', flags=0, dont_inherit=True, optimize=0)
            mappings = {}; issues = []
            _scope_nodes(ast.parse(raw, filename=str(path)), code, (), ast.Module, mappings, issues)
            replay = {0:(code,mappings)}
            for ordinal, function in enumerate(facts.functions):
                node = syntax.nodes[function.template.occurrence]
                if node.constructor not in ('FunctionDef', 'AsyncFunctionDef'):continue
                attributes = dict(zip(schemas[node.constructor].attributes,
                    (v.scalar.to_python() if v.kind == 'SCALAR' else None for v in node.attributes)))
                span = tuple(attributes[k] for k in ('lineno','end_lineno','col_offset','end_col_offset'))
                for flags,(root_code,mappings) in replay.items():
                    for constant_path, child, _ in mappings.get(span, ()):
                        expected = decode(CapturedCode, describe_code(child))
                        matched = tuple(c for c in observed if c.code == expected)
                        if not matched:continue
                        definition = slicer.fact(facts, 'functions', ordinal)
                        identity = ProviderID(_digest((SCHEMA,self.targets.source_sha256,definition,expected)))
                        row = ObservedSourceCodeLink(identity,definition,source_port(facts,function.value),
                            T.Body(unit,function.template,function.body),function.body_scope,matched,
                            tuple((a,t) for a,t in zip(self.targets.target_anchors,self.targets.targets) if t.code == expected.key),
                            tuple((a,e) for a,e in zip(self.targets.entry_anchors,self.targets.entries) if e.code == expected.key),
                            ProviderArtifact(str(path),sha256(raw).hexdigest(),len(raw),'python-source'),
                            ProviderFactReference(syntax_artifact,'#/nodes/'+str(function.template.occurrence)),
                            decode(CapturedCode,describe_code(root_code)),constant_path,flags)
                        body = view.source_region(unit,function.template,function.body)
                        point = Point(body.namespace,identity,None)
                        key = self._key(point)
                        if key in self.records and self.records[key] != row:
                            raise ValueError('observed code mapping has conflicting compiler paths')
                        self.records[key] = row; self.points[key] = point; self.bodies[key] = body
                        self._sources[unit] = view.unit(unit)
        self.fact_materials.admit(tuple(r.function_fact for r in self.records.values()))
        self.check(); view.register(self)

    @staticmethod
    def _key(point):return point.namespace,point.node

    def check(self):
        self.view.catalog.fact_store.validate_parents()
        self.fact_materials.check()
        if tuple(sorted(Path(self.trace.directory).glob('python-call-target-meta.*.json'))) != self._target_metas:
            raise ValueError('observed target process inventory changed')
        for source in self._sources.values():source.check()
        if any(path.read_bytes() != raw for path,raw in self._guard.items()):
            raise ValueError('observed code/static source material changed')
        for receipt in (*self.trace.files,*self.trace.frame_scan.files):
            path = Path(self.trace.directory)/receipt.path
            with open_binary(path) as stream:raw=stream.read()
            if len(raw) != receipt.raw_bytes or sha256(raw).hexdigest() != receipt.raw_sha256:
                raise ValueError('observed code capture bytes changed')

    def describe(self, point):
        if self._key(point) not in self.records:return None
        if point.context is not None:raise ValueError('observed code evidence has no static invocation context')
        self.check()
        return V.ProgramNode(point,None,V.ProgramNodeRole.PROVIDER,self.bodies[self._key(point)],None)

    def original(self, point):return self.records[self._key(point)]
    def expand(self, point):return ()
    def explain(self, point):
        return dict(original=self.original(point),code_template_matched=True,
            source_function_creation_proven=False,caller_site_selected=False,
            globals_or_cell_contents_proven=False)

    def _neighbors(self, point, incoming):
        if point.context is not None:return Neighborhood()
        keys = tuple(k for k,b in self.bodies.items() if b == point) if incoming else (self._key(point),)
        keys = tuple(k for k in keys if k in self.records)
        if not keys:return Neighborhood()
        self.check(); edges=[]
        for key in keys:
            source,target=self.points[key],self.bodies[key];row=self.records[key]
            guards=tuple(Condition(SCHEMA,c,source,None,(source,target)) for c in (
                'CODE_TEMPLATE_CORRESPONDENCE_NOT_SOURCE_FUNCTION_CREATION_IDENTITY',
                'F4_EXECUTION_PROFILE_AND_CALLER_INTERFACE_STILL_REQUIRED'))
            locators=(source.namespace.graph,)
            edges.append(Edge(source,target,K.IMPLEMENTATION,Meaning.STRUCTURE,
                (Evidence('scar.observed-code.original-source-body.v1',locators,(source,target)),),guards,Strength.MAY))
        return Neighborhood(tuple(edges))

    def incoming(self, point):return self._neighbors(point,True)
    def outgoing(self, point):return self._neighbors(point,False)

    def summary(self):
        return dict(code_links=len(self.records),units=len(self._sources),
            target_observations=sum(len(r.targets) for r in self.records.values()),
            entry_bindings=sum(len(r.entries) for r in self.records.values()),issues=self.issues,
            source_bodies_copied=False,creator_instances_proven=False,callsite_interfaces_connected=False,
            first_stage_complete=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',required=True);parser.add_argument('--trace',required=True)
    parser.add_argument('--project-root',required=True);parser.add_argument('--unit',action='append',default=[])
    parser.add_argument('--out',required=True);args=parser.parse_args()
    view=ProgramView(args.catalog);provider=ObservedSourceCodeProvider(view,args.trace,args.project_root,units=args.unit)
    out=Path(args.out).absolute()
    if out.exists():raise ValueError('fresh observed source-code view output required')
    _durable_mkdir(out);table=write_table(out/'links.jsonl.gz',provider.records.values());provider.check()
    report=dict(schema=SCHEMA,schema_version=1,catalog=str(view.catalog.path),trace=provider.trace.directory,
        run_scope=provider.targets.source_sha256,table=table,summary=provider.summary())
    _durable_bytes(out/'result.json',_json(report),replace=False);print(json.dumps(report['summary']),flush=True)


if __name__=='__main__':main()
