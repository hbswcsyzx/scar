"""Actual branch prefix and first-outcome cuts over the original close body.

The source/native close semantics remain conditional. Both static frontiers
are genuine original sources; a disconnected captured source is not a path.
"""
from dataclasses import replace

from scar.ir.execution.common import Unresolved
from scar.ir.execution.coordinates import ExecutionSegment, ResumeIngress
from scar.ir.execution.ids import ExecutionSegmentID
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.program.ids import BlockID, OperationID
from scar.ir.program.model import TerminatorKind
from tests.fixtures.execution_call_graphs import _model
from tests.fixtures.program_generator_admission_graphs import _environment
from tests.fixtures.program_generator_close_retry_graphs import _branching_body, _first_driver


def body_prefix_execution(*, selected='A', mode='complete'):
    """A=RETURN, B=ignored YIELD; mode can disconnect B after actual choose-A.

    Returns (program,model,details). ``ghost_b`` intentionally omits A's actual
    terminal occurrence while retaining its selected prefix and a disconnected
    B occurrence. ``missing_transfer`` has no known contradictory branch choice.
    """
    if selected not in ('A', 'B') or mode not in ('complete', 'ghost_b', 'missing_transfer'):
        raise ValueError('unknown finite prefix fixture variant')
    if mode != 'complete' and selected != 'B':
        raise ValueError('the partial counterexamples request static B')
    program, _ = _first_driver(_environment(_branching_body()), release=False)
    operations = {op.id: op for op in program.operations}
    blocks = {block.id: block for region in program.regions for block in region.blocks}
    drive, = program.body_drives
    goals = {'A': OperationID('close.body.return.exit'), 'B': OperationID('resume.raise')}
    desired = goals[selected]
    static_edge = next(number for number, edge in enumerate(operations[drive.operation].terminator.successors)
                       if edge.source == desired)
    driver_path = []
    cursor = next(region.entry for region in program.regions if region.id == program.root)
    while True:
        terminal = operations[blocks[cursor].operations[-1]]
        term = terminal.terminator
        if term.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
            driver_path.append((cursor, None))
            break
        ordinal = static_edge if terminal.id == drive.operation else 0
        driver_path.append((cursor, ordinal))
        cursor = term.successors[ordinal].block
    if mode == 'ghost_b':
        body_path = ((BlockID('resume.entry'), 1), (BlockID('resume.packet'), 0),
                     (BlockID('close.body.return'), None), (BlockID('close.body.yield'), None))
    elif mode == 'missing_transfer':
        body_path = ((BlockID('resume.entry'), 1), (BlockID('resume.packet'), None),
                     (BlockID('close.body.yield'), None))
    else:
        ordinal = int(selected == 'B')
        body_path = ((BlockID('resume.entry'), 1), (BlockID('resume.packet'), ordinal),
                     (BlockID('close.body.yield' if ordinal else 'close.body.return'), None))
    model, scopes, source = _model(program, (
        (program.root, tuple(driver_path), 'prefix.driver'),
        (program.resumable_bodies[0].region, body_path, 'prefix.body')))
    driver_scope, body_scope = scopes
    activation, visits, actual_ops = body_scope
    point = model.activations[0].entry
    suspension = actual_ops[OperationID('resume.suspend')]
    initial = next(row for row in model.segments if row.activation == activation)
    resumed = ExecutionSegment(ExecutionSegmentID('prefix.body.resumed'), activation,
        initial.host_thread, ResumeIngress(suspension, 1, point))
    model = replace(model, segments=(*model.segments, resumed), visits=tuple(replace(row, segment=resumed.id)
        if row.id in set(visits[1:]) else row for row in model.visits))
    omitted = actual_ops.get(goals['A']) if mode == 'ghost_b' else None
    if omitted is not None:
        model = replace(model, operations=tuple(row for row in model.operations if row.id != omitted),
                        uses=tuple(row for row in model.uses if row.operation != omitted))
    identity = driver_scope[2][drive.operation]
    outcome = actual_ops[desired]
    gap = Unresolved('external body creation and source/native correspondence were not captured', point)
    model = replace(model,
        body_drive_executions=(BodyDriveExecution(identity, activation, visits[1], outcome, source),),
        body_activation_origins=(BodyActivationOrigin(activation, gap, source),))
    return program, model, {'drive': identity, 'activation': activation, 'entry': visits[1],
        'outcome': outcome, 'selected_source': desired, 'static_sources': tuple(goals.values()),
        'branch': actual_ops[OperationID('close.body.choose')], 'omitted': omitted,
        'selected': selected, 'mode': mode, 'source': source}


__all__ = ['body_prefix_execution']
