"""Pack existing source-publication selections into independent body fragments."""
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import encode, loads
from scar.store.source_fragments import SourceFragmentBudget, SourceFragmentWriter


def store_source_fragments_cli(args):
    started = time.monotonic()
    selection = Path(args.selection).absolute()
    if selection.is_symlink() or not selection.is_file():
        raise ValueError('source selection must be an existing regular file')
    before = selection.stat()
    if before.st_size > 8_000_000:
        raise ValueError('source selection exceeds 8MB metadata limit')
    raw = selection.read_bytes()
    after = selection.stat()
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if stamp(before) != stamp(after) or sha256(raw).hexdigest() != args.sha256:
        raise ValueError('source selection differs from its expected stored SHA256')
    document = loads(raw.decode('utf-8'))
    requests = document['requests']
    if type(requests) is not list or not requests:
        raise ValueError('source selection needs a nonempty original requests list')
    if args.limit is not None and (type(args.limit) is not int or args.limit < 1):
        raise ValueError('source fragment limit must be positive')
    output = Path(args.out).absolute()
    if output.exists():
        raise ValueError('source fragment output directory must be fresh')
    budget = SourceFragmentBudget(max_stored_input_bytes=args.max_stored_bytes,
        max_decoded_input_bytes=args.max_decoded_bytes, max_output_bytes=args.max_output_bytes,
        max_contexts=args.max_contexts, seconds=args.max_seconds)
    writer = SourceFragmentWriter(output, budget=budget)
    rows = []
    selected = requests if args.limit is None else requests[:args.limit]
    for request in selected:
        if type(request) is not dict or set(request) != {'entry_key', 'source_program'}:
            raise ValueError('expected original source publication request')
        source = request['source_program']
        locator = SourceArtifactLocator(
            ProviderArtifact(source['uri'], source['physical_sha256'], source['physical_bytes'], source['representation']),
            source['decoded_sha256'], source['decoded_bytes'],
            'gzip-canonical-json' if Path(source['uri']).suffix == '.gz' else 'canonical-json')
        fragment = writer.write(locator)
        rows.append({'entry_key': request['entry_key'], 'original': encode(locator), 'fragment': encode(fragment)})
    result = {'schema': 'scar.source-fragment-selection', 'schema_version': 1,
              'selection': {'uri': str(selection), 'sha256': args.sha256, 'bytes': len(raw)},
              'selected': len(rows), 'remaining': len(requests) - len(rows),
              'bodies': rows, 'costs': writer.finish(),
              'qualification': 'ARCHIVE_SPLIT_ONLY; original IDs retained; source admission unchanged',
              'target_executed': False, 'transformation_authorized': False}
    result['elapsed_s'] = time.monotonic() - started
    manifest = output / 'manifest.json'
    with manifest.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': 'FRAGMENTS_STORED', 'manifest': str(manifest),
                      'bodies': len(rows), 'remaining': result['remaining'],
                      'elapsed_s': result['elapsed_s'], 'costs': result['costs']}))
    return 0
