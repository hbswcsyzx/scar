"""Compact, expandable views of the existing canonical program graph.

This is a query projection: no producer, SSA value, region or dependency is
rewritten. Contiguous lowering runs stay within their original block. Their
crossing ports and effects remain visible; original membership permits exact
expansion without treating administrative steps as removable work.
"""
from __future__ import annotations

from collections import Counter

from scar.ir.program.control import PendingDispatchTerminator
from scar.ir.program.cleanup import CleanupRouteTerminator
from scar.ir.program.ids import RegionID
from scar.ir.program.model import BlockArgument, OperationResult, TerminatorKind
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.source import SourceRole
from scar.ir.record_codec import encode


_DETAIL_PROTOCOLS = frozenset((
    "FRAME_ENTER", "FRAME_BIND", "FRAME_DISCARD", "FRAME_EXIT",
    "FRAME_HOLD_TEMPORARY", "FRAME_RELEASE_TEMPORARY",
    "FUNCTION_EXCEPTION_PACKET", "FUNCTION_PENDING_COMPLETION",
    "FUNCTION_HANDLED_CONTEXT_ENTER", "FUNCTION_CLEANUP_RESUME",
    "FUNCTION_CLEANUP_REPLACE", "FUNCTION_FRAME_EXIT_EXCEPTION_PACKET",
    "FUNCTION_FRAME_EXIT_BINDINGS", "FUNCTION_START_PROPAGATION",
    "FUNCTION_CLEAR_EXCEPTION_NAME",
))


class ProgramRegionView:
    """One validated core index; all returned IDs keep this graph's namespace."""

    def __init__(self, graph, *, metadata=None, structured=None, interface=None):
        self.index = ProgramIndex(graph)
        self.graph = graph
        self.sources = {}
        self.calls = {}
        self.protocols = {}
        if metadata is not None:
            from scar.ir.program.source import LoweringMetadata
            if type(metadata) is not LoweringMetadata:
                raise TypeError("metadata must be LoweringMetadata")
            for link in metadata.operation_links:
                if link.operation not in self.index.operations:
                    raise ValueError("source link refers to another graph")
                self.sources.setdefault(link.operation, []).append(link)
            for call in metadata.call_targets:
                if call.operation not in self.index.operations:
                    raise ValueError("source call refers to another graph")
                self.calls.setdefault(call.operation, []).append(call)
        if structured is not None:
            from scar.ir.program.structured import StructuredBodyModel
            if type(structured) is not StructuredBodyModel:
                raise TypeError("structured must be StructuredBodyModel")
            structured.__post_init__()
            if structured.region not in self.index.regions:
                raise ValueError("structured source refers to another region")
            for row in structured.protocols:
                if row.operation not in self.index.operations:
                    raise ValueError("source protocol refers to another graph")
                self.protocols[row.operation] = row.kind.value
        self.structured = structured
        if interface is not None:
            from scar.ir.program.functions import BodyEntryInterface
            if type(interface) is not BodyEntryInterface or interface.region not in self.index.regions:
                raise ValueError("interface must describe an original body region")
            interface.__post_init__()
            if any(p.value not in self.index.values for p in interface.parameters) or interface.world not in self.index.values:
                raise ValueError("interface refers to another graph's values")
        self.interface = interface
        self.details = self._details()

    def _details(self):
        result = {}
        for row in self.graph.binding_definitions:
            origin = self.index.values[row.value].origin
            if type(origin) is OperationResult:
                result[origin.operation] = "LOCAL_BINDING"
        for row in self.graph.binding_reads:
            result[row.operation] = "LOCAL_BINDING_READ"
        for operation in self.graph.operations:
            kind = self.protocols.get(operation.id)
            if kind in _DETAIL_PROTOCOLS:
                result[operation.id] = kind
            term = operation.terminator
            if type(term) in (PendingDispatchTerminator, CleanupRouteTerminator):
                result[operation.id] = "COMPLETION_ROUTING"
            links = self.sources.get(operation.id, ())
            if (term is not None and term.kind is TerminatorKind.JUMP and links
                    and all(link.role is SourceRole.CONTROL and link.semantic_operation is None
                            for link in links)):
                result[operation.id] = "CONTROL_FORWARDING"
        return result

    def region(self, region=None, *, expand_lowering=False):
        if region is None:
            region = self.graph.root
        if type(region) is not RegionID or region not in self.index.regions:
            raise ValueError("region must be an original RegionID")
        if type(expand_lowering) is not bool:
            raise TypeError("expand_lowering must be bool")
        original = self.index.regions[region]
        nodes, owner, blocks, source_files, source_spans = {}, {}, [], {}, {}

        def source_links(identities):
            result = []
            for identity in identities:
                for link in self.sources.get(identity, ()):
                    source = link.source
                    file_key = (source.path, source.fingerprint)
                    if file_key not in source_files:
                        source_files[file_key] = "file:" + str(len(source_files))
                    key = source.atom_id.wire
                    span = {"file": source_files[file_key], "start_line": source.start_line,
                            "end_line": source.end_line, "start_column": source.start_column,
                            "end_column": source.end_column}
                    if key in source_spans and source_spans[key] != span:
                        raise ValueError("source atom has inconsistent original version/span")
                    source_spans[key] = span
                    result.append({"operation": identity.wire, "atom": key, "role": link.role.value,
                                   "semantic_operation": (link.semantic_operation.wire
                                                          if link.semantic_operation is not None else None)})
            return result

        for block in original.blocks:
            ordered = []
            position = 0
            while position < len(block.operations):
                start = position
                identity = block.operations[position]
                folded = not expand_lowering and identity in self.details
                position += 1
                if folded:
                    while position < len(block.operations) and block.operations[position] in self.details:
                        position += 1
                members = block.operations[start:position]
                # Keys belong only to this query, never to the canonical IR.
                key = "n" + str(len(nodes))
                operations = [self.index.operations[item] for item in members]
                nodes[key] = {
                    "kind": "LOWERING_INTERFACE" if folded else "OPERATION",
                    "members": [item.wire for item in members], "block": block.id.wire,
                    "start": start, "stop": position,
                    "behaviors": sorted({behavior.value for op in operations for behavior in op.behaviors}),
                    "effects_complete": all(op.effects_complete for op in operations),
                    "accesses": [{"operation": op.id.wire, "access": encode(access)}
                                 for op in operations for access in op.accesses],
                    "source_links": source_links(members),
                    "completions": [{"operation": op.id.wire, "signatures": encode(op.completions)}
                                    for op in operations if op.completions],
                }
                if folded:
                    nodes[key]["details"] = dict(Counter(self.details[item] for item in members))
                    nodes[key]["omission_means"] = "ENCODING_FOLDED; effects/lifetime/control not removed"
                else:
                    nodes[key]["label"] = operations[0].label
                    nodes[key]["protocol"] = self.protocols.get(identity)
                    nodes[key]["callee"] = (operations[0].callee.wire
                                            if operations[0].callee is not None else None)
                    nodes[key]["source_targets"] = encode(tuple(self.calls.get(identity, ())))
                for item in members:
                    owner[item] = key
                ordered.append(key)
            blocks.append({"id": block.id.wire, "arguments": [v.wire for v in block.arguments],
                           "nodes": ordered})
        entry_node = {row["id"]: row["nodes"][0] if row["nodes"] else None for row in blocks}
        data, control, evaluation, internal = [], [], [], Counter()
        for block in original.blocks:
            for before, after in zip(block.operations, block.operations[1:]):
                if owner[before] != owner[after]:
                    evaluation.append({"source": owner[before], "target": owner[after],
                                       "original_before": before.wire, "original_after": after.wire})
            for identity in block.operations:
                operation = self.index.operations[identity]
                for ordinal, use in enumerate(operation.uses):
                    value = self.index.values[use.value]
                    origin = value.origin
                    producer = origin.operation if type(origin) is OperationResult else None
                    source = owner.get(producer)
                    if source == owner[identity]:
                        internal[owner[identity]] += 1
                        continue
                    if producer is not None:
                        boundary = {"kind": "OPERATION_RESULT", "operation": producer.wire,
                                    "index": origin.index}
                    elif type(origin) is BlockArgument:
                        boundary = {"kind": "BLOCK_ARGUMENT", "block": origin.block.wire,
                                    "index": origin.index}
                    else:
                        boundary = {"kind": "LITERAL", "value": value.id.wire}
                    data.append({"source": source, "target": owner[identity], "origin": boundary,
                                 "value": use.value.wire, "consumer": identity.wire,
                                 "use": use.id.wire, "use_index": ordinal, "role": use.role.value})
                term = operation.terminator
                if term is not None:
                    for number, edge in enumerate(term.successors):
                        control.append({"source": owner[identity], "target": entry_node.get(edge.block.wire),
                                        "operation": identity.wire, "successor_index": number,
                                        "successor": encode(edge)})
                    if not term.successors:
                        control.append({"source": owner[identity], "target": None,
                                        "operation": identity.wire, "exit": encode(term)})
        ordering = [{"source": owner.get(edge.before), "target": owner.get(edge.after),
                     "original": encode(edge)} for edge in self.graph.ordering
                    if edge.before in owner or edge.after in owner]
        resource_uses = tuple(row for row in self.graph.resource_uses if row.operation in owner)
        requirement_ids = {row.requirement for row in resource_uses}
        requirements = tuple(row for row in self.graph.resource_requirements
                             if row.owner == region or row.owner in owner or row.id in requirement_ids)
        resource_ids = {row.definition for row in resource_uses if row.definition is not None}
        resources = tuple(row for row in self.graph.resources if row.id in resource_ids)
        for key, node in nodes.items():
            node["internal_uses"] = internal[key]
        return {
            "schema": "scar.program-region-view", "schema_version": 1,
            "region": region.wire, "entry": original.entry.wire, "exits": encode(original.exits),
            "interface": encode(self.interface) if self.interface and self.interface.region == region else None,
            "environment": encode(self.index.environment_interface(region)),
            "blocks": blocks, "nodes": nodes, "uses": data, "control": control,
            "evaluation_order": evaluation, "explicit_ordering": ordering,
            "resource_uses": encode(resource_uses), "resource_requirements": encode(requirements),
            "resources": encode(resources),
            "children": [r.id.wire for r in self.graph.regions if r.parent == region],
            "source_files": {key: {"path": path, "fingerprint": fingerprint}
                             for (path, fingerprint), key in source_files.items()},
            "source_spans": source_spans,
            "summary": {"original_operations": len(owner), "view_nodes": len(nodes),
                        "program_operations": sum(node["kind"] == "OPERATION" for node in nodes.values()),
                        "folded_operations": sum(op in self.details for op in owner) if not expand_lowering else 0,
                        "original_uses": sum(len(self.index.operations[op].uses) for op in owner),
                        "crossing_uses": len(data), "internal_uses": sum(internal.values())},
            "namespace": "ALL IDS REFER TO THE INPUT GRAPH; view node keys are query-local",
            "qualification": "TYPED_CORE_PROJECTION; source/runtime applicability not granted",
            "constraints": {"frame_rules": encode(self.structured.frame_rules) if self.structured else None,
                            "record_tables": {name: len(getattr(self.graph, name)) for name in (
                                "binding_definitions", "binding_reads", "control_scopes", "control_ports",
                                "exception_packets", "pending_completions", "cleanup_interfaces",
                                "cleanup_enters", "cleanup_resumes", "cleanup_replacements")},
                            "folding_is_work_elimination": False},
            "source_verified": False, "runtime_verified": False, "transformation_authorized": False,
        }

    def expand(self, key, *, region=None):
        """Original typed members of a folded run, with their exact operands."""
        view = self.region(region)
        if key not in view["nodes"]:
            raise KeyError(key)
        by_wire = {identity.wire: operation for identity, operation in self.index.operations.items()}
        return tuple(by_wire[identity] for identity in view["nodes"][key]["members"])

    def value(self, identity):
        """Original typed value/producer/consumers; no new content or alias claim."""
        from scar.ir.program.ids import ValueID
        if type(identity) is not ValueID:
            raise TypeError("value lookup requires an original ValueID")
        value = self.index.values[identity]
        return {"value": value, "consumers": self.index.consumers(identity)}


__all__ = ["ProgramRegionView"]


def read_source_region(path, *, expected_sha256, region=None, expand_lowering=False,
                       max_stored_bytes=128_000_000, max_decoded_bytes=256_000_000):
    """Read one retained graph; do not replay its whole source context."""
    import gzip
    import hashlib
    from io import BytesIO
    import os
    from pathlib import Path
    import re
    import stat
    import json
    from scar.ir.program.codec import loads as load_graph
    from scar.ir.program.source import LoweringMetadata
    from scar.ir.program.structured import StructuredBodyModel
    from scar.ir.record_codec import decode, loads

    if (type(expected_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
            or any(type(n) is not int or n < 1 for n in (max_stored_bytes, max_decoded_bytes))):
        raise ValueError("explicit source receipt and positive read bounds required")
    path = Path(path).absolute()
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_stored_bytes:
            raise ValueError("source must be a bounded regular file")
        stored = stream.read(max_stored_bytes + 1)
        after = os.fstat(stream.fileno())
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if (stamp(before) != stamp(after) or len(stored) != before.st_size
            or hashlib.sha256(stored).hexdigest() != expected_sha256):
        raise ValueError("source stored receipt changed or differs")
    if path.suffix == ".gz":
        with gzip.GzipFile(fileobj=BytesIO(stored)) as stream:
            raw = stream.read(max_decoded_bytes + 1)
    else:
        raw = stored
    if len(raw) > max_decoded_bytes:
        raise ValueError("decoded source exceeds read bound")
    document = loads(raw.decode("utf-8"))
    metadata = structured = interface = context_reference = original_locator = None
    pointer = "#/graph"
    if document.get("schema") == "scar.source-body-fragment":
        if type(document.get("schema_version")) is not int or document["schema_version"] != 1:
            raise ValueError("unsupported source body fragment")
        context_reference, original_locator = document["context"], document["original"]
        document, pointer = document["program"], "#/program/graph"
    if document.get("schema") in ("scar.source-program", "scar.body-construction-checkpoint"):
        versions = range(1, 9) if document["schema"] == "scar.source-program" else (1,)
        if type(document.get("schema_version")) is not int or document["schema_version"] not in versions:
            raise ValueError("unsupported source body envelope")
        graph_document = document["graph"]
        if graph_document is None:
            raise ValueError("source body has no canonical graph")
        metadata = decode(LoweringMetadata, document["metadata"])
        if document.get("structured") is not None:
            structured = decode(StructuredBodyModel, document["structured"])
        if document.get("interface") is not None:
            from scar.ir.program.functions import BodyEntryInterface
            interface = decode(BodyEntryInterface, document["interface"])
    elif document.get("schema") == "scar.program-graph":
        graph_document, pointer = document, "#"
    else:
        raise ValueError("expected a retained SourceProgram or canonical program graph")
    graph = load_graph(json.dumps(graph_document, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    view = ProgramRegionView(graph, metadata=metadata, structured=structured, interface=interface).region(
        region, expand_lowering=expand_lowering)
    view["source"] = {"uri": str(path), "stored_sha256": expected_sha256, "stored_bytes": len(stored),
                      "decoded_sha256": hashlib.sha256(raw).hexdigest(), "decoded_bytes": len(raw),
                      "pointer": pointer, "program_schema_version": graph_document["schema_version"]}
    view["source_context_replayed"] = False
    if context_reference is not None:
        view["context_reference"] = context_reference
        view["original_locator"] = original_locator
        view["context_reference_verified"] = False
    view["core_validated"] = True
    return view


def query_source_region_cli(args):
    import json
    from pathlib import Path
    import time

    started = time.monotonic()
    region = None
    if args.region is not None:
        prefix = RegionID.prefix + ":"
        if not args.region.startswith(prefix) or not args.region[len(prefix):]:
            raise ValueError("--region requires an original program_region ID")
        region = RegionID(args.region[len(prefix):])
    result = read_source_region(args.source, expected_sha256=args.sha256, region=region,
                                expand_lowering=args.expand_lowering,
                                max_stored_bytes=args.max_stored_bytes,
                                max_decoded_bytes=args.max_decoded_bytes)
    result["elapsed_s"] = time.monotonic() - started
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.out:
        with Path(args.out).open("x", encoding="utf-8") as stream:
            stream.write(payload)
    else:
        print(payload, end="")
    return 0


__all__ += ["read_source_region", "query_source_region_cli"]
