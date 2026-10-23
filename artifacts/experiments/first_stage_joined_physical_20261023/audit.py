"""Audit the real joined capture and physical tables, without rebuilding IR."""
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.store.bundle_partitions import BundlePartitions

root = Path(__file__).resolve().parent
out = root / 'result'
capture = root.parent / 'first_stage_lewm_physical_20261023'
started = time.perf_counter()

def load(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rb') as stream:
        return json.load(stream)

model = load(out / 'capture-model.json')
coordinates = load(out / 'capture-coordinates.json')
assert model['coordinate_identity_consistent'] is True
assert model['whole_model_established'] is model['transformation_authorized'] is False
assert model['run'] == coordinates['run']
assert model['processes'] == coordinates['processes'] and model['threads'] == coordinates['threads']
outputs_checked = 0
for declaration in model['outputs']:
    path = Path(declaration['path'])
    assert path.is_relative_to(out) and path.is_file() and not path.is_symlink()
    digest, size = sha256(), 0
    with path.open('rb') as stream:
        while data := stream.read(1048576):
            digest.update(data)
            size += len(data)
    assert digest.hexdigest() == declaration['stored_sha256'] and size == declaration['stored_bytes']
    outputs_checked += 1

physical = load(out / 'native' / 'tensor-physical.json.gz')
meta = load(next((capture / 'trace').glob('tensor-physical-meta.*.json')))
assert physical['capture_membership_verified'] is True
assert physical['marker_nodes'] == meta['counts']['marker_nodes']
assert physical['argument_slots'] == meta['counts']['marker_argument_slots']
assert physical['physical_slot_associations'] == meta['counts']['marker_slots_with_epoch_reference']
assert physical['source_allocation_receipts'] == meta['counts']['allocation_nodes']
assert sum(physical['gaps'].values()) + physical['physical_slot_associations'] == physical['argument_slots']
assert all(physical[key] is False for key in ('logical_versions_established',
    'materializations_established', 'state_effects_established', 'resource_readiness_established'))
associations = {row['storage_region']: row for row in physical['associations']}
epochs = {row['allocation']: row for row in physical['epochs']}
assert len(associations) == physical['physical_slot_associations']
assert len(epochs) == physical['allocation_epochs']
slots = {(row['marker_instance'], row['argument_ordinal']) for row in associations.values()}
assert len(slots) == len(associations)

bundle = BundlePartitions(out / 'native' / 'bundle-partitions' / 'manifest.json')
assert bundle.manifest['whole_program_established'] is False
assert bundle.manifest['transformation_authorized'] is False
allocation_ids, epoch_count, region_count = set(), 0, 0
for envelope in bundle.iter_records('values', 'allocations'):
    row = envelope['record']
    identity = row['id']['wire']
    assert identity not in allocation_ids
    allocation_ids.add(identity)
    if identity in epochs:
        epoch = epochs[identity]
        assert (row['device'], row['nbytes']) == (epoch['device'], epoch['nbytes'])
        assert row['metadata']['provider_allocation_id'] == epoch['provider_allocation_id']
        assert row['metadata']['address'] == epoch['address']
        epoch_count += 1
for envelope in bundle.iter_records('values', 'regions'):
    row = envelope['record']
    assert row['allocation']['wire'] in allocation_ids
    association = associations.get(row['id']['wire'])
    if association is not None:
        assert row['allocation']['wire'] == association['allocation']
        assert row['metadata']['marker_instance'] == association['marker_instance']
        assert row['metadata']['argument_ordinal'] == association['argument_ordinal']
        assert row['metadata']['physical_observation'] == association['physical_reference']
        assert row['metadata']['logical_version'] is None
        region_count += 1
assert epoch_count == len(epochs) and region_count == len(associations)
assert bundle.manifest['graphs']['values']['counts']['versions'] == 0
assert bundle.manifest['graphs']['values']['counts']['materializations'] == 0

report = {'schema': 'scar.joined-physical-independent-audit', 'status': 'PASS',
    'run': model['run'], 'output_artifacts_stored_sha_verified': outputs_checked,
    'capture_counts': coordinates['counts'],
    'marker_nodes': physical['marker_nodes'], 'ordered_tensor_slots': physical['argument_slots'],
    'physical_slots_checked': region_count, 'physical_epochs_checked': epoch_count,
    'physical_frontiers': physical['gaps'], 'source_allocation_receipts': physical['source_allocation_receipts'],
    'bundle_totals': bundle.manifest['totals'],
    'physical_value_tables_full_decoded_receipts_verified': True,
    'other_bundle_tables_stored_sha_only': True,
    'whole_bundle_semantics_revalidated_by_this_audit': False,
    'producer_public_validation': bundle.manifest['public_bundle_validation_performed'],
    'no_logical_versions_or_materializations_invented': True,
    'os_coordinate_check': model['os']['coordinate_check'],
    'coverage_obligations': model['coverage_obligations'],
    'elapsed_s': time.perf_counter() - started,
    'target_executed': False, 'whole_model_established': False, 'transformation_authorized': False}
(root / 'audit-result.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
print(json.dumps(report, sort_keys=True), flush=True)
