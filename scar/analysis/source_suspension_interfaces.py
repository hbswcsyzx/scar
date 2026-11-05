"""Lazy source interfaces for iteration and deferred bodies.

Ports are projections of sealed ProductionStep/Region signatures. Some state
ports deliberately have no entry in the sparse F5 table; they remain original
G.Ports with a plan witness, never synthesized source operations. No body is
activated here and no target code is imported or executed.
"""
from dataclasses import fields, is_dataclass
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from scar.analysis.normal_graph import _Emitter
from scar.analysis.source_productions import _digest, production_plan_document
from scar.analysis.source_template_links import read_template_graph, _worker_stores
from scar.ir.program import normal_graph as G, normal_links as F, source_productions as P
from scar.ir.program import suspension_interfaces as I
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.program.normal_targets import GlobalPort
from scar.ir.record_codec import decode, encode


def _state_indices(types):
    return tuple(i for i, value in enumerate(types) if type(value) is ValueType and value.kind is ValueKind.STATE)


def _stamp(path):
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


class SuspensionInterfaceIndex:
    """A per-query cache over selected units, with an explicit fixture mode.

    ``plan_reader(unit_id, template_key)`` may supply controlled in-memory
    plans. Its witnesses say CONTROLLED_PLAN_PROVIDER and carry no fabricated
    store receipt. With no provider, a receipt-bound SourceFactStore is required.
    """
    def __init__(self, fact_store=None, *, plan_reader=None, jobs=None):
        if fact_store is None and plan_reader is None:
            raise ValueError('suspension interfaces require a fact store or controlled plan provider')
        if jobs is not None and (type(jobs) is not int or jobs < 1):
            raise ValueError('plan reader jobs must be a positive exact integer')
        self.store, self.plan_reader = fact_store, plan_reader
        self._plans, self._ports, self._headers, self._graphs = {}, {}, {}, {}
        self._suspending, self._bodies, self._iterations = {}, {}, {}
        self._iteration_candidates = {}
        self._pins = {}
        self._materials_pinned = set()
        self._material_reports, self._body_functions = {}, {}
        self._jobs, self._pool = jobs, None
        self._stats = dict(plan_hits=0,plan_reads=0,prefetch_batches=0,prefetched_plans=0,
            iteration_hits=0,iteration_reads=0,body_hits=0,body_reads=0,
            material_report_reads=0,material_report_hits=0,material_report_seconds=0.0,
            parent_checks=0,parent_paths_checked=0,parent_check_seconds=0.0,
            prefetch_seconds=0.0,plan_read_seconds=0.0,discovery_units=0,discovery_seconds=0.0)

    @property
    def stats(self):
        return dict(self._stats, cached_plans=len(self._plans),cached_bodies=len(self._bodies),
            cached_iterations=len(self._iterations),pinned_paths=len(self._pins),
            plan_pool={} if self._pool is None else dict(self._pool.stats))

    def close(self):
        """Release workers; the publisher separately seals parent validation."""
        if self._pool is not None:self._pool.close()

    def _unit(self, unit):
        if type(unit) is str:
            if self.store is None:raise ValueError('controlled provider requires its original unit facts')
            unit = self.store.load(unit)
        if self.store is not None and unit.unit not in self.store.rows:
            raise ValueError('interface unit is outside its source fact catalog')
        return unit

    def _pin(self, path):
        path = Path(path)
        stamp = _stamp(path)
        if path in self._pins and self._pins[path] != stamp:
            raise ValueError('an original interface parent changed during the query')
        self._pins[path] = stamp

    def validate_parents(self):
        """Recheck the retained proof footprint before/after publication.

        Cached typed values belong to this query's pinned snapshot. Hot-path
        reuse does no filesystem work; consumers must call this gate around
        publication so a changed parent cannot be reported as accepted.
        """
        started = perf_counter();checked = 0
        self._stats['parent_checks'] += 1
        try:
            for path, stamp in self._pins.items():
                checked += 1
                if _stamp(path) != stamp:
                    raise ValueError('an original interface parent changed during the query')
        finally:
            self._stats['parent_paths_checked'] += checked
            self._stats['parent_check_seconds'] += perf_counter() - started
        return checked

    def _header(self, unit):
        if unit.unit not in self._headers:
            self.validate_parents()
            parent = self.store
            while parent.parents:
                parent = parent.parents[parent.unit_parent[unit.unit]]
            if (parent.path / 'result.json').read_bytes() != parent.raw:
                raise ValueError('source fact receipt changed before interface extraction')
            row = parent.rows[unit.unit]
            fact_path = parent.path / row['facts']
            fact_raw = fact_path.read_bytes()
            if len(fact_raw) != row['bytes'] or sha256(fact_raw).hexdigest() != row['sha256']:
                raise ValueError('source fact fragment changed before interface extraction')
            self._pin(fact_path)
            root = Path(parent.templates)
            raw = (root / 'result.json').read_bytes()
            if sha256(raw).hexdigest() != parent.report['source_result_sha256']:
                raise ValueError('suspension template parent differs from its F5 receipt')
            model_raw = (parent.model / 'manifest.json').read_bytes()
            if sha256(model_raw).hexdigest() != parent.report['model_manifest_sha256']:
                raise ValueError('suspension source model differs from its F5 receipt')
            report = json.loads(raw)
            self._headers[unit.unit] = root, report, sha256(raw).hexdigest()
            for path in (root / 'result.json', parent.model / 'manifest.json', parent.path / 'result.json'):
                self._pin(path)
            graph = read_template_graph(root, unit.unit)
            self._graphs[unit.unit] = {node.key: node for node in graph.templates}
            row = next(row for row in report['units'] if row['unit'] == unit.unit)
            header_path = root / row['header']
            self._pin(header_path)
            header = json.loads(header_path.read_bytes())
            for table in ('templates', 'links'):
                self._pin(header_path.parent / header[table]['path'])
            self.validate_parents()
        return self._headers[unit.unit]

    def _accept_plan(self, unit, key, plan, digest, source, receipt, model):
        if (type(plan) is not P.SourceProductionPlan or type(plan.source) is not P.ProductionOccurrence
                or plan.source.occurrence != key.occurrence or plan.purpose is not key.purpose
                or plan.compilation_flow is None):
            raise ValueError('deferred interface plan has another original source/context')
        self._plans[unit.unit,key] = plan, digest, source, receipt, model

    def _plan(self, unit, key):
        cache = unit.unit, key
        if cache in self._plans:
            self._stats['plan_hits'] += 1
        else:
            self._stats['plan_reads'] += 1
            started = perf_counter()
            if self.plan_reader is not None:
                plan = self.plan_reader(unit.unit, key)
                digest = _digest(production_plan_document(plan))
                source = I.WitnessSource.CONTROLLED_PLAN_PROVIDER
                receipt = model = None
            else:
                self._prefetch(unit,(key,))
                self._stats['plan_read_seconds'] += perf_counter() - started
                return self._plans[cache]
            self._accept_plan(unit,key,plan,digest,source,receipt,model)
            self._stats['plan_read_seconds'] += perf_counter() - started
        return self._plans[cache]

    def _prefetch(self, unit, keys):
        missing = tuple(sorted((key for key in keys if (unit.unit,key) not in self._plans),
                               key=lambda key:(key.occurrence,key.purpose.value)))
        if not missing:return
        if self.plan_reader is not None:
            for key in missing:self._plan(unit,key)
            return
        from scar.analysis.source_template_workers import TemplatePlanPool
        root, report, receipt = self._header(unit)
        self.validate_parents()
        if self._pool is None:self._pool = TemplatePlanPool(jobs=self._jobs)
        started = perf_counter()
        plans = self._pool.read_many(root,unit.unit,missing,expected_root_sha256=receipt)
        self._stats['prefetch_seconds'] += perf_counter() - started
        self._stats['prefetch_batches'] += 1
        if set(plans) != set(missing):raise ValueError('parallel source plan selection differs')
        for key in missing:
            digest = self._graphs[unit.unit][key].origin.plan_sha256
            # Worker readers perform the original complete admission. Rehash
            # the transported DTO as well, without replaying that admission.
            if _digest(encode(plans[key],record_tags=P.PRODUCTION_RECORD_TAGS)) != digest:
                raise ValueError('parallel source plan differs from its original digest')
            self._accept_plan(unit,key,plans[key],digest,I.WitnessSource.SEALED_TEMPLATE_STORE,
                              receipt,report['model_manifest_sha256'])
        self._stats['prefetched_plans'] += len(missing)
        self._pin_materials(unit)
        self.validate_parents()

    def _pin_materials(self, unit):
        if unit.unit in self._materials_pinned:
            return
        root, report, _ = self._header(unit)
        for parent in report['parents']:
            material, verification = Path(parent['materials']), Path(parent['verification'])
            for path in (material / 'result.json', verification / 'result.json',
                         material / 'catalog.json', verification / 'catalog.json'):
                self._pin(path)
            cache = material, parent['collection_sha256']
            if cache not in self._material_reports:
                started = perf_counter()
                raw = (material / 'result.json').read_bytes()
                if sha256(raw).hexdigest() != parent['collection_sha256']:
                    raise ValueError('source material report differs from its selected receipt')
                stored = json.loads(raw)
                rows = {row['unit']:row for row in stored['units']}
                if len(rows) != len(stored['units']):raise ValueError('duplicate source material unit')
                self._material_reports[cache] = rows
                self._stats['material_report_reads'] += 1
                self._stats['material_report_seconds'] += perf_counter() - started
            else:
                self._stats['material_report_hits'] += 1
            row = self._material_reports[cache][unit.unit]
            self._pin(material / row['artifact']['path'])
        self._materials_pinned.add(unit.unit)

    def _port(self, unit, index):
        if type(index) is not int or not 0 <= index < len(unit.ports):
            raise ValueError('interface port is outside the original F5 table')
        cache = unit.unit, index
        if cache not in self._ports:
            raw = unit.ports[index]
            port = decode(G.Port, raw, record_tags=P.PRODUCTION_RECORD_TAGS) if type(raw) is dict else raw
            if type(port) is not G.Port:raise ValueError('interface needs an original graph port')
            self._ports[cache] = GlobalPort(unit.unit, port)
        return self._ports[cache]

    def _witness(self, unit, key, step):
        plan, digest, source, receipt, model = self._plan(unit, key)
        context = next(port for port in plan.compilation_flow.ports if port.region == step.region)
        return I.StepWitness(unit.unit, key, digest, step.id, step.region,
            F.CodeScopeRef(unit.unit, context.code_scope), source, receipt, model)

    @staticmethod
    def _completion(unit, emitter, owner, completion):
        ports = tuple(GlobalPort(unit.unit, emitter.port(owner, G.PortKind.RESULT, i, completion))
                      for i in range(len(completion.types)))
        states = _state_indices(completion.types)
        if len(states) > 1:raise ValueError('completion has multiple current-world ports')
        return I.CompletionPorts(completion.kind, completion.target, ports, ports[states[0]] if states else None)

    def iteration(self, unit, item):
        unit = self._unit(unit)
        if type(item) is not F.Iteration:
            raise ValueError('iteration must come from the original unit facts')
        cache = unit.unit, item
        if cache in self._iterations:
            self._stats['iteration_hits'] += 1
        else:
            if item not in unit.iterations:raise ValueError('iteration must come from the original unit facts')
            self._stats['iteration_reads'] += 1
            value = self._port(unit, item.value)
            if self.plan_reader is None and (unit.unit,value.port.template) not in self._plans:
                pending = sorted((key for key in self._iteration_candidates.get(unit.unit,())
                    if key!=value.port.template and (unit.unit,key) not in self._plans),
                    key=lambda key:(key.occurrence,key.purpose.value))
                self._prefetch(unit,(value.port.template,*pending[:63]))
            plan = self._plan(unit, value.port.template)[0]
            emitter = _Emitter(plan, value.port.template, {})
            step = emitter.steps.get(value.port.owner)
            from scar.ir.program.structured import PythonProtocolKind as K
            if step is None or type(step.instruction) is not P.ApplyPythonProtocol:
                raise ValueError('iteration result is not an original Python protocol step')
            protocol = step.instruction.protocol
            if (protocol not in (K.GET_ITERATOR, K.ADVANCE_ITERATOR, K.COMPREHENSION_NEXT)
                    or item.advance != (protocol is not K.GET_ITERATOR)):
                raise ValueError('iteration fact disagrees with its original protocol')
            source = GlobalPort(unit.unit, emitter.value(step.arguments[0])[0])
            completions = tuple(self._completion(unit, emitter, step.id, c) for c in step.completions)
            normal = next(c for c in completions if c.kind is C.FALLTHROUGH)
            states = [GlobalPort(unit.unit, emitter.value(v)[0]) for v in step.arguments
                      if _state_indices((emitter.value(v)[1],))]
            if (source != self._port(unit, item.source) or normal.ports[0] != value
                    or len(states) != 1 or normal.world is None):
                raise ValueError('iteration input/output/current-world ABI differs from its F5 projection')
            self._iterations[cache] = I.IterationSite(self._witness(unit, value.port.template, step),
                protocol, source, value, states[0], normal.world, completions)
        return self._iterations[cache]

    def register_iterations(self, unit, items):
        """Register admitted scope coordinates without reading or activating plans."""
        unit = self._unit(unit)
        keys = self._iteration_candidates.setdefault(unit.unit,set())
        for item in items:
            if type(item) is not F.Iteration:raise ValueError('expected original iteration facts')
            keys.add(self._port(unit,item.value).port.template)

    def _candidate_templates(self, unit, owner):
        indices = set()
        for group in unit.scope_groups:
            if group.owner != owner:continue
            for span in group.tables:
                for index in range(span.start, span.stop):
                    item = getattr(unit, span.table.value)[index]
                    if span.table is F.FactTable.ALIASES:
                        indices.update(item)
                    elif is_dataclass(item):
                        def collect(value):
                            if type(value) is int:
                                if 0 <= value < len(unit.ports):indices.add(value)
                            elif type(value) is tuple:
                                for member in value:collect(member)
                        # Only these fact fields are source port references;
                        # namespace/scope/enum ordinals are not graph indices.
                        for field in fields(item):
                            if field.name in ('value','receiver','result','world','result_world','callee',
                                    'positional','keywords','positional_pack','keyword_pack','elements','pairs',
                                    'source','target','operands','bases','bases_pack','key'):
                                collect(getattr(item, field.name))
        return {self._port(unit, index).port.template for index in indices}

    def _suspending_templates(self, unit, candidates):
        if self.plan_reader is not None:
            return {key for key in candidates if any(type(s.instruction) is P.SuspendExecution
                    for s in self._plan(unit, key)[0].steps)}
        if unit.unit not in self._suspending:
            started = perf_counter()
            root, report, _ = self._header(unit)
            specs = tuple((p['domain'],p['materials'],p['verification'],p['collection_sha256'],p['verification_sha256'])
                          for p in report['parents'])
            stores = _worker_stores(specs, report['model_manifest_sha256'])
            origins = {(node.origin.domain, node.origin.line): key for key, node in self._graphs[unit.unit].items()}
            found = set()
            discriminator, tag = P.PRODUCTION_RECORD_TAGS[P.SuspendExecution]
            for store in stores:
                basis = store.basis[unit.unit]
                for domain, line, document in store.records(dict(key=unit.unit, **{k:v for k,v in basis.items() if k!='unit'})):
                    if any(s['instruction'].get(discriminator) == tag for s in document['steps']):
                        key = origins.get((domain,line))
                        if key is not None:found.add(key)
            if not all(store.unchanged() for store in stores):
                raise ValueError('suspension parent proof changed during discovery')
            self._pin_materials(unit)
            self._suspending[unit.unit] = found
            self._stats['discovery_units'] += 1
            self._stats['discovery_seconds'] += perf_counter() - started
        return candidates & self._suspending[unit.unit]

    @staticmethod
    def _obligations(kind, suspension=None):
        result = []
        if kind is P.DeferredBodyKind.ASYNC_GENERATOR:result.append(I.DriverObligation.ASYNC_GENERATOR_DRIVER_REQUIRED)
        elif kind is not P.DeferredBodyKind.GENERATOR:result.append(I.DriverObligation.NOT_SYNCHRONOUS_GENERATOR)
        if suspension is P.SuspensionKind.YIELD_FROM:result.append(I.DriverObligation.YIELD_FROM_DRIVER_REQUIRED)
        elif suspension is P.SuspensionKind.AWAIT:result.append(I.DriverObligation.AWAIT_DRIVER_REQUIRED)
        elif suspension is P.SuspensionKind.ASYNC_YIELD and I.DriverObligation.ASYNC_GENERATOR_DRIVER_REQUIRED not in result:
            result.append(I.DriverObligation.ASYNC_GENERATOR_DRIVER_REQUIRED)
        return tuple(result)

    def body(self, unit, function):
        unit = self._unit(unit)
        if type(function) is not F.Function or function.body_scope is None:
            raise ValueError('deferred body requires its original scope-qualified function fact')
        cache = unit.unit, function.value
        if cache in self._bodies:
            original = self._body_functions[cache]
            if function is not original and function != original:
                raise ValueError('function port selects another deferred interface')
            self._stats['body_hits'] += 1
        else:
            if function not in unit.functions:raise ValueError('function is not in its original unit facts')
            self._stats['body_reads'] += 1
            key = function.template
            owner = function.body_scope.owner
            candidates = self._candidate_templates(unit,owner)
            candidates.add(key)
            selected = self._suspending_templates(unit,candidates)
            # Material discovery already confirmed these source templates.
            # Prefetch their interfaces together with this function's root,
            # including other suspensions in this unit, without activating
            # their owners or reading every ordinary expression separately.
            pending = selected | {key} if self.plan_reader is not None else self._suspending[unit.unit] | {key}
            self._prefetch(unit,pending)
            plan = self._plan(unit, key)[0]
            emitter = _Emitter(plan, key, {})
            region = emitter.regions[function.body]
            context = next(p for p in plan.compilation_flow.ports if p.region == region.id)
            if (function.body_scope.owner != F.CodeScopeRef(unit.unit, context.code_scope)
                    or function.body_scope.source_scope != context.source_scope
                    or function.body_scope.template != key or function.body_scope.region != region.id):
                raise ValueError('deferred body scope differs from its original compilation context')
            parameters = tuple(GlobalPort(unit.unit, emitter.port(region.id,G.PortKind.PARAMETER,i))
                               for i in range(len(region.parameters)))
            if parameters != tuple(self._port(unit,i) for i in function.formals):
                raise ValueError('deferred formal ports differ from the F5 function ABI')
            completions = tuple(self._completion(unit,emitter,region.id,c) for c in region.completions)
            entry = [step for step in plan.steps if step.region == region.id
                     and type(step.instruction) is P.EnterDeferredBody]
            if len(entry) != 1 or entry[0].instruction.environment != function.environment:
                raise ValueError('function environment differs from its original deferred-body entry')
            returned = next((c for c in completions if c.kind is C.RETURN),None)
            if ((function.returns is not None and (returned is None
                    or self._port(unit,function.returns) != returned.ports[0]))
                    or (function.return_world is not None and (returned is None
                    or self._port(unit,function.return_world) != returned.world))):
                raise ValueError('function terminal return/world differs from its original body completion')
            suspensions = []
            for candidate in sorted(selected, key=lambda k:(k.occurrence,k.purpose.value)):
                child = self._plan(unit,candidate)[0];child_emitter = _Emitter(child,candidate,{})
                for step in child.steps:
                    ins = step.instruction
                    if type(ins) is not P.SuspendExecution:continue
                    witness = self._witness(unit,candidate,step)
                    if witness.owner != owner:continue
                    operands = tuple(GlobalPort(unit.unit,child_emitter.value(v)[0]) for v in step.arguments)
                    if len(operands)!=2 or not _state_indices((child_emitter.value(step.arguments[1])[1],)):
                        raise ValueError('suspension export must retain its value/current-world ABI')
                    resumes = []
                    for route in ins.routes:
                        resume = child_emitter.regions[route.region]
                        inputs = tuple(GlobalPort(unit.unit,child_emitter.port(resume.id,G.PortKind.PARAMETER,i))
                                       for i in range(len(resume.parameters)))
                        states = _state_indices(resume.parameters)
                        if len(states)!=1:raise ValueError('resume route requires one fresh current-world input')
                        resumes.append(I.ResumeSite(route.kind,resume.id,inputs,inputs[states[0]]))
                    suspensions.append(I.SuspensionSite(witness,ins.suspension,operands[0],operands[1],tuple(resumes),
                        tuple(GlobalPort(unit.unit,child_emitter.value(v)[0]) for v in ins.saved),
                        None if ins.delegate is None else GlobalPort(unit.unit,child_emitter.value(ins.delegate)[0]),
                        tuple(self._completion(unit,child_emitter,step.id,c) for c in step.completions),ins.exception_abi,
                        self._obligations(function.environment.kind,ins.suspension)))
            obligations = tuple(dict.fromkeys((*self._obligations(function.environment.kind),
                *(o for site in suspensions for o in site.obligations))))
            self._bodies[cache] = I.DeferredBodySite(function.body_scope,function.environment.kind,
                self._port(unit,function.value),parameters,completions,tuple(suspensions),obligations)
            self._body_functions[cache] = function
        return self._bodies[cache]


__all__ = ['SuspensionInterfaceIndex']
