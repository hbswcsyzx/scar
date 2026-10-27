"""Independent bounded archive reconstruction; no target or source replay."""
from pathlib import Path
from io import BytesIO
import gzip
import hashlib
import json
import time

HERE = Path(__file__).resolve().parent
GATE = HERE.parent / 'first_stage_source_revision_current_20261025'
ROOT = HERE.parents[2]
START = time.monotonic()
stats = {'chunks': 0, 'rows': 0, 'decoded_bytes': 0, 'tables': {}}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def checked_chunk(row):
    path = Path(row['path'])
    assert path.is_relative_to(GATE) and path.is_file() and not path.is_symlink()
    raw = path.read_bytes()
    assert len(raw) == row['bytes']
    assert hashlib.sha256(raw).hexdigest() == row['sha256']
    assert row['decoded_bytes'] <= 16_000_000
    with gzip.GzipFile(fileobj=BytesIO(raw)) as stream:
        payload = stream.read(row['decoded_bytes'] + 1)
    assert len(payload) == row['decoded_bytes']
    assert hashlib.sha256(payload).hexdigest() == row['decoded_sha256']
    stats['chunks'] += 1
    stats['decoded_bytes'] += len(payload)
    return payload


class Table:
    def __init__(self, name, declaration):
        self.name, self.declaration = name, declaration

    def values(self):
        count = 0
        for chunk in self.declaration['chunks']:
            payload = checked_chunk(chunk)
            assert payload.endswith(b'\n') and payload.count(b'\n') == chunk['rows']
            assert chunk['rows'] <= 1000
            for line in payload.splitlines():
                # Confirm the stored row is independently parseable canonical
                # JSON before feeding its bytes into the reconstructed stream.
                assert canonical(json.loads(line)) == line
                count += 1
                stats['rows'] += 1
                yield line
        assert count == self.declaration['rows']
        stats['tables'][self.name] = count


def emit(value):
    if isinstance(value, Table):
        yield b'['
        for position, row in enumerate(value.values()):
            if position:
                yield b','
            yield row
        yield b']'
    elif isinstance(value, dict):
        yield b'{'
        for position, key in enumerate(sorted(value)):
            if position:
                yield b','
            yield canonical(key)
            yield b':'
            yield from emit(value[key])
        yield b'}'
    else:
        yield canonical(value)


manifest = json.loads((GATE / 'result/analysis/manifest.json').read_text())
summary = json.loads((GATE / 'summary.json').read_text())
document = json.loads(checked_chunk(manifest['header']))
for name, declaration in manifest['tables'].items():
    parts = name.split('.')
    parent = document
    for part in parts[:-1]:
        parent = parent[part]
    assert parts[-1] not in parent
    parent[parts[-1]] = Table(name, declaration)
digest, size = hashlib.sha256(), 0
for block in emit(document):
    digest.update(block)
    size += len(block)
assert digest.hexdigest() == manifest['canonical_document_sha256'] == summary['canonical_report_sha256']
assert size == manifest['canonical_document_bytes'] == summary['canonical_report_bytes']
producer = json.loads((GATE / 'participating-producer.json').read_text())
assert producer['all_imported_sources_unchanged'] and not producer['mismatches']
for row in producer['checked']:
    path = Path(row['path'])
    raw = path.read_bytes()
    assert len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
    copy = GATE / 'participating-source-evidence' / (row['sha256'] + '.py-source')
    assert copy.read_bytes() == raw
assert summary['reader_counts']['source_binder_runs'] == 1
assert summary['reader_counts']['completed_source_checkpoints'] == 0
assert summary['code_witness_activity']['compile_attempts'] == 0
assert summary['proof_reuse']['rule_version'] == 2
assert summary['proof_reuse']['static_membership_only']
assert not summary['proof_reuse']['old_body_or_activation_reused']
assert summary['owned_ancestor_reader_counts']['parent_compositions'] == 2
result = {
    'schema': 'scar.root-source-revision-archive-review', 'schema_version': 1,
    'status': 'PASS_BOUNDED_ARCHIVE_AND_RECORDED_PRODUCER_REVIEW',
    'canonical_document_sha256': digest.hexdigest(), 'canonical_document_bytes': size,
    'archive': stats, 'participating_sources_checked': len(producer['checked']),
    'actual_gate_session': 40820, 'actual_gate_exit': 0,
    'review_scope': 'all saved report chunks and canonical reconstruction; exact current and archived participating source bytes; selected terminal/proof invariants',
    'raw_trace_reopened': False, 'source_binder_reexecuted': False,
    'additional_graph_or_runtime_semantics_verified': False,
    'target_executed': False, 'whole_model_complete': False,
    'elapsed_seconds': time.monotonic() - START,
}
(HERE / 'review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({key: value for key, value in result.items() if key != 'archive'}, sort_keys=True))
