"""Public query for a native input's original, same-capture allocation."""
from __future__ import annotations

import json
from pathlib import Path


def query_native_allocation_cli(args):
    from scar.analysis.native_input_storage_bridge import query_native_input_allocation
    from scar.ir.program.providers import ProviderArtifact
    from scar.ir.record_codec import encode

    def artifact(path, digest, schema):
        path = Path(path).absolute()
        return ProviderArtifact(str(path), digest, path.stat().st_size, schema)

    path = None if args.path is None else json.loads(args.path)
    if path is not None and (type(path) is not list or
            any(type(index) is not int or index < 0 for index in path)):
        raise ValueError('--path must be a JSON list of nonnegative integer slot indices')
    result = query_native_input_allocation(
        artifact(args.navigation, args.navigation_sha256, 'scar.native-input-port-navigation'),
        artifact(args.storage_index, args.storage_sha256, 'scar.tensor-storage-locator-index'),
        row=args.row, path=None if path is None else tuple(path),
        derive_region=args.derive_region,
        max_input_bytes=args.max_input_bytes, max_seconds=args.max_seconds)
    payload = json.dumps(encode(result), ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.out:
        with Path(args.out).open('x', encoding='utf-8') as stream:
            stream.write(payload)
    else:
        print(payload, end='')
    return 0


def register_native_allocation_query(sub):
    parser = sub.add_parser('query-native-allocation',
        help='connect an original native input to its allocation and receipt-referenced ETO geometry when available')
    for name in ('navigation', 'navigation-sha256', 'storage-index', 'storage-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--row', type=int, help='original native metadata row ordinal')
    parser.add_argument('--path', help='original input slot path as a JSON list, requires --row')
    parser.add_argument('--derive-region', action='store_true',
        help='also run the existing pinned valid-Tensor-bounds protocol; ETO-observed geometry is returned independently')
    parser.add_argument('--max-input-bytes', type=int, default=256_000_000)
    parser.add_argument('--max-seconds', type=int, default=60)
    parser.add_argument('--out', help='fresh JSON query result; otherwise stdout')
    parser.set_defaults(func=query_native_allocation_cli)
    read = sub.add_parser('query-native-read',
        help='query original native input/use/state, conditional read, symbolic payload and allocation together')
    read.add_argument('--read', required=True, help='closed native tensor read artifact')
    read.add_argument('--sha256', required=True)
    read.add_argument('--max-input-bytes', type=int, default=256_000_000)
    read.add_argument('--max-seconds', type=int, default=60)
    read.add_argument('--out', help='fresh graph view JSON; otherwise stdout')
    read.set_defaults(func=query_native_read_cli)


def query_native_read_cli(args):
    from scar.analysis.program_query import query_native_read
    from scar.ir.program.providers import ProviderArtifact
    path = Path(args.read).absolute()
    artifact = ProviderArtifact(str(path), args.sha256, path.stat().st_size, 'scar.native-tensor-read')
    result = query_native_read(artifact, max_input_bytes=args.max_input_bytes, max_seconds=args.max_seconds)
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.out:
        with Path(args.out).open('x', encoding='utf-8') as stream:
            stream.write(payload)
    else:
        print(payload, end='')
    return 0
