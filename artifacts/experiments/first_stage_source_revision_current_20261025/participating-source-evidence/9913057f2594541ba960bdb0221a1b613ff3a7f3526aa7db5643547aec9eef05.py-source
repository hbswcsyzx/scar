"""Compiler-context policy for reproducing captured code descriptors.

These helpers only choose the flags used to compile current source. A
successful descriptor comparison is a source correspondence; it is not an
execution, call, environment, data-flow, or effects proof.
"""
from __future__ import annotations

from dataclasses import dataclass
import dis
import __future__
from pathlib import Path
import sys

from scar.ir.program.compilation import CallCompilationProfile


class UnsupportedCompilationFlags(ValueError):
    """Captured code uses flags this runtime cannot treat as compile context."""

    def __init__(self, flags: int, unsupported: int):
        self.flags = flags
        self.unsupported = unsupported
        super().__init__(
            "captured code flags contain unsupported bits: "
            + format(unsupported, "#x")
        )


def _exact_integer(value, name: str, *, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an exact integer >= {minimum}")


def _profile(value) -> CallCompilationProfile:
    if type(value) is not CallCompilationProfile:
        raise ValueError("compilation profile must be a CallCompilationProfile")
    return value


def structural_flag_mask() -> int:
    """Return interpreter code-object flags that are not compiler context."""
    result = 0
    for flag in dis.COMPILER_FLAG_NAMES:
        result |= flag
    return result


def supported_future_flag_mask() -> int:
    """Return known future bits that do not overlap structural code flags.

    ``__future__.nested_scopes`` overlaps ``CO_NESTED``. Passing it to
    ``compile`` would confuse a structural property of the captured code with
    an inherited compiler setting, so any overlapping feature is excluded.
    """
    structural = structural_flag_mask()
    result = 0
    for name in __future__.all_feature_names:
        flag = getattr(__future__, name).compiler_flag
        if flag and not flag & structural:
            result |= flag
    return result


def future_flags_for(flags: int, profile: CallCompilationProfile) -> int:
    """Choose the only compile flags authorized by a compilation profile.

    The legacy policy deliberately ignores ``flags`` and always returns zero.
    The recorded policy accepts only known future bits plus interpreter-known
    structural code flags, and returns just the future bits to pass to
    ``compile``.
    """
    _exact_integer(flags, "captured code flags")
    profile = _profile(profile)
    if profile is CallCompilationProfile.LEGACY_ZERO_FLAGS:
        return 0

    future = supported_future_flag_mask()
    known = future | structural_flag_mask()
    unsupported = flags & ~known
    if unsupported:
        raise UnsupportedCompilationFlags(flags, unsupported)
    return flags & future


@dataclass(frozen=True, slots=True)
class CompilationCacheKey:
    """All inputs that can change source compilation or descriptor output.

    ``path`` is the canonical path used to read and fingerprint the source;
    ``compile_filename`` preserves the exact lexical filename passed to
    ``compile`` because it is embedded in code descriptors as ``co_filename``.
    """

    path: str
    compile_filename: str
    source_fingerprint: str
    profile: CallCompilationProfile
    future_flags: int
    optimize: int
    implementation: str
    version: tuple[int, int, int, str, int]
    mode: str
    dont_inherit: bool

    def __post_init__(self):
        if type(self.path) is not str or not self.path:
            raise ValueError("compile cache canonical source path must be nonempty text")
        if type(self.compile_filename) is not str or not self.compile_filename:
            raise ValueError("compile cache filename must be nonempty text")
        if type(self.source_fingerprint) is not str or not self.source_fingerprint:
            raise ValueError("compile cache source fingerprint must be nonempty text")
        _profile(self.profile)
        _exact_integer(self.future_flags, "future flags")
        _exact_integer(self.optimize, "optimization level")
        if self.optimize not in (0, 1, 2):
            raise ValueError("optimization level must be 0, 1, or 2")
        if type(self.implementation) is not str or not self.implementation:
            raise ValueError("interpreter implementation must be nonempty text")
        if (type(self.version) is not tuple or len(self.version) != 5
                or any(type(item) is not int for item in self.version[:3])
                or type(self.version[3]) is not str
                or type(self.version[4]) is not int):
            raise ValueError("interpreter version must be an exact version tuple")
        if type(self.mode) is not str or not self.mode:
            raise ValueError("compile mode must be nonempty text")
        if type(self.dont_inherit) is not bool:
            raise ValueError("dont_inherit must be bool")


def compile_cache_key(
    path: str | Path,
    source_fingerprint: str,
    profile: CallCompilationProfile,
    captured_flags: int,
    optimize: int,
    *,
    compile_filename: str,
    mode: str = "exec",
    dont_inherit: bool = True,
) -> CompilationCacheKey:
    """Build a strict cache identity for one source compile attempt.

    The canonical read path and raw compile filename are intentionally separate:
    filesystem aliases may read the same source while producing different code
    descriptors.
    """
    profile = _profile(profile)
    return CompilationCacheKey(
        str(Path(path)), compile_filename, source_fingerprint, profile,
        future_flags_for(captured_flags, profile), optimize,
        sys.implementation.name,
        (sys.version_info.major, sys.version_info.minor, sys.version_info.micro,
         sys.version_info.releaselevel, sys.version_info.serial),
        mode, dont_inherit,
    )
