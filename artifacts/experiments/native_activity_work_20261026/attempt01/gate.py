"""Root-run, one full native-activity acquisition; no target or Torch import."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
import traceback


HERE = Path(__file__).resolve().parent
TREE = HERE.parents[3]


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def write(name, value):
    with (HERE / name).open("xb") as stream:
        stream.write(canonical(value))


def main():
    started = time.monotonic()
    freeze_bytes = (HERE / "freeze.json").read_bytes()
    freeze = json.loads(freeze_bytes)
    source_hash_bytes, control_hash_bytes = 0, 0

    def verify():
        nonlocal source_hash_bytes, control_hash_bytes
        for family in ("sources", "runners", "controls"):
            for row in freeze[family]:
                p = Path(row["path"]); b = p.read_bytes()
                if family == "controls":
                    control_hash_bytes += len(b)
                else:
                    source_hash_bytes += len(b)
                if len(b) != row["bytes"] or sha256(b).hexdigest() != row["sha256"]:
                    raise ValueError("frozen source/control changed: " + str(p))
        if source_hash_bytes > 64_000_000 or control_hash_bytes > 16_000_000:
            raise ValueError("independent source/control hash budget exceeded")

    try:
        verify()
        for row in freeze["declared_bulk_inputs"]:
            p = Path(row["path"])
            if p.is_symlink() or p.stat().st_size != row["stored_bytes"]:
                raise ValueError("declared bulk input stat differs: " + str(p))
        # This imports the live frozen tree; no previous artifact runner is used.
        from scar.trace.native_work_bridge import acquire_native_activity_work, NativeWorkBudget
        from scar.ir.execution.native_work_protocol import NativeActivityWorkEvidence
        negative = None

        def on_verified(evidence, work, bindings, quiet, payload):
            nonlocal negative
            if negative is not None or len(bindings) < 2:
                return
            if type(evidence) is not NativeActivityWorkEvidence:
                raise ValueError("unexpected owned source evidence API")
            # Both producers are real, same-Run, same projection occurrences.
            candidate = (replace(bindings[0], instance=bindings[1].instance), *bindings[1:])
            try:
                evidence.check_fragment(work, candidate, quiet, payload)
            except ValueError as error:
                message = str(error)
                if message != "native work binding producer/artifact/source differs":
                    raise
                negative = {"status": "REJECTED", "kind": "actual_same_run_wrong_producer",
                    "changed": "binding[0].instance = binding[1].instance",
                    "original": bindings[0].instance.value, "replacement": bindings[1].instance.value,
                    "independent_semantic_rejection": True, "seal_rejection": False, "error": message}
                write("negative.json", negative)
            else:
                raise ValueError("independent native checker accepted wrong actual producer")

        report = acquire_native_activity_work(freeze["capture"], freeze["partitions"], HERE / "result",
            budgets=NativeWorkBudget(**freeze["runtime_budget"]), on_verified_shard=on_verified)
        if negative is None:
            raise ValueError("BLOCKED: no two real qualified producers for the sole negative")
        verify()
        pins = {Path(row["path"]).resolve(): row for row in freeze["sources"]}
        imported = []
        for name, module in sorted(sys.modules.items()):
            if name != "scar" and not name.startswith("scar."):
                continue
            file = getattr(module, "__file__", None)
            if file is None:
                continue
            path = Path(file).resolve()
            if path.suffix != ".py" or not path.is_relative_to(TREE):
                raise ValueError("SCAR import escaped the frozen source tree: " + str(path))
            row = pins.get(path)
            if row is None:
                raise ValueError("actually imported SCAR source is not frozen: " + str(path))
            b = path.read_bytes(); source_hash_bytes += len(b)
            if sha256(b).hexdigest() != row["sha256"] or len(b) != row["bytes"]:
                raise ValueError("actually imported source differs from its freeze")
            imported.append({"module": name, **row})
        if source_hash_bytes > 64_000_000:
            raise ValueError("source hash/read budget exceeded")
        if "torch" in sys.modules:
            raise ValueError("resource acquisition unexpectedly imported Torch")
        write("imports.json", {"source_tree": str(TREE), "imported": imported,
            "torch_imported": False, "source_hash_bytes": source_hash_bytes,
            "control_hash_bytes": control_hash_bytes})
        result = {"status": "PASS_WITH_OPEN", "producer": report, "negative": negative,
            "freeze_sha256": sha256(freeze_bytes).hexdigest(), "freeze_bytes": len(freeze_bytes),
            "whole_elapsed_s": time.monotonic() - started,
            "source_hash_bytes": source_hash_bytes, "control_hash_bytes": control_hash_bytes,
            "actual_imported_modules": len(imported), "target_executions": 0,
            "execution_model_created": False, "program_snapshot_attachment": "UNATTACHED_TO_PROGRAM_SNAPSHOT",
            "resource_readiness_established": False, "whole_model_established": False}
        write("result.json", result)
        print(json.dumps({key: result[key] for key in ("status", "whole_elapsed_s", "actual_imported_modules")}))
        return 0
    except BaseException as error:
        write("failure.json", {"status": "FAILED", "error_type": type(error).__name__, "error": str(error),
            "traceback": traceback.format_exc(), "whole_elapsed_s": time.monotonic() - started,
            "source_hash_bytes": source_hash_bytes, "control_hash_bytes": control_hash_bytes,
            "whole_model_established": False})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
