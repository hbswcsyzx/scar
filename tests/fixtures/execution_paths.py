"""Finite declared paths through canonical CFGs; not runtime/source evidence."""
from scar.ir.execution.common import EvidencePoint, MissingEvidence
from scar.ir.execution.coordinates import (
    BlockVisit, ControlTransfer, ExecutionRun, ExecutionSegment, HostThreadInstance,
    InitialEntry, OperationOccurrence, ProcessInstance, RegionActivation,
    ResumeIngress, UseOccurrence, ValueOccurrence,
)
from scar.ir.execution.ids import (
    BlockVisitID, ExecutionSegmentID, HostThreadInstanceID, OperationOccurrenceID,
    ProcessInstanceID, RegionActivationID, RunID, ValueOccurrenceID,
)
from scar.ir.execution.model import ExecutionModel
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.program.model import LiteralOrigin
from scar.ir.program.resumption import SuspendTerminator


def declared_path(program, path):
    """path contains (BlockID, actual successor index or None at final exit)."""
    missing = MissingEvidence('test declaration, not a collected runtime path')
    run, process, thread = RunID('path'), ProcessInstanceID('path'), HostThreadInstanceID('path')
    point = EvidencePoint(run, process, missing)
    activation = RegionActivationID('path')
    segments, visits, operations, values, uses, transfers = [], [], [], [], [], []
    blocks = {block.id: block for region in program.regions for block in region.blocks}
    ops = {op.id: op for op in program.operations}
    env = {}
    for value in program.values:
        if value.region == program.root and isinstance(value.origin, LiteralOrigin):
            occurrence = ValueOccurrence(ValueOccurrenceID('literal.' + value.id.value), value.id, activation)
            values.append(occurrence)
            env[value.id] = occurrence.id
    segment = ExecutionSegmentID('start')
    segments.append(ExecutionSegment(segment, activation, thread, InitialEntry(point)))
    previous = None
    for number, (block_id, edge) in enumerate(path):
        visit = BlockVisitID(str(number))
        if previous is not None:
            op, occurrence, previous_edge = previous
            if type(op.terminator) is SuspendTerminator:
                segment = ExecutionSegmentID(str(number))
                segments.append(ExecutionSegment(segment, activation, thread,
                    ResumeIngress(occurrence, previous_edge, point)))
            transfers.append(ControlTransfer(occurrence, previous_edge, visit))
        visits.append(BlockVisit(visit, segment, block_id))
        block = blocks[block_id]
        for formal in block.arguments:
            occurrence = ValueOccurrence(ValueOccurrenceID(f'{number}.{formal.value}'), formal, visit)
            values.append(occurrence)
            env[formal] = occurrence.id
        for op_id in block.operations:
            op = ops[op_id]
            occurrence = OperationOccurrenceID(f'{number}.{op_id.value}')
            operations.append(OperationOccurrence(occurrence, visit, op_id))
            uses.extend(UseOccurrence(occurrence, use.id, env[use.value]) for use in op.uses)
            for result in op.results:
                value = ValueOccurrence(ValueOccurrenceID(f'{number}.{result.value}'), result, occurrence)
                values.append(value)
                env[result] = value.id
        previous = None if edge is None else (op, occurrence, edge)
    return ExecutionModel(snapshot_for(program), runs=(ExecutionRun(run, missing),),
        processes=(ProcessInstance(process, run, 10, missing),),
        threads=(HostThreadInstance(thread, process, 11, missing),),
        activations=(RegionActivation(activation, program.root, process, point),),
        segments=tuple(segments), visits=tuple(visits), operations=tuple(operations),
        values=tuple(values), uses=tuple(uses), transfers=tuple(transfers))
