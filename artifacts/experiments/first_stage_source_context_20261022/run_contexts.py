"""Retain source layers and exercise contexts in one offline preparation pass.

The observer only inspects the existing PreparedSource returned to the public
archive writer. It does not alter that writer, import a target, or replay bodies.
The final result requires the archive writer's original digest checks to pass.
"""
import argparse
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch

from scar.analysis import source_layers
from scar.analysis.source_control_context import index_source_control_contexts
from scar.ir.control_flow_v2 import NodeKind
from scar.ir.record_codec import decode, encode
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = args.inventory.read_bytes()
    inventory = json.loads(gzip.decompress(raw) if args.inventory.suffix == ".gz" else raw)
    original = {file["snapshot"]["path"]: file for file in inventory["files"]}
    assert len(original) == len(inventory["files"])
    args.out.mkdir()
    counts = Counter({key: 0 for key in (
        "files", "source_calls", "semantic_operations", "source_atoms",
        "with_computational_semantics", "without_computational_semantics",
        "calls_with_structural_statement_context", "calls_without_structural_statement_context",
        "with_semantics_and_statement_context", "without_semantics_but_with_statement_context",
        "exact_operation_id_cfg_matches", "contexts_with_gap", "ordered_operand_links")})
    gaps, boundaries, phase_counts = Counter(), Counter(), Counter()
    files = []
    prepare = source_layers.prepare_source
    allowed = {NodeKind.STATEMENT, NodeKind.BRANCH_TEST, NodeKind.LOOP_TEST, NodeKind.GAP}
    records_path = args.out / "contexts.jsonl.gz"

    with records_path.open("xb") as raw_stream:
        with gzip.GzipFile(fileobj=raw_stream, mode="wb", mtime=0) as records:
            def observe(path, *, project_root):
                prepared = prepare(path, project_root=project_root)
                file = original[str(prepared.path)]
                index = index_source_control_contexts(
                    prepared.semantic, prepared.semantics, prepared.control,
                    source_path=prepared.path, source_text=prepared.text, max_work=20_000_000)
                cfg_ops = {op for node in prepared.control.nodes.values() for op in node.operations}
                local = Counter()
                for ordinal, call in enumerate(file["calls"]):
                    source = decode(SourceReference, call["source"])
                    owner = decode(OperationDefinitionID, call["execution_owner"])
                    operation = (None if call["semantic_operation"] is None else
                                 decode(OperationDefinitionID, call["semantic_operation"]))
                    computational = (None if operation is None else
                                     prepared.semantics.operations[operation])
                    local["source_calls"] += 1
                    local["with_computational_semantics" if computational else
                          "without_computational_semantics"] += 1
                    phase_counts[call["phase"]] += 1
                    if operation in cfg_ops:
                        local["exact_operation_id_cfg_matches"] += 1
                    contexts = index.query(source, owner)
                    assert contexts
                    connected = False
                    for context in contexts:
                        assert context.expression_source == source and context.execution_proven is False
                        if context.gap:
                            local["contexts_with_gap"] += 1
                            gaps[context.gap] += 1
                        boundaries.update(context.boundaries)
                        for identifier in context.control_nodes:
                            node = prepared.control.nodes[identifier]
                            assert node.kind in allowed and node.source == context.statement_source
                            assert node.scope == context.scope == owner
                            connected = True
                    local["calls_with_structural_statement_context" if connected else
                          "calls_without_structural_statement_context"] += 1
                    if connected:
                        local["with_semantics_and_statement_context" if computational else
                              "without_semantics_but_with_statement_context"] += 1
                    inputs = []
                    if computational is not None:
                        for use in computational.operands:
                            value = prepared.semantics.values[use.value]
                            inputs.append({"use": encode(use), "producer": encode(value.producer),
                                           "external": value.external})
                    record = {"source_path": str(prepared.path), "call_ordinal": ordinal,
                              "inventory_call": call["operation"], "source": call["source"],
                              "execution_owner": call["execution_owner"], "phase": call["phase"],
                              "semantic_operation": call["semantic_operation"],
                              "inputs": inputs, "contexts": [encode(item) for item in contexts],
                              "dynamic_execution_proven": False, "transformation_authorized": False}
                    records.write((json.dumps(record, sort_keys=True, ensure_ascii=False,
                                              separators=(",", ":")) + "\n").encode())
                local.update(files=1, source_atoms=len(prepared.semantic.source_atoms),
                             semantic_operations=len(prepared.semantics.operations),
                             ordered_operand_links=sum(len(op.operands) for op in prepared.semantics.operations.values()))
                counts.update(local)
                files.append({"source": str(prepared.path), "counts": dict(local),
                              "ast_nodes": index.ast_nodes, "context_work": index.work})
                print(json.dumps(files[-1]), flush=True)
                return prepared

            with patch.object(source_layers, "prepare_source", side_effect=observe):
                manifest = source_layers.reconstruct_source_layers(
                    args.inventory, args.out / "source-layers", max_files=256,
                    max_input_bytes=256_000_000, max_record_bytes=128_000_000,
                    max_total_bytes=2_000_000_000)
    complete = (manifest["complete"] and counts["files"] == len(inventory["files"])
                and counts["source_calls"] == inventory["summary"]["source_calls"]
                and counts["source_atoms"] == inventory["summary"]["coverage_atoms"])
    result = {"schema": "scar.source-control-context-real-queries", "valid": complete,
              "scope": "all original inventory source calls; structural evaluation context only",
              "input_inventory_raw_sha256": sha256(raw).hexdigest(),
              "records_raw_sha256": sha256(records_path.read_bytes()).hexdigest(),
              "counts": dict(counts), "gap_counts": dict(gaps), "boundary_counts": dict(boundaries),
              "phase_counts": dict(phase_counts), "files": files,
              "archive_complete": manifest["complete"],
              "all_original_context_digests_matched": manifest["complete"],
              "original_body_statuses": inventory["summary"]["body_statuses"],
              "whole_program_graph_established": False, "dynamic_dependencies_established": False,
              "transformation_authorized": False}
    (args.out / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"valid": complete, "counts": dict(counts)}), flush=True)
    if not complete:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
