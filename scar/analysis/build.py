"""Unified, non-executing build and read session over original graph shards.

Publication references the source catalog and its relationship shards. Function
and loop bodies retain their original identities; resource interfaces are lazy.
A successful build is workflow acceptance, never whole-program closure.
"""
from __future__ import annotations

import argparse
import gzip
from collections import Counter
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path

from scar.ir.record_codec import encode
from scar.ir.program.dependencies import DependencyPoint as Point, GraphNamespace

SCHEMA = 'scar.program-build'


def _rules():
    return {name: sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
        for name in ('build.py', 'observed_body_scope.py', 'observed_call_bindings.py',
            'observed_function_interfaces.py', 'build_resources.py','build_target_resources.py','build_f4.py','build_f4_resources.py',
            '../ir/program/build_f4_resources.py')}


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False) + '\n')


def _receipt(path):
    raw = path.read_bytes()
    return dict(path=str(path), sha256=sha256(raw).hexdigest(), bytes=len(raw))


def _check(receipt):
    if _receipt(Path(receipt['path'])) != receipt:
        raise ValueError('build input receipt changed: ' + receipt['path'])


def _configuration_inputs(roots, out, gaps):
    """Admit declared YAML graphs; do not compose Hydra or evaluate tags."""
    from scar.analysis.static_sources import _EXCLUDED_DIRECTORIES
    result = []
    seen = set()
    for root in roots:
        for directory, directories, files in os.walk(root, followlinks=False):
            directories[:] = sorted(d for d in directories if d not in _EXCLUDED_DIRECTORIES
                and not (Path(directory) / d).is_symlink()
                and not (Path(directory) / d).resolve().is_relative_to(out))
            for name in sorted(files):
                path = Path(directory) / name
                if path.suffix not in ('.yaml', '.yml') or path in seen:
                    continue
                seen.add(path)
                try:
                    from scar.analysis.source_data_materials import parse_yaml_material
                    material, _ = parse_yaml_material(path)
                    folder = out / 'configuration'
                    folder.mkdir(exist_ok=True)
                    stored = folder / (sha256(str(path).encode()).hexdigest() + '.json.gz')
                    stored.write_bytes(gzip.compress(json.dumps(encode(material),
                        separators=(',', ':')).encode(), mtime=0))
                    result.append(dict(source=_receipt(path), material=_receipt(stored),
                        nodes=len(material.nodes), obligations=encode(material.obligations)))
                except Exception as error:
                    # Parser/missing optional dependency failures are input gaps,
                    # never a reason to drop the source silently.
                    gaps.append(dict(layer='configuration', kind=type(error).__name__,
                        file=str(path), detail=str(error)))
    if result:
        gaps.append(dict(layer='configuration', kind='CONFIGURATION_COMPOSITION_UNRESOLVED',
            detail='Declared YAML representation graphs are admitted; loader selection, interpolation, '
                'defaults composition and runtime configuration-to-port bindings remain open.'))
    _write(out / 'configuration.json', dict(schema='scar.build-configuration-inputs',
        materials=result, runtime_configuration_proven=False))
    return result


def _budget(seconds=3600, input_bytes=16 * 1024**3):
    from scar.analysis.program_dependency_session import ProgramDependencyBudget
    return ProgramDependencyBudget(max_seconds=seconds, max_input_bytes=input_bytes,
        max_graphs=100000, max_shards=100000, max_cached_bytes=512 * 1024**2)


class _LazyResources:
    """Materialize resource interfaces once for each demanded original body."""
    def __init__(self, view, session, *, target=None):
        from scar.analysis.build_resources import BuildResourceProvider
        self.view, self.session = view, session
        self.provider = BuildResourceProvider(view, target=target)
        self.seen = set()
        self.relation_kinds = self.provider.relation_kinds

    def demand(self, point):
        namespace = point.namespace
        if namespace in self.seen:
            return
        index = self.session.index(namespace)
        for operation in index.graph.operations:
            owner = Point(namespace, operation.id, None)
            ports = tuple(Point(namespace, node, None) for node in
                (*(use.id for use in operation.uses), *operation.results))
            self.provider.add_operation(owner, ports, operation, candidates=True)
        self.seen.add(namespace)

    def incoming(self, point):
        self.demand(point)
        return self.provider.incoming(point)

    def outgoing(self, point):
        self.demand(point)
        return self.provider.outgoing(point)

    def describe(self, point):
        return self.provider.describe(point)

    def original(self, point):
        return self.provider.original(point)

    def expand(self, point):
        return self.provider.expand(point)

    def explain(self, point):
        return self.provider.explain(point)


class BuildSession:
    """One catalog/code/call cache for any number of queries in a session."""
    def __init__(self, path, *, seconds=3600, input_bytes=16 * 1024**3, _publishing=False):
        from scar.analysis.program_dependency_session import ProgramDependencySession
        from scar.analysis.program_view import ProgramView, _RepresentationProvider
        self.path = Path(path).resolve()
        self.report = json.loads((self.path / 'manifest.json').read_bytes())
        self._f4=None
        if self.report.get('backend')=='F4':
            from scar.analysis.build_f4 import F4BuildSession
            self._f4=F4BuildSession(path,seconds=seconds,input_bytes=input_bytes,_publishing=_publishing)
            self.session=self._f4;self.view=self._f4.view;self.resources=self._f4.resources
            self.entry=self._f4.entry;self.entries=self._f4.entries;return
        if (self.report.get('schema'), self.report.get('schema_version')) != (SCHEMA, 1):
            raise ValueError('unsupported build manifest')
        if self.report['rules'] != _rules():
            raise ValueError('build resource or assembly rules changed')
        if not _publishing and self.report.get('workflow_complete') is not True:
            raise ValueError('build publication has not completed readback')
        _check(self.report['model'])
        for receipt in self.report['tables'].values():
            _check(receipt)
        self.session = ProgramDependencySession(Path(self.report['model']['path']).parent,
            budget=_budget(seconds, input_bytes))
        self.view = ProgramView(None, core_loader=self.session.index)
        self.view.dependencies = self.session.graph()
        # Core adapters validate against their own original entity tables.
        # Route extension-owned resource nodes to the metadata adapter, as the
        # ordinary ProgramView does, while keeping this same observed session.
        self.view.dependencies.providers[:] = [_RepresentationProvider(provider,
            self.view._core_extension) for provider in self.view.dependencies.providers]
        target = self.report.get('target')
        if target is not None:
            _check(target)
        self.resources = _LazyResources(self.view, self.session,
            target=None if target is None else Path(target['path']).parent)
        self.view.register(self.resources)
        self.observed = None
        self.entries = tuple(self.session.select_bodies(file=self.report['entry'], kind='MODULE'))
        if len(self.entries) != 1:
            self.session.close()
            raise ValueError('entry requires exactly one admitted module body')
        self.entry = Point(GraphNamespace.from_source(self.entries[0]), self.entries[0].region, ())

    def attach_trace(self):
        if self._f4 is not None:return self._f4.attach_trace()
        if self.observed is None and self.report['trace'] is not None:
            for receipt in self.report['trace']['inputs']:
                _check(receipt)
            self.observed = self.session.attach_observations(self.report['trace']['path'])
        return self.observed

    def select(self, *, file=None, entry=None, kind=None):
        if self._f4 is not None:return self._f4.select(file=file,entry=entry,kind=kind)
        return tuple(self.session.select_bodies(file=file, entry=entry, kind=kind))

    def close(self):
        if self._f4 is not None:return self._f4.close()
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()


def _model_for(entry, explicit):
    if explicit:
        return Path(explicit).resolve()
    # Reuse the workspace's admitted source catalog, never mutate it.
    candidate = Path(__file__).resolve().parents[2] / 'artifacts/current/static'
    if (candidate / 'manifest.json').is_file():
        report = json.loads((candidate / 'manifest.json').read_bytes())
        matches = [u for u in report.get('units', ()) if u['path'] == str(entry)]
        if len(matches) == 1 and matches[0]['raw_sha256'] == sha256(entry.read_bytes()).hexdigest():
            return candidate
    return None


def build(entry, trace, out, *, model=None, jobs=4, source_roots=(),
          max_seconds=3600, max_input_bytes=16 * 1024**3,catalog=None,cache_roots=(),target=None,
          body_scope='all', call_binding=None):
    from scar.analysis.static_program import build_static_program, link_static_program, read_static_program
    from scar.analysis.static_calls import StaticCallBudget
    from scar.analysis.program_dependency_export import export_dependency_walk
    entry, out = Path(entry).resolve(), Path(out).absolute()
    if not entry.is_file() or entry.suffix != '.py':
        raise ValueError('entry must be an existing Python source file')
    if not 1 <= jobs <= 32 or max_seconds < 1 or max_input_bytes < 1:
        raise ValueError('jobs must be in [1, 32] and budgets must be positive')
    if out.exists() or out.resolve() != out:
        raise ValueError('build requires a fresh canonical output directory')
    if entry.is_relative_to(out):
        raise ValueError('build output must not contain entry source')
    trace_path = None if trace is None else Path(trace).resolve()
    if trace_path is not None and not trace_path.is_dir():
        raise ValueError('trace must be an existing directory; omit it for static-only build')
    if body_scope not in ('all', 'observed') or body_scope == 'observed' and (trace_path is None or model is not None):
        raise ValueError('observed body scope requires a trace and a fresh source build')
    call_binding = call_binding or ('observed' if body_scope == 'observed' else 'static')
    if call_binding not in ('static', 'observed') or call_binding == 'observed' and trace_path is None:
        raise ValueError('observed call binding requires a trace')
    target_path = None if target is None else Path(target).resolve()
    target_ref = None
    if target_path is not None:
        from scar.analysis.target_graph import TargetHardwareGraph
        hardware = TargetHardwareGraph(target_path)
        hardware.resources(); hardware.connections(); hardware.paths()
        target_ref = _receipt(target_path / 'result.json')
    from scar.analysis.build_f4 import discover,build_f4
    f4=discover(entry,trace_path,catalog=catalog,cache_roots=cache_roots) if catalog or model is None else None
    if f4 is not None:
        return build_f4(entry,trace_path,out,f4,source_roots=source_roots,
            max_seconds=max_seconds,max_input_bytes=max_input_bytes,target=target_path)
    selected = _model_for(entry, model) if model or not source_roots else None
    out.mkdir(parents=True)
    if selected is None:
        selected = out / 'source'
        observed_scope = None
        source_files = ()
        if body_scope == 'observed':
            from scar.analysis.observed_body_scope import read_observed_scope
            observed_scope = read_observed_scope(trace_path)
            source_files = tuple(sorted({c.code.filename for c in observed_scope.captures
                if Path(c.code.filename).suffix == '.py' and Path(c.code.filename).is_file()}))
        source = build_static_program(entry.parent, source_roots=source_roots,
            out=selected, jobs=jobs, phase='bodies', source_files=source_files)
        from scar.analysis.static_body import expand_static_bodies
        entries=()
        if body_scope == 'observed':
            from scar.analysis.observed_body_scope import select_observed_bodies
            entries, selection=select_observed_bodies(selected, trace_path, entry,scope=observed_scope)
            selection['observed_source_files'] = list(source_files)
            _write(out/'body-selection.json',selection)
        expand_static_bodies(selected, jobs=jobs, entries=entries)
        source = (link_static_program(selected, budget=replace(StaticCallBudget(),
            max_seconds=max_seconds, max_input_bytes=max_input_bytes))
            if call_binding == 'static' else read_static_program(selected, verify=False))
    else:
        source = read_static_program(selected, verify=False)
        # Refinement owns a private copy; never modify a supplied catalog.
        if 'static_calls' not in source and call_binding == 'static':
            import shutil
            original_model = selected
            selected = out / 'source'
            shutil.copytree(original_model, selected)
            from scar.analysis.static_body import expand_static_bodies
            expand_static_bodies(selected, jobs=jobs)
            source = link_static_program(selected, budget=replace(StaticCallBudget(),
                max_seconds=max_seconds, max_input_bytes=max_input_bytes))
    rows = [u for u in source['units'] if u['path'] == str(entry)]
    if len(rows) != 1 or rows[0]['raw_sha256'] != sha256(entry.read_bytes()).hexdigest():
        raise ValueError('source catalog does not contain current entry')
    trace_ref = None
    if trace_path is not None:
        from scar.analysis.program_observed_dependencies import _inputs
        trace_ref = dict(path=str(trace_path), inputs=[_receipt(p) for p in sorted(_inputs(trace_path))])
    # Missing dependencies remain individually referenced, not hidden behind totals.
    gaps = []
    for name in ('remaining', 'source_issues', 'worker_errors', 'source_changed'):
        for item in source.get(name, ()):
            gaps.append(dict(layer='source', kind=name, detail=item))
    for unit in source['units']:
        for issue in unit.get('issues', ()):
            gaps.append(dict(layer='local', file=unit['path'], kind='UNIT_ISSUE', detail=issue))
        for body in unit['bodies']:
            if body['status'] != 'LOWERED':
                gaps.append(dict(layer='local', file=unit['path'], entry=body['entry_key'],
                    kind=body['status'], artifact=body.get('artifact'),
                    detail={name: body[name] for name in ('reason', 'issue', 'gaps',
                        'module_frontiers', 'class_frontiers', 'diagnostics', 'last_attempt_issue') if name in body}))
    calls = source.get('static_calls')
    if calls is None:
        gaps.append(dict(layer='calls', kind='STATIC_CALL_INFERENCE_NOT_REQUESTED'
            if call_binding == 'observed' else 'CALL_RELATIONS_NOT_PUBLISHED',
            detail='Static local data/control/state subgraphs remain indexed. '
                'Observed interfaces apply only to their recorded run; unobserved dispatch remains open.'))
    else:
        gaps.extend(dict(layer='calls', kind='PUBLICATION_FRONTIER', detail=f) for f in calls['frontiers'])
        gaps.append(dict(layer='calls', kind='CONDITIONAL_RELATIONS_REMAIN',
            counts=calls.get('relation_frontier_counts', {}), complete=calls['complete']))
    configuration = _configuration_inputs((entry.parent, *(Path(p).resolve() for p in source_roots)), out, gaps)
    gaps.extend([dict(layer='resources', kind='RUNTIME_RESOURCE_EVIDENCE_NOT_JOINED',
        detail='CPU/GPU, host/device memory and file/SSD/NVMe interfaces remain symbolic; actual placement, transfer and I/O require original events.'),
        dict(layer='coverage', kind='INFERENCE_PATH_NOT_CERTIFIED',
        detail='Source coverage and observed prefix do not certify successful entry-to-output inference.')])
    if trace_path is None:
        gaps.append(dict(layer='observed', kind='TRACE_NOT_SUPPLIED'))
    # Relationship bodies stay in their original shards. Contexts are stored
    # independently from canonical bodies by the existing call publication.
    _write(out/'relationships.json', dict(schema='scar.build-relationship-index',
        model=str(selected), shards=[] if calls is None else [dict(
            caller=s['caller'], artifact=s['artifact'], calls=s['calls']) for s in calls['shards']],
        observed='observed.json' if trace_path is not None else None,
        function_bodies_copied=0, loop_iterations_expanded=0))
    report = dict(schema=SCHEMA, schema_version=1, rules=_rules(), entry=str(entry), model=_receipt(selected/'manifest.json'),
        trace=trace_ref, target=target_ref, tables={}, body_storage='ORIGINAL_REFERENCED_SHARDS',
        cross_layer_storage='ORIGINAL_CALL_SHARDS_AND_SCOPED_OBSERVATIONS',
        resource_storage='LAZY_TYPED_SYMBOLIC_INTERFACES', original_body_bytes_copied=0,
        loops_unrolled=False, target_executed=False, first_stage_complete=False,
        entry_probe_limits=dict(max_points=128, max_edges=512, max_depth=8),
        observed_admission='ABSENT' if trace_path is None else 'PENDING',
        body_scope=body_scope,
        call_binding=call_binding,
        workflow_complete=False, selection_scope='INDEXED_CORPUS_NOT_PROVEN_RUNTIME_REACHABILITY',
        summary=dict(source_units=len(source['units']),
            configuration_inputs=len(configuration),
            body_statuses=dict(Counter(b['status'] for u in source['units'] for b in u['bodies']))))
    _write(out/'manifest.json', report)
    with BuildSession(out, seconds=max_seconds, input_bytes=max_input_bytes, _publishing=True) as session:
        session.resources.demand(session.entry)
        (out/'resources.json.gz').write_bytes(gzip.compress(json.dumps(
            session.resources.provider.payload(), separators=(',', ':')).encode(), mtime=0))
        # Admission of the actual original trace is isolated from static may-edges.
        try:
            observed = session.attach_trace()
            if observed is not None:
                from scar.analysis.observed_dependency_export import export_observed_dependencies
                _write(out/'observed.json', export_observed_dependencies(observed))
                report['observed'] = dict(scopes=len(observed.scopes), edges=len(observed.edges))
                report['observed_admission'] = 'ADMITTED'
                gaps.extend(dict(layer='observed', kind='FRONTIER', detail=encode(f)) for f in observed.frontiers)
                gaps.extend(dict(layer='observed', kind='ISSUE', detail=i) for i in observed.issues)
        except (ValueError, OverflowError, TimeoutError, FileNotFoundError) as error:
            report['observed_admission'] = 'REJECTED'
            gaps.append(dict(layer='observed', kind=type(error).__name__, detail=str(error)))
        # Small explicit probe validates the composed facade; it is not full coverage.
        walk = session.view.dependencies.walk((session.entry,), direction='outgoing',
            include_structure=True, max_points=128, max_edges=512, max_depth=8)
        probe = export_dependency_walk(walk)
        _write(out/'entry-query.json', probe)
        gaps.extend(dict(layer='query', kind=f.kind, detail=f.detail, point=encode(f.point)) for f in walk.frontiers)
    _write(out/'gaps.json', dict(schema='scar.build-gaps', gaps=gaps,
        counts=dict(Counter(g['layer'] for g in gaps)), first_stage_complete=False))
    report['tables'] = {p.name: _receipt(p) for p in out.iterdir()
        if p.is_file() and p.name != 'manifest.json'}
    report['summary']['gaps'] = len(gaps)
    _write(out/'manifest.json', report)
    # Read back through the same public session and expand an original body.
    with BuildSession(out, _publishing=True) as recovered:
        recovered.view.expand(recovered.entry)
    report['workflow_complete'] = True
    _write(out/'manifest.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scar build')
    parser.add_argument('--entry', required=True)
    parser.add_argument('--trace')
    parser.add_argument('--target', help='retained target hardware graph; inventory is not placement evidence')
    parser.add_argument('--body-scope', choices=('all','observed'), default='all',
        help='lower all declared bodies or exact observed code bodies; all source templates remain indexed')
    parser.add_argument('--call-binding', choices=('static','observed'),
        help='infer static call targets or join actual trace selections; observed body scope defaults to observed binding')
    parser.add_argument('--out', required=True)
    parser.add_argument('--model', help='reuse an existing admitted source model')
    parser.add_argument('--source-root', action='append', default=[])
    parser.add_argument('--catalog',help='explicit F4 context catalog; otherwise discover a compatible retained catalog')
    parser.add_argument('--cache-root',action='append',default=[],help='search this directory for retained relationship publications')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--max-seconds', type=int, default=3600)
    parser.add_argument('--max-input-bytes', type=int, default=16 * 1024**3)
    args = parser.parse_args(argv)
    result = build(args.entry, args.trace, args.out, model=args.model, jobs=args.jobs,
        source_roots=args.source_root, max_seconds=args.max_seconds, max_input_bytes=args.max_input_bytes,
        catalog=args.catalog,cache_roots=args.cache_root,target=args.target,body_scope=args.body_scope,
        call_binding=args.call_binding)
    print(json.dumps(dict(workflow_complete=result['workflow_complete'],
        first_stage_complete=result['first_stage_complete'], **result['summary'])))
    return 0


def query_main(argv=None):
    from scar.analysis.program_dependency_export import export_dependency_walk
    parser = argparse.ArgumentParser(prog='scar build-query')
    parser.add_argument('build')
    parser.add_argument('--file')
    parser.add_argument('--entry')
    parser.add_argument('--kind')
    parser.add_argument('--node', help='original typed wire ID from an expansion')
    parser.add_argument('--action', choices=('summary', 'select', 'expand', 'dependencies', 'observed', 'inputs', 'resources'), default='summary')
    parser.add_argument('--direction', choices=('incoming', 'outgoing'), default='incoming')
    parser.add_argument('--max-points', type=int, default=256)
    args = parser.parse_args(argv)
    with BuildSession(args.build) as session:
        if session._f4 is not None:
            result=_query_f4(session._f4,args)
            print(json.dumps(result,ensure_ascii=False));return 0
        if args.action == 'summary':
            result = session.report
        elif args.action == 'resources':
            session.resources.demand(session.entry)
            result = session.resources.provider.payload()
        elif args.action == 'inputs':
            result = json.loads((session.path / 'configuration.json').read_bytes())
            for material in result['materials']:
                _check(material['source'])
                _check(material['material'])
        elif args.action == 'observed':
            observed = session.attach_trace()
            result = dict(scopes=[] if observed is None else [encode(s) for s in observed.scopes],
                first_stage_complete=False)
        else:
            selected = session.select(file=args.file, entry=args.entry, kind=args.kind) if any(
                (args.file, args.entry, args.kind)) else session.entries
            points = [Point(GraphNamespace.from_source(b), b.region,
                () if b in session.entries else None) for b in selected]
            if args.node:
                points = [session.session.point(file=args.file, entry=args.entry, kind=args.kind, node=args.node)]
            if args.action == 'select':
                result = dict(bodies=[encode(b) for b in selected])
            elif args.action == 'expand':
                result = dict(children=[encode(c) for p in points for c in session.view.expand(p)])
            else:
                result = export_dependency_walk(session.view.dependencies.walk(points,
                    direction=args.direction, max_points=args.max_points))
        print(json.dumps(result, ensure_ascii=False))
    return 0


def _query_f4(session,args):
    from scar.analysis.program_dependency_export import export_dependency_walk
    if args.action=='summary':return session.report
    if args.action=='observed':return session.attach_trace()
    if args.action=='inputs':
        result=json.loads((session.path/'configuration.json').read_bytes())
        for material in result['materials']:
            _check(material['source']);_check(material['material'])
        return result
    if args.action=='resources':
        session.resources.demand(session.entry)
        return session.resources.payload()
    points=session.select(file=args.file,entry=args.entry,kind=args.kind)
    if args.node:points=(session.point(file=args.file,entry=args.entry,kind=args.kind,node=args.node),)
    if args.action=='select':return dict(points=[encode(p) for p in points])
    if args.action=='expand':return dict(children=[encode(p) for point in points for p in session.view.expand(point)])
    return export_dependency_walk(session.view.dependencies.walk(points,direction=args.direction,max_points=args.max_points))
