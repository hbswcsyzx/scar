"""Descending varargs cycles retain may-content without enumerating positions."""
from scar.analysis.normal_targets import _Solver
from scar.ir.program import normal_targets as T, source_productions as P
from scar.ir.program.content_factors import ContentIndexCycle
from scar.ir.record_codec import decode, encode
from tests.unit.test_source_construction_connections import source_facts


def test_tail_cycles_widen_positions_and_preserve_mapping_keys():
    unit = source_facts('''
def self_pack(*same): return same
def left_pack(*left): return left
def right_pack(*right): return right
def named_pack(**named): return named
def rest_pack(**rest): return rest
def observe(self_value, left_value, right_value, mapping_value, namespace_value, finite_value):
    return self_value
''')
    solver = _Solver([unit])
    flow = solver.containers
    functions = {f.parameter_names: f for f in unit.functions}
    self_function = functions['same',]
    left_function = functions['left',]
    right_function = functions['right',]
    same, left, right = (f.formals[1] for f in (self_function, left_function, right_function))
    named = functions['named',].formals[1]
    rest = functions['rest',].formals[1]
    probes = functions['self_value', 'left_value', 'right_value', 'mapping_value', 'namespace_value', 'finite_value'].formals[1:-1]
    self_probe, left_probe, right_probe, mapping_probe, namespace_probe, finite = probes
    start = 1_000_000

    def container(point, kind):
        value = ('container', point, kind)
        solver.add(point, value)
        return value

    # A real varargs formal flows back into its own tail projection.
    same_container = container(same, 'SEQUENCE')
    flow.project_argument(same, same, T.ProjectionKind.POSITIONAL_TAIL, index=1)
    flow.read(same_container, ('int', 0), self_probe)
    before = flow.content_events
    flow.write(same_container, ('int', start), self_function.value)
    assert flow.content_events - before < 16
    assert len(flow.entries[same_container]) <= 3
    assert self_function.value in flow.entries[same_container][('int', start)]
    assert self_function.value in flow.entries[same_container][None]
    assert same_container in flow.open_containers
    assert ('function', self_function.value) in solver.values[self_probe]
    self_cycles = [cycle for cycle in flow.index_cycles.values()
                   if cycle.container == solver.gp(same) and cycle.source == solver.gp(self_function.value)]
    assert len(self_cycles) == 1
    assert (self_cycles[0].start, self_cycles[0].stride) == (start, 1)
    assert self_cycles[0].path == (solver.gp(same), solver.gp(same))

    # Two distinct varargs formals retain both orientations of the closed path.
    left_container = container(left, 'SEQUENCE')
    right_container = container(right, 'SEQUENCE')
    flow.project_argument(right, left, T.ProjectionKind.POSITIONAL_TAIL, index=1)
    flow.project_argument(left, right, T.ProjectionKind.POSITIONAL_TAIL, index=1)
    flow.read(left_container, ('int', 0), left_probe)
    before = flow.content_events
    flow.write(left_container, ('int', start), left_function.value)
    flow.write(right_container, ('int', start), left_function.value)
    flow.read(right_container, ('int', 0), right_probe)
    assert flow.content_events - before < 16
    for value in (left_container, right_container):
        assert len(flow.entries[value]) <= 4
        assert left_function.value in flow.entries[value][None]
        assert value in flow.open_containers
    assert ('function', left_function.value) in solver.values[left_probe]
    assert ('function', left_function.value) in solver.values[right_probe]
    pair_cycles = [cycle for cycle in flow.index_cycles.values()
                   if cycle.source == solver.gp(left_function.value)]
    assert {(cycle.start, cycle.stride, cycle.path) for cycle in pair_cycles} == {
        (start, 2, (solver.gp(left), solver.gp(right), solver.gp(left))),
        (start, 2, (solver.gp(right), solver.gp(left), solver.gp(right))),
    }
    assert (same, T.ProjectionKind.POSITIONAL_TAIL, 1, None, ()) in flow.argument_projections[same]
    assert (right, T.ProjectionKind.POSITIONAL_TAIL, 1, None, ()) in flow.argument_projections[left]
    assert (left, T.ProjectionKind.POSITIONAL_TAIL, 1, None, ()) in flow.argument_projections[right]

    # Two independent writes with decreasing keys do not establish a cycle.
    finite_container = container(finite, 'SEQUENCE')
    cycle_count = len(flow.index_cycles)
    flow.write(finite_container, ('int', start), right_function.value)
    flow.write(finite_container, ('int', 1), right_function.value)
    assert None not in flow.entries[finite_container]
    assert len(flow.index_cycles) == cycle_count

    # Keyword remainder cycles preserve exact string keys and exclusions.
    named_container = container(named, 'MAPPING')
    rest_container = container(rest, 'MAPPING')
    flow.project_argument(rest, named, T.ProjectionKind.KEYWORD_REMAINDER, excluded_names=('drop',))
    flow.project_argument(named, rest, T.ProjectionKind.KEYWORD_REMAINDER, excluded_names=('drop',))
    flow.read(rest_container, ('str', 'keep'), mapping_probe)
    flow.write(named_container, ('str', 'keep'), right_function.value)
    flow.write(named_container, ('str', 'drop'), self_function.value)
    flow.write(named_container, ('int', start), self_function.value)
    assert right_function.value in flow.entries[rest_container][('str', 'keep')]
    assert ('str', 'drop') not in flow.entries[rest_container]
    assert ('int', start) not in flow.entries[rest_container]
    assert ('function', right_function.value) in solver.values[mapping_probe]
    assert None not in flow.entries[named_container] and None not in flow.entries[rest_container]
    assert len(flow.index_cycles) == cycle_count

    namespace = ('namespace_mapping', unit.unit, named)
    flow.access(namespace, ('str', 'kept'), right_function.value, True)
    flow.access(namespace, ('str', 'kept'), namespace_probe, False)
    assert ('function', right_function.value) in solver.values[namespace_probe]
    assert len(flow.index_cycles) == cycle_count
    assert not flow.content_pending and not flow.content_draining and flow.content_current is None
    for cycle in flow.index_cycles.values():
        assert cycle.path[0] == cycle.path[-1]
        assert cycle.abstract_position == 'UNKNOWN_POSITION'
        assert decode(ContentIndexCycle, encode(cycle, record_tags=P.PRODUCTION_RECORD_TAGS),
                      record_tags=P.PRODUCTION_RECORD_TAGS) == cycle
