"""Connect observed dispatch categories to original F4 Python CALL interfaces.

Source ports are shared; occurrences remain in a separate evidence table.
Native entry, type-call stages, return completion and effects stay unproved.
"""
from collections import Counter, defaultdict
from bisect import bisect_left
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from scar.analysis.program_view import ProgramView, _digest
from scar.analysis.source_call_view import source_call_site, source_active_scope, prepare_source_ports
from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.analysis.source_roles import SyntaxRoleView
from scar.analysis.source_reference_slice import source_port
from scar.analysis.source_observed_calls import ObservedSourceCallsiteIndex
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.source_value_flow import _artifact
from scar.analysis.source_consumer_parents import _stamp
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import source_observed_boundaries as R, source_productions as P, view as V
from scar.ir.program.call_edges import CallEdgeBudget
from scar.ir.program.ids import ProviderID
from scar.ir.program.python_call_targets import PythonTargetKind as Target
from scar.ir.program.structured import PythonProtocolKind
from scar.ir.program.dependencies import (
    DependencyPoint as Point, DependencyFrame as Frame, DependencyKind as K, DependencyMeaning as Meaning,
    DependencyStrength as Strength, DependencyCondition as Condition,
    DependencyEvidence as Evidence, DependencyEdge as Edge,
    DependencyFrontier as Frontier, DependencyNeighborhood as Neighborhood,
    context_push, context_pop,
)
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import decode, encode


SCHEMA = 'scar.source-observed-boundaries'
_KINDS = frozenset((Target.NATIVE_BUILTIN, Target.NATIVE_WRAPPER,
    Target.TYPE_OBJECT, Target.OTHER_UNCLASSIFIED))
_FALSE = ('source_bodies_copied', 'loops_unrolled', 'implementation_entry_proven',
    'normal_completion_proven', 'effects_proven', 'target_executed', 'first_stage_complete')


def _pins():
    from scar.analysis import source_observed_codes, source_observed_calls, source_call_view
    from scar.analysis import native_callables
    from scar.ir.program import native_callables as native_types
    return {name: sha256(Path(module.__file__).read_bytes()).hexdigest() for name, module in (
        ('producer', __import__(__name__, fromlist=['__file__'])), ('types', R),
        ('code_reader', source_observed_codes), ('callsite_reader', source_observed_calls),
        ('call_ports', source_call_view), ('native_reader', native_callables), ('native_types', native_types))}


class _NativeInputs:
    """One strict companion read per original index, including NOT_RECORDED."""
    def __init__(self, index):
        from scar.analysis.native_callables import read_native_callables
        self.codes = index.codes; self.directory = Path(self.codes.trace.directory)
        self.inventory = self._inventory()
        self.capture = capture = read_native_callables(self.codes.trace)
        self.facts = {}
        if capture is not None:
            if capture.run_scope != self.codes.targets.source_sha256:
                raise ValueError('native companion belongs to another original dispatch run')
            for fact, anchor in zip(capture.facts, capture.anchors):
                self.facts[fact.caller.process_id, fact.attempt_index] = fact, anchor
            for receipt in capture.files:
                self.codes._admit_trace(Path(receipt.path), receipt.raw_bytes, receipt.raw_sha256)
            for metadata in capture.metadata:
                for receipt in (metadata.probe_source, metadata.probe_binary):
                    self.codes._admit_trace(Path(receipt.path), receipt.bytes, receipt.sha256)
        self.check()

    def _inventory(self):
        return tuple(sorted(p.name for p in self.directory.iterdir()
            if p.name.startswith(('native-callable-meta.', 'native-callables.'))))

    def check(self):
        if self._inventory() != self.inventory:
            raise ValueError('native callable companion inventory changed within the original index')
        self.codes._check_trace()

    def basis(self):
        self.check()
        if self.capture is None: return dict(status='NOT_RECORDED')
        return dict(status='RECORDED', run_scope=self.capture.run_scope,
            metadata=encode(self.capture.metadata), files=encode(self.capture.files))


def _native(index):
    materials = getattr(index, '_source_boundary_native_inputs', None)
    if materials is None:
        materials = _NativeInputs(index)
        index._source_boundary_native_inputs = materials
    materials.check()
    return materials


def _basis(index):
    index.check(); codes = index.codes; native = _native(index)
    # Trace readers verified these original streams once; do not copy payloads.
    streams = [dict(path=str(path), bytes=size, sha256=digest)
        for path, (_, _, size, digest) in sorted(codes._trace_guard.items())]
    streams.extend(encode(_artifact(p, 'scar.python-call-target-meta')) for p in codes._target_metas)
    return dict(catalog=encode(_artifact(index.view.catalog.path/'result.json', index.view.catalog.report['schema'])),
        trace=codes.trace.directory, project_root=codes.trace.project_root,
        run_scope=codes.targets.source_sha256, trace_inputs=streams,
        code_units=sorted(set(codes._sources) | {row[0] for row in codes.root_callers}),
        compiled_units=[profile.unit for profile in index.compiled],
        target_reader_budget=codes.target_reader_budget, frame_reader_budget=encode(codes.trace.frame_budget),
        native=native.basis())


def _derive(index):
    """Check the original recipe ABI before deriving any interface record."""
    if type(index) is not ObservedSourceCallsiteIndex:
        raise TypeError('boundary projection requires the original checked source call index')
    index.check(); native = _native(index)
    groups = {}; observations = defaultdict(list); contexts = {}; roles = {}
    for observation in index.bindings:
        if observation.target.kind not in _KINDS: continue
        unit = observation.unit; source = index.view.unit(unit); facts = source.facts
        call = facts.calls[observation.query]
        gp = lambda ordinal: source_port(facts, ordinal)
        if (observation.call != index.slicer.fact(facts, 'calls', observation.query)
                or (observation.callee, observation.result) != (gp(call.callee), gp(call.result))):
            raise ValueError('observed boundary changed its original call fact/callee/result')
        template = observation.result.port.template
        key = unit, template
        if key not in contexts:
            contexts[key] = NamespacePlanView(unit, source.material.plans((template,))[template])
        context = contexts[key]; step = context.steps[observation.result.port.owner]
        ins = step.instruction
        if (context.owner(step.region) != observation.owner or context.result(step) != observation.result
                or context.worlds(step) != (gp(call.world), gp(call.result_world))
                or context.value(step.arguments[0]) != observation.callee):
            raise ValueError('observed boundary original scope/result/world ABI differs')
        actual = tuple(context.value(v) for v in step.arguments[1:-1])
        if type(ins) is P.ApplyPythonProtocol and ins.protocol is PythonProtocolKind.CALL_FUNCTION_EX:
            expected = (gp(call.positional_pack),) + (() if call.keyword_pack is None else (gp(call.keyword_pack),))
            valid = call.positional_pack is not None and not call.positional and not call.keywords
        else:
            expected = (*map(gp, call.positional), *(gp(p) for _, p in call.keywords))
            valid = call.positional_pack is call.keyword_pack is None
            if type(ins) is P.ApplyDecorator:
                valid = valid and len(call.positional) == 1 and not call.keywords
            elif type(ins) is P.ApplyLanguageAction and ins.action is P.LanguageActionKind.CALL:
                if unit not in roles: roles[unit] = SyntaxRoleView(index._source_syntax(unit))
                _, args = roles[unit].locate(ins.selectors[0])
                _, keywords = roles[unit].locate(ins.selectors[1])
                names = tuple(roles[unit].field(v.reference, 'arg').scalar.to_python() for v in keywords.items)
                valid = valid and len(call.positional) == len(args.items) and tuple(n for n, _ in call.keywords) == names
            else: valid = False
        if not valid or actual != tuple(expected):
            raise ValueError('observed boundary positional/keyword/pack ABI differs from the original recipe')
        identity = ProviderID(_digest((SCHEMA, source.basis, observation.call, observation.target.kind)))
        record = R.SourceObservedBoundary(identity, unit, observation.query, observation.call, observation.owner,
            observation.target.kind, gp(call.callee), tuple(map(gp, call.positional)),
            tuple((name, gp(p)) for name, p in call.keywords),
            None if call.positional_pack is None else gp(call.positional_pack),
            None if call.keyword_pack is None else gp(call.keyword_pack),
            gp(call.world), gp(call.result), gp(call.result_world))
        if groups.setdefault(identity, record) != record:
            raise ValueError('shared source boundary identity has conflicting original interfaces')
        companion = native.facts.get((observation.target.caller.process_id, observation.target.attempt_index))
        if native.capture is not None and (companion is None
                or companion[0].caller != observation.target.caller
                or companion[0].callable_reference != observation.target.callable_reference):
            raise ValueError('native observation changed the original caller/attempt/callable token')
        observations[unit].append(R.SourceBoundaryObservation(identity, observation.id, observation.attempt.anchor,
            observation.target, observation.target_anchor, observation.profile_alternatives,
            None if companion is None else companion[0], None if companion is None else companion[1]))
    records = defaultdict(list)
    for record in groups.values(): records[record.unit].append(record)
    index.check()
    return {unit: (tuple(records[unit]), tuple(observations[unit])) for unit in sorted(records)}


def _callbacks(index, units):
    """Associate same-thread direct frames with their actual enclosing CALL.

    The interval ends at the next CALL in that caller or the caller's exit.
    No function name, receiver address, normal return value or constructor
    stage participates in this selection.
    """
    calls=defaultdict(list); exits=defaultdict(list); by_code=defaultdict(list)
    for attempt in index.codes.trace.attempts:calls[attempt.invocation].append(attempt)
    intervals={key:(tuple(a.frame_index for a in rows),tuple(rows)) for key,rows in calls.items()}
    for exit_ in index.codes.trace.exits:exits[exit_.invocation].append(exit_)
    captures={(c.process_id,c.code.key):c for c in index.codes.trace.frame_scan.captures}
    for code in index.codes.records.values():
        for capture in code.captures:by_code[capture.process_id,capture.code.key].append(code)
    selected={(o.target.caller,o.target.attempt_index):(unit,o) for unit,(_,rows) in units.items() for o in rows}
    records=defaultdict(dict); observed=defaultdict(list)
    for frame in index.codes.trace.entries:
        caller=frame.caller_invocation
        if (caller is None or not frame.path_complete or len(frame.path)!=1
                or frame.caller!=frame.path[0]
                or (caller.process_id,caller.thread_id)!=(frame.invocation.process_id,frame.invocation.thread_id)):
            continue
        positions,attempts=intervals.get(caller,((),()))
        ordinal=bisect_left(positions,frame.anchor.index)-1
        if ordinal<0:continue
        attempt=attempts[ordinal]
        found=selected.get((caller,attempt.index))
        if found is None or frame.caller!=attempt.site:continue
        unit,source=found
        upper=attempts[ordinal+1].frame_index if ordinal+1<len(attempts) else None
        caller_exits=exits.get(caller,())
        if len(caller_exits)==1:
            limit=caller_exits[0].anchor.index
            upper=limit if upper is None else min(upper,limit)
        if upper is not None and frame.anchor.index>upper:continue
        endings=exits.get(frame.invocation,())
        exit_anchor=(endings[0].anchor if len(endings)==1 and endings[0].code==frame.code
            and endings[0].anchor.index>frame.anchor.index
            and (upper is None or endings[0].anchor.index<=upper) else None)
        capture=captures[frame.invocation.process_id,frame.code]
        if frame.suspended!=bool(capture.code.flags&(0x20|0x80|0x200)):
            raise ValueError('callback suspendable flag differs from its captured code')
        candidates=by_code.get((frame.invocation.process_id,frame.code),()) or (None,)
        for code in candidates:
            body=None if code is None else code.body
            identity=ProviderID(_digest((SCHEMA+'.callback',source.boundary,capture.code.key,body)))
            function=None
            if code is not None:
                facts,local=index.slicer.local(code.function)
                function=next(f for f in facts.functions if f.value==local)
                if function.body_scope!=code.scope:raise ValueError('callback source body scope differs')
            gp=lambda p: source_port(facts,p)
            record=R.SourceBoundaryCallback(identity,source.boundary,capture.code,frame.suspended,body,
                None if code is None else code.function_fact,None if code is None else code.scope,
                () if function is None else tuple(gp(p) for p in function.formals),
                None if function is None or function.returns is None else gp(function.returns),
                None if function is None or function.return_world is None else gp(function.return_world))
            if records[unit].setdefault(identity,record)!=record:raise ValueError('shared callback identity conflict')
            observed[unit].append(R.SourceCallbackObservation(identity,source.source_observation,
                frame.invocation,frame.anchor,exit_anchor,capture.anchor))
    index.check()
    return {unit:(tuple(records[unit].values()),tuple(observed[unit])) for unit in units}


def _counts(units,callbacks):
    return dict(units=len(units),boundaries=sum(len(b) for b,_ in units.values()),
        observations=sum(len(o) for _,o in units.values()),
        kinds=dict(Counter(b.target_kind.value for rows,_ in units.values() for b in rows)),
        callbacks=sum(len(c) for c,_ in callbacks.values()),
        callback_observations=sum(len(o) for _,o in callbacks.values()),
        source_callback_interfaces=sum(c.body is not None for rows,_ in callbacks.values() for c in rows),
        source_callback_observations=sum(sum(o.callback in {c.id for c in rows if c.body is not None}
            for o in observations) for rows,observations in callbacks.values()))


def build_boundaries(index, out):
    """Publish per-unit shared signatures and separate original observations."""
    out = Path(out).absolute()
    if out.resolve() != out or out.exists(): raise ValueError('fresh canonical boundary output required')
    basis, pins = _basis(index), _pins(); units = _derive(index); callbacks=_callbacks(index,units); shards = {}
    _durable_mkdir(out)
    for unit, (boundaries, observations) in units.items():
        folder = out/'units'/unit; _durable_mkdir(folder)
        tables = dict(boundaries=write_table(folder/'boundaries.jsonl.gz', boundaries),
            observations=write_table(folder/'observations.jsonl.gz', observations),
            callbacks=write_table(folder/'callbacks.jsonl.gz',callbacks[unit][0]),
            callback_observations=write_table(folder/'callback_observations.jsonl.gz',callbacks[unit][1]))
        shards[unit] = dict(path='units/'+unit, tables=tables,
            boundaries=len(boundaries), observations=len(observations))
    report = dict(schema=SCHEMA, schema_version=2, basis=basis, pins=pins, shards=shards,
        counts=_counts(units,callbacks),
        **{name:False for name in _FALSE})
    if _basis(index) != basis or _pins() != pins: raise ValueError('boundary producer or original inputs changed')
    _durable_bytes(out/'result.json', _json(report), replace=False)
    return report


class BoundaryStore:
    def __init__(self, path, index=None):
        self.path = Path(path).absolute(); self.raw = (self.path/'result.json').read_bytes()
        self.report = r = json.loads(self.raw)
        if (r['schema'], r['schema_version'], r['pins']) != (SCHEMA, 2, _pins()) or any(r[n] is not False for n in _FALSE):
            raise ValueError('boundary schema, producer or proof contract differs')
        basis = r['basis']
        if index is None:
            from scar.analysis.source_observed_codes import ObservedSourceCodeProvider
            from scar.analysis.source_compiled_code_profiles import CompiledCodeProfiles
            view = ProgramView(Path(basis['catalog']['uri']).parent)
            profiles = tuple(CompiledCodeProfiles(view.catalog, u) for u in basis['compiled_units'])
            codes = ObservedSourceCodeProvider(view, basis['trace'], basis['project_root'],
                units=basis['code_units'], compiled=profiles,
                frame_budget=decode(CallEdgeBudget, basis['frame_reader_budget']), **basis['target_reader_budget'])
            index = ObservedSourceCallsiteIndex(codes, compiled=profiles)
        if _basis(index) != basis: raise ValueError('boundary index does not match the original catalog/trace/run/budgets')
        self.index = index; self.catalog = index.view.catalog
        expected = _derive(index); callbacks=_callbacks(index,expected); self.units = {}; self._tables = {}
        if set(expected) != set(r['shards']): raise ValueError('boundary unit selection differs from the original call index')
        for unit, records in expected.items():
            s = r['shards'][unit]; folder = self.path/s['path']
            names=('boundaries','observations','callbacks','callback_observations')
            if s['path'] != 'units/'+unit or set(s['tables']) != set(names):
                raise ValueError('boundary original shard layout differs')
            loaded = []
            for name, kind in zip(names,(R.SourceObservedBoundary,R.SourceBoundaryObservation,
                    R.SourceBoundaryCallback,R.SourceCallbackObservation)):
                receipt = s['tables'][name]; table = folder/receipt['path']; before = _stamp(table)
                if receipt['path'] != name+'.jsonl.gz': raise ValueError('boundary table left its original shard')
                loaded.append(tuple(decode(kind, row, record_tags=P.PRODUCTION_RECORD_TAGS) for row in _table(folder, receipt)))
                if _stamp(table) != before: raise ValueError('boundary table changed during reading')
                self._tables[table] = before
            if tuple(loaded) != (*records,*callbacks[unit]) or (s['boundaries'], s['observations']) != tuple(map(len, records)):
                raise ValueError('stored boundary signature/observations differ from original CALL evidence')
            self.units[unit] = SimpleNamespace(**dict(zip(names,loaded)))
        counts = _counts(expected,callbacks)
        if counts != r['counts']: raise ValueError('boundary shared/observed counts differ')
        self.validate()

    def validate(self):
        if self.raw != (self.path/'result.json').read_bytes() or self.report['pins'] != _pins():
            raise ValueError('boundary publication or rules changed')
        if any(_stamp(p) != before for p, before in self._tables.items()): raise ValueError('boundary table changed')
        _native(self.index).check()
        self.index.check()

    def read_unit(self, unit):
        self.validate(); return self.units[unit]


class SourceObservedBoundaryProvider:
    relation_kinds = frozenset((K.CONTAINS,K.ARGUMENT,K.STATE_INTERFACE,K.COMPLETION,
        K.CALL_TARGET,K.IMPLEMENTATION,K.ENVIRONMENT,K.PROJECTION))

    def __init__(self, view, store, *, units=()):
        self.view = view; self.store = store if isinstance(store, BoundaryStore) else BoundaryStore(store)
        if (view.catalog.path, view.catalog.report) != (self.store.catalog.path, self.store.catalog.report):
            raise ValueError('boundary provider requires the same original source catalog')
        self.available_units = frozenset(self.store.units); self.attached = set()
        self.records = {}; self.owners = {}; self.observations = defaultdict(list)
        self.in_edges = defaultdict(list); self.out_edges = defaultdict(list)
        self.callbacks={};self.callback_owners={};self.callback_frames={}
        self.callback_observations=defaultdict(list);self.callback_targets=defaultdict(set)
        self.callback_in=defaultdict(list);self.callback_out=defaultdict(list)
        for unit,rows in self.store.units.items():
            for callback in rows.callbacks:
                if callback.body is not None:self.callback_targets[callback.body.unit].add(unit)
        artifact = _artifact(self.store.path/'result.json', SCHEMA)
        self.locator = SourceArtifactLocator(artifact, artifact.sha256, artifact.size_bytes, 'canonical-json')
        for unit in units: self.attach(unit)
        view.register(self)

    @staticmethod
    def _key(point): return point.namespace, point.node

    def attach(self, unit):
        if unit in self.attached: return
        rows = self.store.read_unit(unit); ports = []
        for b in rows.boundaries: ports.extend(self._ports(b))
        prepare_source_ports(self.view, ports)
        for i, b in enumerate(rows.boundaries):
            operation, _, _ = source_call_site(self.view, b)
            point = Point(operation.namespace, b.id, None); key = self._key(point)
            self.records[key] = b; self.owners[key] = operation
            evidence = _table_ref(self.store.path/self.store.report['shards'][unit]['path'],
                self.store.report['shards'][unit]['tables']['boundaries'], SCHEMA+'.interface', i)
            edges = [(operation, point, K.CONTAINS, Meaning.STRUCTURE, 'DECLARED_INTERFACE', 0)]
            inputs = (b.callee, *b.positional, *(p for _, p in b.keywords),
                *((b.positional_pack,) if b.positional_pack else ()), *((b.keyword_pack,) if b.keyword_pack else ()))
            edges.extend((self.view.source_port(p), point, K.ARGUMENT, Meaning.DEPENDENCE, 'PYTHON_SIDE_INPUT', n)
                for n, p in enumerate(inputs))
            edges.extend(((self.view.source_port(b.world), point, K.STATE_INTERFACE, Meaning.STATE_INTERFACE, 'PRE_CALL_WORLD', 0),
                (point, self.view.source_port(b.result), K.COMPLETION, Meaning.DEPENDENCE, 'NORMAL_COMPLETION_NOT_OBSERVED', 0),
                (point, self.view.source_port(b.result_world), K.STATE_INTERFACE, Meaning.STATE_INTERFACE, 'NORMAL_COMPLETION_NOT_OBSERVED', 1)))
            for edge in edges:
                row = b, evidence, edge
                self.out_edges[self._key(edge[0])].append(row); self.in_edges[self._key(edge[1])].append(row)
        for observation in rows.observations: self.observations[observation.boundary].append(observation)
        self.attached.add(unit)
        for i,callback in enumerate(rows.callbacks):self._attach_callback(unit,i,callback)
        for observation in rows.callback_observations:self.callback_observations[observation.callback].append(observation)

    def _attach_callback(self,unit,ordinal,callback):
        source=self.view.unit(unit);key=source.namespace,callback.boundary
        boundary=self.records[key];parent=Point(source.namespace,callback.boundary,None)
        point=Point(source.namespace,callback.id,None);self.callbacks[self._key(point)]=callback
        self.callback_owners[self._key(point)]=parent
        shard=self.store.report['shards'][unit]
        fact=_table_ref(self.store.path/shard['path'],shard['tables']['callbacks'],SCHEMA+'.callback',ordinal)
        edge=(parent,point,K.CONTAINS,Meaning.STRUCTURE,'RECORDED_CALLBACK_CODE',ordinal)
        row=boundary,fact,edge
        self.out_edges[self._key(parent)].append(row);self.in_edges[self._key(point)].append(row)
        if callback.body is None:return
        body=callback.body
        target=self.view.source_region_ref(body.unit,body.template,body.region)
        frame=None if callback.suspending else Frame(source.namespace,self.owners[key].node,None,None,
            target.namespace,entry=target.node,selection=fact)
        if frame is not None:self.callback_frames[self._key(point)]=frame
        def relation(left,right,kind,meaning,flow,rule):
            item=boundary,callback,fact,left,right,frame,flow,kind,meaning,rule
            self.callback_out[self._key(left)].append(item);self.callback_in[self._key(right)].append(item)
        if callback.suspending:
            # flags establish a suspendable code template, not an instance,
            # start/resume PC or a fresh binding of its saved arguments.
            relation(point,target,K.IMPLEMENTATION,Meaning.STRUCTURE,None,'SUSPENDABLE_BODY_TEMPLATE_NOT_RESUME_POSITION')
            return
        relation(point,target,K.CALL_TARGET,Meaning.DEPENDENCE,'ENTER','RECORDED_ORDINARY_CALLBACK_BODY')
        prepare_source_ports(self.view,callback.formals,
            bodies=(callback.body,))
        for i,formal in enumerate(callback.formals):
            target=self.view.source_port(formal)
            kind=K.ENVIRONMENT if i==0 else K.STATE_INTERFACE if i==len(callback.formals)-1 else K.PROJECTION
            meaning=Meaning.STATE_INTERFACE if kind is K.STATE_INTERFACE else Meaning.DEPENDENCE
            relation(point,target,kind,meaning,'ENTER','CALLBACK_INPUT_PROJECTION_ORIGIN_NOT_SELECTED')
        for port,kind in ((callback.result,K.PROJECTION),(callback.result_world,K.STATE_INTERFACE)):
            if port is not None:
                relation(self.view.source_port(port),parent,kind,
                    Meaning.STATE_INTERFACE if kind is K.STATE_INTERFACE else Meaning.DEPENDENCE,
                    'RETURN','CALLBACK_RETURN_TO_DISPATCHER_NOT_OUTER_RESULT_ALIAS')

    @staticmethod
    def _ports(b):
        return (b.callee, *b.positional, *(p for _, p in b.keywords),
            *((b.positional_pack,) if b.positional_pack else ()), *((b.keyword_pack,) if b.keyword_pack else ()),
            b.world, b.result, b.result_world)

    def _demand(self, point):
        source = self.view.namespaces.get(point.namespace)
        if source is not None:
            if source.unit in self.available_units:self.attach(source.unit)
            for caller in sorted(self.callback_targets.get(source.unit,())):self.attach(caller)

    def describe(self, point):
        self._demand(point); key = self._key(point)
        if key in self.callbacks:
            self.store.validate()
            return V.ProgramNode(point,None,V.ProgramNodeRole.PROVIDER,
                replace(self.callback_owners[key],context=point.context),None)
        if key not in self.records: return None
        self.store.validate(); b = self.records[key]
        role = V.ProgramNodeRole.NATIVE_BOUNDARY if b.target_kind in (Target.NATIVE_BUILTIN, Target.NATIVE_WRAPPER) else V.ProgramNodeRole.PROVIDER
        return V.ProgramNode(point, None, role, replace(self.owners[key], context=point.context), None)

    def original(self, point):
        if self.describe(point) is None: raise ValueError('boundary is outside the original source interface publication')
        key=self._key(point)
        return self.callbacks[key] if key in self.callbacks else self.records[key]

    def expand(self, point):
        b = self.original(point)
        if type(b) is R.SourceBoundaryCallback:
            if b.body is None:return ()
            target=self.view.source_region_ref(b.body.unit,b.body.template,b.body.region)
            frame=self.callback_frames.get(self._key(point))
            return (replace(target,context=None if frame is None else context_push(point.context,frame)),)
        children=(Point(point.namespace,c.id,point.context) for c in self.callbacks.values() if c.boundary==b.id)
        return tuple(dict.fromkeys((*tuple(self.view.source_port(p,context=point.context) for p in self._ports(b)),*children)))

    def explain(self, point):
        b = self.original(point)
        if type(b) is R.SourceBoundaryCallback:
            return dict(node=self.describe(point),original=b,observations=tuple(self.callback_observations[b.id]),
                entry_kind='SUSPENDABLE_BODY_ENTRY' if b.suspending else 'ORDINARY_FRAME_ENTRY',
                source_body_available=b.body is not None,argument_origins_proven=False,
                resume_position_proven=False,generator_instance_proven=False,
                callback_result_is_outer_call_result=False,first_stage_complete=False)
        return dict(node=self.describe(point), original=b, observations=tuple(self.observations[b.id]),
            native_formals_proven=False, construction_stages_proven=False, normal_completion_proven=False,
            effects=b.effects.value, source_bodies_copied=False, first_stage_complete=False)

    def _neighbors(self, point, incoming):
        self._demand(point); self.store.validate()
        rows = (self.in_edges if incoming else self.out_edges).get(self._key(point), ())
        callback_rows=(self.callback_in if incoming else self.callback_out).get(self._key(point),())
        if not rows and not callback_rows:return Neighborhood()
        active = source_active_scope(self.view, point.namespace, point.context); edges = []
        for b, evidence, (source, target, kind, meaning, route, ordinal) in rows:
            if active is not None and active != b.owner.owner: continue
            source, target = replace(source, context=point.context), replace(target, context=point.context)
            owner = replace(self.owners[source.namespace, b.id], context=point.context)
            guards = ('RECORDED_DISPATCH_OPERAND_NOT_IMPLEMENTATION_ENTRY',
                'CURRENT_CALLABLE_AND_TARGET_KIND_SELECTION_NOT_PROVEN', 'EFFECTS_AND_OBJECT_CONTENTS_UNKNOWN',
                'PYTHON_SIDE_INTERFACE_NOT_NATIVE_FORMAL', route)
            if b.target_kind is Target.TYPE_OBJECT: guards += ('TYPE_OBJECT_NOT_STANDARD_CONSTRUCTION_STAGE',)
            if b.target_kind is Target.OTHER_UNCLASSIFIED: guards += ('CALLABLE_PROTOCOL_NOT_IDENTIFIED',)
            conditions = tuple(Condition(SCHEMA, guard, owner, ordinal, (source, target)) for guard in guards)
            edges.append(Edge(source, target, kind, meaning,
                (Evidence(SCHEMA+'.original-call-interface.v1', (self.locator, point.namespace.graph), (owner, source, target)),),
                conditions, Strength.MAY))
        callback=self._callback_neighbors(point,incoming)
        edges.extend(callback.edges)
        frontiers = () if not edges else (Frontier(point, 'OBSERVED_CALL_IMPLEMENTATION_AND_EFFECTS_OPEN',
            'Python-side CALL ports and recorded target categories are connected; no native body, type-call stage or completion is proven.'),)
        return Neighborhood(tuple(dict.fromkeys(edges)),(*frontiers,*callback.frontiers))

    def _callback_neighbors(self,point,incoming):
        rows=(self.callback_in if incoming else self.callback_out).get(self._key(point),())
        edges=[];frontiers=[]
        for boundary,callback,fact,left,right,frame,flow,kind,meaning,rule in rows:
            if frame is None:
                caller_context=None if incoming else point.context
                left=replace(left,context=caller_context);right=replace(right,context=None)
                if incoming and point.context is not None:continue
            else:
                pop=(incoming and flow=='ENTER') or (not incoming and flow=='RETURN')
                if pop:
                    selected=context_pop(point.context,(frame,))
                    if not selected.matched:continue
                    caller_context,callee_context=selected.remaining,point.context
                else:
                    caller_context=point.context;callee_context=context_push(caller_context,frame)
                left=replace(left,context=caller_context if flow=='ENTER' else callee_context)
                right=replace(right,context=callee_context if flow=='ENTER' else caller_context)
            caller=self.view.source_port(boundary.result).namespace
            active=source_active_scope(self.view,caller,caller_context)
            if active is not None and active!=boundary.owner.owner:continue
            owner=replace(self.owners[caller,boundary.id],context=caller_context)
            guards=('OBSERVED_DIRECT_CALLBACK_CALL_INTERVAL',
                'SOURCE_BODY_CORRESPONDENCE_NOT_CALLABLE_ENVIRONMENT_IDENTITY',
                'CALLBACK_ARGUMENT_PROJECTION_AND_NATIVE_INTERNAL_EFFECTS_OPEN',rule)
            conditions=tuple(Condition(SCHEMA,name,owner,operands=(left,right)) for name in guards)
            edges.append(Edge(left,right,kind,meaning,
                (Evidence(SCHEMA+'.callback-interface.v1',(self.locator,caller.graph,right.namespace.graph),
                    (owner,left,right)),),conditions,Strength.MAY))
            if callback.suspending:
                frontiers.append(Frontier(point,'CALLBACK_GENERATOR_INSTANCE_AND_RESUME_POSITION_NOT_RECORDED',
                    'The observed suspendable code body is linked structurally; saved inputs and the actual resume ingress remain open.'))
        return Neighborhood(tuple(dict.fromkeys(edges)),tuple(dict.fromkeys(frontiers)))

    def incoming(self, point): return self._neighbors(point, True)
    def outgoing(self, point): return self._neighbors(point, False)

    def summary(self):
        return dict(**self.store.report['counts'], attached_units=len(self.attached), shared_interfaces=len(self.records),
            shared_callback_interfaces=len(self.callbacks),
            target_kind_observations_connected=True, **{name:False for name in _FALSE})
