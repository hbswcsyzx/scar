"""Optional close declarations cannot erase original C1 continuations."""
from dataclasses import replace

import pytest

from scar.ir.program.model import ExitKind
from scar.ir.program.protocol_connections import InjectedPacketTrigger, ProtocolOperationRef
from scar.ir.program.protocols import StaticProtocolGap
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import SuspendTerminator
from scar.ir.program.validation import require_valid
from tests.fixtures.program_packet_continuation_graphs import packet_continuation_program


def _site(row):
    return ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)


def _report(program, details):
    require_valid(replace(program, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=()))
    require_valid(program)
    report = ProgramIndex(program).protocol_obligations(details['scope'], budget=262144)
    assert report['budget']['truncated'] is False
    assert not report['connections']['issues']
    assert report['source_runtime_verified'] is False
    assert report['transformation_authorized'] is False
    return report['connections']['families']


def _close_entries(report, sites):
    entries = {entry['site']: entry for entry in report['continuations']['obligations']
               if entry['site'] in sites}
    assert set(entries) == sites
    return entries


def _routes(entries):
    result = {}
    for site, entry in entries.items():
        routes = entry.get('close_routes', ())
        assert len(routes) == 1, (site, entry)
        result[site] = routes[0]
    return result


def _common_entries(report, name, sites):
    entries = {entry['site']: entry for entry in report['common'][name]
               if entry['site'] in sites}
    assert set(entries) == sites
    return entries


def _topology(route):
    """Compare canonical endpoints, independently of source binding reports."""
    return {
        'targets': frozenset(route['targets']),
        'actions': frozenset(item['action'].operation for item in route['actions']),
        'projections': frozenset((item['operation'].id, item['successor_index'],
            item['argument_index'], item['selector'], item['port'], item['formal'].id)
            for item in route['projections']),
        'suspensions': frozenset(item['operation'].id for item in route['suspensions']),
    }


def _host_checks(route, host):
    checks = tuple(item for item in route['checks'] if item['target'] == host)
    assert checks
    return checks


def _flags(route):
    assert route['frontier_only'] is False
    assert route['source_runtime_verified'] is False
    assert route['runtime_identity_verified'] is False
    assert route['transformation_authorized'] is False


@pytest.mark.parametrize('deleted', ('consumers', 'inputs-and-consumers'))
def test_optional_close_tables_do_not_define_the_two_original_c1_continuations(deleted):
    program, details = packet_continuation_program(two_cuts=True, complete_transitions=True)
    sites = {_site(row) for row in details['rows']}
    assert len(sites) == 2
    operations = {operation.id: operation for operation in program.operations}
    by_kind = {}
    for row in details['rows']:
        result = row.contract.result
        assert result.edge.operation == row.operation == details['helper']
        assert result.edge.successor_index == row.slot
        edge = operations[row.operation].terminator.successors[result.edge.successor_index]
        by_kind[edge.kind] = _site(row)
    assert set(by_kind) == {ExitKind.NORMAL, ExitKind.RAISE}
    assert sum(type(operation.terminator) is SuspendTerminator
               for operation in program.operations) == 2

    baseline = _report(program, details)
    original_entries = _close_entries(baseline, sites)
    original_routes = _routes(original_entries)
    original_consumers = _common_entries(baseline, 'consumers', sites)
    for site, route in original_routes.items():
        assert original_entries[site]['row'] in details['rows']
        assert route['status'] == 'DECLARED'
        assert route['known_inventory_complete'] is True
        assert route['actions'] and route['projections']
        assert details['replacement'] in _topology(route)['actions']
        # Both own N and own R reach this same original second cut. A handled
        # branch that never called close is not its NORMAL completion.
        assert _topology(route)['suspensions'] == {details['second_suspend']}
        assert details['host_packet'] in route['targets']
        assert all(item['binding']['match'] is True
                   for item in _host_checks(route, details['host_packet']))
        _flags(route)

    normal_site, raise_site = by_kind[ExitKind.NORMAL], by_kind[ExitKind.RAISE]
    normal_attachment, = tuple(row for row in program.protocol_call_inputs
                               if row.site == normal_site)
    normal_case, = normal_attachment.cases
    assert type(normal_case.trigger) is InjectedPacketTrigger
    assert original_routes[normal_site]['source'] == normal_case.trigger.packet
    assert original_routes[normal_site]['source'] != original_entries[normal_site]['row'].contract.result
    assert original_routes[raise_site]['source'] == original_entries[raise_site]['row'].contract.result

    changed = replace(program,
        protocol_call_inputs=tuple(row for row in program.protocol_call_inputs
            if not (deleted == 'inputs-and-consumers' and row.site in sites)),
        protocol_result_consumers=tuple(row for row in program.protocol_result_consumers
                                       if row.site not in sites))
    # Every canonical operation, value, state, control port, cleanup action,
    # pending definition and cut is exactly the original record. Only the two
    # optional declaration tables differ.
    assert replace(changed, protocol_call_inputs=program.protocol_call_inputs,
        protocol_result_consumers=program.protocol_result_consumers) == program
    partial = _report(changed, details)
    entries = _close_entries(partial, sites)
    routes = _routes(entries)
    consumers = _common_entries(partial, 'consumers', sites)
    inputs = _common_entries(partial, 'inputs', sites)
    for site in sites:
        assert entries[site]['row'] == original_entries[site]['row']
        assert _topology(routes[site]) == _topology(original_routes[site])
        assert details['host_packet'] in routes[site]['targets']
        _host_checks(routes[site], details['host_packet'])
        _flags(routes[site])
        assert consumers[site]['source'] == original_consumers[site]['source']
        assert set(consumers[site]['targets']) == set(original_consumers[site]['targets'])
        assert consumers[site]['declared'] == ()
        assert 'protocol_result_consumers_missing' in consumers[site]['gaps']

    if deleted == 'consumers':
        assert changed.protocol_call_inputs == program.protocol_call_inputs
        for site in sites:
            assert routes[site]['source'] == original_routes[site]['source']
            assert routes[site]['status'] == 'DECLARED'
            assert all(item['binding']['match'] is True
                       for item in _host_checks(routes[site], details['host_packet']))
        return

    assert all(inputs[site]['status'] == 'MISSING'
               and 'protocol_call_inputs_missing' in inputs[site]['gaps'] for site in sites)
    assert routes[raise_site]['source'] == entries[raise_site]['row'].contract.result
    assert all(item['binding']['match'] is True
               for item in _host_checks(routes[raise_site], details['host_packet']))
    normal = routes[normal_site]
    assert normal['source'] is None or type(normal['source']) is StaticProtocolGap
    assert normal['source'] != entries[normal_site]['row'].contract.result
    assert normal['status'] in ('MISSING', 'PARTIAL', 'NOT_CHECKED')
    assert 'delegate_close_normal_injected_source_unresolved' in normal['gaps']
    # An actual pending payload cannot select the deleted expected injection.
    # Later independently known current sources may have their own proofs;
    # checks relative to the unresolved original source must remain unknown.
    root_checks = tuple(item for item in normal['checks'] if item['source'] == normal['source'])
    assert root_checks
    assert all(item['binding']['match'] is None for item in root_checks)


def test_unknown_packet_root_does_not_contradict_a_real_return_replacement():
    from scar.ir.execution.validity_budget import ValidityBudget
    from scar.ir.program.control import LanguageCompletionKind
    from scar.ir.program.model import OperationResult, ReferenceValue, TerminatorKind
    from scar.ir.program.protocol_connection_flow import ConnectionContext
    from scar.ir.program.protocol_packet_routes import packet_continuations
    from scar.ir.program.protocols import OwnedUse, StaticGapReason
    from tests.fixtures.program_packet_continuation_graphs import _explicit_transfers
    from tests.fixtures.program_resumption_graphs import resumption_cleanup_program

    program, _ = _explicit_transfers(resumption_cleanup_program(replace_pending=True))
    require_valid(program)
    index = ProgramIndex(program)
    context = ConnectionContext(program, index=index, budget=ValidityBudget(262144))
    action, = program.cleanup_replacements
    block, = tuple(block for region in program.regions for block in region.blocks
                   if action.operation in block.operations)
    start = (block.id, block.operations.index(action.operation))

    # The current source follows the original replacement token's constructor,
    # not the unknown packet that existed before this C1 action.
    originals = context.origins(OwnedUse(action.operation, action.replacement))
    definitions = {definition.value: definition for definition in program.pending_completions}
    candidates = {recipe['leaf'].id for recipe in originals['recipes']
                  if recipe['leaf'].id in definitions}
    replacement_id, = candidates
    definition = definitions[replacement_id]
    ports = {port.id: port for port in program.control_ports}
    assert ports[definition.port].kind is LanguageCompletionKind.RETURN
    values = {value.id: value for value in program.values}
    origin = values[definition.value].origin
    assert type(origin) is OperationResult and definition.payload is not None
    current = OwnedUse(origin.operation, definition.payload)
    assert isinstance(values[context.owned_use(current.operation, current.use).value], ReferenceValue)
    terminal, = tuple(operation for operation in program.operations
        if operation.terminator is not None
        and operation.terminator.kind is TerminatorKind.RETURN)
    host = OwnedUse(terminal.id, terminal.terminator.values[0])

    unknown = StaticProtocolGap(StaticGapReason.PORT_UNCAPTURED)
    route = packet_continuations(context, unknown, start=start)
    assert route['source'] == unknown
    assert route['status'] == 'PARTIAL'
    assert 'packet_continuation_source_unresolved' in route['gaps']
    assert not any(item['binding']['match'] is False for item in route['checks'])
    assert all(item['binding']['match'] is None for item in route['checks']
               if item['source'] == unknown)
    override, = tuple(item for item in route['overrides'] if item['action'] == action)
    assert override['definition'] == definition
    assert override['source'] == current and override['previous_source'] == unknown
    assert override['token_binding']['match'] is True
    assert override['source_applicability_verified'] is False
    assert host in route['targets']
    checks = _host_checks(route, host)
    assert any(item['source'] == current and item['binding']['match'] is True for item in checks)
    _flags(route)

