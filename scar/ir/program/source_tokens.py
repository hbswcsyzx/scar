"""F1 lexical records; references are character spans, never raw-byte offsets."""
from dataclasses import dataclass

from .source_bytes import SourceBytesProfile, _digest


@dataclass(frozen=True, slots=True)
class TokenSpan:
    start: int
    end: int

    def __post_init__(self):
        if type(self.start) is not int or type(self.end) is not int or not 0 <= self.start <= self.end:
            raise ValueError('invalid F1 half-open span')


@dataclass(frozen=True, slots=True)
class TokenTextRef:
    kind: str
    start: int | None
    end: int | None
    literal_index: int | None

    def __post_init__(self):
        if self.kind == 'VIEW_RANGE':
            valid = self.literal_index is None and type(self.start) is int and type(self.end) is int and 0 <= self.start <= self.end
        else:
            valid = self.kind == 'INTERNED_LITERAL' and self.start is None and self.end is None and type(self.literal_index) is int and self.literal_index >= 0
        if not valid:
            raise ValueError('invalid F1 text reference')


@dataclass(frozen=True, slots=True)
class TokenExtent:
    view_chars: TokenSpan
    original_chars: TokenSpan
    view_utf8_bytes: TokenSpan


@dataclass(frozen=True, slots=True)
class NewlineRewrite:
    original_chars: TokenSpan
    view_chars: TokenSpan


@dataclass(frozen=True, slots=True)
class TokenView:
    sha256: str
    characters: int
    utf8_bytes: int
    newline_rewrites: tuple[NewlineRewrite, ...]

    def __post_init__(self):
        if not _digest(self.sha256) or any(type(x) is not int or x < 0 for x in (self.characters, self.utf8_bytes)):
            raise ValueError('invalid F1 view receipt')


@dataclass(frozen=True, slots=True)
class TokenType:
    code: int
    name: str


@dataclass(frozen=True, slots=True)
class ExactOperator:
    text: str
    code: int


@dataclass(frozen=True, slots=True)
class SourceTokensProfile:
    runtime: SourceBytesProfile
    api: str
    newline_rule: str
    warning_policy: str
    tokenize_sha256: str
    token_sha256: str
    native_tokenizer_origin: str
    native_tokenizer_binary: str
    native_tokenizer_sha256: str
    token_types: tuple[TokenType, ...]
    exact_operators: tuple[ExactOperator, ...]

    def __post_init__(self):
        if (self.api != 'stdlib.tokenize.generate_tokens.extra_tokens'
                or self.newline_rule != 'CRLF_AND_CR_TO_LF_NO_FINAL_NEWLINE_V1'
                or self.warning_policy != 'RECORD_ALL_ALWAYS_ISOLATED_V1'
                or not _digest(self.tokenize_sha256) or not _digest(self.token_sha256)
                or not _digest(self.native_tokenizer_sha256)):
            raise ValueError('invalid F1 lexer profile')


@dataclass(frozen=True, slots=True)
class SourceTokensInput:
    f0_document_sha256: str
    path: str
    namespace_root: str
    raw_sha256: str
    decoded_utf8_sha256: str | None
    decoding_status: str


@dataclass(frozen=True, slots=True)
class SourceToken:
    type: int
    exact_type: int
    string: TokenTextRef
    line: TokenTextRef
    start: tuple[int, int]
    end: tuple[int, int]
    source_extent: TokenExtent | None
    coordinate_kind: str

    def __post_init__(self):
        if self.coordinate_kind not in ('SOURCE', 'ZERO_WIDTH', 'SYNTHETIC_NEWLINE', 'VIRTUAL_ENDMARKER', 'VIRTUAL_COORDINATES'):
            raise ValueError('invalid F1 native-coordinate classification')
        if any(type(x) is not int or x < 0 for pair in (self.start, self.end) for x in pair):
            raise ValueError('invalid F1 native token position')


@dataclass(frozen=True, slots=True)
class TokenCoverage:
    covered: tuple[TokenSpan, ...]
    gaps: tuple[TokenSpan, ...]


@dataclass(frozen=True, slots=True)
class NativeTokenParameter:
    kind: str
    value: str | int | float | bool | None
    items: tuple['NativeTokenParameter', ...]

    def __post_init__(self):
        scalar_types = {'NONE': type(None), 'STR': str, 'INT': int, 'FLOAT': float, 'BOOL': bool, 'BYTES_BASE64': str}
        if self.kind == 'TUPLE':
            valid = self.value is None
        else:
            valid = self.kind in scalar_types and type(self.value) is scalar_types[self.kind] and not self.items
        if not valid:
            raise ValueError('invalid F1 native diagnostic parameter')


@dataclass(frozen=True, slots=True)
class NativeTokenAttribute:
    name: str
    value: NativeTokenParameter


@dataclass(frozen=True, slots=True)
class SourceTokenError:
    module: str
    exception_type: str
    message: str
    parameters: NativeTokenParameter
    attributes: tuple[NativeTokenAttribute, ...]
    coordinate_basis: str = 'NATIVE_EXCEPTION_DIAGNOSTIC_NOT_TOKEN_COORDINATES'


@dataclass(frozen=True, slots=True)
class SourceTokenWarning:
    category_module: str
    category_name: str
    message: str
    filename: str
    lineno: int
    line: str | None
    source_present: bool


@dataclass(frozen=True, slots=True)
class SourceTokensMaterial:
    input: SourceTokensInput
    profile: SourceTokensProfile
    max_tokens: int
    status: str
    actual_eof: bool
    view: TokenView | None
    text_pool: tuple[str, ...]
    tokens: tuple[SourceToken, ...]
    source_coverage: TokenCoverage | None
    error: SourceTokenError | None
    warnings: tuple[SourceTokenWarning, ...]
    schema: str = 'scar.source-tokens'
    schema_version: int = 1

    def __post_init__(self):
        if (self.schema != 'scar.source-tokens' or type(self.schema_version) is not int or self.schema_version != 1
                or type(self.max_tokens) is not int or self.max_tokens < 0
                or self.status not in ('TOKENIZED', 'TOKENIZER_ERROR', 'BUDGET_STOPPED', 'UPSTREAM_DECODING_ERROR')):
            raise ValueError('invalid F1 document envelope')
