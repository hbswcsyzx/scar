"""Code-only identity/position contracts; no workload execution or imports."""
from collections import OrderedDict
import dis
import gc
import inspect
import json
import os
import struct
import subprocess
import sys
from types import CodeType, FunctionType
import weakref

import pytest

from scar.trace import code_snapshot as snapshots


def _code(source="def f(a, b):\n    local = a\n    return local + b\n", filename="fixture.py"):
    module = compile(source, filename, "exec", dont_inherit=True)
    return next(value for value in module.co_consts if type(value) is CodeType)


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch):
    monkeypatch.setattr(snapshots, "_CACHE", OrderedDict())
    monkeypatch.setattr(snapshots, "_CACHE_TEXT_BYTES", 0)


def test_description_uses_true_parameter_layout_and_original_filename():
    code = _code("def f(a, /, b, *args, option, **kwargs):\n    local = a\n    return local\n",
                 "../unresolved/source.py")
    description = snapshots.describe_code(code)
    assert set(description) == {"key", "filename", "qualname", "first_line", "flags", "parameters"}
    assert description["key"].startswith("pycode-v2:")
    assert len(description["key"].removeprefix("pycode-v2:")) == 64
    assert description["filename"] == "../unresolved/source.py"
    assert description["qualname"] == "f" and description["first_line"] == 1
    assert description["flags"] == code.co_flags
    assert description["parameters"] == ["a", "b", "option", "args", "kwargs"]


def test_parameter_names_are_not_deduplicated_for_a_constructed_code_object():
    code = _code().replace(co_varnames=("same", "same", "local"))
    assert snapshots.describe_code(code)["parameters"] == ["same", "same"]


def test_fresh_compile_and_warmed_code_have_identical_fingerprints():
    source = "def f(a, b):\n    return a + b\n"
    code = _code(source)
    before = snapshots.describe_code(code)
    function = FunctionType(code, {})
    for _ in range(5000):
        assert function(1, 2) == 3
    # Force structural re-encoding so a cache hit cannot conceal quickening drift.
    cached = snapshots._CACHE[id(code)]
    snapshots._forget(id(code), cached.reference)
    after = snapshots.describe_code(code)
    fresh = snapshots.describe_code(_code(source))
    assert before == after == fresh


@pytest.mark.parametrize("field", [
    "co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals",
    "co_stacksize", "co_flags", "co_code", "co_consts", "co_names",
    "co_varnames", "co_freevars", "co_cellvars", "co_filename", "co_name",
    "co_qualname", "co_firstlineno", "co_linetable", "co_exceptiontable",
])
def test_every_execution_field_participates_in_fingerprint(field):
    code = _code()
    changes = {
        "co_argcount": {"co_argcount": 1},
        "co_posonlyargcount": {"co_posonlyargcount": 1},
        "co_kwonlyargcount": {"co_kwonlyargcount": 1},
        "co_nlocals": {"co_nlocals": code.co_nlocals + 1,
                       "co_varnames": (*code.co_varnames, "extra_local")},
        "co_stacksize": {"co_stacksize": code.co_stacksize + 1},
        "co_flags": {"co_flags": code.co_flags ^ inspect.CO_NESTED},
        "co_code": {"co_code": code.co_code + bytes((dis.opmap["NOP"], 0))},
        "co_consts": {"co_consts": (*code.co_consts, "extra_constant")},
        "co_names": {"co_names": (*code.co_names, "different_global")},
        "co_varnames": {"co_varnames": ("changed", *code.co_varnames[1:])},
        "co_freevars": {"co_freevars": ("captured",)},
        "co_cellvars": {"co_cellvars": ("cell",)},
        "co_filename": {"co_filename": "different.py"},
        "co_name": {"co_name": "different"},
        "co_qualname": {"co_qualname": "outer.different"},
        "co_firstlineno": {"co_firstlineno": code.co_firstlineno + 1},
        "co_linetable": {"co_linetable": b""},
        "co_exceptiontable": {"co_exceptiontable": b"\x00"},
    }
    changed = code.replace(**changes[field])
    assert snapshots.describe_code(changed)["key"] != snapshots.describe_code(code)["key"]


def test_nested_code_content_is_fingerprinted_recursively():
    code = _code("def outer():\n    def inner():\n        return 1\n    return inner\n")
    nested = next(value for value in code.co_consts if type(value) is CodeType)
    changed = code.replace(co_consts=tuple(
        nested.replace(co_consts=(None, 2)) if value is nested else value for value in code.co_consts))
    assert snapshots.describe_code(code)["key"] != snapshots.describe_code(changed)["key"]


def test_fresh_compilation_with_constant_slices_has_stable_fingerprint():
    source = "def f(a):\n    return a[1:], a[:1500], a[::2]\n"
    first, second = _code(source), _code(source)
    assert any(type(value) is slice for value in first.co_consts)
    assert snapshots.describe_code(first) == snapshots.describe_code(second)


@pytest.mark.parametrize("left,right", [
    (slice(1, None, None), slice(2, None, None)),
    (slice(None, 10, None), slice(None, 11, None)),
    (slice(None, None, 2), slice(None, None, 3)),
    (slice(1, 2, 3), (1, 2, 3)),
])
def test_slice_encoding_preserves_all_parts_and_type(left, right):
    code = _code()
    assert snapshots.describe_code(code.replace(co_consts=(left,)))["key"] != snapshots.describe_code(
        code.replace(co_consts=(right,)))["key"]


@pytest.mark.parametrize("left,right", [
    (True, 1), (False, 0), (1, 1.0), (1.0, 1 + 0j), (0.0, -0.0),
    ("text", b"text"), ((1, 2), frozenset((1, 2))), (None, Ellipsis),
])
def test_constants_preserve_exact_types_and_binary_values(left, right):
    code = _code()
    assert snapshots.describe_code(code.replace(co_consts=(left,)))["key"] != snapshots.describe_code(
        code.replace(co_consts=(right,)))["key"]


def _nan(payload):
    return struct.unpack(">d", bytes.fromhex(payload))[0]


@pytest.mark.parametrize("complex_value", [False, True])
def test_nan_payload_bits_are_not_normalized(complex_value):
    left, right = _nan("7ff8000000000001"), _nan("7ff8000000000002")
    if complex_value:
        left, right = complex(-0.0, left), complex(-0.0, right)
    code = _code()
    assert snapshots.describe_code(code.replace(co_consts=(left,)))["key"] != snapshots.describe_code(
        code.replace(co_consts=(right,)))["key"]


def test_frozenset_is_canonical_even_with_distinct_nan_members():
    first = frozenset((_nan("7ff8000000000001"), _nan("7ff8000000000002"), "text", 1))
    second = frozenset((1, "text", _nan("7ff8000000000002"), _nan("7ff8000000000001")))
    code = _code()
    assert snapshots.describe_code(code.replace(co_consts=(first,)))["key"] == snapshots.describe_code(
        code.replace(co_consts=(second,)))["key"]


def test_scalar_text_encoding_preserves_surrogates_and_path_spelling():
    code = _code(filename="../relative-\u03bb\ud800.py")
    description = snapshots.describe_code(code)
    assert description["filename"] == code.co_filename
    assert description["key"] != snapshots.describe_code(code.replace(co_filename="relative-\u03bb\ud800.py"))["key"]


class _HostileConstant:
    calls = []

    def __repr__(self):
        self.calls.append("repr")
        raise AssertionError("repr must not execute")

    def __hash__(self):
        self.calls.append("hash")
        return 42

    def __eq__(self, other):
        self.calls.append("eq")
        raise AssertionError("equality must not execute")


@pytest.mark.parametrize("container", ["direct", "tuple", "frozenset", "code"])
def test_unknown_constants_are_rejected_without_application_protocols(container):
    value = _HostileConstant()
    if container == "tuple":
        value = (value,)
    elif container == "frozenset":
        value = frozenset((value,))
    elif container == "code":
        value = _code().replace(co_consts=(value,))
    code = _code().replace(co_consts=(value,))
    _HostileConstant.calls.clear()
    with pytest.raises(ValueError, match="constant type"):
        snapshots.describe_code(code)
    with pytest.raises(ValueError, match="constant type"):
        snapshots.site(code, 0)
    assert _HostileConstant.calls == []


def test_subclass_of_supported_constant_is_not_treated_as_exact_builtin():
    class CustomString(str):
        def encode(self, *args, **kwargs):
            raise AssertionError("custom encode must not execute")

    code = _code().replace(co_consts=(CustomString("value"),))
    with pytest.raises(ValueError, match="constant type"):
        snapshots.describe_code(code)


@pytest.mark.parametrize("part", [0, 1, 2])
def test_slice_with_custom_member_is_rejected_without_application_protocols(part):
    parts = [None, None, None]
    parts[part] = _HostileConstant()
    code = _code().replace(co_consts=(slice(*parts),))
    _HostileConstant.calls.clear()
    with pytest.raises(ValueError, match="constant type"):
        snapshots.describe_code(code)
    assert _HostileConstant.calls == []


def test_equal_code_objects_with_different_filenames_never_share_cache_entry():
    first, second = _code(filename="first.py"), _code(filename="second.py")
    assert first == second  # CodeType equality itself is too weak for this cache.
    assert snapshots.describe_code(first)["key"] != snapshots.describe_code(second)["key"]
    assert snapshots.describe_code(first)["filename"] == "first.py"
    assert snapshots.describe_code(second)["filename"] == "second.py"
    assert {id(first), id(second)} <= snapshots._CACHE.keys()


def test_same_line_calls_have_distinct_exact_offsets_and_positions():
    code = _code("def f(g, h):\n    return g() + h()\n")
    calls = [instruction for instruction in dis.get_instructions(code) if instruction.opname == "CALL"]
    assert len(calls) == 2
    observed = [snapshots.site(code, instruction.offset) for instruction in calls]
    assert len({record["offset"] for record in observed}) == 2
    assert len({tuple(record["position"]) for record in observed}) == 2
    for instruction, record in zip(calls, observed):
        assert record == {"code": snapshots.describe_code(code)["key"], "offset": instruction.offset,
                          "opname": instruction.opname, "position": list(instruction.positions)}


def test_sites_preserve_non_calls_and_inline_cache_units():
    code = _code("def f(g):\n    return g()\n")
    for instruction in dis.get_instructions(code):
        record = snapshots.site(code, instruction.offset)
        assert record["opname"] == instruction.opname
        assert record["position"] == list(instruction.positions)
    cache_offset = next(offset for offset in range(0, len(code.co_code), 2)
                        if code.co_code[offset] == dis.opmap["CACHE"])
    assert snapshots.site(code, cache_offset)["opname"] == "CACHE"


@pytest.mark.parametrize("offset", [-1, 1, 1_000_000])
def test_unknown_offsets_do_not_borrow_a_neighboring_call(offset):
    code = _code()
    assert snapshots.site(code, offset) == {"code": snapshots.describe_code(code)["key"],
                                           "offset": offset, "opname": None, "position": None}


@pytest.mark.parametrize("offset", [True, False, 1.0, "2", None])
def test_offset_requires_an_exact_integer(offset):
    with pytest.raises(ValueError, match="exact integer"):
        snapshots.site(_code(), offset)


def test_missing_positions_remain_unknown():
    code = _code().replace(co_linetable=b"")
    assert snapshots.site(code, 0)["position"] is None


def test_no_debug_ranges_does_not_publish_a_partial_source_span():
    environment = os.environ.copy()
    environment.pop("SCAR_TRACE_DIR", None)
    environment.pop("SCAR_OPTIMIZE", None)
    source = """
import json
from scar.trace.code_snapshot import site
code = compile('def f(x): return x', 'fixture.py', 'exec').co_consts[0]
print(json.dumps({'positions': list(code.co_positions()), 'site': site(code, 0)}))
"""
    completed = subprocess.run([sys.executable, "-X", "no_debug_ranges", "-c", source],
                               env=environment, capture_output=True, text=True, timeout=10, check=True)
    observed = json.loads(completed.stdout)
    assert any(position[0] is not None and position[2] is None for position in observed["positions"])
    assert observed["site"]["opname"] is not None
    assert observed["site"]["position"] is None


@pytest.mark.parametrize("limit,value,match", [
    ("_MAX_BYTES", 32, "byte budget"),
    ("_MAX_NODES", 3, "node budget"),
    ("_MAX_DEPTH", 1, "nesting budget"),
])
def test_budget_failures_cannot_be_bypassed_by_a_warm_cache(monkeypatch, limit, value, match):
    code = _code()
    snapshots.describe_code(code)
    monkeypatch.setattr(snapshots, limit, value)
    with pytest.raises(ValueError, match=match):
        snapshots.describe_code(code)


def test_instruction_budget_is_checked_before_position_traversal(monkeypatch):
    code = _code()
    monkeypatch.setattr(snapshots, "_MAX_CODE_UNITS", 1)
    with pytest.raises(ValueError, match="instruction budget"):
        snapshots.site(code, 0)


def test_cache_does_not_keep_equal_application_code_objects_alive():
    first, second = _code(), _code()
    assert first is not second and first == second
    refs = [weakref.ref(first), weakref.ref(second)]
    identities = [id(first), id(second)]
    description = snapshots.describe_code(first)
    snapshots.describe_code(second)
    position = snapshots.site(first, 0)
    del first
    gc.collect()
    assert refs[0]() is None and identities[0] not in snapshots._CACHE
    assert refs[1]() is second and identities[1] in snapshots._CACHE
    del second
    gc.collect()
    assert refs[1]() is None and identities[1] not in snapshots._CACHE
    assert description["key"] == position["code"]


def test_cache_retains_neither_outer_nor_nested_code_constants():
    code = _code("def outer():\n    def inner():\n        return 1\n    return inner\n")
    nested = next(value for value in code.co_consts if type(value) is CodeType)
    refs = [weakref.ref(code), weakref.ref(nested)]
    snapshots.describe_code(code)
    snapshots.site(code, 0)
    del nested, code
    gc.collect()
    assert all(reference() is None for reference in refs)
    assert not snapshots._CACHE


def test_cache_entry_and_site_counts_are_bounded(monkeypatch):
    monkeypatch.setattr(snapshots, "_MAX_CACHE_ENTRIES", 2)
    monkeypatch.setattr(snapshots, "_MAX_CACHED_SITES", 2)
    codes = [_code(filename=f"{index}.py") for index in range(5)]
    for code in codes:
        snapshots.describe_code(code)
    assert tuple(snapshots._CACHE) == tuple(id(code) for code in codes[-2:])
    code = codes[-1]
    for offset in (0, 2, 4):
        snapshots.site(code, offset)
    assert tuple(snapshots._CACHE[id(code)].sites) == (2, 4)


def test_oversized_cache_metadata_is_not_retained(monkeypatch):
    monkeypatch.setattr(snapshots, "_MAX_CACHE_TEXT_BYTES", 100)
    code = _code(filename="a" * 200)
    assert snapshots.describe_code(code)["filename"] == code.co_filename
    assert id(code) not in snapshots._CACHE


def test_returned_dicts_and_parameter_position_lists_do_not_mutate_cache():
    code = _code()
    expected = snapshots.describe_code(code)
    changed = snapshots.describe_code(code)
    changed["key"] = "wrong"
    changed["parameters"].append("wrong")
    assert snapshots.describe_code(code) == expected
    original = snapshots.site(code, 0)
    changed = snapshots.site(code, 0)
    changed["position"][0] = -999
    assert snapshots.site(code, 0) == original


def test_non_code_input_is_rejected_without_hash_or_repr():
    value = _HostileConstant()
    _HostileConstant.calls.clear()
    with pytest.raises(ValueError, match="CodeType"):
        snapshots.describe_code(value)
    assert _HostileConstant.calls == []
