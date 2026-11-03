"""Observed CALL interfaces over the original shared program graph.

Admission replays raw capture and source interfaces. Saved DTOs are never
accepted as proofs. Ordinary static neighborhoods are not modified.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import re

from scar.analysis.observed_call_bindings import derive_observed_interfaces
from scar.ir.program.call_edges import FrameCompletion
from scar.ir.program.dependencies import (DependencyCondition, DependencyEdge,
    DependencyEvidence, DependencyKind as K, DependencyMeaning as M,
    DependencyPoint as P, DependencyStrength, GraphNamespace)
from scar.ir.program.model import CompletionResult, ExitKind, StateVersionValue, TerminatorKind, UseRole, ValueKind
from scar.ir.program.native_callables import NativeCarrier, NativeFieldState
from scar.ir.program.observed_dependencies import (ObservedCallLayout, ObservedCallScope, ObservedDependencyEdge,
    ObservedDependencyFrontier, ObservedDependencyNeighborhood, ObservedPortPhase as Phase,
    ObservedNativeCallable, ObservedNativeCallableFrontier, ObservedPortPoint)
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import decode, encode, loads


_INPUT = re.compile(r'(?:call-(?:codes|events|meta|operands|operand-meta)|'
    r'python-call-(?:targets|target-meta)|native-callables|native-callable-meta|lean-plan|captured-source-meta)'
    r'\.[1-9][0-9]*\.(?:jsonl|json)(?:\.gz)?$')


def _inputs(directory):
    from scar.analysis.program_dependency_session import _stamp
    result = {}
    for path in directory.iterdir():
        if not _INPUT.fullmatch(path.name):
            continue
        if path.is_symlink() or not path.is_file() or path.resolve() != path:
            raise ValueError('observed capture inputs must be original canonical files')
        result[path] = _stamp(path)
    return result


def _native_inputs(capture):
    """Pin all companion dependencies, including the external probe receipts."""
    from scar.analysis.program_dependency_session import _stamp
    result, receipts = {}, {}
    for metadata in capture.metadata:
        for receipt in (metadata.probe_source, metadata.probe_binary, metadata.target_meta):
            path = Path(receipt.path)
            expected = receipt.bytes, receipt.sha256
            if path in receipts and receipts[path] != expected:
                raise ValueError('native callable dependencies have conflicting original receipts')
            receipts[path] = expected
        for receipt in metadata.legacy_inputs:
            path = Path(receipt.path)
            if not path.exists():
                path = Path(str(path) + '.gz')
            if not path.is_absolute() or path.resolve() != path or path.is_symlink() or not path.is_file():
                raise ValueError('native callable legacy input is not an original canonical file')
            result[path] = _stamp(path)
    for path, (size, expected_sha256) in receipts.items():
        if not path.is_absolute() or path.resolve() != path or path.is_symlink() or not path.is_file():
            raise ValueError('native callable dependency is not an original canonical file')
        before = _stamp(path)
        if before[2] != size:
            raise ValueError('native callable dependency byte receipt changed')
        digest = sha256()
        with path.open('rb') as stream:
            remaining = size
            while remaining:
                block = stream.read(min(1_048_576, remaining))
                if not block:
                    raise ValueError('native callable dependency was truncated')
                digest.update(block)
                remaining -= len(block)
            if stream.read(1):
                raise ValueError('native callable dependency grew')
        if before != _stamp(path) or digest.hexdigest() != expected_sha256:
            raise ValueError('native callable dependency changed since the original capture')
        result[path] = before
    return result


class ObservedDependencyProvider:
    def __init__(self, session, trace):
        directory = Path(getattr(trace, 'directory', trace)).absolute()
        if directory.resolve() != directory or directory.is_symlink():
            raise ValueError('observed capture directory must be canonical')
        before = _inputs(directory)
        argument_layouts = {}
        bindings, interfaces, evidence, issues = derive_observed_interfaces(session, trace,
            argument_layouts=argument_layouts)
        from scar.analysis.native_callables import read_native_callables
        native = read_native_callables(evidence.trace)
        native_stamps = {} if native is None else _native_inputs(native)
        after = _inputs(directory)
        if before != after:
            raise ValueError('observed capture inputs changed during admission')
        self.session, self.directory, self._stamps = session, directory, after
        self._native_stamps = native_stamps
        self.native_protocols = self.native_protocol_manifest = None
        self._protocol_stamps = {}
        self.run_scope = evidence.targets.source_sha256
        if native is not None and (native.run_scope != self.run_scope or native.directory != str(directory)):
            raise ValueError('native callable companion belongs to another original trace/run')
        self.bindings, self.interfaces, self.issues = bindings, interfaces, issues
        self.capture_files = (*evidence.trace.frame_scan.files, *evidence.trace.files,
            *(() if native is None else native.files))
        self.target_count = len(evidence.targets.targets)
        self._bindings, self._interfaces = {}, {}
        self._before, self._after = defaultdict(dict), defaultdict(dict)
        self._ports, self._notes = {}, defaultdict(dict)
        self._layouts = []
        entries = {(e.caller, e.attempt_index): (e, anchor)
                   for e, anchor in zip(evidence.targets.entries, evidence.targets.entry_anchors)}
        frames = {frame.invocation: frame for frame in evidence.trace.entries}
        exits = defaultdict(list)
        for exit_ in evidence.trace.exits:
            exits[exit_.invocation].append(exit_)
        selected = {(item.binding.target.caller, item.binding.target.attempt_index): item
                    for item in interfaces}
        for binding in bindings:
            target = binding.target
            entry = entries.get((target.caller, target.attempt_index))
            callee = entry_anchor = frame_anchor = exit_anchor = None
            if entry is not None:
                e, anchor = entry
                frame = frames[e.callee]
                if (frame.caller_invocation == target.caller and frame.code == target.code
                        and not frame.suspended and frame.path == (binding.captured_site,)):
                    callee, entry_anchor, frame_anchor = e.callee, anchor, frame.anchor
                    actual_exits = exits[callee]
                    if len(actual_exits) == 1:
                        exit_anchor = actual_exits[0].anchor
            scope = ObservedCallScope(binding.run_scope, target.caller, target.attempt_index,
                binding.attempt_anchor, binding.target_anchor, callee, entry_anchor, frame_anchor, exit_anchor)
            self._bindings[scope] = binding
            self._ports[scope] = {}
            call = self._point(scope, binding.call, Phase.CALL_SITE)
            callable_ = self._point(scope, binding.callable, Phase.CALL_SITE)
            self._edge(callable_, call, K.OPERAND, M.DEPENDENCE, 'OBSERVED_CALL_CALLEE_USE_V1')
            item = selected.get((target.caller, target.attempt_index))
            if item is None:
                self._note(call, 'OBSERVED_FUNCTION_INTERFACE_OPEN',
                    'Actual callable is captured; its body/signature/receiver/native interface is not fully joined.')
                continue
            if (scope.callee != item.entry.callee or scope.entry_anchor != item.entry_anchor
                    or scope.frame_entry != item.frame_entry
                    or (item.observed_exit is not None and scope.exit_anchor != item.observed_exit.anchor)):
                raise ValueError('observed interface changed the original direct entry/exit occurrence')
            self._interfaces[scope] = item
            self._join(scope, item, argument_layouts.get((target.caller, target.attempt_index), ()))
        self.native_metadata = None if native is None else native.metadata
        self.native_callables = self.native_frontiers = None
        if native is not None:
            joined, unbound = [], []
            scopes = {(scope.caller, scope.attempt_index): scope for scope in self._bindings}
            for fact, anchor in zip(native.facts, native.anchors):
                scope = scopes.get((fact.caller, fact.attempt_index))
                if scope is None:
                    unbound.append(ObservedNativeCallableFrontier(self.run_scope, fact, anchor,
                        'NATIVE_CALLABLE_STATIC_BINDING_OPEN',
                        'The original callable fact has no retained static CALL binding; no program port is invented.'))
                    continue
                binding = self._bindings[scope]
                if fact.callable_reference != binding.target.callable_reference:
                    raise ValueError('native callable fact changed its original target token')
                call = self._point(scope, binding.call, Phase.CALL_SITE)
                callable_ = self._point(scope, binding.callable, Phase.CALL_SITE)
                joined.append(ObservedNativeCallable(scope, call, callable_, fact, anchor))
                if fact.carrier is NativeCarrier.UNKNOWN:
                    self._note(call, 'CALLABLE_CARRIER_DETAILS_OPEN',
                        'The actual callable type is recorded; the probe did not identify a native carrier. '
                        'This does not imply native execution or weaken a separately established Python interface.')
                else:
                    self._note(call, 'OBSERVED_NATIVE_IMPLEMENTATION_OPEN',
                        'Captured callable-carrier/ABI facts do not establish execution, a source body, kernel, copy or effects.')
            self.native_callables, self.native_frontiers = tuple(joined), tuple(unbound)
        self.scopes = tuple(self._bindings)
        self.layouts = tuple(self._layouts)
        self.edges = tuple(dict.fromkeys(edge for rows in self._after.values() for edge in rows))
        self.frontiers = tuple(note for rows in self._notes.values() for note in rows)
        # The same session checks these original inputs again at close. A
        # query additionally checks trace membership and stamps before reuse.
        for path, stamp in (*after.items(), *native_stamps.items()):
            previous = session._stamps.setdefault(path, stamp)
            if previous != stamp:
                raise ValueError('observed capture changed within the owning session')

    def _point(self, scope, point, phase):
        result = ObservedPortPoint(point, scope, phase)
        self._ports[scope][result] = None
        return result

    def _note(self, point, kind, detail):
        self._notes[point][ObservedDependencyFrontier(point, kind, detail)] = None

    def _edge(self, source, target, kind, meaning, rule, *, normal=False, conditions=()):
        originals = source.original, target.original
        sources = tuple(dict.fromkeys(point.namespace.graph for point in originals))
        guards = () if kind is K.OPERAND else (DependencyCondition('SCAR_INTERFACE',
            'DIRECT_FUNCTION_ENTRY_SELECTED', subject=originals[0]),)
        if normal:
            guards += (DependencyCondition('SCAR_INTERFACE', 'CALLEE_NORMAL_RETURN_SELECTED'),
                DependencyCondition('SCAR_INTERFACE', 'CALLER_NORMAL_LANDING_DECLARED_NOT_OBSERVED'))
        guards += conditions
        template = DependencyEdge(*originals, kind, meaning,
            (DependencyEvidence(rule, sources, originals),), guards,
            DependencyStrength.MAY if conditions else DependencyStrength.EXACT)
        edge = ObservedDependencyEdge(template, source, target)
        self._after[source][edge] = None
        self._before[target][edge] = None

    def _join(self, scope, item, layouts):
        binding, interface = item.binding, item.interface
        caller = binding.call.namespace
        callee = GraphNamespace.from_source(interface.body)
        point = lambda ns, node, phase: self._point(scope, P(ns, node, None), phase)
        call = point(caller, binding.call.node, Phase.CALL_SITE)
        entry = point(callee, callee.root, Phase.ENTRY_INTERFACE)
        body = self.session.load_body(interface.body)
        for formal in body.interface.parameters:
            point(callee, formal.value, Phase.ENTRY_INTERFACE)
        self._edge(call, entry, K.CALL_TARGET, M.STRUCTURE, 'OBSERVED_DIRECT_FUNCTION_ENTRY_V1')
        for argument in interface.arguments:
            self._edge(point(GraphNamespace.from_source(argument.actual_body), argument.actual_use, Phase.CALL_SITE),
                point(GraphNamespace.from_source(argument.formal_body), argument.formal_value, Phase.ENTRY_INTERFACE),
                K.ARGUMENT, M.REFERENCE, 'OBSERVED_SOURCE_ARGUMENT_INTERFACE_V1')
        for layout in layouts:
            condition = (DependencyCondition('SCAR_CALL_ABI', 'IMPLICIT_POSITIONAL_PREFIX',
                subject=binding.call, index=layout.implicit_prefix) if len(layouts) > 1 else None)
            guards = () if condition is None else (condition,)
            defaults = tuple(point(callee, formal.value, Phase.ENTRY_INTERFACE) for formal in layout.missing)
            implicit = tuple(dict.fromkeys(point(callee, formal.value, Phase.ENTRY_INTERFACE)
                for formal in (*layout.implicit_formals, *(pack.formal for pack in layout.packs if pack.implicit))))
            packed = tuple(point(callee, pack.formal.value, Phase.ENTRY_INTERFACE) for pack in layout.packs)
            self._layouts.append(ObservedCallLayout(scope, layout.implicit_prefix, condition,
                defaults, implicit, packed))
            for argument in layout.arguments:
                if argument not in interface.arguments:
                    self._edge(point(GraphNamespace.from_source(argument.actual_body), argument.actual_use, Phase.CALL_SITE),
                        point(GraphNamespace.from_source(argument.formal_body), argument.formal_value, Phase.ENTRY_INTERFACE),
                        K.ARGUMENT, M.REFERENCE, 'OBSERVED_CONDITIONAL_ARGUMENT_INTERFACE_V1', conditions=guards)
            for pack in layout.packs:
                target = point(callee, pack.formal.value, Phase.ENTRY_INTERFACE)
                for actual in pack.actuals:
                    if actual.use is None:
                        self._note(target, 'OBSERVED_PACK_ACTUAL_USE_OPEN',
                            'An original expanded/ambiguous operand has no unique owned CALL Use; other packing inputs are retained.')
                        continue
                    self._edge(point(caller, actual.use, Phase.CALL_SITE), target, K.ARGUMENT, M.DEPENDENCE,
                        'OBSERVED_ARGUMENT_PACK_DEPENDENCE_NOT_REFERENCE_IDENTITY_V1', conditions=guards)
                self._note(target, 'OBSERVED_ARGUMENT_PACK_STATE_OPEN',
                    'Packing dependencies are retained; aggregate identity, allocation and contents are not sampled.')
            for target in defaults:
                self._note(target, 'OBSERVED_DEFAULT_STATE_SOURCE_OPEN',
                    'Current function default state is required under an admitted layout; a declaration default is not its current value.')
            for target in implicit:
                self._note(target, 'OBSERVED_IMPLICIT_ARGUMENT_SOURCE_OPEN',
                    'This admitted CALL layout requires an implicit parameter; its complete receiver/descriptor source provenance remains unresolved.')
        state = interface.state_entry
        if state is not None:
            self._edge(point(caller, state.caller_use, Phase.CALL_SITE),
                point(callee, state.callee_value, Phase.ENTRY_INTERFACE), K.STATE_INTERFACE,
                M.STATE_INTERFACE, 'OBSERVED_COARSE_WORLD_ENTRY_NOT_LOCATION_IDENTITY_V1')
        else:
            self._note(call, 'OBSERVED_STATE_ENTRY_OPEN', 'No original coarse world entry mapping is available.')
        for frontier in interface.frontiers:
            self._note(call, frontier.kind, frontier.detail)
        chosen = item.selected_return
        if (chosen is None or item.observed_exit is None
                or item.observed_exit.completion is not FrameCompletion.NORMAL):
            self._note(call, 'OBSERVED_RETURN_INTERFACE_OPEN',
                'No unique observed normal return maps to an original source terminal; completion is not guessed.')
            return
        for value_kind in (ValueKind.REFERENCE, ValueKind.STATE):
            matches = []
            for route in interface.completions:
                if route.kind is not ExitKind.NORMAL or route.value_kind is not value_kind:
                    continue
                for terminal in route.terminals:
                    if (terminal.operation != chosen.operation or terminal.block != chosen.block
                            or value_kind is ValueKind.REFERENCE and (terminal.use != chosen.use
                            or terminal.value != chosen.value or terminal.port != chosen.exit_port)):
                        continue
                    matches.append((route, terminal))
            if len(matches) != 1:
                self._note(call, 'OBSERVED_NORMAL_COMPLETION_INTERFACE_OPEN',
                    value_kind.value + ': selected return has no unique original completion payload route.')
                continue
            route, terminal = matches[0]
            source = point(callee, terminal.use, Phase.RETURN_SITE)
            target = point(caller, route.landing_value, Phase.NORMAL_INTERFACE)
            self._edge(source, target, K.STATE_INTERFACE if value_kind is ValueKind.STATE else K.COMPLETION,
                M.STATE_INTERFACE if value_kind is ValueKind.STATE else M.REFERENCE,
                'OBSERVED_SELECTED_RETURN_INTERFACE_V1', normal=True)
            self._note(target, 'CALLER_LANDING_NOT_INDEPENDENTLY_OBSERVED',
                'The callee exit selects an original caller interface; no caller instruction or Tensor value was sampled here.')

    def _native_protocol_plan(self):
        """Derive each explicit source operand afresh, without native entry claims."""
        from scar.analysis.cpython_native_interfaces import NativeProtocolShape, build_native_protocol
        from scar.analysis.observed_call_bindings import _session_body
        from scar.analysis.program_dependency_export import _Tables
        from scar.analysis.static_calls import StaticCallSession
        self.check()
        if self.native_callables is None:
            raise ValueError('native callable capability was not recorded for this original trace')
        table, cache, shapes, calls, routes = _Tables(), {}, {}, [], []
        for item in self.native_callables:
            if item.fact.carrier is NativeCarrier.UNKNOWN:
                continue
            self.session.check()
            binding = self._bindings[item.scope]
            location = self.session._body_paths[binding.call.namespace.graph.artifact.uri]
            caller = _session_body(self.session, *location, cache)
            operation = caller.index.operations[binding.call.node]
            node = caller.context.call_nodes.get(binding.source.atom_id)
            actuals, gaps = StaticCallSession._actuals(self.session, caller, operation, node)
            notes = [(gap.kind, gap.detail) for gap in gaps]
            flags = (item.fact.fields.method_flags if item.fact.carrier is NativeCarrier.METHOD_DEF
                     else item.fact.fields.wrapper_flags)
            shape = None
            if flags.state is not NativeFieldState.OBSERVED:
                notes.append(('NATIVE_PROTOCOL_FLAGS_OPEN',
                    'The original callable carrier has no observed calling-convention flags.'))
            elif node is not None:
                try:
                    shape = NativeProtocolShape(item.fact.carrier.value, flags.value,
                        tuple((actual.kind.value, actual.keyword) for actual in actuals))
                    if shape not in shapes:
                        # Pure construction validates the supported protocol,
                        # without executing the callable or importing its owner.
                        shapes[shape] = len(shapes), build_native_protocol(shape)
                except (TypeError, ValueError) as error:
                    notes.append(('NATIVE_PROTOCOL_SHAPE_OPEN', str(error)))
                    shape = None
            row = {'scope': encode(item.scope), 'native_anchor': encode(item.anchor),
                'callable_reference': item.fact.callable_reference,
                'call': table.point(binding.call), 'callable': table.point(binding.callable),
                'arguments': table.pack(actuals),
                'protocol': None if shape is None else shapes[shape][0],
                'frontiers': [{'kind': kind, 'detail': detail} for kind, detail in notes]}
            calls.append(row)
            routes.append((item, caller, operation, actuals, shape, tuple(notes)))
        basis = {'run_scope': self.run_scope, 'source_model': encode(self.session.manifest_artifact),
            'capture_files': encode(self.capture_files), 'native_metadata': encode(self.native_metadata),
            'calls': calls, **table.tables}
        return basis, tuple(shapes), tuple(value[1] for value in shapes.values()), tuple(routes)

    @staticmethod
    def _protocol_directory(directory, *, fresh=False):
        path = Path(directory).absolute()
        if path.resolve() != path or path.is_symlink():
            raise ValueError('native protocol directory must be canonical')
        if fresh:
            if path.exists() and (not path.is_dir() or any(path.iterdir())):
                raise FileExistsError('native protocol output must be fresh or empty')
            path.mkdir(parents=True, exist_ok=True)
        elif not path.is_dir():
            raise FileNotFoundError('the original native protocol directory is absent')
        return path

    def build_native_protocols(self, fresh_output_dir):
        """Write shared ABI declaration templates, then admit them via replay."""
        from scar.analysis.cpython_native_interfaces import write_native_protocol
        if self.native_protocol_manifest is not None:
            raise ValueError('native protocols are already attached to this observed run')
        basis, shapes, _, _ = self._native_protocol_plan()
        directory = self._protocol_directory(fresh_output_dir, fresh=True)
        protocols = []
        for number, shape in enumerate(shapes):
            self.session.check()
            locator, representation, _ = write_native_protocol(shape,
                directory / ('protocol-' + str(number).zfill(4) + '.json.gz'))
            protocols.append({'shape': encode(shape), 'locator': encode(locator),
                'representation': representation})
        document = {'schema': 'scar.observed-native-protocols', 'schema_version': 1,
            **basis, 'protocols': protocols, 'target_executed': False,
            'native_implementation_entered': False, 'whole_program_complete': False,
            'transformation_authorized': False}
        raw = (json.dumps(document, sort_keys=True, separators=(',', ':'),
            ensure_ascii=True, allow_nan=False) + '\n').encode()
        with (directory / 'manifest.json').open('xb') as stream:
            stream.write(raw)
        return self.attach_native_protocols(directory)

    def attach_native_protocols(self, existing_dir):
        """Replay original inputs and compare fresh expected graphs before wiring."""
        from scar.analysis.cpython_native_interfaces import native_protocol_document
        from scar.analysis.program_dependency_session import _stamp
        if self.native_protocol_manifest is not None:
            raise ValueError('native protocols are already attached to this observed run')
        basis, shapes, graphs, routes = self._native_protocol_plan()
        directory = self._protocol_directory(existing_dir)
        path = directory / 'manifest.json'
        if path.is_symlink() or path.resolve() != path or not path.is_file():
            raise ValueError('native protocol manifest must be an original canonical file')
        before = _stamp(path)
        if before[2] > self.session.budget.max_record_bytes:
            raise OverflowError('native protocol manifest exceeds the original record byte budget')
        with path.open('rb') as stream:
            raw = stream.read(before[2] + 1)
        if len(raw) != before[2] or before != _stamp(path):
            raise ValueError('native protocol manifest changed during admission')
        document = loads(raw)
        flags = {'target_executed': False, 'native_implementation_entered': False,
            'whole_program_complete': False, 'transformation_authorized': False}
        expected_keys = {'schema', 'schema_version', 'protocols', *basis, *flags}
        if (type(document) is not dict or set(document) != expected_keys
                or document['schema'] != 'scar.observed-native-protocols'
                or type(document['schema_version']) is not int or document['schema_version'] != 1
                or any(document[key] is not value for key, value in flags.items())
                or any(document[key] != value for key, value in basis.items())
                or type(document['protocols']) is not list or len(document['protocols']) != len(shapes)):
            raise ValueError('native protocol manifest changed its original source/capture/operand basis')
        declared, protocol_stamps = [], {}
        for number, (row, shape, graph) in enumerate(zip(document['protocols'], shapes, graphs)):
            if (type(row) is not dict or set(row) != {'shape', 'locator', 'representation'}
                    or row['shape'] != encode(shape)):
                raise ValueError('native protocol template changed its freshly derived ABI shape')
            locator = decode(SourceArtifactLocator, row['locator'])
            expected_path = directory / ('protocol-' + str(number).zfill(4) + '.json.gz')
            if locator.artifact.uri != str(expected_path):
                raise ValueError('native protocol template escaped its original manifest shard')
            expected_document = native_protocol_document(shape)
            core = expected_document['graph']
            if row['representation'] != core['schema'] + '/' + str(core['schema_version']):
                raise ValueError('native protocol template changed its original core representation')
            # This existing owner strictly reads receipts and compares the
            # stored core with this freshly generated expected declaration.
            namespace = self.session.register_implementation_graph(locator, row['representation'], graph)
            if self.session.read_artifact(locator) != expected_document:
                raise ValueError('native protocol wrapper differs from its freshly generated shape/ABI/graph declaration')
            protocol_stamps[expected_path] = self.session._stamps[expected_path]
            declared.append(namespace)
        if before != _stamp(path):
            raise ValueError('native protocol manifest changed while templates were admitted')
        artifact = ProviderArtifact(str(path), sha256(raw).hexdigest(), len(raw),
            'scar.observed-native-protocols/1')
        manifest = SourceArtifactLocator(artifact, artifact.sha256, artifact.size_bytes, 'canonical-json')
        self.session.register_evidence_artifact(manifest, document)
        self._protocol_stamps = {path: before, **protocol_stamps}
        # All source/trace/template admissions finish before new observed
        # adjacency is published. Existing static providers are untouched.
        shape_indices = {shape: number for number, shape in enumerate(shapes)}
        for number, route in enumerate(routes):
            item, caller, operation, actuals, shape, notes = route
            for kind, detail in notes:
                self._note(item.call, kind, detail)
            if shape is not None:
                self._join_native_protocol(item, caller, operation, actuals,
                    declared[shape_indices[shape]], replace(manifest, pointer='#/calls/' + str(number)))
        self.native_protocols, self.native_protocol_manifest = tuple(declared), manifest
        self.edges = tuple(dict.fromkeys(edge for rows in self._after.values() for edge in rows))
        self.frontiers = tuple(note for rows in self._notes.values() for note in rows)
        self.check()
        return manifest

    def _protocol_edge(self, source, target, kind, meaning, manifest, *, completion=None):
        binding = self._bindings[source.scope]
        originals = source.original, target.original
        sources = tuple(dict.fromkeys((*(point.namespace.graph for point in originals), manifest)))
        conditions = (DependencyCondition('SCAR_NATIVE_ABI', 'DECLARED_CALL_PROTOCOL', subject=binding.call),)
        if completion is not None:
            conditions += (DependencyCondition('SCAR_NATIVE_ABI',
                'DECLARED_' + completion.value + '_COMPLETION_NOT_OBSERVED', subject=binding.call),)
        template = DependencyEdge(*originals, kind, meaning,
            (DependencyEvidence('CPYTHON_NATIVE_CALL_PROTOCOL_DECLARATION_V1', sources, originals),),
            conditions, DependencyStrength.MAY)
        edge = ObservedDependencyEdge(template, source, target)
        self._after[source][edge] = None
        self._before[target][edge] = None

    def _join_native_protocol(self, item, caller, operation, actuals, namespace, manifest):
        from scar.analysis.static_calls import StaticCallSession
        binding, scope = self._bindings[item.scope], item.scope
        protocol = self.session.load(namespace)
        root = next(region for region in protocol.graph.regions if region.id == protocol.graph.root)
        blocks = {block.id: block for block in root.blocks}
        entry = blocks[root.entry]
        if len(entry.arguments) != len(actuals) + 2:
            raise ValueError('native protocol entry changed its callable/explicit/world signature')
        point = lambda ns, node, phase: self._point(scope, P(ns, node, None), phase)
        connect = lambda source, target, kind, meaning, **kw: self._protocol_edge(
            source, target, kind, meaning, manifest, **kw)
        connect(item.call, point(namespace, root.id, Phase.PROTOCOL_INPUT), K.CALL_TARGET, M.STRUCTURE)
        connect(item.callable, point(namespace, entry.arguments[0], Phase.PROTOCOL_INPUT), K.ARGUMENT, M.REFERENCE)
        for number, actual in enumerate(actuals):
            if actual.use is None:
                self._note(item.call, 'NATIVE_PROTOCOL_ARGUMENT_USE_OPEN',
                    'Explicit operand ' + str(number) + ' has no unique original CALL Use; its declared port remains unconnected.')
                continue
            connect(point(binding.call.namespace, actual.use, Phase.CALL_SITE),
                point(namespace, entry.arguments[number + 1], Phase.PROTOCOL_INPUT), K.ARGUMENT, M.REFERENCE)
        world, issue = StaticCallSession._caller_world(caller)
        states = [] if world is None else [use for use in operation.uses
            if type(caller.index.values[use.value]) is StateVersionValue
            and caller.index.values[use.value].location == world.location
            and use.role is UseRole.STATE_CONTENT and use.id in operation.invoke_arguments]
        if issue is None and len(states) == 1:
            connect(point(binding.call.namespace, states[0].id, Phase.CALL_SITE),
                point(namespace, entry.arguments[-1], Phase.PROTOCOL_INPUT), K.STATE_INTERFACE, M.STATE_INTERFACE)
        else:
            self._note(item.call, 'NATIVE_PROTOCOL_STATE_ENTRY_OPEN',
                issue or 'The original CALL has no unique input in its validated coarse world domain.')
        caller_blocks = {block.id: block for region in caller.graph.regions for block in region.blocks}
        for kind, phase in ((ExitKind.NORMAL, Phase.DECLARED_NORMAL), (ExitKind.RAISE, Phase.DECLARED_RAISE)):
            signatures = [row for row in operation.completions if row.kind is kind]
            exits = [port for port in root.exits if port.kind is kind]
            successors = [edge for edge in operation.terminator.successors if edge.kind is kind]
            if len(signatures) != 1 or len(exits) != 1 or len(successors) != 1:
                self._note(item.call, 'NATIVE_PROTOCOL_COMPLETION_INTERFACE_OPEN',
                    kind.value + ': no unique original caller signature, landing and declared protocol exit.')
                continue
            signature, exit_, successor = signatures[0], exits[0], successors[0]
            if kind is ExitKind.RAISE:
                self._note(item.call, 'NATIVE_PROTOCOL_EXCEPTION_PACKET_ADAPTER_REQUIRED',
                    'RAISE: caller exception type/value/traceback packets are not proven identical to the protocol exception object; reference payloads remain unconnected.')
                caller_states = [i for i, type_ in enumerate(signature.types)
                    if type_.kind is ValueKind.STATE and world is not None and type_.location == world.location]
                protocol_world = protocol.index.values[entry.arguments[-1]]
                protocol_states = [i for i, type_ in enumerate(exit_.types)
                    if type_.kind is ValueKind.STATE and type_.location == protocol_world.location]
                if len(caller_states) != 1 or len(protocol_states) != 1:
                    self._note(item.call, 'NATIVE_PROTOCOL_STATE_COMPLETION_OPEN',
                        'RAISE: no unique independently identified coarse world port on both sides.')
                    continue
                payloads = ((caller_states[0], protocol_states[0]),)
            elif len(signature.types) != len(exit_.types):
                self._note(item.call, 'NATIVE_PROTOCOL_COMPLETION_PAYLOAD_ADAPTER_REQUIRED',
                    kind.value + ': original caller and declared protocol exception/result packet arities differ; no packet is invented.')
                continue
            else:
                payloads = tuple((i, i) for i in range(len(signature.types)))
            for caller_position, protocol_position in payloads:
                left, right = signature.types[caller_position], exit_.types[protocol_position]
                if left.kind is not right.kind or left.kind is ValueKind.DATA and left.data_type != right.data_type:
                    self._note(item.call, 'NATIVE_PROTOCOL_COMPLETION_TYPE_ADAPTER_REQUIRED',
                        kind.value + ': original caller and protocol payload kinds differ.')
                    continue
                if left.kind is ValueKind.STATE and (world is None or left.location != world.location):
                    self._note(item.call, 'NATIVE_PROTOCOL_STATE_COMPLETION_OPEN',
                        kind.value + ': the caller payload is not independently identified as its coarse world domain.')
                    continue
                positions = [i for i, argument in enumerate(successor.arguments)
                    if type(argument) is CompletionResult and argument.index == caller_position]
                terminals = [op for op in protocol.graph.operations if op.terminator is not None
                    and op.terminator.kind is (TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE)
                    and op.terminator.exit == exit_.name]
                if len(positions) != 1 or len(terminals) != 1:
                    self._note(item.call, 'NATIVE_PROTOCOL_COMPLETION_LANDING_OPEN',
                        kind.value + ': no unique original payload landing or declared terminal Use.')
                    continue
                terminal = terminals[0]
                source = point(namespace, terminal.terminator.values[protocol_position], phase)
                target = point(binding.call.namespace, caller_blocks[successor.block].arguments[positions[0]], phase)
                connect(source, target, K.STATE_INTERFACE if left.kind is ValueKind.STATE else K.COMPLETION,
                    M.STATE_INTERFACE if left.kind is ValueKind.STATE else M.REFERENCE, completion=kind)
        self._note(item.call, 'NATIVE_PROTOCOL_IMPLEMENTATION_ENTRY_NOT_OBSERVED',
            'This is the declared CPython call protocol; pre-entry checks may raise. No implementation entry, completion, source or kernel is observed here.')

    def check(self):
        self.session.check()
        self.check_inputs()

    def check_inputs(self):
        from scar.analysis.program_dependency_session import _stamp
        if _inputs(self.directory) != self._stamps:
            raise ValueError('observed capture inputs changed within this read session')
        for path, stamp in self._native_stamps.items():
            if (path.is_symlink() or path.resolve() != path or not path.is_file()
                    or _stamp(path) != stamp):
                raise ValueError('native callable dependency changed within this read session')
        for path, stamp in self._protocol_stamps.items():
            if (path.is_symlink() or path.resolve() != path or not path.is_file()
                    or _stamp(path) != stamp):
                raise ValueError('native protocol declaration changed within this read session')

    def _scope(self, scope):
        self.check()
        if type(scope) is not ObservedCallScope or scope not in self._bindings:
            raise ValueError('observed scope was not admitted from this original capture')
        binding = self._bindings[scope]
        self.session.index(binding.call.namespace)
        item = self._interfaces.get(scope)
        if item is not None:
            self.session.load_body(item.interface.body)
        return binding

    def binding(self, scope):
        return self._scope(scope)

    def ports(self, scope):
        self._scope(scope)
        return tuple(self._ports[scope])

    def native_callables_for(self, scope):
        """None means NOT_RECORDED; an empty tuple means no fact in this scope."""
        self._scope(scope)
        if self.native_callables is None:
            return None
        return tuple(item for item in self.native_callables if item.scope == scope)

    def neighborhood(self, point, *, outgoing=False, kinds=None):
        if type(point) is not ObservedPortPoint:
            raise TypeError('observed query requires an explicit scoped port')
        self._scope(point.scope)
        # Equality of graph identity never lends a different declaration the
        # authority of a previously loaded original namespace.
        self.session.index(point.original.namespace)
        if point not in self._ports[point.scope]:
            return ObservedDependencyNeighborhood(frontiers=(ObservedDependencyFrontier(point,
                'OBSERVED_PORT_NOT_CAPTURED', 'This original node has no captured interface in the selected CALL occurrence.'),),
                enumerated=False)
        if kinds is not None:
            kinds = frozenset(kinds)
            if any(type(kind) is not K for kind in kinds):
                raise TypeError('observed relation filters require typed dependency kinds')
        edges = tuple(edge for edge in (self._after if outgoing else self._before).get(point, ())
                      if kinds is None or edge.kind in kinds)
        return ObservedDependencyNeighborhood(edges, tuple(self._notes.get(point, ())))


def main(argv=None):
    """Offline observed-interface export, never execution or transformation."""
    import argparse
    from collections import Counter
    import gzip
    import json
    import time
    from scar.analysis.observed_dependency_export import export_observed_dependencies
    from scar.analysis.program_dependency_session import ProgramDependencyBudget, ProgramDependencySession
    parser = argparse.ArgumentParser(prog='scar observed-graph')
    parser.add_argument('--model', required=True)
    parser.add_argument('--trace', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--native-protocols', help='replay existing ABI declaration shards instead of writing new ones')
    parser.add_argument('--max-seconds', type=int, default=180)
    parser.add_argument('--max-graphs', type=int, default=128)
    parser.add_argument('--expand-missing', action='store_true',
                        help='add version-verified missing source units and bodies, then open fresh readers')
    parser.add_argument('--max-expand-bodies', type=int, default=32)
    parser.add_argument('--max-source-files', type=int, default=8)
    parser.add_argument('--max-source-bytes', type=int, default=8 * 1024 * 1024)
    args = parser.parse_args(argv)
    out = Path(args.out).absolute()
    if out.resolve() != out or out.is_symlink() or out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise FileExistsError('observed graph output must be a fresh or empty canonical directory')
    if args.expand_missing and args.native_protocols is not None:
        parser.error('--expand-missing rebuilds the source basis; omit --native-protocols to regenerate its declarations')
    started = time.monotonic()
    expansion = None
    if args.expand_missing:
        from dataclasses import replace
        from scar.analysis.observed_body_demands import expand_observed_bodies
        from scar.analysis.static_calls import StaticCallBudget
        expansion = expand_observed_bodies(args.model, args.trace, out / 'expansion',
            replace(StaticCallBudget(), max_seconds=args.max_seconds),
            max_bodies=args.max_expand_bodies, max_source_files=args.max_source_files,
            max_source_bytes=args.max_source_bytes)
    budget = ProgramDependencyBudget(max_seconds=args.max_seconds, max_input_bytes=1024**3,
        max_cached_bytes=256*1024**2, max_graphs=args.max_graphs)
    with ProgramDependencySession(args.model, budget=budget) as session:
        provider = session.attach_observations(args.trace)
        if args.native_protocols is not None:
            provider.attach_native_protocols(args.native_protocols)
        elif provider.native_metadata is not None:
            provider.build_native_protocols(out / 'native-protocols')
        document = export_observed_dependencies(provider)
        layout_counts = Counter(layout.scope for layout in provider.layouts)
        summary = {'schema': 'scar.observed-dependency-summary', 'schema_version': 1,
            'run_scope': provider.run_scope, 'observed_targets': provider.target_count,
            'bound_calls': len(provider.bindings), 'function_interfaces': len(provider.interfaces),
            'scopes': len(provider.scopes), 'edges': dict(Counter(edge.kind.value for edge in provider.edges)),
            'argument_layouts': len(provider.layouts),
            'ambiguous_call_layouts': sum(count > 1 for count in layout_counts.values()),
            'conditional_argument_edges': sum(edge.kind is K.ARGUMENT and any(
                condition.domain == 'SCAR_CALL_ABI' for condition in edge.template.conditions)
                for edge in provider.edges),
            'packing_dependency_edges': sum(edge.kind is K.ARGUMENT and edge.meaning is M.DEPENDENCE
                for edge in provider.edges),
            'native_protocol_templates': None if provider.native_protocols is None else len(provider.native_protocols),
            'declared_native_protocol_edges': dict(Counter(edge.kind.value for edge in provider.edges
                if any(condition.domain == 'SCAR_NATIVE_ABI' and condition.name == 'DECLARED_CALL_PROTOCOL'
                       for condition in edge.template.conditions))),
            'callable_carrier_capture': None if provider.native_metadata is None else {
                'bound': len(provider.native_callables),
                'unbound': len(provider.native_frontiers),
                'carriers': dict(Counter(item.fact.carrier.value for item in
                    (*provider.native_callables, *provider.native_frontiers)))},
            'frontiers': dict(Counter(note.kind for note in provider.frontiers)), 'issues': provider.issues,
            'measurements': session.measurements(), 'target_executed': False,
            'whole_program_complete': False, 'normal_landing_observed': False,
            'transformation_authorized': False}
        if expansion is not None:
            summary['expansion'] = {'report': str(out / 'expansion' / 'result.json'),
                'added_source_count': expansion['source_expansion']['added_source_count'],
                'expanded_body_count': expansion['expanded_body_count'],
                'prior_manifest_sha256': expansion['source_expansion']['prior_manifest_sha256'],
                'published_manifest_sha256': expansion['published_manifest_sha256']}
    raw = json.dumps(document, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
    stored = gzip.compress(raw, mtime=0)
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'observations.json.gz').open('xb') as stream:
        stream.write(stored)
    summary.update(decoded_bytes=len(raw), gzip_bytes=len(stored), analyzer_seconds=time.monotonic()-started)
    with (out / 'summary.json').open('x') as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({key: summary[key] for key in ('bound_calls', 'function_interfaces', 'scopes',
        'edges', 'argument_layouts', 'ambiguous_call_layouts', 'conditional_argument_edges',
        'callable_carrier_capture',
        'gzip_bytes', 'analyzer_seconds', 'target_executed', 'whole_program_complete')}, ensure_ascii=False))
    return 0
