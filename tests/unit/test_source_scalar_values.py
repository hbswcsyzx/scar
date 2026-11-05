"""Original static interfaces only; the example program is never executed."""
from collections import defaultdict
from dataclasses import replace

import pytest

from scar.analysis.source_scalar_values import ScalarValueFlow
from scar.ir.literals import PythonLiteral
from scar.ir.program import normal_targets as T, scalar_values as V, source_productions as P
from scar.ir.record_codec import decode, encode
from tests.unit.test_source_construction_connections import source_facts


def test_scalar_fields_keep_candidates_open_and_bound_feedback():
    unit = source_facts('number = 2 + 3\nname = "left" + "right"\n'
                        'x = 0\nx = x + 1\nexception = 1 / 0\n'
                        'unsupported = 2 @ 3\ncomparison = 2 == 3\n')
    gp = lambda point: T.GlobalPort(unit.unit, unit.ports[point])
    flow = ScalarValueFlow()
    for a, b in unit.aliases:
        flow.connect(gp(a), gp(b))
    names = defaultdict(lambda: (set(), set()))
    for item in unit.names:
        names[item.namespace][int(not item.write)].add(item.value)
    for writes, reads in names.values():
        for source in writes:
            for target in reads:
                flow.connect(gp(source), gp(target))
    for constant in unit.constants:
        flow.offer(gp(constant.value), constant.literal)
    sites = []
    for i, operation in enumerate(unit.operations):
        site = T.LanguageOperationSite(operation.action, operation.selector,
            tuple(gp(p) for p in operation.operands), gp(operation.result),
            gp(operation.world), gp(operation.result_world))
        sites.append(site)
        assert flow.register(i, site)
        assert not flow.register(i, site)
    assert flow.drain()
    literals = {d.result.literal.to_python() for d in flow.derivations()}
    assert 5 in literals and 'leftright' in literals
    assert flow.stats['widened_ports'] > 0 and flow.stats['events'] < 10000
    assert all(len(flow.snapshot(gp(i)).literals) <= 4 for i in range(len(unit.ports)))
    assert all(not flow.snapshot(site.result).complete for site in sites)
    assert any(o.status is V.ScalarEvaluationStatus.KNOWN_EXCEPTION and o.exception == 'ZeroDivisionError'
               for o in flow.obligations())
    assert any(o.kind is V.ScalarObligationKind.UNSUPPORTED_OPERATOR for o in flow.obligations())
    for derivation in flow.derivations():
        assert derivation.semantics == 'CONDITIONAL_BUILTIN_CONTENT'
        assert V.ScalarRuntimeRequirement.BUILTIN_RUNTIME_MATCH in derivation.requirements
        assert decode(V.ScalarDerivation, encode(derivation, record_tags=P.PRODUCTION_RECORD_TAGS),
                      record_tags=P.PRODUCTION_RECORD_TAGS) == derivation
    with pytest.raises(ValueError):
        flow.register(0, replace(sites[0], world=sites[0].result_world))

    # Missing input is a removable obligation. Open content does not block a
    # late literal candidate or make its conditional result a complete value.
    late = ScalarValueFlow()
    addition = next(d.site for d in flow.derivations()
                    if d.result.literal.to_python() == 'leftright')
    late.register('late', addition)
    late.open(addition.operands[0], 'another source path remains open')
    assert late.drain()
    assert any(o.kind is V.ScalarObligationKind.INPUT_LITERAL_ABSENT for o in late.obligations())
    late.offer(addition.operands[0], PythonLiteral.from_python('left'))
    late.offer(addition.operands[1], PythonLiteral.from_python('right'))
    assert late.drain()
    snapshot = late.snapshot(addition.result)
    assert snapshot.content_open and not snapshot.complete
    assert tuple(l.to_python() for l in snapshot.literals) == ('leftright',)
    assert not any(o.kind is V.ScalarObligationKind.INPUT_LITERAL_ABSENT for o in late.obligations())
    assert late.derivations()[0].site == addition
