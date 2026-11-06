"""Read selected relation rows with bounded decoded memory and full receipts."""
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path


def select_relation_rows(root,receipt,predicate):
    """Return original (ordinal, wire) pairs after validating the entire table.

    Retain compressed bytes and selected records only. Large decoded tables are
    never split into an additional in-memory list of all line documents.
    """
    path=Path(root)/receipt['path'];payload=path.read_bytes()
    if len(payload)!=receipt['bytes'] or sha256(payload).hexdigest()!=receipt['sha256']:
        raise ValueError('relation compressed receipt differs')
    digest=sha256();decoded_bytes=0;count=0;selected=[]
    with gzip.GzipFile(fileobj=BytesIO(payload),mode='rb') as stream:
        for ordinal,line in enumerate(stream):
            if not line.endswith(b'\n'):raise ValueError('relation record lacks its line terminator')
            digest.update(line);decoded_bytes+=len(line);count+=1
            wire=json.loads(line)
            if predicate(wire):selected.append((ordinal,wire))
    if (decoded_bytes!=receipt['decoded_bytes'] or digest.hexdigest()!=receipt['decoded_sha256']
            or count!=receipt['records']):raise ValueError('relation decoded receipt differs')
    return tuple(selected)
