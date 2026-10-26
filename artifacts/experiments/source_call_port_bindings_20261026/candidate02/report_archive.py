"""Bounded export of the existing CallOperandReport wire document.

Adapted from the completed current-source gate partition function, with an
explicit destination replacing its experiment-global output directory.
This is an experiment serializer, not another IR or semantic verifier.
"""
from pathlib import Path
import gzip
import hashlib
import json


def receipt(path):
    path=Path(path)
    digest=hashlib.sha256(); size=0
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1_048_576),b''):
            digest.update(block);size+=len(block)
    return {'path':str(path.resolve()),'sha256':digest.hexdigest(),'bytes':size}


def write_json(path,value):
    with Path(path).open('x') as stream:
        json.dump(value,stream,ensure_ascii=False,sort_keys=True,allow_nan=False,indent=2)
        stream.write('\n')


def partitions(document, destination):
    """Preserve one to_dict document in bounded reference-only gzip tables."""
    destination = Path(destination)
    destination.mkdir()
    maximum = 16_000_000
    tables = {}

    def table(name, rows):
        chunks, pending, total, number = [], bytearray(), 0, 0
        def flush():
            nonlocal pending, number
            if not pending:
                return
            path = destination / (name + '.' + str(len(chunks)).zfill(4) + '.jsonl.gz')
            payload = bytes(pending)
            with path.open('xb') as raw:
                with gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as stream:
                    stream.write(payload)
            chunks.append({**receipt(path), 'decoded_sha256': hashlib.sha256(payload).hexdigest(),
                           'decoded_bytes': len(payload), 'rows': number})
            pending, number = bytearray(), 0
        for row in rows:
            raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'
            if len(raw) > maximum:
                raise ValueError('one existing report record exceeds independent 16MB shard ceiling')
            if len(pending) + len(raw) > maximum or number == 1000:
                flush()
            pending.extend(raw)
            number += 1
            total += 1
        flush()
        tables[name] = {'rows': total, 'chunks': chunks}

    header = {key: value for key, value in document.items()
              if key not in ('routing', 'entry_parameters', 'environments', 'code_links')}
    table('code_links', document['code_links'])
    table('entry_parameters', document['entry_parameters'])
    routing = document['routing']
    header['routing'] = {key: value for key, value in routing.items() if type(value) is not list}
    for key, value in routing.items():
        if type(value) is list:
            table('routing.' + key, value)
    environment = document['environments']
    header['environments'] = {key: value for key, value in environment.items()
                              if key not in ('bindings', 'unresolved', 'files', 'metadata')}
    for key in ('bindings', 'unresolved', 'files', 'metadata'):
        table('environments.' + key, environment[key])
    raw = json.dumps(header, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > maximum:
        raise ValueError('report header exceeds independent 16MB shard ceiling')
    path = destination / 'header.json.gz'
    with path.open('xb') as out:
        with gzip.GzipFile(fileobj=out, mode='wb', filename='', mtime=0) as stream:
            stream.write(raw)
    digest, size = hashlib.sha256(), 0
    for text in json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).iterencode(document):
        block = text.encode()
        digest.update(block)
        size += len(block)
    manifest = {'schema': 'scar.partitioned-call-operand-links', 'schema_version': 1,
        'original_schema': document['schema'], 'original_schema_version': document['schema_version'],
        'canonical_document_sha256': digest.hexdigest(), 'canonical_document_bytes': size,
        'header': {**receipt(path), 'decoded_sha256': hashlib.sha256(raw).hexdigest(), 'decoded_bytes': len(raw)},
        'tables': tables, 'max_shard_decoded_bytes': maximum, 'max_rows_per_shard': 1000,
        'table_pointer_rule': 'dot-separated table names replace that original JSON array; header holds all other fields',
        'canonical_graphs_copied': False, 'whole_program_established': False, 'transformation_authorized': False}
    write_json(destination / 'manifest.json', manifest)
    return manifest
