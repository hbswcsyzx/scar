# ExecutionModel tagged JSON codec — bounded result

## Implemented interface

- `scar.ir.execution.codec.to_dict(model)`, `from_dict(data)`, `dumps(model)`, `loads(text)`.
- Envelope: exact `schema`, `schema_version`, `model`; schema is `scar.execution-model`, version is exact integer `1`.
- Every dataclass is `{"$record": canonical_qualified_type, "fields": {...}}`.
- Every Identifier is `{"$id": canonical_qualified_type, "kind": original_prefix, "value": original_value, "wire": original_wire}`. Program/v2 IDs retain their original classes and namespaces.
- Every Enum is `{"$enum": canonical_qualified_type, "value": original_member_value}`.
- Type vocabulary is closed over ExecutionModel's declared annotations; tags never cause dynamic imports. A union accepts only its declared exact variant, selected by tag rather than a same-shape fallback.
- All declared fields, including default-empty tables and optional fields, are required on wire; missing, unknown and extra fields are rejected. Tuples are JSON arrays and rebuilt as exact tuples.
- IDs, primitive types, enum payloads, local constructor invariants and nested records are rechecked on encoding and decoding. Duplicate JSON keys and non-finite JSON constants are rejected.
- JSON encoding is deterministic (`sort_keys=True`, compact separators, no NaN).

## Actual verification

First and only dedicated pytest run: **40 passed in 0.59s**, exit 0.

```text
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/unit/test_execution_codec.py
```

The exact interpreter/command/cwd/environment and original stdout/exit/source hashes are preserved under `attempt001/`.

Cases include the existing complete resource fixtures (repeated activations, imported/external resources, implicit selection, native descriptor lifetimes and allocation placement), deep rights/ownership/constraints and legacy evidence references, exact program/v2 ID preservation, wrong union variants and tag families, wrong enum/ID namespace, missing/extra fields, local kind-role incompatibility, bool/int confusion, non-JSON tuple input, repeated keys, NaN/Infinity, frozen-record private mutation and an injected Identifier namespace.

## Explicit boundary

This codec verifies record shape and local invariants. It does **not** resolve artifacts, open URIs/files, execute providers, validate canonical graph foreign keys/current state, establish real identity or grant runtime/transformation authority. A dedicated test preserves a local record with a nonexistent visit while graph validation and file opening are patched to fail if called; such a record still needs the independent execution validator.

No full suite, LeWM/GPU execution, environment change or git action occurred. An initial apply_patch hunk was rejected before any mutation or pytest invocation; it was corrected before `attempt001`.

## Frozen source hashes

- `scar/ir/execution/codec.py`: `9fe67ab00091d1477c71baa3259394d8f2062d9c3deb93bdf3c318f9faaf37bd`
- `tests/unit/test_execution_codec.py`: `1f2875ff9f03a3b493149d18c75c78ab6e4576942a51c24723ea8eb8b086736a`
