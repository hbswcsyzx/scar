"""Explicit OS observation scopes for program interfaces, not OS internals.

These contracts describe requested selection. Neither an argv nor a successful
exit establishes loss-free delivery or effective seccomp acceleration.
"""
from __future__ import annotations


PROGRAM_INTERFACE_CALLS = (
    # Process/handle identity controls required by the existing continuity reader.
    'clone', 'clone3', 'fork', 'vfork', 'execve', 'execveat', 'exit', 'exit_group',
    'unshare', 'close_range', 'open', 'openat', 'openat2', 'creat', 'close',
    'dup', 'dup2', 'dup3', 'fcntl', 'pipe', 'pipe2', 'socket', 'socketpair',
    # File/range/materialization and program-visible metadata.
    'read', 'write', 'readv', 'writev', 'pread64', 'pwrite64', 'preadv', 'pwritev',
    'preadv2', 'pwritev2', 'lseek', 'stat', 'lstat', 'fstat', 'newfstatat', 'statx',
    'readlink', 'readlinkat', 'getcwd', 'chdir', 'fchdir', 'getdents', 'getdents64',
    'truncate', 'ftruncate', 'fallocate', 'fsync', 'fdatasync', 'sync_file_range',
    'rename', 'renameat', 'renameat2', 'link', 'linkat', 'unlink', 'unlinkat',
    'mkdir', 'mkdirat', 'rmdir', 'copy_file_range', 'sendfile', 'splice', 'tee', 'vmsplice',
    # Allocation/mapping interfaces; not allocator or VM implementation details.
    'brk', 'mmap', 'mremap', 'munmap', 'mprotect', 'madvise',
    'mlock', 'munlock', 'mlockall', 'munlockall',
    # External endpoints, device commands and explicit asynchronous IO interfaces.
    'bind', 'listen', 'connect', 'accept', 'accept4', 'getsockname', 'getpeername',
    'sendto', 'recvfrom', 'sendmsg', 'recvmsg', 'sendmmsg', 'recvmmsg', 'shutdown',
    'setsockopt', 'getsockopt', 'ioctl', 'getrandom',
    'poll', 'ppoll', 'select', 'pselect6', 'epoll_create', 'epoll_create1',
    'epoll_ctl', 'epoll_wait', 'epoll_pwait', 'epoll_pwait2', 'eventfd', 'eventfd2',
    'io_uring_setup', 'io_uring_enter', 'io_uring_register', 'io_setup', 'io_destroy',
    'io_submit', 'io_cancel', 'io_getevents', 'io_pgetevents',
    'wait4', 'waitid', 'kill', 'tkill', 'tgkill',
)


def selection_contract(profile):
    if profile not in ('all', 'program-interfaces'):
        raise ValueError('unknown OS capture selection profile')
    selected = PROGRAM_INTERFACE_CALLS if profile == 'program-interfaces' else ()
    return {
        'profile': profile,
        'expression': 'trace=' + (','.join(selected) if selected else 'all'),
        'explicit_syscalls': list(selected),
        'scope': 'PROGRAM_RESOURCE_INTERFACES' if selected else 'ALL_SYSCALLS',
        'excluded_scope': ['unlisted_syscalls', 'scheduler_and_thread_runtime_internals'] if selected else [],
        'kernel_filter': 'REQUESTED_NOT_VERIFIED' if selected else 'NOT_REQUESTED',
        'event_completeness': 'UNKNOWN',
        'effect_completeness': 'UNKNOWN',
        'absence_inference_authorized': False,
    }


def validate_launch_selection(intent, launch, options):
    """Check the exact declared scope against original actual-launch options.

    Old captures have no new declaration and retain their original checks.
    The caller must still run the existing actual-options/identity-control
    coverage validator; this function never substitutes for it.
    """
    first, second = intent.get('selection_contract'), launch.get('selection_contract')
    if first is None and second is None:
        return None
    if type(first) is not dict:
        raise ValueError('OS selection contract is missing or malformed')
    expected = selection_contract(first.get('profile'))
    if first != expected or second != expected or launch.get('selection_profile') != expected['profile']:
        raise ValueError('intent/launch OS selection contracts differ')
    selected = None
    for index, option in enumerate(options):
        expression = (options[index + 1] if option == '-e' and index + 1 < len(options)
                      else option[2:] if option.startswith('-e') and len(option) > 2 else None)
        if expression is not None and expression.startswith('trace='):
            selected = expression
    if (selected != expected['expression'] or
            ('--seccomp-bpf' in options) != (expected['kernel_filter'] == 'REQUESTED_NOT_VERIFIED')):
        raise ValueError('actual OS selection/filter request differs from its contract')
    return expected
