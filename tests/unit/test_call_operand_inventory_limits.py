"""Operand inventory inputs obey raw and decoded limits before replay."""
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import scar.cli as cli
from scar.analysis.program_inventory import ProgramInventory


@pytest.fixture
def replay_stub(monkeypatch):
    """Keep the real input reader; replace only expensive inventory replay."""
    result = object()
    replay = Mock(return_value=result)
    monkeypatch.setattr(ProgramInventory, "from_dict", staticmethod(replay))
    monkeypatch.setattr(cli, "_inventory_limits", lambda args: {})
    monkeypatch.setattr(cli, "_runtime_inventory_budget", lambda args: "runtime-ceiling")
    monkeypatch.setattr(cli, "_context_inventory_budget", lambda args: "context-ceiling")
    monkeypatch.setattr(cli, "_call_budget", lambda args: "call-ceiling")
    return SimpleNamespace(max_compile_attempts=17), replay, result


def test_raw_oversize_is_rejected_before_hash_open_or_json_replay(tmp_path, monkeypatch, replay_stub):
    args, replay, _ = replay_stub
    path = tmp_path / "inventory.json"
    path.write_bytes(b'{"value": 1}')
    forbidden = Mock(side_effect=AssertionError("oversized input must not be read or hashed"))
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(hashlib, "sha256", forbidden)
    monkeypatch.setattr(hashlib, "file_digest", forbidden)
    monkeypatch.setattr(cli, "_call_json", forbidden)

    with pytest.raises(ValueError, match="inventory raw input byte budget exceeded"):
        cli._call_inventory_input(path, args, max_input_bytes=path.stat().st_size - 1)

    forbidden.assert_not_called()
    replay.assert_not_called()


def test_small_gzip_rejects_decoded_oversize_before_inventory_replay(tmp_path, replay_stub):
    args, replay, _ = replay_stub
    decoded = json.dumps({"value": "x" * 4096}).encode()
    raw = gzip.compress(decoded, mtime=0)
    path = tmp_path / "inventory.json.gz"
    path.write_bytes(raw)
    ceiling = 128
    assert len(raw) < ceiling < len(decoded)

    with pytest.raises(ValueError, match="independent read byte ceiling"):
        cli._call_inventory_input(path, args, max_input_bytes=ceiling)

    replay.assert_not_called()


@pytest.mark.parametrize("growth_phase", ("after_stat", "during_hash"))
def test_file_growth_is_detected_after_reading_at_most_raw_ceiling_plus_one(
        tmp_path, monkeypatch, replay_stub, growth_phase):
    args, replay, _ = replay_stub
    path = tmp_path / "inventory.json"
    path.write_bytes(b"{}")
    ceiling = 32
    original_open = Path.open
    requests, returned = [], []
    grown = False
    opens = 0

    def grow():
        nonlocal grown
        assert not grown
        with original_open(path, "ab") as stream:
            stream.write(b" " * (ceiling * 2))
        grown = True

    class ObservedStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self.stream.__exit__(*exc)

        def read(self, count):
            assert 0 < count <= ceiling + 1
            requests.append(count)
            data = self.stream.read(count)
            returned.append(len(data))
            if growth_phase == "during_hash" and not grown:
                grow()
            return data

    def observed_open(self, mode="r", *positional, **keywords):
        nonlocal opens
        if self == path and mode == "rb":
            opens += 1
            assert opens == 1, "oversized hash must fail before JSON opens the file"
            if growth_phase == "after_stat":
                grow()
            return ObservedStream(original_open(self, mode, *positional, **keywords))
        return original_open(self, mode, *positional, **keywords)

    monkeypatch.setattr(Path, "open", observed_open)
    parse = Mock(side_effect=AssertionError("raw growth must fail before JSON parsing"))
    monkeypatch.setattr(cli, "_call_json", parse)

    with pytest.raises(ValueError, match="inventory raw input byte budget exceeded"):
        cli._call_inventory_input(path, args, max_input_bytes=ceiling)

    assert grown and opens == 1
    assert sum(returned) == ceiling + 1
    assert requests == ([ceiling + 1] if growth_phase == "after_stat" else [ceiling + 1, ceiling - 1])
    parse.assert_not_called()
    replay.assert_not_called()


@pytest.mark.parametrize("compressed", (False, True))
@pytest.mark.parametrize("headroom", (0, 11))
def test_small_input_replays_decoded_json_and_binds_exact_original_raw_hash(
        tmp_path, replay_stub, compressed, headroom):
    args, replay, expected_inventory = replay_stub
    document = {"fixture": "bounded input", "number": 7}
    decoded = json.dumps(document).encode()
    raw = gzip.compress(decoded, mtime=0) if compressed else decoded
    path = tmp_path / ("inventory.json.gz" if compressed else "inventory.json")
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    ceiling = max(len(raw), len(decoded)) + headroom

    inventory, binding = cli._call_inventory_input(path, args, expected=digest, max_input_bytes=ceiling)

    assert inventory is expected_inventory
    assert binding == {"path": str(path.resolve()), "sha256": digest}
    replay.assert_called_once_with(document, runtime_verification_budget="runtime-ceiling",
        max_compile_attempts=17, context_verification_budget="context-ceiling",
        call_verification_budget="call-ceiling")
    if compressed:
        assert binding["sha256"] != hashlib.sha256(decoded).hexdigest()


def test_wrong_raw_hash_rejects_before_json_and_inventory_replay(tmp_path, monkeypatch, replay_stub):
    args, replay, _ = replay_stub
    raw = b'{"value": 1}'
    path = tmp_path / "inventory.json"
    path.write_bytes(raw)
    parse = Mock(side_effect=AssertionError("wrong binding must not reach JSON parsing"))
    monkeypatch.setattr(cli, "_call_json", parse)

    with pytest.raises(ValueError, match="inventory file differs from its bound input"):
        cli._call_inventory_input(path, args, expected=hashlib.sha256(raw + b" ").hexdigest(),
                                  max_input_bytes=len(raw))

    parse.assert_not_called()
    replay.assert_not_called()
