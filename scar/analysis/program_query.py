"""On-demand traversal of qualified program fragments.

This is a read-only view, not another graph authority. Query-local node keys
deduplicate exact typed references; their original artifacts and IDs remain in
``nodes``. A work query uses the ordinary retained-relation validator before
exposing edges. Index enumeration alone does not validate runtime endpoints.
"""
from __future__ import annotations

import re

from scar.ir.execution.fragment_relations import (
    HostRelationKind, WorkRelations, need, stable_key,
)
from scar.ir.execution.fragment_relations_codec import from_dict
from scar.ir.record_codec import encode, loads as strict_loads
from scar.store.fragment_relations import Meter, RelationBudgets, RelationPartitions


class ProgramQuery:
    """Bounded access to original work, invocation and source references."""

    def __init__(self, manifest, *, expected_sha256, budgets=None):
        self.budgets = budgets or RelationBudgets(
            max_input_bytes=256_000_000, max_seconds=60)
        self.relations = RelationPartitions(
            manifest, expected_sha256=expected_sha256, budgets=self.budgets)

    def list_work(self, *, offset=0, limit=20):
        """Page the compact index without opening every work/source record."""
        need(type(offset) is int and offset >= 0, "nonnegative work offset required")
        need(type(limit) is int and 1 <= limit <= 1000, "work page limit is 1..1000")
        meter, cache, result, position = Meter(self.budgets), {}, [], 0
        total = self.relations.manifest["report"]["declared_work_count"]
        for number, descriptor in enumerate(self.relations.manifest["work_index"]):
            stop = position + descriptor["rows"]
            if stop > offset and len(result) < limit:
                rows = [strict_loads(raw.decode()) for raw in
                        self.relations._chunk("work_index", number, meter, cache)]
                ids = [row["id"] for row in rows]
                need(ids == sorted(set(ids)) and ids[0] == descriptor["first_id"]
                     and ids[-1] == descriptor["last_id"], "work index bounds/order differ")
                start = max(0, offset - position)
                result.extend(ids[start:start + limit - len(result)])
            position = stop
            if len(result) == limit:
                break
        next_offset = offset + len(result)
        return {"schema": "scar.program-query", "schema_version": 1,
                "query": "WORK_INDEX", "work_ids": result, "total": total,
                "offset": offset, "next_offset": next_offset if next_offset < total else None,
                "qualification": "CHECKSUM_BOUND_INDEX_ONLY",
                "runtime_endpoints_validated": False,
                "whole_program_complete": False, "costs": meter.receipt()}

    def work(self, identity, *, expand_static=False, include_record=False):
        """Follow work → native/source context → original static body.

        Collector scope, runtime submission and Python direct calls are
        different relations. This query preserves that distinction.
        """
        need(type(identity) is str and re.fullmatch(r"work_relation:[0-9a-f]{64}", identity),
             "qualified work_relation ID required")
        meter = Meter(self.budgets)
        # ID discovery only. The public reader below rechecks the complete
        # relation and its original endpoints; this lookup is not an admission.
        document = self.relations._lookup("work", identity, meter, {})
        if document is None:
            return {"schema": "scar.program-query", "schema_version": 1,
                    "query": "WORK", "work_id": identity, "status": "NOT_FOUND",
                    "whole_program_complete": False, "costs": meter.receipt()}
        row = from_dict(document)
        need(type(row) is WorkRelations and row.id == identity,
             "work index changed original qualified identity")
        checked = self.relations.work(row.projection.scope, row.projection.work, meter=meter)
        need(checked["record"] == row, "work changed between discovery and validation")
        nodes, edges = {}, []

        def node(kind, reference):
            key = kind + ":" + stable_key(reference)
            value = {"kind": kind, "reference": encode(reference)}
            need(key not in nodes or nodes[key] == value, "query reference key collision")
            nodes[key] = value
            return key

        def edge(kind, source, target, origin):
            edges.append({"kind": kind, "source": source, "target": target,
                          "origin": origin})

        work = node("WORK", row.projection.work)
        activity = node("ACTIVITY", row.projection.original)
        edge("WORK_ACTIVITY_PROJECTION", work, activity,
             {"relation_id": row.projection.id, "receipt": encode(row.projection.receipt)})
        for index, host in enumerate(row.hosts):
            current = node("ACTIVITY", host.host)
            target = work if host.kind is HostRelationKind.SUBMITTED_BY_RUNTIME else activity
            edge(host.kind.value, current, target,
                 {"relation_id": host.id, "provider_edges": encode(host.evidence_path)})
            if host.native is not None:
                edge("ORIGINAL_EVIDENCE_BINDING", node("NATIVE_OCCURRENCE", host.native),
                     current, {"relation_pointer": f"#/hosts/{index}/native/binding"})
        for index, enclosing in enumerate(row.enclosing_native):
            chain = (enclosing.host,) + enclosing.parents
            for depth, (child, parent) in enumerate(zip(chain, chain[1:])):
                edge("COLLECTOR_SCOPE_PARENT", node("ACTIVITY", child), node("ACTIVITY", parent),
                     {"relation_id": enclosing.id, "depth": depth + 1,
                      "is_python_direct_call": False})
            edge("ORIGINAL_EVIDENCE_BINDING", node("NATIVE_OCCURRENCE", enclosing.native),
                 node("ACTIVITY", chain[-1]),
                 {"relation_pointer": f"#/enclosing_native/{index}/native/binding"})
        for context in row.source_contexts:
            edge(context.kind, node("NATIVE_OCCURRENCE", context.native),
                 node("INVOCATION", context.invocation),
                 {"relation_id": context.id, "association": encode(context.association),
                  "is_python_direct_call": False})
        bodies = []
        for binding in row.static_bindings:
            definition = node("SOURCE_DEFINITION", binding.definition)
            edge("CODE_SOURCE_BINDING", node("INVOCATION", binding.invocation), definition,
                 {"relation_id": binding.id, "code_source_link": encode(binding.code_source_link)})
            if binding.body is not None:
                body = node("STATIC_BODY", binding.body)
                edge("HAS_STATIC_BODY", definition, body, {"relation_id": binding.id})
                if expand_static and body not in bodies:
                    from scar.analysis.fragment_relations import static_member
                    expanded = static_member(binding.body, meter=meter)
                    nodes[body]["member"] = encode(expanded["member"])
                    nodes[body]["qualification"] = expanded["qualification"]
                    nodes[body]["runtime_occurrence_implied"] = False
                    bodies.append(body)
        result = {"schema": "scar.program-query", "schema_version": 1,
                  "query": "WORK", "work_id": identity, "status": "FOUND",
                  "scope": encode(row.projection.scope), "nodes": nodes, "edges": edges,
                  "node_keys": "QUERY_LOCAL_ONLY; original typed references own identity",
                  "gaps": encode(row.gaps), "validation": checked["validation"],
                  "whole_program_complete": False, "transformation_authorized": False,
                  "costs": meter.receipt()}
        if include_record:
            result["record"] = document
        return result


def query_program_cli(args):
    import json
    from pathlib import Path

    query = ProgramQuery(args.relations, expected_sha256=args.sha256,
                         budgets=RelationBudgets(max_input_bytes=args.max_input_bytes,
                                                 max_seconds=args.max_seconds))
    result = (query.list_work(offset=args.offset, limit=args.limit) if args.work is None
              else query.work(args.work, expand_static=args.expand_static,
                              include_record=args.record))
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.out:
        with Path(args.out).open("x", encoding="utf-8") as stream:
            stream.write(payload)
    else:
        print(payload, end="")
    return 1 if result.get("status") == "NOT_FOUND" else 0
