"""Attach bounded scalar fields to an immutable source dependency graph.

This pass follows published relations rather than rediscovering dispatch. It
does not turn a singleton may field into a constant or a cache/rewrite permit.
Groups retain their parent table row and use a private linear-size transfer
index. Functions, loops, source ports and the parent graph are not cloned.
"""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

from scar.analysis import source_scalar_values, source_builtin_values, constants_v2
from scar.analysis.normal_query import NormalCallGraph
from scar.analysis.normal_output import write_table
from scar.analysis.source_scalar_values import ScalarValueFlow, collect_unit
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import normal_links as F, normal_targets as T
from scar.ir.program import normal_namespaces as N, scalar_values as V
from scar.ir.program import normal_graph as G, source_productions as P
from scar.ir.record_codec import decode


class ScalarGraphOverlay:
    def __init__(self, graph, *, sources=(), limit=4):
        self.graph = graph
        self.flow = ScalarValueFlow(limit=limit)
        self.units = (set(graph.units) if not sources else
            {u for source in sources for u in graph.fact_store.units_for_source(source)})
        if sources and not self.units:
            raise ValueError('selected scalar sources are outside the parent graph')
        self.scopes = None
        if graph.report['analysis_mode'] == 'ENTRY_SCOPED_MAY_ANALYSIS':
            self.scopes = defaultdict(set)
            for record in graph.entry_activations():
                self.scopes[record.target.unit].add(record.target)
            self.units.intersection_update(self.scopes)
        self.stats = Counter()
        self._ports = {}
        self._returns = {}
        self._functions = {}
        self._function_units = set()
        self._module_writes = defaultdict(list)
        self._module_units = set()

    def gp(self, unit, ordinal):
        key = unit.unit, ordinal
        if key not in self._ports:
            port = unit.ports[ordinal]
            if type(port) is dict:
                port = decode(G.Port, port, record_tags=P.PRODUCTION_RECORD_TAGS)
            self._ports[key] = T.GlobalPort(unit.unit, port)
        return self._ports[key]

    def collect(self):
        for identity in sorted(self.units):
            unit = self.graph.fact_store.load(identity)
            scopes = None if self.scopes is None else self.scopes[identity]
            collect_unit(unit, self.flow, scopes=scopes)
            self.stats['collected_units'] += 1
            self.index_module_writes(identity, unit)

    def index_module_writes(self, identity, unit=None):
        if identity in self._module_units:
            return
        unit = self.graph.fact_store.load(identity) if unit is None else unit
        scopes = None if self.scopes is None else self.scopes.get(identity, set())
        allowed_names = None if scopes is None else {i for group in unit.scope_groups
            if group.owner in scopes for span in group.tables
            if span.table is F.FactTable.NAMES for i in range(span.start, span.stop)}
        for index, access in enumerate(unit.names):
            if (access.write and access.namespace.kind is F.NamespaceKind.MODULE
                    and (allowed_names is None or index in allowed_names)):
                self._module_writes[identity, access.namespace.name].append(self.gp(unit, access.value))
        self._module_units.add(identity)

    def group(self, table, ordinal, role, sources, targets, conditions=()):
        sources = tuple(dict.fromkeys(sources))
        targets = tuple(dict.fromkeys(t for t in targets
            if type(t) is T.GlobalPort and t.unit in self.units))
        if not targets:
            return
        if not sources or any(type(p) is not T.GlobalPort for p in sources):
            for target in targets:
                self.flow.open(target, 'scalar relation has no supported original value source: '+table+'/'+role)
            self.stats['unsupported_endpoint_groups'] += 1
            return
        for source in sources:
            if source.unit not in self.units:
                self.flow.open(source, 'source scope lies outside the selected scalar slice')
        group = V.ScalarTransferGroup(table, ordinal, role, sources, targets, tuple(conditions))
        if self.flow.connect_group((table, ordinal, role), group):
            self.stats[table+'/'+role] += 1

    def function(self, source):
        if source.unit not in self._function_units:
            unit = self.graph.fact_store.load(source.unit)
            self._functions.update((self.gp(unit, f.value), (unit, f)) for f in unit.functions)
            self._function_units.add(source.unit)
        return self._functions.get(source)

    def connection(self, table, ordinal, connection, *, conditions=()):
        if connection.source_callable is None:
            return
        if (connection.source_callable.unit not in self.units
                and not any(target.unit in self.units for _, target in connection.returns)):
            return
        if (type(connection) is T.FunctionConnection
                and connection.activation is T.FunctionActivation.CREATE_DEFERRED_BODY):
            self.stats['deferred_creation_routes_not_resumed'] += 1
            return
        if connection.body is None:
            self.stats['non_function_source_call'] += 1
            return
        definition = self.function(connection.source_callable)
        if definition is None:
            raise ValueError('source connection has no original function')
        unit, function = definition
        conditions = tuple(dict.fromkeys((*connection.conditions, *conditions)))
        if table == 'calls':
            if function.environment.kind is not P.DeferredBodyKind.FUNCTION:
                self.stats['deferred_creation_routes_not_resumed'] += 1
                return
        for index, route in enumerate(connection.parameters):
            if route.kind in (T.RouteKind.ARGUMENT, T.RouteKind.INITIAL_DEFAULT,
                              T.RouteKind.CONDITIONAL_DEFAULT):
                self.group(table, ordinal, 'argument/'+str(index), route.actuals,
                    (route.formal,), conditions)
            else:
                # A pack is not an element; environment/state/class routes
                # are separate typed protocols, not scalar reference copies.
                self.stats['non_scalar_route/'+route.kind.value] += 1
        for source, target in connection.returns:
            if type(source) is not T.GlobalPort:
                continue
            if connection.source_callable not in self._returns:
                self._returns[connection.source_callable] = (None
                    if function.returns is None else self.gp(unit, function.returns))
            if source == self._returns[connection.source_callable]:
                self.group(table, ordinal, 'return', (source,), (target,), conditions)
            else:
                self.stats['state_return_not_scalar'] += 1

    def connect(self):
        for ordinal, link in enumerate(self.graph.calls()):
            self.connection('calls', ordinal, link)
        for table, records in (('properties', self.graph.properties()),
                               ('constructions', self.graph.constructions()),
                               ('generator_advances', self.graph.generator_advances())):
            for ordinal, record in enumerate(records):
                if record.connection is not None:
                    self.connection(table, ordinal, record.connection, conditions=record.conditions)
        for ordinal, link in enumerate(self.graph.namespace_lookups()):
            if link.kind is N.NamespaceKind.MODULE and link.result.unit in self.units:
                for identity in link.source_units:
                    self.index_module_writes(identity)
                self.group('namespaces', ordinal, 'module_member',
                    (p for u in link.source_units for p in self._module_writes[u, link.member]),
                    (link.result,), link.conditions)
        for ordinal, link in enumerate(self.graph.attribute_contents()):
            self.group('attribute_content', ordinal, 'field', (link.source,),
                (link.target,), link.conditions)
        for ordinal, factor in enumerate(self.graph.content_factors()):
            self.group('content_factors', ordinal, 'selected_content', factor.sources,
                factor.targets, (factor.semantics, 'PARENT_READ_SELECTOR_CONDITIONS_SELECTED'))
        return self.flow


def build_scalar_graph(targets, out, *, sources=(), limit=4):
    started = time.monotonic()
    def pins():
        modules = (source_scalar_values, source_builtin_values, constants_v2, V)
        return {str(Path(module.__file__).relative_to(Path(__file__).parents[2])):
            sha256(Path(module.__file__).read_bytes()).hexdigest() for module in modules}
    implementation = pins()
    bridge_sha = sha256(Path(__file__).read_bytes()).hexdigest()
    out = Path(out).absolute()
    if out.exists():
        raise ValueError('fresh scalar graph output required')
    graph = NormalCallGraph(targets)
    overlay = ScalarGraphOverlay(graph, sources=sources, limit=limit)
    overlay.collect()
    collected = time.monotonic()
    print(json.dumps(dict(phase='SCALAR_SCOPES_COLLECTED',units=len(overlay.units),
        seconds=collected-started)),file=sys.stderr,flush=True)
    overlay.connect()
    connected = time.monotonic()
    print(json.dumps(dict(phase='SCALAR_RELATIONS_CONNECTED',groups=len(overlay.flow.groups()),
        seconds=connected-started)),file=sys.stderr,flush=True)
    overlay.flow.drain()
    drained = time.monotonic()
    if pins()!=implementation or sha256(Path(__file__).read_bytes()).hexdigest()!=bridge_sha:
        raise ValueError('scalar producer changed during the run; no result published')
    _durable_mkdir(out)
    tables = {name:write_table(out/(name+'.jsonl.gz'), rows) for name, rows in (
        ('operations', overlay.flow.operations()), ('sources', overlay.flow.sources()),
        ('fields', overlay.flow.snapshots()),
        ('groups', overlay.flow.groups()), ('derivations', overlay.flow.derivations()),
        ('obligations', overlay.flow.obligations()))}
    result = dict(schema='scar.source-scalar-graph', schema_version=1,
        status='BOUNDED_SCALAR_FIELD_FIXED_POINT', source_targets=str(graph.path),
        source_targets_sha256=sha256((graph.path/'result.json').read_bytes()).hexdigest(),
        source_target_status=graph.report['status'],
        source_facts_sha256=graph.report['source_facts_sha256'],
        selected_units=sorted(overlay.units), selected_sources=list(sources),
        tables=tables, stats=overlay.flow.stats, bridge_stats=dict(overlay.stats),
        seconds=time.monotonic()-started, phase_seconds=dict(collect=collected-started,
            connect=connected-collected, drain=drained-connected),
        analysis_scope='SELECTED_SOURCE_SCOPES_AND_PARENT_CONDITIONAL_RELATIONS',
        context_sensitive=False, must_value_proven=False, target_executed=False,
        first_stage_complete=False, transformation_authorized=False,
        unbridged_protocols=('PACK_PROJECTION_AND_VARIADIC_VALUE_CONSTRUCTION',
            'CAPTURE_ENVIRONMENT_FIELD_SELECTION', 'GENERATOR_SENT_AND_YIELD_VALUE_RULES',
            'NATIVE_OPERATOR_RESULT_VALUES'),
        implementation_sha256=implementation, bridge_sha256=bridge_sha)
    _durable_bytes(out/'result.json', _json(result), replace=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--targets', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--source', action='append', default=[])
    parser.add_argument('--literal-limit', type=int, default=4)
    args = parser.parse_args()
    result = build_scalar_graph(args.targets, args.out, sources=args.source, limit=args.literal_limit)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
