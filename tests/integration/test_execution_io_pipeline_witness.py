"""Real owned OS observations; declared model correspondence is separate."""
import hashlib
from pathlib import Path
import runpy

import pytest


WITNESS = Path(__file__).resolve().parents[2] / 'scripts/witness_io_pipeline.py'


@pytest.mark.parametrize('case', ('file', 'file_raise'))
def test_real_file_pipeline_buffering_and_exception_cleanup(case):
    run_case = runpy.run_path(str(WITNESS))['run_case']
    result = run_case(case)
    observed = result['observed']
    assert observed['accepted_bytes'] == observed['requested_bytes'] == 8
    assert observed['visible_before_explicit_flush_bytes'] == 0
    assert observed['final_bytes'] == 8
    assert observed['final_sha256'] == hashlib.sha256(b'BCDEFGHI').hexdigest()
    assert observed['closed']
    assert observed['explicit_flush_returned'] == observed['fsync_returned'] == (case == 'file')
    assert observed['host_exception'] == ('HostFailure' if case == 'file_raise' else None)
    if case == 'file':
        assert observed['visible_after_explicit_flush_bytes'] == 8
    else:
        assert 'visible_after_explicit_flush_bytes' not in observed
    _assert_receipt(result)


def test_real_host_raise_precedes_partial_worker_failure_and_view_release():
    run_case = runpy.run_path(str(WITNESS))['run_case']
    result = run_case('pending_raise')
    observed = result['observed']
    assert observed['host_exception'] == 'HostFailure'
    assert not observed['work_done_at_host_raise']
    assert observed['buffer_nonzero_bytes_at_host_raise'] == 0
    assert observed['work_exception'] == 'PartialWorkFailure'
    assert observed['work_done'] and observed['this_view_released']
    assert observed['actual_bytes'] == 4 < observed['requested_bytes'] == 8
    assert observed['final_sha256'] == hashlib.sha256(b'BCDE' + bytes(4)).hexdigest()
    positions = {(row['action'], row['phase']): row['sequence'] for row in result['events']}
    assert positions['submit_wrapper', 'raise'] < positions['work', 'partial_write']
    assert positions['work', 'partial_write'] < positions['borrow', 'release']
    assert positions['borrow', 'release'] < positions['work_observer', 'terminal']
    _assert_receipt(result)


def _assert_receipt(result):
    assert result['worker_returncode'] == 0
    assert result['owned_workspace_removed_after_worker_exit']
    assert not Path(result['owned_workspace']).exists()
    assert not result['source_runtime_verified'] and not result['transformation_authorized']
    assert result['events'] and result['limitations']
