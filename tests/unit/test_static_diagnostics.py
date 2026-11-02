"""Metadata compaction retains unique diagnostics and original graph authority."""
import copy
import gzip
import hashlib
import json

import pytest

from scar.analysis.static_calls import input_basis_unit
from scar.analysis.static_diagnostics import body_diagnostics, compact_static_diagnostics
from scar.analysis.static_program import _json, _read_fragment, _write


def test_diagnostics_inline_refs_and_atomic_failure_preserve_original_details(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    artifacts = {name: _write(model, "source/" + name + ".json.gz", {"schema": "original-" + name})
                 for name in ("source", "semantic", "semantics", "control")}
    inputs = {name: artifacts[name] for name in artifacts}
    rows = []
    for index in range(2):
        gaps = [{"kind": "SOURCE_RULE_OPEN", "detail": "original body diagnostic " * 20, "ordinal": index}]
        payload = {"schema": "scar.static-body", "schema_version": 1, "entry_key": "entry-" + str(index),
                   "cache_key": "original-key-" + str(index), "status": "UNSUPPORTED", "inputs": inputs,
                   "graph": None, "metadata": {"gaps": gaps}, "gaps": gaps}
        if index == 0:
            payload.update(module_frontiers=[{"kind": "ORIGINAL_MODULE_BOUNDARY"}],
                           class_frontiers=[{"kind": "ORIGINAL_CLASS_BOUNDARY"}])
        descriptor = _write(model, "units/body-" + str(index) + ".json.gz", payload)
        row = {name: payload[name] for name in ("entry_key", "cache_key", "status", "gaps")}
        row.update(kind="FUNCTION", source={"original_source": index}, definitions=["original-definition-" + str(index)], artifact=descriptor)
        if index == 0:
            row.update({field: payload[field] for field in ("module_frontiers", "class_frontiers")})
        else:
            row["gaps"] = [{"kind": "LEDGER_ONLY_INFORMATION", "detail": "must remain inline"}]
        rows.append(row)
    rows.append({"entry_key": "unbacked", "kind": "FUNCTION", "status": "ERROR", "gaps": [{"detail": "unique worker failure"}]})
    unit = {"key": "original-unit", "path": str(tmp_path / "application.py"), "namespace_root": str(tmp_path),
            "decoded_sha256": "a" * 64, "artifacts": artifacts, "bodies": rows}
    manifest = {"schema": "scar.static-program", "schema_version": 1, "units": [unit]}
    path = model / "manifest.json"
    path.write_bytes(_json(manifest))
    before_basis = input_basis_unit(unit)
    before_fragments = {str(p): p.read_bytes() for p in model.rglob("*.gz")}
    original_details = body_diagnostics(rows[0], lambda descriptor: _read_fragment(model, descriptor), unit=unit)
    result = compact_static_diagnostics(model, jobs=1)
    assert result["bodies_verified"] == 2 and result["bodies_changed"] == 1
    assert result["fields_compacted"] == {"gaps": 1, "module_frontiers": 1, "class_frontiers": 1}
    assert {row["reason"] for row in result["retained"]} == {"ORIGINAL_ARTIFACT_VALUE_DIFFERS", "ORIGINAL_BODY_ARTIFACT_UNAVAILABLE"}
    after = json.loads(path.read_bytes())
    assert input_basis_unit(after["units"][0]) == before_basis
    new_rows = after["units"][0]["bodies"]
    assert all(field not in new_rows[0] for field in original_details)
    assert body_diagnostics(new_rows[0], lambda d: _read_fragment(model, d), unit=after["units"][0]) == original_details
    assert new_rows[1]["gaps"] == rows[1]["gaps"] and new_rows[2]["gaps"] == rows[2]["gaps"]
    assert before_fragments == {str(p): p.read_bytes() for p in model.rglob("*.gz")}
    wrong_count = copy.deepcopy(new_rows[0])
    wrong_count["diagnostics"]["gaps"]["count"] += 1
    with pytest.raises(ValueError, match="count/field"):
        body_diagnostics(wrong_count, lambda d: _read_fragment(model, d), unit=after["units"][0])
    unchanged = path.read_bytes()
    assert compact_static_diagnostics(model, jobs=1)["status"] == "UNCHANGED"
    assert path.read_bytes() == unchanged
    # The still-inline unique record makes this artifact a compaction input.
    # A corrupt receipt must abort without discarding any manifest data.
    (model / new_rows[1]["artifact"]["path"]).write_bytes(b"corrupt body bytes")
    with pytest.raises(ValueError, match="receipt|fragment"):
        compact_static_diagnostics(model, jobs=1)
    assert path.read_bytes() == unchanged
    assert not list(tmp_path.glob(".scar-static-manifest-*"))
