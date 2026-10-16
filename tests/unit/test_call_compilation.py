from __future__ import annotations

from dataclasses import replace
import __future__
import hashlib

import pytest

from scar.analysis.call_compilation import (
    UnsupportedCompilationFlags,
    compile_cache_key,
    future_flags_for,
    supported_future_flag_mask,
)
from scar.analysis.call_edges import _Sources, _nested_codes
from scar.ir.program.call_edges import (
    CallEdgeBudget,
    CallEdgeIssueKind,
    CallLinkStatus,
    CapturedCode,
)
from scar.ir.program.compilation import CallCompilationProfile
from scar.ir.record_codec import decode
from scar.trace.code_snapshot import describe_code


RECORDED = CallCompilationProfile.RECORDED_FUTURE_FLAGS
LEGACY = CallCompilationProfile.LEGACY_ZERO_FLAGS


def _captured(source: str, filename: str, *, flags: int, qualname: str):
    module = compile(source, filename, "exec", flags=flags, dont_inherit=True)
    matches = [code for code in _nested_codes(module) if code.co_qualname == qualname]
    assert len(matches) == 1
    return decode(CapturedCode, describe_code(matches[0]))


def _boundary(link):
    assert link.status is CallLinkStatus.INCOMPLETE
    assert link.issues
    assert link.issues[0].kind is CallEdgeIssueKind.SOURCE_BOUNDARY


def test_recorded_annotations_flags_reproduce_exact_code_and_legacy_stays_zero(tmp_path):
    path = tmp_path / "inherited_annotations.py"
    source = "def worker(value: MissingType):\n    return value\n"
    path.write_text(source, encoding="utf-8")
    annotations = __future__.annotations.compiler_flag
    captured = _captured(source, str(path), flags=annotations, qualname="worker")

    recorded = _Sources(
        path.parent.resolve(), CallEdgeBudget(), None,
        compilation_profile=RECORDED,
    ).code(captured)
    legacy = _Sources(path.parent.resolve(), CallEdgeBudget(), None).code(captured)

    assert recorded.status is CallLinkStatus.VERIFIED
    assert recorded.snapshot.fingerprint == "sha256:" + hashlib.sha256(source.encode()).hexdigest()
    assert legacy.status is CallLinkStatus.MISMATCH


def test_same_file_distinct_future_contexts_have_separate_compile_cache_entries(tmp_path):
    path = tmp_path / "two_contexts.py"
    source = "def worker(value: MissingType):\n    return value\n"
    path.write_text(source, encoding="utf-8")
    no_future = _captured(source, str(path), flags=0, qualname="worker")
    annotations = _captured(
        source, str(path), flags=__future__.annotations.compiler_flag,
        qualname="worker",
    )
    sources = _Sources(path.parent.resolve(), CallEdgeBudget(), None,
                       compilation_profile=RECORDED)

    zero_link = sources.code(no_future)
    annotations_link = sources.code(annotations)

    assert zero_link.status is CallLinkStatus.VERIFIED
    assert annotations_link.status is CallLinkStatus.VERIFIED
    assert len(sources.contexts) == 1
    assert len(sources.indexes) == 1
    assert len(sources.compiled) == 6  # Three optimize levels per future mask.
    keys = tuple(sources.compiled)
    assert {key.future_flags for key in keys} == {0, __future__.annotations.compiler_flag}
    assert {key.optimize for key in keys} == {0, 1, 2}


def test_nested_code_structural_flags_are_not_passed_as_future_context(tmp_path):
    path = tmp_path / "nested.py"
    source = (
        "def outer():\n"
        "    def worker(value: MissingType):\n"
        "        return value\n"
        "    return worker\n"
    )
    path.write_text(source, encoding="utf-8")
    annotations = __future__.annotations.compiler_flag
    captured = _captured(source, str(path), flags=annotations,
                         qualname="outer.<locals>.worker")

    assert captured.flags & 0x10  # CPython CO_NESTED structural bit.
    assert future_flags_for(captured.flags, RECORDED) == annotations
    assert future_flags_for(captured.flags, LEGACY) == 0
    assert _Sources(path.parent.resolve(), CallEdgeBudget(), None,
                    compilation_profile=RECORDED).code(captured).status is CallLinkStatus.VERIFIED


def test_unknown_flags_are_per_code_boundaries_and_do_not_poison_file_context(tmp_path):
    path = tmp_path / "unknown_flag.py"
    source = "def worker(value):\n    return value\n"
    path.write_text(source, encoding="utf-8")
    captured = _captured(source, str(path), flags=0, qualname="worker")
    unknown = replace(
        captured,
        key="pycode-v2:" + "f" * 64,
        flags=captured.flags | (1 << 30),
    )
    sources = _Sources(path.parent.resolve(), CallEdgeBudget(), None,
                       compilation_profile=RECORDED)

    unsupported_link = sources.code(unknown)
    normal_link = sources.code(captured)

    _boundary(unsupported_link)
    assert "unsupported bits" in unsupported_link.issues[0].detail
    assert normal_link.status is CallLinkStatus.VERIFIED
    assert not sources.context_errors


def test_future_syntax_outside_frontend_support_is_a_source_boundary(tmp_path):
    path = tmp_path / "barry.py"
    source = "def worker():\n    return 1 <> 2\n"
    path.write_text(source, encoding="utf-8")
    captured = _captured(
        source, str(path), flags=__future__.barry_as_FLUFL.compiler_flag,
        qualname="worker",
    )

    link = _Sources(path.parent.resolve(), CallEdgeBudget(), None,
                    compilation_profile=RECORDED).code(captured)

    _boundary(link)
    assert "invalid syntax" in link.issues[0].detail


def test_cache_identity_binds_fingerprint_profile_flags_and_compiler_settings(tmp_path):
    path = (tmp_path / "cache.py").resolve()
    raw_alias = str(path.parent) + "/./cache.py"
    annotations = __future__.annotations.compiler_flag
    zero = compile_cache_key(path, "sha256:" + "a" * 64, RECORDED, 0, 0,
                             compile_filename=str(path))
    with_annotations = compile_cache_key(path, "sha256:" + "a" * 64,
                                         RECORDED, annotations, 0,
                                         compile_filename=str(path))
    legacy = compile_cache_key(path, "sha256:" + "a" * 64, LEGACY,
                               annotations, 0, compile_filename=str(path))
    drift = compile_cache_key(path, "sha256:" + "b" * 64, RECORDED, 0, 0,
                              compile_filename=str(path))
    alias = compile_cache_key(path, "sha256:" + "a" * 64, RECORDED, 0, 0,
                              compile_filename=raw_alias)

    assert len({zero, with_annotations, legacy, drift, alias}) == 5
    assert alias.path == zero.path
    assert alias.compile_filename == raw_alias
    assert zero.future_flags == 0
    assert with_annotations.future_flags == annotations
    assert legacy.future_flags == 0
    assert supported_future_flag_mask() & __future__.annotations.compiler_flag


@pytest.mark.parametrize("alias_kind", ["dot", "repeated_slash"])
@pytest.mark.parametrize("profile", [LEGACY, RECORDED])
@pytest.mark.parametrize("alias_first", [True, False])
def test_compile_cache_preserves_lexical_filename_for_code_descriptors(
    tmp_path, alias_kind, profile, alias_first,
):
    path = (tmp_path / "worker.py").resolve()
    source = "def worker(value):\n    return value\n"
    path.write_text(source, encoding="utf-8")
    canonical_filename = str(path)
    if alias_kind == "dot":
        alias_filename = str(path.parent) + "/./worker.py"
    else:
        alias_filename = str(path.parent) + "//worker.py"
    alias = _captured(source, alias_filename, flags=0, qualname="worker")
    canonical = _captured(source, canonical_filename, flags=0, qualname="worker")
    assert alias.key != canonical.key

    sources = _Sources(path.parent, CallEdgeBudget(), None,
                       compilation_profile=profile)
    ordered = (alias, canonical) if alias_first else (canonical, alias)
    links = tuple(sources.code(captured) for captured in ordered)

    assert tuple(link.status for link in links) == (
        CallLinkStatus.VERIFIED, CallLinkStatus.VERIFIED,
    )
    keys = tuple(sources.compiled)
    assert {key.path for key in keys} == {str(path)}
    assert {key.compile_filename for key in keys} == {
        canonical_filename, alias_filename,
    }
    assert len(keys) == 6


def test_unsupported_future_mask_rejects_only_unknown_bits():
    with pytest.raises(UnsupportedCompilationFlags) as caught:
        future_flags_for((1 << 30) | __future__.annotations.compiler_flag, RECORDED)

    assert caught.value.unsupported == 1 << 30
    assert future_flags_for(__future__.annotations.compiler_flag, RECORDED) == \
        __future__.annotations.compiler_flag
    with pytest.raises(ValueError, match="exact integer"):
        future_flags_for(True, RECORDED)
