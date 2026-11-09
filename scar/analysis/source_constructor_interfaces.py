"""Project original constructor interfaces without rebinding calls or bodies.

Construction ports retain their original call/class anchors and roles. Source
new results need not be fresh allocations, and initializer data is discarded.
Only the exact recorded source connection may provide a guarded body entry.
"""
from collections import defaultdict

from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.source_template_links import _json
from scar.ir.program import normal_targets as T, source_constructor_interfaces as C
from scar.ir.program import source_productions as P
from scar.ir.program.source_value_flow import SourceBodyCall
from scar.ir.record_codec import encode


_PENDING = frozenset((T.ConstructionStage.NEW_LOOKUP_PENDING,
    T.ConstructionStage.INIT_LOOKUP_PENDING, T.ConstructionStage.RESULT_TYPE_OPEN))
_SOURCE = frozenset((T.ConstructionStage.SOURCE_NEW, T.ConstructionStage.SOURCE_INIT))


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _site(slicer, identity, record):
    _require(type(identity) is str and bool(identity) and type(record) is SourceBodyCall,
        'constructor site needs its original source unit and typed call record')
    unit, *_ = slicer.unit(identity)
    prefix = slicer.fact(unit, 'calls', 0).locator.rsplit('/', 1)[0] + '/'
    suffix = record.fact.locator.removeprefix(prefix)
    _require(record.fact.locator.startswith(prefix) and suffix.isascii() and suffix.isdecimal(),
        'constructor site must cite its original unit calls table')
    ordinal = int(suffix)
    _require(str(ordinal) == suffix and 0 <= ordinal < len(unit.calls),
        'constructor call locator differs from its canonical original ordinal')
    call = unit.calls[ordinal]
    _require(record.fact == slicer.fact(unit, 'calls', ordinal) and record.call == call,
        'constructor site changed its original source fact or artifact receipt')
    return unit, call


def _endpoint(slicer, point, result, source_class):
    if type(point) is T.GlobalPort:
        slicer.local(point)
    else:
        _require(type(point) is T.ConstructionPort and type(point.role) is T.ConstructionPortKind
            and point.call == result and point.source_class == source_class,
            'constructor endpoint changed its original call/class anchor or role')


def _stage(slicer, unit, call, link):
    result, callee = source_port(unit, call.result), source_port(unit, call.callee)
    before, after = source_port(unit, call.world), source_port(unit, call.result_world)
    _require(link.result == result and link.callee == callee and type(link.stage) is T.ConstructionStage,
        'construction stage differs from its original source call or callee')
    owner, local = slicer.local(link.source_class)
    _require(any(cls.value == local for cls in owner.classes),
        'construction source class is not an original source class definition')
    new_result = T.ConstructionPort(result, link.source_class, T.ConstructionPortKind.NEW_RESULT)
    new_world = T.ConstructionPort(result, link.source_class, T.ConstructionPortKind.NEW_WORLD)
    for point in (*link.inputs, *link.outputs):
        _endpoint(slicer, point, result, link.source_class)
    if link.stage in (T.ConstructionStage.NEW_LOOKUP_PENDING, T.ConstructionStage.OBJECT_NEW,
                      T.ConstructionStage.SOURCE_NEW):
        inputs, outputs = (link.source_class, before), (new_result, new_world)
    elif link.stage in (T.ConstructionStage.INIT_LOOKUP_PENDING, T.ConstructionStage.RESULT_TYPE_OPEN):
        inputs, outputs = (new_result, new_world), ()
    elif link.stage is T.ConstructionStage.EXPLICIT_OBJECT_NEW:
        _require(len(call.positional) == 1 and not call.keywords
            and call.positional_pack is None and call.keyword_pack is None,
            'explicit object allocation lost its original single-class argument layout')
        inputs, outputs = (source_port(unit, call.positional[0]), before), (result, after)
    else:
        inputs, outputs = (new_result, new_world), (result, after)
    _require(link.inputs == inputs and link.outputs == outputs,
        'constructor stage input/output endpoints differ from the original protocol ABI')
    _require(link.stage in _SOURCE or link.connection is None,
        'non-source constructor stage cannot supply a source function connection')
    return new_result, new_world


def _source_entry(slicer, unit, call, link, new_result, new_world):
    connection = link.connection
    _require(type(connection) is T.FunctionConnection,
        'source constructor stage requires its original function connection')
    provider, local = slicer.local(connection.source_callable)
    functions = [fn for fn in provider.functions if fn.value == local]
    _require(len(functions) == 1, 'constructor source callable is absent or ambiguous in original facts')
    fn = functions[0]
    _require(connection.body == T.Body(provider.unit, fn.template, fn.body)
        and len(fn.formals) == len(fn.environment.parameters)+2
        and len(fn.parameter_names) == len(fn.defaults) == len(fn.environment.parameters),
        'constructor source body or original formal/default interface differs')
    formals = tuple(source_port(provider, point) for point in fn.formals)
    expected_activation = (T.FunctionActivation.NORMAL if fn.environment.kind is P.DeferredBodyKind.FUNCTION
        else T.FunctionActivation.CREATE_DEFERRED_BODY)
    _require(connection.activation is expected_activation,
        'constructor connection confused ordinary body entry and deferred body creation')
    new = link.stage is T.ConstructionStage.SOURCE_NEW
    required = ('NEW_RECEIVES_SOURCE_CLASS',) if new else (
        'NEW_RESULT_IS_REQUESTED_CLASS_INSTANCE', 'INIT_DATA_RETURN_DISCARDED')
    _require(set(required) <= set(link.conditions) <= set(connection.conditions),
        'constructor source connection lost its original stage/type-call guards')
    for route in connection.parameters:
        allowed = (formals[0],) if route.kind is T.RouteKind.FUNCTION_ENVIRONMENT else (
            (formals[-1],) if route.kind is T.RouteKind.STATE else formals[1:-1])
        _require(route.formal in allowed, 'constructor route is not an original function formal of this kind')
        for point in route.actuals:
            _endpoint(slicer, point, link.result, link.source_class)
    environment = [route for route in connection.parameters if route.kind is T.RouteKind.FUNCTION_ENVIRONMENT]
    state = [route for route in connection.parameters if route.kind is T.RouteKind.STATE]
    _require(len(environment) == 1 and environment[0].actuals == (connection.source_callable,),
        'constructor environment must use the selected original function, not the class-call callee')
    world = source_port(unit, call.world) if new else new_world
    _require(len(state) == 1 and state[0].actuals == (world,),
        'constructor source body receives a different original protocol world')
    if new:
        _require(any(link.source_class in route.actuals and route.kind in (
            T.RouteKind.ARGUMENT, T.RouteKind.CLASS_RECEIVER, T.RouteKind.PACK_POSITIONALS)
            for route in connection.parameters), 'source new does not receive this original source class')
    else:
        _require(any(new_result in route.actuals and route.kind in (
            T.RouteKind.ARGUMENT, T.RouteKind.CLASS_RECEIVER, T.RouteKind.PACK_POSITIONALS)
            for route in connection.parameters), 'initializer receiver does not come from this constructor NEW_RESULT')
    packs = connection.argument_packs
    positional = None if call.positional_pack is None else source_port(unit, call.positional_pack)
    keywords = None if call.keyword_pack is None else source_port(unit, call.keyword_pack)
    _require((packs is not None) == (positional is not None or keywords is not None),
        'constructor connection lost its original evaluated argument packs')
    if packs is not None:
        _require(packs.positional == positional and packs.keywords == keywords,
            'constructor argument packs differ from the original source call')
        for point in (packs.receiver, packs.class_receiver):
            if point is not None: _endpoint(slicer, point, link.result, link.source_class)
    for projection in connection.projections:
        _require(projection.formal in formals[1:-1] and projection.pack in (positional, keywords),
            'constructor projection changed its original parameter or evaluated source pack')
        _endpoint(slicer, projection.pack, link.result, link.source_class)
    for source, target in connection.returns:
        _endpoint(slicer, source, link.result, link.source_class)
        _endpoint(slicer, target, link.result, link.source_class)
    if connection.activation is not T.FunctionActivation.NORMAL:
        _require(not connection.returns, 'deferred constructor creation cannot claim ordinary body returns')
        return 'DEFERRED_BODY_CREATION_IS_NOT_BODY_ENTRY'
    expected = ((source_port(provider, fn.returns), new_result),) if new and fn.returns is not None else ()
    if fn.return_world is not None:
        expected = (*expected, (source_port(provider, fn.return_world),
            new_world if new else source_port(unit, call.result_world)))
    _require(connection.returns == expected,
        'constructor source return crossed NEW_RESULT/NEW_WORLD or included discarded initializer data')
    if fn.return_world is None or new and fn.returns is None:
        return 'CONSTRUCTOR_SOURCE_NORMAL_RETURN_INTERFACE_UNRESOLVED'
    return None


def project_constructor_interfaces(snapshot, sites):
    """Project all recorded class/stage alternatives in one constructions scan.

    Site ordinals retain the supplied order, including repeated source sites.
    Every step keeps its original historical evidence and connection. No call
    is rebound, no completion is added, and no source body is copied or run.
    The caller owns the snapshot's final parent-guard validation.
    """
    slicer = ReferenceSlicer(snapshot); records = []; selected_sites = defaultdict(list)
    wanted = set(); wanted_units = set()
    for identity, record in sites:
        unit, call = _site(slicer, identity, record)
        index = len(records); records.append(C.ConstructorInterfaceSite(identity, record))
        result = source_port(unit, call.result)
        selected_sites[result].append((index, unit, call))
        wanted.add(_json(encode(result))); wanted_units.add(identity)
    steps = []; entries = []; frontiers = []
    for _, link, evidence in snapshot.rows('constructions', lambda wire:
            wire['result']['unit'] in wanted_units and _json(wire['result']) in wanted, T.ConstructionLink):
        for site, unit, call in selected_sites[link.result]:
            new_result, new_world = _stage(slicer, unit, call, link)
            step = len(steps); steps.append(C.ConstructorInterfaceStep(site, evidence, link))
            if link.stage in _PENDING:
                frontiers.append(C.ConstructorInterfaceFrontier(step, link.stage.value+'_UNRESOLVED'))
            elif link.stage in _SOURCE:
                reason = _source_entry(slicer, unit, call, link, new_result, new_world)
                if reason is None:
                    entries.append(C.ConstructorBodyEntry(step, link.connection))
                else:
                    frontiers.append(C.ConstructorInterfaceFrontier(step, reason))
    return C.ConstructorInterfaceGraph(tuple(records), tuple(steps), tuple(entries), tuple(frontiers))
