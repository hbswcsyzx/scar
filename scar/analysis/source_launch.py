"""Register script inputs without running or importing the target program.

F0/F2 and the original F5 root supply source identity. Parser-only flags are
not runtime compilation flags. Unlisted environment fields remain unknown.
"""
import argparse
import __future__
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.source_bytes import read_source_bytes
from scar.analysis.source_syntax import _digest
from scar.analysis.static_query import _Fragments
from scar.analysis.source_template_links import _json
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.call_compilation import future_flags_for
from scar.ir.program.compilation import CallCompilationProfile
from scar.ir.literals import PythonLiteral
from scar.ir.program import source_launch as L, normal_links as F
from scar.ir.program import normal_graph as G, normal_targets as T, source_productions as P
from scar.ir.program.source_bytes import SourceBytesProfile
from scar.ir.record_codec import decode, encode


def source_future_features(syntax):
    """Read only the module preamble in the retained official F2 tree."""
    nodes = syntax['nodes']
    fields = {row['name']:dict(zip(row['fields'], range(len(row['fields']))))
              for row in syntax['profile']['ast_schema']}

    def member(node, name):
        return node['fields'][fields[node['constructor']][name]]

    def scalar(node, name):
        return decode(PythonLiteral, member(node, name)['scalar']).to_python()

    root = nodes[syntax['root']]
    if root['constructor'] != 'Module':
        return ()
    features = []
    for index, value in enumerate(member(root, 'body')['items']):
        node = nodes[value['reference']]
        if index == 0 and node['constructor'] == 'Expr':
            expression = nodes[member(node, 'value')['reference']]
            if expression['constructor'] == 'Constant' and type(scalar(expression, 'value')) is str:
                continue
        if (node['constructor'] != 'ImportFrom' or scalar(node, 'module') != '__future__'
                or scalar(node, 'level') != 0):
            break
        for alias in member(node, 'names')['items']:
            name = scalar(nodes[alias['reference']], 'name')
            if name not in __future__.all_feature_names:
                raise ValueError('source future feature is outside the current compiler catalog')
            features.append(name)
    return tuple(dict.fromkeys(features))


def declare_script_entry(store, script, *, cwd, argv, environment=(),
                         environment_complete=False, executable=None, optimize=0):
    """Bind one declared script launch to original source/root/name ports.

    This does not perform EntrySolver activation. It supplies initial facts for
    that later layer. Existing namespace writes must still be represented.
    """
    if type(store) is not SourceFactStore:
        raise TypeError('an original SourceFactStore is required')
    cwd = str(Path(cwd).absolute())
    source_path = Path(script)
    source_path = source_path if source_path.is_absolute() else Path(cwd)/source_path
    identities = store.units_for_source(source_path)
    if len(identities) != 1:
        raise ValueError('script source must select one original unit')
    identity, = identities
    unit = store.load(identity)
    model = Path(store.model_for(identity))
    manifest_raw = (model/'manifest.json').read_bytes()
    model_unit = store.model_units[identity]
    reader = _Fragments(model)
    f0 = reader.read(model_unit['artifacts']['source_bytes'])
    syntax = reader.read(model_unit['artifacts']['source_syntax'])
    raw = read_source_bytes(f0)
    if (syntax['status'] != 'PARSED' or syntax['mode'] != 'exec'
            or syntax['input']['f0_document_sha256'] != _digest(f0)
            or syntax['input']['raw_sha256'] != sha256(raw).hexdigest()
            or f0['path'] != str(source_path) or unit.root_scope is None):
        raise ValueError('entry source and retained syntax/root differ')
    features = source_future_features(syntax)
    # Feature names in source are not the effective co_flags. Mandatory
    # historical features can have obsolete nonzero catalog bits, and
    # nested_scopes even overlaps CO_NESTED. Reuse the compiler and existing
    # future/structural-mask policy; compilation never executes this code.
    compiled = compile(raw, f0['path'], 'exec', flags=0, dont_inherit=True,
                       optimize=0 if optimize is None else optimize)
    future_flags = future_flags_for(compiled.co_flags,
                                   CallCompilationProfile.RECORDED_FUTURE_FLAGS)
    source = L.EntrySourceSnapshot(identity, f0['path'], str(model), sha256(manifest_raw).hexdigest(),
        _digest(f0), _digest(syntax), sha256(raw).hexdigest(), len(raw),
        decode(SourceBytesProfile, f0['profile']))
    # A script is compiled without a Python caller's future flags. The
    # optimize level is a declared launch input, not the analyzer's setting.
    context = L.SourceCompilationContext(f0['path'], 'exec', 0, True, 0, future_flags, optimize)
    inputs = L.ScriptLaunchInputs(cwd, argv, environment, environment_complete, executable)
    initial = {'__name__':'__main__', '__file__':f0['path'], '__package__':None, '__spec__':None}
    bindings = []
    for name, literal in initial.items():
        namespace = F.Namespace(F.NamespaceKind.MODULE, 0, name)
        points = dict.fromkeys(access.value for access in unit.names
            if not access.write and access.namespace == namespace)
        reads = []
        for point in points:
            port = unit.ports[point]
            if type(port) is dict:
                port = decode(G.Port, port, record_tags=P.PRODUCTION_RECORD_TAGS)
            reads.append(T.GlobalPort(identity, port))
        bindings.append(L.EntryGlobalBinding(namespace, PythonLiteral.from_python(literal), tuple(reads)))
    # Recheck the actual retained parents, without opening the live target.
    if (model/'manifest.json').read_bytes() != manifest_raw:
        raise ValueError('entry source manifest changed during declaration')
    return L.ScriptEntryContract(source, unit.root_scope, context, inputs, tuple(bindings),
        features, sha256(Path(__future__.__file__).read_bytes()).hexdigest())


def read_script_entry(path, store):
    """Revalidate the declaration against its original source/root interfaces."""
    path = Path(path).absolute()
    report = json.loads((path/'result.json').read_bytes())
    if (report['schema'], report['schema_version']) != ('scar.source-script-entry', 1):
        raise ValueError('a script-entry declaration is required')
    if (report['source_facts_sha256'] != sha256(store.raw).hexdigest()
            or Path(report['source_facts']) != store.path
            or report['implementation_sha256'] != sha256(Path(__file__).read_bytes()).hexdigest()
            or report['types_sha256'] != sha256(Path(L.__file__).read_bytes()).hexdigest()):
        raise ValueError('script-entry producer or source parents differ')
    receipt = report['entry']
    if receipt['path'] != 'entry.json':
        raise ValueError('unexpected script-entry fragment')
    raw = (path/'entry.json').read_bytes()
    if len(raw) != receipt['bytes'] or sha256(raw).hexdigest() != receipt['sha256']:
        raise ValueError('script-entry fragment differs')
    contract = decode(L.ScriptEntryContract, json.loads(raw), record_tags=P.PRODUCTION_RECORD_TAGS)
    expected = declare_script_entry(store, contract.source.path, cwd=contract.inputs.cwd,
        argv=contract.inputs.argv, environment=contract.inputs.environment,
        environment_complete=contract.inputs.environment_complete,
        executable=contract.inputs.executable, optimize=contract.compilation.optimize)
    if expected != contract:
        raise ValueError('script-entry source/root/globals/compilation references differ')
    return contract


def initial_scalar_fields(contract, unit):
    """Connect declared globals to one unit's static scalar fields.

    The entry contract remains the enclosing assumption. Later namespace
    writes and all original source constraints remain in the may graph.
    No argv list or environment dictionary is offered as a tuple constant.
    """
    from scar.analysis.source_scalar_values import collect_unit
    if (type(contract) is not L.ScriptEntryContract
            or unit.unit != contract.source.unit or unit.root_scope != contract.root):
        raise ValueError('entry scalar fields require their original source unit')
    flow = collect_unit(unit)
    for binding in contract.globals:
        for port in binding.reads:
            flow.offer(port, binding.literal)
    flow.drain()
    return flow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--facts', required=True)
    parser.add_argument('--script', required=True)
    parser.add_argument('--cwd', required=True)
    parser.add_argument('--python')
    parser.add_argument('--env', action='append', default=[], metavar='NAME=VALUE')
    parser.add_argument('--unset-env', action='append', default=[])
    parser.add_argument('--optimize', type=int, choices=(0,1,2), default=0)
    parser.add_argument('--out', required=True)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    environment = []
    for item in args.env:
        name, separator, value = item.partition('=')
        if not separator or not name:
            raise ValueError('--env requires an explicit NAME=VALUE')
        environment.append(L.InitialEnvironmentEntry(name, value))
    environment.extend(L.InitialEnvironmentEntry(name, None) for name in args.unset_env)
    remaining = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    store = SourceFactStore(args.facts)
    contract = declare_script_entry(store, args.script, cwd=args.cwd,
        argv=(args.script, *remaining), environment=tuple(environment),
        executable=args.python, optimize=args.optimize)
    out = Path(args.out).absolute()
    if out.exists():
        raise ValueError('fresh entry declaration output required')
    _durable_mkdir(out)
    document = _json(encode(contract, record_tags=P.PRODUCTION_RECORD_TAGS))
    _durable_bytes(out/'entry.json', document, replace=False)
    report = dict(schema='scar.source-script-entry', schema_version=1,
        status='DECLARED_STATIC_ENTRY_CONTRACT', source_facts=str(store.path),
        source_facts_sha256=sha256(store.raw).hexdigest(),
        entry=dict(path='entry.json', bytes=len(document), sha256=sha256(document).hexdigest()),
        unit=contract.source.unit, source=contract.source.path,
        source_future_features=contract.source_future_features,
        effective_flags=contract.compilation.effective_flags,
        global_reads=sum(len(binding.reads) for binding in contract.globals),
        target_executed=False, runtime_observed=False, body_activated=False,
        first_stage_complete=False,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        types_sha256=sha256(Path(L.__file__).read_bytes()).hexdigest())
    _durable_bytes(out/'result.json', _json(report), replace=False)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
