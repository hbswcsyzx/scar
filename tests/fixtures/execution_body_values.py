"""Actual saved Data ports across a persistent body's suspension."""
from dataclasses import replace

from scar.ir.execution.common import Unresolved
from scar.ir.execution.content import DataIdentity, ValueDenotation, VersionRef
from scar.ir.execution.coordinates import OperationOccurrence, UseOccurrence, ValueOccurrence
from scar.ir.execution.ids import DenotationID, OperationOccurrenceID, ValueOccurrenceID
from scar.ir.execution.snapshot import external_artifact, snapshot_for
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import Behavior, BlockArgument, DataValue, LiteralOrigin, Operation, Use, UseRole
from scar.ir.program.resumption import SavedInput, SavedRole, SavedSlot
from scar.ir.v2.ids import LogicalValueID, ValueVersionID
from scar.ir.v2.values import LogicalValue, ValueGraph, ValueVersion
from tests.fixtures.execution_resumable_graphs import resumable_execution


def saved_data_execution(*, changed_version=False):
    program, model, details = resumable_execution()
    item, = details['instances']
    activation = next(row for row in model.activations if row.id == item['activation'])
    body = next(row for row in program.regions if row.id == activation.region)
    suspension = next(row for row in program.operations if row.id.value == 'resume.suspend')
    data = DataValue(ValueID('body.data.literal'), body.id, LiteralOrigin(11), 'builtins.int')
    data_use = Use(UseID('body.data.saved'), data.id, UseRole.DATA)
    saved_slot = len(suspension.terminator.saved)
    new_values, operations, blocks, successors, formal_values = [], [], [], [], {}
    for number, edge in enumerate(suspension.terminator.successors):
        block = next(row for row in body.blocks if row.id == edge.block)
        formal = DataValue(ValueID(f'body.data.formal.{number}'), body.id,
            BlockArgument(block.id, len(block.arguments)), 'builtins.int')
        use = Use(UseID(f'body.data.consume.{number}'), formal.id, UseRole.DATA)
        operation = Operation(OperationID(f'body.data.consume.{number}'), 'consume saved scalar',
            (Behavior.COMPUTE,), (use,), effects_complete=True)
        new_values.append(formal)
        operations.append(operation)
        blocks.append(replace(block, arguments=(*block.arguments, formal.id),
                              operations=(*block.operations[:-2], operation.id, *block.operations[-2:])))
        successors.append(replace(edge, arguments=(*edge.arguments, SavedInput(saved_slot))))
        formal_values[block.id] = formal, operation, use
    suspension = replace(suspension, uses=(*suspension.uses, data_use),
        terminator=replace(suspension.terminator,
            saved=(*suspension.terminator.saved, SavedSlot(SavedRole.VALUE, data_use.id)),
            successors=tuple(successors)))
    changed_blocks = {row.id: row for row in blocks}
    program = replace(program,
        values=(*program.values, data, *new_values),
        operations=tuple(suspension if row.id == suspension.id else row for row in program.operations) + tuple(operations),
        regions=tuple(replace(row, blocks=tuple(changed_blocks.get(block.id, block) for block in row.blocks))
                      if row.id == body.id else row for row in program.regions))
    source = ValueOccurrence(ValueOccurrenceID('body.data.literal'), data.id, item['activation'])
    visit = next(row for row in model.visits if row.id == item['entries'][1])
    formal, operation, use = formal_values[visit.block]
    target = ValueOccurrence(ValueOccurrenceID('body.data.formal'), formal.id, visit.id)
    consume = OperationOccurrence(OperationOccurrenceID('body.data.consume'), visit.id, operation.id)
    value_graph = ValueGraph()
    logical = LogicalValueID('body.data')
    value_graph.logical_values[logical] = LogicalValue(logical, 'builtins.int')
    versions = (ValueVersionID(logical, 0), ValueVersionID(logical, 1))
    for version in versions:
        value_graph.versions[version] = ValueVersion(version)
    artifact = external_artifact(value_graph, 'memory:body-saved-data')
    point = next(row for row in model.activations if row.id == item['activation']).entry
    basis = Unresolved('declared numerical lineage, not observed equality', point)
    denotations = tuple(ValueDenotation(DenotationID('body.data.' + str(number)), value.id,
        DataIdentity(VersionRef(artifact, versions[1 if number and changed_version else 0])), basis,
        point.source) for number, value in enumerate((source, target)))
    model = replace(model, snapshot=snapshot_for(program),
        values=(*model.values, source, target), operations=(*model.operations, consume),
        uses=(*model.uses, UseOccurrence(item['suspension'], data_use.id, source.id),
              UseOccurrence(consume.id, use.id, target.id)),
        denotations=(*model.denotations, *denotations))
    details = {**details, 'value_graphs': {artifact.sha256: value_graph}, 'saved_data': (source, target)}
    return program, model, details
