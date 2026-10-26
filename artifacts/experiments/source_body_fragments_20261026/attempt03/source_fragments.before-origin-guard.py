"""Receipt-bound source context sharing; original SourceProgram owns all facts.

Only SP5 transport is supported. A live read session owns the mutable typed
context privately. Public body reads return the existing LoweredSourceBody,
never shared mutable semantic/semantics/control objects or a trusted token.
"""
from __future__ import annotations

from dataclasses import dataclass
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

from scar.analysis.program_lowering import LoweredSourceBody
from scar.ir.program.inventory import SourceContextDigest
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2._validation import record_errors

_CONTEXT = ('semantic', 'semantics', 'control')
_CONTEXT_SCHEMA = 'scar.source-context'
_BODY_SCHEMA = 'scar.source-body-fragment'


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _strict(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, 'duplicate source fragment JSON field')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('nonfinite source fragment JSON number: ' + value)
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    _need(type(value) is dict, 'source fragment record must be an object')
    return value


def _stamp(path):
    value = path.stat()
    return (value.st_dev, value.st_ino, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


@dataclass(frozen=True, slots=True)
class SourceFragmentBudget:
    max_stored_input_bytes: int = 128_000_000
    max_decoded_input_bytes: int = 256_000_000
    max_record_bytes: int = 64_000_000
    max_output_bytes: int = 128_000_000
    max_contexts: int = 8
    max_operations: int = 4000
    seconds: int = 180

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError('source fragment budget must be positive: ' + name)


@dataclass(frozen=True, slots=True)
class SourceContextReference:
    source: SourceSnapshot
    context: SourceContextDigest
    payload: SourceArtifactLocator

    def __post_init__(self):
        _need(type(self.source) is SourceSnapshot and not record_errors(self.source, SourceSnapshot, 'context.source'),
              'context source snapshot differs')
        _need(type(self.context) is SourceContextDigest, 'context digest must be typed')
        root = self.context.namespace_root
        _need(type(root) is str and Path(root).is_absolute() and os.path.normpath(root) == root,
              'context namespace must be an exact absolute root')
        for name in ('semantic_sha256', 'semantics_sha256', 'control_sha256'):
            _need(type(getattr(self.context, name)) is str and re.fullmatch('[0-9a-f]{64}', getattr(self.context, name)),
                  'context needs exact canonical SHA256 values')
        _need(type(self.payload) is SourceArtifactLocator, 'context payload locator must be typed')
        self.payload.__post_init__()
        _need(self.payload.artifact.schema == _CONTEXT_SCHEMA + '/1' and self.payload.pointer == '#',
              'unsupported context artifact schema/pointer')


@dataclass(frozen=True, slots=True)
class SourceBodyFragment:
    """Body-only result; no new graph identity or shared context exposure."""
    body: LoweredSourceBody
    context: SourceContextReference
    original: SourceArtifactLocator
    artifact: SourceArtifactLocator


class _IO:
    def __init__(self, budget):
        _need(type(budget) is SourceFragmentBudget, 'source fragment budget must be typed')
        budget.__post_init__()
        self.budget = budget
        self.started = time.monotonic()
        self.counts = dict(stored_input_bytes=0, decoded_input_bytes=0,
                           stored_output_bytes=0, decoded_output_bytes=0, existing_output_guard_bytes=0,
                           context_reads=0, context_validations=0, context_hash_guards=0, body_reads=0)
        self.inputs = {}
        self.closed = False

    def _check(self):
        _need(not self.closed, 'source fragment session is closed')
        _need(time.monotonic() - self.started <= self.budget.seconds,
              'source fragment wall budget exceeded')

    def _read(self, locator):
        self._check()
        _need(type(locator) is SourceArtifactLocator, 'input requires exact source artifact locator')
        locator.__post_init__()
        _need(locator.pointer == '#', 'source fragment transport supports whole-record locators only')
        p = Path(locator.artifact.uri)
        _need(p.is_file() and not p.is_symlink(), 'source fragment input absent or symlinked: ' + str(p))
        before = _stamp(p)
        _need(before[2] == locator.artifact.size_bytes, 'source fragment stored size differs')
        _need(before[2] <= self.budget.max_record_bytes and locator.decoded_bytes <= self.budget.max_record_bytes,
              'source fragment record byte budget exceeded')
        _need(self.counts['stored_input_bytes'] + before[2] <= self.budget.max_stored_input_bytes,
              'source fragment stored input budget exceeded')
        _need(self.counts['decoded_input_bytes'] + locator.decoded_bytes <= self.budget.max_decoded_input_bytes,
              'source fragment decoded input budget exceeded')
        raw = p.read_bytes()
        self.counts['stored_input_bytes'] += len(raw)
        _need(_stamp(p) == before and _sha(raw) == locator.artifact.sha256,
              'source fragment stored SHA/input changed')
        if locator.representation == 'gzip-canonical-json':
            # Bound decompression before allocation beyond the declared ceiling.
            import io
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                decoded = stream.read(locator.decoded_bytes + 1)
                _need(len(decoded) == locator.decoded_bytes and not stream.read(1),
                      'source fragment decoded size differs')
        else:
            decoded = raw
        self.counts['decoded_input_bytes'] += len(decoded)
        _need(len(decoded) == locator.decoded_bytes and _sha(decoded) == locator.decoded_sha256,
              'source fragment decoded SHA differs')
        self.inputs[str(p)] = before
        document = _strict(decoded)
        if locator.artifact.schema in (_CONTEXT_SCHEMA + '/1', _BODY_SCHEMA + '/1'):
            _need(_canonical(document) == decoded, 'source fragment JSON is not canonical')
        return document

    def finish(self):
        self._check()
        for name, expected in self.inputs.items():
            p = Path(name)
            _need(p.is_file() and not p.is_symlink() and _stamp(p) == expected,
                  'source fragment input changed during session: ' + name)
        return {**self.counts, 'elapsed_seconds': time.monotonic() - self.started}


class SourceFragmentWriter(_IO):
    """Archive-only split; normal body readers still establish validation."""
    def __init__(self, directory, *, budget=SourceFragmentBudget()):
        super().__init__(budget)
        self.directory = Path(directory).absolute()
        _need(not self.directory.is_symlink(), 'source fragment output cannot be symlinked')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _existing_matches(self, path, expected):
        _need(path.is_file() and not path.is_symlink(), 'existing source fragment output is invalid')
        before = _stamp(path)
        _need(before[2] <= self.budget.max_record_bytes and self.counts['stored_input_bytes'] + before[2]
              <= self.budget.max_stored_input_bytes, 'existing output guard input budget exceeded')
        raw = path.read_bytes()
        self.counts['stored_input_bytes'] += len(raw)
        self.counts['existing_output_guard_bytes'] += len(raw)
        _need(_stamp(path) == before and raw == expected, 'existing source fragment output differs')
        self.inputs[str(path)] = before

    def _publish(self, document, family, key):
        self._check()
        decoded = _canonical(document)
        _need(len(decoded) <= self.budget.max_record_bytes, 'source fragment output record budget exceeded')
        raw = gzip.compress(decoded, mtime=0)
        path = self.directory / family / (key + '.json.gz')
        path.parent.mkdir(exist_ok=True, mode=0o700)
        _need(not path.parent.is_symlink(), 'source fragment output family cannot be symlinked')
        if path.exists():
            self._existing_matches(path, raw)
        else:
            _need(self.counts['stored_output_bytes'] + len(raw) <= self.budget.max_output_bytes,
                  'source fragment output budget exceeded')
            fd, temporary = tempfile.mkstemp(prefix='.building-', dir=path.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw);stream.flush();os.fsync(stream.fileno())
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    self._existing_matches(path, raw)
                else:
                    self.counts['stored_output_bytes'] += len(raw)
                    self.counts['decoded_output_bytes'] += len(decoded)
            finally:
                os.unlink(temporary)
        return SourceArtifactLocator(ProviderArtifact(str(path), _sha(raw), len(raw),
            document['schema'] + '/1'), _sha(decoded), len(decoded), 'gzip-canonical-json')

    def write(self, original, *, namespace_root):
        document = self._read(original)
        _need(document.get('schema') == 'scar.source-program' and type(document.get('schema_version')) is int
              and document['schema_version'] == 5, 'unsupported source fragment input; explicit SP5 required')
        _need(type(document.get('language')) is dict and document['language'].get('namespace_root') == namespace_root,
              'source body namespace differs')
        source = decode(SourceSnapshot, document['metadata']['source'])
        hashes = [_sha(_canonical(document[name])) for name in _CONTEXT]
        digest = SourceContextDigest(namespace_root, *hashes)
        context_document = dict(schema=_CONTEXT_SCHEMA, schema_version=1,
            source=encode(source), context=encode(digest), **{name: document[name] for name in _CONTEXT})
        key = _sha(_canonical({'source': encode(source), 'context': encode(digest)}))
        context_locator = self._publish(context_document, 'contexts', key)
        context = SourceContextReference(source, digest, context_locator)
        program = {key: value for key, value in document.items() if key not in _CONTEXT}
        body_document = dict(schema=_BODY_SCHEMA, schema_version=1,
            original=encode(original), context=encode(context), program=program,
            canonical_program_sha256=_sha(_canonical(document)))
        body_locator = self._publish(body_document, 'bodies', _sha(_canonical(body_document)))
        return body_locator


@dataclass(slots=True)
class _OwnedContext:
    reference: SourceContextReference
    semantic: object
    semantics: object
    control: object


class SourceContextSession(_IO):
    """Live, nonserializable owner; receipt/source validation is session local."""
    def __init__(self, *, source_texts, budget=SourceFragmentBudget()):
        super().__init__(budget)
        _need(type(source_texts) is dict and all(type(k) is str and type(v) is str for k, v in source_texts.items()),
              'source fragment reader requires explicit retained source_texts')
        self._texts = dict(source_texts)
        self._contexts = {}

    def __enter__(self):
        self._check();return self

    def __exit__(self, kind, value, trace):
        try:
            if kind is None:self.finish()
        finally:
            self._contexts.clear();self._texts.clear();self.closed = True

    def _context(self, reference):
        self._check()
        _need(type(reference) is SourceContextReference, 'source context reference must be typed')
        reference.__post_init__()
        key = _canonical(encode(reference))
        if key not in self._contexts:
            _need(len(self._contexts) < self.budget.max_contexts, 'source context count budget exceeded')
            doc = self._read(reference.payload)
            _need(set(doc) == {'schema', 'schema_version', 'source', 'context', *_CONTEXT}
                  and doc['schema'] == _CONTEXT_SCHEMA and type(doc['schema_version']) is int and doc['schema_version'] == 1,
                  'source context fields/schema differ')
            _need(doc['source'] == encode(reference.source) and doc['context'] == encode(reference.context),
                  'source context source/namespace/digest differs')
            for name in _CONTEXT:
                _need(_sha(_canonical(doc[name])) == getattr(reference.context, name + '_sha256'),
                      'source context canonical SHA differs')
            from scar.ir.v2.codec import semantic_from_dict
            from scar.ir.semantics_v2 import SourceSemanticsGraph
            from scar.ir.control_flow_v2 import SourceControlFlowGraph
            from scar.analysis.source_semantics_v2 import validate_source_semantics
            from scar.analysis.control_flow_v2 import validate_source_control_flow
            semantic = semantic_from_dict(doc['semantic'])
            semantics = SourceSemanticsGraph.from_dict(doc['semantics'], semantic)
            control = SourceControlFlowGraph.from_dict(doc['control'])
            _need(semantics.sources.get(reference.source.path) == reference.source,
                  'source context snapshot is not its original source')
            semantic.assert_valid()
            checked = validate_source_semantics(semantics, semantic, sources=self._texts)
            _need(checked['valid'], '; '.join(checked['errors']))
            checked = validate_source_control_flow(control, semantic, semantics, sources=self._texts)
            _need(checked['valid'], '; '.join(checked['errors']))
            self._contexts[key] = _OwnedContext(reference, semantic, semantics, control)
            self.counts['context_reads'] += 1;self.counts['context_validations'] += 1
        return self._contexts[key]

    def _claim(self, result, reference):
        """No cached validation of caller-owned IR: identities and hashes must match."""
        owned = self._context(reference)
        _need(result.semantic is owned.semantic and result.semantics is owned.semantics
              and result.control is owned.control, 'source body does not use this live owned context')
        _need(result.metadata.source == reference.source and result.language is not None
              and result.language.namespace_root == reference.context.namespace_root,
              'source body snapshot/namespace differs from owned context')
        for name in _CONTEXT:
            _need(_sha(_canonical(getattr(owned, name).to_dict())) == getattr(reference.context, name + '_sha256'),
                  'private source context changed after validation')
        self.counts['context_hash_guards'] += 1
        return owned

    def read(self, artifact, *, namespace_root):
        doc = self._read(artifact)
        _need(set(doc) == {'schema', 'schema_version', 'original', 'context', 'program', 'canonical_program_sha256'}
              and doc['schema'] == _BODY_SCHEMA and type(doc['schema_version']) is int and doc['schema_version'] == 1,
              'source body fragment fields/schema differ')
        context = decode(SourceContextReference, doc['context'])
        _need(context.context.namespace_root == namespace_root, 'source fragment namespace differs')
        original = decode(SourceArtifactLocator, doc['original'])
        _need(original.artifact.schema == 'scar.source-program/5', 'source fragment original must be SP5')
        from scar.analysis.program_lowering import SourceProgram
        body = SourceProgram.read_structure_fragment(doc['program'], context_session=self,
            context=context, max_operations=self.budget.max_operations)
        # Reconstructed canonical identity is measured from the same private
        # original tables, without exposing them or making a second graph.
        owned = self._context(context)
        full = dict(doc['program'], **{name: getattr(owned, name).to_dict() for name in _CONTEXT})
        _need(_sha(_canonical(full)) == doc['canonical_program_sha256'],
              'source fragment reconstructed original canonical identity differs')
        self.counts['body_reads'] += 1
        return SourceBodyFragment(body, context, original, artifact)
