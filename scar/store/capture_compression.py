"""Independent lossless capture members with bounded threaded compression.

Only closed, explicitly selected byte files belong here. Application objects,
graph ownership and dynamic observation never cross this worker boundary.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import gzip
from hashlib import sha256
from pathlib import Path
from threading import Lock

from scar.store.bundle_partitions import _Sink


def _stamp(path):
    s = path.stat()
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


class _LockedSink(_Sink):
    def __init__(self, stream, totals, limits, lock):
        super().__init__(stream, totals, limits)
        self.lock = lock

    def write(self, data):
        # The shared stored-byte ceiling must be checked and charged atomically.
        with self.lock:
            return super().write(data)


def compress_capture_members(paths, *, root, limits, max_raw_bytes, max_files,
                             os_directory, max_os_lines, workers=4):
    if type(workers) is not int or not 1 <= workers <= 32:
        raise ValueError('capture compression requires 1..32 workers')
    root, os_directory = Path(root).absolute(), Path(os_directory).absolute()
    paths = tuple(Path(p).absolute() for p in paths)
    if not paths or len(paths) > max_files or len(set(paths)) != len(paths):
        raise ValueError('capture member count/uniqueness differs')
    stamps = {}
    for path in paths:
        if (not path.is_file() or path.is_symlink() or path.suffix == '.gz'
                or not path.resolve().is_relative_to(root)):
            raise ValueError('unsafe capture compression member')
        stamps[path] = _stamp(path)
    expected_raw = sum(stamp[2] for stamp in stamps.values())
    if expected_raw > max_raw_bytes:
        raise ValueError('capture compression raw-byte budget exceeded before work')
    totals, lock = {'stored_bytes': 0}, Lock()

    def member(path):
        target = path.with_name(path.name + '.gz')
        raw_digest, size, lines = sha256(), 0, 0
        before = stamps[path]
        with path.open('rb') as source, target.open('xb') as output:
            sink = _LockedSink(output, totals, limits, lock)
            with gzip.GzipFile(filename='', fileobj=sink, mode='wb', mtime=0, compresslevel=1) as compressed:
                while True:
                    block = source.read(min(1_048_576, before[2] - size + 1))
                    if not block:
                        break
                    size += len(block)
                    if size > before[2]:
                        raise ValueError('capture member grew during compression')
                    lines += block.count(b'\n')
                    raw_digest.update(block)
                    compressed.write(block)
        if size != before[2] or _stamp(path) != before:
            raise ValueError('capture member changed during compression')
        check, checked = sha256(), 0
        with gzip.open(target, 'rb') as stream:
            while block := stream.read(1_048_576):
                checked += len(block)
                if checked > size:
                    raise ValueError('capture roundtrip exceeds original byte count')
                check.update(block)
        if (checked, check.hexdigest()) != (size, raw_digest.hexdigest()):
            raise ValueError('capture compression roundtrip differs')
        return {'logical_path': str(path), 'actual_path': str(target),
                'raw_sha256': raw_digest.hexdigest(), 'raw_bytes': size,
                'compressed_bytes': sink.size, 'gzip_sha256': sink.digest.hexdigest()}, lines

    if workers == 1:
        completed = [member(path) for path in paths]
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='scar-archive') as pool:
            completed = list(pool.map(member, paths))
    rows = [row for row, _ in completed]
    os_lines = sum(lines for path, (_, lines) in zip(paths, completed) if path.parent == os_directory)
    if os_lines > max_os_lines:
        raise ValueError('capture compression OS-line budget exceeded')
    if sum(row['raw_bytes'] for row in rows) != expected_raw:
        raise ValueError('capture compression raw denominator differs')
    return rows, {'raw_bytes_read': expected_raw, 'decoded_roundtrip_bytes_read': expected_raw,
                  'stored_bytes_written': totals['stored_bytes'], 'os_lines': os_lines,
                  'compression_workers': workers}, stamps


def remove_verified_originals(rows, stamps, *, retain=()):
    """Only after the caller has published its complete archive manifest."""
    retain = set(map(Path, retain))
    for row in rows:
        path = Path(row['logical_path'])
        if path not in retain:
            if path.is_symlink() or _stamp(path) != stamps[path]:
                raise ValueError('original capture member changed before archive cleanup')
            path.unlink()
