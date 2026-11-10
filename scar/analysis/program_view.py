"""One typed dependency/query facade for core graphs and sealed F4 sources.

The original ProgramDependencyGraph supplies adjacency and traversal. This
adapter normalizes identities and relations only; it does not parse Python,
interpret labels, select targets or turn a may walk into an execution proof.
"""
from collections import defaultdict
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from types import MappingProxyType
import argparse
import time

from scar.analysis.program_dependencies import ProgramDependencyGraph
from scar.analysis.source_graph_material import source_graph_material
from scar.analysis.source_context_query import ContextTargetGraph
from scar.analysis.normal_graph import normal_edges, _Emitter
from scar.analysis.source_template_links import _json, _worker_stores
from scar.analysis.source_consumer_parents import _stamp
from scar.analysis.source_reference_slice import source_port
from scar.ir.program import normal_graph as G, source_productions as P, model as M
from scar.ir.program import view as V
from scar.ir.program.dependencies import (GraphNamespace, DependencyPoint as Point,
    DependencyKind as K, DependencyMeaning as Meaning, DependencyEdge, DependencyEvidence,
    DependencyCondition, DependencyFrontier, DependencyNeighborhood)
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.ids import (OperationID, RegionID, ValueID, UseID, ControlPortID, LocationID,
    BlockID, ResourceDefinitionID, ResourceRequirementID, EnvironmentInterfaceID, ProviderID, NativeBoundaryID)
from scar.ir.record_codec import encode, _encode, _record_tags


SOURCE_REPRESENTATION = 'scar.f4.normal-success.v1'
_CONTROL = frozenset((G.PortKind.ENTER, G.PortKind.EXIT, G.PortKind.CALL_RETURN))
_SOURCE_TAGS = MappingProxyType(_record_tags(P.PRODUCTION_RECORD_TAGS))


def _digest(value):
    # The finite, fixed declaration catalog is checked once. Revalidating it
    # for every port hash dominates large units and cannot add source facts.
    return sha256(_json(_encode(value, _SOURCE_TAGS))).hexdigest()


class _RepresentationProvider:
    """Route existing core providers without fabricating an N1 ProgramGraph."""
    def __init__(self, provider, extension=None):
        self.provider = provider
        self.extension = extension
        self.relation_kinds = getattr(provider, 'relation_kinds', None)

    def incoming(self, point):
        return self._query(point, True)

    def outgoing(self, point):
        return self._query(point, False)

    def _query(self, point, incoming):
        if point.namespace.representation == SOURCE_REPRESENTATION:
            return DependencyNeighborhood()
        if self.extension is not None and self.extension(point):
            return DependencyNeighborhood()
        return (self.provider.incoming if incoming else self.provider.outgoing)(point)


class SourceUnitProvider:
    """A unit-local projection; all functions share the same identity domain."""
    def __init__(self, material):
        self.material = material; self.unit = material.unit
        self.graph = material.graph; self.facts = material.fact_store.load(self.unit)
        self.nodes = {}; self.anchors = {}; self.records = {}; self.incoming_edges = defaultdict(list)
        self.outgoing_edges = defaultdict(list); self.edge_sources = defaultdict(list); self.expanded = set()
        self.metadata_providers = ()
        self.plans = {}; self.callers = defaultdict(set)
        self.basis = _digest((self.unit, self.graph.input, self.graph.profile))
        root = self.facts.root_scope
        root_id = self._identity(RegionID, root.template, root.region)
        artifact = material.result_artifact
        self.locator = SourceArtifactLocator(artifact, artifact.sha256, artifact.size_bytes, 'canonical-json')
        self.namespace = GraphNamespace(self.locator, SOURCE_REPRESENTATION, root_id)
        self.evidence = DependencyEvidence('scar.f4.identity-and-interface.v1', (self.locator,))
        for node in self.graph.templates:
            self._node(node.key, node.root)
        for link in self.graph.links: self.callers[link.callee].add(link.caller)
        self.formals = {source_port(self.facts,p).port for f in self.facts.functions for p in f.formals}
        world = self.graph.profile.world
        if type(world) is M.ValueType and world.kind is M.ValueKind.STATE:
            anchor = V.SourceAnchor(self.unit, None, world.location)
            point = Point(self.namespace, world.location, None)
            self.nodes[world.location] = V.SourceNodeProjection(point, anchor, V.ProgramEntityKind.STATE_LOCATION,
                V.ProgramNodeRole.ABSTRACT_STATE_DOMAIN, None, world, material.result_artifact)
            self.anchors[anchor] = world.location; self.records[world.location] = world
        self._guard = {path:_stamp(path) for path in material._parents}
        if self.unit in material.fact_store.original_source_units:
            for receipt in material.descriptor['tables'].values():
                path=material.root/material.descriptor['path']/receipt['path']
                self._guard[path]=_stamp(path)
        else:
            report=json.loads(material._template_raw)
            entry=next(row for row in report['units'] if row['unit']==self.unit)
            path=material.root/entry['header'];self._guard[path]=_stamp(path)
            header=json.loads(path.read_bytes())
            for name in ('templates','links'):
                path=material.root/entry['header'];table=path.parent/header[name]['path']
                self._guard[table]=_stamp(table)
            specifications=tuple((p['domain'],p['materials'],p['verification'],p['collection_sha256'],p['verification_sha256']) for p in report['parents'])
            for parent in _worker_stores(specifications,report['model_manifest_sha256']):
                path=parent.root/parent.rows[self.unit]['artifact']['path']
                self._guard[path]=_stamp(path)
        self.check()

    def check(self, point=None):
        if point is not None and (point.namespace != self.namespace or point.namespace.graph != self.namespace.graph
                or point.namespace.source_body is not None):
            raise ValueError('source endpoint namespace or full material declaration differs')
        if any(_stamp(path)!=stamp for path,stamp in self._guard.items()):
            raise ValueError('admitted source material changed during this query session')
        if json.loads(self.material._catalog_raw)!=self.material.catalog.report:
            raise ValueError('admitted source catalog changed in memory')
        if any(_stamp(path)!=stamp for path,stamp in getattr(self.material,'_tables',{}).items()):
            raise ValueError('admitted compiled source table changed')

    def _identity(self, cls, template, original):
        return cls(_digest((self.basis, template, original)))

    def _node(self, template, original, value_type=None):
        anchor = V.SourceAnchor(self.unit, template, original)
        if type(original) is P.ProductionRegionID:
            cls, kind, role, owner = RegionID, V.ProgramEntityKind.REGION, V.ProgramNodeRole.REGION, None
        elif type(original) is P.ProductionStepID:
            cls, kind, role, owner = OperationID, V.ProgramEntityKind.OPERATION, V.ProgramNodeRole.OPERATION, None
        elif type(original) is G.Port:
            if original.template != template: raise ValueError('source port lost its original template')
            cls = ControlPortID if original.kind in _CONTROL else UseID if original.kind is G.PortKind.ARGUMENT else ValueID
            kind = V.ProgramEntityKind.VALUE if cls is ValueID else None
            role = V.ProgramNodeRole(original.kind.value)
            owner = None
        else: raise TypeError('source projection requires an original region, step or port')
        # Full original anchors already index admitted nodes. Reusing them
        # avoids rehashing the material/port and recursing through an owner on
        # every edge. Preserve later full-record and owner assignments.
        identity = self.anchors.get(anchor)
        if identity is not None:
            current = self.nodes[identity]
            if type(identity) is not cls or current.anchor != anchor:
                raise ValueError('source-to-core cached identity projection differs')
            if value_type is not None:
                if current.value_type not in (None, value_type): raise ValueError('source port has incompatible declared types')
                if current.value_type is None:
                    self.nodes[identity] = replace(current, value_type=value_type)
            return current.point
        if type(original) is G.Port:
            owner = self._node(template, original.owner)
        identity = self._identity(cls, template, original)
        point = Point(self.namespace, identity, None)
        if identity in self.nodes:
            current = self.nodes[identity]
            if current.anchor != anchor: raise ValueError('source-to-core identity projection collision')
            if value_type is not None:
                if current.value_type not in (None, value_type): raise ValueError('source port has incompatible declared types')
                self.nodes[identity] = replace(current, value_type=value_type)
        else:
            self.nodes[identity] = V.SourceNodeProjection(point, anchor, kind, role, owner,
                value_type, self.material.result_artifact)
            self.anchors[anchor] = identity; self.records[identity] = original
        return point

    def _relation(self, source, target, kind, meaning, template, ordinal, rule, original=None, conditions=()):
        relation = DependencyEdge(source, target, kind, meaning,
            (DependencyEvidence(rule, (self.locator,), (source, target)),), tuple(conditions))
        projection = V.SourceEdgeProjection(relation, template, ordinal, original, rule)
        if relation not in self.edge_sources:
            self.outgoing_edges[source.node].append(relation); self.incoming_edges[target.node].append(relation)
        if projection not in self.edge_sources[relation]: self.edge_sources[relation].append(projection)

    def _interfaces(self, key, plan):
        emitter = _Emitter(plan, key, self.material.interfaces)
        for region in plan.regions:
            point = self._node(key, region.id); self.records[point.node] = region
            self._node(key, emitter.port(region.id, G.PortKind.ENTER))
            if region.parent is not None:
                parent = self._node(key, region.parent)
                self.nodes[point.node] = replace(self.nodes[point.node], owner=parent)
                self._relation(parent, point, K.CONTAINS, Meaning.STRUCTURE, key, 0, 'scar.f4.region-parent.v1')
            for index, type_ in enumerate(region.parameters):
                self._node(key, emitter.port(region.id, G.PortKind.PARAMETER, index), type_)
            for completion in region.completions:
                self._node(key, emitter.port(region.id, G.PortKind.EXIT, completion=completion))
                for index, type_ in enumerate(completion.types):
                    self._node(key, emitter.port(region.id, G.PortKind.RESULT, index, completion), type_)
        for step in plan.steps:
            operation = self._node(key, step.id); self.records[operation.node] = step
            self._node(key, emitter.port(step.id, G.PortKind.ENTER))
            owner = self._node(key, step.region)
            self.nodes[operation.node] = replace(self.nodes[operation.node], owner=owner)
            self._relation(owner, operation, K.CONTAINS, Meaning.STRUCTURE, key, 0, 'scar.f4.operation-owner.v1')
            for index, argument in enumerate(step.arguments):
                type_ = emitter.value(argument)[1]
                port = self._node(key, emitter.port(step.id, G.PortKind.ARGUMENT, index), type_)
                state = type(type_) is M.ValueType and type_.kind is M.ValueKind.STATE
                self._relation(port, operation, K.STATE_INPUT if state else K.OPERAND,
                    Meaning.STATE_INTERFACE if state else Meaning.DEPENDENCE, key, index, 'scar.f4.operation-input.v1')
            for completion in step.completions:
                exit_port = self._node(key, emitter.port(step.id, G.PortKind.EXIT, completion=completion))
                for index, type_ in enumerate(completion.types):
                    port = self._node(key, emitter.port(step.id, G.PortKind.RESULT, index, completion), type_)
                    state = type(type_) is M.ValueType and type_.kind is M.ValueKind.STATE
                    self._relation(operation, port, K.STATE_OUTPUT if state else K.RESULT,
                        Meaning.STATE_INTERFACE if state else Meaning.DEPENDENCE, key, index, 'scar.f4.operation-output.v1',
                        conditions=(DependencyCondition('scar.f4.declared-completion', completion.kind.value,
                            exit_port, index, (port,)),))

    def _expand(self, keys):
        self.check()
        keys = tuple(k for k in dict.fromkeys(keys) if k not in self.expanded)
        if not keys: return
        plans = self.material.plans(keys)
        for key, plan in plans.items():
            self.plans[key] = plan; self._interfaces(key, plan)
            for ordinal, edge in enumerate(normal_edges(plan, self.material.interfaces)):
                source = self._node(edge.source.template, edge.source, edge.value_type)
                target = self._node(edge.target.template, edge.target, edge.value_type)
                conditions = []
                if edge.condition is not None:
                    condition = self._node(edge.condition.template, edge.condition)
                    conditions.append(DependencyCondition('scar.f4.branch', 'TRUE' if edge.when else 'FALSE', condition))
                if edge.transition is not G.Transition.DIRECT:
                    conditions.append(DependencyCondition('scar.f4.recipe-transition', edge.transition.value,
                        source, ordinal, (source, target)))
                if edge.kind is G.EdgeKind.STATE:
                    kind, meaning = K.STATE_INTERFACE, Meaning.STATE_INTERFACE
                elif edge.kind is G.EdgeKind.DATA:
                    kind = K.VALUE_USE
                    meaning = (Meaning.REFERENCE if type(edge.value_type) is M.ValueType
                        and edge.value_type.kind is M.ValueKind.REFERENCE else Meaning.VALUE)
                elif edge.kind is G.EdgeKind.CONTROL:
                    kind, meaning = K.CONTROL_FLOW, Meaning.STRUCTURE
                else:
                    kind, meaning = K.IMPLEMENTATION, Meaning.STRUCTURE
                self._relation(source, target, kind, meaning, key, ordinal,
                    'scar.f4.normal-interface.v1', edge, conditions)
            self.expanded.add(key)
        self.material.validate_parents()

    def port(self, port, *, context=None):
        if type(port) is not G.Port or port.template not in self.material.interfaces['nodes']:
            raise ValueError('source port is outside its original unit templates')
        self._expand((port.template,))
        cls = ControlPortID if port.kind in _CONTROL else UseID if port.kind is G.PortKind.ARGUMENT else ValueID
        identity = self._identity(cls, port.template, port)
        if identity not in self.nodes: raise ValueError('source port is not in a retained declared interface')
        return replace(self.nodes[identity].point, context=context)

    def expand(self, point):
        self.ensure(point)
        anchor = self.nodes[point.node].anchor
        if anchor.template is None: return ()
        self._expand((anchor.template,))
        original = self.records[point.node]
        if type(original) is P.ProductionRegion:
            return tuple(replace(self._node(anchor.template, step), context=point.context) for step in original.steps)
        if type(original) is P.ProductionStep:
            ports = tuple(replace(node.point, context=point.context) for node in self.nodes.values()
                if node.owner is not None and node.owner.node == point.node)
            regions = tuple(dict.fromkeys(replace(self._node(edge.target.template, edge.target.owner), context=point.context)
                for projections in self.edge_sources.values() for row in projections
                if (edge := row.original) is not None and edge.source.template == anchor.template
                and edge.source.owner == original.id and edge.target.kind is G.PortKind.ENTER
                and type(edge.target.owner) is P.ProductionRegionID
                and (edge.transition in (G.Transition.CALL, G.Transition.RESUME) or edge.kind is G.EdgeKind.DECLARE)))
            return (*ports, *regions)
        return ()

    def ensure(self, point):
        self.check(point)
        if point.node not in self.nodes:raise ValueError('source endpoint has no admitted identity projection')
        key=self.nodes[point.node].anchor.template
        if key is not None:self._expand((key,))
        if type(point.node) is RegionID and type(self.records[point.node]) is not P.ProductionRegion:
            raise ValueError('declared source region is absent from its original recipe')

    def _neighbors(self, point, incoming):
        if point.namespace != self.namespace: return DependencyNeighborhood()
        self.check(point)
        if point.node not in self.nodes:
            # Extension records use this same source namespace. Their owning
            # metadata adapter, rather than a fabricated source port, admits
            # them; unknown endpoints still fail.
            if any(provider.describe(point) is not None for provider in self.metadata_providers):
                return DependencyNeighborhood()
            raise ValueError('source endpoint has no admitted identity projection')
        node = self.nodes[point.node]; key = node.anchor.template
        if key is not None: self._expand((key, *sorted(self.callers[key], key=lambda k: (k.occurrence,k.purpose.value))))
        edges = self.incoming_edges[point.node] if incoming else self.outgoing_edges[point.node]
        projected = tuple(replace(e, source=replace(e.source, context=point.context),
            target=replace(e.target, context=point.context), conditions=tuple(replace(c,
                subject=None if c.subject is None else replace(c.subject, context=point.context),
                operands=tuple(replace(p, context=point.context) for p in c.operands)) for c in e.conditions)) for e in edges)
        frontiers = []
        if node.kind is V.ProgramEntityKind.OPERATION:
            frontiers.append(DependencyFrontier(point, 'SOURCE_EFFECT_FIELDS_NOT_ATTACHED',
                'Original instruction is retained; effect, alias and resource summaries are separate analyses.'))
        if type(node.anchor.original) is G.Port:
            port=node.anchor.original
            if port in self.formals:
                frontiers.append(DependencyFrontier(point,'SOURCE_FUNCTION_INCOMING_INTERFACE_NOT_ATTACHED',
                    'Declared formal/environment/world needs an original selected caller route; an empty neighborhood is not closure.'))
            elif port.kind is G.PortKind.PARAMETER and not any(e.kind in (K.VALUE_USE,K.STATE_INTERFACE) for e in self.incoming_edges[point.node]):
                frontiers.append(DependencyFrontier(point,'SOURCE_REGION_INPUT_BINDING_OPEN',
                    'No retained interface supplies this region input in the current projection.'))
            if port.kind is G.PortKind.ENTER and type(port.owner) is P.ProductionRegionID and self._identity(RegionID,port.template,port.owner)==self.namespace.root:
                frontiers.append(DependencyFrontier(point,'SOURCE_ENTRY_ACTIVATION_NOT_ATTACHED',
                    'This is a declared root interface, not a selected execution entry.'))
        return DependencyNeighborhood(projected, tuple(frontiers))

    def incoming(self, point): return self._neighbors(point, True)
    def outgoing(self, point): return self._neighbors(point, False)


class ProgramView:
    """Shared source/core query interface with explicit original record access."""
    def __init__(self, catalog, *, core_loader=None):
        self.catalog = (catalog if catalog is None or isinstance(catalog, ContextTargetGraph) else ContextTargetGraph(catalog))
        self.core_loader = core_loader; self.units = {}; self.namespaces = {}; self.metadata_providers = []
        self.state_providers = {}
        self.dependencies = ProgramDependencyGraph(self._core_index)
        self.dependencies.providers[:] = [_RepresentationProvider(p,self._core_extension) for p in self.dependencies.providers]

    def _core_index(self, namespace):
        if namespace.representation == SOURCE_REPRESENTATION:
            raise TypeError('source recipes are not fabricated canonical ProgramGraphs')
        if self.core_loader is None: raise ValueError('this original core graph has not been attached')
        return self.core_loader(namespace)

    def _core_record(self, point):
        index=self._core_index(point.namespace)
        for name in ('operations','values','regions','locations','resources','_uses','_block_records'):
            rows=getattr(index,name,{})
            if point.node in rows:return rows[point.node]
        for name in ('resources','resource_requirements','environments','control_ports','provider_envelopes','native_boundaries'):
            for record in getattr(index.graph,name,()):
                if getattr(record,'id',None)==point.node:return record
        return None

    def _core_extension(self, point):
        if not self.metadata_providers or self._core_record(point) is not None:return False
        return self._metadata(point)[0] is not None

    def unit(self, identity):
        if self.catalog is None: raise ValueError('no source catalog is attached')
        if identity not in self.units:
            provider = SourceUnitProvider(source_graph_material(self.catalog, identity))
            provider.metadata_providers = self.metadata_providers
            self.units[identity] = provider; self.namespaces[provider.namespace] = provider
            self.dependencies.register(provider)
        return self.units[identity]

    def state(self, identity):
        """Attach source effect requests and binding versions on demand."""
        if identity not in self.state_providers:
            from scar.analysis.source_state import SourceStateProvider
            self.state_providers[identity] = SourceStateProvider(self, identity)
        return self.state_providers[identity]

    def register(self, provider):
        """Attach another typed relation/record adapter to this same view."""
        methods=('describe','original','expand','explain')
        available=tuple(callable(getattr(provider,name,None)) for name in methods)
        if any(available) and not all(available):raise TypeError('metadata adapters need describe/original/expand/explain')
        self.dependencies.register(provider)
        if all(available):self.metadata_providers.append(provider)
        return provider

    def _metadata(self, point):
        source=self.namespaces.get(point.namespace)
        if source is not None:source.check(point)
        for provider in self.metadata_providers:
            node=provider.describe(point)
            if node is not None:
                if type(node) is not V.ProgramNode or node.point!=point:
                    raise TypeError('metadata adapter changed its typed query endpoint')
                return provider,node
        return None,None

    def source_port(self, global_port, *, context=None):
        return self.unit(global_port.unit).port(global_port.port, context=context)

    def source_region(self, unit, template, region, *, context=None):
        provider = self.unit(unit); provider._expand((template,))
        identity = provider._identity(RegionID, template, region)
        if identity not in provider.nodes or type(provider.records[identity]) is not P.ProductionRegion:
            raise ValueError('source region is outside its original recipe')
        return replace(provider.nodes[identity].point, context=context)

    def source_region_ref(self, unit, template, region, *, context=None):
        """Reference a sealed root or declared function body without expansion.

        The header or exact original function fact supplies this identity.
        get/original/expand still admit the full recipe when its fields or
        dependencies are queried; no arbitrary nested region is introduced.
        """
        provider=self.unit(unit)
        declared=provider.material.interfaces['nodes'].get(template)
        body=any(f.template==template and f.body==region for f in provider.facts.functions)
        if declared is None or declared.root!=region and not body:
            raise ValueError('source region reference is not an original declared root or function body')
        point=provider._node(template,region)
        provider.check(point)
        return replace(point,context=context)

    def entry(self, unit, *, context=None):
        root = self.unit(unit).facts.root_scope
        return self.source_region(unit, root.template, root.region, context=context)

    def original(self, point):
        provider = self.namespaces.get(point.namespace)
        if provider is None:
            original=self._core_record(point)
            if original is not None:return original
        if provider is None or point.node not in provider.nodes:
            adapter,_=self._metadata(point)
            if adapter is not None:return adapter.original(point)
            if provider is not None:raise ValueError('source endpoint has no admitted record adapter')
            raise ValueError('core endpoint is not in an attached entity table')
        provider.ensure(point)
        return provider.records[point.node]

    def get(self, point):
        provider = self.namespaces.get(point.namespace)
        if provider is not None and point.node in provider.nodes:
            provider.ensure(point); node = provider.nodes[point.node]
            owner = None if node.owner is None else replace(node.owner, context=point.context)
            return V.ProgramNode(point, node.kind, node.role, owner, node.value_type)
        if provider is not None or self._core_record(point) is None:
            _,node=self._metadata(point)
            if node is not None:return node
        original = self.original(point)
        kinds = {OperationID:V.ProgramEntityKind.OPERATION, ValueID:V.ProgramEntityKind.VALUE,
            RegionID:V.ProgramEntityKind.REGION, LocationID:V.ProgramEntityKind.STATE_LOCATION,
            ResourceDefinitionID:V.ProgramEntityKind.RESOURCE}
        roles = {OperationID:V.ProgramNodeRole.OPERATION, ValueID:V.ProgramNodeRole.CORE_VALUE,
            UseID:V.ProgramNodeRole.CORE_USE, ControlPortID:V.ProgramNodeRole.CORE_CONTROL_PORT,
            RegionID:V.ProgramNodeRole.REGION, BlockID:V.ProgramNodeRole.BLOCK,
            LocationID:V.ProgramNodeRole.STATE_LOCATION, EnvironmentInterfaceID:V.ProgramNodeRole.ENVIRONMENT_INTERFACE,
            ResourceDefinitionID:V.ProgramNodeRole.RESOURCE, ResourceRequirementID:V.ProgramNodeRole.RESOURCE_REQUIREMENT,
            ProviderID:V.ProgramNodeRole.PROVIDER, NativeBoundaryID:V.ProgramNodeRole.NATIVE_BOUNDARY}
        owner = None; value_type = None
        if type(point.node) is ValueID:
            owner = Point(point.namespace, original.region, point.context); value_type = M.value_type(original)
        elif type(point.node) is UseID:
            index = self._core_index(point.namespace)
            owner = Point(point.namespace, original.operation, point.context)
            value_type = M.value_type(index.values[original.use.value])
        elif type(point.node) is OperationID:
            index=self._core_index(point.namespace)
            owner=Point(point.namespace,index._blocks[index._operation_blocks[point.node]],point.context)
        elif type(point.node) is RegionID and original.parent is not None:
            owner=Point(point.namespace,original.parent,point.context)
        elif type(point.node) is BlockID:
            owner=Point(point.namespace,self._core_index(point.namespace)._blocks[point.node],point.context)
        return V.ProgramNode(point, kinds.get(type(point.node)), roles[type(point.node)], owner, value_type)

    def expand(self, point):
        """Expand original structure and guarded callable body interfaces.

        Call targets retain their selected frame and original edge evidence;
        listing a body does not assert its activation or discharge its guards.
        """
        children=self._expand_original(point)
        if type(point.node) is OperationID:
            targets=self.dependencies.outgoing(point,kinds=(K.CALL_TARGET,K.CONTAINS))
            children=(*children,*(edge.target for edge in targets.edges
                if edge.kind is K.CONTAINS or self.get(edge.target).kind is V.ProgramEntityKind.REGION))
        return tuple(dict.fromkeys(children))

    def _expand_original(self, point):
        provider = self.namespaces.get(point.namespace)
        if provider is not None and point.node in provider.nodes:return provider.expand(point)
        adapter,_=self._metadata(point)
        if adapter is not None:return adapter.expand(point)
        original=self.original(point);children=()
        if type(original) is M.Region:
            children=tuple(o for block in original.blocks for o in block.operations)
        elif type(original) is M.Block:children=original.operations
        elif type(original) is M.Operation:
            # A callable body belongs to its selected interface frame. The
            # CALL_TARGET query in expand supplies it; do not also expose an
            # unframed body through this structural port expansion.
            children=(*(u.id for u in original.uses),*original.results)
        return tuple(Point(point.namespace,node,point.context) for node in children)

    def producers(self, point): return self.dependencies.incoming(point)
    def consumers(self, point): return self.dependencies.outgoing(point)

    def explain(self, point):
        provider = self.namespaces.get(point.namespace)
        if provider is None or point.node not in provider.nodes:
            adapter,_=self._metadata(point)
            if adapter is not None:return adapter.explain(point)
        if provider is None: return dict(node=self.get(point), namespace=point.namespace, original=self.original(point))
        provider.ensure(point)
        return dict(node=self.get(point), projection=provider.nodes[point.node], original=provider.records[point.node],
            input=provider.graph.input, profile=provider.graph.profile,
            normal_success_view_only=True, execution_or_effect_proof=False)

    def explain_edge(self, edge):
        provider = self.namespaces.get(edge.source.namespace)
        if provider is None: return edge.evidence
        unscoped = replace(edge, source=replace(edge.source, context=None), target=replace(edge.target, context=None),
            conditions=tuple(replace(c, subject=None if c.subject is None else replace(c.subject, context=None),
                operands=tuple(replace(p, context=None) for p in c.operands)) for c in edge.conditions))
        return tuple(provider.edge_sources.get(unscoped, ())) or edge.evidence

    def project_unit(self, unit, *, templates=None):
        """Normalize one selected finite material domain, without body copies."""
        provider = self.unit(unit)
        keys = tuple(provider.material.interfaces['nodes']) if templates is None else tuple(templates)
        provider._expand(keys)
        return provider


def mapping_contract():
    """Closed source record domains; unsupported kinds never become OPAQUE."""
    return dict(entity_kinds=[k.value for k in V.ProgramEntityKind],
        port_ids={k.value: ('ControlPortID' if k in _CONTROL else 'UseID' if k is G.PortKind.ARGUMENT else 'ValueID') for k in G.PortKind},
        edge_kinds={G.EdgeKind.DATA.value:K.VALUE_USE.value, G.EdgeKind.STATE.value:K.STATE_INTERFACE.value,
            G.EdgeKind.CONTROL.value:K.CONTROL_FLOW.value, G.EdgeKind.DECLARE.value:K.IMPLEMENTATION.value},
        transitions=[k.value for k in G.Transition],
        instruction_records=sorted(cls.__name__ for cls in P.ProductionInstruction.__args__),
        unknown_instruction_fallback=False, traversal_is_execution_proof=False,
        auxiliary_roles_are_not_new_entities=True, declaration_is_body_activation=False)


def _pins():
    from scar.ir.program import dependencies
    from scar.analysis import program_dependencies, normal_graph, source_graph_material
    from scar.analysis import program_view_storage
    return dict(producer=sha256(Path(__file__).read_bytes()).hexdigest(), **{
        name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
        ('types', V), ('core_types', dependencies),
        ('query_engine', program_dependencies), ('normal_edges', normal_graph), ('materials', source_graph_material),
        ('storage', program_view_storage))}
    )


def publish_program_view(catalog, units, out):
    """Store identity/edge projections; original instructions stay in F4."""
    from scar.analysis.normal_output import write_table
    from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
    from scar.analysis.source_value_flow import _artifact
    from scar.analysis.program_view_storage import pack_nodes,pack_edges
    started = time.monotonic(); pins = _pins(); out = Path(out).absolute()
    if out.exists(): raise ValueError('fresh unified program view output required')
    catalog = catalog if isinstance(catalog, ContextTargetGraph) else ContextTargetGraph(catalog)
    _durable_mkdir(out); shards = {}
    for unit in tuple(dict.fromkeys(units)):
        view=ProgramView(catalog)
        provider = view.project_unit(unit); folder = out/'units'/unit; _durable_mkdir(folder)
        projection_count=sum(len(rows) for rows in provider.edge_sources.values())
        tables = dict(nodes=write_table(folder/'nodes.jsonl.gz', pack_nodes(provider)),
            edges=write_table(folder/'edges.jsonl.gz', pack_edges(provider)))
        shards[unit] = dict(path='units/'+unit, namespace=encode(provider.namespace), material=encode(provider.material.result_artifact),
            templates=len(provider.expanded), nodes=len(provider.nodes), relations=len(provider.edge_sources),
            edge_projections=projection_count, tables=tables)
        provider.material.validate_parents()
        # Publication owns this temporary facade. Do not retain every unit's
        # projection maps through its bound-loader cycle until the full tree
        # finishes; source records remain in their original shared stores.
        view.dependencies.providers.clear();view.units.clear();view.namespaces.clear()
    if pins != _pins(): raise ValueError('program view mapping rules changed')
    catalog_artifact = _artifact(catalog.path/'result.json', catalog.report['schema'])
    tables = {unit+'/'+name:dict(receipt,path=shard['path']+'/'+receipt['path'])
        for unit,shard in shards.items() for name,receipt in shard['tables'].items()}
    report = dict(schema='scar.unified-program-view', schema_version=2, catalog=str(catalog.path),
        parent=encode(catalog_artifact), pins=pins, contract=mapping_contract(), shards=shards, tables=tables,
        acceptance='PINNED_DATA_CONTRACT_AND_CURRENT_SOURCE_REDERIVATION',
        seconds=time.monotonic()-started, original_body_bytes_copied=0, loops_unrolled=False,
        effects_proven=False, runtime_dispatch_proven=False, target_executed=False, first_stage_complete=False)
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report


def read_program_view(path, *, unit):
    """Rederive one complete unit's projections from its original F4 plans."""
    from scar.analysis.program_view_storage import read_and_validate
    from scar.analysis.source_value_flow import _artifact
    path=Path(path).absolute();raw=(path/'result.json').read_bytes();report=json.loads(raw)
    current_pins=_pins()
    # Schema 2's compact storage forbids contexts (program_view_storage._local).
    # The known previous dependency declaration predates Frame.selection only;
    # no Frame is present in these tables. Admit that exact producer receipt,
    # then still rederive every node/edge with current rules below. Contextual
    # query records have no such migration and retain exact wire validation.
    frameless_v2_dependency_pin='fec8584d711dbecd8ecb6bc9dd80eb85d7a1f16f03d6c5959f4d7581e3dd73e6'
    if ((report['schema'],report['schema_version'])!=('scar.unified-program-view',2)
            or set(report['pins'])!=set(current_pins)
            or any(report['pins'][k]!=current_pins[k] and not
                (k=='core_types' and report['pins'][k]==frameless_v2_dependency_pin)
                for k in current_pins if k!='producer')
            or len(report['pins']['producer'])!=64 or any(c not in '0123456789abcdef' for c in report['pins']['producer'])
            or report['contract']!=mapping_contract()
            or report['acceptance']!='PINNED_DATA_CONTRACT_AND_CURRENT_SOURCE_REDERIVATION'):
        raise ValueError('unified program view rules or mapping contract differ')
    # Facade implementation receipts retain producer provenance. Acceptance
    # always rederives the selected unit using current rules; adding a query
    # method does not invalidate unchanged source identities. The instruction
    # generator, wire types and other data dependencies remain exact pins.
    view=ProgramView(report['catalog'])
    if report['parent']!=encode(_artifact(view.catalog.path/'result.json',view.catalog.report['schema'])):
        raise ValueError('unified program view source catalog differs')
    if (report['original_body_bytes_copied']!=0 or any(report[n] is not False for n in
            ('loops_unrolled','effects_proven','runtime_dispatch_proven','target_executed','first_stage_complete'))):
        raise ValueError('identity projections cannot grant effects, execution or transformations')
    expected_tables={u+'/'+name:dict(receipt,path=shard['path']+'/'+receipt['path'])
        for u,shard in report['shards'].items() for name,receipt in shard['tables'].items()}
    if report['tables']!=expected_tables:raise ValueError('unified program view table index differs')
    for identity,shard in report['shards'].items():
        if (identity not in view.catalog.fact_store.rows or shard['path']!='units/'+identity
                or set(shard['tables'])!={'nodes','edges'}
                or any(v['path']!=name+'.jsonl.gz' for name,v in shard['tables'].items())):
            raise ValueError('unified program view shard membership/path differs')
    shard=report['shards'][unit];folder=path/shard['path']
    provider=view.project_unit(unit)
    counts=read_and_validate(folder,shard['tables'],provider)
    if (shard['namespace']!=encode(provider.namespace) or shard['material']!=encode(provider.material.result_artifact)
            or (shard['nodes'],shard['relations'],shard['edge_projections'],shard['templates'])!=
                (counts['nodes'],len(provider.edge_sources),counts['edges'],len(provider.expanded))):
        raise ValueError('unified program view identity, original edge or ownership projection differs')
    provider.material.validate_parents()
    if raw!=(path/'result.json').read_bytes() or current_pins!=_pins():raise ValueError('unified program view changed during read')
    return report,view


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog');parser.add_argument('--unit',action='append',required=True)
    parser.add_argument('--out');parser.add_argument('--read');args=parser.parse_args()
    if args.read:
        if len(args.unit)!=1:parser.error('--read requires one unit for explicit semantic rederivation')
        report,_=read_program_view(args.read,unit=args.unit[0]);status='UNIFIED_PROGRAM_UNIT_REDERIVED'
    else:
        if not args.catalog or not args.out:parser.error('--catalog and --out required')
        report=publish_program_view(args.catalog,args.unit,args.out);status='UNIFIED_PROGRAM_VIEW_PUBLISHED'
    print(json.dumps(dict(status=status,units=len(report['shards']),seconds=report['seconds'])),flush=True)


if __name__ == '__main__': main()
