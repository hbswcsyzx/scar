"""Resolve retained conditional call routes to original qualified graph ports.

This is a bounded read-only adapter over existing reports, InventoryPartitions
and GraphIndex. It creates no producer, state, execution occurrence or proof of
equivalence. A report's original conditions remain attached to every answer.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import gzip
import hashlib
import io
from pathlib import Path

from scar.analysis.inventory_partitions import InventoryPartitions
from scar.ir.execution.coordinates import ExecutionRun
from scar.ir.program.call_operand_routes import ArgumentRoute, CompletionRoute
from scar.ir.program.ids import (BlockID, LocationID, OperationID, RegionID,
    ResourceDefinitionID, ResourceRequirementID, UseID, ValueID)
from scar.ir.program.model import ExitKind, StateVersionValue, TerminatorKind
from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.store.graph_index import GraphIndex


_KINDS = {"Block": BlockID, "StateLocation": LocationID, "Operation": OperationID,
    "Region": RegionID, "ResourceDefinition": ResourceDefinitionID,
    "ResourceRequirement": ResourceRequirementID, "Use": UseID, "Value": ValueID}


def _need(condition, detail):
    if not condition:
        raise ValueError("call endpoint query: " + detail)


def _hash(payload):
    return hashlib.sha256(payload).hexdigest()


def _receipt(path, payload):
    return {"path": str(path), "sha256": _hash(payload), "bytes": len(payload)}


def _bytes(path, limit):
    path = Path(path).absolute()
    _need(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit,
          "input is not an explicitly bounded regular carrier")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    _need(len(raw) <= limit, "carrier byte ceiling exceeded")
    return path, raw


class _ReportRows:
    """Read the already published partitioned-call-operand-links v1 format.

    Only manifest-local header/chunk carriers are opened. JSONL line locators
    are explicit evidence locations, never canonical graph identity.
    """
    def __init__(self, manifest, *, max_manifest_bytes, max_chunk_bytes):
        path, raw = _bytes(manifest, max_manifest_bytes)
        self.root, self.receipt = path.parent, _receipt(path, raw)
        self.document = strict_loads(raw.decode("utf-8"))
        self.limit, self.cache = max_chunk_bytes, OrderedDict()
        doc = self.document
        _need(doc.get("schema") == "scar.partitioned-call-operand-links"
              and type(doc.get("schema_version")) is int and doc["schema_version"] == 1
              and doc.get("original_schema") == "scar.call-operand-links"
              and type(doc.get("original_schema_version")) is int and doc["original_schema_version"] == 2
              and doc.get("canonical_graphs_copied") is False,
              "unsupported original report format or authority")
        header = self.carrier(doc["header"])
        self.header = strict_loads(header.decode("utf-8"))
        _need(type(doc.get("tables")) is dict, "missing bounded table directory")
        for table in doc["tables"].values():
            _need(type(table) is dict and type(table["rows"]) is int and table["rows"] >= 0
                  and type(table["chunks"]) is list
                  and all(type(chunk["rows"]) is int and chunk["rows"] > 0 for chunk in table["chunks"])
                  and sum(chunk["rows"] for chunk in table["chunks"]) == table["rows"],
                  "report table/chunk denominator differs")

    def carrier(self, declaration):
        _need(type(declaration) is dict and type(declaration.get("path")) is str,
              "report carrier lacks its exact original path")
        path = Path(declaration["path"])
        _need(path.is_absolute() and path.resolve().is_relative_to(self.root.resolve()),
              "report-selected carrier escapes its explicit archive")
        path, stored = _bytes(path, self.limit)
        _need(len(stored) == declaration["bytes"] and _hash(stored) == declaration["sha256"],
              "stored report carrier receipt differs")
        with gzip.GzipFile(fileobj=io.BytesIO(stored)) as stream:
            raw = stream.read(self.limit + 1)
        _need(len(raw) <= self.limit and len(raw) == declaration["decoded_bytes"]
              and _hash(raw) == declaration["decoded_sha256"], "decoded report carrier receipt differs")
        return raw

    def row(self, table, ordinal):
        _need(table in self.document["tables"] and type(ordinal) is int
              and 0 <= ordinal < self.document["tables"][table]["rows"],
              "table/ordinal is outside the original report")
        first = 0
        for number, chunk in enumerate(self.document["tables"][table]["chunks"]):
            if ordinal < first + chunk["rows"]:
                cache_key = table, number
                if cache_key not in self.cache:
                    raw = self.carrier(chunk)
                    lines = raw.splitlines(keepends=True)
                    _need(len(lines) == chunk["rows"] and all(line.endswith(b"\n") for line in lines),
                          "selected JSONL chunk has a different complete-line count")
                    self.cache[cache_key] = lines
                    while len(self.cache) > 2:
                        self.cache.popitem(last=False)
                self.cache.move_to_end(cache_key)
                line = ordinal - first
                payload = self.cache[cache_key][line]
                record = strict_loads(payload.decode("utf-8"))
                return record, {"manifest": deepcopy(self.receipt), "table": table,
                    "ordinal": ordinal, "chunk": deepcopy(chunk), "line": line + 1,
                    "pointer_within_line": "", "row_sha256": _hash(payload)}
            first += chunk["rows"]
        raise ValueError("report denominator did not select a chunk")


class CallEndpointQueries:
    """Navigate one explicit Run's conditional report into original graph ports.

    Inputs are explicit, already produced snapshots. Hash checks establish
    carrier correspondence, not that a forged report is a trustworthy runtime
    producer. Original capture, source and routing conditions are not replayed
    or removed. No current source is parsed or compiled by this reader.
    """
    def __init__(self, graph_index, inventory, report_manifest, *, expected_run,
                 source_report, source_bindings, max_manifest_bytes=4_000_000,
                 max_chunk_bytes=16_000_000, max_source_report_bytes=16_000_000):
        _need(type(graph_index) is GraphIndex and type(inventory) is InventoryPartitions
              and type(expected_run) is ExecutionRun, "explicit original index/inventory/Run required")
        _need(all(type(bound) is int and bound > 0 for bound in
              (max_manifest_bytes, max_chunk_bytes, max_source_report_bytes)), "invalid query byte ceilings")
        self.graph, self.inventory, self.run = graph_index, inventory, expected_run
        self.rows = _ReportRows(report_manifest, max_manifest_bytes=max_manifest_bytes,
                                max_chunk_bytes=max_chunk_bytes)
        header = self.rows.header
        _need(header.get("schema") == "scar.call-operand-links"
              and type(header.get("schema_version")) is int and header["schema_version"] == 2
              and header.get("whole_program_complete") is False
              and header.get("transformation_authorized") is False,
              "report is not the supported conditional source-body form")
        scope = header["source_body_access"]
        _need(scope.get("schema") == "scar.call-source-body-access"
              and type(scope.get("schema_version")) is int and scope["schema_version"] == 1
              and scope.get("current_raw_scan_verified") is True
              and scope.get("canonical_producers_copied") is False
              and scope.get("transformation_authorized") is False
              and scope["run"] == encode(expected_run), "source-body scope or expected Run differs")
        self.scope = deepcopy(scope)
        source_path, source_raw = _bytes(source_report, max_source_report_bytes)
        bindings_path, bindings_raw = _bytes(source_bindings, max_source_report_bytes)
        _need(_receipt(source_path, source_raw) == scope["source_report"]
              and _receipt(bindings_path, bindings_raw) == scope["source_bindings"],
              "explicit source report/bindings do not match the retained routing receipts")
        source = strict_loads(source_raw.decode("utf-8"))
        bindings = strict_loads(bindings_raw.decode("utf-8"))
        _need(source.get("schema") == "scar.source-invocations"
              and type(source.get("schema_version")) is int and source["schema_version"] in (2, 3)
              and source["run"] == encode(expected_run)
              and source.get("current_capture_raw_scan_verified") is True
              and source.get("old_capture_dynamic_facts_used_for_current_run") is False
              and source["composition_canonical_sha256"] == scope["composition_canonical_sha256"]
              and source["inventory"] == scope["inventory"],
              "source report is not this independently scanned Run")
        _need(source["bindings"]["raw_sha256"] == _hash(bindings_raw)
              and source["bindings"]["raw_bytes"] == len(bindings_raw)
              and bindings.get("schema") == "scar.source-invocation-bindings"
              and type(bindings.get("schema_version")) is int
              and bindings["schema_version"] == source["schema_version"]
              and bindings.get("transformation_authorized") is False,
              "source report and explicit binding carrier differ")
        declared = scope["inventory"]
        original = inventory.manifest_receipt
        indexed = graph_index.snapshot["manifest_receipt"]
        _need(declared["path"] == graph_index.snapshot["manifest_uri"]
              and declared["raw_sha256"] == original["physical_sha256"] == indexed["physical_sha256"]
              and declared["raw_bytes"] == original["physical_bytes"] == indexed["physical_bytes"]
              and declared["decoded_bytes"] == original["decoded_bytes"] == indexed["decoded_bytes"],
              "index, inventory and routing scope have different original snapshots")
        _need(len(bindings["bindings"]) == source["summary"]["entered_code_groups"],
              "source binding denominator differs")
        self.processes = {row["process_id"] for row in source["collection_metadata"]}
        self.namespaces = {}
        for definition, info in scope["namespaces"].items():
            _need(definition not in scope["bare_definition_conflicts"]
                  and type(info["file_index"]) is int and info["file_index"] >= 0
                  and type(info["body_index"]) is int and info["body_index"] >= 0
                  and info["namespace"]["body"]["definition"]["wire"] == definition,
                  "ambiguous or contradictory original body namespace")
            identity = self._namespace_key(info["namespace"])
            _need(identity not in self.namespaces, "two source definitions acquired one original namespace")
            self.namespaces[identity] = (definition, deepcopy(info))
        self.bodies = OrderedDict()

    @staticmethod
    def _namespace_key(namespace):
        import json
        return json.dumps(namespace, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def _body(self, definition):
        wire = definition if type(definition) is str else definition.wire
        _need(wire in self.scope["namespaces"] and wire not in self.scope["bare_definition_conflicts"],
              "definition has no unique selected original canonical body")
        if wire not in self.bodies:
            info = self.scope["namespaces"][wire]
            typed = self.inventory.typed_body(info["file_index"], info["body_index"])
            _need(typed.namespace == info["namespace"] and typed.body.definition.wire == wire
                  and typed.body.graph is not None and typed.interface is not None
                  and typed.public_graph_validated,
                  "selected original body/namespace/interface differs")
            graph = typed.body.graph
            self.bodies[wire] = {"typed": typed, "graph": graph,
                "operations": {row.id: row for row in graph.operations},
                "values": {row.id: row for row in graph.values},
                "uses": {use.id: (operation, use) for operation in graph.operations for use in operation.uses},
                "blocks": {block.id: block for region in graph.regions for block in region.blocks}}
            while len(self.bodies) > 2:
                self.bodies.popitem(last=False)
        self.bodies.move_to_end(wire)
        return self.bodies[wire]

    def endpoint(self, reference):
        _need(type(reference) is dict and set(reference) == {"namespace", "kind", "local_id"}
              and reference["kind"] in _KINDS, "exact qualified canonical endpoint required")
        identity = self._namespace_key(reference["namespace"])
        _need(identity in self.namespaces, "namespace is outside this report's selected original body scope")
        info = self.namespaces[identity][1]
        local = reference["local_id"]
        identifier = decode(_KINDS[reference["kind"]], local) if type(local) is dict else local
        _need(type(identifier) is _KINDS[reference["kind"]], "endpoint kind and typed original ID disagree")
        body = self._body(self.namespaces[identity][0])
        qualified = {"namespace": deepcopy(body["typed"].namespace),
                     "kind": reference["kind"], "local_id": encode(identifier)}
        _need(qualified["namespace"] == reference["namespace"], "inventory and requested original namespaces differ")
        entity = self.graph.entity(qualified)
        _need(entity is not None and entity["artifact_receipt"]["decoded_sha256"] ==
              info["graph_locator"]["artifact"]["decoded_sha256"], "endpoint is absent from the selected original index")
        return entity

    def _endpoint(self, definition, kind, identifier):
        info = self.scope["namespaces"][definition.wire]
        return self.endpoint({"namespace": info["namespace"], "kind": kind, "local_id": identifier})

    def _route(self, table, ordinal, kind):
        raw, locator = self.rows.row(table, ordinal)
        route = decode(kind, raw)
        _need(encode(route) == raw and route.caller.process_id in self.processes
              and route.callee.process_id in self.processes, "route wire or original process scope differs")
        caller, callee = self._body(route.caller_definition), self._body(route.callee_definition)
        _need(route.caller_region == caller["graph"].root and route.callee_region == callee["graph"].root,
              "route's original caller/callee regions differ")
        operation = caller["operations"].get(route.operation)
        _need(operation is not None and operation.terminator is not None
              and operation.terminator.kind is TerminatorKind.INVOKE, "route caller has no original invoke")
        links = [row for row in caller["typed"].body.metadata.operation_links if row.operation == route.operation]
        _need(len(links) == 1 and links[0].semantic_operation == route.call and links[0].source == route.call_source,
              "route's call is not its original source/core operation")
        endpoints = {"caller_operation": self._endpoint(route.caller_definition, "Operation", route.operation),
            "caller_region": self._endpoint(route.caller_definition, "Region", route.caller_region),
            "callee_region": self._endpoint(route.callee_definition, "Region", route.callee_region)}
        return raw, locator, route, caller, callee, operation, endpoints

    def _answer(self, raw, locator, endpoints):
        return {"run": encode(self.run), "route": raw, "report_record": locator, "endpoints": endpoints,
            "conditions": deepcopy(raw["conditions"]), "original_endpoint_membership_verified": True,
            "source_conditions": deepcopy(self.scope["source_producer_conditions"]),
            "original_capture_and_source_proofs_replayed": False, "runtime_control_established": False,
            "cross_body_state_domain_identity_established": False, "world_equivalence_established": False,
            "contents_or_alias_equivalence_established": False, "all_relationships_indexed": False,
            "whole_program_established": False, "transformation_authorized": False}

    def argument(self, ordinal):
        raw, locator, route, caller, callee, operation, endpoints = self._route(
            "routing.argument_routes", ordinal, ArgumentRoute)
        owner, actual = caller["uses"].get(route.actual_use, (None, None))
        _need(owner is operation and actual.value == route.actual_value
              and route.actual_index + 1 < len(operation.invoke_arguments)
              and operation.invoke_arguments[route.actual_index + 1] == route.actual_use,
              "actual does not retain its original operation/ordered Use/value")
        _need(any(port.slot == route.formal_slot and port.value == route.formal_value
                  for port in callee["typed"].interface.parameters), "formal is not an original declared parameter port")
        use_links = [row for row in caller["typed"].body.metadata.use_links
                     if row.operation == route.operation and row.use == route.actual_use]
        _need(len(use_links) == 1 and use_links[0].source == route.actual_source,
              "actual operand lost its original source reference")
        endpoints.update(caller_actual_use=self._endpoint(route.caller_definition, "Use", route.actual_use),
            caller_actual_value=self._endpoint(route.caller_definition, "Value", route.actual_value),
            callee_formal_value=self._endpoint(route.callee_definition, "Value", route.formal_value))
        return self._answer(raw, locator, endpoints)

    def completion(self, ordinal):
        raw, locator, route, caller, callee, operation, endpoints = self._route(
            "routing.completion_routes", ordinal, CompletionRoute)
        normal = [edge for edge in operation.terminator.successors if edge.kind is ExitKind.NORMAL]
        _need(len(normal) == 1 and caller["blocks"][normal[0].block].arguments[0] == route.normal_result,
              "normal result is not the original invoke normal payload")
        owner, payload = callee["uses"].get(route.payload_use, (None, None))
        _need(owner is not None and payload.value == route.payload_value and owner.terminator is not None
              and owner.terminator.kind is TerminatorKind.RETURN
              and len(owner.terminator.values) == 2 and owner.terminator.values[0] == route.payload_use,
              "callee payload is not an original normal RETURN Use/value")
        state_owner, state = callee["uses"].get(owner.terminator.values[1], (None, None))
        world = callee["values"].get(route.post_world)
        _need(state_owner is owner and state.value == route.post_world and type(world) is StateVersionValue,
              "callee post-world is not the original RETURN state port")
        endpoints.update(caller_normal_result=self._endpoint(route.caller_definition, "Value", route.normal_result),
            callee_payload_use=self._endpoint(route.callee_definition, "Use", route.payload_use),
            callee_payload_value=self._endpoint(route.callee_definition, "Value", route.payload_value),
            callee_post_world=self._endpoint(route.callee_definition, "Value", route.post_world),
            callee_world_location=self._endpoint(route.callee_definition, "StateLocation", world.location))
        return self._answer(raw, locator, endpoints)


__all__ = ["CallEndpointQueries"]
