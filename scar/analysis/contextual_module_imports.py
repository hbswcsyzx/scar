"""Conditional source modules for original contextual import-result ports.

The requested spelling/level/fromlist are original source/compiler operands.
A separately declared package candidate can resolve a relative request, but
never becomes the runtime __package__, an executed import or a closed source
set. This adapter does not modify historical import routes or wire records.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, replace

from scar.analysis.static_imports import _unit_mappings, _importer_contexts, _resolve_from
from scar.analysis.static_namespace import normal_reference
from scar.ir.program.dependencies import (DependencyCondition as Condition,
    DependencyEvidence as Evidence, DependencyFrontier as Frontier,
    DependencyPoint as Point, GraphNamespace)
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import LiteralOrigin, ReferenceValue, StateVersionValue
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.static_calls import StaticImportFromRequest
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.v2.common import SourceReference


@dataclass(frozen=True, slots=True)
class ContextualModuleImport:
    origin: Point
    operation: OperationID
    source: SourceReference
    requested_spelling: str
    relative_level: int
    resolved_module: str
    module: SourceBodyNamespace
    locals_namespace: ValueID
    globals_namespace: ValueID
    entry_world: ValueID
    world: UseID
    normal: ControlEdgeReference
    conditions: tuple[Condition, ...]
    evidence: tuple[Evidence, ...]
    request: StaticImportFromRequest | None = None
    package_context: str | None = None

    def __post_init__(self):
        for value, kind in ((self.origin, Point), (self.operation, OperationID),
                (self.source, SourceReference), (self.module, SourceBodyNamespace),
                (self.locals_namespace, ValueID), (self.globals_namespace, ValueID),
                (self.entry_world, ValueID), (self.world, UseID),
                (self.normal, ControlEdgeReference)):
            if type(value) is not kind:
                raise TypeError('contextual import needs exact ' + kind.__name__)
            value.__post_init__()
        if (type(self.origin.node) is not ValueID or self.normal.operation != self.operation
                or type(self.requested_spelling) is not str
                or type(self.relative_level) is not int or self.relative_level < 0
                or type(self.resolved_module) is not str or not self.resolved_module
                or self.module.source is not None):
            raise ValueError('contextual import changed its original request/module/normal ports')
        for rows, kind in ((self.conditions, Condition), (self.evidence, Evidence)):
            if type(rows) is not tuple or not rows or any(type(row) is not kind for row in rows):
                raise TypeError('contextual import needs nonempty typed conditions/evidence')
        if self.request is not None:
            if type(self.request) is not StaticImportFromRequest:
                raise TypeError('FROM import must retain its exact original request')
            self.request.__post_init__()
            if self.request.fromlist_constant.source != self.source:
                raise ValueError('FROM import changed its original fromlist source')
        elif self.relative_level:
            raise ValueError('relative import requires its original FROM request')
        if self.relative_level:
            if type(self.package_context) is not str or not self.package_context:
                raise ValueError('relative import needs its declared package candidate')
            if not any(condition.domain == 'scar.contextual-import'
                    and condition.name == 'CURRENT_IMPORT_PACKAGE_CONTEXT_MATCHES_DECLARED_CANDIDATE'
                    and condition.subject == self.origin and condition.operands
                    and type(condition.index) is int for condition in self.conditions):
                raise ValueError('relative import cannot drop its declared-package predicate')
        elif self.package_context is not None:
            raise ValueError('an absolute request has no inferred package-context requirement')

    @property
    def module_context(self):
        return None


class ContextualImportSources:
    """One bounded source query, sharing the resolver's original input owner.

    Only the last point's diagnostics are retained. Derived routes are freshly
    recomputed; original module/source indices remain owned by the resolver.
    """
    def __init__(self, resolver):
        self.resolver = resolver
        self._point = None
        self._frontiers = {}

    def _note(self, point, kind, detail):
        self._frontiers[Frontier(point, kind, detail)] = None

    def frontiers_for(self, point):
        return tuple(self._frontiers) if self._point == point else ()

    def _unit(self, body):
        number = body.context.number
        unit = self.resolver.owner.units[number]
        if unit['path'] != body.metadata.source.path:
            raise ValueError('contextual importer unit differs from its original source body')
        return number, unit

    def _declaration(self, number, suffix=''):
        session = self.resolver.session
        artifact = session.manifest_artifact
        locator = SourceArtifactLocator(artifact, artifact.sha256, artifact.size_bytes,
            'canonical-json', '#/units/' + str(number) + suffix)
        session.read_artifact(locator)
        return locator

    def _mapping(self, number, unit, module_name, source_root):
        rows = unit.get('module_mappings')
        if type(rows) is list:
            for ordinal, row in enumerate(rows):
                if type(row) is dict and row.get('name') == module_name and row.get('source_root') == source_root:
                    return ordinal, self._declaration(number, '/module_mappings/' + str(ordinal))
        names = unit.get('module_names')
        if type(names) is list and unit.get('namespace_root') == source_root:
            for ordinal, name in enumerate(names):
                if name == module_name:
                    return ordinal, self._declaration(number, '/module_names/' + str(ordinal))
        raise ValueError('declared package candidate has no exact original unit-mapping provenance')

    def _module_ports(self, body):
        facts = self.resolver.modules._index(body)
        if facts.module is None or len(body.graph.frame_roots) != 1 or body.namespace.source is not None:
            return None
        frame = body.graph.frame_roots[0].entry
        for value in (frame.locals_namespace, frame.globals_namespace):
            if type(body.index.values.get(value)) is not ReferenceValue:
                raise ValueError('source module namespace is not its original reference')
        if type(body.index.values.get(frame.world)) is not StateVersionValue:
            raise ValueError('source module entry world is not its original state value')
        return frame

    def _record(self, *, body, origin, operation, source, spelling, level,
            resolved, module, world, normal, namespaces, conditions,
            request=None, package=None, package_mapping=None):
        frame = self._module_ports(module)
        if frame is None:
            self._note(origin, 'CONTEXTUAL_IMPORT_SOURCE_MODULE_INTERFACE_UNAVAILABLE',
                'A declared module candidate has no retained original L/G/world module initializer interface.')
            return None
        source_number, _ = self._unit(body)
        module_number, _ = self._unit(module)
        module_ns = GraphNamespace.from_source(module.namespace)
        module_g = Point(module_ns, frame.globals_namespace, None)
        module_world = Point(module_ns, frame.world, None)
        at = lambda node: Point(origin.namespace, node, origin.context)
        operands = tuple(at(use) for use in namespaces)
        if request is not None:
            operands += tuple(at(use) for use in (request.requested_use, request.level_use, request.fromlist_use))
        operands += (at(world), module_g, module_world)
        selected = [replace(Condition.from_enum(condition), subject=origin, operands=operands)
            for condition in conditions]
        selected.append(Condition('scar.contextual-import',
            'IMPORT_NORMAL_RESULT_DENOTES_DECLARED_SOURCE_MODULE', origin,
            operands=(at(operation), *operands)))
        sources = [origin.namespace.graph, replace(origin.namespace.graph, pointer='#'),
            module.namespace.graph,
            self._declaration(source_number), self._declaration(module_number)]
        if request is not None:
            selected.append(Condition('scar.contextual-import',
                'FROM_IMPORT_NORMAL_RETURNS_RESOLVED_MODULE', origin,
                operands=(at(operation), *operands)))
        if package_mapping is not None:
            ordinal, mapping_source = package_mapping
            selected.append(Condition('scar.contextual-import',
                'CURRENT_IMPORT_PACKAGE_CONTEXT_MATCHES_DECLARED_CANDIDATE', origin,
                ordinal, operands))
            sources.append(mapping_source)
        evidence = Evidence('CONTEXTUAL_IMPORT_DECLARED_MODULE_SOURCE_V1',
            tuple(dict.fromkeys(sources)), tuple(dict.fromkeys((origin, at(operation), *operands))))
        return ContextualModuleImport(origin, operation, source, spelling, level, resolved,
            module.namespace, frame.locals_namespace, frame.globals_namespace, frame.world,
            world, normal, tuple(dict.fromkeys(selected)), (evidence,), request, package)

    def sources(self, origin):
        if type(origin) is not Point or type(origin.node) is not ValueID or origin.namespace.source_body is None:
            raise TypeError('contextual import origin must be an original source IMPORT_NAME normal Value point')
        origin.__post_init__()
        self._point, self._frontiers = origin, {}
        resolver = self.resolver
        records = {}
        request_source = None

        def admit(record, maximum):
            if record not in records and len(records) >= maximum:
                raise OverflowError('contextual import source candidate budget exhausted')
            records[record] = None
        try:
            resolver.owner._check()
            body = resolver._body(origin.namespace)
            facts = resolver.modules._index(body)
            operation = facts.normal_producers.get(origin.node)
            if operation is None or facts.protocols.get(operation) not in ('IMPORT_NAME_314', 'FUNCTION_IMPORT_NAME'):
                raise ValueError('contextual import origin is not an original IMPORT_NAME normal result')
            source_links = [row for row in facts.links if row.operation == operation]
            if len(source_links) != 1:
                raise ValueError('import request lacks its unique original source link')
            request_source = source_links[0].source
            actual = body.index.operations[operation]
            worlds = [use for use in actual.uses if type(body.index.values[use.value]) is StateVersionValue]
            if len(worlds) != 1:
                raise ValueError('import request lost its unique original world Use')
            world = worlds[0].id
            normal = normal_reference(body.index, operation, blocks=resolver.owner._namespace_for(body).blocks)
            if normal is None or normal[1] != origin.node:
                raise ValueError('import origin changed its original normal payload0 port')
            count = 3 if facts.protocols[operation] == 'IMPORT_NAME_314' else 2
            namespaces = tuple(use.id for use in actual.uses[:count])
            maximum = resolver.session.budget.max_entry_projections
            from_selected = facts.from_requests.get(operation)
            if from_selected is None:
                # A template's empty requirements mean no CALL support; they
                # never replace origin.context with a closed root selection.
                for route in resolver.modules.imports_for_result(body, origin.node, requirements=()):
                    resolver.owner._check()
                    module = resolver._body(GraphNamespace.from_source(route.module_body))
                    record = self._record(body=body, origin=origin, operation=operation,
                        source=route.source, spelling=route.requested, level=0,
                        resolved=route.returned_module, module=module, world=world,
                        normal=normal[0], namespaces=namespaces, conditions=route.conditions)
                    if record is not None:
                        admit(record, maximum)
            else:
                node, source, request = from_selected
                if type(node) is not ast.ImportFrom or type(request) is not StaticImportFromRequest:
                    raise ValueError('FROM source index changed its original request types')
                spelling, level = node.module or '', node.level
                for use, expected in ((request.requested_use, spelling), (request.level_use, level)):
                    site = body.index.use_site(use)
                    value = body.index.values[site.use.value]
                    if (site.operation != operation or type(value.origin) is not LiteralOrigin
                            or type(value.origin.value) is not type(expected) or value.origin.value != expected):
                        raise ValueError('FROM request spelling/level differs from original source/compiler operands')
                fromlist = body.index.use_site(request.fromlist_use)
                if fromlist.operation != operation or request.fromlist_constant.source != source:
                    raise ValueError('FROM request changed its original code-constant fromlist endpoint')
                importer_number, unit = self._unit(body)
                choices = []
                if level == 0:
                    resolved, status = _resolve_from(spelling, 0, None)
                    if status == 'OK':
                        choices.append((resolved, None, None))
                    else:
                        self._note(origin, 'CONTEXTUAL_IMPORT_ABSOLUTE_REQUEST_UNSUPPORTED', status)
                else:
                    issues = []
                    mappings = _unit_mappings(unit, issues)
                    for issue in issues:
                        self._note(origin, 'CONTEXTUAL_IMPORT_DECLARED_PACKAGE_MAPPING_OPEN',
                            issue['kind'] + ': ' + issue.get('detail', 'Original source mapping is incomplete.'))
                    contexts = _importer_contexts(unit, mappings)
                    if not contexts:
                        self._note(origin, 'CONTEXTUAL_IMPORT_PACKAGE_CANDIDATE_UNAVAILABLE',
                            'No supplied source-unit mapping provides a declared package candidate; runtime __package__ is not guessed.')
                    for context in contexts:
                        resolver.owner._check()
                        package = context['package_context']
                        resolved, status = _resolve_from(spelling, level, package)
                        if status != 'OK':
                            self._note(origin, 'CONTEXTUAL_IMPORT_RELATIVE_CANDIDATE_' + status,
                                'Declared package ' + repr(package) + ' cannot resolve original level ' + str(level)
                                + '; this does not establish the runtime package context.')
                            continue
                        mapping = self._mapping(importer_number, unit,
                            context['module_name'], context['source_root'])
                        choices.append((resolved, package, mapping))
                from scar.ir.program.static_calls import MODULE_FLOW_BASE_CONDITIONS
                for resolved, package, mapping in tuple(dict.fromkeys(choices)):
                    candidates = 0
                    for module in resolver._module_bodies(resolved):
                        resolver.owner._check()
                        candidates += 1
                        record = self._record(body=body, origin=origin, operation=operation,
                            source=source, spelling=spelling, level=level, resolved=resolved,
                            module=module, world=world, normal=normal[0], namespaces=namespaces,
                            conditions=MODULE_FLOW_BASE_CONDITIONS[:4], request=request,
                            package=package, package_mapping=mapping)
                        if record is not None:
                            admit(record, maximum)
                    if not candidates:
                        self._note(origin, 'CONTEXTUAL_IMPORT_SOURCE_MODULE_UNAVAILABLE',
                            'No supplied canonical source module matches declared candidate ' + resolved + '.')
            if not records:
                self._note(origin, 'CONTEXTUAL_IMPORT_SOURCE_SET_UNCONNECTED',
                    'No supported declared source-module candidate supplies this exact original import result/context.')
            # Retain a missing source/compiler request adapter as that exact
            # gap, rather than replacing it with a generic absent candidate.
            for frontier in resolver.modules._permanent_frontiers.get(body.namespace, ()):
                if frontier.source is None or frontier.source == request_source:
                    self._note(origin, frontier.kind, frontier.detail)
        except (OverflowError, TimeoutError) as error:
            self._note(origin, 'CONTEXTUAL_IMPORT_SOURCE_BUDGET', type(error).__name__ + ': ' + str(error))
        self._note(origin, 'CONTEXTUAL_IMPORT_LOADER_AND_STATE_OPEN',
            'Import hooks/cache, package selection, source initialization and mutable module state remain conditional; known candidates do not close the source set.')
        return tuple(records)

    def validate(self, record):
        if type(record) is not ContextualModuleImport:
            raise TypeError('expected ContextualModuleImport')
        record.__post_init__()
        replay = self.sources(record.origin)
        if any(frontier.kind == 'CONTEXTUAL_IMPORT_SOURCE_BUDGET' for frontier in self.frontiers_for(record.origin)):
            raise OverflowError('fresh contextual import replay did not complete its bounded source demand')
        if record not in replay:
            raise ValueError('contextual module import differs from fresh original request/declaration/ports')
        return True


def module_import_sources(resolver, origin):
    """Convenience API retaining one resolver-owned diagnostics collector."""
    collector = getattr(resolver, '_contextual_import_sources', None)
    if collector is None:
        collector = ContextualImportSources(resolver)
        resolver._contextual_import_sources = collector
    elif type(collector) is not ContextualImportSources or collector.resolver is not resolver:
        raise ValueError('resolver contextual import collector belongs to another input owner')
    return collector.sources(origin)


__all__ = ['ContextualModuleImport', 'ContextualImportSources', 'module_import_sources']
