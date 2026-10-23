"""One analysis pass reused by validation and endpoint queries."""
from dataclasses import dataclass
from types import MappingProxyType

from .lifecycle_flow import TerminalFacts, derive_terminal_facts
from .session_flow import SessionFacts, derive_session_facts


@dataclass(frozen=True, slots=True)
class DriverLifecycleFacts:
    terminal: TerminalFacts
    session: SessionFacts


def analyze_lifecycles(graph, *, operation_blocks):
    """Call after canonical structure and all local lifecycle shapes pass."""
    interfaces = {row.region: row for row in graph.driver_interfaces}
    operations = {op.id: op for op in graph.operations}
    owners = {block.id: region.id for region in graph.regions for block in region.blocks}
    facts, errors = {}, []
    for scope in graph.driver_lifecycles:
        interface = interfaces[scope.region]
        terminal = derive_terminal_facts(graph, interface)
        session = derive_session_facts(graph, interface, terminal)
        facts[scope.region] = DriverLifecycleFacts(terminal, session)
    for row in graph.terminal_frame_releases:
        region = owners[operation_blocks[row.operation]]
        owner = next(use.value for use in operations[row.operation].uses if use.id == row.owner)
        if not facts[region].terminal.before[row.operation].is_finished(owner):
            errors.append(("terminal_release_unfinished", str(row.operation),
                           "every actual incoming path must establish terminal history for this exact owner"))
    return tuple(errors), MappingProxyType(facts)


__all__ = ["DriverLifecycleFacts", "analyze_lifecycles"]
