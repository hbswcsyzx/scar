"""Verify owned design evidence without executing probes or product tests."""
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        path = root / name
        if not path.resolve().is_relative_to(root):
            raise ValueError('Archive path escapes')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Hash mismatch: ' + name)
    review = json.loads((root / 'review_checks.json').read_text())
    if (review['c2_0_status'] != 'OPEN' or review['c2_implemented']
            or review['product_source_sha256'] != review['frozen_c1_source_sha256']
            or review['product_source_files'] != 391
            or review['missing_local_links']):
        raise ValueError('Review scope/identity mismatch')
    counts = {}
    for name, expected in [('runtime', 15), ('delegation', 3), ('exception-context', 5),
                           ('delegate-context', 4), ('bytecode', 4)]:
        path = root / 'review' / ('language-' + name + '-probe.json')
        data = json.loads(path.read_text())
        script = path.with_suffix('.py')
        if data['script_sha256'] != hashlib.sha256(script.read_bytes()).hexdigest():
            raise ValueError('Probe/script mismatch: ' + name)
        actual = len(data['codes'] if name == 'bytecode' else data['observations'])
        if actual != expected:
            raise ValueError('Observation count mismatch: ' + name)
        counts[name] = actual
    design = json.loads((root / 'review/availability-probe.json').read_text())
    if (design['status'] != 'PASS' or len(design['cases']) != 5
            or any(not row['passed'] or row['core_issues'] for row in design['cases'])
            or design['script_sha256'] != hashlib.sha256(
                (root / 'review/availability-probe.py').read_bytes()).hexdigest()):
        raise ValueError('Design projection evidence mismatch')
    print(json.dumps({'status': 'PASS', 'scope': 'archived design receipts only',
                      'observation_groups': counts, 'availability_design_checks': 5,
                      'c2_0_status': 'OPEN', 'c2_implemented': False,
                      'archive_files': len(manifest['files'])}))


if __name__ == '__main__':
    main()
