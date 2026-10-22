"""Independent structural audit; stdlib only, no target imports or execution.

PASS establishes the recorded source/operand/CFG/AST-path facts only. It does
not establish dynamic dependencies, expression execution, or a whole program.
"""
import argparse
import ast
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path
import tokenize


def canonical(value, *, ascii=False):
    return json.dumps(value, sort_keys=True, ensure_ascii=ascii,
                      separators=(",", ":"), allow_nan=False).encode()


def digest(value, *, ascii=False):
    return sha256(canonical(value, ascii=ascii)).hexdigest()


def wire(value):
    if value is None:
        return None
    assert set(value) == {"kind", "value", "wire"}
    assert value["wire"] == value["kind"] + ":" + value["value"]
    return value["wire"]


def mapping(items, key="id"):
    result = {wire(item[key]): item for item in items}
    assert len(result) == len(items)
    return result


def span(kind, value):
    return (kind, value["start_line"], value["end_line"],
            value["start_column"], value["end_column"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--result-dir", required=True, type=Path)
    args = parser.parse_args()
    output = args.result_dir / "audit.json"
    assert not output.exists(), "refusing to overwrite audit.json"
    raw = args.inventory.read_bytes()
    inventory = json.loads(gzip.decompress(raw) if args.inventory.suffix == ".gz" else raw)
    result = json.loads((args.result_dir / "result.json").read_text())
    archive = args.result_dir / "source-layers"
    index_raw = (archive / "index.json").read_bytes()
    index = json.loads(index_raw)
    assert canonical(index) == index_raw and index["complete"] is True
    assert index["input"]["raw_sha256"] == sha256(raw).hexdigest() == result["input_inventory_raw_sha256"]
    assert len(inventory["files"]) == len(index["files"]) == index["files_total"] == index["files_stored"]
    assert index["files_gapped"] == 0
    records = args.result_dir / "contexts.jsonl.gz"
    assert sha256(records.read_bytes()).hexdigest() == result["records_raw_sha256"]
    counts, gaps, boundaries, phases = Counter(), Counter(), Counter(), Counter()
    audited_operands = audited_results = audited_edges = audited_nodes = 0
    forbidden = ("whole_program_graph_established", "dynamic_dependencies_established", "transformation_authorized")
    assert result["valid"] is True and all(result[key] is False for key in forbidden)
    assert index["whole_program_graph_established"] is index["transformation_authorized"] is False
    with gzip.open(records, "rt", encoding="utf-8") as stream:
        for original, row, reported in zip(inventory["files"], index["files"], result["files"], strict=True):
            snapshot, context = original["snapshot"], original["context"]
            path = snapshot["path"]
            assert row["source_path"] == path == reported["source"] and row["status"] == "STORED" and row["gap"] is None
            assert row["snapshot"] == snapshot and row["context"] == context
            record_path = archive / row["archive"]
            assert record_path.resolve().is_relative_to(archive.resolve()) and not record_path.is_symlink()
            compressed = record_path.read_bytes()
            payload = gzip.decompress(compressed)
            document = json.loads(payload)
            assert canonical(document) == payload and len(payload) == row["canonical_bytes"]
            assert len(compressed) == row["compressed_bytes"] and sha256(payload).hexdigest() == row["canonical_sha256"]
            assert document["source"] == {"snapshot": snapshot, "context": context}
            meta = document["metadata"]
            assert meta["source_replay"] == "REBUILT_AND_MATCHED_INVENTORY_CONTEXT_DIGESTS"
            assert all(meta[key] is False for key in ("whole_program_graph_established", "fine_state_effects_established", "transformation_authorized"))
            layers = document["payload"]
            for name, key in (("semantic", "semantic_sha256"), ("semantics", "semantics_sha256"), ("control", "control_sha256")):
                assert digest(layers[name]) == context[key]
            semantic, semantics, cfg = layers["semantic"], layers["semantics"], layers["control"]["graph"]
            assert cfg["semantic_digest"] == "sha256:" + digest(semantic, ascii=True)
            assert cfg["source_semantics_digest"] == "sha256:" + digest(semantics, ascii=True)
            atoms, definitions = mapping(semantic["source_atoms"]), mapping(semantic["definitions"])
            operations, values = mapping(semantics["operations"], "operation"), mapping(semantics["values"])
            nodes, suites = mapping(cfg["nodes"]), mapping(cfg["suites"])
            def reference(source):
                assert source["path"] == path and source["fingerprint"] == snapshot["fingerprint"]
                assert atoms[wire(source["atom_id"])]["reference"] == source
            for operation in operations.values():
                assert wire(operation["operation"]) in definitions and wire(operation["scope"]) in definitions
                reference(operation["source"])
                for use in operation["operands"]:
                    assert wire(use["value"]) in values
                    audited_operands += 1
                if operation["result"] is not None:
                    assert values[wire(operation["result"])]["producer"] == operation["operation"]
                    audited_results += 1
            for value in values.values():
                assert value["producer"] is None or wire(value["producer"]) in operations
            cfg_ops = set()
            for node in nodes.values():
                assert wire(node["suite"]) in suites and suites[wire(node["suite"])]["scope"] == node["scope"]
                assert wire(node["scope"]) in definitions
                if node["source"] is not None:
                    reference(node["source"])
                for identifier in node["operations"]:
                    assert wire(identifier) in definitions
                    cfg_ops.add(wire(identifier))
                audited_nodes += 1
            for edge in cfg["edges"]:
                assert wire(edge["source"]) in nodes and wire(edge["target"]) in nodes
                assert nodes[wire(edge["source"])]["scope"] == nodes[wire(edge["target"])]["scope"]
                assert edge["operation"] is None or wire(edge["operation"]) in definitions
                audited_edges += 1
            with tokenize.open(path) as source_stream:
                text = source_stream.read()
            assert "sha256:" + sha256(text.encode()).hexdigest() == snapshot["fingerprint"]
            tree = ast.parse(text, filename=path, type_comments=True)
            positioned = {}
            for node in ast.walk(tree):
                if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
                    key = (type(node).__name__, node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)
                    positioned.setdefault(key, []).append(node)
            def locate(source, kind=None):
                reference(source)
                kind = kind or atoms[wire(source["atom_id"])]["kind"]
                candidates = positioned.get(span(kind, source), ())
                assert len(candidates) == 1
                return candidates[0]
            local = Counter(files=1, source_atoms=len(atoms), semantic_operations=len(operations),
                            ordered_operand_links=sum(len(op["operands"]) for op in operations.values()))
            for ordinal, call in enumerate(original["calls"]):
                record = json.loads(next(stream))
                assert record["source_path"] == path and record["call_ordinal"] == ordinal
                for key in ("source", "execution_owner", "phase", "semantic_operation"):
                    assert record[key] == call[key]
                assert record["inventory_call"] == call["operation"]
                assert record["dynamic_execution_proven"] is record["transformation_authorized"] is False
                expression = locate(call["source"], "Call")
                operation = operations.get(wire(call["semantic_operation"]))
                assert call["semantic_operation"] is None or operation is not None
                expected = [] if operation is None else [{"use": use, "producer": values[wire(use["value"])]["producer"], "external": values[wire(use["value"])]["external"]} for use in operation["operands"]]
                assert record["inputs"] == expected and record["contexts"]
                connected = False
                for ctx in record["contexts"]:
                    assert ctx["expression_source"] == call["source"] and ctx["execution_proven"] is False
                    assert ctx["scope"] is None or wire(ctx["scope"]) in definitions
                    if ctx["operation"] is not None:
                        assert operations[wire(ctx["operation"])]["source"] == call["source"]
                    if ctx["statement_source"] is None:
                        assert ctx["gap"] and not ctx["field_path"] and not ctx["control_nodes"]
                    else:
                        current = locate(ctx["statement_source"])
                        assert isinstance(current, ast.stmt)
                        required_boundaries = set()
                        for step in ctx["field_path"]:
                            if isinstance(current, ast.Lambda) and step["field"] == "body":
                                # Lexical ancestors before this deferred body
                                # govern creation, not this body's execution.
                                # Keep its missing suite explicit, rather than
                                # demanding the creator's short-circuit tags.
                                required_boundaries.clear()
                                assert "LAMBDA_BODY_FRAME" in ctx["boundaries"]
                                assert "LAMBDA_BODY_HAS_NO_RELIABLE_CFG_SUITE" in (ctx["gap"] or "")
                                assert not ctx["control_nodes"]
                            if isinstance(current, ast.BoolOp):
                                required_boundaries.add("BOOLEAN_SHORT_CIRCUIT")
                            if isinstance(current, ast.IfExp):
                                required_boundaries.add("CONDITIONAL_EXPRESSION")
                            if isinstance(current, ast.Compare) and len(current.ops) > 1:
                                required_boundaries.add("CHAINED_COMPARISON_SHORT_CIRCUIT")
                            current = getattr(current, step["field"])
                            current = current[step["index"]] if step["index"] is not None else current
                            assert isinstance(current, ast.AST) and not isinstance(current, ast.stmt)
                        assert current is expression
                        assert required_boundaries <= set(ctx["boundaries"])
                    for identifier in ctx["control_nodes"]:
                        node = nodes[wire(identifier)]
                        assert node["kind"] in {"statement", "branch_test", "loop_test", "gap"}
                        assert node["source"] == ctx["statement_source"] and node["scope"] == ctx["scope"] == call["execution_owner"]
                        connected = True
                    assert ctx["control_nodes"] or ctx["gap"]
                    for gap in ctx["control_gaps"]:
                        assert gap in cfg["gaps"] and gap["source"] == ctx["statement_source"] and gap["scope"] == ctx["scope"]
                    if ctx["gap"]:
                        local["contexts_with_gap"] += 1
                        gaps[ctx["gap"]] += 1
                    boundaries.update(ctx["boundaries"])
                local["source_calls"] += 1
                local["with_computational_semantics" if operation else "without_computational_semantics"] += 1
                local["exact_operation_id_cfg_matches"] += wire(call["semantic_operation"]) in cfg_ops
                local["calls_with_structural_statement_context" if connected else "calls_without_structural_statement_context"] += 1
                if connected:
                    local["with_semantics_and_statement_context" if operation else "without_semantics_but_with_statement_context"] += 1
                phases[call["phase"]] += 1
            assert local == Counter(reported["counts"])
            counts.update(local)
            print(json.dumps({"source": path, "calls_checked": local["source_calls"], "files_checked": counts["files"]}), flush=True)
        assert stream.readline() == ""
    assert counts == Counter(result["counts"]) and gaps == Counter(result["gap_counts"])
    assert boundaries == Counter(result["boundary_counts"]) and phases == Counter(result["phase_counts"])
    assert counts["source_calls"] == inventory["summary"]["source_calls"] and counts["source_atoms"] == inventory["summary"]["coverage_atoms"]
    report = {"valid": True, "scope": "source snapshots, retained graph references and structural AST field paths only", "counts": dict(counts),
              "operand_links_checked": audited_operands, "result_producer_links_checked": audited_results,
              "cfg_nodes_checked": audited_nodes, "cfg_edges_checked": audited_edges,
              "whole_program_graph_established": False, "dynamic_dependencies_established": False, "transformation_authorized": False}
    with output.open("x") as destination:
        json.dump(report, destination, indent=2, ensure_ascii=False)
        destination.write("\n")


if __name__ == "__main__":
    main()
