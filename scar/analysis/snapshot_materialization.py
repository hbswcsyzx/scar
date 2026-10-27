"""Offline process entry for converting closed owned snapshots to reader JSONL."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--journal', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--receipt', required=True)
    parser.add_argument('--max-output-bytes', required=True, type=int)
    parser.add_argument('--max-line-bytes', type=int, default=2_000_000)
    args = parser.parse_args(argv)
    from scar.analysis.snapshot_journal import materialize_snapshot_journal
    try:
        result = materialize_snapshot_journal(args.journal, args.out,
            expected_sha256=args.sha256,
            max_total_bytes=args.max_output_bytes,
            max_record_bytes=args.max_line_bytes,
            max_output_bytes=args.max_output_bytes, max_output_line_bytes=args.max_line_bytes)
    except Exception as error:
        with Path(args.receipt).open('x') as stream:
            json.dump({'status': 'FAILED', 'exception': type(error).__name__,
                       'whole_program_complete': False}, stream)
        return 1
    with Path(args.receipt).open('x') as stream:
        result['postprocessor'] = {'process_id': os.getpid(), 'parent_process_id': os.getppid(),
                                   'role': 'SCAR_OFFLINE_POSTPROCESSING'}
        json.dump(result, stream, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
        stream.write('\n')
    return 0 if result.get('complete') is True and result['output'].get('published') is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
