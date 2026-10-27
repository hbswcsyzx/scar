"""Conservative links between static source nodes and dynamic events."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from collections import Counter
from pathlib import Path

from .graph import ExecutionGraph, ProgramGraph
from .ids import CodeID


@dataclass(frozen=True, slots=True)
class SourceCorrespondence:
    event_index: int
    code_id: str | None
    source: str
    line: int
    static_node_ids: tuple[str, ...]
    confidence: str
    status: str

    def as_dict(self):
        return asdict(self)


def link_events(static: ProgramGraph, execution: ExecutionGraph) -> list[SourceCorrespondence]:
    """Join events to source locations or matching loaded function spans.

    A function span is used only when the runtime CodeID supplies a qualname
    and the event line falls inside a statically observed definition span.
    Otherwise the conservative path/line correspondence is retained.
    """
    by_location: dict[tuple[str, int], list[str]] = {}
    by_span: dict[str, list[tuple[int, int, str]]] = {}
    for node in static.nodes.values():
        if node.source and node.line is not None:
            by_location.setdefault((str(Path(node.source).resolve()), node.line), []).append(node.node_id)
        if node.source and node.attrs.get("qualname"):
            try:
                start = int(node.attrs["span_start"])
                end = int(node.attrs["span_end"])
            except (KeyError, TypeError, ValueError):
                continue
            span_key = f"{Path(node.source).resolve()}::{node.attrs['qualname']}"
            by_span.setdefault(span_key, []).append((start, end, node.node_id))
    matches: list[SourceCorrespondence] = []
    for index, event in enumerate(execution.events):
        metadata = event.metadata or {}
        source = metadata.get("file")
        line = metadata.get("line")
        parsed = CodeID.parse_key(event.code_id) if event.code_id else None
        if source is None and parsed is not None:
            source = parsed.source
        try:
            invalid_line = line is None or int(line) <= 0
        except (TypeError, ValueError):
            invalid_line = True
        if invalid_line and parsed is not None:
            line = parsed.line
        try:
            source = str(Path(source).resolve())
            line = int(line)
        except (TypeError, ValueError):
            continue
        span_nodes = ()
        if parsed is not None:
            qualnames = (parsed.qualname,
                         parsed.qualname.replace(".<locals>.", "."))
            for qualname in qualnames:
                span_key = f"{source}::{qualname}"
                span_nodes = tuple(node_id for start, end, node_id in by_span.get(span_key, ())
                                   if start <= line <= end)
                if span_nodes:
                    break
        confidence = "function_span" if span_nodes else "exact_path_line"
        nodes = span_nodes or tuple(by_location.get((source, line), ()))
        if not nodes:
            continue
        matches.append(SourceCorrespondence(
            event_index=index, code_id=event.code_id, source=source, line=line,
            static_node_ids=nodes, confidence=confidence,
            status="ambiguous" if len(nodes) > 1 else "linked"))
    return matches


def add_correspondences(graph: ProgramGraph,
                        matches: list[SourceCorrespondence]) -> None:
    """Add links without collapsing ambiguous AST nodes."""
    for match in matches:
        action_id = f"invocation:{match.event_index}:"
        actions = [node_id for node_id in graph.nodes
                   if node_id.startswith(action_id)]
        for action in actions:
            for static_node in match.static_node_ids:
                graph.add_edge(static_node, action, "dynamic_instance",
                                confidence=match.confidence, status=match.status,
                                source_path=match.source, line=match.line)


def summarize_correspondence(
    static: ProgramGraph,
    execution: ExecutionGraph,
    matches: list[SourceCorrespondence],
) -> dict:
    """Report linkage coverage with an explicit eligible-event denominator.

    An event is eligible when its metadata or loaded CodeID names a source
    file present in the static graph. Third party/library events outside that
    graph are out of scope rather than false misses. An eligible event whose
    line/span cannot be resolved remains an explicit unlinked event.
    """
    sources = {
        str(Path(node.source).resolve()) for node in static.nodes.values()
        if node.source is not None
    }
    eligible: set[int] = set()
    for index, event in enumerate(execution.events):
        source = (event.metadata or {}).get("file")
        if source is None and event.code_id:
            parsed = CodeID.parse_key(event.code_id)
            source = parsed.source if parsed is not None else None
        try:
            resolved = str(Path(source).resolve())
        except TypeError:
            continue
        if resolved in sources:
            eligible.add(index)
    linked = {item.event_index for item in matches}
    linked_eligible = eligible & linked
    return {
        "source_files": len(sources),
        "eligible_events": len(eligible),
        "linked_events": len(linked_eligible),
        "unlinked_eligible_events": len(eligible - linked),
        "event_coverage": (
            len(linked_eligible) / len(eligible) if eligible else None),
        "ambiguous_events": sum(item.status == "ambiguous" for item in matches),
        "by_confidence": dict(Counter(item.confidence for item in matches)),
        "by_status": dict(Counter(item.status for item in matches)),
    }
