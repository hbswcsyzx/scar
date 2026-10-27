"""Conserve original graph members/uses/constraints in the compact query."""
import gzip
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.program_region_view import ProgramRegionView, read_source_region
from scar.ir.program.codec import loads
from scar.ir.program.ids import RegionID
from scar.ir.program.source import LoweringMetadata
from scar.ir.program.structured import StructuredBodyModel
from scar.ir.record_codec import decode, encode

HERE = Path(__file__).resolve().parent
started = time.monotonic()
receipt = json.loads((HERE / 'input.json').read_text())
stored = Path(receipt['uri']).read_bytes()
assert sha256(stored).hexdigest() == receipt['physical_sha256']
document = json.loads(gzip.decompress(stored))
graph = loads(json.dumps(document['graph']))
session = ProgramRegionView(graph, metadata=decode(LoweringMetadata, document['metadata']),
                            structured=decode(StructuredBodyModel, document['structured']))
compact = json.loads((HERE / 'compact-v2.json').read_text())
expanded = json.loads((HERE / 'expanded-v2.json').read_text())
members = [op for node in compact['nodes'].values() for op in node['members']]
assert len(set(members)) == len(members) == len(graph.operations)
assert set(members) == {op.id.wire for op in graph.operations}
assert compact['summary']['original_uses'] == expanded['summary']['original_uses'] == 714
assert compact['summary']['crossing_uses'] + compact['summary']['internal_uses'] == 714
assert len(expanded['uses']) == 714
assert compact['control'] == [dict(edge, source=next(
    k for k, node in compact['nodes'].items() if edge['operation'] in node['members']),
    target=(next((k for k, node in compact['nodes'].items()
                  if node['block'] == edge['successor']['block']['wire']), None)
            if 'successor' in edge else None)) for edge in expanded['control']]
assert compact['exits'] == expanded['exits']
assert compact['resources'] == expanded['resources']
assert compact['resource_uses'] == expanded['resource_uses']
assert compact['resource_requirements'] == expanded['resource_requirements']
original_accesses = [dict(operation=op.id.wire, access=encode(access))
                     for op in graph.operations for access in op.accesses]
compact_accesses = [access for node in compact['nodes'].values() for access in node['accesses']]
canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
assert canonical(original_accesses) == canonical(compact_accesses)
for key, node in compact['nodes'].items():
    original = session.expand(key)
    assert [op.id.wire for op in original] == node['members']
    assert node['effects_complete'] == all(op.effects_complete for op in original)
one = next(iter(session.index.values))
assert session.value(one)['value'] == session.index.values[one]
rejected = []
for name, kwargs in (
    ('wrong_sha', dict(expected_sha256='0' * 64)),
    ('wrong_region', dict(expected_sha256=receipt['physical_sha256'], region=RegionID('absent'))),
):
    try:
        read_source_region(receipt['uri'], **kwargs)
    except ValueError:
        rejected.append(name)
    else:
        raise AssertionError(name)
result = dict(status='ACTUAL_ORIGINAL_CORE_VIEW_PASS', elapsed_s=time.monotonic() - started,
              input=receipt, compact=compact['summary'], expanded=expanded['summary'],
              state_accesses=len(original_accesses), original_control_edges=len(compact['control']),
              compact_output_bytes=(HERE / 'compact-v2.json').stat().st_size,
              expanded_output_bytes=(HERE / 'expanded-v2.json').stat().st_size,
              rejected=rejected, original_members_preserved=True, original_uses_preserved=True,
              effects_preserved=True, cfg_preserved=True, source_context_replayed=False,
              deleted_program_work=0, target_executed=False, whole_program_complete=False)
with (HERE / 'verification.json').open('x') as stream:
    json.dump(result, stream, indent=2); stream.write('\n')
print(json.dumps(result))
