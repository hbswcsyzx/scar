"""Exact def/use queries; deliberately independent of optimization decisions."""
from dataclasses import dataclass

from .ids import OperationID, RegionID, ValueID
from .model import ProgramGraph, Use
from .validation import require_valid


@dataclass(frozen=True, slots=True)
class UseSite:
    operation: OperationID
    use: Use


class ProgramIndex:
    def __init__(self, graph: ProgramGraph):
        require_valid(graph)
        self.graph = graph
        self.values = {value.id: value for value in graph.values}
        self.regions = {region.id: region for region in graph.regions}
        self._consumers = {value.id: [] for value in graph.values}
        for operation in graph.operations:
            for use in operation.uses:
                self._consumers[use.value].append(UseSite(operation.id, use))

    def producer(self, value_id: ValueID):
        return self.values[value_id].origin

    def consumers(self, value_id: ValueID) -> tuple[UseSite, ...]:
        return tuple(self._consumers[value_id])

    def entry_arguments(self, region_id: RegionID):
        region = self.regions[region_id]
        block = next(block for block in region.blocks if block.id == region.entry)
        return tuple(self.values[value_id] for value_id in block.arguments)


__all__ = ["ProgramIndex", "UseSite"]
