"""Project standard pathlib source-text candidates without executing a target.

Path terms retain original source sites. Lexical path alternatives are guarded
by declared cwd, platform and filesystem-version conditions; resolve performs
no target filesystem lookup. Text-open decoding uses captured raw bytes and
has its own encoding/newline interpretation, independent of F0 PEP263 decoding.
"""
import argparse
from collections import defaultdict, deque
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO, TextIOWrapper
import json
import pathlib
from pathlib import Path, PurePosixPath
import posixpath
import sys

from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.source_bytes import read_source_bytes
from scar.analysis.source_launch import read_script_entry
from scar.analysis.source_syntax import _digest
from scar.analysis.static_query import _Fragments
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.literals import PythonLiteral
from scar.ir.program import source_text as X, normal_links as F, normal_targets as T
from scar.ir.program import normal_graph as G, source_productions as P
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.python_bindings import SourceCallSite
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import decode, encode


_BASE = ('DECLARED_SCRIPT_ENTRY_CONTEXT_SELECTED', 'SOURCE_SCOPE_AND_NORMAL_COMPLETION_SELECTED',
         'STANDARD_LIBRARY_PATHLIB_REFERENCE_SELECTED', 'CURRENT_NAMESPACE_REFERENCE_ALTERNATIVE_SELECTED')
_EXPORTS = {'Path': ('POSIX', True), 'PurePath': ('POSIX', False),
            'PosixPath': ('POSIX', True), 'PurePosixPath': ('POSIX', False),
            'WindowsPath': ('WINDOWS', True), 'PureWindowsPath': ('WINDOWS', False)}


@dataclass(frozen=True)
class _String:
    value: str
    conditions: tuple[str, ...] = ()


@dataclass(frozen=True)
class _PathValue:
    expression: str
    lexical: str | None
    export: str
    trace: frozenset[int]
    conditions: tuple[str, ...]


@dataclass(frozen=True)
class _Method:
    path: _PathValue
    receiver: int
    name: str


def _conditions(*groups):
    return tuple(dict.fromkeys(item for group in groups for item in group))


class _Projection:
    def __init__(self, store, unit, entry, limit):
        if type(store) is not SourceFactStore or type(limit) is not int or limit < 1:
            raise ValueError('an original SourceFactStore and positive path limit are required')
        self.store, self.unit, self.entry, self.limit = store, unit, entry, limit
        self.ports, self.f0s, self.manifests = {}, {}, {}
        self.paths, self.path_points, self.reads, self.candidates, self.obligations = {}, {}, {}, {}, set()
        self.values, self.adj, self.watch = defaultdict(set), defaultdict(set), defaultdict(set)
        self.queue = deque()
        self.owners = {(span.table.value, i): group.owner for group in unit.scope_groups
            for span in group.tables for i in range(span.start, span.stop)}
        model = Path(store.model_for(unit.unit))
        self.syntax = _Fragments(model).read(store.model_units[unit.unit]['artifacts']['source_syntax'])
        f0, _, _ = self.f0(unit.unit)
        if (entry.root != unit.root_scope or entry.source.unit != unit.unit
                or entry.source.f0_document_sha256 != _digest(f0)
                or entry.source.f2_document_sha256 != _digest(self.syntax)
                or self.syntax['input']['f0_document_sha256'] != _digest(f0)):
            raise ValueError('script entry and original F0/F2/root interfaces differ')
        self.fields = {row['name']:{name:i for i,name in enumerate(row['fields'])}
                       for row in self.syntax['profile']['ast_schema']}
        self.provider = None
        stdlib = str(Path(pathlib.__file__).absolute())
        for identity, row in store.model_units.items():
            if row['path'] == stdlib:
                _, raw, locator = self.f0(identity)
                if raw == Path(stdlib).read_bytes():
                    self.provider = locator
                    break
        for source, target in unit.aliases:
            self.adj[source].add(target)
        for access in unit.names:
            ns = access.namespace
            channel = ('namespace', ns.kind, ns.owner, ns.name)
            self.adj[access.value if access.write else channel].add(channel if access.write else access.value)
        self.attributes = defaultdict(list)
        for i, access in enumerate(unit.attributes):
            if access.action in (F.AttributeAction.GET, F.AttributeAction.IMPORT_MEMBER):
                self.attributes[access.receiver].append((i, access))
        for i, call in enumerate(unit.calls):
            for point in (call.callee, *call.positional, *(p for _,p in call.keywords)):
                self.watch[point].add(('call', i))
        for i, operation in enumerate(unit.operations):
            if operation.action is F.LanguageOperationKind.BINARY and operation.selector is F.OperatorSelector.DIV:
                for point in operation.operands:
                    self.watch[point].add(('join', i))
        for item in unit.constants:
            value = item.literal.to_python()
            if type(value) is str:
                self.offer(item.value, _String(value))
        for binding in entry.globals:
            value = binding.literal.to_python()
            if type(value) is str:
                reads = set(binding.reads)
                for access in unit.names:
                    if not access.write and access.namespace == binding.namespace and self.gp(access.value) in reads:
                        self.offer(access.value, _String(value, _conditions(entry.conditions,
                            ('DECLARED_INITIAL_NAMESPACE_VALUE_PRESERVED_AT_READ',))))
        if self.provider is not None:
            for imported in unit.imports:
                if imported.module == 'pathlib':
                    self.offer(imported.value, ('module', 'pathlib'))
        else:
            for imported in unit.imports:
                if imported.module == 'pathlib':
                    self.oblige(self.gp(imported.value), 'RETAINED_STANDARD_LIBRARY_PATHLIB_PROVIDER_NOT_AVAILABLE')

    def gp(self, index):
        if index not in self.ports:
            port = self.unit.ports[index]
            if type(port) is dict:
                port = decode(G.Port, port, record_tags=P.PRODUCTION_RECORD_TAGS)
            self.ports[index] = T.GlobalPort(self.unit.unit, port)
        return self.ports[index]

    def f0(self, identity):
        if identity not in self.f0s:
            model = Path(self.store.model_for(identity))
            manifest = (model/'manifest.json').read_bytes()
            if model in self.manifests and self.manifests[model] != manifest:
                raise ValueError('source model changed during projection')
            self.manifests[model] = manifest
            rows = json.loads(manifest)['units']
            ordinal, = [i for i,row in enumerate(rows) if row['key'] == identity]
            descriptor = self.store.model_units[identity]['artifacts']['source_bytes']
            document = _Fragments(model).read(descriptor)
            raw = read_source_bytes(document)
            declared = ProviderFactReference(ProviderArtifact(str(model/'manifest.json'),
                sha256(manifest).hexdigest(), len(manifest), 'scar.static-program'),
                '#/units/'+str(ordinal)+'/artifacts/source_bytes')
            locator = SourceArtifactLocator(ProviderArtifact(str(model/descriptor['path']),
                descriptor['sha256'], descriptor['bytes'], 'scar.source-bytes+gzip-json'),
                descriptor['decoded_sha256'], descriptor['decoded_bytes'], 'gzip-canonical-json', declaration=declared)
            self.f0s[identity] = document, raw, locator
        return self.f0s[identity]

    def oblige(self, port, reason):
        self.obligations.add(X.SourceTextObligation(port, reason))

    def offer(self, point, value):
        if value in self.values[point]:
            return
        if type(value) is _PathValue and sum(type(v) is _PathValue for v in self.values[point]) >= self.limit:
            if type(point) is int:
                self.oblige(self.gp(point), 'PATH_ALTERNATIVE_LIMIT_REACHED_NO_EXHAUSTIVE_VALUE_CLAIM')
            return
        self.values[point].add(value)
        self.queue.append((point, value))

    def site(self, call):
        return SourceCallSite(self.gp(call.callee), tuple(map(self.gp, call.positional)),
            tuple((n,self.gp(p)) for n,p in call.keywords), self.gp(call.result),
            self.gp(call.world), self.gp(call.result_world),
            None if call.positional_pack is None else self.gp(call.positional_pack),
            None if call.keyword_pack is None else self.gp(call.keyword_pack))

    def expression(self, kind, table, ordinal, result, operands, export, **sites):
        payload = dict(operation=kind, result=self.gp(result), operands=tuple(map(self.gp, operands)),
                       export=export, source_table=table, source_ordinal=ordinal)
        identity = sha256(_json(encode(payload, record_tags=P.PRODUCTION_RECORD_TAGS))).hexdigest()
        self.paths.setdefault(identity, X.SourcePathExpression(identity, self.gp(result),
            self.owners[table,ordinal], kind, tuple(map(self.gp, operands)), self.provider, export,
            table, ordinal, conditions=_BASE, **sites))
        self.path_points[identity] = result
        return identity

    def path_value(self, expression, result, lexical, export, previous=(), conditions=()):
        trace = frozenset().union(*(p.trace for p in previous))
        if result in trace:
            self.oblige(self.gp(result), 'CYCLIC_PATH_EXPRESSION_RETAINED_WITHOUT_UNROLLING')
            return
        self.offer(result, _PathValue(expression, lexical, export, trace | {result},
            _conditions(*(p.conditions for p in previous), conditions)))

    def attribute(self, ordinal, access, value):
        if value == ('module', 'pathlib') and access.name in _EXPORTS:
            self.offer(access.value, ('constructor', access.name))
        if type(value) is not _PathValue:
            return
        if access.name == 'parent':
            site = T.AttributeSite(T.AttributeOrigin.ATTRIBUTE, access.action, self.gp(access.receiver),
                access.name, self.gp(access.value), None, self.gp(access.world), self.gp(access.result_world))
            expression = self.expression(X.SourcePathOperation.PARENT, 'attributes', ordinal,
                access.value, (access.receiver,), value.export, attribute=site)
            lexical = None if value.lexical is None else str(PurePosixPath(value.lexical).parent)
            self.path_value(expression, access.value, lexical, value.export, (value,))
        elif access.name in ('resolve', 'read_text'):
            if _EXPORTS[value.export][1]:
                self.offer(access.value, _Method(value, access.receiver, access.name))
            else:
                self.oblige(self.gp(access.value), 'PURE_PATH_HAS_NO_FILESYSTEM_METHOD:'+access.name)

    def parameters(self, call):
        names = ('encoding', 'errors', 'newline')
        supplied = dict(call.keywords)
        note = []
        packed = call.positional_pack is not None or call.keyword_pack is not None
        if packed:
            note.append('READ_TEXT_ARGUMENT_PACK_BINDING_NOT_IMPLEMENTED')
        if len(call.positional)>3 or any(name not in names for name in supplied):
            note.append('READ_TEXT_SIGNATURE_ACCEPTANCE_NOT_ESTABLISHED')
        for name, point in zip(names, call.positional):
            if name in supplied:
                note.append('READ_TEXT_DUPLICATE_PARAMETER:'+name)
            supplied[name] = point
        node = self.syntax['nodes'][self.gp(call.result).port.template.occurrence]
        literal_by_point = {}
        if node['constructor'] == 'Call':
            fields = self.fields['Call']
            for point, child in zip(call.positional, node['fields'][fields['args']]['items']):
                expr = self.syntax['nodes'][child['reference']]
                if expr['constructor'] == 'Constant':
                    literal_by_point[point] = (decode(PythonLiteral,expr['fields'][self.fields['Constant']['value']]['scalar']),
                                               P.ProductionOccurrence(child['reference']))
            for child in node['fields'][fields['keywords']]['items']:
                keyword = self.syntax['nodes'][child['reference']]
                name = decode(PythonLiteral,keyword['fields'][self.fields['keyword']['arg']]['scalar']).to_python()
                ref = keyword['fields'][self.fields['keyword']['value']]['reference']
                expr = self.syntax['nodes'][ref]
                if name in supplied and expr['constructor'] == 'Constant':
                    literal_by_point[supplied[name]] = (decode(PythonLiteral,expr['fields'][self.fields['Constant']['value']]['scalar']),
                                                       P.ProductionOccurrence(ref))
        parameters = []
        for name in names:
            if name in supplied:
                literal, occurrence = literal_by_point.get(supplied[name], (None, None))
                parameters.append(X.TextReadParameter(name,self.gp(supplied[name]),literal,False,occurrence))
                if literal is None:
                    note.append('READ_TEXT_PARAMETER_VALUE_NOT_RESOLVED:'+name)
            elif packed:
                parameters.append(X.TextReadParameter(name,None,None,False))
            else:
                parameters.append(X.TextReadParameter(name,None,PythonLiteral.from_python(None),True))
        return tuple(parameters), tuple(note)

    def call(self, ordinal, call, callee):
        if type(callee) is tuple and callee[:1] == ('constructor',):
            export = callee[1]
            expression = self.expression(X.SourcePathOperation.CONSTRUCT, 'calls', ordinal,
                call.result, call.positional, export, call=self.site(call))
            if call.keywords or call.positional_pack is not None or call.keyword_pack is not None or len(call.positional)>1:
                self.oblige(self.gp(call.result), 'PATH_CONSTRUCTOR_SIGNATURE_NOT_IMPLEMENTED')
                self.path_value(expression, call.result, None, export)
                return
            values = self.values[call.positional[0]] if call.positional else (_String('.'),)
            found = False
            for value in tuple(values):
                if type(value) not in (_String, _PathValue):
                    continue
                found = True
                lexical = value.value if type(value) is _String else value.lexical
                conditions = list(value.conditions)
                if export in ('Path', 'PurePath'):
                    conditions.append('TARGET_PATHLIB_FLAVOUR_IS_POSIX')
                if _EXPORTS[export][0] != 'POSIX':
                    lexical = None
                    self.oblige(self.gp(call.result), 'WINDOWS_PATH_VALUE_PROJECTION_NOT_IMPLEMENTED')
                elif lexical is not None:
                    lexical = str(PurePosixPath(lexical))
                self.path_value(expression,call.result,lexical,export,
                    (value,) if type(value) is _PathValue else (),tuple(conditions))
            if not found:
                self.path_value(expression,call.result,None,export)
        elif type(callee) is _Method:
            path = callee.path
            if callee.name == 'resolve':
                expression = self.expression(X.SourcePathOperation.RESOLVE, 'calls', ordinal,
                    call.result, (callee.receiver,*call.positional), path.export, call=self.site(call))
                lexical = path.lexical
                conditions = ('DECLARED_CWD_SELECTED_AND_PRESERVED',
                    'PATH_RESOLUTION_HAS_NO_SYMLINK_REDIRECTION', 'PATH_RESOLVE_COMPLETES_NORMALLY')
                if lexical is not None:
                    lexical = posixpath.normpath(posixpath.join(self.entry.inputs.cwd,lexical))
                if call.positional_pack is not None or call.keyword_pack is not None or call.positional or call.keywords:
                    lexical = None
                    self.oblige(self.gp(call.result), 'RESOLVE_ARGUMENT_BINDING_NOT_IMPLEMENTED')
                self.path_value(expression,call.result,lexical,path.export,(path,),conditions)
            else:
                parameters, obligations = self.parameters(call)
                read = X.SourceTextRead(self.site(call),self.owners['calls',ordinal],self.gp(callee.receiver),
                    path.expression,parameters,_BASE,obligations)
                self.reads[ordinal,path.expression] = read
                self.text_candidates(read,path)

    def join(self, ordinal, operation):
        if len(operation.operands) != 2:
            return
        left, right = operation.operands
        site = T.LanguageOperationSite(operation.action,operation.selector,tuple(map(self.gp,operation.operands)),
            self.gp(operation.result),self.gp(operation.world),self.gp(operation.result_world))
        for path in tuple(self.values[left]):
            if type(path) is not _PathValue:
                continue
            expression = self.expression(X.SourcePathOperation.JOIN,'operations',ordinal,
                operation.result,operation.operands,path.export,language=site)
            strings = [value for value in self.values[right] if type(value) is _String]
            if not strings:
                self.path_value(expression,operation.result,None,path.export,(path,))
            for value in strings:
                lexical = None if path.lexical is None else str(PurePosixPath(path.lexical)/value.value)
                self.path_value(expression,operation.result,lexical,path.export,(path,),value.conditions)

    def text_candidates(self, read, path):
        if path.lexical is None:
            return
        lexical = path.lexical
        path_conditions = list(path.conditions)
        if not posixpath.isabs(lexical):
            lexical = posixpath.normpath(posixpath.join(self.entry.inputs.cwd,lexical))
            path_conditions.extend(('DECLARED_CWD_SELECTED_AND_PRESERVED','RELATIVE_PATH_HAS_NO_SYMLINK_REDIRECTION'))
        matches = [identity for identity,row in self.store.model_units.items() if row['path'] == lexical]
        if not matches:
            self.oblige(read.site.result,'NO_RETAINED_F0_ARTIFACT_AT_LEXICAL_PATH_CANDIDATE')
        for identity in matches:
            f0, raw, locator = self.f0(identity)
            values = {p.name:p.literal.to_python() for p in read.parameters if p.literal is not None}
            encoding = values.get('encoding')
            errors = values.get('errors')
            newline = values.get('newline')
            default_encoding = 'encoding' in values and encoding is None
            conditions, obligations = [], list(read.obligations)
            if default_encoding:
                encoding = 'utf-8'
                conditions.append('TEXT_OPEN_DEFAULT_ENCODING_SELECTS_UTF8')
                obligations.append('DEFAULT_ENCODING_CONTEXT_NOT_DECLARED_CONDITIONAL_UTF8_INTERPRETATION_ONLY')
            codecs = {'utf-8':'utf-8','utf8':'utf-8','utf-8-sig':'utf-8-sig',
                      'ascii':'ascii','latin-1':'latin-1','latin1':'latin-1','iso-8859-1':'latin-1'}
            encoding = codecs.get(encoding.lower()) if type(encoding) is str else None
            errors = 'strict' if 'errors' in values and errors is None else errors
            newline_ready = 'newline' in values and (newline is None or newline in ('','\n','\r','\r\n'))
            if encoding is None:
                obligations.append('TEXT_OPEN_ENCODING_NOT_SUPPORTED_OR_NOT_RESOLVED')
            if errors not in ('strict','ignore','replace'):
                obligations.append('TEXT_OPEN_ERRORS_NOT_SUPPORTED_OR_NOT_RESOLVED')
            if not newline_ready:
                obligations.append('TEXT_OPEN_NEWLINE_NOT_SUPPORTED_OR_NOT_RESOLVED')
            text_sha, characters = None, None
            if not read.obligations and encoding is not None and errors in ('strict','ignore','replace') and newline_ready:
                try:
                    with TextIOWrapper(BytesIO(raw),encoding=encoding,errors=errors,newline=newline) as stream:
                        text = stream.read()
                    text_sha, characters = sha256(text.encode('utf-8')).hexdigest(), len(text)
                except UnicodeError:
                    obligations.append('CAPTURED_BYTES_DO_NOT_HAVE_A_SUCCESSFUL_CANDIDATE_TEXT_INTERPRETATION')
            interpretation = X.TextOpenInterpretation(encoding,errors,newline,newline_ready,default_encoding,
                conditions=tuple(conditions),obligations=tuple(obligations))
            candidate = X.SourceTextCandidate(read.site.result,path.expression,identity,f0['path'],locator,
                _digest(f0),sha256(raw).hexdigest(),len(raw),interpretation,text_sha,characters,
                _conditions(_BASE,path_conditions,conditions,('PATH_CANDIDATE_SELECTS_CAPTURED_ARTIFACT',
                    'CAPTURED_FILE_VERSION_PRESERVED_UNTIL_READ','TEXT_READ_COMPLETES_NORMALLY')),
                tuple(obligations))
            self.candidates[_json(encode(candidate,record_tags=P.PRODUCTION_RECORD_TAGS))] = candidate

    def run(self):
        while self.queue:
            point, value = self.queue.popleft()
            for target in tuple(self.adj.get(point,())):
                self.offer(target,value)
            for ordinal, access in self.attributes.get(point,()):
                self.attribute(ordinal,access,value)
            for kind, ordinal in tuple(self.watch.get(point,())):
                if kind == 'call':
                    call = self.unit.calls[ordinal]
                    for callee in tuple(self.values[call.callee]):
                        self.call(ordinal,call,callee)
                else:
                    self.join(ordinal,self.unit.operations[ordinal])
        concrete = {v.expression for values in self.values.values() for v in values
                    if type(v) is _PathValue and v.lexical is not None}
        for expression in self.paths.values():
            if expression.id not in concrete:
                self.oblige(expression.result,'PATH_INPUT_OR_PLATFORM_VALUE_NOT_RESOLVED_SYMBOLIC_EXPRESSION_RETAINED')
        for read in self.reads.values():
            if not any(candidate.read_result==read.site.result for candidate in self.candidates.values()):
                self.oblige(read.site.result,'READ_TEXT_PATH_HAS_NO_CAPTURED_SOURCE_CANDIDATE')
        if (self.store.path/'result.json').read_bytes() != self.store.raw:
            raise ValueError('source fact catalog changed during projection')
        for model, manifest in self.manifests.items():
            if (model/'manifest.json').read_bytes() != manifest:
                raise ValueError('source model changed during projection')
        path_values = {}
        for expression in self.paths.values():
            for value in self.values[self.path_points[expression.id]]:
                if type(value) is _PathValue and value.expression == expression.id and value.lexical is not None:
                    candidate = X.SourcePathCandidate(expression.id,expression.result,value.lexical,
                        _conditions(_BASE,value.conditions))
                    path_values[_json(encode(candidate,record_tags=P.PRODUCTION_RECORD_TAGS))] = candidate
        return X.SourceTextOverlay(self.unit.unit,tuple(self.paths.values()),
            tuple(path_values[key] for key in sorted(path_values)),tuple(self.reads.values()),
            tuple(self.candidates.values()),tuple(sorted(self.obligations,key=lambda item:(str(item.port),item.reason))))


def source_text_candidates(store, unit, entry, *, max_path_values=8):
    """Use actual parent-store receipts; result remains conditional source data."""
    return _Projection(store,unit,entry,max_path_values).run()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--facts',required=True)
    parser.add_argument('--entry-contract',required=True)
    parser.add_argument('--out',required=True)
    args = parser.parse_args()
    store = SourceFactStore(args.facts)
    entry = read_script_entry(args.entry_contract,store)
    overlay = source_text_candidates(store,store.load(entry.source.unit),entry)
    out = Path(args.out).absolute()
    if out.exists():
        raise ValueError('fresh source-text output required')
    _durable_mkdir(out)
    tables = {name:write_table(out/(name+'.jsonl.gz'),getattr(overlay,name))
              for name in ('paths','path_values','reads','candidates','obligations')}
    report = dict(schema='scar.source-text-candidates',schema_version=1,
        status='CONDITIONAL_CAPTURED_SOURCE_TEXT_CANDIDATES',source_facts=str(store.path),
        source_facts_sha256=sha256(store.raw).hexdigest(),entry_contract=str(Path(args.entry_contract).absolute()),
        entry_result_sha256=sha256((Path(args.entry_contract)/'result.json').read_bytes()).hexdigest(),
        entry_sha256=sha256((Path(args.entry_contract)/'entry.json').read_bytes()).hexdigest(),
        unit=overlay.unit,tables=tables,target_executed=False,source_body_activated=False,
        exact_runtime_text_proven=False,first_stage_complete=False,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        types_sha256=sha256(Path(X.__file__).read_bytes()).hexdigest(),
        interpretation='TEXT_OPEN_RAW_BYTES_SEPARATE_FROM_F0_PEP263;DEFAULT_UTF8_IS_CONDITIONAL')
    _durable_bytes(out/'result.json',_json(report),replace=False)
    print(json.dumps(report),flush=True)


if __name__ == '__main__':
    main()
