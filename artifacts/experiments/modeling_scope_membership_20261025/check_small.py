"""Necessary small API/codec/query negative cases; no target or real archive."""
import gzip
import hashlib
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from scar.analysis.modeling_scope import InputArtifact, InputCatalog, InputResolver, produce_scope_ledger
from scar.ir.execution.common import EvidencePoint
from scar.ir.execution.coordinates import ExecutionRun, ProcessInstance
from scar.ir.execution.ids import RunID, ProcessInstanceID
from scar.ir.modeling_scope import Axis, Domain, Encoding, Enumeration, RequirementStatus, obligation_id
from scar.ir.modeling_scope_codec import dumps, loads
from scar.ir.program.call_edges import InvocationKey, CallRecordAnchor
from scar.ir.program.inventory import DefinitionInventory, DefinitionKind, SourceContextDigest
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import encode
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID, SourceAtomID
from scar.store.scope_partitions import ScopeBudgets, ScopePartitions, publish_scope_ledger


def raw_json(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def write_json(path, value, *, compress=False):
    raw = raw_json(value)
    stored = gzip.compress(raw, mtime=0) if compress else raw
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(stored)
    return {"uri": str(path), "external": True,
        "physical_sha256": hashlib.sha256(stored).hexdigest(), "physical_bytes": len(stored),
        "decoded_sha256": hashlib.sha256(raw).hexdigest(), "decoded_bytes": len(raw),
        "representation": value["schema"] + "/" + str(value["schema_version"])}


def input_file(path, encoding=Encoding.JSON):
    raw = path.read_bytes()
    return InputArtifact(str(path), hashlib.sha256(raw).hexdigest(), len(raw), encoding)


def fixture(root, *, wrong_run=False, duplicate_call=False):
    """Only retained inventory/call metadata; deliberately no hand-written IR."""
    project = root / "project"; project.mkdir()
    source = project / "fixture.py"
    source.write_text("# source snapshot only; not imported or executed\n")
    fingerprint = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    snapshot = SourceSnapshot(str(source), fingerprint)
    context = SourceContextDigest(str(project), "1" * 64, "2" * 64, "3" * 64)
    definitions = []
    for i in range(5):
        reference = SourceReference(SourceAtomID("source-" + str(i)), str(source), fingerprint, 1, 1)
        definitions.append(DefinitionInventory(OperationDefinitionID("definition-" + str(i)), reference,
            "function_" + str(i), "function_" + str(i), DefinitionKind.FUNCTION, None))
    inventory = root / "inventory"; inventory.mkdir()
    header = write_json(inventory / "header.json", {"schema": "scar.inventory-component", "schema_version": 1,
        "name": "header", "value": {"summary": {"definitions": 5, "coverage_atoms": 11}}})
    shard = write_json(inventory / "source.json.gz", {"schema": "scar.partitioned-file-inventory", "schema_version": 1,
        "file_index": 0, "file": {"snapshot": encode(snapshot), "context": encode(context),
        "definitions": encode(tuple(definitions)), "bodies": [
            {"definition": encode(definitions[0].id), "status": "UNSUPPORTED", "reason": "", "checkpoint": None},
            {"definition": encode(definitions[1].id), "status": "NOT_ATTEMPTED", "reason": "Original queue retained", "checkpoint": None}],
        "coverage": [], "calls": [], "implicit_invocations": []}}, compress=True)
    write_json(inventory / "manifest.json", {"schema": "scar.partitioned-program-inventory", "schema_version": 1,
        "files": [shard], "components": {"header": header}, "counts": {"source_files": 1},
        "whole_program_graph_established": False, "transformation_authorized": False})
    seed_path = root / "seed.json"; seed_path.write_bytes(b'{"origin":"small fixture"}\n')
    seed = ProviderArtifact(str(seed_path), hashlib.sha256(seed_path.read_bytes()).hexdigest(), seed_path.stat().st_size, "fixture.source")
    fact = ProviderFactReference(seed, "#")
    run = ExecutionRun(RunID("small-fixture-run"), fact)
    process = ProcessInstance(ProcessInstanceID("small-fixture-process"), run.id, 7, fact)
    coord_path = root / "coordinates.json"
    write_json(coord_path, {"schema": "scar.capture-coordinates", "schema_version": 1, "run": encode(run),
        "processes": encode((process,)), "membership": [{"artifact": encode(seed)}],
        "seed": {"command_sha256": seed.sha256}, "dispatch_collector_declaration": {"dispatch_attempts": 7}})
    coord_raw = coord_path.read_bytes()
    coord = ProviderArtifact(str(coord_path), hashlib.sha256(coord_raw).hexdigest(), len(coord_raw), "scar.capture-coordinates")
    calls = root / "calls"; calls.mkdir()
    rows = []
    for i in range(3):
        invocation = InvocationKey(7, 10, 1 if duplicate_call else i + 1)
        anchor = CallRecordAnchor(str(seed_path), 1, seed.sha256, i)
        point = EvidencePoint(RunID("wrong-run") if wrong_run else run.id, process.id, fact)
        rows.append({"kind": "INVOCATION", "invocation": encode(invocation), "anchor": encode(anchor),
            "point": encode(point), "status": "UNRESOLVED", "frontiers": ["NO_CANONICAL_BODY"],
            "region_activation": None})
    payload = b"".join(raw_json(row) for row in rows)
    (calls / "invocations.jsonl.gz").write_bytes(gzip.compress(payload, mtime=0))
    inventory_raw = (inventory / "manifest.json").read_bytes()
    write_json(calls / "report.json", {"schema": "scar.source-invocations", "schema_version": 3,
        "inventory": {"path": str(inventory / "manifest.json"),
            "raw_sha256": hashlib.sha256(inventory_raw).hexdigest(),
            "raw_bytes": len(inventory_raw), "decoded_bytes": len(inventory_raw)},
        "run": encode(run), "coordinate_binding": encode(coord), "summary": {"invocations": 3},
        "invocations": {"path": "invocations.jsonl.gz", "rows": 3, "raw_bytes": len(payload),
                        "raw_sha256": hashlib.sha256(payload).hexdigest()},
        "orphan_exits": {"rows": 0}})
    contract = root / "contract.md"; contract.write_text("# Original acceptance contract fixture\n")
    return InputCatalog(input_file(coord_path), input_file(inventory / "manifest.json"),
        input_file(calls / "report.json"), input_file(contract, Encoding.TEXT))


class SmallScopeChecks(unittest.TestCase):
    def test_codec_query_and_independent_open_debts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = fixture(root)
            output = root / "ledger"
            limits = ScopeBudgets(max_chunk_rows=2)
            receipt = produce_scope_ledger(catalog, str(output), storage_budgets=limits)
            reader = ScopePartitions(output / "manifest.json", expected_sha256=receipt["manifest"]["sha256"], budgets=limits)
            self.assertEqual(receipt["counts"]["members"], 8)
            self.assertEqual(receipt["counts"]["obligations"], 14)
            self.assertEqual(receipt["aggregate"], "OPEN")
            denoms = {loads(json.dumps(d)).domain: loads(json.dumps(d)) for d in reader.manifest["denominators"]}
            self.assertEqual((denoms[Domain.SOURCE_DEFINITIONS].declared_count, denoms[Domain.SOURCE_DEFINITIONS].enumerated_count), (5, 5))
            self.assertEqual(denoms[Domain.OBSERVED_PYTHON_CALLS].enumeration, Enumeration.ENUMERATED)
            dispatch = denoms[Domain.DISPATCH_ATTEMPTS]
            self.assertEqual((dispatch.declared_count, dispatch.enumerated_count), (7, 0))
            self.assertTrue(any(g.missing_count == 7 for g in dispatch.gaps))
            self.assertIsNone(denoms[Domain.OS_RESOURCES].declared_count)
            self.assertIsNotNone(denoms[Domain.OS_RESOURCES].cursor)
            index = [json.loads(x) for x in reader._chunk(reader.manifest["index"][0])]
            identity = index[0]["id"]
            entry = reader.query(identity, scope_revision=reader.scope.revision)
            self.assertEqual(loads(dumps(entry)), entry)
            self.assertEqual(reader.last_query["data_chunks_read"], 1)
            self.assertEqual(reader.last_query["index_chunks_read"], 1)
            self.assertFalse(reader.last_query["raw_replayed"])
            subject = entry.obligation.subject
            same_bytes_other_origin = replace(subject, record=replace(subject.record, artifact=replace(subject.record.artifact,
                original=replace(subject.record.artifact.original, uri="/another-original-namespace/same-bytes"))))
            self.assertEqual(same_bytes_other_origin.scope_id, subject.scope_id)
            self.assertEqual(same_bytes_other_origin.record.artifact.decoded_sha256, subject.record.artifact.decoded_sha256)
            self.assertNotEqual(obligation_id(same_bytes_other_origin, entry.obligation.rule_key), entry.obligation.id)
            for axis in entry.assessment.axes:
                if axis.axis is not Axis.STRUCTURAL_ATTRIBUTION:
                    self.assertTrue(all(r.status is RequirementStatus.OPEN and r.gaps for r in axis.results))
            with self.assertRaises(ValueError):
                reader.query(identity, scope_revision="scope_revision:" + "0" * 64)
            document = json.loads(dumps(entry))
            for mutate in (
                lambda d: d.update(schema_version=True),
                lambda d: d["record"].update(unknown="field"),
                lambda d: d["record"].update({"$ledger_record": "QualifiedEntitySubject"}),
                lambda d: d["record"]["obligation"]["subject"]["record"]["artifact"].update(decoded_bytes=True),
                lambda d: d["record"]["assessment"]["axes"][1]["results"][0].update(status="SATISFIED", gaps=[]),
            ):
                d = json.loads(json.dumps(document)); mutate(d)
                with self.assertRaises(ValueError):
                    loads(json.dumps(d))
            with self.assertRaises(ValueError):
                loads('{"schema":"one","schema":"two"}')
            desc = reader.manifest["entries"][index[0]["chunk"]]
            chunk = output / desc["uri"]
            raw = chunk.read_bytes(); chunk.write_bytes(raw[:-1] + bytes((raw[-1] ^ 1,)))
            with self.assertRaises(ValueError):
                reader.query(identity, scope_revision=reader.scope.revision)

    def test_wrong_run_duplicate_invocation_and_interrupt(self):
        for flags in ({"wrong_run": True}, {"duplicate_call": True}, {}):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                catalog = fixture(root, **flags)
                output = root / "ledger"
                limits = ScopeBudgets(max_entries=2) if not flags else ScopeBudgets()
                with self.assertRaises(ValueError):
                    produce_scope_ledger(catalog, str(output), storage_budgets=limits)
                self.assertTrue((output / "BUILDING.json").is_file())
                self.assertTrue((output / "FAILED.json").is_file())
                self.assertFalse((output / "manifest.json").exists())

    def test_owned_scan_refuses_changed_mandatory_and_unpublished_batch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = fixture(root)
            with self.assertRaises(ValueError):
                replace(catalog, native_capture_batch=catalog.coordinates)
            resolver = InputResolver(catalog)
            scope = resolver.plan_scope()
            def changed_rows():
                for row in resolver.rows(scope):
                    if hasattr(row, "obligation"):
                        yield replace(row, obligation=replace(row.obligation, mandatory=False))
                    else:
                        yield row
            output = root / "changed"
            with self.assertRaises(ValueError):
                publish_scope_ledger(scope, changed_rows(), str(output), resolver=resolver)
            self.assertFalse((output / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
