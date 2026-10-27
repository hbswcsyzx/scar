"""Diagnose source-relative final edges on the validated original core only."""
from dataclasses import replace
import json

from scar.ir.program.await_outcome_flow import bind_target, required_choices, selected, state_links
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocols import HostTerminal
from scar.ir.program.queries import ProgramIndex
from tests.fixtures.program_await_shared_final_graphs import await_shared_final_program


for zero_cut in (True, False):
    graph, details = await_shared_final_program(zero_cut=zero_cut, case_mode='universal')
    core = replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=())
    ctx = ConnectionContext(core, index=ProgramIndex(core))
    for site in details['shared_final']['extractors']:
        for row in site['rows']:
            own = row.contract.output
            target = HostTerminal(site['terminals'][site['operation'].terminator.successors[row.slot].kind].id)
            required, complete = required_choices(ctx, own)
            before = (own.edge,)
            after = selected(ctx, before, required)
            print(json.dumps({'zero_cut': zero_cut, 'operation': str(site['operation'].id),
                'slot': row.slot, 'required': tuple(map(str, required)), 'complete': complete,
                'before': bind_target(ctx, own, target, before)['match'],
                'after': bind_target(ctx, own, target, after)['match'],
                'states_before': tuple(item['binding']['match'] for item in state_links(ctx, target, own.edge, before, outward=True)),
                'states_after': tuple(item['binding']['match'] for item in state_links(ctx, target, own.edge, after, outward=True))}))
