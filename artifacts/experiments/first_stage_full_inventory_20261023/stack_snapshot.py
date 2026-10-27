"""One stack-only diagnostic in this experiment's own analysis process."""
import sys
import traceback
from pathlib import Path

output = Path(__file__).resolve().parent / 'stack-snapshot.txt'
with output.open('w') as stream:
    for ident, frame in sys._current_frames().items():
        stream.write(f'Thread {ident}\n')
        traceback.print_stack(frame, file=stream)
