"""One real offline dependency admission; does not run target or GPU work."""
import json
import os
from pathlib import Path

from scar.analysis.dependency_sources import DependencySourceBudget, admit_dependency_sources
from scar.ir.program.call_edges import CallEdgeBudget
from scar.ir.program.expansion import ContextStoreBudget


root = Path(__file__).resolve().parent
(root / "pid.txt").write_text(str(os.getpid()) + "\n")
with (root / "progress.jsonl").open("x") as progress:
    def emit(row):
        progress.write(json.dumps(row, ensure_ascii=False) + "\n")
        progress.flush()

    report = admit_dependency_sources(
        "/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_lewm_dispatch_20261023/trace",
        "/home/zyf/AAA/le-wm", root / "result",
        call_budget=CallEdgeBudget(max_raw_bytes=256_000_000, max_lines=300_000,
            max_events=250_000, max_references=2_000_000,
            max_source_files=256, max_source_bytes=16_000_000),
        budget=DependencySourceBudget(max_archive_bytes=1_500_000_000,
            max_archive_record_bytes=256_000_000, max_report_bytes=64_000_000),
        context_budget=ContextStoreBudget(max_compressed_bytes=512_000_000,
                                         max_record_bytes=128_000_000),
        progress=emit,
    )
print(json.dumps({"summary": report["summary"], "measurements": report["measurements"],
                  "target_executed": False, "first_stage_complete": False}, ensure_ascii=False))
