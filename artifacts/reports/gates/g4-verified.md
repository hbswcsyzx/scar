# G4 independent criteria report

Status: **PASS**

Revision: `a473f1a49161819d92cf8e1750bbcf80309d367a`

Source digest: `5df5530fe18d57c1cd24264802392c58e7341c7e530478b376b7d51e70d3daa4`

| Criterion | Status |
| --- | --- |
| foreign_write_invalidates_prior_version | PASS |
| inference_without_torch_version | PASS |
| allocation_lifetime_not_address | PASS |
| view_geometry_and_byte_overlap | PASS |
| deepcopy_independent_mutable_lineage | PASS |
| actual_cuda_materialization_and_noop | PASS |
| semantic_transform_is_new_value | PASS |
| mutation_escape_scope_and_ledger | PASS |
| bounded_explicit_checkpoint | PASS |
| external_graph_references_without_legacy_merge | PASS |

Scope: Typed descriptor provenance, scoped materialization validity, opt-in tensor observations and bounded at-time checkpoints. This is identity infrastructure, not automatic whole-program proof or optimization.

- Open native/NumPy/ctypes aliases remain NEEDS_VERIFICATION until an observed write or explicit at-time comparison; no universal write interception.
- Bitwise checkpoint equality is scoped to capture/comparison under write exclusion, not future stability or autograd/effect equivalence.
- Cross-copy provenance collectors are opt-in; archived provisional trace identities are preserved rather than retrospectively certified.
- Large/unknown-stride overlap is conservative; exact checkpoint reads have explicit byte, entry and temporary-work bounds.
- Actual CUDA acceptance is required; the gate runner treats skipped hardware tests as failures. No LeWM speedup is measured here.
