"""Query inventory connectivity by typed IDs and versioned source references.

This runner reads JSON artifacts only.  It does not import an analyzed package,
execute target code, add edges, or select rules by workload names.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path


LEGACY_SIGNATURE_DETAIL = (
    "defaults, decorators, async and variadic/keyword-only interfaces need explicit binding rules"
)


def wire(value):
    return value["wire"] if isinstance(value, dict) else value


def counts(values):
    return dict(sorted(Counter(values).items()))


def source_atom(source):
    return source["path"], source["fingerprint"], wire(source["atom_id"])


def same_source(left, right):
    return left == right


def terminal_gap(body):
    gaps = body["metadata"]["gaps"] if body and body.get("metadata") else ()
    return gaps[-1] if gaps else None


def owner_status(body):
    return body["status"] if body else "NO_BODY_RECORD"


def load(path):
    raw = path.read_bytes()
    decoded = gzip.decompress(raw) if path.suffix == ".gz" else raw
    return json.loads(decoded), {"path": str(path), "compressed_sha256": hashlib.sha256(raw).hexdigest(),
                                 "bytes": len(raw)}


def inventory_index(document):
    definitions = {wire(item["id"]): item for file in document["files"] for item in file["definitions"]}
    bodies = {wire(item["definition"]): item for file in document["files"] for item in file["bodies"]}
    calls = {wire(item["operation"]): item for file in document["files"] for item in file["calls"]}
    return definitions, bodies, calls


def unique_entries(entries):
    return list({(wire(entry["body"]["definition"]), wire(entry["link"]["operation"])): entry
                 for entry in entries}.values())


def audit(before, after):
    old_definitions, old_bodies, _ = inventory_index(before)
    definitions, bodies, calls = inventory_index(after)
    bindings = after["interfaces"]["bindings"]
    core_by_id, core_by_atom = defaultdict(list), defaultdict(list)
    core_call_entries = []
    callee_use_operations_count, graph_calls_without_call_link = 0, []
    for body in bodies.values():
        if body["graph"] is None:
            continue
        operations = {wire(operation["id"]): operation for operation in body["graph"]["operations"]}
        use_sources = {(wire(link["operation"]), wire(link["use"])): link["source"]
                       for link in body["metadata"]["use_links"]}
        linked_call_operations = set()
        for link in body["metadata"]["operation_links"]:
            operation = operations[wire(link["operation"])]
            entry = {"body": body, "link": link, "operation": operation, "use_sources": use_sources}
            if link["semantic_operation"] is not None:
                core_by_id[wire(link["semantic_operation"])].append(entry)
            core_by_atom[source_atom(link["source"])].append(entry)
            if link["opcode"] == "call":
                core_call_entries.append(entry)
                linked_call_operations.add(wire(operation["id"]))
        callee_use_operations = {wire(link["operation"]) for link in body["metadata"]["use_links"]
                                 if link["role"] == "callee"}
        callee_use_operations_count += len(callee_use_operations)
        for key in callee_use_operations - linked_call_operations:
            graph_calls_without_call_link.append({"body": wire(body["definition"]), "operation": key})

    calls_by_semantic = defaultdict(list)
    for call in calls.values():
        if call["semantic_operation"] is not None:
            calls_by_semantic[wire(call["semantic_operation"])].append(call)

    def inventory_calls_for_core(entry):
        semantic = wire(entry["link"]["semantic_operation"])
        direct = [calls[semantic]] if semantic in calls else []
        return list({wire(call["operation"]): call
                     for call in (*direct, *calls_by_semantic.get(semantic, ()))}.values())

    joined, integrity = [], Counter()
    connection_issues, eligible_actuals, actuals_connected = [], 0, 0
    for binding in bindings:
        call = calls.get(wire(binding["call"]))
        target = definitions.get(wire(binding["target"]))
        if call is None:
            integrity["binding_call_missing"] += 1
            continue
        if target is None:
            integrity["binding_target_missing"] += 1
        if not same_source(binding["source"], call["source"]):
            integrity["binding_source_differs_from_call"] += 1
        if wire(binding["target"]) not in {wire(item) for item in call["candidates"]}:
            integrity["binding_target_missing_from_call_candidates"] += 1
        owner_id = wire(call["execution_owner"])
        owner = definitions.get(owner_id)
        body = bodies.get(owner_id)
        id_links = unique_entries([*core_by_id.get(wire(call["operation"]), ()),
                                   *core_by_id.get(wire(call["semantic_operation"]), ())])
        atom_links = unique_entries(core_by_atom.get(source_atom(call["source"]), ()))
        call_links = [entry for entry in id_links if entry["link"]["opcode"] == "call"]
        expected_uses = defaultdict(set)
        for entry in call_links:
            operation = entry["operation"]
            if len(operation["invoke_arguments"]) != len(binding["arguments"]) + 2:
                connection_issues.append({"kind": "CORE_CALL_ARITY_DIFFERS", "call": wire(binding["call"]),
                                          "body": wire(entry["body"]["definition"]),
                                          "operation": wire(operation["id"])})
                continue
            for argument in binding["arguments"]:
                use = wire(operation["invoke_arguments"][argument["index"] + 1])
                actual_source = entry["use_sources"].get((wire(operation["id"]), use))
                if actual_source != argument["source"]:
                    connection_issues.append({"kind": "CORE_ACTUAL_SOURCE_DIFFERS", "call": wire(binding["call"]),
                                              "argument_index": argument["index"], "use": use})
                    continue
                expected_uses[argument["index"]].add(use)
        for argument in binding["arguments"]:
            expected = expected_uses.get(argument["index"])
            if not expected:
                continue
            eligible_actuals += 1
            if wire(argument["use"]) in expected:
                actuals_connected += 1
            else:
                connection_issues.append({"kind": "MISSING_OR_MISMATCHED_CORE_USE", "call": wire(binding["call"]),
                                          "argument_index": argument["index"], "use": wire(argument["use"]),
                                          "expected_uses": sorted(expected)})
        joined.append({
            "call": wire(binding["call"]), "target": wire(binding["target"]), "source": binding["source"],
            "phase": call["phase"], "execution_owner": owner_id,
            "owner_kind": owner["kind"] if owner else "MODULE_INITIALIZER_NOT_DEFINITION",
            "owner_body_status": owner_status(body), "owner_body_reason": body["reason"] if body else None,
            "owner_terminal_gap": terminal_gap(body),
            "target_kind": target["kind"] if target else "MISSING_DEFINITION",
            "target_body_status": owner_status(bodies.get(wire(binding["target"]))),
            "binding_status": binding["status"], "actuals": len(binding["arguments"]),
            "actuals_with_use": sum(argument["use"] is not None for argument in binding["arguments"]),
            "core_operation_id_links": len(id_links), "core_operation_atom_links": len(atom_links),
            "core_call_id_links": len(call_links),
            "cross_file_import_witness": any(wire(witness["definition"]) == wire(binding["target"])
                                             and bool(witness["through_imports"])
                                             for witness in call["candidate_witnesses"]),
        })

    core_rows = []
    for entry in core_call_entries:
        matched = inventory_calls_for_core(entry)
        core_rows.append({
            "body": wire(entry["body"]["definition"]), "operation": wire(entry["link"]["operation"]),
            "semantic_operation": wire(entry["link"]["semantic_operation"]),
            "source": entry["link"]["source"], "inventory_calls": [wire(call["operation"]) for call in matched],
            "candidate_counts": [len(call["candidates"]) for call in matched],
            "source_matches": [same_source(entry["link"]["source"], call["source"]) for call in matched],
        })
    grouped_actuals, grouped_owners = Counter(), defaultdict(set)
    for row in joined:
        key = row["phase"] + "|" + row["owner_body_status"]
        grouped_actuals[key] += row["actuals"]
        grouped_owners[key].add(row["execution_owner"])

    observed = {wire(entry["definition"]) for entry in before.get("expansion", {}).get("entries", ())
                if entry["kind"] == "OBSERVED_CODE"}
    old_observed_signature = {key for key in observed if terminal_gap(old_bodies.get(key))
                              and terminal_gap(old_bodies[key])["kind"] == "UNSUPPORTED_SIGNATURE"}
    selected = {key for key in old_observed_signature
                if terminal_gap(old_bodies[key])["detail"] == LEGACY_SIGNATURE_DETAIL}
    transitions = []
    for key in sorted(selected):
        old_body, new_body = old_bodies[key], bodies.get(key)
        transitions.append({
            "definition": key, "source": old_definitions[key]["source"],
            "same_definition_source": key in definitions
                                      and old_definitions[key]["source"] == definitions[key]["source"],
            "before_status": old_body["status"], "before_terminal_gap": terminal_gap(old_body),
            "after_status": owner_status(new_body), "after_terminal_gap": terminal_gap(new_body),
        })
    still_unsupported = [row for row in transitions if row["after_status"] == "UNSUPPORTED"]
    summary = {
        "binding_plans": len(bindings), "distinct_binding_calls": len({wire(binding["call"]) for binding in bindings}),
        "actuals": sum(len(binding["arguments"]) for binding in bindings),
        "actuals_with_use": sum(argument["use"] is not None for binding in bindings for argument in binding["arguments"]),
        "core_bodies": sum(body["graph"] is not None for body in bodies.values()),
        "core_operations_with_callee_use_source": callee_use_operations_count,
        "core_call_operation_links": len(core_rows),
        "core_call_links_with_inventory_call": sum(bool(row["inventory_calls"]) for row in core_rows),
        "core_call_links_with_candidates": sum(any(row["candidate_counts"]) for row in core_rows),
        "core_call_candidate_count_distribution": counts(str(count) for row in core_rows for count in row["candidate_counts"]),
        "core_call_links_with_exact_inventory_source": sum(any(row["source_matches"]) for row in core_rows),
        "binding_calls_with_core_operation_id_join": sum(row["core_operation_id_links"] > 0 for row in joined),
        "binding_calls_with_core_operation_atom_join": sum(row["core_operation_atom_links"] > 0 for row in joined),
        "binding_phase": counts(row["phase"] for row in joined),
        "binding_owner_kind": counts(row["owner_kind"] for row in joined),
        "binding_owner_body_status": counts(row["owner_body_status"] for row in joined),
        "binding_phase_owner_status": counts(row["phase"] + "|" + row["owner_body_status"] for row in joined),
        "actuals_by_phase_owner_status": dict(sorted(grouped_actuals.items())),
        "distinct_owners_by_phase_owner_status": {key: len(value) for key, value in sorted(grouped_owners.items())},
        "binding_target_kinds": counts(row["target_kind"] for row in joined),
        "binding_status_by_target_kind": counts(row["target_kind"] + "|" + row["binding_status"] for row in joined),
        "binding_target_body_status": counts(row["target_body_status"] for row in joined),
        "cross_file_import_witnesses": sum(row["cross_file_import_witness"] for row in joined),
        "not_attempted_owner_reasons_per_binding": counts(row["owner_body_reason"] for row in joined
                                                         if row["owner_body_status"] == "NOT_ATTEMPTED"),
        "unsupported_owner_terminal_gaps_per_binding": counts(
            row["owner_terminal_gap"]["detail"] if row["owner_terminal_gap"] else row["owner_body_reason"]
            for row in joined if row["owner_body_status"] == "UNSUPPORTED"),
        "eligible_actuals_with_core_source_and_use": eligible_actuals,
        "eligible_actuals_connected": actuals_connected,
        "connection_issue_count": len(connection_issues), "join_integrity_errors": dict(sorted(integrity.items())),
        "core_operations_with_callee_use_but_no_call_source_link": len(graph_calls_without_call_link),
    }
    return {
        "summary": summary,
        "connectivity_assessment": ("CORE_BINDING_CONNECTION_DISCREPANCY" if connection_issues or integrity
                                    else "NO_EXISTING_CORE_CALL_TO_BINDING_INTERSECTION"
                                    if not summary["binding_calls_with_core_operation_id_join"]
                                    else "ELIGIBLE_CORE_ACTUALS_CONNECTED"),
        "binding_call_rows": joined, "core_call_rows": core_rows,
        "connection_issues": connection_issues,
        "core_operations_with_callee_use_but_no_call_source_link": graph_calls_without_call_link,
        "previous_signature_blockers": {
            "selection": {"old_expansion_kind": "OBSERVED_CODE", "terminal_gap_kind": "UNSUPPORTED_SIGNATURE",
                          "terminal_gap_detail": LEGACY_SIGNATURE_DETAIL},
            "observed_definitions": len(observed), "all_observed_signature_terminal_gaps": len(old_observed_signature),
            "selected": len(selected), "after_statuses": counts(row["after_status"] for row in transitions),
            "same_definition_source_references": all(row["same_definition_source"] for row in transitions),
            "still_unsupported": len(still_unsupported),
            "still_unsupported_terminal_gap_kinds": counts(row["after_terminal_gap"]["kind"] for row in still_unsupported),
            "still_unsupported_terminal_gap_details": counts(row["after_terminal_gap"]["detail"] for row in still_unsupported),
            "rows": transitions,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    before, before_input = load(args.before)
    after, after_input = load(args.after)
    result = {
        "schema": "scar.function-interface-connectivity-audit", "schema_version": 1,
        "inputs": [before_input, after_input],
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "method": "automatic joins by operation/definition IDs and versioned source atoms; no workload name rules",
        "terminal_gap_policy": "last metadata gap identifies the first fatal blocker of an unsupported body",
        "target_executed": False, "edges_added": False, "live_call_binding_established": False,
        "transformation_authorized": False,
        **audit(before, after),
    }
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "assessment": result["connectivity_assessment"],
                      "summary": result["summary"],
                      "previous_signature_blockers": {key: value for key, value
                                                     in result["previous_signature_blockers"].items() if key != "rows"}},
                     indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
