"""Command line interface for generic SCAR tracing and analysis."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from scar.analysis import (dead_expression_candidates, detect, graph_candidates,
                           graph_liveness, graph_loop_candidates,
                           loop_invariant_candidates, summarize_action_inventory,
                           topdown_report, constant_report)
from scar.analysis.rejection_audit import audit_path
from scar.ir import (ProgramGraph, add_correspondences, from_project, from_source,
                     link_events, summarize_correspondence)
from scar.planner import plan, plan_candidates, select_candidates
from scar.trace.reader import load
from scar.workloads.micro import optimize


def _trace(args) -> int:
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    project_root = str(Path(__file__).resolve().parents[1])
    env["SCAR_TRACE_DIR"] = str(out)
    env["SCAR_TRACE_DEBUG"] = "1"
    if args.lines:
        env["SCAR_TRACE_LINES"] = "1"
    if args.resources:
        env["SCAR_RESOURCE_SAMPLER"] = "1"
        env["SCAR_RESOURCE_INTERVAL"] = str(args.resource_interval)
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
    cmd = args.command
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        raise SystemExit("trace requires '-- command'")
    start = time.perf_counter()
    result = subprocess.run(cmd, env=env)
    (out / "run.json").write_text(json.dumps({"command": cmd, "returncode": result.returncode,
                                                "wall_s": time.perf_counter() - start}, indent=2))
    return result.returncode


def _optimize(args) -> int:
    """Run an arbitrary child command with an opt-in generic backend.

    The optimizer process is intentionally separate from ``trace``.  This
    keeps timing evidence free of Python line/profiler instrumentation while
    still using the same command boundary and environment isolation.
    """
    report = Path(args.report).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    project_root = str(Path(__file__).resolve().parents[1])
    env["SCAR_OPTIMIZE"] = "1"
    env["SCAR_OPTIMIZE_REPORT"] = str(report)
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
    cmd = args.command
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        raise SystemExit("optimize requires '-- command'")
    started = time.perf_counter()
    result = subprocess.run(cmd, env=env)
    run = report.with_name(report.stem + ".run.json")
    run.write_text(json.dumps({"command": cmd, "returncode": result.returncode,
                               "wall_s": time.perf_counter() - started,
                               "backend_report": str(report)}, indent=2))
    return result.returncode


def _analyze(args) -> int:
    graph = load(args.trace)
    opportunities = plan(graph, memory_budget_bytes=args.memory_budget_bytes)
    program_graph = ProgramGraph()
    static_graph = ProgramGraph()
    for source in args.link_source or []:
        source_path = Path(source).resolve()
        static_graph.merge_graph(
            from_project(source_path) if source_path.is_dir()
            else from_source(source_path))
    program_graph.merge_graph(static_graph)
    program_graph.merge_execution(graph)
    graph_validation = program_graph.assert_valid()
    correspondences = link_events(static_graph, graph)
    add_correspondences(program_graph, correspondences)
    correspondence_summary = summarize_correspondence(
        static_graph, graph, correspondences)
    graph_opportunities = plan_candidates(
        graph_candidates(program_graph) + graph_loop_candidates(program_graph),
        memory_budget_bytes=args.memory_budget_bytes)
    # Event and graph views intentionally remain separate in the report, but
    # the final selector sees both so one target cannot be transformed twice
    # merely because two evidence paths described it.  Selection is a plan
    # record; this command never mutates the traced workload.
    simplification = select_candidates(opportunities + graph_opportunities)
    all_candidates = opportunities + graph_opportunities
    action_inventory = summarize_action_inventory(
        program_graph, all_candidates, simplification)
    liveness = graph_liveness(program_graph, closed_world=args.closed_world)
    graph_path = Path(args.graph_out or Path(args.trace) / "graph.json")
    program_graph.write_json(graph_path)
    if args.operation_out:
        program_graph.write_operation_json(args.operation_out)
    report = {"status": "Observed", "events": len(graph.events),
              "policy": {"memory_budget_bytes": args.memory_budget_bytes,
                          "closed_world": args.closed_world},
              "graph_validation": graph_validation,
              "operation_graph": str(Path(args.operation_out).resolve()) if args.operation_out else None,
              "correspondence": {
                  "sources": [str(Path(p).resolve())
                              for p in args.link_source or []],
                  **correspondence_summary,
              },
              "opportunities": [x.as_dict() for x in opportunities],
              "graph_opportunities": [x.as_dict() for x in graph_opportunities],
              "simplification": simplification.as_dict(),
              "action_inventory": action_inventory,
              "liveness": [x.as_dict() for x in liveness],
              "summary": {"kinds": {}, "labels": {}}}
    topdown = None
    if args.topdown_out:
        topdown = topdown_report(program_graph, all_candidates)
        topdown_path = Path(args.topdown_out).resolve()
        topdown_path.parent.mkdir(parents=True, exist_ok=True)
        topdown_path.write_text(json.dumps(topdown, indent=2, default=str))
        report["topdown"] = topdown
    for event in graph.events:
        report["summary"]["kinds"][event.kind] = report["summary"]["kinds"].get(event.kind, 0) + 1
        for label in event.labels:
            report["summary"]["labels"][label] = report["summary"]["labels"].get(label, 0) + 1
    out = Path(args.out or Path(args.trace) / "report.json")
    out.write_text(json.dumps(report, indent=2, default=str))
    copies = defaultdict(lambda: {"count": 0, "bytes": 0})
    for event in graph.events:
        if event.kind == "cuda_memcpy" and event.metadata.get("physical") is True:
            item = copies[event.resource.get("direction", "unknown")]
            item["count"] += 1
            item["bytes"] += int(event.resource.get("bytes", 0))
    summary = {
        "evidence": "Observed", "events": len(graph.events),
        "event_kinds": report["summary"]["kinds"],
        "graph": {"nodes": len(program_graph.nodes), "edges": len(program_graph.edges),
                  "relations": dict(Counter(edge.relation for edge in program_graph.edges))},
        "graph_validation": graph_validation,
        "correspondence": report["correspondence"],
        "physical_cuda_copies": dict(copies),
        "detected_opportunities": len(all_candidates),
        "opportunity_kinds": dict(Counter(item.kind for item in opportunities)),
        "decisions": dict(Counter(item.decision for item in opportunities)),
        "detector_decisions": dict(Counter(item.decision for item in all_candidates)),
        "proof_obligations": dict(Counter(
            proof.status.value for item in opportunities
            for proof in item.proof_obligations if proof.required)),
        "graph_opportunity_kinds": dict(Counter(item.kind for item in graph_opportunities)),
        "graph_decisions": dict(Counter(item.decision for item in graph_opportunities)),
        "graph_proof_obligations": dict(Counter(
            proof.status.value for item in graph_opportunities
            for proof in item.proof_obligations if proof.required)),
        "simplification_decisions": simplification.counts(),
        "authoritative_dispositions": simplification.counts(),
        "transformations_selected": len(simplification.selected_indices),
        "action_inventory": {key: value for key, value in action_inventory.items()
                             if key != "records"},
        "liveness": dict(Counter(item.status for item in liveness)),
        "policy": report["policy"], "transformation_applied": False,
    }
    if topdown is not None:
        summary["topdown"] = {
            "path": str(Path(args.topdown_out).resolve()),
            "counts": topdown["counts"],
        }
    # Keep the default trace-local location stable even when a report is
    # redirected elsewhere.  A caller doing batch analysis can provide an
    # explicit summary path rather than silently overwriting a global
    # ``summary.json`` from another run.
    summary_path = Path(args.summary_out) if args.summary_out else Path(args.trace) / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2))
    print(json.dumps(report, indent=2, default=str))
    return 0


def _model(args) -> int:
    source_path = Path(args.source).resolve()
    graph = from_project(source_path) if source_path.is_dir() else from_source(source_path)
    graph_validation = graph.assert_valid()
    graph.write_json(args.out)
    if args.report:
        static_opportunities = (loop_invariant_candidates(graph) +
                                dead_expression_candidates(graph))
        static_selection = select_candidates(static_opportunities)
        static_inventory = summarize_action_inventory(
            graph, static_opportunities, static_selection)
        report = {
            "status": "Inferred",
            "source": str(source_path),
            "source_kind": "project" if source_path.is_dir() else "file",
            "source_files": sorted({node.source for node in graph.nodes.values()
                                     if node.source is not None}),
            "graph_validation": graph_validation,
            "opportunities": [x.as_dict() for x in static_opportunities],
            "proof_obligations": dict(Counter(
                proof.status.value for item in static_opportunities
                for proof in item.proof_obligations if proof.required)),
            "simplification": static_selection.as_dict(),
            "action_inventory": static_inventory,
        }
        Path(args.report).write_text(json.dumps(report, indent=2, default=str))
    print(f"modeled {len(graph.nodes)} nodes and {len(graph.edges)} edges -> {args.out}")
    if args.report:
        print(f"static opportunities -> {args.report}")
    return 0


def _audit_rejections(args) -> int:
    """Explain rejection causes without rerunning or mutating a workload."""
    result = audit_path(args.report)
    output = json.dumps(result, indent=2, default=str)
    if args.out:
        destination = Path(args.out).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(output + "\n")
    print(output)
    return 0


def _constants(args) -> int:
    """Collect cross-module literal provenance without importing the target."""
    result = constant_report(args.source, project_root=args.project_root)
    output = json.dumps(result, indent=2, default=str)
    if args.out:
        destination = Path(args.out).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(output + "\n")
    print(output)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="scar")
    sub = parser.add_subparsers(dest="subcommand", required=True)
    trace = sub.add_parser("trace", help="trace an arbitrary child command")
    trace.add_argument("--out", default="artifacts/traces/run")
    trace.add_argument("--lines", action="store_true",
                       help="record user python_line and bytecode loop back-edge events")
    trace.add_argument("--resources", action="store_true",
                       help="sample traced-process CPU and nvidia-smi GPU resources")
    trace.add_argument("--resource-interval", type=float, default=0.1,
                       help="resource sampling interval in seconds (with --resources)")
    trace.add_argument("command", nargs=argparse.REMAINDER)
    trace.set_defaults(func=_trace)
    optimize_cmd = sub.add_parser("optimize", help="run a command with generic opt-in backends")
    optimize_cmd.add_argument("--report", default="artifacts/experiments/optimizer.json",
                              help="write backend counters to this JSON file")
    optimize_cmd.add_argument("command", nargs=argparse.REMAINDER)
    optimize_cmd.set_defaults(func=_optimize)
    analyze = sub.add_parser("analyze", help="detect generic avoidable work")
    analyze.add_argument("trace")
    analyze.add_argument("--out")
    analyze.add_argument("--graph-out")
    analyze.add_argument("--operation-out",
                         help="write the recursive operation/data graph projection")
    analyze.add_argument("--summary-out",
                         help="write the machine-readable summary to this path")
    analyze.add_argument("--topdown-out",
                         help="write a top-down dynamic region/placement report")
    analyze.add_argument("--memory-budget-bytes", type=int,
                         help="reject transformations exceeding this memory budget")
    analyze.add_argument("--closed-world", action="store_true",
                         help="declare that all consumers and escapes in this trace are captured")
    analyze.add_argument("--link-source", action="append", default=[],
                        help="add a static Python file or project graph and link observed events by path/line/function span")
    analyze.set_defaults(func=_analyze)
    model = sub.add_parser("model", help="build a source file or project graph")
    model.add_argument("source", help="a Python file or project directory")
    model.add_argument("--out", required=True)
    model.add_argument("--report", help="write conservative static candidate report")
    model.set_defaults(func=_model)
    audit = sub.add_parser("audit-rejections",
                           help="explain proof and evidence blockers in an analysis report")
    audit.add_argument("report", help="JSON report produced by scar analyze")
    audit.add_argument("--out", help="optional path for the audit JSON")
    audit.set_defaults(func=_audit_rejections)
    constants = sub.add_parser("constants",
                               help="find literal values reached through local imports")
    constants.add_argument("source", help="Python source file to inspect")
    constants.add_argument("--project-root",
                          help="root containing the source and local packages")
    constants.add_argument("--out", help="optional path for the constant provenance JSON")
    constants.set_defaults(func=_constants)
    micro = sub.add_parser("optimize-micro", help="run generic exact reuse experiment")
    micro.add_argument("--loops", type=int, default=30)
    micro.add_argument("--repetitions", type=int, default=5)
    micro.add_argument("--warmup", type=int, default=1)
    micro.add_argument("--work-factor", type=int, default=1)
    micro.set_defaults(func=lambda a: (print(json.dumps(optimize(a.loops, a.repetitions, a.warmup, a.work_factor), indent=2)) or 0))
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
