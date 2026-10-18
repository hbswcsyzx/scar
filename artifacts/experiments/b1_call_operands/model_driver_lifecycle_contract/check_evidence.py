"""Verify saved D2.0 design evidence without executing any probe or product."""
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent


def read(name):
    return json.loads((BASE / name).read_text())


def main():
    manifest = read('manifest.json')['files']
    actual = {str(path.relative_to(BASE)) for path in BASE.rglob('*')
              if path.is_file() and path.name != 'manifest.json'}
    assert set(manifest) == actual
    for name, item in manifest.items():
        path = (BASE / name).resolve()
        assert BASE in path.parents and not (BASE / name).is_symlink()
        raw = path.read_bytes()
        assert len(raw) == item['bytes']
        assert hashlib.sha256(raw).hexdigest() == item['sha256']
    receipt = read('receipt.json')
    assert receipt['status'] == 'PASS_DESIGN'
    assert hashlib.sha256((BASE / 'contract.frozen.md').read_bytes()).hexdigest() == receipt['contract_sha256']
    assert receipt['baseline_source_matches_d1_implementation']
    assert all(receipt[key] is False for key in ('d2_product_complete',
        'efp_product_analysis_implemented', 'source_runtime_verified',
        'transformation_authorized', 'full_first_stage_complete', 'lewm_speedup_measured'))
    probe = read('review/owner_flow.lewm.json')
    assert probe['python'].startswith('3.14.7') and len(probe['scenarios']) == 11
    assert probe['bounded_oracle'] == {'concrete_pool_size': 1728,
        'sampled_concrete_groups': 320, 'seed': 20261018, 'sound_transfer_checks': 1920}
    assert (BASE / 'review/owner_flow.py').read_bytes() == (BASE / 'review/owner_flow.lewm.py').read_bytes()
    assert read('review/owner_flow.json')['python'].startswith('3.12.3')
    assert probe['scenarios']['owner_source_cross_swap'] == {'p': False, 'q': True}
    assert probe['scenarios']['unknown_write_regate_repeated_release']['p_twice'] == [True, True]
    assert all((BASE / path).exists() for path in receipt['reviews'].values())
    assert receipt['contract_sha256'] in (BASE / 'review/owner_flow.md').read_text()
    print(json.dumps({'archive_integrity': 'PASS', 'design_status': 'PASS_DESIGN',
        'files': len(manifest), 'lewm_scenarios': 11, 'bounded_checks': 1920,
        'efp_product_analysis_implemented': False}))


if __name__ == '__main__':
    main()
