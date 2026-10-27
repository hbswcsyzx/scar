"""Actual whole retained-observation association; no native graph replay."""
import json
from pathlib import Path

from scar.analysis.dispatch_sources import bind_dispatch_sources, query_dispatch_source
from scar.trace.capture_coordinates import bind_capture_coordinates

base = Path(__file__).resolve().parent
experiments = base.parent
capture = experiments / 'first_stage_lewm_dispatch_20261023'
coordinate_path = base / 'capture-coordinates.json'
coordinates = bind_capture_coordinates(capture, max_bytes=2_000_000_000,
                                       max_lines=2_000_000, profile_uri=str(coordinate_path))
coordinate_path.write_bytes(coordinates.payload)
report = bind_dispatch_sources(
    experiments / 'first_stage_source_bindings_reused_20261023/result',
    experiments / 'first_stage_joined_dispatch_20261023/result/native/dispatch-bridge.json.gz',
    coordinates, base / 'result',
)
queried = {}
for status, example in report['examples'].items():
    row = query_dispatch_source(base / 'result', example['marker_instance'])
    queried[status] = {'marker_instance': row['marker_instance'], 'status': row['status'],
                      'invocation': row['invocation'], 'definition': row['definition'],
                      'body': row['body'], 'region_activation': row['region_activation'],
                      'direct_callsite_established': row['direct_callsite_established']}
(base / 'query-results.json').write_text(json.dumps(queried, sort_keys=True, indent=2) + '\n')
print(json.dumps({'summary': report['summary'], 'frontiers': report['frontiers'],
                  'upstream_dispatch_gaps': report['upstream_dispatch_gaps'],
                  'source_frontiers': report['source_frontiers'],
                  'source_audit': report['source_audit'],
                  'query_statuses': sorted(queried), 'first_stage_complete': False}, sort_keys=True))
