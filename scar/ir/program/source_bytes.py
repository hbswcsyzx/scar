"""F0 material records: original bytes and their encoding interpretation only."""
from dataclasses import dataclass
from pathlib import PurePosixPath
import re


def _text(value):
    return type(value) is str and bool(value) and '\0' not in value


def _digest(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _version(value):
    return (type(value) is tuple and len(value) == 5
        and all(type(part) is int and part >= 0 for part in (*value[:3], value[4]))
        and type(value[3]) is str and value[3] in ('alpha', 'beta', 'candidate', 'final'))


@dataclass(frozen=True, slots=True)
class SourceBytesProfile:
    implementation: str
    implementation_version: tuple[int, int, int, str, int]
    version: tuple[int, int, int, str, int]
    version_string: str
    hexversion: int
    cache_tag: str | None
    rule: str = 'STDLIB_DETECT_ENCODING_RAW_DECODE_F0_V1'
    decoded_text_encoding: str = 'utf-8'
    decoded_text_errors: str = 'strict'

    def __post_init__(self):
        if (not _text(self.implementation) or not _version(self.implementation_version)
                or not _version(self.version) or not _text(self.version_string)
                or type(self.hexversion) is not int or self.hexversion < 1
                or self.cache_tag is not None and not _text(self.cache_tag)
                or self.rule != 'STDLIB_DETECT_ENCODING_RAW_DECODE_F0_V1'
                or self.decoded_text_encoding != 'utf-8' or self.decoded_text_errors != 'strict'):
            raise ValueError('unsupported F0 source interpretation profile')


@dataclass(frozen=True, slots=True)
class SourceBytesError:
    stage: str
    exception_type: str
    message: str
    reason: str | None
    encoding: str | None
    start: int | None
    end: int | None
    index_basis: str | None
    lineno: int | None
    offset: int | None
    end_lineno: int | None
    end_offset: int | None

    def __post_init__(self):
        if (self.stage not in ('ENCODING', 'DECODING', 'DECODED_TEXT_ENCODING')
                or not _text(self.exception_type) or type(self.message) is not str
                or any(value is not None and type(value) is not str
                    for value in (self.reason, self.encoding))
                or any(value is not None and type(value) is not int
                    for value in (self.start, self.end, self.lineno, self.offset, self.end_lineno, self.end_offset))
                or (self.start is None) != (self.end is None)
                or self.start is not None and not 0 <= self.start <= self.end
                or self.index_basis not in (None, 'RAW_INPUT', 'DECODED_TEXT', 'EXCEPTION_OBJECT')):
            raise ValueError('invalid structured F0 encoding error')


@dataclass(frozen=True, slots=True)
class SourceRawBytes:
    base64: str
    sha256: str
    size_bytes: int

    def __post_init__(self):
        if type(self.base64) is not str or not _digest(self.sha256) or type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError('invalid original F0 bytes receipt')


@dataclass(frozen=True, slots=True)
class SourceBytesDecoding:
    status: str
    encoding: str | None
    decoded_utf8_sha256: str | None
    characters: int | None
    error: SourceBytesError | None

    def __post_init__(self):
        if (self.encoding is not None and not _text(self.encoding)
                or self.characters is not None and (type(self.characters) is not int or self.characters < 0)
                or self.decoded_utf8_sha256 is not None and not _digest(self.decoded_utf8_sha256)
                or self.error is not None and type(self.error) is not SourceBytesError):
            raise ValueError('invalid F0 decoded fields')
        if self.status == 'DECODED':
            valid = self.encoding is not None and self.characters is not None and self.decoded_utf8_sha256 is not None and self.error is None
        else:
            stages = {'ENCODING_ERROR': 'ENCODING', 'DECODE_ERROR': 'DECODING',
                'DECODED_TEXT_ENCODING_ERROR': 'DECODED_TEXT_ENCODING'}
            valid = (self.status in stages and self.error is not None
                and self.error.stage == stages[self.status] and self.decoded_utf8_sha256 is None
                and (self.encoding is None) == (self.status == 'ENCODING_ERROR')
                and (self.characters is not None) == (self.status == 'DECODED_TEXT_ENCODING_ERROR'))
        if not valid:
            raise ValueError('F0 decoding status contradicts its fields')


@dataclass(frozen=True, slots=True)
class SourceBytesMaterial:
    path: str
    namespace_root: str
    profile: SourceBytesProfile
    raw: SourceRawBytes
    decoding: SourceBytesDecoding
    schema: str = 'scar.source-bytes'
    schema_version: int = 1

    def __post_init__(self):
        if self.schema != 'scar.source-bytes' or type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError('unsupported source-bytes schema')
        for value in (self.path, self.namespace_root):
            if (not _text(value) or not PurePosixPath(value).is_absolute()
                    or str(PurePosixPath(value)) != value or '..' in PurePosixPath(value).parts):
                raise ValueError('F0 paths must be absolute and lexically normalized')
        if self.path == self.namespace_root or not PurePosixPath(self.path).is_relative_to(self.namespace_root):
            raise ValueError('F0 source path must be inside its declared namespace')
        for value, kind in ((self.profile, SourceBytesProfile), (self.raw, SourceRawBytes), (self.decoding, SourceBytesDecoding)):
            if type(value) is not kind:
                raise TypeError('F0 requires exact ' + kind.__name__)
            value.__post_init__()
