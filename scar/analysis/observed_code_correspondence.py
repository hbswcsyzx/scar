"""Fresh, code-scope-only correspondence to retained static source.

A current file is material, not a capture-time module version. Matching a
compiled child never identifies its creator, globals, defaults or class object.
Saved correspondence records are audit DTOs, not reusable admission tokens.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import sys
from types import CodeType

from scar.analysis.call_operand_reader import CallOperandTrace
from scar.analysis.static_compilation import StaticCodeEvidence
from scar.ir.program.call_edges import CodeCapture
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.program.source_subjects import ModuleUnitSource, SourceCompilationCodeRef
from scar.ir.record_codec import decode, encode, loads
from scar.ir.semantics_v2 import SourceSnapshot
from scar.trace.code_snapshot import code_key, describe_code
from scar.trace.lean_capture import LeanCapturePlan


_ORIGINS = ('HISTORICAL_SOURCE_SNAPSHOT', 'CURRENT_STATIC_SOURCE_CANDIDATE')
_SCOPE = 'MATCHED_CODE_SCOPE_ONLY'


@dataclass(frozen=True, slots=True)
class SourceScopeAuthority:
    run_scope: str
    capture: CodeCapture
    source: SourceSnapshot
    historical_snapshot: SourceSnapshot | None
    plan: ProviderArtifact | None
    source_origin: str
    scope: str = _SCOPE

    def __post_init__(self):
        if (type(self.run_scope) is not str or re.fullmatch(r'[0-9a-f]{64}', self.run_scope) is None
                or type(self.capture) is not CodeCapture or type(self.source) is not SourceSnapshot
                or type(self.source_origin) is not str or self.source_origin not in _ORIGINS
                or self.scope != _SCOPE or type(self.scope) is not str):
            raise ValueError('code correspondence needs original capture/current source and fixed scope')
        self.capture.code.__post_init__()
        self.capture.anchor.__post_init__()
        if self.capture.code.filename != self.source.path:
            raise ValueError('code correspondence changed its original source locator')
        if self.source_origin == 'HISTORICAL_SOURCE_SNAPSHOT':
            if (type(self.historical_snapshot) is not SourceSnapshot or type(self.plan) is not ProviderArtifact
                    or self.historical_snapshot.path != self.source.path
                    or self.historical_snapshot.fingerprint != self.source.fingerprint):
                raise ValueError('historical source scope needs its matching original snapshot/plan')
            self.plan.__post_init__()
        elif self.historical_snapshot is not None or self.plan is not None:
            raise ValueError('current source candidate cannot invent a historical whole-file snapshot')


@dataclass(frozen=True, slots=True)
class CodeScopeCorrespondence(SourceScopeAuthority):
    body: SourceBodyNamespace | None = None
    compilation: SourceCompilationCodeRef | None = None

    def __post_init__(self):
        SourceScopeAuthority.__post_init__(self)
        if type(self.body) is not SourceBodyNamespace or type(self.compilation) is not SourceCompilationCodeRef:
            raise TypeError('code/body correspondence needs original body and static compilation reference')
        self.body.__post_init__()
        self.compilation.__post_init__()
        if (self.body.definition != self.compilation.definition
                or self.compilation.code_layout_key != self.capture.code.key):
            raise ValueError('correspondence changed its original definition or matched Code scope')
        subject = self.compilation.source
        if type(subject) is ModuleUnitSource:
            if self.body.source is not None or subject.snapshot != self.source:
                raise ValueError('module Code correspondence changed its static source subject')
        elif (subject != self.body.source or subject.path != self.source.path
                or subject.fingerprint != self.source.fingerprint):
            raise ValueError('child Code correspondence changed its original static source occurrence')


class ObservedCodeSources:
    """One fresh trace/profile owner; code matches grant no environment facts.

    The supplied trace/run are the existing normal reader results. This owner
    checks membership, compiler profiles and original lean-plan receipts without
    repeating the frame/operand/target scan or accepting validation booleans.
    """
    def __init__(self, trace, run_scope):
        if (type(trace) is not CallOperandTrace or type(run_scope) is not str
                or re.fullmatch(r'[0-9a-f]{64}', run_scope) is None):
            raise TypeError('observed source scopes require a normal typed trace and original run scope')
        self.trace, self.run_scope = trace, run_scope
        self._captures = set(trace.frame_scan.captures)
        self._metadata = {row.process_id: row for row in trace.metadata}
        if len(self._metadata) != len(trace.metadata):
            raise ValueError('source-scope compiler metadata has duplicate processes')
        self._snapshots, self._plans, self._roots = {}, {}, OrderedDict()
        directory = Path(trace.directory)
        if not directory.is_absolute() or directory.resolve() != directory or directory.is_symlink():
            raise ValueError('observed source scopes require the original canonical trace directory')
        total = 0
        for metadata in trace.frame_scan.metadata:
            wire = metadata.get('capture_plan')
            if wire is None:
                continue
            process = metadata['process_id']
            receipt = decode(ProviderArtifact, wire)
            path = Path(receipt.uri)
            if (path != directory / f'lean-plan.{process}.json' or path.resolve() != path
                    or path.is_symlink() or not path.is_file() or receipt.size_bytes > 16_000_000
                    or total + receipt.size_bytes > trace.frame_budget.max_raw_bytes):
                raise ValueError('source-scope plan differs from its original namespace/byte bound')
            with path.open('rb') as stream:
                raw = stream.read(receipt.size_bytes + 1)
            if len(raw) != receipt.size_bytes or sha256(raw).hexdigest() != receipt.sha256:
                raise ValueError('source-scope original plan bytes/SHA differ')
            total += len(raw)
            plan = LeanCapturePlan.from_dict(loads(raw), max_codes=trace.frame_budget.max_codes)
            if plan.namespace_root != trace.project_root:
                raise ValueError('source-scope original plan namespace policy differs')
            if process in self._plans:
                raise ValueError('source-scope process has duplicate original plans')
            self._plans[process] = receipt
            for body in plan.bodies:
                key = process, body.source.path
                previous = self._snapshots.setdefault(key, body.source)
                if previous != body.source:
                    raise ValueError('one original plan path has conflicting whole-file snapshots')

    def require_source(self, captured, current_snapshot):
        """Check material/profile scope; not itself a compiled-code match."""
        if type(captured) is not CodeCapture or captured not in self._captures:
            raise ValueError('source correspondence requires the retained original CodeCapture/anchor')
        if type(current_snapshot) is not SourceSnapshot or current_snapshot.path != captured.code.filename:
            raise ValueError('source correspondence changed the captured filename/current snapshot')
        metadata = self._metadata.get(captured.process_id)
        if (metadata is None or metadata.implementation != sys.implementation.name
                or metadata.python != sys.version):
            raise ValueError('CAPTURE_COMPILER_PROFILE_UNSUPPORTED')
        historical = self._snapshots.get((captured.process_id, current_snapshot.path))
        if historical is not None and historical.fingerprint != current_snapshot.fingerprint:
            raise ValueError('CAPTURE_SOURCE_VERSION_CHANGED: original whole-file snapshot differs')
        return SourceScopeAuthority(self.run_scope, captured, current_snapshot, historical,
            None if historical is None else self._plans[captured.process_id],
            _ORIGINS[0] if historical is not None else _ORIGINS[1])

    def require(self, captured, body, code, compilation):
        """Verify this retained body/compiler path, never a parent environment."""
        if type(code) is not CodeType or type(compilation) is not SourceCompilationCodeRef:
            raise TypeError('code correspondence requires the actual static Code and typed compilation')
        namespace, snapshot = body.namespace, body.metadata.source
        if type(namespace) is not SourceBodyNamespace or type(snapshot) is not SourceSnapshot:
            raise TypeError('code correspondence requires original body namespace/source records')
        authority = self.require_source(captured, snapshot)
        compilation.__post_init__()
        if (namespace.region != body.graph.root or namespace.entry != body.metadata.entry
                or compilation.definition != namespace.definition
                or compilation.compiler_implementation != sys.implementation.name
                or compilation.compiler_version != tuple(sys.version_info[:3])
                or compilation.compiler_python != sys.version
                or compilation.compiler_cache_tag != sys.implementation.cache_tag):
            raise ValueError('source-scope body/definition/compiler profile differs')
        text = body.context.docs['source']['text']
        if type(text) is not str or 'sha256:' + sha256(text.encode()).hexdigest() != snapshot.fingerprint:
            raise ValueError('source-scope current retained text differs from its exact fingerprint')
        root = self._roots.get(snapshot)
        if root is None:
            root = compile(text, snapshot.path, 'exec', flags=0, dont_inherit=True, optimize=0)
            self._roots[snapshot] = root
            while len(self._roots) > 16:
                self._roots.popitem(last=False)
        else:
            self._roots.move_to_end(snapshot)
        selected = root
        for position in compilation.code_path:
            if position >= len(selected.co_consts) or type(selected.co_consts[position]) is not CodeType:
                raise ValueError('source-scope compiler path does not select an original child Code')
            selected = selected.co_consts[position]
        if (describe_code(selected) != encode(captured.code)
                or describe_code(code) != encode(captured.code)):
            raise ValueError('CAPTURE_CODE_DESCRIPTOR_MISMATCH')
        evidence = StaticCodeEvidence(snapshot, body.context.unit['namespace_root'], namespace.definition,
            compilation.source, compilation.code_path, selected, code_key(selected),
            sys.implementation.name, tuple(sys.version_info[:3]), sys.version,
            sys.implementation.cache_tag, root_code_layout_key=code_key(root))
        if evidence.to_reference() != compilation:
            raise ValueError('source-scope original compilation differs from retained-source replay')
        if body.document.get('module') is not None:
            original = body.module.declaration.compilation
            if original != compilation:
                raise ValueError('source-scope original module CodeRef differs')
        elif body.document.get('class') is not None:
            if body.class_entry.compilation != compilation:
                raise ValueError('source-scope original class CodeRef differs')
        else:
            wire = body.document.get('static_compilation')
            expected = evidence.to_dict()
            if type(wire) is dict and 'layout' not in wire:
                expected.pop('layout')
            if encode(expected) != wire:
                raise ValueError('source-scope original function compilation envelope differs')
        return CodeScopeCorrespondence(authority.run_scope, authority.capture, authority.source,
            authority.historical_snapshot, authority.plan, authority.source_origin,
            authority.scope, namespace, compilation)


__all__ = ['ObservedCodeSources', 'SourceScopeAuthority', 'CodeScopeCorrespondence']
