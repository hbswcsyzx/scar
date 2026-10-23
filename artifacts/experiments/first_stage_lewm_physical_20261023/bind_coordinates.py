"""Validate the closed real capture and retain its common execution identity."""
import json
from pathlib import Path
from scar.trace.capture_coordinates import bind_capture_coordinates

root = Path(__file__).resolve().parent
out = root / 'coordinate-preflight'
out.mkdir(exist_ok=False)
coordinates = bind_capture_coordinates(root, max_bytes=2_000_000_000,
    max_lines=2_000_000, profile_uri=str(out / 'capture-coordinates.json'))
(out / 'capture-coordinates.json').write_bytes(coordinates.payload)
(out / 'summary.json').write_text(json.dumps(coordinates.report['counts'], indent=2) + '\n')
print(json.dumps(coordinates.report['counts']))
