"""Demand queue primitives for inventory v6 call-source expansion.

The queue records reasons for analysis work. Its priority is an analysis
policy; it does not turn source candidates into runtime call facts.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import heapq

from scar.ir.program.call_demand import (
    BodyExpansionV6, DemandOrigin, EnteredCallCode, EntryRoot, LegacyObservation,
    Remainder, SourceCallCandidate, ExpansionScheduleV6,
)
from scar.ir.program.expansion import ContextStoreBudget, ContextUnavailable
from scar.ir.program.inventory import BodyStatus, DefinitionInventory, FileInventory
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID


def _matched_call_sources(report, files: tuple[FileInventory, ...]):
    """Match every structurally eligible D0 group to this indexed source view.

    The join intentionally requires the exact source path and decoded-source
    fingerprint, the exact definition ID, and the exact SourceReference. A
    matching filename or qualname is insufficient. The returned mapping also
    includes eligible non-function definitions so the coordinator can report
    their admission without attempting to lower them as function bodies.
    """
    if report is None:
        return {}
    model = getattr(report, "model", None)
    if model is None or not callable(getattr(report, "eligible_groups", None)):
        raise TypeError("call-source scheduling requires a replayed CallSourceSeedReport")
    links = {link.code: link for link in report.eligible_code_links()}
    by_path = {file.snapshot.path: file for file in files}
    matched = {}
    for group in report.eligible_groups():
        key = group.process_id, group.code
        link = links.get(group.code)
        if link is None or link.snapshot is None or link.definition is None or link.source is None:
            matched[key] = None
            continue
        file = by_path.get(link.snapshot.path)
        if (file is None or file.snapshot.path != link.snapshot.path
                or file.snapshot.fingerprint != link.snapshot.fingerprint):
            matched[key] = None
            continue
        definitions = [definition for definition in file.definitions
                       if definition.id == link.definition and definition.source == link.source]
        matched[key] = (link, definitions[0]) if len(definitions) == 1 else None
    return matched


@dataclass(slots=True)
class _Task:
    definition: OperationDefinitionID
    source: SourceReference
    priority: int
    origins: list[DemandOrigin] = field(default_factory=list)
    _origin_set: set = field(default_factory=set)
    version: int = 0
    started: bool = False
    attempted: bool = False
    construction_operations: int = 0
    status: BodyStatus = BodyStatus.NOT_ATTEMPTED
    operation_budget_charged: int = 0
    construction_cost_known: bool = True

    def add_origin(self, origin):
        if origin not in self._origin_set:
            self._origin_set.add(origin)
            self.origins.append(origin)


class CallDemandQueue:
    """FIFO within three priority frontiers, with one task per definition.

    Priorities are entry-reachable source candidates, orphan observed roots,
    then the static remainder. A task may be promoted before it is processed;
    later origins are retained even after construction has finished.
    """

    ENTRY = 0
    OBSERVED = 1
    REMAINDER = 2

    def __init__(self, functions: dict[OperationDefinitionID, DefinitionInventory]):
        self.functions = functions
        self._tasks = {}
        self._heap = []
        self._serial = 0
        self._processed = []

    def add(self, definition, priority, origin):
        if definition not in self.functions:
            return None
        if type(priority) is not int or priority not in (self.ENTRY, self.OBSERVED, self.REMAINDER):
            raise ValueError("unknown call-demand priority")
        if type(origin) not in (LegacyObservation, EnteredCallCode, SourceCallCandidate, Remainder):
            raise TypeError("call-demand origin must be a typed record")
        task = self._tasks.get(definition)
        if task is None:
            task = _Task(definition, self.functions[definition].source, priority)
            self._tasks[definition] = task
            self._push(task)
        elif type(origin) is not Remainder and not task.started:
            remainder = Remainder()
            if remainder in task._origin_set:
                task._origin_set.remove(remainder)
                task.origins.remove(remainder)
        task.add_origin(origin)
        if not task.started and priority < task.priority:
            task.priority = priority
            task.version += 1
            self._push(task)
        return task

    def add_remainder(self, definition):
        if definition in self._tasks:
            return self._tasks[definition]
        return self.add(definition, self.REMAINDER, Remainder())

    def _push(self, task):
        self._serial += 1
        heapq.heappush(self._heap, (task.priority, self._serial, task.version, task.definition))

    def pop(self):
        while self._heap:
            priority, _, version, definition = heapq.heappop(self._heap)
            task = self._tasks[definition]
            if task.started or version != task.version or priority != task.priority:
                continue
            task.started = True
            self._processed.append(task)
            return task
        return None

    @staticmethod
    def mark_unattempted(task, status):
        if type(status) is not BodyStatus or status is not BodyStatus.NOT_ATTEMPTED:
            raise ValueError("unattempted task must retain NOT_ATTEMPTED status")
        task.status = status

    @staticmethod
    def mark_result(task, *, status, construction_operations, operation_budget_charged,
                    construction_cost_known):
        if type(status) is not BodyStatus or status is BodyStatus.NOT_ATTEMPTED:
            raise ValueError("attempted task needs a terminal body status")
        task.attempted = True
        task.status = status
        task.construction_operations = construction_operations
        task.operation_budget_charged = operation_budget_charged
        task.construction_cost_known = construction_cost_known

    def schedule(self, budget: ContextStoreBudget, entry_roots: tuple[EntryRoot, ...],
                 unavailable_contexts: tuple[ContextUnavailable, ...]) -> ExpansionScheduleV6:
        entries = tuple(BodyExpansionV6(
            task.definition, task.source, tuple(task.origins), task.attempted,
            task.construction_operations, task.status, task.operation_budget_charged,
            task.construction_cost_known,
        ) for task in self._processed)
        return ExpansionScheduleV6(
            budget, entries, tuple(entry_roots), tuple(unavailable_contexts),
        )


def entry_roots_for(files: tuple[FileInventory, ...], module_initializers: dict[str, OperationDefinitionID],
                    entry_path: str) -> tuple[EntryRoot, ...]:
    """Build genuine module-scope roots from indexed source files."""
    roots = []
    for file in files:
        if file.snapshot.path == entry_path and file.snapshot.path in module_initializers:
            roots.append(EntryRoot(file.snapshot, module_initializers[file.snapshot.path]))
    return tuple(roots)


def entry_frontier_initializers(discovery, source_workspace, module_initializers):
    """Return module scopes in the entry's nondeferred local-import closure.

    These scopes contribute only conditional source-call candidates. Their
    presence does not assert that a guarded or dynamically selected import ran.
    """
    frontier = getattr(source_workspace, "entry_frontier", None) or discovery
    files = {file.snapshot.path for file in frontier.files}
    adjacency = {path: [] for path in files}
    for dependency in frontier.imports:
        if dependency.deferred or dependency.owner_qualname != "<module>":
            continue
        targets = adjacency.get(dependency.source.path)
        if targets is None:
            continue
        for candidate in dependency.candidates:
            if candidate.namespace:
                continue
            for path in (*candidate.parent_initializers, candidate.path):
                if path in files and path not in targets:
                    targets.append(path)

    ordered_paths, seen = [], {discovery.entry}
    pending = deque((discovery.entry,))
    while pending:
        path = pending.popleft()
        ordered_paths.append(path)
        for target in adjacency.get(path, ()):
            if target not in seen:
                seen.add(target)
                pending.append(target)
    return tuple(module_initializers[path] for path in ordered_paths if path in module_initializers)


__all__ = ["CallDemandQueue", "_matched_call_sources", "entry_frontier_initializers", "entry_roots_for"]
