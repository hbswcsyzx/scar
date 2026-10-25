"""Small synthetic checks: missing witnesses versus corrupt source identity."""
import json
from pathlib import Path
from scar.trace.native_capture_batch import _SourceIndex, _MissingDependency, NativeCaptureBatchBudget

OUT = Path(__file__).resolve().parent
checks = []


def expect(call, missing):
    try:
        call()
    except ValueError as error:
        assert isinstance(error, _MissingDependency) == missing, (missing, type(error).__name__, str(error))
    else:
        raise AssertionError('expected rejection')


class Stub:
    node_ordinals = {2: 0}
    births = {}


stub = Stub()
stub.get = lambda *args, **kwargs: None
expect(lambda: _SourceIndex.selected(stub, {'nodes': [{'id': 2}]}, []), True)
checks.append('missing original archive record is MissingDependency')
stub.get = lambda *args, **kwargs: {'ordinal': 7}
expect(lambda: _SourceIndex.selected(stub, {'nodes': [{'id': 2}]}, []), False)
checks.append('original ETO ordinal mismatch is hard rejection')
source = {'nodes': [], 'artifacts': {'physical': {'sha256': '0' * 64}}}
interface = {'ports': {'inputs': [{'tensor': True, 'held': {'weak_token': 'weak:11:1',
    'physical_line': 10, 'marker_ordinal': 0, 'metadata': {'device': {'text': 'cpu'}, 'provider_allocation_id': 1}}}], 'outputs': []}}
stub.get = lambda *args, **kwargs: {'record': {'allocation': {'value': 'original-allocation'}}}
expect(lambda: _SourceIndex.selected(stub, source, [interface]), True)
checks.append('zero positive births is MissingDependency')
stub.births = {('cpu', 1): [1, 2]}
expect(lambda: _SourceIndex.selected(stub, source, [interface]), False)
checks.append('duplicate positive births is hard rejection')
tiny = OUT / 'integrity-source-check'
tiny.mkdir()
owner = _SourceIndex(tiny, NativeCaptureBatchBudget(), None)
owner.put('node', 2, 0, {'id': 2})
raw = owner.db.execute("SELECT payload FROM records WHERE kind='node' AND key='2'").fetchone()[0]
owner.db.execute("UPDATE records SET payload=? WHERE kind='node' AND key='2'", (b'{}',))
expect(lambda: owner.get('node', 2, optional=True), False)
checks.append('changed private payload is hard rejection')
owner.db.execute("DELETE FROM records WHERE kind='node' AND key='2'")
expect(lambda: owner.get('node', 2, optional=True), False)
checks.append('deleted previously indexed record is hard rejection even for optional lookup')
owner.db.commit()
owner.db.close()
print(json.dumps({'status': 'INTEGRITY_ABSENCE_CHECK_PASS', 'checks': checks,
                  'original_raw_reads': 0, 'archive_chunk_reads': 0, 'full_gate_run': False},
                 sort_keys=True, indent=2))
