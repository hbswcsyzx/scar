"""Read-only navigation of saved static source and canonical fragment IDs.

Queries do not execute/import target code or rebuild any graph. The default
reads the manifest only; selected fragments are checked against both stored
and decoded receipts before projecting their original records.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path


def _wire(value):
    if value is None:
        return None
    if type(value) is str:
        return value
    if type(value) is dict:
        return value.get("wire")
    raise ValueError("expected an original wire identity")


def _page(rows, limit):
    return {"total": len(rows), "returned": min(limit, len(rows)),
            "truncated": len(rows) > limit, "items": rows[:limit]}


class _Fragments:
    def __init__(self, root):
        self.root = root
        self.receipts = []

    def read(self, descriptor):
        relative = Path(descriptor["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("fragment path escapes static model")
        path = self.root / relative
        if path.resolve() != path or path.is_symlink() or not path.is_file():
            raise ValueError("fragment is absent or traverses a symlink")
        stored_size, decoded_size = descriptor["bytes"], descriptor["decoded_bytes"]
        if any(type(n) is not int or n < 0 for n in (stored_size, decoded_size)):
            raise ValueError("fragment byte receipts must be nonnegative integers")
        with path.open("rb") as source:
            payload = source.read(stored_size + 1)
        if len(payload) != stored_size or hashlib.sha256(payload).hexdigest() != descriptor["sha256"]:
            raise ValueError("stored fragment receipt differs: " + str(relative))
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as source:
            decoded = source.read(decoded_size + 1)
        if (len(decoded) != decoded_size or
                hashlib.sha256(decoded).hexdigest() != descriptor["decoded_sha256"]):
            raise ValueError("decoded fragment receipt differs: " + str(relative))
        document = json.loads(decoded)
        if type(document) is not dict:
            raise ValueError("fragment root must be a JSON object")
        self.receipts.append(dict(descriptor))
        return document


def _file_matches(path, selector):
    if selector is None:
        return True
    selected = Path(selector)
    if selected.is_absolute():
        return path == str(selected)
    suffix = selected.as_posix()
    return path == suffix or path.endswith("/" + suffix)


def _entry_matches(entry, name, kind):
    if kind is not None and entry["kind"].casefold() != kind.casefold():
        return False
    if name is None:
        return True
    identities = [entry["entry_key"], *(_wire(item) for item in entry.get("semantic_definition_ids") or ())]
    return name in identities or any(name in entry.get(field, "") for field in ("name", "qualname"))


def _entry_view(entry, unit, symbols, limit):
    keys = entry.get("symbol_table_candidates", [])
    candidates = []
    for key in keys:
        if key not in symbols:
            raise ValueError("lexical symbol candidate is not in its original catalog")
        table = symbols[key]
        candidates.append({**{name: table.get(name) for name in (
            "table_path", "parent", "kind", "name", "lineno", "free_names")},
            "symbols": _page(table.get("symbols", []), limit)})
    bodies = [body for body in unit.get("bodies", ()) if body.get("entry_key") == entry["entry_key"]]
    if len(bodies) > 1:
        raise ValueError("duplicate body status for one original entry")
    fields = ("entry_key", "kind", "name", "qualname", "phase", "definition_phase", "span",
              "lexical_parent", "source_ref", "semantic_definition_ids", "semantic_source_candidates",
              "catalog_status", "support_status", "language_version_dependent", "closure_names", "closure_status",
              "subject_entry_key", "lowering_route")
    body = bodies[0] if bodies else None
    return {**{name: entry.get(name) for name in fields}, "file": unit["path"],
            "namespace_root": unit["namespace_root"], "symbol_table_candidates": candidates,
            "body": None if body is None else {name: body[name] for name in (
                "status", "reason", "artifact", "gaps", "construction_operations", "issue") if name in body}}


def _catalog(unit, fragments):
    descriptor = unit.get("artifacts", {}).get("lexical")
    if descriptor is None:
        return None
    catalog = fragments.read(descriptor)
    if (catalog.get("schema") != "scar.static-lexical-catalog" or catalog.get("schema_version") != 1
            or catalog.get("path") != unit["path"] or catalog.get("namespace_root") != unit["namespace_root"]
            or catalog.get("fingerprint") != "sha256:" + unit["decoded_sha256"]):
        raise ValueError("lexical catalog belongs to another source unit")
    if len({row["entry_key"] for row in catalog["entries"]}) != len(catalog["entries"]):
        raise ValueError("duplicate lexical entry identity")
    return catalog


def _canonical_dependencies(unit, entries, fragments, limit):
    """Project selected canonical bodies, retaining original typed IDs/ports."""
    from scar.ir.program.codec import loads
    selected = {entry["entry_key"]: entry for entry in entries}
    rows = []
    for body in unit.get("bodies", ()):
        if body["entry_key"] not in selected:
            continue
        row = {key: body.get(key) for key in
               ("entry_key", "status", "reason", "plan", "cache_key", "construction_operations")}
        if "artifact" not in body:
            rows.append(row)
            continue
        document = fragments.read(body["artifact"])
        if document.get("schema") != "scar.static-body" or document.get("schema_version") != 1:
            raise ValueError("unsupported canonical body container")
        if document.get("entry_key") != body["entry_key"] or document.get("cache_key") != body.get("cache_key"):
            raise ValueError("body belongs to a different lexical entry")
        if document.get("inputs") != {name: unit["artifacts"].get(name) for name in
                                       ("source", "semantic", "semantics", "control")}:
            raise ValueError("body shared source fragments differ from the selected unit")
        graph_document = document.get("graph")
        if graph_document is None:
            row["canonical_graph"] = None
            row["issue"] = document.get("issue")
            rows.append(row)
            continue
        metadata = document["metadata"]
        if (metadata["source"]["path"] != unit["path"] or
                metadata["source"]["fingerprint"] != "sha256:" + unit["decoded_sha256"]):
            raise ValueError("canonical body source differs from selected source unit")
        # Ordinary canonical structure, rather than a purity or execution test.
        graph = loads(json.dumps(graph_document, allow_nan=False))
        interface = document.get("interface")
        if (interface is None or interface.get("definition") not in
                (selected[body["entry_key"]].get("semantic_definition_ids") or ())
                or interface.get("region") != graph_document["root"]):
            raise ValueError("canonical body interface differs from the selected definition/root")
        row.update(canonical_root=graph_document["root"],
                   canonical_schema=graph_document["schema_version"],
                   regions=_page(graph_document["regions"], limit),
                   operations=_page(graph_document["operations"], limit),
                   operation_order="storage tuple; execution order follows each Region's CFG blocks",
                   values=_page(graph_document["values"], limit),
                   state_locations=_page(graph_document["locations"], limit),
                   interface=document.get("interface"),
                   targets=_page(metadata.get("call_targets", []), limit),
                   operation_sources=_page(metadata.get("operation_links", []), limit),
                   value_sources=_page(metadata.get("value_links", []), limit),
                   use_sources=_page(metadata.get("use_links", []), limit),
                   source_gaps=_page(metadata.get("gaps", []), limit),
                   language_capabilities=(document.get("language") or {}).get("capabilities", []),
                   core_structure_checked=True, source_snapshot_match=True,
                   source_mapping_revalidated=False, source_language_revalidated=False,
                   independent_compiler_replayed=False,
                   counts={"regions": len(graph.regions), "operations": len(graph.operations),
                           "values": len(graph.values), "state_locations": len(graph.locations)},
                   projection_closed=False)
        rows.append(row)
    return {"bodies": rows, "qualification": "Ordinary canonical structure checked; original ports, source links and state versions projected, without purity or execution claims."}


def _rule_plans(unit, entries, fragments, limit):
    descriptor = unit.get("artifacts", {}).get("rules")
    if descriptor is None:
        return {"status": "RULE_LEDGER_NOT_BUILT"}
    document = fragments.read(descriptor)
    source = document.get("source", {})
    if (document.get("schema") != "scar.static-rule-ledger" or document.get("schema_version") != 1
            or source.get("path") != unit["path"] or source.get("namespace_root") != unit["namespace_root"]
            or source.get("fingerprint") != "sha256:" + unit["decoded_sha256"]
            or source.get("artifact") != unit["artifacts"]["source"]):
        raise ValueError("rule ledger belongs to another source unit")
    selected = {entry["entry_key"] for entry in entries}
    plans = []
    for plan in document["plans"]:
        if plan["entry_key"] in selected:
            plans.append({**{key: plan.get(key) for key in
                              ("entry_key", "kind", "status", "selected_profile", "capabilities")},
                          "rules": _page(plan.get("rules", []), limit),
                          "prerequisites": _page(plan.get("prerequisites", []), limit),
                          "unsupported_shapes": _page(plan.get("unsupported_shapes", []), limit)})
    if {plan["entry_key"] for plan in plans} != selected:
        raise ValueError("rule ledger omits a selected source entry")
    return {"status": "ORIGINAL_STATIC_RULE_PLANS", "plans": plans,
            "language_semantics_complete": document["language_semantics_complete"]}


def _dependencies(unit, entries, fragments, limit):
    artifacts = unit.get("artifacts", {})
    if "semantic" not in artifacts:
        return {"status": "SEMANTIC_FRAGMENT_UNAVAILABLE", "source_unit_status": unit["status"],
                "language_rules": _rule_plans(unit, entries, fragments, limit)}
    semantic = fragments.read(artifacts["semantic"])
    if semantic.get("schema") != "scar.ir.v2.semantic":
        raise ValueError("unsupported semantic fragment")
    modules = [row for row in semantic["modules"] if row.get("path") == unit["path"]]
    if not modules or any(row.get("fingerprint") != "sha256:" + unit["decoded_sha256"] for row in modules):
        raise ValueError("semantic fragment belongs to another source snapshot")
    roots = {_wire(identity) for entry in entries for identity in entry.get("semantic_definition_ids") or ()}
    atoms = {_wire(entry["source_ref"]["atom_id"]) for entry in entries if entry.get("source_ref")}
    definitions = {_wire(row["id"]): row for row in semantic["definitions"]}
    if not roots:
        roots = {identity for identity, row in definitions.items()
                 if atoms.intersection(_wire(item) for item in row.get("source_atoms", ()))}
    if not roots <= definitions.keys():
        raise ValueError("selected lexical definition is absent from semantic fragment")
    source_ids = {_wire(row["id"]) for row in semantic["source_atoms"]}
    if not atoms <= source_ids:
        raise ValueError("selected source atom is absent from semantic fragment")
    operations = set(roots)
    computational, values, bindings, uses, semantic_gaps = [], [], [], [], []
    if "semantics" in artifacts:
        document = fragments.read(artifacts["semantics"])
        from scar.ir.semantics_v2 import SourceSemanticsGraph
        if document.get("schema") != SourceSemanticsGraph.SCHEMA:
            raise ValueError("unsupported source-semantics fragment")
        snapshots = [row for row in document["sources"] if row["path"] == unit["path"]]
        if not snapshots or any(row["fingerprint"] != "sha256:" + unit["decoded_sha256"] for row in snapshots):
            raise ValueError("source semantics belongs to another source snapshot")
        for row in document["operations"]:
            if _wire(row["scope"]) in roots or _wire(row["operation"]) in roots:
                # Preserve the original operand array order; it is not a set.
                computational.append({key: row.get(key) for key in (
                    "operation", "scope", "block", "position", "opcode", "operands", "result",
                    "source", "binding_use", "attribute", "dispatch", "callee", "import_spec")})
                operations.add(_wire(row["operation"]))
        value_ids = {_wire(value) for row in computational for value in [row["result"]] if value is not None}
        value_ids.update(_wire(use["value"]) for row in computational for use in row["operands"])
        values = [row for row in document["values"] if _wire(row["id"]) in value_ids]
        bindings = [row for row in document["bindings"] if _wire(row["scope"]) in roots
                    or _wire(row["definition"]) in operations]
        uses = [row for row in document["uses"] if _wire(row["scope"]) in roots
                or _wire(row["operation"]) in operations]
        semantic_gaps = document.get("gaps", [])
    slot_ids = {_wire(slot) for identity in operations if identity in definitions
                for role in ("input_slots", "output_slots", "state_slots") for slot in definitions[identity][role]}
    slots = [row for row in semantic["slots"] if _wire(row.get("owner")) in operations
             or _wire(row["slot_id"]) in slot_ids]
    slot_ids.update(_wire(row["slot_id"]) for row in slots)
    endpoints = operations | slot_ids | atoms
    edges = [row for row in semantic["edges"]
             if _wire(row["source"].get("id")) in endpoints or _wire(row["target"].get("id")) in endpoints]
    suites, nodes, control_edges = [], [], []
    control_status = "CONTROL_FRAGMENT_UNAVAILABLE"
    if "control" in artifacts:
        document = fragments.read(artifacts["control"])
        from scar.ir.control_flow_v2 import SourceControlFlowGraph
        if document.get("schema") != SourceControlFlowGraph.SCHEMA:
            raise ValueError("unsupported control-flow fragment")
        graph = document["graph"]
        snapshot = graph["sources"].get(unit["path"])
        if snapshot is None or snapshot["fingerprint"] != "sha256:" + unit["decoded_sha256"]:
            raise ValueError("control flow belongs to another source snapshot")
        suites = [row for row in graph["suites"] if _wire(row["scope"]) in roots
                  or _wire(row.get("owner")) in operations]
        suite_ids = {_wire(row["id"]) for row in suites}
        nodes = [row for row in graph["nodes"] if _wire(row["suite"]) in suite_ids
                 or any(_wire(identity) in operations for identity in row["operations"])]
        node_ids = {_wire(row["id"]) for row in nodes}
        control_edges = [row for row in graph["edges"] if _wire(row["source"]) in node_ids
                         or _wire(row["target"]) in node_ids]
        control_status = "ORIGINAL_CFG_RELATIONS"
    return {"status": "ORIGINAL_STATIC_RELATIONS", "entry_keys": [row["entry_key"] for row in entries],
            "selection": "returned entries only; source-atom fallback may include multiple definition phases",
            "definition_ids": sorted(roots), "source_atom_ids": sorted(atoms),
            "definitions": _page([row for key, row in definitions.items() if key in operations], limit),
            "slots": _page(slots, limit), "semantic_edges": _page(edges, limit),
            "ordered_operations": _page(computational, limit), "values": _page(values, limit),
            "bindings": _page(bindings, limit), "binding_uses": _page(uses, limit),
            "file_semantic_gaps": _page(semantic_gaps, limit), "control_status": control_status,
            "suites": _page(suites, limit), "cfg_nodes": _page(nodes, limit), "cfg_edges": _page(control_edges, limit),
            "canonical": _canonical_dependencies(unit, entries, fragments, limit),
            "language_rules": _rule_plans(unit, entries, fragments, limit),
            "closed_graph_projection": False,
            "qualification": "Original fragment records/IDs only; limits can omit endpoint descriptions. No producer/state reconstruction or execution claim."}


def query_static_program(directory, *, file=None, name=None, kind=None, limit=20, include_dependencies=False):
    """Query saved entries; name matches name/qualname text or an exact original ID.

    File selection accepts an absolute original filename or a component suffix.
    No filters means a manifest summary, without loading lexical fragments.
    Dependencies require exactly one selected file and describe returned entries.
    """
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")
    if type(include_dependencies) is not bool:
        raise TypeError("include_dependencies must be an explicit bool")
    for label, value in (("file", file), ("name", name), ("kind", kind)):
        if value is not None and (type(value) is not str or not value):
            raise ValueError(label + " must be nonempty text")
    from scar.analysis.static_program import read_static_program
    root = Path(directory).absolute()
    manifest = read_static_program(root, verify=False)
    manifest_bytes = (root / "manifest.json").read_bytes()
    if json.loads(manifest_bytes) != manifest:
        raise ValueError("static manifest changed during query")
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    units = [unit for unit in manifest["units"] if _file_matches(unit["path"], file)]
    if include_dependencies and len(units) != 1:
        raise ValueError("--dependencies requires exactly one selected source file")
    fragments = _Fragments(root)
    result = {"schema": "scar.static-program-query", "schema_version": 1,
              "model": {"directory": str(root), "manifest_sha256": manifest_hash, "phase": manifest["phase"]},
              "summary": manifest["summary"], "completion": manifest["completion"],
              "selection": {"file": file, "name": name, "kind": kind, "limit": limit},
              "files_matched": len(units), "files": _page([
                  {key: unit.get(key) for key in ("key", "path", "namespace_root", "module_names", "status", "counts", "issues")}
                  for unit in units], limit),
              "entries": [], "target_executed": False, "runtime_evidence_required": False}
    summary_only = all(value is None for value in (file, name, kind)) and not include_dependencies
    selected = []
    count = 0
    unavailable = []
    if not summary_only:
        for unit in units:
            catalog = _catalog(unit, fragments)
            if catalog is None:
                unavailable.append({"file": unit["path"], "status": unit["status"], "reason": "LEXICAL_FRAGMENT_UNAVAILABLE"})
                continue
            symbols = {row["table_path"]: row for row in catalog.get("symbol_tables", [])}
            for entry in catalog["entries"]:
                if _entry_matches(entry, name, kind):
                    count += 1
                    if len(result["entries"]) < limit:
                        result["entries"].append(_entry_view(entry, unit, symbols, limit))
                        selected.append(entry)
        result.update(candidate_count=count, returned_entries=len(result["entries"]), entries_truncated=count>limit,
                      unavailable_lexical=_page(unavailable, limit), mode="ENTRIES")
    else:
        result.update(candidate_count=manifest["summary"].get("lexical_entries"), returned_entries=0,
                      entries_truncated=False, mode="MANIFEST_SUMMARY")
    if include_dependencies:
        result["dependencies"] = _dependencies(units[0], selected, fragments, limit)
    if (root / "manifest.json").read_bytes() != manifest_bytes:
        raise ValueError("static manifest changed during query")
    result["verified_fragments"] = fragments.receipts
    result["qualification"] = "Manifest namespace and selected stored/decoded SHA receipts checked; original static facts projected, not a new graph or semantic replay."
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, prog="scar static-query")
    parser.add_argument("--model", default="artifacts/current/static")
    parser.add_argument("--file", help="absolute original source path or component suffix")
    parser.add_argument("--name", help="name/qualname substring or exact entry key/semantic definition ID")
    parser.add_argument("--kind", help="case-insensitive exact lexical entry kind")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--dependencies", action="store_true")
    args = parser.parse_args(argv)
    result = query_static_program(args.model, file=args.file, name=args.name, kind=args.kind,
                                  limit=args.limit, include_dependencies=args.dependencies)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
