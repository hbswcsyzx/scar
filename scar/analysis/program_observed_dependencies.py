"""Observed CALL interfaces over the original shared program graph.

Admission replays raw capture and source interfaces. Saved DTOs are never
accepted as proofs. Ordinary static neighborhoods are not modified.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re

from scar.analysis.observed_call_bindings import derive_observed_interfaces
from scar.ir.program.call_edges import FrameCompletion
from scar.ir.program.dependencies import (DependencyCondition, DependencyEdge,
    DependencyEvidence, DependencyKind as K, DependencyMeaning as M,
    DependencyPoint as P, GraphNamespace)
from scar.ir.program.model import ExitKind, ValueKind
from scar.ir.program.observed_dependencies import (ObservedCallScope, ObservedDependencyEdge,
    ObservedDependencyFrontier, ObservedDependencyNeighborhood, ObservedPortPhase as Phase,
    ObservedPortPoint)


_INPUT = re.compile(r'(?:call-(?:codes|events|meta|operands|operand-meta)|'
    r'python-call-(?:targets|target-meta)|lean-plan|captured-source-meta)'
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


class ObservedDependencyProvider:
    def __init__(self, session, trace):
        directory = Path(getattr(trace, 'directory', trace)).absolute()
        if directory.resolve() != directory or directory.is_symlink():
            raise ValueError('observed capture directory must be canonical')
        before = _inputs(directory)
        bindings, interfaces, evidence, issues = derive_observed_interfaces(session, trace)
        after = _inputs(directory)
        if before != after:
            raise ValueError('observed capture inputs changed during admission')
        self.session, self.directory, self._stamps = session, directory, after
        self.run_scope = evidence.targets.source_sha256
        self.bindings, self.interfaces, self.issues = bindings, interfaces, issues
        self.capture_files = (*evidence.trace.frame_scan.files, *evidence.trace.files)
        self.target_count = len(evidence.targets.targets)
        self._bindings, self._interfaces = {}, {}
        self._before, self._after = defaultdict(dict), defaultdict(dict)
        self._ports, self._notes = {}, defaultdict(dict)
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
            self._join(scope, item)
        self.scopes = tuple(self._bindings)
        self.edges = tuple(dict.fromkeys(edge for rows in self._after.values() for edge in rows))
        self.frontiers = tuple(note for rows in self._notes.values() for note in rows)
        # The same session checks these original inputs again at close. A
        # query additionally checks trace membership and stamps before reuse.
        for path, stamp in after.items():
            previous = session._stamps.setdefault(path, stamp)
            if previous != stamp:
                raise ValueError('observed capture changed within the owning session')

    def _point(self, scope, point, phase):
        result = ObservedPortPoint(point, scope, phase)
        self._ports[scope][result] = None
        return result

    def _note(self, point, kind, detail):
        self._notes[point][ObservedDependencyFrontier(point, kind, detail)] = None

    def _edge(self, source, target, kind, meaning, rule, *, normal=False):
        originals = source.original, target.original
        sources = tuple(dict.fromkeys(point.namespace.graph for point in originals))
        guards = () if kind is K.OPERAND else (DependencyCondition('SCAR_INTERFACE',
            'DIRECT_FUNCTION_ENTRY_SELECTED', subject=originals[0]),)
        if normal:
            guards += (DependencyCondition('SCAR_INTERFACE', 'CALLEE_NORMAL_RETURN_SELECTED'),
                DependencyCondition('SCAR_INTERFACE', 'CALLER_NORMAL_LANDING_DECLARED_NOT_OBSERVED'))
        template = DependencyEdge(*originals, kind, meaning,
            (DependencyEvidence(rule, sources, originals),), guards)
        edge = ObservedDependencyEdge(template, source, target)
        self._after[source][edge] = None
        self._before[target][edge] = None

    def _join(self, scope, item):
        binding, interface = item.binding, item.interface
        caller = binding.call.namespace
        callee = GraphNamespace.from_source(interface.body)
        point = lambda ns, node, phase: self._point(scope, P(ns, node, None), phase)
        call = point(caller, binding.call.node, Phase.CALL_SITE)
        entry = point(callee, callee.root, Phase.ENTRY_INTERFACE)
        self._edge(call, entry, K.CALL_TARGET, M.STRUCTURE, 'OBSERVED_DIRECT_FUNCTION_ENTRY_V1')
        for argument in interface.arguments:
            self._edge(point(GraphNamespace.from_source(argument.actual_body), argument.actual_use, Phase.CALL_SITE),
                point(GraphNamespace.from_source(argument.formal_body), argument.formal_value, Phase.ENTRY_INTERFACE),
                K.ARGUMENT, M.REFERENCE, 'OBSERVED_SOURCE_ARGUMENT_INTERFACE_V1')
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

    def check(self):
        self.session.check()
        self.check_inputs()

    def check_inputs(self):
        if _inputs(self.directory) != self._stamps:
            raise ValueError('observed capture inputs changed within this read session')

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
    parser.add_argument('--max-seconds', type=int, default=180)
    args = parser.parse_args(argv)
    out = Path(args.out).absolute()
    if out.resolve() != out or out.is_symlink() or out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise FileExistsError('observed graph output must be a fresh or empty canonical directory')
    started = time.monotonic()
    budget = ProgramDependencyBudget(max_seconds=args.max_seconds, max_input_bytes=1024**3,
        max_cached_bytes=256*1024**2)
    with ProgramDependencySession(args.model, budget=budget) as session:
        provider = session.attach_observations(args.trace)
        document = export_observed_dependencies(provider)
        summary = {'schema': 'scar.observed-dependency-summary', 'schema_version': 1,
            'run_scope': provider.run_scope, 'observed_targets': provider.target_count,
            'bound_calls': len(provider.bindings), 'function_interfaces': len(provider.interfaces),
            'scopes': len(provider.scopes), 'edges': dict(Counter(edge.kind.value for edge in provider.edges)),
            'frontiers': dict(Counter(note.kind for note in provider.frontiers)), 'issues': provider.issues,
            'measurements': session.measurements(), 'target_executed': False,
            'whole_program_complete': False, 'normal_landing_observed': False,
            'transformation_authorized': False}
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
        'edges', 'gzip_bytes', 'analyzer_seconds', 'target_executed', 'whole_program_complete')}, ensure_ascii=False))
    return 0
