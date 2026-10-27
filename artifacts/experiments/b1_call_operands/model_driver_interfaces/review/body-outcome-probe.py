"""Design witnesses on valid existing IR, not a BodyDrive implementation."""
import json
from pathlib import Path
import platform
import sys

from scar.ir.program.ids import BlockID
from scar.ir.program.model import TerminatorKind as K
from scar.ir.program.validation import require_valid
from tests.fixtures.program_resumption_graphs import (
    resumption_program, resumption_two_cuts_program, resumption_loop_program,
    resumption_cleanup_invoke_program,
)
from tests.unit.test_cleanup_nontermination import _fully_diverging_cleanup


def cut_outcomes(graph, start):
    """Stop at the first actual handoff; do not cross a temporal successor."""
    blocks = {b.id: b for r in graph.regions for b in r.blocks}
    operations = {o.id: o for o in graph.operations}
    seen, pending, outcomes = set(), [BlockID(start)], set()
    while pending:
        block = pending.pop()
        if block in seen:
            continue
        seen.add(block)
        final = operations[blocks[block].operations[-1]]
        term = final.terminator
        if term.kind in (K.SUSPEND, K.RETURN, K.RAISE):
            outcomes.add(final.id.value)
        else:
            pending.extend(edge.block for edge in term.successors)
    return {'outcomes': sorted(outcomes),
            'ordinary_blocks': sorted(block.value for block in seen)}


def main():
    cases = []
    specifications = (
        ('start_stops_at_first_suspend', resumption_program, 'resume.entry', {'resume.suspend'}),
        ('sent_ingress_has_only_its_return', resumption_program, 'resume.value', {'resume.return'}),
        ('packet_ingress_has_only_its_raise', resumption_program, 'resume.packet', {'resume.raise'}),
        ('two_cuts_start_does_not_skip_to_second', resumption_two_cuts_program,
         'resume.entry', {'resume.suspend'}),
        ('first_resume_stops_at_second_cut', resumption_two_cuts_program,
         'resume.value', {'resume.second.suspend'}),
        ('second_resume_reaches_only_final_return', resumption_two_cuts_program,
         'resume.second', {'resume.second.return'}),
        ('ordinary_branch_cycle_keeps_possible_exit', resumption_loop_program,
         'resume.value', {'resume.return'}),
    )
    for name, factory, start, expected in specifications:
        graph = factory()
        require_valid(graph)
        observed = cut_outcomes(graph, start)
        assert set(observed['outcomes']) == expected, (name, observed, expected)
        cases.append({'case': name, 'status': 'PASS', 'start': start, **observed})
    divergent = _fully_diverging_cleanup()
    require_valid(divergent)
    root = next(r for r in divergent.regions if r.id == divergent.root)
    observed = cut_outcomes(divergent, root.entry.value)
    assert not observed['outcomes'], observed
    assert root.exits, 'The valid C1 fixture has only potential, intercepted exit ports.'
    cases.append({'case': 'divergence_has_no_fabricated_completion', 'status': 'PASS', **observed})
    # Shared-state projection is a signature calculation, not a new runtime fact.
    body_domains = ('world', 'context')
    driver_domains = ('world', 'context', 'driver-private')
    produced = {domain for domain in body_domains}
    forwarded = {domain for domain in driver_domains if domain not in produced}
    assert produced | forwarded == set(driver_domains) and not produced & forwarded
    cases.append({'case': 'extra_driver_domain_must_forward_not_be_a_body_result',
                  'status': 'PASS', 'produced': sorted(produced), 'forwarded': sorted(forwarded),
                  'scope': 'Signature-only design check; no BodyDrive record exists.'})
    result = {'schema': 'scar.driver-design-witness', 'schema_version': 1,
              'python': sys.version, 'implementation': platform.python_implementation(),
              'status': 'PASS', 'cases': cases,
              'scope': 'Existing valid hand-authored IR, derived design projection only. '
                       'No new product, source/runtime, driver or transformation proof.'}
    Path(__file__).with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': 'PASS', 'checks': len(cases)}))


if __name__ == '__main__':
    main()
