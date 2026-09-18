"""A compact in-memory event graph used by analysis and reports."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from .entities import ObjectEntity, Region
from .effects import ActionLabel
from .events import Event
from .ids import LogicalVersion, StorageID


@dataclass
class ExecutionGraph:
    events: list[Event] = field(default_factory=list)
    entities: dict[str, ObjectEntity] = field(default_factory=dict)

    def add(self, event: Event) -> int:
        self.events.append(event)
        return len(self.events) - 1

    def extend(self, events: Iterable[Event]) -> None:
        self.events.extend(events)

    def calls_by_code(self) -> dict[str, list[tuple[int, Event]]]:
        out: dict[str, list[tuple[int, Event]]] = {}
        for idx, event in enumerate(self.events):
            if event.code_id:
                out.setdefault(event.code_id, []).append((idx, event))
        return out


class NodeKind(str, Enum):
    CONTROL = "K_CONTROL"
    STATE = "SIGMA_STATE"
    ACTION = "A_ACTION"
    RESOURCE = "R_RESOURCE"
    CONTRACT = "Q_CONTRACT"
    MEASUREMENT = "M_MEASUREMENT"
    OPAQUE = "OPAQUE"


@dataclass(slots=True)
class GraphNode:
    node_id: str
    kind: NodeKind
    label: str
    source: str | None = None
    line: int | None = None
    labels: list[str] = field(default_factory=list)
    attrs: dict = field(default_factory=dict)


@dataclass(slots=True)
class GraphEdge:
    source: str
    target: str
    relation: str
    attrs: dict = field(default_factory=dict)


@dataclass
class ProgramGraph:
    """Multi-view graph for an arbitrary program.

    Nodes are intentionally not forced into one exclusive taxonomy: a call
    can have CONTROL, ACTION and RESOURCE edges at once. The graph can be
    populated statically from source and enriched with dynamic Event nodes.
    """
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)

    GRAPH_SCHEMA = "scar.program_graph"
    GRAPH_SCHEMA_VERSION = 1

    def to_dict(self, *, include_validation: bool = True) -> dict[str, Any]:
        """Return a versioned, machine-readable graph document.

        ``nodes`` and ``edges`` remain the stable payload used by earlier
        prototypes.  The explicit schema and validation snapshot make the
        file safe to hand to a later simplifier: consumers can reject an
        unknown format or a graph that was malformed before analysis.  The
        snapshot is evidence about structure and source coverage only; it is
        never a legality or purity proof.
        """
        document: dict[str, Any] = {
            "schema": self.GRAPH_SCHEMA,
            "schema_version": self.GRAPH_SCHEMA_VERSION,
            "nodes": [asdict(node) for node in self.nodes.values()],
            "edges": [asdict(edge) for edge in self.edges],
        }
        if include_validation:
            document["validation"] = self.validate()
        return document

    @classmethod
    def from_dict(cls, document: dict[str, Any], *, validate: bool = True) -> "ProgramGraph":
        """Load a versioned graph document without executing user code.

        Loading is intentionally data-only.  A caller may set ``validate``
        false to inspect a damaged artifact, but normal graph consumers keep
        the integrity gate enabled and receive a ``ValueError`` for unknown
        schema versions or dangling edges.
        """
        if not isinstance(document, dict):
            raise ValueError("program graph document must be an object")
        if document.get("schema") != cls.GRAPH_SCHEMA:
            raise ValueError(f"unsupported program graph schema: {document.get('schema')!r}")
        if document.get("schema_version") != cls.GRAPH_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported program graph schema version: {document.get('schema_version')!r}"
            )
        try:
            nodes = {
                str(raw["node_id"]): GraphNode(
                    node_id=str(raw["node_id"]),
                    kind=NodeKind(raw["kind"]),
                    label=str(raw["label"]),
                    source=raw.get("source"),
                    line=raw.get("line"),
                    labels=list(raw.get("labels", [])),
                    attrs=dict(raw.get("attrs", {})),
                )
                for raw in document.get("nodes", [])
            }
            edges = [
                GraphEdge(
                    source=str(raw["source"]),
                    target=str(raw["target"]),
                    relation=str(raw["relation"]),
                    attrs=dict(raw.get("attrs", {})),
                )
                for raw in document.get("edges", [])
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid program graph node or edge payload") from exc
        graph = cls(nodes=nodes, edges=edges)
        if validate:
            graph.assert_valid()
        return graph

    def validate(self) -> dict[str, Any]:
        """Check graph invariants before a simplification pass consumes it.

        A graph is an evidence container, so malformed input must be reported
        explicitly instead of being silently interpreted by a detector.  The
        validator checks identity, edge endpoints, source locations, and the
        physical-line coverage that static source graphs promise.  Dynamic
        nodes may have no source location; in that case coverage is reported
        as unavailable rather than being treated as complete.
        """
        errors: list[str] = []
        action_labels = frozenset(item.value for item in ActionLabel)
        for key, node in self.nodes.items():
            if not key or node.node_id != key:
                errors.append(f"node identity mismatch: {key!r}")
            if not node.label:
                errors.append(f"node {key!r} has no label")
            if node.line is not None and (not isinstance(node.line, int) or node.line < 1):
                errors.append(f"node {key!r} has invalid source line {node.line!r}")
            if len(node.labels) != len(set(node.labels)):
                errors.append(f"node {key!r} has duplicate action labels")
            # ``labels`` on a source-located node are the multi-label Action
            # taxonomy.  K/Σ/A/R/Q/M is represented by ``kind`` instead, so
            # an arbitrary tag must not satisfy per-line classification.
            # Non-source structural nodes retain legacy view annotations;
            # they are not evidence about a physical source line.
            if node.source is not None and node.line is not None:
                invalid = sorted(set(node.labels) - action_labels)
                if invalid:
                    errors.append(
                        f"node {key!r} has invalid action labels: {invalid!r}")
        for index, edge in enumerate(self.edges):
            if edge.source not in self.nodes:
                errors.append(f"edge {index} source is missing: {edge.source!r}")
            if edge.target not in self.nodes:
                errors.append(f"edge {index} target is missing: {edge.target!r}")
            if not edge.relation:
                errors.append(f"edge {index} has no relation")

        by_source: dict[str, set[int]] = {}
        labels_by_source_line: dict[str, dict[int, set[str]]] = {}
        invalid_labels_by_source_line: dict[str, dict[int, set[str]]] = {}
        for node in self.nodes.values():
            if node.source is None or node.line is None:
                continue
            source = str(node.source)
            line = int(node.line)
            by_source.setdefault(source, set()).add(line)
            valid = set(node.labels) & action_labels
            invalid = set(node.labels) - action_labels
            labels_by_source_line.setdefault(source, {}).setdefault(line, set()).update(valid)
            if invalid:
                invalid_labels_by_source_line.setdefault(source, {}).setdefault(
                    line, set()).update(invalid)
        source_coverage: dict[str, dict[str, Any]] = {}
        for source, observed in sorted(by_source.items()):
            total: int | None = None
            try:
                source_path = Path(source)
                if source_path.is_file():
                    total = len(source_path.read_text().splitlines())
            except (OSError, UnicodeError):
                # A runtime CodeID can name a source that is gone or opaque.
                # Keep the coverage result available without making I/O a
                # prerequisite for dynamic graph validation.
                total = None
            upper = total if total is not None else (max(observed) if observed else 0)
            missing = sorted(set(range(1, upper + 1)) - observed)
            line_labels = labels_by_source_line.get(source, {})
            invalid_line_labels = invalid_labels_by_source_line.get(source, {})
            unclassified = sorted(
                line for line in range(1, upper + 1)
                if not line_labels.get(line)
            )
            source_coverage[source] = {
                "physical_lines": total,
                "observed_lines": len(observed),
                "missing_lines": missing,
                "coverage_complete": total is not None and not missing,
                "line_labels": {str(line): sorted(labels)
                                for line, labels in sorted(line_labels.items())},
                "invalid_line_labels": {
                    str(line): sorted(labels)
                    for line, labels in sorted(invalid_line_labels.items())
                },
                "unclassified_lines": unclassified,
                "classification_complete": (
                    total is not None and not missing and not unclassified
                    and not invalid_line_labels),
                "evidence": "Observed source file" if total is not None else "UNKNOWN",
            }
        return {
            "valid": not errors,
            "errors": errors,
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "source_coverage": source_coverage,
        }

    def assert_valid(self) -> dict[str, Any]:
        """Validate and raise before graph simplification proceeds."""
        report = self.validate()
        if not report["valid"]:
            raise ValueError("invalid ProgramGraph: " + "; ".join(report["errors"]))
        return report

    def add_node(self, node: GraphNode) -> GraphNode:
        # Labels are a multi-label set with deterministic insertion order.
        # Runtime observers may append a generic label (for example ``VAL``)
        # after an earlier classification already supplied it; duplicate
        # labels carry no extra evidence and make graph invariants ambiguous.
        node.labels = list(dict.fromkeys(node.labels))
        self.nodes[node.node_id] = node
        return node

    def add_edge(self, source: str, target: str, relation: str, **attrs) -> None:
        self.edges.append(GraphEdge(source, target, relation, attrs))

    def operation_view(self) -> dict[str, Any]:
        """Project the evidence graph into an operation/data graph.

        The storage graph keeps K/Σ/A/R/Q/M nodes explicit because legality
        and measurement need those dimensions separately.  This projection is
        the compact view used for simplification: an operation is a broad
        function/action/control node, a data node is a State node, and edges
        between them describe reads, writes, dependencies and aliases.
        Static AST containment and observed call control are retained as a
        ``children`` index, so a simplifier can recursively expand one
        function/action without flattening the whole program.
        """
        action_labels = {item.value for item in ActionLabel}
        operation_ids: set[str] = set()
        data_ids: set[str] = set()
        for node_id, node in self.nodes.items():
            if node.kind == NodeKind.STATE and not (set(node.labels) & action_labels):
                data_ids.add(node_id)
            elif node.kind in {NodeKind.ACTION, NodeKind.CONTROL, NodeKind.OPAQUE}:
                # Dimension-only CONTROL/OPAQUE helper nodes have labels such
                # as CONTROL/RESOURCE and are intentionally omitted. Static
                # FunctionDef/Call/AST nodes carry the closed action labels.
                if set(node.labels) & action_labels:
                    operation_ids.add(node_id)
            elif set(node.labels) & action_labels:
                # A static assignment can be represented as STATE+VAL; it is
                # an operation in this view while its variable slots remain
                # data nodes.
                operation_ids.add(node_id)

        containment = {"module_contains", "ast_contains", "controls_dynamic"}
        data_relations = {
            "reads", "writes", "data_depends", "overwrites", "aliases",
            "version_of", "materializes", "has_region", "materializes_physical",
            "captures_callable", "escapes",
        }
        children: dict[str, list[str]] = {node_id: [] for node_id in operation_ids}
        edges: list[dict[str, Any]] = []
        for edge in self.edges:
            if edge.relation in containment and edge.source in operation_ids:
                if edge.target in operation_ids:
                    children[edge.source].append(edge.target)
                continue
            if edge.relation not in data_relations:
                continue
            if edge.source not in operation_ids | data_ids:
                continue
            if edge.target not in operation_ids | data_ids:
                continue
            edges.append({"source": edge.source, "target": edge.target,
                          "relation": edge.relation, "attrs": edge.attrs})
        for value in children.values():
            value[:] = list(dict.fromkeys(value))

        def encode(node_id: str) -> dict[str, Any]:
            node = self.nodes[node_id]
            return {"node_id": node.node_id, "kind": "operation" if node_id in operation_ids else "data",
                    "label": node.label, "source": node.source, "line": node.line,
                    "labels": list(node.labels), "attrs": dict(node.attrs),
                    "children": children.get(node_id, [])}

        return {
            "schema": "scar.operation_graph",
            "schema_version": 1,
            "nodes": [encode(node_id) for node_id in sorted(operation_ids | data_ids)],
            "edges": edges,
            "roots": sorted(node_id for node_id in operation_ids
                            if not any(node_id in value for value in children.values())),
            "semantics": {
                "operation_nodes": "function/action/control nodes with action labels",
                "data_nodes": "State nodes without an action label",
                "edge_semantics": "reads, writes, data dependency, overwrite, alias and materialization",
                "recursive_expansion": "children follows static AST containment or observed call control",
            },
        }

    def write_operation_json(self, path: str | Path) -> None:
        """Write the operation/data projection without executing user code."""
        Path(path).write_text(json.dumps(self.operation_view(), indent=2, default=str))

    def merge_graph(self, other: "ProgramGraph") -> None:
        """Merge a static or dynamic view while preserving node identities."""
        for node in other.nodes.values():
            if node.node_id in self.nodes and self.nodes[node.node_id] != node:
                raise ValueError(f"graph node identity collision: {node.node_id}")
            self.nodes[node.node_id] = node
        self.edges.extend(other.edges)

    def merge_execution(self, execution: ExecutionGraph) -> None:
        previous_id = None
        dynamic_calls: dict[tuple[object, object], str] = {}
        # A logical version has one or more observed producers in a trace.
        # Keep the latest producer so every later read can be connected to the
        # action that actually made the value available.  This is a runtime
        # fact, not a claim that the producer is the only possible alias.
        last_writer: dict[str, str] = {}
        # Index aliases by physical storage and unique region geometry.  A
        # workload can materialize the same view under thousands of logical
        # versions; comparing every historical version would be quadratic and
        # adds no new alias fact.  Each geometry keeps one canonical node.
        known_regions: dict[tuple[str, int], dict[tuple, tuple[str, Region]]] = {}
        # CUDA execution is ordered within one (process, device, context,
        # stream) tuple.  Keep this separate from serialized record_order:
        # cross-stream and host/device happens-before relations remain
        # unknown unless another observer supplies them.
        last_stream_event: dict[tuple[str, str, str, str], str] = {}
        # A line tracer emits a loop_iteration marker after a concrete
        # backwards bytecode jump. Keep the latest marker per dynamic loop
        # scope so subsequent actions can be connected without inventing the
        # first iteration or using serialized record order as control proof.
        loop_markers: dict[tuple[str, object, object], tuple[str, object]] = {}

        for idx, event in enumerate(execution.events):
            # ``Event.invocation_id`` identifies a dynamic call only for
            # per-call events.  Aggregate profiler records intentionally have
            # no such identity (and older traces may reuse a count), so the
            # event position is always part of the graph key.  This prevents
            # distinct actions from silently overwriting one another.
            invocation = event.invocation_id if event.invocation_id is not None else "aggregate"
            node_id = f"invocation:{idx}:{invocation}"
            self.add_node(GraphNode(node_id, NodeKind.ACTION, event.kind,
                                    event.code_id, labels=list(event.labels),
                                    attrs={"evidence": event.evidence,
                                           # Keep runtime source coordinates
                                           # discoverable without assigning
                                           # them to GraphNode.source. The
                                           # latter is reserved for static
                                           # source coverage; an observed
                                           # dynamic line is not coverage of
                                           # every physical line in a file.
                                           "source_file": event.metadata.get("file"),
                                           "source_line": event.metadata.get("line"),
                                           "process_id": event.metadata.get("process_id"),
                                           "thread_id": event.metadata.get("thread_id"),
                                           "duration_ns": event.duration_ns,
                                           "invocation_id": event.invocation_id,
                                           "effect": event.effect.as_dict()}))
            process = event.metadata.get("process_id", "unknown")
            invocation_key = (process, event.invocation_id)
            parent_invocation = event.metadata.get("parent_invocation_id")
            parent_key = (process, parent_invocation)
            if event.kind == "python_call":
                dynamic_calls[invocation_key] = node_id
                if parent_invocation is not None and parent_key in dynamic_calls:
                    self.add_edge(dynamic_calls[parent_key], node_id, "controls_dynamic",
                                  depth=event.metadata.get("call_depth"),
                                  evidence="Observed")
            elif event.kind == "python_return":
                call_node = dynamic_calls.get(invocation_key)
                if call_node is not None:
                    self.add_edge(call_node, node_id, "returns",
                                  outcome=event.metadata.get("outcome"),
                                  evidence="Observed")
                if parent_invocation is not None and parent_key in dynamic_calls:
                    self.add_edge(dynamic_calls[parent_key], node_id, "controls_dynamic",
                                  depth=event.metadata.get("call_depth"),
                                  evidence="Observed")
            elif parent_invocation is not None and parent_key in dynamic_calls:
                self.add_edge(dynamic_calls[parent_key], node_id, "controls_dynamic",
                              depth=event.metadata.get("call_depth"), evidence="Observed")
            loop_target = event.metadata.get("loop_target_offset")
            # A marker belongs to the current frame's InvocationID, while a
            # nested action names that frame as parent_invocation_id. This
            # is why marker and action metadata use different fields here.
            loop_scope = (event.invocation_id
                          if event.kind == "loop_iteration" else
                          event.metadata.get("loop_parent_invocation_id",
                                             event.metadata.get("parent_invocation_id")))
            loop_key = (str(process), loop_scope, loop_target)
            if event.kind == "loop_iteration" and loop_target is not None:
                loop_markers[loop_key] = (node_id, event.metadata.get("iteration"))
            elif loop_target is not None:
                marker = loop_markers.get(loop_key)
                if marker is not None:
                    marker_id, marker_iteration = marker
                    self.add_edge(marker_id, node_id, "loop_controls",
                                  iteration=(event.metadata.get("loop_iteration")
                                             if event.metadata.get("loop_iteration") is not None
                                             else marker_iteration),
                                  loop_target_offset=loop_target,
                                  evidence="Observed")
            # Keep the six SCAR dimensions explicit in the graph.  These
            # nodes are per invocation/event, so a later pass can distinguish
            # a control dependency, a correctness contract, and a timing
            # observation instead of inferring them from Action labels.
            control_id = f"control:{idx}"
            self.add_node(GraphNode(control_id, NodeKind.CONTROL, event.kind,
                                    event.code_id, labels=["CONTROL"],
                                    attrs={"invocation_id": event.invocation_id}))
            self.add_edge(control_id, node_id, "controls")
            contract_id = f"contract:{idx}"
            self.add_node(GraphNode(contract_id, NodeKind.CONTRACT, "effect_contract",
                                    event.code_id, labels=["CONTRACT"],
                                    attrs={"evidence": event.evidence,
                                           "effect": event.effect.as_dict()}))
            self.add_edge(node_id, contract_id, "subject_to")
            measurement_id = f"measurement:{idx}"
            self.add_node(GraphNode(measurement_id, NodeKind.MEASUREMENT, "runtime_measurement",
                                    event.code_id, labels=["MEASUREMENT"],
                                    attrs={"timestamp_ns": event.ts_ns,
                                           "duration_ns": event.duration_ns,
                                           "resource": event.resource,
                                           "metadata": event.metadata,
                                           "evidence": event.evidence}))
            self.add_edge(node_id, measurement_id, "measured_by")
            if previous_id is not None:
                self.add_edge(previous_id, node_id, "record_order", implies_happens_before=False)
            previous_id = node_id
            for key, value in event.resource.items():
                resource_id = f"resource:{key}:{value}"
                self.add_node(GraphNode(resource_id, NodeKind.RESOURCE, key,
                                        labels=["RESOURCE"], attrs={"value": value}))
                self.add_edge(node_id, resource_id, "uses_resource")
            stream = event.resource.get("stream")
            if stream is not None and str(stream).lower() not in {"", "none", "unknown"}:
                stream_key = (
                    str(process), str(event.resource.get("device", "unknown")),
                    str(event.resource.get("context", "unknown")), str(stream),
                )
                previous_stream = last_stream_event.get(stream_key)
                if previous_stream is not None:
                    self.add_edge(previous_stream, node_id, "stream_order",
                                  happens_before=True, evidence="Observed",
                                  stream=stream, device=event.resource.get("device"),
                                  context=event.resource.get("context"))
                last_stream_event[stream_key] = node_id
            observed_input_versions: set[str] = set()
            for inp in event.inputs:
                sid = inp.get("logical_version", inp.get("object_id", "unknown"))
                observed_input_versions.add(str(sid))
                state_id = f"state:{sid}"
                self.add_node(GraphNode(state_id, NodeKind.STATE, "logical_version",
                                        labels=["STATE"], attrs=inp))
                self.add_edge(state_id, node_id, "reads")
                if inp.get("state_role") == "callable":
                    # Passing a callable exposes a control/state boundary,
                    # but does not prove registration, invocation count, or
                    # whether an unknown callee retained it. Keep that
                    # uncertainty explicit for simplification passes.
                    self.add_edge(node_id, state_id, "captures_callable",
                                  evidence="Observed", status="UNKNOWN")
                producer = last_writer.get(str(sid))
                if producer is not None:
                    self.add_edge(producer, node_id, "data_depends",
                                  logical_version=sid, evidence="Observed")
                self._add_entity_region(inp, state_id, known_regions)

            # Non-tensor state (module fields, Python containers, RNG or an
            # external handle) may be present only in the effect summary. It
            # still participates in the dependency graph when a runtime
            # observer provided its logical identity.
            for sid in event.effect.reads:
                if str(sid) in observed_input_versions:
                    continue
                state_id = f"state:{sid}"
                if state_id not in self.nodes:
                    self.add_node(GraphNode(state_id, NodeKind.STATE, "logical_version",
                                            labels=["STATE"], attrs={"logical_version": sid}))
                self.add_edge(state_id, node_id, "reads", origin="effect")
                producer = last_writer.get(str(sid))
                if producer is not None:
                    self.add_edge(producer, node_id, "data_depends",
                                  logical_version=sid, evidence="Observed")
            for out in event.outputs:
                sid = out.get("logical_version", out.get("object_id", "unknown"))
                state_id = f"state:{sid}"
                self.add_node(GraphNode(state_id, NodeKind.STATE, "logical_version",
                                        labels=["STATE"], attrs=out))
                self.add_edge(node_id, state_id, "writes")
                previous_writer = last_writer.get(str(sid))
                if previous_writer is not None and previous_writer != node_id:
                    self.add_edge(previous_writer, node_id, "overwrites",
                                  logical_version=sid, evidence="Observed")
                last_writer[str(sid)] = node_id
                self._add_entity_region(out, state_id, known_regions)

            # Effects can name versions that are not represented as a tensor
            # input/output (for example a state slot or an in-place dispatch
            # write).  Preserve those facts as graph dependencies too.  An
            # empty collection is not interpreted as "no effect" when the
            # effect knowledge is UNKNOWN; the edge only records members that
            # were actually observed.
            for sid in event.effect.writes:
                state_id = f"state:{sid}"
                if state_id not in self.nodes:
                    self.add_node(GraphNode(state_id, NodeKind.STATE, "logical_version",
                                            labels=["STATE"], attrs={"logical_version": sid}))
                previous_writer = last_writer.get(str(sid))
                if previous_writer is not None and previous_writer != node_id:
                    self.add_edge(previous_writer, node_id, "overwrites",
                                  logical_version=sid, evidence="Observed")
                self.add_edge(node_id, state_id, "writes", origin="effect")
                last_writer[str(sid)] = node_id
            for sid in event.effect.escapes:
                state_id = f"state:{sid}"
                if state_id not in self.nodes:
                    self.add_node(GraphNode(state_id, NodeKind.STATE, "logical_version",
                                            labels=["STATE"], attrs={"logical_version": sid}))
                self.add_edge(node_id, state_id, "escapes", evidence="Observed")

            # A Python function can return another callable (a closure,
            # bound method, or partial).  The return value is an externally
            # visible control/state handle even when no Tensor output exists.
            # Keep the identity observed while marking the continuation of
            # that callable beyond this action UNKNOWN: a caller may retain,
            # register, invoke, or mutate its captured state later.
            for returned_callable in event.metadata.get("returned_callables", []):
                if not isinstance(returned_callable, dict):
                    continue
                logical = returned_callable.get("logical_version")
                object_id = returned_callable.get("object_id")
                sid = logical or object_id
                if not sid:
                    continue
                state_id = f"state:{sid}"
                attrs = {**returned_callable, "state_role": "callable"}
                self.add_node(GraphNode(state_id, NodeKind.STATE, "callable",
                                        labels=["STATE", "CTRL"], attrs=attrs))
                self.add_edge(node_id, state_id, "escapes",
                              evidence="Observed", status="UNKNOWN",
                              escape_kind="callable")

            # A physical CUDA activity may be joined to a logical version by
            # the trace finalizer. Preserve that R↔Σ link separately from
            # ordinary action outputs; an UNKNOWN or ambiguous mapping emits
            # no state edge.
            if event.kind == "cuda_memcpy":
                logical = event.metadata.get("logical_version")
                confidence = event.metadata.get("mapping_confidence")
                if logical and confidence in {"Observed", "Inferred"}:
                    state_id = f"state:{logical}"
                    if state_id not in self.nodes:
                        self.add_node(GraphNode(
                            state_id, NodeKind.STATE, "logical_version",
                            labels=["STATE"], attrs={
                                "logical_version": logical,
                                "storage_id": event.metadata.get("storage_id"),
                                "mapping_confidence": confidence,
                            }))
                    self.add_edge(node_id, state_id, "materializes_physical",
                                  direction=event.resource.get("direction"),
                                  bytes=event.resource.get("bytes"),
                                  confidence=confidence,
                                  evidence=confidence)

    def _add_entity_region(self, value: dict, state_id: str,
                           known_regions: dict[tuple[str, int], dict[tuple, tuple[str, Region]]]) -> None:
        """Add object/region identity and conservative alias edges."""
        object_value = value.get("object_id")
        object_id = f"object:{object_value}" if object_value else None
        if object_id:
            self.add_node(GraphNode(object_id, NodeKind.STATE, "object",
                                    labels=["STATE"], attrs=value))
            self.add_edge(object_id, state_id, "materializes")
        storage = value.get("storage_id")
        if not storage:
            return
        logical = str(value.get("logical_version", "unknown"))
        region_id = (f"region:{storage}:{logical}:{value.get('offset', 0)}:"
                     f"{tuple(value.get('shape', []))}:"
                     f"{tuple(value.get('strides', []))}:{value.get('dtype', 'unknown')}:"
                     f"{value.get('device', 'unknown')}")
        region = self._region_from_value(value)
        if region is None:
            return
        self.add_node(GraphNode(region_id, NodeKind.STATE, "region",
                                labels=["STATE"], attrs=value))
        if object_id:
            self.add_edge(object_id, region_id, "has_region")
        self.add_edge(region_id, state_id, "version_of")
        storage_key = (region.storage.value, region.storage.epoch)
        geometry = (region.offset, region.shape, region.strides,
                    region.dtype, region.device)
        bucket = known_regions.setdefault(storage_key, {})
        for old_id, old_region in bucket.values():
            overlap = old_region.overlap(region)
            if overlap != "DISJOINT":
                self.add_edge(old_id, region_id, "aliases", overlap=overlap)
        # Keep the first region node for this geometry as the canonical alias
        # representative. New logical versions still get their own region
        # node and an exact alias edge, but are not compared against one
        # another repeatedly.
        bucket.setdefault(geometry, (region_id, region))

    @staticmethod
    def _region_from_value(value: dict) -> Region | None:
        storage = value.get("storage_id")
        if not storage:
            return None
        logical = str(value.get("logical_version", "unknown"))
        match = re.search(r"@(-?\d+):v", logical)
        epoch = int(match.group(1)) if match else 0
        try:
            return Region(StorageID(str(storage), epoch),
                          int(value.get("offset", 0)),
                          tuple(int(x) for x in value.get("shape", [])),
                          tuple(int(x) for x in value.get("strides", [])),
                          str(value.get("dtype", "unknown")),
                          str(value.get("device", "unknown")),
                          LogicalVersion(logical))
        except (TypeError, ValueError):
            return None

    def write_json(self, path: str | Path) -> None:
        self.assert_valid()
        Path(path).write_text(json.dumps(
            self.to_dict(),
            default=lambda x: x.value if isinstance(x, Enum) else str(x),
            indent=2,
        ))

    @classmethod
    def read_json(cls, path: str | Path, *, validate: bool = True) -> "ProgramGraph":
        """Read a graph written by :meth:`write_json`."""
        with Path(path).open(encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle), validate=validate)
