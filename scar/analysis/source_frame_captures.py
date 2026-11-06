"""Read original frame globals/callable captures from shared F4 plans.

Source units retain the existing strict sealed reader. Compiled units use
their explicit F4 store and exec receipt; neither path infers a dictionary
identity from a module name or activates source code.
"""
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

from scar.analysis.source_namespace_captures import extract_captures
from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.analysis.source_suspension_interfaces import SuspensionInterfaceIndex
from scar.analysis.source_productions import _digest
from scar.ir.program import source_productions as P, suspension_interfaces as I
from scar.ir.program.model import ValueType,ValueKind
from scar.ir.record_codec import decode


def _stamp(path):
    stat = path.stat()
    return stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns


class FrameCaptureIndex:
    def __init__(self, context_store, exec_graph, jobs=4):
        if context_store.exec_sha256 != sha256((exec_graph.path/'result.json').read_bytes()).hexdigest():
            raise ValueError('frame capture exec parent differs from context facts')
        self.store,self.exec_graph = context_store,exec_graph
        self.base_index = SuspensionInterfaceIndex(context_store.base,jobs=jobs)
        self._source_indices = {id(context_store.base):self.base_index}
        for parent in context_store.supplemental_sources:
            self._source_indices[id(parent)] = SuspensionInterfaceIndex(parent,jobs=jobs)
        self._units,self._pins = {},{}
        self._selected={};self._records={};self._headers={}
        self._connections = {}
        for connection in exec_graph.connections():
            self._connections.setdefault(connection.root.owner.unit,connection)
        self._stats = dict(base_units=0,compiled_units=0,base_templates=0,compiled_templates=0,
            cache_hits=0,references=0,captures=0,witnesses=0,obligations=0,
            parent_checks=0,load_seconds=0.0,root_interfaces=0)
        self._closed = False

    @property
    def stats(self):
        return dict(self._stats,cached_units=len(self._units),pinned_variant_paths=len(self._pins),
            source_reader=dict(self.base_index.stats),
            supplemental_readers=[dict(index.stats) for index in self._source_indices.values()
                if index is not self.base_index])

    def _source_index(self, unit):
        return self._source_indices[id(self.store.source_parent_for(unit.unit))]

    def _pin(self, path):
        path = Path(path);stamp = _stamp(path)
        if path in self._pins and self._pins[path] != stamp:
            raise ValueError('frame capture original parent changed: '+str(path))
        self._pins[path] = stamp

    def validate_parents(self):
        self._stats['parent_checks'] += 1
        count = self.store.validate_parents()+sum(index.validate_parents()
            for index in self._source_indices.values())
        for path,stamp in self._pins.items():
            if _stamp(path) != stamp:
                raise ValueError('frame capture original parent changed: '+str(path))
        return count+len(self._pins)

    def close(self):
        if not self._closed:
            for index in self._source_indices.values():index.close()
            self._closed = True

    def _compiled_plans(self, unit, keys):
        connection = self._connections[unit.unit]
        root,report = self.exec_graph.parents['f4_graphs']
        descriptor = report['variants'][unit.unit]
        folder = root/descriptor['path']
        self._pin(root/'result.json')
        self._pin(folder/descriptor['tables']['templates']['path'])
        graph = self.exec_graph.expand_root(connection)
        nodes = {node.key:node for node in graph.templates}
        if not keys <= nodes.keys():
            raise ValueError('frame capture template missing from compiled F4 graph')
        domains = {}
        for key in keys:
            node = nodes[key]
            selected = domains.setdefault(node.origin.domain.value,{})
            if node.origin.line in selected:
                raise ValueError('compiled frame templates share a material row')
            selected[node.origin.line] = key
        source = self.store.original_source_units[unit.unit]
        parent = self.store.base
        while parent.parents:
            parent = parent.parents[parent.unit_parent[source]]
        manifest = parent.model/'manifest.json';self._pin(manifest)
        manifest_sha = sha256(manifest.read_bytes()).hexdigest()
        if manifest_sha != parent.report['model_manifest_sha256']:
            raise ValueError('compiled frame source model manifest differs')
        result = {}
        for domain,selected in sorted(domains.items()):
            self._pin(folder/descriptor['tables'][domain]['path'])
            for ordinal,wire in enumerate(self.exec_graph._rows(connection,domain),1):
                key = selected.get(ordinal)
                if key is None:
                    continue
                node = nodes[key]
                if _digest(wire) != node.origin.plan_sha256:
                    raise ValueError('compiled frame plan digest differs')
                plan = decode(P.SourceProductionPlan,wire,record_tags=P.PRODUCTION_RECORD_TAGS)
                if (type(plan.source) is not P.ProductionOccurrence or plan.source.occurrence != key.occurrence
                        or plan.purpose is not key.purpose or plan.root != node.root
                        or plan.input != graph.input or plan.profile != graph.profile
                        or plan.compilation_flow is None):
                    raise ValueError('compiled frame plan source/profile differs from F4 header')
                result[key] = (plan,node.origin.plan_sha256,I.WitnessSource.SEALED_TEMPLATE_STORE,
                    self.store.exec_sha256,manifest_sha)
        if result.keys() != keys:
            raise ValueError('compiled frame plan selection is incomplete')
        self._stats['compiled_templates'] += len(result)
        return result

    def _root_header(self, unit):
        if unit.unit in self._headers:return self._headers[unit.unit]
        if unit.unit in self.store.original_source_units:
            connection=self._connections[unit.unit]
            root,report=self.exec_graph.parents['f4_graphs'];descriptor=report['variants'][unit.unit]
            self._pin(root/'result.json')
            self._pin(root/descriptor['path']/descriptor['tables']['templates']['path'])
            graph=self.exec_graph.expand_root(connection)
            node=next(n for n in graph.templates if n.key==unit.root_scope.template)
            kind='COMPILE_CONTEXT_F4_VARIANT';self._stats['compiled_units']+=1
        else:
            index=self._source_index(unit)
            index._header(unit)
            node=index._graphs[unit.unit][unit.root_scope.template]
            kind='SEALED_SOURCE_TEMPLATE_STORE';self._stats['base_units']+=1
        if (node.key.purpose is not P.ProductionPurpose.ROOT or node.root!=unit.root_scope.region
                or len(node.parameters)!=3 or any(type(t) is not ValueType or t.kind is not k
                    for t,k in zip(node.parameters,(ValueKind.REFERENCE,ValueKind.REFERENCE,ValueKind.STATE)))):
            raise ValueError('frame root header globals/locals/world ABI differs')
        self._headers[unit.unit]=kind;self._stats['root_interfaces']+=1
        return kind

    def load(self, unit_id):
        """Explicit full-unit view; incremental users select only needed plans."""
        unit=self.store.load(unit_id)
        return self.load_selected(unit_id,{unit.root_scope.template,*(f.template for f in unit.functions)})

    def load_selected(self, unit_id, templates=()):
        if self._closed:
            raise ValueError('frame capture index is closed')
        started = perf_counter();self.validate_parents()
        unit = self.store.load(unit_id)
        if unit.root_scope is None or unit.root_scope.owner.unit != unit_id:
            raise ValueError('frame capture unit lacks an original root witness')
        keys=set(templates)
        if not keys<={unit.root_scope.template,*(f.template for f in unit.functions)}:
            raise ValueError('selected frame plan is not an original root or function template')
        selected=self._selected.setdefault(unit_id,set())
        if unit_id in self._units and keys<=selected:
            self._stats['cache_hits']+=1
            return self._units[unit_id]
        kind=self._root_header(unit)
        missing=keys-selected
        if unit_id in self.store.original_source_units:
            plans = self._compiled_plans(unit,missing) if missing else {}
        else:
            index=self._source_index(unit)
            index._prefetch(unit,missing)
            plans = {key:index._plan(unit,key) for key in missing}
            self._stats['base_templates'] += len(plans)
        records=self._records.setdefault(unit_id,{})
        for key,(plan,digest,source,receipt,model) in sorted(plans.items(),
                key=lambda item:(item[0].occurrence,item[0].purpose.value)):
            view = NamespacePlanView(unit_id,plan)
            refs,created,pending = extract_captures(view)
            witnesses=[]
            for record in (*refs,*created):
                step = view.steps[record.site.port.owner]
                if record.owner != view.owner(step.region):
                    raise ValueError('frame capture owner differs from its original step')
                witnesses.append(I.StepWitness(unit_id,key,digest,step.id,step.region,record.owner.owner,
                    source,receipt,model))
            records[key]=(refs,created,tuple(witnesses),pending)
            for name,rows in zip(('references','captures','witnesses','obligations'),records[key]):
                self._stats[name]+=len(rows)
        selected.update(missing)
        references,captures,witnesses,obligations=(tuple(row for key in sorted(records,
            key=lambda k:(k.occurrence,k.purpose.value)) for row in records[key][i]) for i in range(4))
        self.validate_parents()
        value = SimpleNamespace(root=unit.root_scope,references=tuple(references),captures=tuple(captures),
            witnesses=tuple(witnesses),obligations=tuple(obligations),template_store_kind=kind,
            selected_templates=frozenset(selected))
        self._units[unit_id] = value
        self._stats['load_seconds'] += perf_counter()-started
        return value
