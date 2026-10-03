"""Public nonexecuting report: conditional value paths, not import deletion."""
from collections import Counter
import time

from scar.ir.frontend_v2 import build_semantic
from .constants_v2 import EvaluationBudget
from .import_values_v2 import resolve_import_values
from .source_semantics_v2 import extract_source_semantics, validate_source_semantics


def report_import_values(source, *, project_root=None, budget=EvaluationBudget()):
    started = time.perf_counter()
    frontend = build_semantic(source, project_root=project_root)
    model = extract_source_semantics(frontend.graph)
    replay = validate_source_semantics(model, frontend.graph)
    if not replay["valid"]:
        raise ValueError("source replay failed: " + "; ".join(replay["errors"]))
    paths = resolve_import_values(frontend.graph, model, budget=budget)
    summary = paths.summary()
    summary.update({
        "files": len(model.sources), "semantic_boundaries": len(model.boundaries),
        "conditional_binding_uses": sum(bool(use.conditional_reaching) for use in model.uses.values()),
        "boundary_kinds": dict(sorted(Counter(item.kind.value for item in model.boundaries).items())),
        "selected_transformations": 0, "applied": False,
    })
    return {
        "schema": "scar.import-values-report", "schema_version": 1,
        "input": str(source), "status": "Inferred",
        "scope": "Selected local source files; import resolution and immutable value paths remain conditional on explicit loader, namespace and runtime contracts.",
        "file_selection": {"mode": "PROJECT_TREE" if project_root is not None else "SOURCE_INPUT",
                           "paths": sorted(model.sources), "import_reachability_proven": False},
        "source_replay": {**replay, "scope": "Current matching source text only; no target execution or import initialization observed."},
        "semantic": frontend.graph.to_dict(), "model": model.to_dict(),
        "import_values": paths.to_dict(verification_budget=budget), "summary": summary,
        "decision": {"selection_status": "NOT_SELECTED", "cost_status": "PENDING",
                     "applied": False, "import_deletion": "NOT_PROVEN"},
        "measurement": {"analysis_seconds": time.perf_counter() - started,
                        "scope": "SCAR source analysis, not workload execution or speedup"},
    }


__all__ = ["report_import_values"]
