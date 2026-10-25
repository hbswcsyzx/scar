"""Incremental current-snapshot prerequisite checks; no real headers or raw."""
from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import unittest

from scar.analysis.modeling_scope import InputResolver
from scar.ir.modeling_scope import Encoding

BASE = Path(__file__).resolve().parent
API = runpy.run_path(str(BASE / "check_small.py"))


class CurrentInventoryChecks(unittest.TestCase):
    def test_same_run_prior_inventory_is_rejected_before_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = API["fixture"](root)
            report_path = root / "calls/report.json"
            original = json.loads(report_path.read_bytes())
            # The report still binds the prior bytes at the same original URI;
            # new manifest bytes are a different snapshot even in this Run.
            manifest_path = root / "inventory/manifest.json"
            manifest = json.loads(manifest_path.read_bytes())
            manifest["snapshot_revision"] = "new-publication"
            API["write_json"](manifest_path, manifest)
            catalog = replace(catalog, source_inventory=API["input_file"](manifest_path))
            (root / "calls/invocations.jsonl.gz").unlink()
            with self.assertRaisesRegex(ValueError, "current inventory receipt differs"):
                InputResolver(catalog)
            self.assertEqual(json.loads(report_path.read_bytes()), original)

    def test_uri_types_missing_fields_and_unsupported_old_profile(self):
        mutations = (
            lambda r: r["inventory"].update(path="/other-original-namespace/same-bytes.json"),
            lambda r: r["inventory"].update(raw_bytes=True),
            lambda r: r["inventory"].pop("decoded_bytes"),
            lambda r: r.pop("inventory"),
            lambda r: r["inventory"].update(decoded_sha256="0" * 64),
            lambda r: r.update(schema_version=1),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    catalog = API["fixture"](root)
                    path = root / "calls/report.json"
                    report = json.loads(path.read_bytes()); mutate(report)
                    API["write_json"](path, report)
                    catalog = replace(catalog, source_invocations=API["input_file"](path))
                    (root / "calls/invocations.jsonl.gz").unlink()
                    with self.assertRaises(ValueError):
                        InputResolver(catalog)

    def test_gzip_physical_receipt_and_separate_compiler_origin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = API["fixture"](root)
            source = root / "inventory/manifest.json"
            decoded = source.read_bytes()
            zipped = root / "inventory/manifest.json.gz"
            zipped.write_bytes(gzip.compress(decoded, mtime=0))
            path = root / "calls/report.json"
            report = json.loads(path.read_bytes())
            prior = dict(report["inventory"])
            report["inventory"] = {"path": str(zipped),
                "raw_sha256": hashlib.sha256(zipped.read_bytes()).hexdigest(),
                "raw_bytes": zipped.stat().st_size, "decoded_bytes": len(decoded)}
            # An older compiler origin is deliberately different and is not the
            # current inventory prerequisite. This adapter does not reuse it.
            report["code_source_origin"] = {"inventory": prior}
            API["write_json"](path, report)
            catalog = replace(catalog, source_inventory=API["input_file"](zipped, Encoding.GZIP_JSON),
                source_invocations=API["input_file"](path))
            resolver = InputResolver(catalog)
            self.assertEqual(resolver.inventory.manifest_receipt["decoded_sha256"], hashlib.sha256(decoded).hexdigest())
            report["inventory"]["raw_sha256"] = hashlib.sha256(decoded).hexdigest()
            API["write_json"](path, report)
            with self.assertRaisesRegex(ValueError, "current inventory receipt differs"):
                InputResolver(replace(catalog, source_invocations=API["input_file"](path)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
