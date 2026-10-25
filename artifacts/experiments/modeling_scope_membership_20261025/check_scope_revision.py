"""Incremental scope-root and four-source freeze checks, metadata fixtures only."""
from dataclasses import replace
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

from scar.analysis.modeling_scope import InputResolver, _producer_paths
from scar.ir.modeling_scope import Axis, Coverage, CoverageGap, RequirementStatus, obligation_id
from scar.ir.modeling_scope_codec import dumps, loads
from scar.store.scope_partitions import publish_scope_ledger, ScopePartitions, SCHEMA

BASE = Path(__file__).resolve().parent
API = runpy.run_path(str(BASE / "check_small.py"))


def changed_source_reads(target):
    """Simulate changed source bytes without writing any production file."""
    original = Path.read_bytes
    def read(path):
        data = original(path)
        return data + b"\n# simulated producer revision\n" if path.resolve() == target else data
    return read


class ScopeRevisionChecks(unittest.TestCase):
    def test_prototype_v1_record_and_transport_are_explicitly_unsupported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scope = InputResolver(API["fixture"](root)).plan_scope()
            old_record = json.loads(dumps(scope))
            old_record["schema_version"] = 1
            old_record["record"].pop("policy_sources")
            with self.assertRaisesRegex(ValueError, "unsupported scope record schema/version"):
                loads(json.dumps(old_record))
            old_manifest = root / "prototype-v1.json"
            raw = API["raw_json"]({"schema": SCHEMA, "schema_version": 1, "status": "PUBLISHED"})
            old_manifest.write_bytes(raw)
            import hashlib
            with self.assertRaisesRegex(ValueError, "unsupported/unpublished ledger"):
                ScopePartitions(old_manifest, expected_sha256=hashlib.sha256(raw).hexdigest())

    def test_matched_new_inventory_and_report_change_revision_same_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = API["fixture"](root)
            before = InputResolver(catalog).plan_scope()
            manifest_path = root / "inventory/manifest.json"
            manifest = json.loads(manifest_path.read_bytes())
            manifest["snapshot_revision"] = "next-source-publication"
            API["write_json"](manifest_path, manifest)
            raw = manifest_path.read_bytes()
            import hashlib
            report_path = root / "calls/report.json"
            report = json.loads(report_path.read_bytes())
            report["inventory"] = {"path": str(manifest_path), "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "raw_bytes": len(raw), "decoded_bytes": len(raw)}
            API["write_json"](report_path, report)
            current = replace(catalog, source_inventory=API["input_file"](manifest_path),
                source_invocations=API["input_file"](report_path))
            resolver = InputResolver(current)
            after = resolver.plan_scope()
            self.assertEqual(after.id, before.id)
            self.assertEqual(after.run, before.run)
            self.assertNotEqual(after.revision, before.revision)
            anchors = {item.domain.value: item.sources for item in after.observability}
            self.assertEqual(anchors["SOURCE_DEFINITIONS"][0].artifact, resolver.inventory_artifact)
            self.assertEqual(anchors["OBSERVED_PYTHON_CALLS"][0].artifact, resolver.report_artifact)
            self.assertTrue(all(item.coverage is Coverage.UNKNOWN for item in after.observability))
            with self.assertRaisesRegex(ValueError, "scope revision does not match"):
                replace(after, observability=before.observability)
            # A report-only revision must be bound too, without conflating it
            # with a changed source inventory or changing the original Run.
            report["report_revision"] = "new-retained-associations"
            API["write_json"](report_path, report)
            third = InputResolver(replace(current, source_invocations=API["input_file"](report_path))).plan_scope()
            self.assertEqual(third.id, before.id)
            self.assertNotEqual(third.revision, after.revision)

    def test_optional_native_and_os_roots_change_revision_without_positive_claims(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = API["fixture"](root)
            before = InputResolver(catalog).plan_scope()
            native = root / "native-manifest.json"
            native_doc = {"schema": "scar.partitioned-ir-bundle", "schema_version": 1,
                "graphs": {"evidence": {"tables": {"instances": {"records": 7}}},
                           "values": {"tables": {k: {"records": 2} for k in ("objects", "allocations", "regions")}}}}
            API["write_json"](native, native_doc)
            with_native = replace(catalog, native_bundle=API["input_file"](native))
            first = InputResolver(with_native).plan_scope()
            self.assertNotEqual(first.revision, before.revision)
            native_doc["graphs"]["evidence"]["tables"]["instances"]["records"] = 8
            API["write_json"](native, native_doc)
            with_native = replace(with_native, native_bundle=API["input_file"](native))
            second = InputResolver(with_native).plan_scope()
            self.assertEqual(first.id, second.id)
            self.assertNotEqual(first.revision, second.revision)
            os_path = root / "os-manifest.json"
            coords = json.loads((root / "coordinates.json").read_bytes())
            os_doc = {"schema": "scar.partitioned-os-resource-fragment", "schema_version": 1,
                "run": coords["run"], "tables": {k: {"records": 1} for k in
                    ("resources", "handles", "target_lifetime_events", "processes", "threads", "observations")}}
            API["write_json"](os_path, os_doc)
            with_os = replace(with_native, os_fragment=API["input_file"](os_path))
            third = InputResolver(with_os).plan_scope()
            self.assertNotEqual(second.revision, third.revision)
            os_doc["tables"]["resources"]["records"] = 2
            API["write_json"](os_path, os_doc)
            fourth = InputResolver(replace(with_os, os_fragment=API["input_file"](os_path))).plan_scope()
            self.assertNotEqual(third.revision, fourth.revision)
            self.assertTrue(all(item.coverage is Coverage.UNKNOWN and item.gaps for item in fourth.observability))

    def test_each_producer_changes_revision_and_mid_scan_change_is_rejected(self):
        for i, target in enumerate(_producer_paths()):
            with self.subTest(producer=str(target)):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    catalog = API["fixture"](root)
                    resolver = InputResolver(catalog)
                    before = resolver.plan_scope()
                    self.assertEqual(len(before.policy_sources), 4)
                    with patch.object(Path, "read_bytes", changed_source_reads(target)):
                        changed = InputResolver(catalog).plan_scope()
                        self.assertEqual(changed.id, before.id)
                        self.assertNotEqual(changed.revision, before.revision)
                        with self.assertRaisesRegex(ValueError, "producer source changed during owned scan"):
                            publish_scope_ledger(before, resolver.rows(before), str(root / ("failed-" + str(i))), resolver=resolver)
                    self.assertFalse((root / ("failed-" + str(i)) / "manifest.json").exists())

    def test_assessment_change_does_not_change_obligation_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resolver = InputResolver(API["fixture"](root))
            scope = resolver.plan_scope()
            resolver.begin_publication(scope)
            rows = resolver.rows(scope)
            original = next(rows)
            axis = original.assessment.axes[0]
            self.assertIs(axis.axis, Axis.STRUCTURAL_ATTRIBUTION)
            result = replace(axis.results[0], status=RequirementStatus.OPEN,
                gaps=(CoverageGap("INDEPENDENT_REVIEW_PENDING", axis.results[0].key,
                    original.obligation.subject.record, "Assessment changed without rewriting the original subject"),))
            assessment = replace(original.assessment, axes=(replace(axis, results=(result,)), *original.assessment.axes[1:]))
            changed = replace(original, assessment=assessment)
            self.assertEqual(changed.obligation.id, original.obligation.id)
            self.assertEqual(obligation_id(changed.obligation.subject, changed.obligation.rule_key), original.obligation.id)
            self.assertEqual(changed.obligation.scope_revision, scope.revision)
            rows.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
