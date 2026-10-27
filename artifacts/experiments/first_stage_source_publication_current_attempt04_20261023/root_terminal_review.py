"""Review terminal exports without replaying source, raw capture or the target."""
from hashlib import sha256
import gzip
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(path):
    return json.loads(path.read_text())


def check(raw, size, digest):
    assert len(raw) == size and sha256(raw).hexdigest() == digest


def main():
    summary = load(HERE / 'summary.json')
    dynamic = load(HERE / 'dynamic-audit.json')
    assert 'Exit status: 0' in (HERE / 'run.time.txt').read_text()
    assert summary['status'] == 'PASS_WITH_OPEN_MODEL_OBLIGATIONS'
    assert not summary['first_stage_complete'] and not summary['transformation_authorized']
    assert summary['current'] == dynamic
    assert dynamic['current_invocations'] == 100438 and dynamic['current_groups'] == 817
    assert (dynamic['current_body_groups'], dynamic['current_body_calls']) == (76, 6674)
    assert sorted(row['current_calls'] for row in dynamic['promoted_bodies'].values()) == [150, 900]
    assert summary['reader_counts']['frame_scans'] == summary['reader_counts']['operand_scans'] == 1
    assert summary['reader_counts']['source_binder_runs'] == 0
    assert not summary['code_compiled'] and not summary['target_executed']
    archive = HERE / 'result/analysis'
    manifest = load(archive / 'manifest.json')
    assert manifest['canonical_document_sha256'] == summary['canonical_report_sha256']
    assert manifest['canonical_document_bytes'] == summary['canonical_report_bytes'] == 104486803
    chunks = rows = decoded = 0
    for table in manifest['tables'].values():
        table_rows = 0
        for ref in table['chunks']:
            path = Path(ref['path']).resolve()
            assert path.parent == archive.resolve()
            stored = path.read_bytes()
            check(stored, ref['bytes'], ref['sha256'])
            raw = gzip.decompress(stored)
            check(raw, ref['decoded_bytes'], ref['decoded_sha256'])
            count = 0
            for line in raw.splitlines():
                json.loads(line)
                count += 1
            assert count == ref['rows']
            table_rows += count
            chunks += 1
            decoded += len(raw)
        assert table_rows == table['rows']
        rows += table_rows
    header = manifest['header']
    stored = Path(header['path']).read_bytes()
    check(stored, header['bytes'], header['sha256'])
    raw = gzip.decompress(stored)
    check(raw, header['decoded_bytes'], header['decoded_sha256'])
    json.loads(raw)
    producer = load(HERE / 'participating-producer.json')
    for ref in producer['checked']:
        copied = HERE / 'participating-source-evidence' / (ref['sha256'] + '.py-source')
        check(copied.read_bytes(), ref['bytes'], ref['sha256'])
    result = {'status': 'PASS_TERMINAL_EXPORT_AND_RETAINED_PRODUCER_BYTES',
              'chunks': chunks, 'rows': rows, 'decoded_chunk_bytes': decoded,
              'producer_files': len(producer['checked']), 'raw_capture_replayed': False,
              'source_relowered': False, 'source_semantics_reverified_here': False,
              'tuple_lifetime_established': False, 'first_stage_complete': False}
    (HERE / 'root-terminal-review.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
