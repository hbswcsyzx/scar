"""Prepared real-artifact runner. Requires root authorization before --read-inputs.

No capture/target/raw replay. Catalog roots bind exact existing receipts. Without
--read-inputs this prints planned hard budgets only and does not open inputs.
"""
import argparse
import json
from pathlib import Path
import resource
import time

from scar.analysis.modeling_scope import InputArtifact, InputCatalog, InputBudgets, produce_scope_ledger
from scar.ir.record_codec import decode, loads
from scar.store.scope_partitions import ScopeBudgets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True, help="small fixed typed input catalog JSON")
    parser.add_argument("--out", required=True, help="fresh output directory")
    parser.add_argument("--read-inputs", action="store_true", help="only use after root authorizes the actual retained-artifact scan")
    args = parser.parse_args()
    input_budget = InputBudgets(max_seconds=1800)
    output_budget = ScopeBudgets(max_decoded_bytes=8_000_000_000, max_seconds=1800)
    if not args.read_inputs:
        print(json.dumps({"status": "PREPARED_NOT_RUN", "catalog": args.catalog, "out": args.out,
            "input_budgets": input_budget.__dict__, "storage_budgets": output_budget.__dict__,
            "raw_replay": "NONE", "target_executions": 0}, sort_keys=True))
        return
    catalog_path = Path(args.catalog)
    if catalog_path.stat().st_size > 65536:
        raise ValueError("catalog metadata exceeds64KiB")
    document = loads(catalog_path.read_text())
    if (type(document) is not dict or set(document) != {"schema", "schema_version", "catalog"}
            or document["schema"] != "scar.modeling-scope-input-catalog"
            or type(document["schema_version"]) is not int or document["schema_version"] != 1):
        raise ValueError("input catalog schema/fields differ")
    catalog = decode(InputCatalog, document["catalog"])
    start = time.monotonic()
    result = produce_scope_ledger(catalog, args.out, input_budgets=input_budget, storage_budgets=output_budget)
    print(json.dumps({"status": "PUBLISHED_OPEN", "receipt": result,
        "wall_seconds": time.monotonic() - start, "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "target_executions": 0, "raw_replay": "NONE"}, sort_keys=True))


if __name__ == "__main__":
    main()
