"""Independent decompressed byte ceilings and atomic call-report writes."""
import gzip
import json

import pytest

from scar.cli import _call_json, _write_call_document


def retained(path, raw):
    path.write_bytes(gzip.compress(raw) if path.suffix == ".gz" else raw)


def logical_bytes(path):
    return gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()


def encoded(document):
    return (json.dumps(document, sort_keys=True, ensure_ascii=True, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


@pytest.mark.parametrize("suffix", [".json", ".json.gz"])
def test_read_ceiling_counts_decompressed_utf8_bytes_at_exact_boundary(tmp_path, suffix):
    path = tmp_path / ("report" + suffix)
    document = {"text": "调用é🙂" * 1000, "finite": 1e308}
    raw = (json.dumps(document, ensure_ascii=False) + "\n").encode("utf-8")
    retained(path, raw)
    assert len(raw) > len(raw.decode("utf-8"))
    if suffix.endswith(".gz"):
        assert path.stat().st_size < len(raw) - 1
    assert _call_json(path, max_bytes=len(raw)) == document
    with pytest.raises(ValueError, match="independent read byte ceiling"):
        _call_json(path, max_bytes=len(raw) - 1)


@pytest.mark.parametrize("suffix", [".json", ".json.gz"])
@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e9999", "-1e9999"])
def test_reader_rejects_nonfinite_literals_and_float_overflow(tmp_path, suffix, literal):
    path = tmp_path / ("report" + suffix)
    retained(path, ('{"nested":[{"number":' + literal + "}]}").encode())
    with pytest.raises(ValueError, match="nonfinite JSON"):
        _call_json(path)


@pytest.mark.parametrize("suffix", [".json", ".json.gz"])
def test_reader_rejects_duplicate_nested_fields(tmp_path, suffix):
    path = tmp_path / ("report" + suffix)
    retained(path, b'{"outer":{"name":1,"name":2}}')
    with pytest.raises(ValueError, match="duplicate JSON field"):
        _call_json(path)


@pytest.mark.parametrize("ceiling", [0, -1, True, False, 1.0, "100", None, 1 << 100])
def test_io_requires_positive_exact_integer_ceilings(tmp_path, ceiling):
    path = tmp_path / "report.json"
    path.write_bytes(b"{}")
    with pytest.raises(ValueError, match="positive exact integer"):
        _call_json(path, max_bytes=ceiling)
    with pytest.raises(ValueError, match="positive exact integer"):
        _write_call_document(path, {"replacement": True}, ceiling)
    assert path.read_bytes() == b"{}"
    assert sorted(item.name for item in tmp_path.iterdir()) == [path.name]


@pytest.mark.parametrize("suffix", [".json", ".json.gz"])
def test_writer_exact_ceiling_includes_ascii_escaped_unicode_and_newline(tmp_path, suffix):
    path = tmp_path / ("report" + suffix)
    document = {"z": "调用é🙂", "a": [1, 2, 3]}
    raw = encoded(document)
    assert b"\\u" in raw and raw.endswith(b"\n")
    _write_call_document(path, document, len(raw))
    assert logical_bytes(path) == raw
    assert _call_json(path, max_bytes=len(raw)) == document
    assert sorted(item.name for item in tmp_path.iterdir()) == [path.name]


@pytest.mark.parametrize("suffix", [".json", ".json.gz"])
@pytest.mark.parametrize("existing", [False, True])
def test_midwrite_overflow_keeps_old_output_or_leaves_new_output_absent(tmp_path, suffix, existing):
    path = tmp_path / ("report" + suffix)
    previous = b"old report bytes must survive"
    if existing:
        path.write_bytes(previous)
    # The ceiling is reached after many encoder pieces have already been
    # written into the temporary file, including for gzip output.
    document = {"a": list(range(1000)), "z": "调用🙂" * 100}
    with pytest.raises(ValueError, match="independent write byte ceiling"):
        _write_call_document(path, document, len(encoded(document)) - 1)
    assert path.exists() is existing
    if existing:
        assert path.read_bytes() == previous
    assert sorted(item.name for item in tmp_path.iterdir()) == ([path.name] if existing else [])


@pytest.mark.parametrize("suffix", [".json", ".json.gz"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_write_failure_preserves_output_and_removes_temporary(tmp_path, suffix, value):
    path = tmp_path / ("report" + suffix)
    path.write_bytes(b"previous output")
    with pytest.raises(ValueError):
        _write_call_document(path, {"a": list(range(100)), "z": value}, 100_000)
    assert path.read_bytes() == b"previous output"
    assert sorted(item.name for item in tmp_path.iterdir()) == [path.name]
