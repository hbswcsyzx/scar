"""One authorized offline continuation; no target/GPU execution or tests."""
import json
import os
from pathlib import Path

from scar.analysis.dependency_continuation import (
    DependencyContinuationBudget, continue_dependency_sources,
)
from scar.ir.program.call_edges import CallEdgeBudget
from scar.ir.program.expansion import ContextStoreBudget


root = Path(__file__).resolve().parent
(root / "pid.txt").write_text(str(os.getpid()) + "\n")
with (root / "progress.jsonl").open("x") as progress:
    def emit(row):
        progress.write(json.dumps(row, ensure_ascii=False) + "\n")
        progress.flush()

    report = continue_dependency_sources(
        "/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_lewm_dispatch_20261023/trace",
        "/home/zyf/AAA/le-wm",
        "/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_dependency_sources_20261023/result",
        root / "result",
        expected_parent_report_sha256="fc97075aa66a92758938ad8416347d895e6b18ef0e454053fc7f9c1a7d2f0424",
        call_budget=CallEdgeBudget(max_raw_bytes=256_000_000, max_lines=300_000,
            max_events=250_000, max_references=2_000_000,
            max_source_files=256, max_source_bytes=16_000_000),
        budget=DependencyContinuationBudget(),
        context_budget=ContextStoreBudget(max_compressed_bytes=512_000_000,
                                         max_record_bytes=128_000_000),
        progress=emit,
    )
print(json.dumps({"summary": report["summary"], "measurements": report["measurements"],
                  "target_executed": False, "first_stage_complete": False}, ensure_ascii=False))
