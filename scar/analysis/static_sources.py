"""Collect bounded source text without importing or executing project code."""
from __future__ import annotations

from collections import deque
import hashlib
import io
import os
from pathlib import Path
import stat
import tokenize

from scar.ir.program.discovery import ModuleMapping
from scar.ir.program.static_sources import (
    StaticSourceFile, StaticSourceIssue, StaticSourceIssueKind as IssueKind,
    StaticSourceRemaining, StaticSourceRemainingKind as RemainingKind,
    StaticSources, StaticSourcesStatus,
)


_SOURCE_SUFFIXES = frozenset((".py", ".pyi"))
_NAMESPACE_MARKERS = frozenset(("pyproject.toml", "setup.cfg", "setup.py"))
_EXCLUDED_DIRECTORIES = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
    "site-packages", ".tox", ".nox", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".cache", "__pycache__",
})


def _absolute(path, base=None):
    value = Path(path)
    if not value.is_absolute():
        value = (base if base is not None else Path.cwd()) / value
    return Path(os.path.abspath(value))


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _has_symlink_component(path):
    path = Path(path)
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            if current.is_symlink():
                return current
        except OSError:
            return None
    return None


def _issue(kind, path, detail):
    return StaticSourceIssue(kind, str(path), detail)


def _root_state(path, *, project=False):
    symlink = _has_symlink_component(path)
    if symlink is not None:
        return "symlink", str(symlink)
    try:
        info = path.lstat()
    except OSError as error:
        return "invalid", f"{type(error).__name__}: {error}"
    if not stat.S_ISDIR(info.st_mode):
        return "invalid", "path is not an existing directory"
    return "ok", ""


def _module_name(path, root):
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    parts = list(relative.parts)
    if not parts:
        return None
    suffix = Path(parts[-1]).suffix
    if suffix not in _SOURCE_SUFFIXES:
        return None
    parts[-1] = parts[-1][:-len(suffix)]
    if parts[-1] == "__init__":
        parts.pop()
    initializer = root / "__init__.py"
    if initializer.is_file() and not initializer.is_symlink():
        parts.insert(0, root.name)
    return ".".join(parts) if parts else root.name


def _read_source(path, byte_limit):
    """Read one stable regular file, rejecting symlink replacement and growth."""
    before_path = path.lstat()
    if stat.S_ISLNK(before_path.st_mode) or not stat.S_ISREG(before_path.st_mode):
        raise OSError("source candidate is not a regular non-symlink file")
    if before_path.st_size > byte_limit:
        raise _ByteBudget(before_path.st_size)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before_fd = os.fstat(descriptor)
        if _stamp(before_fd) != _stamp(before_path):
            raise _Changed("source changed between path check and open")
        chunks, remaining = [], before_fd.st_size + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after_fd = os.fstat(descriptor)
        after_path = path.lstat()
        if (_stamp(before_fd) != _stamp(after_fd) or _stamp(before_path) != _stamp(after_path)
                or len(raw) != before_fd.st_size):
            raise _Changed("source changed while it was being read")
        if len(raw) > byte_limit:
            raise _ByteBudget(len(raw))
    finally:
        os.close(descriptor)
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    text = raw.decode(encoding)
    return raw, text, encoding


class _ByteBudget(Exception):
    def __init__(self, required):
        self.required = required


class _Changed(Exception):
    pass


def _positive_limit(value, name):
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def collect_sources(project_root, *, source_roots=(), max_files=4096,
                    max_bytes=64_000_000, max_directories=16_384):
    """Collect all bounded ``.py``/``.pyi`` source candidates under source roots.

    ``source_roots`` may include absolute roots outside ``project_root``;
    relative roots are interpreted from ``project_root``. The returned roots
    retain their actual absolute paths. Namespace mappings are candidates only
    and never assert Python import search order or runtime reachability.

    ``max_files`` limits successfully retained files and ``max_bytes`` limits
    their cumulative raw bytes. Directory-budget frontiers remain exact paths;
    after a file budget is reached, all already enumerated source file paths
    remain individually listed for continuation.
    """
    _positive_limit(max_files, "max_files")
    _positive_limit(max_bytes, "max_bytes")
    _positive_limit(max_directories, "max_directories")
    if isinstance(source_roots, (str, bytes, Path)):
        raise TypeError("source_roots must be an iterable of roots, not one path")

    root = _absolute(project_root)
    issues, remaining = [], []
    namespace_roots, scan_roots = set(), set()
    state, detail = _root_state(root, project=True)
    if state == "ok":
        scan_roots.add(root)
        namespace_roots.add(root)
        conventional_src = root / "src"
        if conventional_src.is_dir() and not conventional_src.is_symlink():
            namespace_roots.add(conventional_src)
    elif state == "symlink":
        issues.append(_issue(IssueKind.PROJECT_ROOT_INVALID, root,
                             f"project root traverses symbolic link {detail}; no path was followed"))
    else:
        issues.append(_issue(IssueKind.PROJECT_ROOT_INVALID, root, detail))

    for supplied in source_roots:
        candidate = _absolute(supplied, root)
        state, detail = _root_state(candidate)
        if state == "ok":
            scan_roots.add(candidate)
            namespace_roots.add(candidate)
        elif state == "symlink":
            issues.append(_issue(IssueKind.SOURCE_ROOT_SYMLINK, candidate,
                                 f"source root traverses symbolic link {detail}; no path was followed"))
        else:
            issues.append(_issue(IssueKind.SOURCE_ROOT_INVALID, candidate, detail))

    directories = deque(sorted(scan_roots, key=str))
    visited = set()
    source_paths = set()
    while directories:
        directory = directories.popleft()
        if directory in visited:
            continue
        if len(visited) >= max_directories:
            frontier = sorted({directory, *directories}, key=str)
            for path in frontier:
                issues.append(_issue(IssueKind.DIRECTORY_BUDGET, path,
                                     f"directory scan stopped at max_directories={max_directories}"))
                remaining.append(StaticSourceRemaining(str(path), RemainingKind.DIRECTORY,
                                                       "directory budget"))
            break
        state, detail = _root_state(directory)
        if state == "symlink":
            issues.append(_issue(IssueKind.SYMLINK_SKIPPED, directory,
                                 f"directory traversal encountered symbolic link {detail}"))
            continue
        if state != "ok":
            issues.append(_issue(IssueKind.DIRECTORY_UNAVAILABLE, directory, detail))
            continue
        visited.add(directory)
        try:
            with os.scandir(directory) as entries:
                ordered = sorted(entries, key=lambda item: item.name)
        except OSError as error:
            issues.append(_issue(IssueKind.DIRECTORY_UNAVAILABLE, directory,
                                 f"{type(error).__name__}: {error}"))
            continue
        for entry in ordered:
            path = directory / entry.name
            try:
                if entry.is_symlink():
                    issues.append(_issue(IssueKind.SYMLINK_SKIPPED, path,
                                         "symbolic link was recorded but not followed"))
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in _EXCLUDED_DIRECTORIES:
                        directories.append(path)
                    continue
                if entry.name in _NAMESPACE_MARKERS and entry.is_file(follow_symlinks=False):
                    namespace_roots.add(directory)
                if Path(entry.name).suffix in _SOURCE_SUFFIXES and entry.is_file(follow_symlinks=False):
                    source_paths.add(path)
            except OSError as error:
                issues.append(_issue(IssueKind.FILE_UNAVAILABLE, path,
                                     f"directory entry could not be inspected: {type(error).__name__}: {error}"))

    roots = tuple(str(path) for path in sorted(namespace_roots, key=str))
    files = []
    used_bytes = 0
    source_paths = sorted(source_paths, key=str)
    for index, path in enumerate(source_paths):
        if len(files) >= max_files:
            for pending_path in source_paths[index:]:
                issues.append(_issue(IssueKind.FILE_BUDGET, pending_path,
                                     f"file scan reached max_files={max_files}"))
                remaining.append(StaticSourceRemaining(str(pending_path), RemainingKind.FILE,
                                                       "file budget"))
            break
        try:
            before = path.lstat()
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
                raise OSError("source candidate is not a regular non-symlink file")
            if before.st_size > max_bytes - used_bytes:
                issues.append(_issue(IssueKind.BYTE_BUDGET, path,
                                     f"file size {before.st_size} exceeds remaining source-byte budget {max_bytes - used_bytes}"))
                remaining.append(StaticSourceRemaining(str(path), RemainingKind.FILE,
                                                       "source-byte budget"))
                continue
            raw, text, encoding = _read_source(path, max_bytes - used_bytes)
        except _ByteBudget as error:
            issues.append(_issue(IssueKind.BYTE_BUDGET, path,
                                 f"file size {error.required} exceeds remaining source-byte budget {max_bytes - used_bytes}"))
            remaining.append(StaticSourceRemaining(str(path), RemainingKind.FILE,
                                                   "source-byte budget"))
            continue
        except _Changed as error:
            issues.append(_issue(IssueKind.FILE_CHANGED, path, str(error)))
            remaining.append(StaticSourceRemaining(str(path), RemainingKind.FILE,
                                                   "source changed during read"))
            continue
        except (OSError, UnicodeError, LookupError, SyntaxError) as error:
            kind = IssueKind.DECODE_ERROR if isinstance(error, (UnicodeError, LookupError, SyntaxError)) else IssueKind.FILE_UNAVAILABLE
            issues.append(_issue(kind, path, f"{type(error).__name__}: {error}"))
            remaining.append(StaticSourceRemaining(str(path), RemainingKind.FILE,
                                                   "source could not be retained"))
            continue

        raw_sha = hashlib.sha256(raw).hexdigest()
        decoded_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        mappings = []
        for source_root in roots:
            module_name = _module_name(path, Path(source_root))
            if module_name is not None:
                mappings.append(ModuleMapping(module_name, str(source_root)))
        mappings = tuple(sorted(set(mappings), key=lambda item: (item.source_root, item.name)))
        if mappings:
            primary_root = min((Path(item.source_root) for item in mappings),
                               key=lambda item: (-len(item.parts), str(item)))
            module_names = tuple(sorted({item.name for item in mappings
                                         if item.source_root == str(primary_root)}))
            namespace_root = str(primary_root)
        else:
            # A scanned path must be under at least one declared source root;
            # retain a clear issue instead of inventing a module name.
            enclosing = [candidate for candidate in scan_roots if path.is_relative_to(candidate)]
            if not enclosing:
                issues.append(_issue(IssueKind.SOURCE_ROOT_INVALID, path,
                                     "source path has no declared namespace root"))
                remaining.append(StaticSourceRemaining(str(path), RemainingKind.FILE,
                                                       "namespace root unavailable"))
                continue
            selected_root = min(enclosing, key=lambda item: (-len(item.parts), str(item)))
            namespace_root, module_names = str(selected_root), ()
        files.append(StaticSourceFile(str(path), namespace_root, module_names, text,
            raw_sha, decoded_sha, encoding, len(raw), mappings))
        used_bytes += len(raw)

    # Remove duplicate directory frontiers created by overlapping roots while
    # preserving deterministic issue/continuation order.
    issue_rows = tuple(sorted(set(issues), key=lambda item: (item.path, item.kind.value, item.detail)))
    remaining_rows = tuple(sorted(set(remaining), key=lambda item: (item.path, item.kind.value, item.reason)))
    file_rows = tuple(sorted(files, key=lambda item: item.path))
    status = StaticSourcesStatus.PARTIAL if issue_rows or remaining_rows else StaticSourcesStatus.COMPLETE
    return StaticSources(str(root), roots, file_rows, issue_rows, remaining_rows, status)


__all__ = ["collect_sources"]
