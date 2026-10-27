# F6: malformed same-family external graph escapes the validation boundary

This is an independent small-input result, not a suite or workload run. No tracked files were edited.

Use the existing valid `resource_execution_with_allocation()` fixture and its exact `ValueGraph` catalog object. Change only its mutable `allocations` container to `[]`. The external object still has the required graph family, so the family guard accepts it. `validation._Context._external` calls `graph.validate()`, which reaches `mapping_errors(...).items()` and raises AttributeError instead of returning an invalid execution report.

Actual Python3.14.7 result: `AttributeError: 'list' object has no attribute 'items'`; torch was not imported. The three read source files were unchanged during the probe. Script, exact command, hashes and JSON/stdout are retained in `external_shape*` files.

Minimal correction: keep provider/artifact execution forbidden; deliberately convert expected external record/shape validation and canonicalization failures into an `external_graph_invalid` issue. This malformed supplied artifact is not unavailable evidence and must not become a gap. Do not broaden this into swallowing arbitrary provider execution or successful cache reuse after a mismatch.

This follows the existing “foreign references/malformed input must not crash” scope. It does not request any new external graph feature, source lowering or runtime capture. Original F1–F5 reports remain untouched. Final closure can bind the corrected module hashes after root's own regression run; this report makes no post-fix execution claim.
