"""F5 table output with one wire-tag admission per independent table.

Keep the established deterministic JSON/gzip bytes and complete receipts.
The validated tag map belongs to this write; no mutable global codec cache is
introduced and all individual values still use the original wire encoder.
"""
import gzip
from hashlib import sha256
import os
import time

from scar.analysis.source_template_links import _json
from scar.ir.program import source_productions as P
from scar.ir.record_codec import _encode, _record_tags


def write_table(path, records, *, timings=None):
    started = time.monotonic()
    tags = _record_tags(P.PRODUCTION_RECORD_TAGS)
    digest = sha256()
    decoded_bytes = count = 0
    with path.open('xb') as destination:
        with gzip.GzipFile(filename='', mode='wb', fileobj=destination, compresslevel=3, mtime=0) as stream:
            for record in records:
                raw = _json(_encode(record, tags))
                stream.write(raw)
                digest.update(raw)
                decoded_bytes += len(raw)
                count += 1
        destination.flush()
        os.fsync(destination.fileno())
    payload = path.read_bytes()
    if timings is not None:
        timings[path.name] = time.monotonic() - started
    return dict(path=path.name, bytes=len(payload), sha256=sha256(payload).hexdigest(),
        decoded_bytes=decoded_bytes, decoded_sha256=digest.hexdigest(), records=count)
