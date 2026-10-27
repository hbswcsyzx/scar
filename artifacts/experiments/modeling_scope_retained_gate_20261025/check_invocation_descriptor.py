"""Current public five-field header/stat contract; never opens invocation body."""
from dataclasses import replace
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

from scar.analysis.modeling_scope import InputBudgets, InputResolver

BASE = Path(__file__).resolve().parent
API = runpy.run_path(str(BASE / "check_small.py"))


def prohibit_body(target):
    original = Path.open
    def opened(path, *args, **kwargs):
        if path.resolve() == target:
            raise AssertionError("invocation body must not be opened by header check")
        return original(path, *args, **kwargs)
    return opened


class InvocationDescriptorChecks(unittest.TestCase):
    def test_current_five_fields_stat_without_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = API["fixture"](root)
            target = root / "calls/invocations.jsonl.gz"
            with patch.object(Path, "open", prohibit_body(target)):
                resolver = InputResolver(catalog)
                declaration, actual = resolver._invocation_file()
                self.assertEqual(actual, target)
                self.assertEqual(declaration["compressed_bytes"], target.stat().st_size)
                self.assertFalse(resolver._calls_verified)

    def test_missing_unknown_wrong_type_or_stat_is_rejected_without_body(self):
        mutations = (
            lambda d: d.pop("compressed_bytes"),
            lambda d: d.update(verified=True),
            lambda d: d.update(compressed_bytes=True),
            lambda d: d.update(compressed_bytes=d["compressed_bytes"] + 1),
        )
        for mutate in mutations:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                catalog = API["fixture"](root)
                report_path = root / "calls/report.json"
                report = json.loads(report_path.read_bytes())
                mutate(report["invocations"])
                API["write_json"](report_path, report)
                catalog = replace(catalog, source_invocations=API["input_file"](report_path))
                with patch.object(Path, "open", prohibit_body(root / "calls/invocations.jsonl.gz")):
                    with self.assertRaises(ValueError):
                        InputResolver(catalog)

    def test_stored_and_decoded_budgets_are_checked_without_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = API["fixture"](root)
            report = json.loads((root / "calls/report.json").read_bytes())
            for budgets in (
                InputBudgets(max_calls_stored_bytes=report["invocations"]["compressed_bytes"] - 1),
                InputBudgets(max_calls_decoded_bytes=report["invocations"]["raw_bytes"] - 1),
            ):
                with patch.object(Path, "open", prohibit_body(root / "calls/invocations.jsonl.gz")):
                    with self.assertRaises(ValueError):
                        InputResolver(catalog, budgets=budgets)


if __name__ == "__main__":
    unittest.main(verbosity=2)
