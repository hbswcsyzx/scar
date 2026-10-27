"""Check actual active reference order, without decoding any source program."""
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.inventory_partitions import InventoryPartitions
from scar.analysis.source_program_publication import _replace_active_refs

HERE = Path(__file__).resolve().parent
EX = HERE.parent


def main():
    gate = EX / 'source_frontend_remainder_publication_20261025'
    inventory = InventoryPartitions(gate / 'result/publication/manifest.json')
    publication = inventory.component('publication')
    plan = json.loads((gate / 'plan.json').read_bytes())['document']
    parent = InventoryPartitions(plan['base_inventory']['path'])
    changed = {(r['file_index'], r['body_index']): {
        'accounting': r['old_accounting'], 'checkpoint': r['checkpoint']}
        for r in publication['changed_bodies']}
    plan_order = [(r['file_index'], r['body_index']) for r in plan['expectations']]
    assert len(changed) == len(plan_order) == 12 and set(changed) == set(plan_order)
    ordered = {key: changed[key] for key in plan_order}
    results = {}
    for component, count in (('interfaces', 'bound_bodies'), ('structured', 'structured_bodies')):
        before, actual = parent.component(component), inventory.component(component)
        old_refs = before['bodies'] if component == 'interfaces' else before
        actual_refs = actual['bodies'] if component == 'interfaces' else actual
        expected = _replace_active_refs(parent, old_refs, ordered, count)
        wrong = _replace_active_refs(parent, old_refs, changed, count)
        assert actual_refs == expected and actual_refs != wrong
        if component == 'interfaces':
            assert {k: v for k, v in before.items() if k != 'bodies'} == {
                k: v for k, v in actual.items() if k != 'bodies'}
        results[component] = {'exact_plan_order': True, 'wrong_shard_order_rejected': True,
                              'parent_count': len(old_refs), 'new_count': len(actual_refs)}
    source = Path(__import__('scar.analysis.source_program_publication', fromlist=['x']).__file__)
    result = {'status': 'REAL_REFERENCE_ORDER_CHECK_PASS', 'components': results,
        'source_sha256': sha256(source.read_bytes()).hexdigest(),
        'source_programs_decoded': 0, 'composition_roots_decoded': 0,
        'publisher_rerun': False, 'original_gate_exit': 1,
        'full_composition_validated': False, 'whole_first_stage_complete': False}
    with (HERE / 'receipt.json').open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write('\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
