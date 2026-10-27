"""Public commands for reference indexes over original Tensor storage facts."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import decode, encode, loads


def _document(path, expected_sha256=None):
    """Read a small request, never another copy of the underlying graph."""
    source = Path(path)
    if not source.is_file() or source.stat().st_size > 65_536:
        raise ValueError('Tensor storage request must be a file of at most 64 KiB')
    with source.open('rb') as stream:
        raw = stream.read(65_537)
    if len(raw) > 65_536:
        raise ValueError('Tensor storage request exceeds 64 KiB')
    if expected_sha256 is not None and sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Tensor storage request SHA256 differs')
    result = loads(raw.decode('utf-8'))
    if type(result) is not dict:
        raise ValueError('Tensor storage request must be a JSON object')
    return result


def _output(result, destination):
    payload = json.dumps(encode(result), ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if destination:
        with Path(destination).open('x', encoding='utf-8') as stream:
            stream.write(payload)
    else:
        print(payload, end='')


def build_tensor_storage_index_cli(args):
    from scar.analysis.tensor_storage_index import build_tensor_storage_reference_index

    request = _document(args.selection, args.sha256)
    if set(request) != {'bundle', 'capture_model', 'eto_source'}:
        raise ValueError('selection requires bundle, capture_model and eto_source artifact receipts')
    receipt = build_tensor_storage_reference_index(
        *(decode(ProviderArtifact, request[key]) for key in ('bundle', 'capture_model', 'eto_source')),
        args.out, max_input_bytes=args.max_input_bytes, max_seconds=args.max_seconds,
        max_output_bytes=args.max_output_bytes)
    _output(receipt, None)
    return 0


def query_tensor_storage_cli(args):
    from scar.analysis.tensor_storage_index import query_tensor_storage_source

    path = Path(args.index).absolute()
    receipt = ProviderArtifact(str(path), args.sha256, path.stat().st_size,
                               'scar.tensor-storage-locator-index')
    association = (None if args.source_fact is None else
                   decode(ProviderFactReference, _document(args.source_fact)))
    result = query_tensor_storage_source(
        receipt, association, region_id=args.region,
        max_input_bytes=args.max_input_bytes, max_seconds=args.max_seconds)
    _output(result, args.out)
    return 0
