"""Point observations of exact builtin stream backing, never a resource graph.

Only saved builtin descriptors are used. A buffered/text receiver can wrap a
custom raw object, so exact receiver type alone does not authorize fileno().
The builtin chain must end at exact FileIO; its saved C fileno descriptor is
called directly. No tell, flush, contents, filename or FD-table lookup occurs.
FD/fstat observations are non-atomic and do not establish handle lifetime,
logical contents, cross-call identity, persistence or readiness.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import inspect
import io
import os
import time


class BackingStatus(str, Enum):
    OBSERVED = 'OBSERVED'
    MEMORY_STREAM = 'MEMORY_STREAM'
    UNSUPPORTED_CHAIN = 'UNSUPPORTED_CHAIN'
    CHAIN_FAILED = 'CHAIN_FAILED'
    FILENO_FAILED = 'FILENO_FAILED'
    FSTAT_FAILED = 'FSTAT_FAILED'


@dataclass(frozen=True, slots=True)
class StreamBackingStat:
    device: int
    inode: int
    mode: int
    rdev: int
    size_bytes: int

    def __post_init__(self):
        if any(type(v) is not int or v < 0 for v in (self.device,self.inode,self.mode,self.rdev)) or type(self.size_bytes) is not int:
            raise ValueError('stream fstat fields must be their exact integer observations')


@dataclass(frozen=True, slots=True)
class StreamBackingFailure:
    stage: str
    exception_type: str
    errno: int | None

    def __post_init__(self):
        if (self.stage not in ('BACKING_CHAIN','FILENO','FSTAT')
                or type(self.exception_type) is not str or not self.exception_type
                or self.errno is not None and type(self.errno) is not int):
            raise ValueError('stream backing failure must retain its actual stage/type/errno')


@dataclass(frozen=True, slots=True)
class StreamBackingObservation:
    status: BackingStatus
    started_ns: int
    finished_ns: int
    chain_types: tuple[str, ...]
    fd: int | None = None
    stat: StreamBackingStat | None = None
    failure: StreamBackingFailure | None = None
    phase: str = 'CALL_BEFORE_INVOKE'
    clock: str = 'MONOTONIC_NS'

    def __post_init__(self):
        if (type(self.status) is not BackingStatus or self.phase != 'CALL_BEFORE_INVOKE'
                or self.clock != 'MONOTONIC_NS' or type(self.started_ns) is not int or self.started_ns < 0
                or type(self.finished_ns) is not int or self.finished_ns < self.started_ns
                or type(self.chain_types) is not tuple or not 1 <= len(self.chain_types) <= 4
                or any(type(name) is not str or not name for name in self.chain_types)
                or self.fd is not None and (type(self.fd) is not int or self.fd < 0)
                or self.stat is not None and type(self.stat) is not StreamBackingStat
                or self.failure is not None and type(self.failure) is not StreamBackingFailure):
            raise ValueError('invalid builtin stream backing point observation')
        observed = self.status is BackingStatus.OBSERVED
        failed = {BackingStatus.CHAIN_FAILED:'BACKING_CHAIN',BackingStatus.FILENO_FAILED:'FILENO',BackingStatus.FSTAT_FAILED:'FSTAT'}.get(self.status)
        if ((self.stat is not None) != observed
                or (self.fd is not None) != (observed or self.status is BackingStatus.FSTAT_FAILED)
                or (self.failure is not None) != (failed is not None)
                or failed is not None and self.failure.stage != failed):
            raise ValueError('stream backing status does not match its actual fields/failure')


_FILE = io.FileIO
_MEMORY = frozenset((io.BytesIO,io.StringIO))
# Getsets bypass per-instance shadow attributes. Never invoke a raw object's
# possibly overridden fileno, even when the enclosing buffer is exact builtin.
_CHILD = {cls:inspect.getattr_static(cls,'raw') for cls in (io.BufferedReader,io.BufferedWriter,io.BufferedRandom)}
_CHILD[io.TextIOWrapper] = inspect.getattr_static(io.TextIOWrapper,'buffer')
_FILENO = inspect.getattr_static(_FILE,'fileno')
_FSTAT = os.fstat
_NOW = time.monotonic_ns


_TYPE_NAMES={cls:cls.__module__+'.'+cls.__qualname__ for cls in (*_MEMORY,*_CHILD,_FILE,io.BufferedRWPair)}


def _type_name(value):
    # Unknown objects/metaclasses are not introspected; even formatting their
    # type could dispatch user descriptors. The missing chain stays explicit.
    return next((name for cls,name in _TYPE_NAMES.items() if type(value) is cls),'<unsupported-nonbuiltin>')


def observe_stream_backing(receiver):
    """Called only at an original accepted stream CALL observation.

    Local receiver/raw references die before return; no application object is
    stored in the sidecar. Probe failures are evidence about this observation,
    distinct from the program's later C_RETURN/C_RAISE completion.
    """
    started=_NOW();chain=[];current=receiver;seen=set();stage='BACKING_CHAIN';fd=None
    try:
        while True:
            chain.append(_type_name(current))
            cls=type(current)
            if any(cls is known for known in _MEMORY):
                return StreamBackingObservation(BackingStatus.MEMORY_STREAM,started,_NOW(),tuple(chain))
            if cls is _FILE:
                break
            descriptor=next((item for known,item in _CHILD.items() if cls is known),None)
            if descriptor is None or id(current) in seen or len(chain) >= 4:
                return StreamBackingObservation(BackingStatus.UNSUPPORTED_CHAIN,started,_NOW(),tuple(chain))
            seen.add(id(current))
            current=descriptor.__get__(current,cls)
        stage='FILENO'
        fd=_FILENO(current)
        stage='FSTAT'
        actual=_FSTAT(fd)
        facts=StreamBackingStat(actual.st_dev,actual.st_ino,actual.st_mode,actual.st_rdev,actual.st_size)
        return StreamBackingObservation(BackingStatus.OBSERVED,started,_NOW(),tuple(chain),fd,facts)
    except (OSError,ValueError) as error:
        failure=StreamBackingFailure(stage,type(error).__name__,error.errno if isinstance(error,OSError) else None)
        status={'BACKING_CHAIN':BackingStatus.CHAIN_FAILED,'FILENO':BackingStatus.FILENO_FAILED,'FSTAT':BackingStatus.FSTAT_FAILED}[stage]
        return StreamBackingObservation(status,started,_NOW(),tuple(chain),fd if stage=='FSTAT' else None,failure=failure)
