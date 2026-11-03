"""Fixed unpack projections over original source and completion ports.

The edges describe component dependence, not identity between a container and
its elements. No runtime instance, builtin container, purity or value equality
is inferred by exposing this already retained language interface.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, replace
import hashlib
import json

from scar.ir.program.dependencies import (
    DependencyCondition, DependencyEdge, DependencyEvidence, DependencyFrontier,
    DependencyKind as K, DependencyMeaning as M, DependencyNeighborhood,
    DependencyPoint, GraphNamespace,
)
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import CompletionResult, ExitKind, ReferenceValue, StateVersionValue, TerminatorKind
from scar.ir.program.providers import ProviderFactReference
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.program.source_language import SourceLanguageCapability, UnpackShape
from scar.ir.program.structured import ControlEdgeReference, PythonProtocol
from scar.ir.record_codec import decode, encode
from scar.ir.v2.common import SourceReference


def _need(ok, detail):
    if not ok:
        raise ValueError("unpack projection: " + detail)


@dataclass(frozen=True, slots=True)
class UnpackInterface:
    body: SourceBodyNamespace
    operation: OperationID
    source: SourceReference
    rhs: UseID
    world: UseID
    outputs: tuple[ValueID, ...]
    normal: ControlEdgeReference
    normal_world: ValueID
    raised: ControlEdgeReference
    raised_payloads: tuple[ValueID, ...]
    raised_world: ValueID
    child_targets: tuple[SourceReference, ...]

    def __post_init__(self):
        for value, kind in ((self.body, SourceBodyNamespace), (self.operation, OperationID),
                (self.source, SourceReference), (self.rhs, UseID), (self.world, UseID),
                (self.normal, ControlEdgeReference), (self.normal_world, ValueID),
                (self.raised, ControlEdgeReference), (self.raised_world, ValueID)):
            if type(value) is not kind:
                raise TypeError("unpack interface requires original " + kind.__name__)
        for rows, kind in ((self.outputs, ValueID), (self.raised_payloads, ValueID),
                (self.child_targets, SourceReference)):
            if type(rows) is not tuple or any(type(row) is not kind for row in rows):
                raise TypeError("unpack interface requires ordered original typed ports")
        _need(len(self.outputs) == len(self.child_targets) and self.rhs != self.world
            and len(set(self.outputs)) == len(self.outputs)
            and self.normal.operation == self.raised.operation == self.operation
            and self.normal != self.raised, "unpack interface changed its arity or original distinct ports")


@dataclass(frozen=True, slots=True)
class UnpackProjection:
    interface: UnpackInterface
    index: int

    def __post_init__(self):
        if type(self.interface) is not UnpackInterface:
            raise TypeError("unpack projection needs its original typed interface")
        self.interface.__post_init__()
        _need(type(self.index) is int and 0 <= self.index < len(self.interface.outputs),
            "unpack projection needs its original normal-result ordinal")


class UnpackProjectionProvider:
    """One receipt-owned batch index, queried by original output or RHS Use."""
    relation_kinds = frozenset((K.PROJECTION,))

    def __init__(self, session):
        self.session = session
        self.batches = self.hits = 0

    @staticmethod
    def _span(value):
        if isinstance(value, ast.AST):
            return value.lineno, value.end_lineno, value.col_offset, value.end_col_offset
        return value.start_line, value.end_line, value.start_column, value.end_column

    @staticmethod
    def _completion(body, operation, kind):
        signatures = [row for row in operation.completions if row.kind is kind]
        edges = [(ordinal, row) for ordinal, row in enumerate(operation.terminator.successors) if row.kind is kind]
        _need(len(signatures) == len(edges) == 1, "unpack lost its unique normal/raise signature")
        signature, = signatures
        ordinal, edge = edges[0]
        block = body.index._block_records[edge.block]
        _need(len(block.arguments) == len(edge.arguments), "unpack landing arity differs")
        slots = {}
        for formal, actual in zip(block.arguments, edge.arguments):
            _need(type(actual) is CompletionResult and actual.index not in slots,
                "unpack landing is not its original produced completion slot")
            slots[actual.index] = formal
        _need(set(slots) == set(range(len(signature.types))), "unpack completion slot order differs")
        ordered = tuple(slots[index] for index in range(len(signature.types)))
        _need(bool(ordered) and type(body.index.values[ordered[-1]]) is StateVersionValue
            and all(type(body.index.values[value]) is not StateVersionValue for value in ordered[:-1]),
            "unpack completion has no unique final original world")
        return ControlEdgeReference(operation.id, ordinal), ordered[:-1], ordered[-1]

    def _tables(self, point):
        # Loading checks each supplied receipt/declaration even when the
        # immutable source-derived table is already retained by this session.
        body = self.session.load(point.namespace)
        if type(getattr(body, "namespace", None)) is not SourceBodyNamespace:
            return None
        _need((type(point.node) is ValueID and point.node in body.index.values)
            or (type(point.node) is UseID and point.node in body.index._uses),
            "query is not an original value/Use in this body")
        key = "unpack-projection-inputs", point.namespace.identity
        saved = self.session._get(key)
        if saved is not None:
            self.hits += 1
            return saved
        document = body.document
        raw_protocols = (document.get("structured") or {}).get("protocols", ())
        protocols = [(number, decode(PythonProtocol, row)) for number, row in enumerate(raw_protocols)
            if row.get("kind") == "UNPACK_FIXED"]
        outputs, inputs, notes, locations = {}, {}, {}, {}
        tables = outputs, inputs, notes, locations
        if not protocols:
            return self.session._put(key, tables, 64)
        _need(len({row.operation for _, row in protocols}) == len(protocols), "duplicate original unpack protocol")
        language = document.get("language")
        shapes = {}
        if language is not None:
            _need(language.get("source") == encode(body.metadata.source), "unpack language source version differs")
            for number, raw in enumerate(language.get("unpackings", ())):
                shape = decode(UnpackShape, raw)
                _need(shape.operation not in shapes, "duplicate original unpack shape")
                shapes[shape.operation] = number, shape
        raw_ports = {}
        for protocol_number, protocol in protocols:
            self.session.check()
            operation = body.index.operations.get(protocol.operation)
            _need(operation is not None and operation.terminator is not None
                and operation.terminator.kind is TerminatorKind.INVOKE and not operation.effects_complete,
                "unpack protocol is not its original incomplete INVOKE")
            owned = {use.id: use for use in operation.uses}
            actuals = tuple(owned[identity] for identity in operation.invoke_arguments)
            _need(len(actuals) == 2 and type(body.index.values[actuals[0].value]) is ReferenceValue
                and type(body.index.values[actuals[1].value]) is StateVersionValue,
                "unpack requires its original one RHS reference and world Use")
            normal, values, after = self._completion(body, operation, ExitKind.NORMAL)
            raised, payloads, raised_world = self._completion(body, operation, ExitKind.RAISE)
            _need(all(type(body.index.values[value]) is ReferenceValue for value in values),
                "unpack normal outputs must be original reference slots")
            raw_ports[protocol.operation] = protocol_number, protocol, actuals, normal, values, after, raised, payloads, raised_world
            if (language is None or protocol.operation not in shapes
                    or SourceLanguageCapability.FIXED_UNPACK.value not in language.get("capabilities", ())):
                note = ("UNPACK_SHAPE_SCOPE_UNAVAILABLE",
                    "The original UNPACK protocol ports are retained, but its fixed-unpack language shape/capability is not recorded.")
                for identity in (actuals[0].id, *values):
                    notes[identity] = note
        if not any(operation in shapes for operation in raw_ports):
            return self.session._put(key, tables, 128 * len(notes))
        tree, semantic, text = self.session.source_context(body)
        _need("sha256:" + hashlib.sha256(text.encode()).hexdigest() == body.metadata.source.fingerprint,
            "unpack source text differs from its original source version")
        _need(any(ast.dump(ast.parse(text, filename=body.metadata.source.path, type_comments=comments), include_attributes=True)
            == ast.dump(tree, include_attributes=True) for comments in (False, True)), "unpack AST differs from retained source text")
        nodes, atoms, use_links, operation_links = defaultdict(list), defaultdict(list), {}, defaultdict(list)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Tuple, ast.List)) and isinstance(node.ctx, ast.Store):
                nodes[self._span(node)].append(node)
        for atom in semantic.source_atoms.values():
            reference = atom.reference
            if reference.path == body.metadata.source.path and reference.fingerprint == body.metadata.source.fingerprint:
                atoms[atom.kind, self._span(reference)].append(reference)
        for row in body.metadata.use_links:
            use_links[row.operation, row.use] = row
        for row in body.metadata.operation_links:
            operation_links[row.operation].append(row)
        operation_numbers = {operation.id: number for number, operation in enumerate(body.graph.operations)}
        descriptor = body.unit["artifacts"]["source"]
        source_locator = self.session._locator(str(self.session.root / descriptor["path"]),
            "scar.static-source-text/1", "#", ProviderFactReference(
                body.namespace.graph.declaration.artifact, f"#/units/{body.unit_number}/artifacts/source"))
        for operation_id, ports in raw_ports.items():
            self.session.check()
            protocol_number, protocol, actuals, normal, values, after, raised, payloads, raised_world = ports
            if actuals[0].id in notes:
                continue
            shape_number, shape = shapes[operation_id]
            _need(shape.source == protocol.source, "unpack shape/protocol source differs")
            candidates = nodes[self._span(shape.source)]
            _need(len(candidates) == 1, "unpack target is not one original Tuple/List Store")
            node, = candidates
            _need(not any(isinstance(child, ast.Starred) for child in ast.walk(node))
                and atoms[type(node).__name__, self._span(node)] == [shape.source],
                "fixed unpack source target changed or contains starred syntax")
            original_children = []
            for child in node.elts:
                source_rows = atoms[type(child).__name__, self._span(child)]
                _need(len(source_rows) == 1, "unpack child has no unique original SG source")
                original_children.append(source_rows[0])
            _need(tuple(original_children) == shape.child_targets and len(values) == len(shape.child_targets),
                "unpack target order/result arity differs from its original source")
            links = operation_links[operation_id]
            _need(len(links) == 1 and links[0].source == shape.source,
                "unpack lost its original core/source operation join")
            rhs_source = use_links.get((operation_id, actuals[0].id))
            _need(rhs_source is not None and rhs_source.role == "unpack-source" and rhs_source.index == 0
                and rhs_source.source == shape.source, "unpack RHS Use/source role differs")
            interface = UnpackInterface(body.namespace, operation_id, shape.source,
                actuals[0].id, actuals[1].id, values, normal, after, raised, payloads, raised_world,
                shape.child_targets)
            inputs[interface.rhs] = interface
            for ordinal, value in enumerate(values):
                _need(value not in outputs, "normal reference output belongs to multiple unpack interfaces")
                outputs[value] = UnpackProjection(interface, ordinal)
            operation = body.index.operations[operation_id]
            normal_slots = {argument.index: number for number, argument in enumerate(
                operation.terminator.successors[normal.successor_index].arguments)}
            locations[operation_id] = (protocol_number, shape_number, operation_numbers[operation_id],
                normal_slots, source_locator)
        _need(set(shapes) <= set(raw_ports), "unpack shape has no original structured UNPACK protocol")
        self.batches += 1
        size = len(json.dumps(encode(tuple(inputs.values())), separators=(",", ":"), allow_nan=False).encode())
        return self.session._put(key, tables, size + 128 * (len(outputs) + len(notes)))

    def projection(self, point):
        if type(point) is not DependencyPoint:
            raise TypeError("unpack projection requires an original typed point")
        if type(point.node) is not ValueID:
            return None
        tables = self._tables(point)
        return tables[0].get(point.node) if tables is not None else None

    @staticmethod
    def _edge(point, projection, locations):
        interface = projection.interface
        source = DependencyPoint(point.namespace, interface.rhs, point.context)
        target = DependencyPoint(point.namespace, interface.outputs[projection.index], point.context)
        operation = DependencyPoint(point.namespace, interface.operation, point.context)
        protocol_number, shape_number, operation_number, normal_slots, source_locator = locations[interface.operation]
        graph = interface.body.graph
        # The slot is a proved static port mapping, not an unresolved runtime
        # predicate. Its source child and actual CompletionResult index are
        # retained in the typed contract and original-record evidence.
        evidence = DependencyEvidence("SOURCE_UNPACK_COMPONENT_PROJECTION_V1",
            (graph, replace(graph, pointer=f"#/language/unpackings/{shape_number}"),
                replace(graph, pointer=f"#/language/unpackings/{shape_number}/child_targets/{projection.index}"),
                replace(graph, pointer=f"#/structured/protocols/{protocol_number}"),
                replace(graph, pointer=(f"{graph.pointer}/operations/{operation_number}/terminator/successors/"
                    f"{interface.normal.successor_index}/arguments/{normal_slots[projection.index]}")),
                source_locator),
            (operation, source, target, DependencyPoint(point.namespace, interface.world, point.context),
                DependencyPoint(point.namespace, interface.normal_world, point.context)))
        guard = DependencyCondition("canonical", "SUCCESSOR_SELECTED", operation,
            interface.normal.successor_index)
        return DependencyEdge(source, target, K.PROJECTION, M.DEPENDENCE, (evidence,), (guard,))

    def _neighbors(self, point, outgoing):
        if type(point) is not DependencyPoint:
            raise TypeError("unpack query requires an original typed point")
        if type(point.node) is not (UseID if outgoing else ValueID):
            return DependencyNeighborhood()
        try:
            tables = self._tables(point)
            if tables is None:
                return DependencyNeighborhood()
            outputs, inputs, notes, locations = tables
            issue = notes.get(point.node)
            if issue is not None:
                return DependencyNeighborhood(frontiers=(DependencyFrontier(point, *issue),), enumerated=False)
            if outgoing:
                interface = inputs.get(point.node)
                projections = tuple(UnpackProjection(interface, index) for index in range(len(interface.outputs))) if interface is not None else ()
            else:
                selected = outputs.get(point.node)
                projections = () if selected is None else (selected,)
            return DependencyNeighborhood(tuple(self._edge(point, row, locations) for row in projections))
        except (OverflowError, TimeoutError) as error:
            return DependencyNeighborhood(frontiers=(DependencyFrontier(point, "UNPACK_PROJECTION_BUDGET",
                type(error).__name__ + ": " + str(error)),), enumerated=False)

    def incoming(self, point):
        return self._neighbors(point, False)

    def outgoing(self, point):
        return self._neighbors(point, True)

    def measurements(self):
        return {"batches_indexed": self.batches, "batch_hits": self.hits,
            "target_executed": False, "container_identity_or_type_proved": False}

    def clear(self):
        # Original input facts live in the owning session's metered LRU.
        pass


__all__ = ["UnpackInterface", "UnpackProjection", "UnpackProjectionProvider"]
