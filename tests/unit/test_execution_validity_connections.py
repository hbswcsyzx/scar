"""Public validity-query guards must run before external-source refresh."""

import pytest

from scar.ir.execution.ids import ContentReadID, RunID
from scar.ir.execution.query import ExecutionIndex
from tests.fixtures.execution_lifetime_graphs import host_lifetime_execution


def _index():
    program, model, values, evidence, payloads, _ = host_lifetime_execution()
    return ExecutionIndex(model, program, value_graphs=values, evidence_graphs=evidence,
                          artifact_bytes=payloads)


def _forbid_refresh(monkeypatch, index):
    refreshed = []

    def refresh():
        refreshed.append(True)
        pytest.fail("invalid validity arguments must be rejected before external refresh")

    monkeypatch.setattr(index, "_content_context", refresh)
    return refreshed


def test_invalid_validity_budget_is_rejected_before_external_refresh(monkeypatch):
    index = _index()
    refreshed = _forbid_refresh(monkeypatch, index)

    with pytest.raises(TypeError, match="exact integer"):
        index.validity(ContentReadID("lifetime.read"), budget=True)
    with pytest.raises(ValueError, match="positive"):
        index.validity(ContentReadID("lifetime.read"), budget=0)

    assert refreshed == []


def test_nonexact_validity_read_id_is_rejected_before_external_refresh(monkeypatch):
    index = _index()
    refreshed = _forbid_refresh(monkeypatch, index)

    with pytest.raises(TypeError, match="exact ContentReadID"):
        index.validity(RunID("wrong-kind"))

    class DerivedContentReadID(ContentReadID):
        pass

    with pytest.raises(TypeError, match="exact ContentReadID"):
        index.validity(DerivedContentReadID("derived-read"))
    assert refreshed == []
