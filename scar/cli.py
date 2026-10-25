"""Command line interface for generic SCAR tracing and analysis."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from itertools import chain
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


def _trace(args) -> int:
    out = Path(args.out).resolve()
    os_capture_root = getattr(args, 'os_capture_root', None)
    if os_capture_root is not None:
        os_capture_root = Path(os_capture_root).absolute()
        if os_capture_root.exists() or out != os_capture_root / 'trace':
            raise SystemExit('--os-capture-root requires a fresh root and explicit --out ROOT/trace')
        if not (getattr(args, 'call_operands', False) and getattr(args, 'execution_evidence', False)):
            raise SystemExit('--os-capture-root requires --call-operands --execution-evidence')
    out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    project_root = str(Path(__file__).resolve().parents[1])
    env["SCAR_TRACE_DIR"] = str(out)
    env["SCAR_TRACE_DEBUG"] = "1"
    env.pop('SCAR_TRACE_CALL_EDGES',None)
    env.pop('SCAR_CALL_TRACE_OWNER_PID',None)
    env.pop('SCAR_CALL_OPERANDS',None)
    env.pop('SCAR_OPERAND_CAPTURE',None)
    env.pop('SCAR_EXECUTION_EVIDENCE',None)
    env.pop('SCAR_TENSOR_PHYSICAL',None)
    for key in ('SCAR_OS_CAPTURE_NONCE','SCAR_OS_CAPTURE_INTENT','SCAR_OS_CAPTURE_INTENT_SHA256'):
        env.pop(key,None)
    operands = getattr(args, "call_operands", False)
    execution_evidence = getattr(args, "execution_evidence", False)
    physical = getattr(args, "tensor_physical", False)
    if physical and not execution_evidence:
        raise SystemExit("--tensor-physical requires --execution-evidence")
    if execution_evidence and not (getattr(args, "calls_only", False) or operands):
        raise SystemExit("--execution-evidence requires --calls-only or --call-operands")
    if getattr(args,"calls_only",False) or operands:
        if args.lines:
            raise SystemExit("calls-only does not collect line tracing; use a separate trace")
        if (any(out.glob('call-events.*.jsonl*')) or any(out.glob('call-codes.*.jsonl*'))
                or any(out.glob('call-operands.*.jsonl*')) or any(out.glob('call-operand-meta.*.json*'))
                or any(out.glob('function-environments.*.jsonl*'))
                or any(out.glob('function-environment-meta.*.json*'))
                or (execution_evidence and any(out.glob('execution-evidence.*.json')))):
            raise SystemExit("calls-only requires a fresh output directory")
        env['SCAR_TRACE_CALL_EDGES'] = '1'
        env['SCAR_CALL_PROJECT_ROOT'] = str(Path(args.project_root or Path.cwd()).resolve())
        env['SCAR_CALL_MAX_EVENTS'] = str(args.max_call_events)
        env['SCAR_CALL_MAX_BYTES'] = str(args.max_call_bytes)
        if args.max_call_events < 1 or args.max_call_bytes < 1:
            raise SystemExit("call budgets must be positive")
        if operands:
            if args.max_operand_events < 1 or args.max_operand_bytes < 1:
                raise SystemExit("operand budgets must be positive")
            capture = getattr(args, 'operand_capture', 'windows')
            if capture not in ('windows', 'instructions'):
                raise SystemExit("operand capture must be windows or instructions")
            env['SCAR_CALL_OPERANDS'] = '1'
            env['SCAR_OPERAND_CAPTURE'] = capture
            env['SCAR_OPERAND_MAX_EVENTS'] = str(args.max_operand_events)
            env['SCAR_OPERAND_MAX_BYTES'] = str(args.max_operand_bytes)
        if execution_evidence:
            env['SCAR_EXECUTION_EVIDENCE'] = '1'
            if physical:
                env['SCAR_TENSOR_PHYSICAL'] = '1'
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
    if os_capture_root is None:
        result = subprocess.run(cmd, env=env)
    else:
        from scar.trace.os_capture_launch import OSCaptureBudgets, launch_os_capture
        os_budgets = OSCaptureBudgets(max_os_bytes=args.max_os_bytes,
            max_raw_bytes=args.max_capture_bytes, max_stored_bytes=args.max_archive_bytes,
            max_os_lines=args.max_os_lines, max_seconds=args.os_timeout)
        result, _ = launch_os_capture(cmd, env=env, capture_root=os_capture_root,
            strace_executable=args.strace_executable, budgets=os_budgets)
    (out / "run.json").write_text(json.dumps({"command": cmd, "returncode": result.returncode,
                                                "wall_s": time.perf_counter() - start}, indent=2))
    if os_capture_root is not None and result.returncode == 0:
        from scar.trace.os_capture_launch import archive_owned_capture, publish_bytes
        from scar.trace.capture_coordinates import bind_capture_coordinates
        archive_owned_capture(os_capture_root, budgets=os_budgets)
        coordinate_path = os_capture_root / 'capture-coordinates.json'
        coordinates = bind_capture_coordinates(os_capture_root, max_bytes=os_budgets.max_raw_bytes,
            max_lines=os_budgets.max_os_lines, profile_uri=str(coordinate_path), publish_os_profile=True)
        publish_bytes(coordinate_path, coordinates.payload)
        print(json.dumps({'os_capture': str(os_capture_root), 'coordinates': str(coordinate_path),
            'os_capture_provider': coordinates.report.get('os_capture_provider'),
            'whole_model_established': False}), flush=True)
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


def _query_body_execution(args) -> int:
    from scar.ir.execution.cli import query_body_execution
    return query_body_execution(args)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="scar")
    sub = parser.add_subparsers(dest="subcommand", required=True)
    model_run = sub.add_parser("model-run", help="build a partial model offline from an existing capture")
    model_run.add_argument("--from-capture", required=True, dest="capture")
    model_run.add_argument("--out", required=True)
    model_run.add_argument("--plan-only", action="store_true", help="read bounded metadata only; no raw streams or compilation")
    model_run.add_argument("--resume", action="store_true", help="preserve old attempts and create a fresh attempt")
    for name, default in (("metadata-bytes", 2_000_000), ("raw-bytes", 64_000_000),
                          ("record-bytes", 64_000_000), ("output-bytes", 128_000_000),
                          ("calls", 256), ("codes", 128), ("source-files", 4),
                          ("source-bytes", 256_000), ("bodies", 4), ("operations", 4000),
                          ("seconds", 180), ("compile-keys", 4), ("witness-bytes", 16_000_000)):
        model_run.add_argument("--max-" + name, type=int, default=default)
    model_run.set_defaults(func=_model_run)
    trace = sub.add_parser("trace", help="trace an arbitrary child command")
    trace.add_argument("--out", default="artifacts/traces/run")
    trace.add_argument("--lines", action="store_true",
                       help="record user python_line and bytecode loop back-edge events")
    trace.add_argument("--resources", action="store_true",
                       help="sample traced-process CPU and nvidia-smi GPU resources")
    trace.add_argument("--resource-interval", type=float, default=0.1,
                       help="resource sampling interval in seconds (with --resources)")
    trace.add_argument('--calls-only',action='store_true',help='record bounded Python call sites and reference identities without Torch hooks or tensor values')
    trace.add_argument('--call-operands',action='store_true',help='record bounded instruction/load/call evidence; implies calls-only (CPython 3.14)')
    trace.add_argument('--execution-evidence',action='store_true',
                       help='collect native ETO/Kineto evidence alongside the call recorder when the target imports Torch; requires calls-only or call-operands')
    trace.add_argument('--tensor-physical',action='store_true',
                       help='also export owned profiler marker Tensor metadata and allocation epochs after close; requires execution-evidence')
    trace.add_argument('--operand-capture',choices=('windows','instructions'),default='windows',
                       help='capture bounded call windows (default) or every project instruction')
    trace.add_argument('--project-root',help='source boundary for lightweight call-site recording; defaults to target cwd')
    trace.add_argument('--max-call-events',type=int,default=100000)
    trace.add_argument('--max-call-bytes',type=int,default=64000000)
    trace.add_argument('--max-operand-events',type=int,default=100000)
    trace.add_argument('--max-operand-bytes',type=int,default=32000000)
    trace.add_argument('--os-capture-root',help='opt in to owned trace=all strace, lossless retention and final coordinates; requires fresh ROOT and --out ROOT/trace')
    trace.add_argument('--strace-executable',default='strace',help='strace executable for the owned opt-in OS capture')
    trace.add_argument('--max-os-bytes',type=int,default=128000000)
    trace.add_argument('--max-os-lines',type=int,default=2000000)
    trace.add_argument('--max-capture-bytes',type=int,default=256000000)
    trace.add_argument('--max-archive-bytes',type=int,default=128000000)
    trace.add_argument('--os-timeout',type=int,default=300,help='owned OS provider wall-time budget in seconds')
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
    model_v2 = sub.add_parser("model-v2", help="build the versioned semantic graph without executing source")
    model_v2.add_argument("source")
    model_v2.add_argument("--project-root")
    model_v2.add_argument("--out", required=True)
    model_v2.add_argument("--report", help="semantic coverage and unresolved-boundary report")
    model_v2.set_defaults(func=_model_v2)
    check_program = sub.add_parser("check-program", help="validate a typed program graph JSON without executing it")
    check_program.add_argument("graph", help="scar.program-graph JSON document")
    check_program.add_argument("--out", help="optional structural validation report")
    check_program.set_defaults(func=_check_program)
    query_body = sub.add_parser("query-body-execution", help="inspect declared body drive or activation links without executing code")
    query_body.add_argument("program", help="strict scar.program-graph JSON document")
    query_body.add_argument("execution", help="strict scar.execution-model JSON document")
    body_subject = query_body.add_mutually_exclusive_group(required=True)
    body_subject.add_argument("--drive", help="canonical exec_operation_occurrence:<value> ID")
    body_subject.add_argument("--activation", help="canonical exec_region_activation:<value> ID")
    query_body.add_argument("--budget", type=int, default=4096)
    query_body.add_argument("--out", help="optional query report; must differ from both inputs")
    query_body.set_defaults(func=_query_body_execution)
    model_program = sub.add_parser("model-program", help="automatically lower a selected Python function into the typed program core")
    model_program.add_argument("source", help="Python source file, read without importing or executing it")
    model_program.add_argument("--entry", required=True, help="qualified function body, for example Class.method")
    model_program.add_argument("--max-operations", type=int, default=10000)
    model_program.add_argument("--max-report-bytes", type=int, default=256000000,
                               help="independent uncompressed output byte ceiling")
    model_program.add_argument("--body-profile", choices=("frame", "legacy", "structured", "environment"), default="frame",
                               help="conditional frame model (default), historical v1, or versioned local-binding/loop model")
    model_program.add_argument("--out", required=True, help="source-linked graph report, optionally ending in .gz")
    model_program.set_defaults(func=_model_program)
    check_source_program = sub.add_parser("check-source-program", help="strictly replay an automatic source graph against current source")
    check_source_program.add_argument("report", help="source graph report JSON or JSON.gz")
    check_source_program.add_argument("--max-operations", type=int, default=10000, help="independent verifier construction ceiling")
    check_source_program.add_argument("--max-report-bytes", type=int, default=256000000,
                                      help="independent decompressed input byte ceiling")
    check_source_program.set_defaults(func=_check_source_program)
    query_frame = sub.add_parser("query-frame-refs", help="replay a source program and follow conditional return reference paths")
    query_frame.add_argument("report", help="bound-frame source program JSON or JSON.gz")
    query_frame.add_argument("--max-operations", type=int, default=10000)
    query_frame.add_argument("--max-reference-steps", type=int, default=4096)
    query_frame.add_argument("--max-report-bytes", type=int, default=256000000)
    query_frame.set_defaults(func=_query_frame_references)
    inventory_program = sub.add_parser("inventory-program", help="discover local source dependencies and automatically inventory/lower available function bodies")
    inventory_program.add_argument("source", help="entry Python file")
    inventory_program.add_argument("--project-root", help="filesystem boundary; inferred source roots remain distinct from runtime sys.path")
    inventory_program.add_argument("--source-root", action="append", default=[], help="explicit local source root; repeat for candidate contexts")
    inventory_program.add_argument("--out", required=True, help="compact source/body report JSON, optionally .gz")
    inventory_program.add_argument("--trace", help="augment candidate source scope from an existing runtime trace directory/JSONL/gzip")
    inventory_program.add_argument("--calls", help="raw call-edge trace directory; enable v6 entry-first source demand")
    inventory_program.add_argument("--body-profile", choices=("frame", "structured", "environment"), default="frame",
                                   help="body lowering profile: frame v5/v6, structured v7, environment v8")
    inventory_program.set_defaults(func=_inventory_program)
    composition = sub.add_parser("compose-program", help="connect retained source structure and typed function bodies using their original identities")
    composition.add_argument("--inventory", required=True)
    composition.add_argument("--source-layers", required=True)
    composition.add_argument("--out", required=True, help="fresh directory for recursive composition references and coverage frontiers")
    composition.add_argument("--max-input-bytes", type=int, default=512000000)
    composition.add_argument("--max-files", type=int, default=256)
    composition.add_argument("--max-record-bytes", type=int, default=128000000)
    composition.add_argument("--max-output-bytes", type=int, default=256000000)
    composition.set_defaults(func=_compose_program)
    source_invocations = sub.add_parser("bind-source-invocations", help="bind every original Python frame entry to exact source and body references")
    source_invocations.add_argument("--composition", required=True, help="bound composition index JSON.gz")
    source_invocations.add_argument("--capture", required=True, help="original successful collector capture")
    source_invocations.add_argument("--trace", help="call trace directory; defaults to capture/trace")
    source_invocations.add_argument("--witness-mode", choices=("same_capture", "reused_code"), default="same_capture")
    source_invocations.add_argument("--max-bytes", type=int, default=2000000000)
    source_invocations.add_argument("--max-lines", type=int, default=2000000)
    source_invocations.add_argument("--max-input-bytes", type=int, default=512000000,
                                    help="independent decompressed composition/inventory input ceiling")
    source_invocations.add_argument("--out", required=True, help="fresh source/invocation binding directory")
    source_invocations.set_defaults(func=_bind_source_invocations)
    dependency_sources = sub.add_parser("admit-dependency-sources", help="recover observed dependency source graphs using independent Python environment roots")
    dependency_sources.add_argument("trace")
    dependency_sources.add_argument("--project-root", required=True)
    dependency_sources.add_argument("--out", required=True, help="fresh source-admission directory")
    from scar.analysis.dependency_sources import DependencySourceBudget
    from scar.ir.program.expansion import ContextStoreBudget
    for budget_type, prefix in ((DependencySourceBudget, "dependency"), (ContextStoreBudget, "context")):
        defaults = budget_type()
        for name in budget_type.__dataclass_fields__:
            dependency_sources.add_argument("--" + prefix + "-" + name.replace("_", "-"),
                dest=prefix + "_" + name, type=int, default=getattr(defaults, name))
    dependency_sources.set_defaults(func=_admit_dependency_sources)
    dispatch_sources = sub.add_parser("bind-dispatch-sources", help="join original provider marker contexts to retained Python source invocations")
    dispatch_sources.add_argument("--source-bindings", required=True)
    dispatch_sources.add_argument("--dispatch-bridge", required=True)
    dispatch_sources.add_argument("--composition", help="original composition index; required for partitioned source bindings")
    dispatch_sources.add_argument("--capture", required=True)
    dispatch_sources.add_argument("--out", required=True)
    dispatch_sources.add_argument("--max-bytes", type=int, default=2000000000)
    dispatch_sources.add_argument("--max-lines", type=int, default=2000000)
    dispatch_sources.add_argument("--max-input-bytes", type=int, default=1000000000)
    dispatch_sources.add_argument("--max-observations", type=int, default=400000)
    dispatch_sources.set_defaults(func=_bind_dispatch_sources)
    dispatch_query = sub.add_parser("query-dispatch-source", help="follow one provider marker's original invocation, definition and body references")
    dispatch_query.add_argument("directory")
    dispatch_query.add_argument("--marker", required=True)
    dispatch_query.set_defaults(func=_query_dispatch_source)
    check_inventory = sub.add_parser("check-inventory", help="rebuild a source inventory from current files and discovery context")
    check_inventory.add_argument("report", help="inventory report JSON or JSON.gz")
    check_inventory.set_defaults(func=_check_inventory)
    source_layers = sub.add_parser("source-layers", help="recover and retain the existing source graphs bound by an inventory")
    source_layers.add_argument("--inventory", required=True, help="existing inventory JSON or JSON.gz; not a complete-inventory replay")
    source_layers.add_argument("--out", required=True, help="fresh source-graph archive directory")
    source_layers.add_argument("--max-input-bytes", type=int, default=256000000)
    source_layers.add_argument("--max-files", type=int, default=256)
    source_layers.add_argument("--max-record-bytes", type=int, default=64000000)
    source_layers.add_argument("--max-total-bytes", type=int, default=512000000)
    source_layers.add_argument("--reuse-archive", help="reuse validated records from the same inventory in an existing source archive")
    source_layers.set_defaults(func=_source_layers)
    call_links = sub.add_parser('link-calls',help='link recorded Python call sites and references to source and optional core inventory')
    call_links.add_argument('trace')
    call_links.add_argument('--project-root',required=True)
    call_links.add_argument('--inventory',help='source inventory to strictly verify and link')
    call_links.add_argument('--out',required=True)
    call_links.set_defaults(func=_link_calls_cli)
    check_call_links = sub.add_parser('check-call-links',help='strictly replay call/source/core links against trace, source and inventory')
    check_call_links.add_argument('report')
    check_call_links.set_defaults(func=_check_call_links_cli)
    query_call_refs = sub.add_parser('query-call-refs',help='replay a call report and traverse one invocation reference path')
    query_call_refs.add_argument('report')
    query_call_refs.add_argument('--process',type=int,required=True)
    query_call_refs.add_argument('--thread',type=int,required=True)
    query_call_refs.add_argument('--invocation',type=int,required=True)
    query_call_refs.set_defaults(func=_query_call_refs_cli)
    seed_calls = sub.add_parser('seed-calls',help='resolve entered Python codes to compact source seeds without building reference routes')
    seed_calls.add_argument('trace')
    seed_calls.add_argument('--project-root',required=True)
    seed_calls.add_argument('--out',required=True)
    seed_calls.set_defaults(func=_seed_calls_cli)
    check_call_seeds = sub.add_parser('check-call-seeds',help='independently rescan compact call seeds against raw trace and current source')
    check_call_seeds.add_argument('report')
    check_call_seeds.set_defaults(func=_check_call_seeds_cli)
    operand_links = sub.add_parser('link-operands',help='automatically link original operand occurrences to core parameter and return ports')
    operand_links.add_argument('trace')
    operand_links.add_argument('--project-root',required=True)
    operand_links.add_argument('--inventory',required=True,help='automatic frame/structured/environment v5-v8 inventory to replay')
    operand_links.add_argument('--out',required=True)
    operand_links.add_argument('--environments-out',help='also bind retained function-environment identities to existing entry ports; fresh JSON/JSON.gz output')
    operand_links.set_defaults(func=_link_operands_cli)
    check_operand_links = sub.add_parser('check-operand-links',help='independently rebuild conditional operand routes from raw trace/source/inventory')
    check_operand_links.add_argument('report')
    check_operand_links.set_defaults(func=_check_operand_links_cli)
    query_operand_refs = sub.add_parser('query-operand-refs',help='follow conditional cross-call return/formal/actual references')
    query_operand_refs.add_argument('report')
    query_operand_refs.add_argument('--process',type=int,required=True)
    query_operand_refs.add_argument('--thread',type=int,required=True)
    query_operand_refs.add_argument('--invocation',type=int,required=True)
    query_operand_refs.add_argument('--max-reference-steps',type=int,default=4096)
    query_operand_refs.set_defaults(func=_query_operand_refs_cli)
    operand_commands = (operand_links, check_operand_links, query_operand_refs)
    from scar.ir.program.call_operands import CallOperandBudget
    from scar.ir.program.call_operand_routes import OperandRouteBudget
    for command in operand_commands:
        for name in CallOperandBudget.__dataclass_fields__:
            flag = '--max-operand-' + name.removeprefix('max_').replace('_','-')
            aliases = (flag, '--max-operand-bytes') if name == 'max_raw_bytes' else (flag,)
            command.add_argument(*aliases, dest='operand_' + name, type=int,
                                 default=getattr(CallOperandBudget(), name),
                                 help='independent operand reader ceiling: ' + name)
        for name in OperandRouteBudget.__dataclass_fields__:
            command.add_argument('--operand-' + name.replace('_','-'), dest='route_' + name,
                                 type=int, default=getattr(OperandRouteBudget(), name),
                                 help='independent route construction ceiling: ' + name)
    for command in (call_links,check_call_links,query_call_refs,seed_calls,check_call_seeds,inventory_program,check_inventory,*operand_commands,source_invocations,dependency_sources):
        command.add_argument('--max-call-report-bytes',type=int,default=256000000,
                             help='independent decompressed input/output report ceiling')
        command.add_argument('--max-call-trace-bytes',type=int,default=128000000)
        command.add_argument('--max-call-trace-lines',type=int,default=200000)
        command.add_argument('--max-call-line-bytes',type=int,default=2000000)
        command.add_argument('--max-call-processes',type=int,default=128)
        command.add_argument('--max-call-trace-events',type=int,default=100000)
        command.add_argument('--max-call-trace-codes',type=int,default=8192)
        command.add_argument('--max-call-references',type=int,default=1000000)
        command.add_argument('--max-call-path',type=int,default=128)
        command.add_argument('--max-call-source-files',type=int,default=256)
        command.add_argument('--max-call-source-bytes',type=int,default=16000000)
    for command in (inventory_program, check_inventory,call_links,check_call_links,query_call_refs,*operand_commands):
        command.add_argument("--max-files", type=int, default=128)
        command.add_argument("--max-bytes", type=int, default=8_000_000)
        command.add_argument("--max-directories", type=int, default=4096)
        command.add_argument("--max-lowered-bodies", type=int, default=256)
        command.add_argument("--max-operations", type=int, default=10000, help="aggregate core operation ceiling across all body reports")
        command.add_argument("--max-call-witnesses", type=int, default=4096, help="aggregate conditional call-target witness ceiling")
        command.add_argument("--max-trace-bytes", type=int, default=128_000_000, help="decompressed runtime trace byte ceiling")
        command.add_argument("--max-trace-records", type=int, default=200_000, help="runtime trace line ceiling, including blank lines")
        command.add_argument("--max-trace-line-bytes", type=int, default=2_000_000)
        command.add_argument("--max-runtime-codes", type=int, default=4096, help="runtime code/process observation group ceiling")
        command.add_argument("--max-compile-attempts", type=int, default=1024, help="offline code reproduction trial ceiling")
        command.add_argument("--max-context-bytes", type=int, default=128_000_000, help="private prepared-context compressed write ceiling")
        command.add_argument("--max-context-record-bytes", type=int, default=64_000_000, help="private prepared-context uncompressed per-record ceiling")
    normalize = sub.add_parser("normalize", help="normalize existing raw trace into IR v2 evidence")
    normalize.add_argument("trace")
    normalize.add_argument("--out", required=True)
    normalize.add_argument("--report", help="raw record conservation and ambiguity report")
    normalize.set_defaults(func=_normalize_v2)
    capture_model = sub.add_parser("import-capture", help="assemble original Python/Torch/OS capture evidence in one verified execution coordinate space")
    capture_model.add_argument("directory", help="successful SCAR collector capture directory containing trace/ and os/")
    capture_model.add_argument("--max-bytes", type=int, default=1000000000)
    capture_model.add_argument("--max-lines", type=int, default=2000000)
    capture_model.add_argument("--schema-contracts", action="store_true", help="recover ordered provider ports using the exact matching installed Torch schema parser")
    capture_model.add_argument("--bundle-partitions", action="store_true", help="store native graph records as bounded chunks instead of one nested bundle JSON")
    capture_model.add_argument("--os-interface-work", action="store_true", help="retain kernel interfaces and typed work in bounded partitions; effects and resource closure remain explicit")
    capture_model.add_argument("--out", required=True, help="fresh assembled capture directory with per-stage progress")
    capture_model.set_defaults(func=_import_capture)
    os_resources = sub.add_parser("import-os-resources", help="import retained per-TID strace files into existing resource and handle identities")
    os_resources.add_argument("directory", help="strace -ff -ttt -T files, optionally gzip")
    os_resources.add_argument("--scope", default="capture", help="namespace, additionally bound to the artifact manifest hash")
    os_resources.add_argument("--root-tid", type=int, help="explicit captured target process declaration")
    os_resources.add_argument("--capture-root", help="bind the original collector capture containing this os/ directory to verified shared Run/Process/Thread coordinates")
    os_resources.add_argument("--interface-work", action="store_true", help="publish schema2 interface and typed-work tables in bounded chunks")
    os_resources.add_argument("--max-bytes", type=int, default=512000000)
    os_resources.add_argument("--max-lines", type=int, default=2000000)
    os_resources.add_argument("--max-report-bytes", type=int, default=512000000, help="legacy single-report ceiling; interface-work uses the independent partition budgets")
    os_resources.add_argument("--out", required=True, help="fresh output directory")
    os_resources.set_defaults(func=_import_os_resources)
    native = sub.add_parser("import-native", help="import collected ETO/Kineto evidence without running or importing the target")
    native.add_argument("--execution-trace", required=True, help="ETO JSON or lossless JSON.gz")
    native.add_argument("--kineto", help="Kineto Chrome JSON or lossless JSON.gz; omit for ETO-only evidence")
    native.add_argument("--reference-markers", help="exact-argument marker sidecar (research profile only)")
    native.add_argument("--call-events", help="call recorder JSONL paired with reference markers")
    native.add_argument("--call-codes", help="call recorder code JSONL paired with reference markers")
    native.add_argument("--call-meta", help="closed call recorder receipt paired with reference markers")
    native.add_argument("--reference-profile", choices=("scar.marker-research-probe-v1",),
                        help="explicit supplied collector contract; not production capture validation")
    native.add_argument("--provider-revision", required=True, help="recorded Torch git revision; not inferred from the analysis environment")
    native.add_argument("--max-bytes", type=int, default=512000000, help="combined decompressed input byte ceiling")
    native.add_argument("--out", required=True, help="fresh output directory")
    native.set_defaults(func=_import_native)
    inspect_v2 = sub.add_parser("inspect-v2", help="join source/runtime evidence and report scoped effect requirements")
    inspect_v2.add_argument("source")
    inspect_v2.add_argument("--trace", required=True)
    inspect_v2.add_argument("--project-root")
    inspect_v2.add_argument("--runtime-sources", action="store_true",
                            help="select only entry and trace-referenced files within project root")
    inspect_v2.add_argument("--out", required=True)
    inspect_v2.set_defaults(func=_inspect_v2)
    regions_v2 = sub.add_parser("regions-v2", help="build scoped, recursively expandable regions without selecting rewrites")
    regions_v2.add_argument("source", help="Python source for semantic view, trace directory/JSONL for execution view")
    regions_v2.add_argument("--view", choices=("semantic", "execution"), default="semantic")
    regions_v2.add_argument("--project-root")
    regions_v2.add_argument("--root-id", action="append", default=[], help="exact typed operation identity; repeat to select roots")
    regions_v2.add_argument("--scope", help="explicit runtime observation scope")
    regions_v2.add_argument("--max-depth", type=int, default=0)
    regions_v2.add_argument("--root-limit", type=int, default=8)
    regions_v2.add_argument("--out", required=True, help="JSON report; use .gz for compressed output")
    regions_v2.set_defaults(func=_regions_v2)
    semantics_v2 = sub.add_parser("semantics-v2", help="extract ordered source semantics and bounded constant facts without executing the target")
    semantics_v2.add_argument("source")
    semantics_v2.add_argument("--project-root")
    semantics_v2.add_argument("--max-nodes", type=int, default=10000)
    semantics_v2.add_argument("--max-int-bits", type=int, default=4096)
    semantics_v2.add_argument("--out", required=True, help="JSON report, optionally ending in .gz")
    semantics_v2.set_defaults(func=_semantics_v2)
    import_values_v2 = sub.add_parser("import-values-v2", help="follow typed local import/export value paths without executing or deleting imports")
    import_values_v2.add_argument("source")
    import_values_v2.add_argument("--project-root")
    import_values_v2.add_argument("--max-nodes", type=int, default=10000)
    import_values_v2.add_argument("--max-int-bits", type=int, default=4096)
    import_values_v2.add_argument("--out", required=True, help="JSON report, optionally ending in .gz")
    import_values_v2.set_defaults(func=_import_values_v2)
    proof_models = sub.add_parser("proof-models-v2", help="build source control and primitive proof models without approving rewrites")
    proof_models.add_argument("source")
    proof_models.add_argument("--project-root")
    proof_models.add_argument("--out", required=True, help="JSON report, optionally ending in .gz")
    proof_models.set_defaults(func=_proof_models_v2)
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
    micro.set_defaults(func=_optimize_micro)
    args = parser.parse_args(argv)
    return args.func(args)


def _optimize_micro(args) -> int:
    from scar.workloads.micro import optimize
    print(json.dumps(optimize(args.loops, args.repetitions, args.warmup, args.work_factor), indent=2))
    return 0


def _check_program(args) -> int:
    from scar.ir.program.codec import _has_driver_capability, _has_no_body_capability, loads as load_program
    from scar.ir.program.model import LocalBindingValue, value_type
    from scar.ir.program.cleanup import CleanupRouteTerminator
    from scar.ir.program.resumption import SuspendTerminator
    from scar.ir.program.drivers import BodyDriveTerminator
    from scar.ir.record_codec import encode as encode_record
    from scar.ir.v2.common import ProofStatus

    source = Path(args.graph)
    report = {"schema": "scar.program-graph-check", "schema_version": 1,
              "input": str(source.resolve()), "scope": "declared graph structure and dependencies",
              "source_recovery": False, "transformation_authorized": False,
              "cleanup_structure_validated": False,
              "body_structure_validated": False,
              "body_driver_verified": False,
              "body_source_verified": False,
              "body_runtime_verified": False,
              "body_exclusivity_verified": False,
              "driver_structure_validated": False,
              "driver_lifecycle_verified": False,
              "body_publication_structure_validated": False,
              "no_body_structure_validated": False,
              "session_release_structure_validated": False,
              "conditional_lifecycle_facts_derived": False,
              "conditional_lifecycle_scopes": []}
    if args.out and Path(args.out).resolve() == source.resolve():
        report.update(status="INVALID", errors=["report path must differ from input graph"])
        print(json.dumps(report, ensure_ascii=False))
        return 2
    try:
        graph = load_program(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        report.update(status="INVALID", errors=[str(exc)])
    else:
        report.update(status="WELL_FORMED", errors=[], counts={
            "regions": len(graph.regions), "blocks": sum(len(r.blocks) for r in graph.regions),
            "operations": len(graph.operations), "values": len(graph.values),
            "locations": len(graph.locations), "uses": sum(len(op.uses) for op in graph.operations),
            "value_kinds": dict(Counter(
                "LOCAL_BINDING" if isinstance(value, LocalBindingValue)
                else value_type(value).kind.value for value in graph.values)),
            "declared_incomplete_effects": sum(not op.effects_complete for op in graph.operations),
        })
        if any((graph.resources, graph.resource_requirements, graph.resource_uses,
                graph.resource_locations)):
            report["counts"].update(
                resources=len(graph.resources),
                resource_requirements=len(graph.resource_requirements),
                resource_uses=len(graph.resource_uses),
                resource_locations=len(graph.resource_locations))
            report.update(resource_realization_verified=False, readiness_verified=False)
        if graph.environments:
            report["counts"].update(
                environments=len(graph.environments),
                environment_members=sum(len(item.members) for item in graph.environments),
                function_entries=len(graph.function_entries),
                python_parameters=sum(len(item.parameters) for item in graph.function_entries))
            report.update(environment_realization_verified=False,
                          environment_extraction_verified=False,
                          python_signature_binding_verified=False,
                          runtime_callable_verified=False)
        if graph.control_scopes:
            report["counts"].update(
                control_scopes=len(graph.control_scopes), control_ports=len(graph.control_ports),
                exception_packets=len(graph.exception_packets),
                pending_completions=len(graph.pending_completions))
            report.update(lexical_source_verified=False, cleanup_unwinding_verified=False,
                          exception_context_verified=False,
                          pending_runtime_realization_verified=False)
        if graph.handled_context_domains:
            report["counts"].update(
                cleanup_interfaces=len(graph.cleanup_interfaces),
                cleanup_actions=sum(len(rows) for rows in (
                    graph.cleanup_enters, graph.cleanup_resumes,
                    graph.cleanup_replacements, graph.handled_context_reads)),
                cleanup_routes=sum(isinstance(op.terminator, CleanupRouteTerminator)
                                   for op in graph.operations))
            report.update(cleanup_structure_validated=True,
                          cleanup_structure_scope="declared static interfaces, CFG routes and state flow",
                          cleanup_unwinding_verified=False,
                          exception_context_verified=False,
                          pending_runtime_realization_verified=False)
        if graph.provider_envelopes:
            report["counts"].update(
                provider_envelopes=len(graph.provider_envelopes),
                provider_regions=len(graph.provider_regions),
                provider_bindings=len(graph.provider_bindings))
            report.update(provider_artifact_replay_verified=False,
                          provider_conditions_verified=False,
                          provider_source_correspondence_verified=False,
                          cross_representation_equivalence_verified=False,
                          provider_runtime_correspondence_verified=False)
        if graph.native_boundaries:
            report["counts"].update(native_boundaries=len(graph.native_boundaries),
                                    boundary_relations=len(graph.boundary_relations))
            report.update(native_signature_replay_verified=False,
                          native_tree_mapping_verified=False,
                          native_state_binding_verified=False,
                          boundary_relations_verified=False)
        if graph.resumable_bodies:
            report["counts"].update(
                resumable_bodies=len(graph.resumable_bodies),
                suspensions=sum(type(operation.terminator) is SuspendTerminator
                                for operation in graph.operations),
                frame_context_actions=(len(graph.frame_context_initials)
                                       + len(graph.frame_context_attaches)
                                       + len(graph.frame_context_detaches)))
            report["body_structure_validated"] = True
        if _has_driver_capability(graph):
            report["counts"].update(
                resumable_creates=len(graph.resumable_creates),
                raw_driver_requests=len(graph.raw_driver_requests),
                async_request_creates=len(graph.async_request_creates),
                request_association_reads=len(graph.request_association_reads),
                driver_interfaces=len(graph.driver_interfaces),
                final_body_gates=len(graph.final_body_gates),
                body_drives=len(graph.body_drives),
                body_drive_outcomes=sum(
                    len(operation.terminator.successors)
                    for operation in graph.operations
                    if type(operation.terminator) is BodyDriveTerminator))
            report.update(driver_structure_validated=True,
                          driver_structure_scope="declared static driver ports, CFG and current state flow",
                          driver_lifecycle_verified=False)
        if graph.driver_lifecycles:
            interfaces = {row.region: row for row in graph.driver_interfaces}
            operation_regions = {operation: region.id for region in graph.regions
                                 for block in region.blocks for operation in block.operations}
            tables = ("body_outcome_commits", "created_close_tests", "no_body_finishes",
                      "session_updates", "terminal_frame_releases")
            report["conditional_lifecycle_scopes"] = [
                {"region": scope.region.wire,
                 "rule_profile": interfaces[scope.region].rule.profile.value,
                 "implementation": encode_record(interfaces[scope.region].rule.implementation),
                 "applicability": ProofStatus.UNKNOWN.value,
                 "conditional_facts_derived": True,
                 "declared_capabilities": {
                     name: sum(operation_regions[row.operation] == scope.region
                               for row in getattr(graph, name)) for name in tables}}
                for scope in graph.driver_lifecycles]
            report["conditional_lifecycle_facts_derived"] = True
            report["counts"].update(
                driver_lifecycles=len(graph.driver_lifecycles),
                body_outcome_commits=len(graph.body_outcome_commits))
            report.update(body_publication_structure_validated=True,
                          body_publication_structure_scope="declared body outcome, owner and publication state links",
                          driver_lifecycle_verified=False)
        if graph.driver_lifecycles and _has_no_body_capability(graph):
            report["counts"].update(created_close_tests=len(graph.created_close_tests),
                                    no_body_finishes=len(graph.no_body_finishes))
            report.update(no_body_structure_validated=True,
                          no_body_structure_scope="declared predicate, real branch edges and optional no-body finish links",
                          driver_lifecycle_verified=False)
        if graph.session_updates or graph.terminal_frame_releases:
            report["counts"].update(session_updates=len(graph.session_updates),
                                    terminal_frame_releases=len(graph.terminal_frame_releases))
            report.update(session_release_structure_validated=True,
                          session_release_structure_scope="declared post states and conditional terminal owner history; no native applicability or resource-release guarantee",
                          conditional_lifecycle_facts_derived=True,
                          driver_lifecycle_verified=False)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        destination = Path(args.out)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report["status"] == "WELL_FORMED" else 2


def _bind_dispatch_sources(args) -> int:
    from scar.analysis.dispatch_sources import bind_dispatch_sources
    from scar.analysis.program_composition import CompositionIndex
    from scar.trace.capture_coordinates import bind_capture_coordinates
    try:
        output = Path(args.out).resolve()
        coordinates = bind_capture_coordinates(args.capture, max_bytes=args.max_bytes, max_lines=args.max_lines,
            profile_uri=str(output / 'capture-coordinates.json'))
        report = bind_dispatch_sources(args.source_bindings, args.dispatch_bridge, coordinates, output,
            max_input_bytes=args.max_input_bytes, max_observations=args.max_observations,
            composition_index=CompositionIndex(args.composition) if args.composition else None)
    except (OSError, ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
        print(json.dumps({"status": "INVALID", "errors": [str(error)], "transformation_authorized": False}))
        return 2
    print(json.dumps({"status": "BOUND_WITH_OPEN_OBLIGATIONS", "out": str(output),
                      "summary": report['summary'], "first_stage_complete": False}))
    return 0


def _query_dispatch_source(args) -> int:
    from scar.analysis.dispatch_sources import query_dispatch_source
    try:
        row = query_dispatch_source(args.directory, args.marker)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"status": "INVALID", "errors": [str(error)]}))
        return 2
    print(json.dumps(row))
    return 0


def _bind_source_invocations(args) -> int:
    from scar.analysis.program_composition import CompositionIndex
    from scar.analysis.source_invocations import bind_source_invocations
    from scar.trace.capture_coordinates import bind_capture_coordinates
    try:
        output = Path(args.out).resolve()
        coordinates = bind_capture_coordinates(args.capture, max_bytes=args.max_bytes, max_lines=args.max_lines,
            profile_uri=str(output / 'capture-coordinates.json'))
        composition = CompositionIndex(args.composition, max_input_bytes=args.max_input_bytes)
        report = bind_source_invocations(composition, coordinates,
            args.trace or str(Path(args.capture) / 'trace'), output,
            call_budget=_call_budget(args), witness_mode=args.witness_mode)
    except (OSError, ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
        print(json.dumps({"status": "INVALID", "errors": [str(error)],
                          "transformation_authorized": False}))
        return 2
    print(json.dumps({"status": "BOUND_WITH_OPEN_OBLIGATIONS", "out": str(output),
                      "summary": report['summary'], "first_stage_complete": False}))
    return 0


def _admit_dependency_sources(args) -> int:
    from scar.analysis.dependency_sources import DependencySourceBudget, admit_dependency_sources
    from scar.ir.program.expansion import ContextStoreBudget
    try:
        report = admit_dependency_sources(args.trace, args.project_root, args.out,
            call_budget=_call_budget(args),
            budget=DependencySourceBudget(**{name: getattr(args, "dependency_" + name)
                for name in DependencySourceBudget.__dataclass_fields__}),
            context_budget=ContextStoreBudget(**{name: getattr(args, "context_" + name)
                for name in ContextStoreBudget.__dataclass_fields__}))
    except (OSError, ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
        print(json.dumps({"status": "INVALID", "errors": [str(error)],
                          "transformation_authorized": False}))
        return 2
    print(json.dumps({"status": "ADMITTED_WITH_OPEN_OBLIGATIONS", "out": args.out,
                      "summary": report["summary"], "first_stage_complete": False}))
    return 0


def _compose_program(args) -> int:
    from scar.analysis.program_composition import compose_program
    try:
        report = compose_program(args.inventory, args.source_layers, args.out,
            max_input_bytes=args.max_input_bytes, max_files=args.max_files,
            max_record_bytes=args.max_record_bytes, max_output_bytes=args.max_output_bytes)
    except (OSError, ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
        print(json.dumps({"status": "INVALID", "errors": [str(error)],
                          "transformation_authorized": False}))
        return 2
    print(json.dumps({"status": "INDEXED_WITH_FRONTIERS", "out": args.out, **report}))
    return 0


def _model_program(args) -> int:
    from scar.analysis.program_lowering import lower_source
    from scar.ir.program.functions import BodyLoweringProfile

    source, output = Path(args.source).resolve(), Path(args.out).resolve()
    try:
        if source == output or (output.exists() and source.samefile(output)):
            raise ValueError("report path must differ from source")
        profile = {"frame": BodyLoweringProfile.BOUND_FRAME,
                   "legacy": BodyLoweringProfile.LEGACY,
                   "structured": BodyLoweringProfile.STRUCTURED_BODY,
                   "environment": BodyLoweringProfile.STRUCTURED_ENV}[args.body_profile]
        result = lower_source(source, args.entry, max_operations=args.max_operations, profile=profile)
        document = result.to_dict()
        _write_call_document(output, document, max_bytes=args.max_report_bytes)
    except (OSError, ValueError, TypeError, SyntaxError, RecursionError) as error:
        print(json.dumps({"status": "INVALID", "errors": [str(error)],
                          "transformation_authorized": False}))
        return 2
    print(json.dumps({"status": document["status"], "out": str(output),
                      "summary": result.summary()}))
    return 0 if result.graph is not None else 3


def _check_source_program(args) -> int:
    from scar.analysis.program_lowering import SourceProgram
    try:
        result = SourceProgram.from_dict(_call_json(args.report, max_bytes=args.max_report_bytes),
                                         max_operations=args.max_operations)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, SyntaxError, RecursionError) as error:
        print(json.dumps({"status": "INVALID", "errors": [str(error)],
                          "transformation_authorized": False}))
        return 2
    print(json.dumps({"status": "REPLAYED", "summary": result.summary(),
                      "transformation_authorized": False}))
    return 0


def _query_frame_references(args) -> int:
    from scar.analysis.frame_queries import query_return_references
    try:
        document = _call_json(args.report, max_bytes=args.max_report_bytes)
        report = query_return_references(document, max_operations=args.max_operations,
                                         max_reference_steps=args.max_reference_steps)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, SyntaxError, RecursionError) as error:
        print(json.dumps({"status": "INVALID", "errors": [str(error)],
                          "transformation_authorized": False}))
        return 2
    print(json.dumps(report, ensure_ascii=True))
    return 0


def _inventory_limits(args):
    return {name: getattr(args, name) for name in
            ("max_files", "max_bytes", "max_directories", "max_lowered_bodies", "max_operations", "max_call_witnesses")}


def _runtime_inventory_budget(args):
    from scar.ir.program.runtime_sources import RuntimeTraceBudget
    return RuntimeTraceBudget(max_uncompressed_bytes=args.max_trace_bytes,
                              max_lines=args.max_trace_records,
                              max_line_bytes=args.max_trace_line_bytes,
                              max_codes=args.max_runtime_codes)


def _context_inventory_budget(args):
    from scar.ir.program.expansion import ContextStoreBudget
    return ContextStoreBudget(args.max_context_bytes, args.max_context_record_bytes)


def _inventory_analysis_measurements(result):
    from scar.ir.record_codec import encode
    return encode(result.analysis_measurements) if result.analysis_measurements is not None else None


def _inventory_program(args) -> int:
    from scar.analysis.program_inventory import inventory_program
    from scar.ir.program.functions import BodyLoweringProfile

    output = Path(args.out).resolve()
    try:
        if not (output.name.endswith(".json") or output.name.endswith(".json.gz")):
            raise ValueError("inventory report must end in .json or .json.gz")
        result = inventory_program(args.source, project_root=args.project_root,
                                   source_roots=args.source_root, **_inventory_limits(args),
                                   runtime_trace=args.trace, runtime_budget=_runtime_inventory_budget(args),
                                   max_compile_attempts=args.max_compile_attempts,
                                   context_budget=_context_inventory_budget(args),
                                   calls_trace=args.calls, call_budget=_call_budget(args),
                                   body_profile=(BodyLoweringProfile.STRUCTURED_ENV if args.body_profile == "environment" else
                                                 BodyLoweringProfile.STRUCTURED_BODY if args.body_profile == "structured"
                                                 else BodyLoweringProfile.BOUND_FRAME))
        for file in result.discovery.files:
            source = Path(file.snapshot.path)
            if output == source or (output.exists() and source.samefile(output)):
                raise ValueError("report must differ from every discovered source")
        if result.runtime_scope is not None:
            from scar.trace.files import resolve
            logical = Path(result.runtime_scope.trace.manifest.logical_path)
            actual = resolve(logical)
            if output == logical or output == actual or (output.exists() and actual.samefile(output)):
                raise ValueError("report must differ from its runtime trace")
        if result.call_sources is not None:
            protected = chain(Path(result.call_sources.model.trace_directory).iterdir(),
                              _call_source_inputs(result.call_sources.model))
            if any(output == path.resolve() or output.exists() and path.exists() and output.samefile(path)
                   for path in protected):
                raise ValueError("inventory report must differ from raw calls and captured source inputs")
            if output.exists():
                existing = _call_json(output, max_bytes=args.max_call_report_bytes)
                if type(existing) is not dict or existing.get("schema") != "scar.program-inventory":
                    raise ValueError("refusing to overwrite a non-inventory-report output")
            _write_call_document(output, result.to_dict(), args.max_call_report_bytes)
        else:
            _compressed_document(output, result.to_dict())
    except (OSError, ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
        print(json.dumps({"status": "INVALID", "errors": [str(error)], "transformation_authorized": False}))
        return 2
    print(json.dumps({"status": "INVENTORIED", "out": str(output), "summary": result.summary(),
                      "analysis_measurements": _inventory_analysis_measurements(result),
                      **({"source_analysis_measurements": result.source_analysis_measurements}
                         if result.call_sources is not None else {})}))
    return 0


def _check_inventory(args) -> int:
    from scar.analysis.program_inventory import ProgramInventory
    from scar.ir.record_codec import loads as strict_loads
    from scar.trace.files import open_text

    try:
        result = ProgramInventory.from_dict(_call_json(args.report, max_bytes=args.max_call_report_bytes),
            **_inventory_limits(args), runtime_verification_budget=_runtime_inventory_budget(args),
            max_compile_attempts=args.max_compile_attempts,
            context_verification_budget=_context_inventory_budget(args), call_verification_budget=_call_budget(args))
    except (OSError, ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
        print(json.dumps({"status": "INVALID", "errors": [str(error)], "transformation_authorized": False}))
        return 2
    print(json.dumps({"status": "REPLAYED", "summary": result.summary(), "transformation_authorized": False,
                      "analysis_measurements": _inventory_analysis_measurements(result),
                      **({"source_analysis_measurements": result.source_analysis_measurements}
                         if result.call_sources is not None else {})}))
    return 0


def _source_layers(args) -> int:
    from scar.analysis.source_layers import reconstruct_source_layers

    try:
        manifest = reconstruct_source_layers(args.inventory, args.out,
            max_input_bytes=args.max_input_bytes, max_files=args.max_files,
            max_record_bytes=args.max_record_bytes, max_total_bytes=args.max_total_bytes,
            reuse_archive=args.reuse_archive)
    except (OSError, ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
        print(json.dumps({"status": "INVALID", "errors": [str(error)],
                          "whole_program_graph_established": False, "transformation_authorized": False}))
        return 2
    print(json.dumps({"status": "RETAINED" if manifest["complete"] else "PARTIAL",
                      "out": str(Path(args.out).resolve()), "complete": manifest["complete"],
                      "whole_program_graph_established": False, "transformation_authorized": False}))
    return 0 if manifest["complete"] else 2


def _call_budget(args):
    from scar.ir.program.call_edges import CallEdgeBudget
    return CallEdgeBudget(max_raw_bytes=args.max_call_trace_bytes,max_lines=args.max_call_trace_lines,
        max_line_bytes=args.max_call_line_bytes,max_processes=args.max_call_processes,
        max_events=args.max_call_trace_events,max_references=args.max_call_references,max_path=args.max_call_path,
        max_codes=args.max_call_trace_codes,max_source_files=args.max_call_source_files,
        max_source_bytes=args.max_call_source_bytes)


def _call_report_limit(value):
    if type(value) is not int or value < 1 or value >= sys.maxsize:
        raise ValueError('call report byte ceiling must be a positive exact integer below sys.maxsize')
    return value


def _call_json(path, *, max_bytes=256000000):
    import math
    from scar.trace.files import open_binary
    max_bytes=_call_report_limit(max_bytes)
    def unique(pairs):
        result={}
        for name,value in pairs:
            if name in result:
                raise ValueError('duplicate JSON field: '+name)
            result[name]=value
        return result
    with open_binary(path) as stream:
        raw=stream.read(max_bytes+1)
    if len(raw)>max_bytes:
        raise ValueError('call report exceeds independent read byte ceiling: '+str(max_bytes))
    def reject(value):
        raise ValueError('nonfinite JSON value: '+value)
    def finite(value):
        number=float(value)
        if not math.isfinite(number):
            reject(value)
        return number
    return json.loads(raw.decode('utf-8'),object_pairs_hook=unique,parse_constant=reject,parse_float=finite)


def _write_call_document(output, document, max_bytes):
    """Bound the raw JSON while writing; a failure preserves any old report."""
    import gzip
    import tempfile
    max_bytes=_call_report_limit(max_bytes)
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='wb',dir=output.parent,prefix='.scar-call-',delete=False) as raw:
            temporary=Path(raw.name)
            stream=gzip.GzipFile(fileobj=raw,mode='wb',mtime=0,filename='') if output.suffix=='.gz' else raw
            try:
                written=0
                pending=bytearray()
                encoder=json.JSONEncoder(sort_keys=True,ensure_ascii=True,allow_nan=False,separators=(',',':'))
                for piece in encoder.iterencode(document):
                    data=piece.encode('utf-8')
                    written+=len(data)
                    if written+1>max_bytes:
                        raise ValueError('call report exceeds independent write byte ceiling: '+str(max_bytes))
                    pending.extend(data)
                    if len(pending)>=65536:
                        stream.write(pending)
                        pending.clear()
                if pending:
                    stream.write(pending)
                stream.write(b'\n')
            finally:
                if stream is not raw:
                    stream.close()
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _call_inventory_input(path,args,expected=None,*,max_input_bytes=None):
    import hashlib
    from scar.analysis.program_inventory import ProgramInventory
    from scar.trace.files import resolve
    actual=resolve(Path(path).resolve())
    if max_input_bytes is None:
        # Historical callers retain their original limits and failure order.
        with actual.open('rb') as stream:
            digest=hashlib.file_digest(stream,'sha256').hexdigest()
    else:
        ceiling=_call_report_limit(max_input_bytes)
        if actual.stat().st_size > ceiling:
            raise ValueError('inventory raw input byte budget exceeded')
        hashed=0
        hasher=hashlib.sha256()
        with actual.open('rb') as stream:
            while True:
                chunk=stream.read(min(1_000_000,ceiling-hashed+1))
                if not chunk:
                    break
                hashed+=len(chunk)
                if hashed > ceiling:
                    raise ValueError('inventory raw input byte budget exceeded')
                hasher.update(chunk)
        digest=hasher.hexdigest()
    if expected is not None and digest!=expected:
        raise ValueError('call report inventory file differs from its bound input')
    document=(_call_json(actual) if max_input_bytes is None else
              _call_json(actual,max_bytes=max_input_bytes))
    inventory=ProgramInventory.from_dict(document,**_inventory_limits(args),
        runtime_verification_budget=_runtime_inventory_budget(args),max_compile_attempts=args.max_compile_attempts,
        context_verification_budget=_context_inventory_budget(args),call_verification_budget=_call_budget(args))
    return inventory,{'path':str(actual),'sha256':digest}


def _call_report_input(path,args):
    from scar.analysis.call_edges import CallEdgeReport
    budget=_call_budget(args)
    document=_call_json(path,max_bytes=args.max_call_report_bytes)
    if (type(document) is not dict or set(document)!={'schema','schema_version','inventory','analysis'}
            or document['schema']!='scar.call-links-envelope' or type(document['schema_version']) is not int
            or document['schema_version']!=1):
        raise ValueError('call report envelope fields/schema mismatch')
    inventory=None
    binding=document['inventory']
    if binding is not None:
        if type(binding) is not dict or set(binding)!={'path','sha256'}:
            raise ValueError('call report inventory binding fields mismatch')
        inventory,_=_call_inventory_input(binding['path'],args,binding['sha256'])
    return CallEdgeReport.from_dict(document['analysis'],inventory=inventory,verification_budget=budget)


def _call_source_inputs(model):
    """Protect observed source paths even when offline resolution failed.

    A captured filename is not a source proof, but it must not disappear from
    overwrite protection when a source budget or canonical-path check fails.
    Python source filenames can end in .json and contain report-shaped JSON.
    """
    paths = {Path(link.snapshot.path) for link in model.code_links if link.snapshot is not None}
    for capture in model.codes:
        path = Path(capture.code.filename)
        if path.is_absolute():
            paths.add(path)
        else:
            paths.add(Path(model.project_root) / path)
            paths.add(Path.cwd() / path)
    return sorted(paths, key=str)


def _link_calls_cli(args):
    from scar.analysis.call_edges import link_calls
    try:
        budget=_call_budget(args)
        report_limit=_call_report_limit(args.max_call_report_bytes)
        inventory,binding=_call_inventory_input(args.inventory,args) if args.inventory else (None,None)
        report=link_calls(args.trace,project_root=args.project_root,inventory=inventory,budget=budget)
        output=Path(args.out).resolve()
        if not (output.name.endswith('.json') or output.name.endswith('.json.gz')):
            raise ValueError('call report must end in .json or .json.gz')
        protected=[]
        if binding is not None:
            protected.append(Path(binding['path']))
        if inventory is not None:
            protected.extend(Path(f.snapshot.path) for f in inventory.files)
        protected.extend(_call_source_inputs(report.model))
        if any(output==p.resolve() or output.exists() and p.exists() and output.samefile(p)
               for p in chain(Path(args.trace).resolve().iterdir(), protected)):
            raise ValueError('call report must differ from trace, source and inventory inputs')
        if output.exists() and _call_json(output,max_bytes=report_limit).get('schema')!='scar.call-links-envelope':
            raise ValueError('refusing to overwrite a non-call-report output')
        _write_call_document(output,{'schema':'scar.call-links-envelope','schema_version':1,
                                    'inventory':binding,'analysis':report.to_dict()},report_limit)
    except (OSError,ValueError,TypeError,KeyError,AttributeError,SyntaxError,RecursionError) as error:
        print(json.dumps({'status':'INVALID','errors':[str(error)],'transformation_authorized':False}))
        return 2
    print(json.dumps({'status':'LINKED','summary':report.summary(),'out':str(output),'transformation_authorized':False}))
    return 0


def _seed_calls_cli(args):
    from scar.analysis.call_seeds import read_call_source_seeds
    try:
        budget = _call_budget(args)
        report_limit = _call_report_limit(args.max_call_report_bytes)
        report = read_call_source_seeds(args.trace, args.project_root, budget=budget)
        output = Path(args.out).resolve()
        if not (output.name.endswith('.json') or output.name.endswith('.json.gz')):
            raise ValueError('source seed report must end in .json or .json.gz')
        protected = []
        protected.extend(_call_source_inputs(report.model))
        if any(output == path.resolve() or output.exists() and path.exists() and output.samefile(path)
               for path in chain(Path(args.trace).resolve().iterdir(), protected)):
            raise ValueError('source seed report must differ from trace and source inputs')
        if output.exists():
            existing = _call_json(output, max_bytes=report_limit)
            if type(existing) is not dict or existing.get('schema') != 'scar.call-source-seeds':
                raise ValueError('refusing to overwrite a non-source-seed-report output')
        _write_call_document(output, report.to_dict(), report_limit)
    except (OSError,ValueError,TypeError,KeyError,AttributeError,SyntaxError,RecursionError) as error:
        print(json.dumps({'status':'INVALID','errors':[str(error)],'transformation_authorized':False}))
        return 2
    print(json.dumps({'status':'SOURCE_SEEDS','summary':report.summary(),
                      'out':str(output),'transformation_authorized':False}))
    return 0


def _check_call_seeds_cli(args):
    from scar.analysis.call_seeds import CallSourceSeedReport
    try:
        budget = _call_budget(args)
        document = _call_json(args.report, max_bytes=args.max_call_report_bytes)
        report = CallSourceSeedReport.from_dict(document, verification_budget=budget)
    except (OSError,ValueError,TypeError,KeyError,AttributeError,SyntaxError,RecursionError) as error:
        print(json.dumps({'status':'INVALID','errors':[str(error)],'transformation_authorized':False}))
        return 2
    print(json.dumps({'status':'REPLAYED','summary':report.summary(),'transformation_authorized':False}))
    return 0


def _check_call_links_cli(args):
    try:
        report=_call_report_input(args.report,args)
    except (OSError,ValueError,TypeError,KeyError,AttributeError,SyntaxError,RecursionError) as error:
        print(json.dumps({'status':'INVALID','errors':[str(error)],'transformation_authorized':False}))
        return 2
    print(json.dumps({'status':'REPLAYED','summary':report.summary(),'transformation_authorized':False}))
    return 0


def _query_call_refs_cli(args):
    from scar.ir.program.call_edges import InvocationKey
    from scar.ir.record_codec import encode
    try:
        report=_call_report_input(args.report,args)
        query=report.trace_reference(InvocationKey(args.process,args.thread,args.invocation))
    except (OSError,ValueError,TypeError,KeyError,AttributeError,SyntaxError,RecursionError) as error:
        print(json.dumps({'status':'INVALID','errors':[str(error)],'transformation_authorized':False}))
        return 2
    print(json.dumps({'status':'REFERENCE_QUERY','query':encode(query),'transformation_authorized':False}))
    return 0


def _operand_budgets(args):
    from scar.ir.program.call_operands import CallOperandBudget
    from scar.ir.program.call_operand_routes import OperandRouteBudget
    operand = CallOperandBudget(**{name: getattr(args, 'operand_' + name)
                                  for name in CallOperandBudget.__dataclass_fields__})
    route = OperandRouteBudget(**{name: getattr(args, 'route_' + name)
                                for name in OperandRouteBudget.__dataclass_fields__})
    return operand, route


def _operand_report_input(path, args):
    import re
    from scar.analysis.call_operands import CallOperandReport
    document = _call_json(path, max_bytes=args.max_call_report_bytes)
    if (type(document) is not dict or set(document) != {'schema','schema_version','inventory','analysis'}
            or document['schema'] != 'scar.call-operand-links-envelope'
            or type(document['schema_version']) is not int or document['schema_version'] != 1):
        raise ValueError('operand report envelope fields/schema mismatch')
    operand_budget, route_budget = _operand_budgets(args)
    # Decode the original independent ceilings before consulting the inventory,
    # target source or raw trace named by this untrusted report.
    CallOperandReport.check_replay_header(document['analysis'], frame_ceiling=_call_budget(args),
        operand_ceiling=operand_budget, route_ceiling=route_budget)
    binding = document['inventory']
    if (type(binding) is not dict or set(binding) != {'path','sha256'}
            or type(binding['path']) is not str or not binding['path']
            or type(binding['sha256']) is not str
            or re.fullmatch(r'[0-9a-f]{64}',binding['sha256']) is None):
        raise ValueError('operand report requires a bound inventory file')
    inventory, _ = _call_inventory_input(binding['path'], args, binding['sha256'],
                                          max_input_bytes=args.max_call_report_bytes)
    return CallOperandReport.from_dict(document['analysis'], inventory=inventory,
        frame_ceiling=_call_budget(args), operand_ceiling=operand_budget, route_ceiling=route_budget)


def _link_operands_cli(args):
    from scar.analysis.call_operands import link_call_operands
    try:
        operand_budget, route_budget = _operand_budgets(args)
        frame_budget = _call_budget(args)
        limit = _call_report_limit(args.max_call_report_bytes)
        inventory, binding = _call_inventory_input(args.inventory, args, max_input_bytes=limit)
        report = link_call_operands(args.trace, args.project_root, inventory,
            frame_budget=frame_budget, operand_budget=operand_budget, route_budget=route_budget,
            include_environments=bool(getattr(args, 'environments_out', None)))
        output = Path(args.out).resolve()
        if not (output.name.endswith('.json') or output.name.endswith('.json.gz')):
            raise ValueError('operand report must end in .json or .json.gz')
        protected = [Path(binding['path']), *(Path(file.snapshot.path) for file in inventory.files),
                     *_call_source_inputs(report.frame_model)]
        if any(output == path.resolve() or output.exists() and path.exists() and output.samefile(path)
               for path in chain(Path(args.trace).resolve().iterdir(), protected)):
            raise ValueError('operand report must differ from raw trace, source and inventory inputs')
        environments_output = None
        if getattr(args, 'environments_out', None):
            environments_output = Path(args.environments_out).resolve()
            if (environments_output == output or environments_output.exists()
                    or not environments_output.name.endswith(('.json', '.json.gz'))
                    or any(environments_output == path.resolve() for path in
                           chain(Path(args.trace).resolve().iterdir(), protected))):
                raise ValueError('environment output must be a fresh JSON path distinct from all inputs and the operand output')
        if output.exists():
            existing = _call_json(output, max_bytes=limit)
            if type(existing) is not dict or existing.get('schema') != 'scar.call-operand-links-envelope':
                raise ValueError('refusing to overwrite a non-operand-report output')
        _write_call_document(output, {'schema':'scar.call-operand-links-envelope','schema_version':1,
            'inventory':binding,'analysis':report.to_dict()}, limit)
        if environments_output is not None:
            _write_call_document(environments_output, report.environments, limit)
    except (OSError,ValueError,TypeError,KeyError,AttributeError,SyntaxError,RecursionError) as error:
        print(json.dumps({'status':'INVALID','errors':[str(error)],'transformation_authorized':False}))
        return 2
    print(json.dumps({'status':'CONDITIONAL_ROUTES','summary':report.summary(),
        'out':str(output),'transformation_authorized':False}))
    return 0


def _check_operand_links_cli(args):
    try:
        report = _operand_report_input(args.report,args)
    except (OSError,ValueError,TypeError,KeyError,AttributeError,SyntaxError,RecursionError) as error:
        print(json.dumps({'status':'INVALID','errors':[str(error)],'transformation_authorized':False}))
        return 2
    print(json.dumps({'status':'REPLAYED_CONDITIONAL_ROUTES','summary':report.summary(),
        'transformation_authorized':False}))
    return 0


def _query_operand_refs_cli(args):
    from scar.ir.program.call_edges import InvocationKey
    from scar.ir.record_codec import encode
    try:
        report = _operand_report_input(args.report,args)
        query = report.trace_reference(InvocationKey(args.process,args.thread,args.invocation),
                                       max_steps=args.max_reference_steps)
    except (OSError,ValueError,TypeError,KeyError,AttributeError,SyntaxError,RecursionError) as error:
        print(json.dumps({'status':'INVALID','errors':[str(error)],'transformation_authorized':False}))
        return 2
    print(json.dumps({'status':'CONDITIONAL_REFERENCE_QUERY','query':encode(query),
        'transformation_authorized':False}))
    return 0


def _write_document(path, document):
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w") as handle:
        json.dump(document, handle, sort_keys=True, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
    return target


def _model_v2(args) -> int:
    from scar.ir.frontend_v2 import build_semantic
    result = build_semantic(Path(args.source), project_root=args.project_root)
    document = result.graph.to_dict()
    validation = document["validation"]
    out = _write_document(args.out, document)
    report = _write_document(args.report or str(out) + ".coverage.json", result.coverage)
    print(json.dumps({"schema": result.graph.SCHEMA, "out": str(out),
                      "report": str(report), "validation": validation}))
    return 0


def _normalize_v2(args) -> int:
    from scar.trace.normalize_v2 import normalize_trace
    result = normalize_trace(args.trace)
    validation = result.bundle.assert_valid()
    out = _write_document(args.out, result.bundle.to_dict())
    report = _write_document(args.report or str(out) + ".coverage.json", result.coverage)
    print(json.dumps({"schema": result.bundle.SCHEMA, "out": str(out),
                      "report": str(report), "valid": validation["valid"]}))
    return 0


def _model_run(args) -> int:
    from scar.analysis.model_run import ModelRunBudget, run_model
    options = {name: getattr(args, name) for name in ModelRunBudget.__dataclass_fields__}
    report = run_model(args.capture, args.out, plan_only=args.plan_only,
                       resume=args.resume, budget=ModelRunBudget(**options))
    print(json.dumps({"out": str(Path(args.out).absolute()), "status": report["status"],
                      "attempt": report["attempt"], "whole_model_established": False}), flush=True)
    return 0 if report["status"] in ("METADATA_PLANNED_WITH_OPEN", "COMPONENTS_LINKED_WITH_OPEN") else 2


def _import_capture(args) -> int:
    from scar.trace.capture_import import import_capture
    report = import_capture(args.directory, args.out, max_bytes=args.max_bytes, max_lines=args.max_lines,
        schema_contracts=args.schema_contracts, bundle_partitions=args.bundle_partitions,
        os_interface_work=args.os_interface_work,
        progress=lambda record: print(json.dumps(record), flush=True))
    print(json.dumps({"out": str(Path(args.out).resolve()), "coordinate_identity_consistent": report["coordinate_identity_consistent"],
                      "whole_model_established": report["whole_model_established"]}))
    return 0


def _import_os_resources(args) -> int:
    from scar.trace.os_resources import import_os_resources, publish_os_interfaces
    output = Path(args.out).resolve()
    if output.exists():
        raise SystemExit("import-os-resources requires a fresh output directory")
    coordinates, root_tid = None, args.root_tid
    if args.capture_root is not None:
        from scar.trace.capture_coordinates import bind_capture_coordinates
        capture = Path(args.capture_root).resolve()
        if Path(args.directory).resolve() != capture / 'os':
            raise SystemExit("capture-root must contain the exact imported os/ directory")
        coordinates = bind_capture_coordinates(capture, max_bytes=args.max_bytes,
            max_lines=args.max_lines, profile_uri=str(output / 'capture-coordinates.json'))
        declared_pid = coordinates.target_process.pid
        if root_tid is not None and root_tid != declared_pid:
            raise SystemExit("root-tid contradicts the original collector target declaration")
        root_tid = declared_pid
    fragment = import_os_resources(args.directory, scope=args.scope, root_tid=root_tid,
        max_bytes=args.max_bytes, max_lines=args.max_lines, coordinates=coordinates,
        interface_work=args.interface_work)
    output.mkdir(parents=True)
    if coordinates is not None:
        (output / 'capture-coordinates.json').write_bytes(coordinates.payload)
    (output / "os-resource-profile.json").write_bytes(fragment.protocol_bytes)
    if args.interface_work:
        publish_os_interfaces(fragment, output / 'interfaces',
            progress=lambda record: print(json.dumps(record), flush=True))
    else:
        _write_call_document(output / "os-resources.json.gz", fragment.to_dict(), args.max_report_bytes)
    (output / "summary.json").write_text(json.dumps(fragment.summary, indent=2) + "\n")
    print(json.dumps({"out": str(output), **fragment.summary}))
    return 0


def _import_native(args) -> int:
    from scar.trace.native_import import import_native_evidence
    output = Path(args.out).resolve()
    if output.exists():
        raise SystemExit("import-native requires a fresh output directory")
    bridge_args = (args.reference_markers, args.call_events, args.call_codes, args.call_meta, args.reference_profile)
    if any(item is not None for item in bridge_args):
        if not all(item is not None for item in bridge_args):
            raise SystemExit("reference import requires markers, call-events, call-codes, call-meta and reference-profile together")
        from scar.trace.reference_import import import_reference_bridge
        result = import_reference_bridge(args.execution_trace, args.reference_markers,
            args.call_events, args.call_codes, args.call_meta, reference_profile=args.reference_profile,
            kineto_path=args.kineto, max_bytes=args.max_bytes, provider_revision=args.provider_revision)
    else:
        result = import_native_evidence(args.execution_trace, args.kineto,
                                        max_bytes=args.max_bytes,
                                        provider_revision=args.provider_revision)
    # These are observation graphs, not a fabricated static SSA program.
    output.mkdir(parents=True, exist_ok=False)
    from scar.trace.native_memory_export import export_native_memory
    memory_fragment = export_native_memory(result, output)
    if memory_fragment is not None:
        _compressed_document(output / "native-memory-values.json.gz", result.bundle.values.to_dict())
        _compressed_document(output / "native-memory-lifetimes.json.gz", memory_fragment)
    _compressed_document(output / "evidence-bundle.json.gz", result.bundle.to_dict())
    _compressed_document(output / "provider-references.json.gz", result.references)
    _compressed_document(output / "resource-observations.json.gz", result.resources)
    _compressed_document(output / "import-report.json.gz", result.report)
    print(json.dumps({"out": str(output), "whole_model_established": False,
                      "instances": len(result.bundle.evidence.instances),
                      "edges": len(result.bundle.evidence.edges),
                      "cpu_rf_matches": result.report["cpu_rf_matches"],
                      "runtime_gpu_matches": result.report["runtime_gpu_matches"]}))
    return 0


def _inspect_v2(args) -> int:
    from scar.analysis.inspection_v2 import inspect_program
    report = inspect_program(args.source, args.trace, project_root=args.project_root,
                             runtime_sources=args.runtime_sources)
    output = _write_document(args.out, report)
    print(json.dumps({"out": str(output), "summary": report["summary"]}))
    return 0


def _compressed_document(output, report):
    output = Path(output).resolve()
    if output.suffix == ".gz":
        import gzip
        import io
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as destination, gzip.GzipFile(
                fileobj=destination, mode="wb", mtime=0, filename="") as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8") as text:
                json.dump(report, text, sort_keys=True, ensure_ascii=True, allow_nan=False)
                text.write("\n")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as text:
            json.dump(report, text, sort_keys=True, ensure_ascii=True, allow_nan=False)
            text.write("\n")
    return output


def _semantics_v2(args) -> int:
    from scar.analysis.constants_v2 import EvaluationBudget
    from scar.analysis.semantics_report_v2 import report_semantics
    report = report_semantics(args.source, project_root=args.project_root,
                              budget=EvaluationBudget(max_nodes=args.max_nodes, max_int_bits=args.max_int_bits))
    output = _compressed_document(args.out, report)
    print(json.dumps({"out": str(output), "summary": report["summary"]}))
    return 0


def _import_values_v2(args) -> int:
    from scar.analysis.constants_v2 import EvaluationBudget
    from scar.analysis.import_report_v2 import report_import_values
    report = report_import_values(args.source, project_root=args.project_root,
        budget=EvaluationBudget(max_nodes=args.max_nodes, max_int_bits=args.max_int_bits))
    output = _compressed_document(args.out, report)
    summary = {key: value for key, value in report["summary"].items() if key != "targets"}
    summary["target_count"] = len(report["summary"].get("targets", ()))
    print(json.dumps({"out": str(output), "summary": summary, "decision": report["decision"]}))
    return 0


def _proof_models_v2(args) -> int:
    from scar.analysis.proof_models_report_v2 import report_source_proof_models
    result = report_source_proof_models(Path(args.source).resolve(), project_root=args.project_root)
    output = _compressed_document(args.out, result)
    summary = {**result["summary"], "primitive_semantics": {
        key: value for key, value in result["summary"]["primitive_semantics"].items()
        if key not in {"certificates", "gaps"}}}
    print(json.dumps({"report": str(output), "summary": summary,
                      "decision": result["decision"]}))
    return 0


def _regions_v2(args) -> int:
    from scar.analysis.region_report_v2 import report_regions
    report = report_regions(args.source, view=args.view, project_root=args.project_root,
                            root_ids=tuple(args.root_id), max_depth=args.max_depth,
                            root_limit=args.root_limit, scope=args.scope)
    output = Path(args.out).resolve()
    if output.suffix == ".gz":
        import gzip
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as destination, gzip.GzipFile(
                fileobj=destination, mode="wb", mtime=0, filename="") as compressed:
            encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, allow_nan=False)
            for chunk in encoder.iterencode(report):
                compressed.write(chunk.encode())
            compressed.write(b"\n")
    else:
        _write_document(output, report)
    print(json.dumps({"out": str(output), "summary": report["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
