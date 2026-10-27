# Native declaration shared read session

Implemented in `scar/analysis/native_declaration_interfaces.py` on base `6ca3c18e04ee94b411d6654f1ed899cea3dad5ca`.

`NativeDeclarationReadSession(catalog, *, budget=None)` loads the receipt-bound catalog, index/source session, coordinates, typed ProgramGraph and PreparedProgramSnapshot, and shared interface bytes once. `read_fragment(artifact)` normally reloads each fragment's execution model, checks every occurrence against the original ordered port shard and original bundle instance/definition/schema, reconstructs expected source-to-core links, runs the ordinary core validator, and rechecks input stamps. Static ABI layouts are rebuilt once per interface signature per session; per-fragment source associations remain checked. `measurements` and each returned view's `measurements` are cumulative for the session (`SESSION_CUMULATIVE`). The legacy `read_native_declaration_fragment` API delegates to the same implementation.

## Actual readback

The runner consumed the first two real fragments from source shard 0 of the completed 230,818-operation publication. The publication itself and the existing native graph were not rebuilt, and the ETO was not rescanned.

- Publication: `structured-program-model/artifacts/experiments/native_declaration_full_20261027/attempt01/manifest.json`, 27,135 bytes, SHA256 `8dba167f8c14df8431b3964b999efa4a11b6f82edd586d5287ecb012f57aae4e`.
- Terminal: exit 0, 12.393 seconds wall time.
- Both fragments: 256 operations each; core validation valid with 0 issues.
- Fragment 1: 687 input refs, 183 conditional output refs.
- Fragment 2: 697 input refs, 183 conditional output refs.
- Cumulative session accounting after fragment 2: 40,612,800 stored bytes + 76,795,256 decoded bytes; 117,408,056 total.
- Receipt-tracked loads: catalog, coordinates, ProgramGraph and shared interfaces once each; native port shard once; two original source chunks once each (evidence instance chunk and semantic definition chunk). Each execution artifact and fragment manifest was read once.
- No output artifacts were produced by the reader.

The machine result preserves the actual tracked input paths, fragment SHAs, counts and cumulative measurements. These two fragments validate the shared-session behavior only; they do not establish full-publication readback.

## Reproduction

```bash
/home/zyf/miniconda3/envs/lewm/bin/python -B artifacts/analysis/native_declaration_read_session_20261027/read_first_fragments.py
```

The runner pins the publication SHA and defaults to the first two fragments. Its bound can be changed through the CLI arguments; it does not launch a producer or perform a raw ETO scan.
