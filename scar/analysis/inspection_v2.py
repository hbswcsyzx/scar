"""Read-only G5 composition of source, runtime and effect-contract evidence."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import time

from scar.ir.frontend_v2 import build_semantic, build_semantic_files
from scar.ir.ids import CodeID
from scar.ir.record_codec import encode
from scar.ir.v2 import EvidenceClaim, EvidenceKind
from scar.trace.normalize_v2 import normalize_trace
from .contracts_v2 import EffectPolicy, evaluate_removal
from .correspondence_v2 import build_correspondence
from .runtime_effects_v2 import ingest_runtime_effects


def inspect_program(source, trace, *, project_root=None, runtime_sources=False):
    """Generate scoped requirements, never candidates, rewrites or performance claims."""
    started = time.perf_counter()
    source = Path(source).resolve()
    root = Path(project_root).resolve() if project_root else (source if source.is_dir() else source.parent)
    if not source.exists():
        raise FileNotFoundError(source)
    if not root.is_dir() or not source.is_relative_to(root):
        raise ValueError("source must be within an existing project root")
    if source.is_file() and source.suffix != ".py":
        raise ValueError("source file must be Python")
    normalized = normalize_trace(trace)
    normalize_seconds = time.perf_counter() - started
    selected, missing = {source} if source.is_file() else set(), []
    if runtime_sources:
        for definition in normalized.bundle.semantic.definitions.values():
            code = CodeID.parse_key(definition.code_id or "")
            if not code or code.source.startswith("<"):
                continue
            path = Path(code.source).resolve()
            if not path.is_relative_to(root) or path.suffix != ".py":
                continue
            if path.is_file():
                selected.add(path)
            else:
                missing.append(str(path))
        if not selected:
            raise ValueError("no trace-referenced Python files within root; provide an explicit source file or disable runtime-sources")
        semantic = build_semantic_files(selected, root)
    else:
        semantic = build_semantic(source, project_root=project_root)
    source_seconds = time.perf_counter() - started - normalize_seconds
    joined = build_correspondence(semantic.graph, normalized.bundle)
    join_seconds = time.perf_counter() - started - normalize_seconds - source_seconds
    runtime = ingest_runtime_effects(normalized.bundle,
                                    namespace="effects:" + normalized.coverage["source_sha256"])
    engine = runtime.engine
    queries = [((definition,), scope) for definition, scope in sorted(
        engine.operations, key=lambda item: (item[1], item[0].wire))]
    summaries = engine.boundaries(queries)
    assessments, decisions, gap_counts, required_effects = [], Counter(), Counter(), set()
    for summary in summaries:
        scope = engine.scopes[summary.scope]
        policy = EffectPolicy("default-preserve:" + scope.id, scope.id, (), EvidenceClaim(
            EvidenceKind.DECLARED, ("scar:default-preserve-unlisted-effects",), scope=scope.id))
        decision = evaluate_removal(summary, policy, engine.semantic, mode=scope.mode)
        decisions[decision.disposition.value] += 1
        required_effects.update(decision.required_effects)
        for gap in summary.gaps:
            gap_counts[(gap.dimension.value if gap.dimension else "boundary", gap.reason)] += 1
        assessments.append({
            "roots": [identity.as_dict() for identity in queries[len(assessments)][0]],
            "members": [identity.as_dict() for identity in summary.members],
            "scope": scope.id,
            "effect_counts": dict(Counter(item.dimension.value for item in summary.occurrences)),
            "entry_reads": [item.as_dict() for item in summary.entry_reads],
            "outward_writes": [item.as_dict() for item in summary.outward_writes],
            "assessment": decision.to_dict(),
        })
    source_coverage = {key: value for key, value in semantic.coverage.items()
                       if key not in ("owners", "diagnostics")}
    source_coverage["diagnostic_counts"] = dict(Counter(
        item.get("kind", "unspecified") for item in semantic.coverage["diagnostics"]))
    return {
        "schema": "scar.inspection.v2", "schema_version": 1,
        "status": "Observed and Inferred; no transformation selected",
        "source": str(source), "project_root": str(root),
        "runtime_sources": runtime_sources, "missing_selected_sources": sorted(set(missing)),
        "source_coverage": source_coverage,
        "source_text_fingerprints": {module.path: module.fingerprint for module in semantic.graph.modules.values()
                                     if module.path and module.fingerprint},
        "trace_coverage": {key: value for key, value in normalized.coverage.items()
                           if key not in ("records",)},
        "correspondence": joined.report,
        "correspondence_graph": joined.graph.to_dict(),
        "runtime_effects": runtime.coverage,
        "scopes": [{"id": item.id, "mode": item.mode.value, "entry": item.entry,
                    "exit": item.exit, "closed": item.closed, "clock_domain": item.clock_domain}
                   for item in sorted(engine.scopes.values(), key=lambda item: item.id)],
        "assessments": assessments,
        "required_effect_evidence": {identity: encode(engine.occurrences[identity])
                                     for identity in sorted(required_effects)},
        "summary": {"region_queries": len(queries), "dispositions": dict(sorted(decisions.items())),
                    "effect_gaps": [{"dimension": key[0], "reason": key[1], "count": count}
                                    for key, count in sorted(gap_counts.items())],
                    "selected_transformations": 0,
                    "source_scope": source_coverage["selection_scope"]},
        "measurement": {"normalization_seconds": normalize_seconds,
                        "source_seconds": source_seconds, "join_seconds": join_seconds,
                        "total_analysis_seconds": time.perf_counter() - started,
                        "scope": "instrumented evidence analysis cost, not workload wall-clock speedup"},
        "limitations": [
            "Source matches certify code objects only, never globals, closure or effect equivalence.",
            "Effect removal is a diagnostic query; no reuse/hoist/delete candidate is selected here.",
            "Runtime scopes remain open; all-path consumer/alias closure needs independent evidence.",
            "Missing source/witness/collector facts produce scoped requests, never invented source identity.",
            "Source selection from runtime files omits unobserved branches/modules and is not whole-program coverage.",
        ],
    }


__all__ = ["inspect_program"]
