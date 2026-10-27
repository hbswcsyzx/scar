"""Bounded real stdlib/OS witnesses; not a SCAR adapter or CUDA experiment."""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from pathlib import Path
import errno
import json
import os
import tempfile
from threading import Event


def file_witnesses(root):
    path = root / 'data'
    path.write_bytes(b'0123456789')
    active = set()

    def opened(path):
        fd = os.open(path, os.O_RDONLY)
        active.add(fd)
        return fd

    def closed(fd):
        os.close(fd)
        active.remove(fd)

    try:
        first = opened(path)
        duplicate = os.dup(first)
        active.add(duplicate)
        independent = opened(path)
        initial = os.read(first, 2)
        through_duplicate = os.read(duplicate, 2)
        through_independent = os.read(independent, 2)
        assert (initial, through_duplicate, through_independent) == (b'01', b'23', b'01')
        old_descriptor = first
        closed(first)
        try:
            os.fstat(old_descriptor)
        except OSError as error:
            assert error.errno == errno.EBADF
        else:
            raise AssertionError('closed descriptor remained valid')
        after_close = os.read(duplicate, 2)
        assert after_close == b'45'
        yield {'case': 'dup-open-offset-close', 'status': 'PASS',
               'first': initial.decode(), 'dup': through_duplicate.decode(),
               'independent_open': through_independent.decode(),
               'dup_after_other_handle_closed': after_close.decode()}

        other = root / 'other'
        other.write_bytes(b'new-resource')
        rebound = opened(other)
        if rebound != old_descriptor:
            os.dup2(rebound, old_descriptor)
            active.add(old_descriptor)
        same_number = os.read(old_descriptor, 3)
        assert same_number == b'new'
        yield {'case': 'descriptor-number-reuse', 'status': 'PASS',
               'descriptor': old_descriptor, 'new_read': same_number.decode(),
               'same_integer_is_not_same_lifetime': True}

        old_file = opened(path)
        replacement = root / 'replacement'
        replacement.write_bytes(b'replacement')
        os.replace(replacement, path)
        new_file = opened(path)
        before = os.read(old_file, 3)
        after = os.read(new_file, 3)
        assert (before, after) == (b'012', b'rep')
        yield {'case': 'same-path-new-binding', 'status': 'PASS',
               'old_open_read': before.decode(), 'new_open_read': after.decode()}
    finally:
        for fd in tuple(active):
            closed(fd)

    output = root / 'buffered'
    with output.open('wb', buffering=8192) as stream:
        written = stream.write(b'abc')
        before_flush = output.read_bytes()
        assert written == 3 and before_flush == b''
        stream.flush()
        after_flush = output.read_bytes()
        assert after_flush == b'abc'
        os.fsync(stream.fileno())
        yield {'case': 'buffered-write-flush-fsync', 'status': 'PASS',
               'write_return': written, 'before_flush_bytes': len(before_flush),
               'after_flush_bytes': len(after_flush), 'fsync_returned': True,
               'power_loss_durability_tested': False}


def asynchronous_witnesses():
    started, release = Event(), Event()
    partial = []

    def failing_work():
        partial.append('written-before-failure')
        started.set()
        assert release.wait(5), 'bounded witness release timed out'
        raise ValueError('intentional partial-work failure')

    with ThreadPoolExecutor(max_workers=1) as pool:
        failed = pool.submit(failing_work)
        try:
            assert started.wait(5), 'worker did not start'
            assert partial == ['written-before-failure'] and not failed.done()
            cancelled_running = failed.cancel()
            assert cancelled_running is False and not failed.done()
            release.set()
            try:
                failed.result(timeout=5)
            except ValueError as error:
                assert str(error) == 'intentional partial-work failure'
            else:
                raise AssertionError('intentional failure disappeared')
            assert failed.done() and not failed.cancelled()
            assert partial == ['written-before-failure']
            yield {'case': 'host-submit-partial-failure', 'status': 'PASS',
                   'returned_future_before_completion': True,
                   'cancel_running_return': cancelled_running,
                   'failed_but_effect_retained': list(partial)}
        finally:
            release.set()

    started, release = Event(), Event()
    executed = []

    def blocker():
        started.set()
        assert release.wait(5), 'bounded queue witness timed out'

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(blocker)
        try:
            assert started.wait(5), 'queue blocker did not start'
            queued = pool.submit(lambda: executed.append('unexpected execution'))
            assert queued.cancel() and queued.done() and queued.cancelled()
            try:
                queued.result(timeout=5)
            except CancelledError:
                pass
            else:
                raise AssertionError('cancelled work returned normally')
            release.set()
            first.result(timeout=5)
            assert not executed
            yield {'case': 'queued-cancellation-is-not-success', 'status': 'PASS',
                   'done': queued.done(), 'cancelled': queued.cancelled(),
                   'executed': list(executed)}
        finally:
            release.set()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='scar-resource-model-witness-') as directory:
        results = [*file_witnesses(Path(directory)), *asynchronous_witnesses()]
    assert len(results) == 6
    print(json.dumps({'scope': 'six real stdlib CPU/OS witnesses, not SCAR product or CUDA',
                      'cases': results, 'status': 'PASS', 'owned_temporary_removed': not Path(directory).exists()},
                     indent=2))
