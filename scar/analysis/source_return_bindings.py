"""Bounded retained source-call normal-return query, never another graph owner.

The session privately owns normal body-only ProgramIndexes. Returned views
reference original endpoints; no mutable graph/index is exposed or accepted as
an evidence token. Source/code admission and observed return selection are not
replayed or inferred here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re

from scar.ir.program.codec import loads as load_graph
from scar.ir.program.drivers import NormalResultPort
from scar.ir.program.functions import BodyEntryInterface
from scar.ir.program.model import CompletionResult, ExitKind, ReferenceValue, StateVersionValue, TerminatorKind, UseRole, ValueKind, value_type
from scar.ir.program.native import ExitPortRef
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.python_call_targets import PythonSourcePortBinding, PythonSourcePortModel
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.source_call_bindings import SourceBodyNamespace, SourceCallPortBinding, SourceCallPortModel
from scar.ir.program.source_returns import (SourceCallStateBinding, SourceNormalReturnBinding,
    SourceReturnSite, SourceStateCompletion, SourceStateTerminal)
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.record_codec import decode, encode, loads as strict_loads


def _need(value, detail):
    if not value:
        raise ValueError('source normal returns: ' + detail)


def _bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def _stamp(path):
    s = path.stat()
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def _pointer(document, pointer):
    _need(type(pointer) is str and (pointer == '#' or pointer.startswith('#/')), 'exact original JSON pointer required')
    selected = document
    for token in pointer[2:].split('/') if pointer != '#' else ():
        token = token.replace('~1', '/').replace('~0', '~')
        if type(selected) is list:
            _need(token.isdigit() and str(int(token)) == token, 'noncanonical array ordinal')
            selected = selected[int(token)]
        else:
            selected = selected[token]
    return selected


@dataclass(frozen=True, slots=True)
class SourceReturnBudget:
    max_model_stored_bytes: int = 64_000_000
    max_model_decoded_bytes: int = 128_000_000
    max_body_stored_bytes: int = 64_000_000
    max_body_decoded_bytes: int = 128_000_000
    max_declaration_stored_bytes: int = 32_000_000
    max_declaration_bytes: int = 128_000_000
    max_bodies: int = 16
    max_return_sites: int = 1024

    def __post_init__(self):
        _need(all(type(getattr(self, name)) is int and getattr(self, name) > 0 for name in self.__dataclass_fields__),
              'positive exact independent reader/query ceilings required')


@dataclass(frozen=True)
class _Body:
    namespace: SourceBodyNamespace
    index: ProgramIndex
    interface: BodyEntryInterface


class SourceReturnSession:
    """Read an accepted v1/v2 model and query original normal source ports."""

    def __init__(self, path, *, expected_sha256, budget=SourceReturnBudget()):
        _need(type(budget) is SourceReturnBudget, 'typed independent return-query budget required')
        budget.__post_init__()
        self._budget, self._watches, self._files, self._bodies = budget, {}, {}, {}
        self._counts = {'stored_bytes': 0, 'decoded_bytes': 0, 'body_codec_reads': 0, 'body_index_builds': 0}
        path = Path(path).absolute()
        raw, stored_bytes = self._read(path, expected_sha256, None, budget.max_model_stored_bytes,
                                       budget.max_model_decoded_bytes, compressed=path.suffix == '.gz')
        document = strict_loads(raw.decode('utf-8'))
        transport = document.get('schema'), document.get('schema_version')
        if transport == ('scar.source-call-port-bindings', 1):
            self._model = SourceCallPortModel.from_dict(document)
            self._pointer_prefix = '#/model/bindings/'
        elif transport == ('scar.python-source-port-bindings', 2):
            self._model = PythonSourcePortModel.loads(raw.decode('utf-8'))
            self._pointer_prefix = '#/bindings/'
        else:
            raise ValueError('source normal returns: unsupported original binding schema/version')
        self._artifact = ProviderArtifact(str(path), expected_sha256, stored_bytes, transport[0] + '/' + str(transport[1]))
        self._transport = transport
        self._check()

    def _check(self):
        for path, stamp in self._watches.items():
            _need(_stamp(path) == stamp, 'original retained input changed during query session')

    def _read(self, path, expected_sha256, expected_size, stored_limit, decoded_limit, *, compressed=False):
        path = Path(path).absolute()
        _need(not path.is_symlink() and path.is_file(), 'original retained artifact must be a regular file')
        before = _stamp(path)
        _need(before[2] <= stored_limit and (expected_size is None or before[2] == expected_size), 'stored artifact size/ceiling differs')
        with path.open('rb') as stream:
            stored = stream.read(stored_limit + 1)
        _need(len(stored) == before[2] and sha256(stored).hexdigest() == expected_sha256, 'original stored artifact SHA differs')
        if compressed:
            with gzip.GzipFile(fileobj=BytesIO(stored)) as stream:
                raw = stream.read(decoded_limit + 1)
        else:
            raw = stored
        _need(len(raw) <= decoded_limit and _stamp(path) == before, 'decoded ceiling/input stability failed')
        self._watches[path] = before
        self._counts['stored_bytes'] += len(stored)
        self._counts['decoded_bytes'] += len(raw)
        return raw, len(stored)

    def _declaration(self, namespace):
        declaration = namespace.graph.declaration
        _need(declaration is not None, 'original namespace declaration required')
        artifact = declaration.artifact
        key = ('declaration', artifact)
        if key not in self._files:
            raw, _ = self._read(Path(artifact.uri), artifact.sha256, artifact.size_bytes,
                                self._budget.max_declaration_stored_bytes, self._budget.max_declaration_bytes,
                                compressed=Path(artifact.uri).suffix == '.gz')
            self._files[key] = strict_loads(raw.decode('utf-8'))
        value = _pointer(self._files[key], declaration.locator)
        a = namespace.graph.artifact
        if type(value) is dict and set(value) == {'uri', 'sha256', 'size_bytes', 'schema'}:
            _need(value == encode(a), 'catalog declaration names a different original body artifact')
        elif type(value) is dict and set(value) == {'artifact', 'namespace', 'pointer'}:
            # Original composition checkpoint locator. Its stored receipt and
            # qualified body namespace are separate from the wrapper artifact.
            receipt = value['artifact']
            expected_namespace = {
                'artifact': {'uri': a.uri, 'decoded_sha256': namespace.graph.decoded_sha256},
                'body': {'definition': encode(namespace.definition), 'entry': namespace.entry,
                         'source': encode(namespace.source)},
                'record_pointer': namespace.graph.pointer,
                'representation': namespace.graph_representation,
            }
            _need(value['namespace'] == expected_namespace and value['pointer'] == namespace.graph.pointer
                  and receipt['uri'] == a.uri and receipt['physical_sha256'] == a.sha256
                  and receipt['physical_bytes'] == a.size_bytes
                  and receipt['decoded_sha256'] == namespace.graph.decoded_sha256
                  and receipt['decoded_bytes'] == namespace.graph.decoded_bytes
                  and receipt['representation'] == a.schema,
                  'composition checkpoint declaration differs from the original qualified body')
        elif artifact.schema == 'scar.source-invocation-bindings/4':
            # Retained v4 source-invocation rows are a static source/body
            # association. They do not recreate the producer's former proof
            # owner or promote the row to a fresh invocation binding.
            match = re.fullmatch(r"#/bindings/(0|[1-9][0-9]*)/body/canonical_locator",
                                declaration.locator)
            _need(match is not None, 'v4 source-body declaration must select one original group locator')
            ordinal = int(match.group(1))
            document = self._files[key]
            _need(type(document) is dict and document.get('schema') == 'scar.source-invocation-bindings'
                  and type(document.get('schema_version')) is int and document['schema_version'] == 4
                  and document.get('transformation_authorized') is False,
                  'v4 source-invocation declaration header differs')
            rows = document.get('bindings')
            _need(type(rows) is list and ordinal < len(rows), 'v4 source-invocation group is absent')
            row = rows[ordinal]
            _need(row.get('binding_index') == ordinal
                  and row.get('status') == 'BODY_LINKED_REUSED_WITNESS'
                  and row.get('complete_descriptor_match') is True
                  and type(row.get('body')) is dict,
                  'v4 group is not an original qualified body association')
            original_locator = replace(namespace.graph, declaration=None)
            retained_locator = row['body'].get('canonical_locator')
            exact_typed_locator = retained_locator == encode(original_locator)
            legacy_locator = (type(retained_locator) is dict
                and set(retained_locator) == {'artifact', 'namespace', 'pointer'}
                and type(retained_locator.get('artifact')) is dict
                and set(retained_locator['artifact']) == {
                    'uri', 'physical_sha256', 'physical_bytes', 'decoded_sha256',
                    'decoded_bytes', 'representation'
                })
            if legacy_locator:
                a = retained_locator['artifact']
                legacy_locator = (retained_locator.get('pointer') == original_locator.pointer
                    and retained_locator.get('namespace') == namespace.original_namespace()
                    and a.get('uri') == original_locator.artifact.uri
                    and a.get('physical_sha256') == original_locator.artifact.sha256
                    and a.get('physical_bytes') == original_locator.artifact.size_bytes
                    and a.get('decoded_sha256') == original_locator.decoded_sha256
                    and a.get('decoded_bytes') == original_locator.decoded_bytes
                    and a.get('representation') == original_locator.artifact.schema)
            _need((exact_typed_locator or legacy_locator)
                  and row['body'].get('namespace') == namespace.original_namespace(),
                  'v4 group declares a different original source-program/checkpoint namespace')
            from scar.ir.program.source_references import SourceDefinitionReference
            original = decode(SourceDefinitionReference, row['definition'])
            _need(original.definition == namespace.definition and original.source == namespace.source
                  and row['body']['namespace']['body']['entry'] == namespace.entry
                  and row['body']['namespace']['artifact']['uri'] == a.uri
                  and row['body']['namespace']['artifact']['decoded_sha256'] == namespace.graph.decoded_sha256,
                  'v4 source definition/body locator differs from the qualified namespace')
        else:
            _need(type(value) is dict and value.get('uri') == a.uri
                  and value.get('physical_sha256') == a.sha256 and value.get('physical_bytes') == a.size_bytes
                  and value.get('decoded_sha256') == namespace.graph.decoded_sha256
                  and value.get('decoded_bytes') == namespace.graph.decoded_bytes
                  and value.get('representation') == a.schema, 'publication declaration differs from original body artifact')

    def _body(self, namespace):
        _need(type(namespace) is SourceBodyNamespace, 'exact original source body namespace required')
        namespace.__post_init__()
        _need(namespace.source is not None, 'Python return rule needs the original source reference')
        self._check()
        if namespace in self._bodies:
            return self._bodies[namespace]
        _need(len(self._bodies) < self._budget.max_bodies, 'private body-index budget exhausted')
        self._declaration(namespace)
        locator = namespace.graph
        key = ('body-artifact', locator.artifact, locator.decoded_sha256, locator.decoded_bytes, locator.representation)
        if key not in self._files:
            _need(locator.representation in ('canonical-json', 'gzip-canonical-json'), 'unsupported original source-body encoding')
            raw, _ = self._read(Path(locator.artifact.uri), locator.artifact.sha256, locator.artifact.size_bytes,
                self._budget.max_body_stored_bytes, self._budget.max_body_decoded_bytes,
                compressed=locator.representation == 'gzip-canonical-json')
            _need((len(raw), sha256(raw).hexdigest()) == (locator.decoded_bytes, locator.decoded_sha256), 'original decoded body artifact differs')
            self._files[key] = strict_loads(raw.decode('utf-8'))
        document = self._files[key]
        graph_document = _pointer(document, locator.pointer)
        if locator.pointer == '#/graph' and (
                document.get('schema') == 'scar.source-program'
                or (document.get('schema') == 'scar.body-construction-checkpoint'
                    and type(document.get('schema_version')) is int and document['schema_version'] == 1)):
            header, interface = document, document.get('interface')
        else:
            _need(document.get('schema') == 'scar.program-inventory' and locator.pointer.endswith('/graph'), 'unsupported original source-body locator/header')
            header = _pointer(document, locator.pointer[:-len('/graph')])
            candidates = [r for r in document['interfaces']['bodies'] if r['definition'] == encode(namespace.definition)]
            _need(len(candidates) == 1, 'original inventory body has no unique normal interface')
            interface = candidates[0]
        _need(header['metadata']['entry'] == namespace.entry
              and header['metadata']['source']['path'] == namespace.source.path
              and header['metadata']['source']['fingerprint'] == namespace.source.fingerprint
              and header['structured']['source'] == encode(namespace.source), 'body namespace/source/header differs')
        interface = decode(BodyEntryInterface, interface)
        _need(interface.definition == namespace.definition and interface.region == namespace.region
              and namespace.graph_representation == 'scar.program-graph/' + str(graph_document['schema_version']),
              'body namespace definition/root/representation differs')
        # Only the selected canonical graph is decoded/validated. The enclosing
        # SourceProgram semantic/semantics/control contexts are not revalidated.
        graph = load_graph(_bytes(graph_document).decode('utf-8'))
        _need(graph.root == namespace.region, 'original body graph has a different root namespace')
        index = ProgramIndex(graph)
        self._counts['body_codec_reads'] += 1; self._counts['body_index_builds'] += 1
        entry = index.entry_arguments(graph.root)
        _need(type(index.values[interface.world]) is StateVersionValue and entry[-1].id == interface.world,
              'normal Python body has no exact original final entry world port')
        result = _Body(namespace, index, interface)
        self._bodies[namespace] = result
        return result

    @staticmethod
    def _python_signature(types, world):
        _need(len(types) == 2 and types[0].kind is ValueKind.REFERENCE and types[1] == value_type(world),
              'single Python reference result0 and separate original world port required')

    def normal_return(self, binding_index):
        _need(type(binding_index) is int and 0 <= binding_index < len(self._model.bindings), 'exact original binding ordinal required')
        binding = self._model.bindings[binding_index]
        binding.__post_init__()
        caller = self._body(binding.caller_body); callee = self._body(binding.callee_body)
        ci, di = caller.index, callee.index
        _need(binding.caller_code.source == binding.caller_body.source and binding.callee_code.source == binding.callee_body.source,
              'original code/source links differ from body namespaces')
        call = ci.operations[binding.call.core_operation]
        _need(binding.call.execution_owner == caller.interface.definition and binding.call.core_region == ci.graph.root
              and call.id == binding.call.core_operation and call.terminator is not None
              and call.terminator.kind is TerminatorKind.INVOKE
              and call.invoke_arguments[0] == binding.call.callee_use
              and ci.use_site(binding.call.callee_use).operation == call.id
              and ci.use_site(binding.call.callee_use).use.value == binding.call.callee_value,
              'original source binding does not select this Python CALL interface')
        ports = binding.ports if type(binding) is SourceCallPortBinding else binding.arguments
        for port in ports:
            _need(port.actual_body == caller.namespace and port.formal_body == callee.namespace
                  and ci.use_site(port.actual_use).operation == call.id
                  and ci.use_site(port.actual_use).use.value == port.actual_value
                  and any(p.slot == port.formal_slot and p.value == port.formal_value for p in callee.interface.parameters),
                  'original actual/formal port or source namespace differs')
        normal = [(n, e) for n, e in enumerate(call.terminator.successors) if e.kind is ExitKind.NORMAL]
        signatures = [s for s in call.completions if s.kind is ExitKind.NORMAL]
        _need(len(normal) == len(signatures) == 1, 'bound CALL has no unique original normal completion')
        edge_number, edge = normal[0]
        self._python_signature(signatures[0].types, ci.values[caller.interface.world])
        positions = [n for n, operand in enumerate(edge.arguments) if type(operand) is CompletionResult and operand.index == 0]
        _need(len(positions) == 1, 'normal object completion0 has no unique landing argument')
        position = positions[0]
        landing = ci.normal_result(call.id, NormalResultPort(0))
        _need(type(landing) is ReferenceValue and di.graph.root == binding.callee_body.region,
              'normal result is not the original Python object reference')
        sites = []
        region = di.regions[di.graph.root]
        for exit_ in region.exits:
            if exit_.kind is not ExitKind.NORMAL:
                continue
            self._python_signature(exit_.types, di.values[callee.interface.world])
            port = ExitPortRef(region.id, exit_.name, 0)
            for site in di.exit_port_uses(port):
                _need(len(sites) < self._budget.max_return_sites, 'normal may-return site budget exhausted')
                op = di.operations[site.operation]
                _need(op.terminator is not None and op.terminator.kind is TerminatorKind.RETURN
                      and op.terminator.exit == exit_.name and len(op.terminator.values) == 2
                      and op.terminator.values[0] == site.use.id and site.use.role is UseRole.REFERENCE
                      and type(di.values[site.use.value]) is ReferenceValue, 'callee payload is not its original normal terminal reference Use')
                world_site = di.use_site(op.terminator.values[1])
                _need(world_site.operation == op.id and world_site.use.role is UseRole.STATE_CONTENT
                      and type(di.values[world_site.use.value]) is StateVersionValue,
                      'callee world was mixed into object result payload')
                sites.append(SourceReturnSite(port, di._operation_blocks[op.id], op.id, site.use.id, site.use.value, 0))
        _need(bool(sites), 'callee has no original normal terminal payload Use')
        caller_key, callee_key = ((binding.caller, binding.callee) if type(binding) is SourceCallPortBinding
                                  else (binding.entry.caller, binding.entry.callee))
        result = SourceNormalReturnBinding(ProviderFactReference(self._artifact, self._pointer_prefix + str(binding_index)),
            binding_index, caller_key, callee_key, caller.namespace, callee.namespace, call.id,
            ControlEdgeReference(call.id, edge_number), CompletionResult(0), edge.block, position,
            landing.id, tuple(sites))
        self._check()
        return result

    def verify(self, view):
        _need(type(view) is SourceNormalReturnBinding, 'typed normal-return view required')
        view.__post_init__()
        _need(self.normal_return(view.binding_index) == view, 'return view differs from exact original binding/namespace/ports')
        return view

    def state_transfer(self, binding_index):
        """Connect original world ports without equating caller/callee state.

        Every completion remains a conditional alternative. In particular, an
        exception still returns its post-state: effect dependencies cannot be
        dropped just because no normal Python value is returned.
        """
        _need(type(binding_index) is int and 0 <= binding_index < len(self._model.bindings),
              'exact original binding ordinal required')
        binding = self._model.bindings[binding_index]
        caller, callee = self._body(binding.caller_body), self._body(binding.callee_body)
        ci, di = caller.index, callee.index
        call = ci.operations[binding.call.core_operation]
        _need(binding.call.execution_owner == caller.interface.definition
              and binding.call.core_region == ci.graph.root
              and call.terminator is not None and call.terminator.kind is TerminatorKind.INVOKE
              and call.invoke_arguments and call.invoke_arguments[0] == binding.call.callee_use
              and ci.use_site(binding.call.callee_use).use.value == binding.call.callee_value,
              'original bound Python CALL interface differs')
        use = ci.use_site(call.invoke_arguments[-1])
        before, formal = ci.values[use.use.value], di.values[callee.interface.world]
        _need(use.operation == call.id and use.use.role is UseRole.STATE_CONTENT
              and type(before) is type(formal) is StateVersionValue
              and before.location == ci.values[caller.interface.world].location,
              'CALL final argument must be the original coarse world Use')
        routes = []
        root = di.regions[di.graph.root]
        for number, edge in enumerate(call.terminator.successors):
            signatures = [s for s in call.completions if s.kind is edge.kind]
            _need(len(signatures) == 1, 'call completion has no unique original signature')
            types = signatures[0].types
            slots = [n for n, t in enumerate(types) if t == value_type(before)]
            _need(len(slots) == 1, 'call completion must expose one separate world slot')
            slot = slots[0]
            positions = [n for n, operand in enumerate(edge.arguments)
                         if type(operand) is CompletionResult and operand.index == slot]
            _need(len(positions) == 1, 'completion world has no unique original landing argument')
            position = positions[0]
            block = ci._block_records[edge.block]
            landing = ci.values[block.arguments[position]]
            _need(type(landing) is StateVersionValue and landing.location == before.location,
                  'completion world landing belongs to a different state domain')
            sites = []
            for exit_ in root.exits:
                if exit_.kind is not edge.kind:
                    continue
                world_slots = [n for n, t in enumerate(exit_.types) if t == value_type(formal)]
                _need(len(world_slots) == 1, 'callee exit must expose one separate world slot')
                exit_slot = world_slots[0]
                port = ExitPortRef(root.id, exit_.name, exit_slot)
                for site in di.exit_port_uses(port):
                    _need(len(sites) < self._budget.max_return_sites, 'state terminal site budget exhausted')
                    op = di.operations[site.operation]
                    terminal = op.terminator
                    expected_kind = TerminatorKind.RETURN if edge.kind is ExitKind.NORMAL else TerminatorKind.RAISE
                    value = di.values[site.use.value]
                    _need(terminal is not None and terminal.kind is expected_kind
                          and terminal.exit == exit_.name and terminal.values[exit_slot] == site.use.id
                          and site.use.role is UseRole.STATE_CONTENT
                          and type(value) is StateVersionValue and value.location == formal.location,
                          'callee completion world is not its original terminal state Use')
                    sites.append(SourceStateTerminal(port, di._operation_blocks[op.id], op.id,
                                                      site.use.id, site.use.value, value.location))
            routes.append(SourceStateCompletion(edge.kind, ControlEdgeReference(call.id, number),
                          CompletionResult(slot), edge.block, position, landing.id, tuple(sites)))
        result = SourceCallStateBinding(
            ProviderFactReference(self._artifact, self._pointer_prefix + str(binding_index)), binding_index,
            caller.namespace, callee.namespace, call.id, use.use.id, before.id, before.location,
            formal.id, formal.location, tuple(routes))
        self._check()
        return result

    def query(self, binding_index, *, include_state=False):
        route = self.normal_return(binding_index)
        binding = self._model.bindings[binding_index]
        ports = binding.ports if type(binding) is SourceCallPortBinding else binding.arguments
        result = {'schema': 'scar.source-normal-return-query', 'schema_version': 1,
            'qualification': 'CONDITIONAL_LANGUAGE_NORMAL_RETURN_PORTS', 'return': encode(route),
            'original_binding_conditions': encode(binding.conditions),
            'original_argument_ports': encode(ports),
            'receiver': encode(binding.receiver) if type(binding) is PythonSourcePortBinding else None,
            'callee_region': encode(binding.callee_body.region),
            'observed_return_site_selected': False, 'object_identity_established': False,
            'content_equivalence_established': False, 'effects_or_world_equivalence_established': False,
            'producer_inputs_replayed': False, 'transformation_authorized': False,
            'costs': dict(self._counts)}
        if include_state:
            result['state_transfer'] = encode(self.state_transfer(binding_index))
            result['state_conditions'] = ['ORIGINAL_TARGET_AND_ENTRY_BINDING',
                'CALLEE_EXIT_AND_CALL_COMPLETION_MATCH', 'TERMINAL_AND_COMPLETION_EDGE_SELECTED']
            result['state_preservation_established'] = False
            result['fine_state_footprints_established'] = False
            result['costs'] = dict(self._counts)
        return result


def query_source_returns_cli(args):
    """Follow one original conditional call binding through its normal result."""
    import time
    started = time.monotonic()
    session = SourceReturnSession(args.model, expected_sha256=args.sha256)
    result = session.query(args.binding_index, include_state=args.include_state)
    result['elapsed_s'] = time.monotonic() - started
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.out:
        with Path(args.out).open('x', encoding='utf-8') as stream:
            stream.write(payload)
    else:
        print(payload, end='')
    return 0
