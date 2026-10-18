"""Read-only associations back to original program ports and evidence.

Queries expose declarations and precise validation gaps. They cannot turn an
association into native/runtime correspondence, content equality, or a proof.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from scar.ir.program.ids import UseID, ValueID
from scar.ir.program.model import BlockArgument, CompletionResult
from scar.ir.program.drivers import BodyDriveResult
from scar.ir.program.resumption import ResumeInput, SavedInput, saved_actual_use
from .common import Unresolved
from .coordinates import ControlTransfer, OccurrencePhase, OccurrencePoint, UseOccurrence
from .ids import BlockVisitID, OperationOccurrenceID, RegionActivationID, ValueOccurrenceID
from .validation import _analyze


@dataclass(frozen=True, slots=True)
class DefinitionLink:
    operation: OperationOccurrenceID
    use: UseID
    definition: ValueID
    occurrence: ValueOccurrenceID | Unresolved
    origin: OperationOccurrenceID | BlockVisitID | RegionActivationID | None


@dataclass(frozen=True, slots=True)
class FormalRoute:
    formal: ValueOccurrenceID
    transfer: ControlTransfer | None
    argument: UseID | CompletionResult | BodyDriveResult | ResumeInput | SavedInput | None
    source_use: UseOccurrence | None


class ExecutionIndex:
    def __init__(self, model, program, *, value_graphs=None, evidence_graphs=None):
        report, ctx = _analyze(model, program, value_graphs=value_graphs, evidence_graphs=evidence_graphs)
        if not report.valid:
            raise ValueError('; '.join(f'{x.code} at {x.path}: {x.message}' for x in report.issues))
        self._ctx = ctx
        self.report = deepcopy(report)

    def definition_for_use(self, operation, use):
        """Original Use/definition plus its declared dynamic definition endpoint."""
        ctx = self._ctx
        binding = ctx.uses[operation, use]
        definition = ctx.core_uses[use][1].value
        row = None if type(binding.value) is Unresolved else ctx.values[binding.value]
        return deepcopy(DefinitionLink(operation, use, definition, binding.value, None if row is None else row.origin))

    def formal_route(self, value):
        """Actual predecessor port, without claiming copied data/object identity."""
        ctx = self._ctx
        row = ctx.values[value]
        core = ctx.core_values[row.value]
        if not isinstance(core.origin, BlockArgument):
            raise ValueError('formal_route requires a block argument occurrence')
        transfer = ctx.incoming.get(row.origin)
        if transfer is None:
            return deepcopy(FormalRoute(value, None, None, None))
        operation = ctx.core_operations[ctx.occurrences[transfer.operation].operation]
        argument = operation.terminator.successors[transfer.successor_index].arguments[core.origin.index]
        use = saved_actual_use(operation, argument)
        binding = None if use is None else ctx.uses.get((transfer.operation, use))
        return deepcopy(FormalRoute(value, transfer, argument, binding))

    def state_at(self, point):
        """Declared current state occurrences; None is explicitly unresolved."""
        ctx = self._ctx
        count = len(ctx.issues)
        ctx.check_point(point, 'query.state_at')
        if len(ctx.issues) != count:
            errors = ctx.issues[count:]
            del ctx.issues[count:]
            raise ValueError('; '.join(row.message for row in errors))
        current = ctx.current(point)
        return None if current is None else deepcopy(current)

    def occurrence(self, identity):
        ctx = self._ctx
        row = ctx.occurrences[identity]
        op = ctx.core_operations[row.operation]
        return deepcopy({
            'occurrence': row, 'operation': op,
            'uses': tuple(ctx.uses.get((identity, use.id)) for use in op.uses),
            'results': tuple(ctx.results.get((identity, value)) for value in op.results),
            'before': ctx.current(OccurrencePoint(identity, OccurrencePhase.BEFORE)),
            'after': ctx.current(OccurrencePoint(identity, OccurrencePhase.AFTER)),
            'transfer': ctx.outgoing.get(identity),
        })

    def resource_access(self, identity):
        ctx = self._ctx
        row = ctx.accesses[identity]
        binding = ctx.requirements[row.requirement]
        requirement = next(x for x in ctx.program.resource_requirements if x.id == binding.requirement)
        op = ctx.occurrences[row.operation].operation
        original = next(x for x in ctx.program.resource_uses if x.operation == op and x.requirement == requirement.id)
        return deepcopy({'access': row, 'binding': binding, 'requirement': requirement, 'original_use': original})


__all__ = ['DefinitionLink', 'FormalRoute', 'ExecutionIndex']
