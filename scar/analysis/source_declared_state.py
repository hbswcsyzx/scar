"""Join source state projections to verified declared context edges.

The join retains the Python data return and state return separately from the
content argument. Declared interfaces do not admit scopes or establish which
input or later state versions occur at runtime.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis import normal_facts, source_configuration_state_binding, source_declared_graph
from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.source_configuration_state_binding import read_configuration_state_bindings
from scar.analysis.source_declared_graph import read_declared_graph
from scar.analysis.source_reference_slice import source_port
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_template_links import _json
from scar.ir.program import declared_state_connections as S, normal_targets as T, source_productions as P
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import decode, encode


_SCHEMA = 'scar.declared-state-connections'
_STATUS = 'GUARDED_DECLARED_SOURCE_STATE_INTERFACE_JOIN'
_UNPROVEN = 'INPUT_CONTENT_AT_CALL_AND_LATER_STATE_VERSIONS_REMAIN_UNPROVEN'
_FALSE_FLAGS = (
    'source_scope_activation_proven', 'entry_admission_proven', 'runtime_dispatch_proven',
    'input_versions_at_call_proven', 'current_state_versions_proven', 'current_task_fields_proven',
    'transformation_authorized', 'target_executed', 'first_stage_complete',
)
_PARENT_SCHEMAS = dict(boundaries='scar.configuration-state-bindings', contexts='scar.declared-context-graph')


def _artifact(path, schema):
    path = Path(path).absolute(); raw = path.read_bytes()
    return ProviderArtifact(str(path), sha256(raw).hexdigest(), len(raw), schema)


def _parents(boundaries, contexts):
    return {name: _artifact(Path(path)/'result.json', _PARENT_SCHEMAS[name])
        for name, path in (('boundaries', boundaries), ('contexts', contexts))}


def _table_artifact(root, receipt, schema):
    return ProviderArtifact(str(Path(root).absolute()/receipt['path']), receipt['sha256'], receipt['bytes'], schema)


def _validate_tables(tables):
    if any(_artifact(row.uri, row.schema) != row for row in tables.values()):
        raise ValueError('declared state parent table receipt changed')


def _pins():
    return {name: sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ('publisher', __file__), ('types', S.__file__), ('facts', normal_facts.__file__),
        ('boundaries', source_configuration_state_binding.__file__), ('contexts', source_declared_graph.__file__))}


def _source_row(reference):
    """Compare a physical original row across its two parent schema views.

    The verified boundary and context producers label unit-fact artifacts
    differently. URI, stored hash, byte count and locator must still agree;
    neither reference is substituted with a historical context-call row.
    """
    artifact = reference.artifact
    return artifact.uri, artifact.sha256, artifact.size_bytes, reference.locator


def _function(store, point):
    unit = store.load(point.unit)
    matches = [fn for fn in unit.functions if source_port(unit, fn.value) == point]
    if len(matches) != 1:
        raise ValueError('declared state source function is absent or ambiguous in original facts')
    return unit, matches[0]


def _routes(binding, connection, unit, function):
    content = [route for route in connection.parameters if route.kind is T.RouteKind.ARGUMENT
        and binding.receiver in route.actuals]
    state = [route for route in connection.parameters if route.kind is T.RouteKind.STATE
        and binding.world_before in route.actuals]
    data_return = binding.normal_return, binding.data_result
    if function.returns is None or function.return_world is None:
        raise ValueError('declared state source body has no original normal data/state return')
    state_return = source_port(unit, function.return_world), binding.world_after
    if (connection.activation is not T.FunctionActivation.NORMAL
            or len(content) != 1 or content[0].actuals != (binding.receiver,)
            or len(state) != 1 or state[0].actuals != (binding.world_before,)
            or binding.normal_return != source_port(unit, function.returns)
            or data_return not in connection.returns or state_return not in connection.returns):
        raise ValueError('declared state join crossed an original content, world or Python data-return route')
    return content[0], state[0], data_return, state_return


def _derive(boundaries, contexts):
    boundary_report, bindings = read_configuration_state_bindings(boundaries)
    context_report, graph, _ = read_declared_graph(contexts)
    store = SourceFactStore(boundary_report['facts'])
    tables = dict(
        projections=_table_artifact(boundaries, boundary_report['bindings'], 'scar.source-state-projections'),
        edges=_table_artifact(contexts, context_report['tables']['edges'], 'scar.declared-context-edges'))
    edges = {}
    for index, edge in enumerate(graph.edges):
        edges.setdefault((_source_row(edge.call), edge.connection.source_callable), []).append((index, edge))
    connections = []; obligations = []
    for ordinal, binding in enumerate(bindings):
        unit, function = _function(store, binding.source_function)
        caller_unit = store.load(binding.caller.owner.unit)
        callers = [fn for fn in caller_unit.functions if fn.body_scope == binding.caller]
        if len(callers) != 1:
            raise ValueError('state projection has no unique original caller function scope')
        caller_fn = callers[0]
        expected_caller = source_port(caller_unit, caller_fn.value)
        caller_body = T.Body(caller_unit.unit, caller_fn.template, caller_fn.body)
        body = T.Body(unit.unit, function.template, function.body)
        matched = False
        for edge_index, edge in edges.get((_source_row(binding.call), binding.source_function), ()):
            caller = graph.contexts[edge.caller]; target = graph.contexts[edge.target]
            if (caller.source_callable != expected_caller or caller.body != caller_body
                    or edge.connection.body != body or target.body != body
                    or target.source_callable != binding.source_function):
                continue
            content, state, data_return, state_return = _routes(binding, edge.connection, unit, function)
            conditions = tuple(dict.fromkeys((*edge.conditions, *edge.connection.conditions,
                *binding.conditions, _UNPROVEN)))
            connections.append(S.DeclaredStateConnection(
                ProviderFactReference(tables['projections'], '#/records/'+str(ordinal)),
                ProviderFactReference(tables['edges'], '#/records/'+str(edge_index)),
                edge.connection, content, state, data_return, state_return, conditions))
            matched = True
        if not matched:
            obligations.append(S.DeclaredStateObligation(ordinal, 'BOUNDARY_NOT_CONNECTED_IN_DECLARED_CONTEXTS',
                'No declared edge matches this original call, caller scope and source-function body.'))
        obligations.extend((
            S.DeclaredStateObligation(ordinal, 'INPUT_VERSIONS_AT_CALL_NOT_PROVEN',
                'Matching declared interfaces does not select the input-content version at this call world.'),
            S.DeclaredStateObligation(ordinal, 'LATER_STATE_VERSIONS_NOT_PROVEN',
                'The projection concerns the content argument at the post-call world; later task state remains open.'),
            S.DeclaredStateObligation(ordinal, 'DECLARED_INTERFACE_IS_NOT_SCOPE_ADMISSION',
                'Scope entry and normal completion remain parent conditions, not admission evidence.')))
    counts = dict(boundaries=len(bindings), connections=len(connections), obligations=len(obligations),
        matched_boundaries=len({row.projection.locator for row in connections}),
        parent_contexts=len(graph.contexts), parent_edges=len(graph.edges), parent_frontiers=len(graph.frontiers))
    _validate_tables(tables)
    return tuple(connections), tuple(obligations), counts, tables


def build_declared_state(boundaries, contexts, out):
    started = time.monotonic(); pins = _pins()
    boundaries = Path(boundaries).absolute(); contexts = Path(contexts).absolute(); out = Path(out).absolute()
    if out.exists():
        raise ValueError('fresh declared state connection output required')
    parents = _parents(boundaries, contexts)
    connections, obligations, counts, parent_tables = _derive(boundaries, contexts)
    if _parents(boundaries, contexts) != parents or _pins() != pins:
        raise ValueError('declared state parents or producer changed during derivation')
    _durable_mkdir(out)
    tables = dict(connections=write_table(out/'connections.jsonl.gz', connections),
        obligations=write_table(out/'obligations.jsonl.gz', obligations))
    report = dict(schema=_SCHEMA, schema_version=1, status=_STATUS, pins=pins,
        boundaries=str(boundaries), contexts=str(contexts), parents={k: encode(v) for k, v in parents.items()},
        parent_tables={k: encode(v) for k, v in parent_tables.items()}, tables=tables, counts=counts,
        semantics=S.SEMANTICS, historical_call_rows_modified=False, source_regions_shared=True,
        seconds=time.monotonic()-started, **{name: False for name in _FALSE_FLAGS})
    _validate_tables(parent_tables)
    if _parents(boundaries, contexts) != parents or _pins() != pins:
        raise ValueError('declared state parents or producer changed during publication')
    _durable_bytes(out/'result.json', _json(report), replace=False)
    return report


def read_declared_state(path):
    path = Path(path).absolute(); raw = (path/'result.json').read_bytes(); report = json.loads(raw)
    if ((report['schema'], report['schema_version'], report['status']) != (_SCHEMA, 1, _STATUS)
            or type(report['schema_version']) is not int or report['pins'] != _pins()):
        raise ValueError('declared state connection producer differs')
    parents = _parents(report['boundaries'], report['contexts'])
    if {k: encode(v) for k, v in parents.items()} != report['parents']:
        raise ValueError('declared state parent result receipt differs')
    connections = tuple(decode(S.DeclaredStateConnection, row, record_tags=P.PRODUCTION_RECORD_TAGS)
        for row in _table(path, report['tables']['connections']))
    obligations = tuple(decode(S.DeclaredStateObligation, row)
        for row in _table(path, report['tables']['obligations']))
    expected, pending, counts, parent_tables = _derive(report['boundaries'], report['contexts'])
    if (connections != expected or obligations != pending or report['counts'] != counts
            or report['parent_tables'] != {k: encode(v) for k, v in parent_tables.items()}
            or report['semantics'] != S.SEMANTICS):
        raise ValueError('declared state evidence, routes, conditional guards or denominators differ')
    if (any(report[name] is not False for name in _FALSE_FLAGS)
            or report['historical_call_rows_modified'] is not False or report['source_regions_shared'] is not True):
        raise ValueError('declared state interfaces cannot grant scope admission, current content or runtime authority')
    if (_parents(report['boundaries'], report['contexts']) != parents
            or report['pins'] != _pins() or (path/'result.json').read_bytes() != raw):
        raise ValueError('declared state graph or parents changed during verification')
    _validate_tables(parent_tables)
    return report, connections, obligations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boundaries'); parser.add_argument('--contexts'); parser.add_argument('--out')
    parser.add_argument('--read')
    args = parser.parse_args()
    if args.read:
        report, _, _ = read_declared_state(args.read)
    else:
        if not args.boundaries or not args.contexts or not args.out:
            parser.error('--boundaries, --contexts and --out required')
        report = build_declared_state(args.boundaries, args.contexts, args.out)
    print(json.dumps(dict(status=report['status'], counts=report['counts'])), flush=True)


if __name__ == '__main__':
    main()
