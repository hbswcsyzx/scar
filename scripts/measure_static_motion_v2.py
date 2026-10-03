"""Measure one explicit source-motion proof query, without executing its source.

The query is supplied by the caller, not discovered by a new detector. Q is
empty unless a separately supplied, strictly decoded contract names this exact
analysis scope. A legal conditional proof never selects or applies a rewrite.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import tokenize

from scar.analysis.control_flow_v2 import build_source_control_flow
from scar.analysis.proof_ledger_v2 import (
    ProofContext, ProofFamily, ProofQ, ProofRequest, derive_proof_ledger,
)
from scar.analysis.regions_v2 import RegionInventory, RegionView
from scar.analysis.source_fragments_v2 import derive_source_fragment
from scar.analysis.source_semantics_v2 import extract_source_semantics
from scar.cli import _compressed_document
from scar.ir.control_flow_v2 import InsertionKind, NodeKind
from scar.ir.frontend_v2 import build_semantic
from scar.ir.record_codec import decode, encode, loads
from scar.ir.v2 import EvidenceGraph, IRBundle, TransformDelta, ValueGraph
from scar.ir.v2.optimization import StaticSourceMove
from scripts.measure_import_values_v2 import process_peak_rss


def source_motion_report(source, *, statement_line, after_line, q_document=None):
    source = Path(source).resolve()
    original_bytes = source.read_bytes()
    started = time.perf_counter()
    semantic = build_semantic(source).graph
    with tokenize.open(source) as stream:
        text = stream.read()
    snapshots = {str(source): text}
    semantics = extract_source_semantics(semantic, sources=snapshots)
    control = build_source_control_flow(semantic, semantics, sources=snapshots)

    def statement(line):
        matches = [node for node in control.nodes.values()
                   if node.kind is NodeKind.STATEMENT and node.source is not None
                   and node.source.path == str(source)
                   and node.source.start_line == line]
        if len(matches) != 1:
            raise ValueError("query line must identify exactly one complete source statement")
        return matches[0]

    moved, anchor = statement(statement_line), statement(after_line)
    fragment = derive_source_fragment(semantic, semantics, control, moved.id,
                                      sources=snapshots)
    insertions = [point for point in control.insertions.values()
                  if point.kind is InsertionKind.AFTER and point.anchor == anchor.id]
    if len(insertions) != 1:
        raise ValueError("target line must have one exact after-statement insertion")
    bundle = IRBundle(semantic, EvidenceGraph(), ValueGraph(), source_semantics=semantics)
    inventory = RegionInventory(bundle, view=RegionView.SEMANTIC)
    region = inventory.region(fragment.operation_ids)
    q = ProofQ(inventory.scope) if q_document is None else decode(ProofQ, q_document)
    context = ProofContext(bundle, semantics, inventory, inventory.scope, q,
                           source_texts=snapshots, source_control_flow=control)
    request = ProofRequest(ProofFamily.MOTION, region, TransformDelta(
        static_moves=(StaticSourceMove(fragment, insertions[0].id),)))
    ledger = derive_proof_ledger(context, request)
    if source.read_bytes() != original_bytes:
        raise ValueError("source bytes changed during proof analysis")
    return {
        "schema": "scar.static-motion-proof-query", "schema_version": 1,
        "status": "Inferred", "input": str(source),
        "scope": "One caller-selected static query under explicit Q; no import, target execution, rewrite selection or workload speedup.",
        "source_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "query": {"statement_line": statement_line, "after_line": after_line},
        "semantic": semantic.to_dict(), "source_semantics": semantics.to_dict(),
        "control_flow": control.to_dict(), "regions": inventory.to_dict(),
        "q": encode(q), "request": encode(request), "ledger": ledger.to_dict(),
        "summary": {"obligations": {item.name: item.status.value for item in ledger.obligations},
                    "outcome": ledger.outcome.value, "q_assumptions": len(q.assumptions)},
        "decision": {"legality_status": ledger.outcome.value,
                     "selection_status": "NOT_SELECTED", "cost_status": "PENDING", "applied": False},
        "measurement": {"analysis_seconds": time.perf_counter() - started},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--statement-line", type=int, required=True)
    parser.add_argument("--after-line", type=int, required=True)
    parser.add_argument("--q", type=Path, help="strict ProofQ JSON; never generated or accepted implicitly")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                       cwd=Path(__file__).resolve().parents[1], text=True).strip()
    q_bytes = args.q.read_bytes() if args.q is not None else None
    q_document = loads(q_bytes.decode("utf-8")) if q_bytes is not None else None
    started = time.perf_counter()
    report = source_motion_report(args.source, statement_line=args.statement_line,
                                  after_line=args.after_line, q_document=q_document)
    output = _compressed_document(args.out, report)
    duration = time.perf_counter() - started
    peak, peak_source = process_peak_rss()
    metadata = {
        "schema": "scar.static-motion-proof-measurement", "schema_version": 1,
        "status": "Observed", "revision": revision, "python": sys.version,
        "executable": sys.executable, "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "scope": report["scope"], "source": report["input"],
        "source_sha256": report["source_sha256"],
        "q_input_sha256": hashlib.sha256(q_bytes).hexdigest() if q_bytes is not None else None,
        "summary": report["summary"], "decision": report["decision"],
        "analysis_seconds": report["measurement"]["analysis_seconds"],
        "seconds_including_write": duration, "peak_rss_kib": peak, "peak_rss_source": peak_source,
        "report": str(output), "report_bytes": output.stat().st_size,
        "report_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    output.with_suffix(".measurement.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    print(json.dumps(metadata, sort_keys=True))


if __name__ == "__main__":
    main()
