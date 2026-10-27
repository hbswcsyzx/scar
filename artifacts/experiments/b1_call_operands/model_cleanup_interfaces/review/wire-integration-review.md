# C1 codec / model / CLI integration review

## Scope and snapshot

Read-only review of `scar/ir/record_codec.py`, `scar/ir/program/codec.py`,
`scar/ir/program/model.py`, and `scar/cli.py` in worktree
`/tmp/scar-structured-model-280qf4mi`, Git HEAD
`588ca84a709d2f2a79e36b918e473db9a629d58b` (2026-10-16). The working tree had
uncommitted C1 integration changes; the file hashes below identify the reviewed
contents, not the committed HEAD contents.

Reviewed file SHA-256:

| File | SHA-256 |
|---|---|
| `scar/ir/record_codec.py` | `2facc7de22eadf2c095181a6f258ecbb7a529079d5c92b6414bbb0a0968ec6c4` |
| `scar/ir/program/codec.py` | `d9d802cfa0791622f5c610432c03ca883bba16b807c9f18bebd251e81f47b350` |
| `scar/ir/program/model.py` | `daeedfec33d9a2f7bfecca23c44d619c929502f0ddfb0846827d38dc837a4825` |
| `scar/cli.py` | `14f965b55c21522a5b14db6ab95d59ddf4f46337ac9b1aa61112d027fb3c264f` |

## Findings

No concrete correctness blocker was found in the requested wire/model/CLI scope.

`record_codec` discriminator configuration is explicit and local to each
encode/decode call. It requires exact nonempty string pairs, distinct tags, and
no collision with dataclass fields. Encoding looks up `tags.get(type(value))`,
so a registered base class does not tag subclasses. Decoding checks exact
record fields and the discriminator before constructing that variant; the
same tag map is passed recursively through unions, tuples, lists, and mappings.
Without a tag map the existing record representation is unchanged.

The program codec registers only the exact `CleanupRouteTerminator` class with
`("kind", "CLEANUP_ROUTE")`, and uses that registration only when decoding v9.
The C1 route therefore has an explicit v9 discriminator. C0
`PendingDispatchTerminator` keeps its historical `{pending, successors}` form.
`Operation.__post_init__` rejects a subclass of `CleanupRouteTerminator`, and
the generic `Terminator` rejects the dedicated `CLEANUP_ROUTE` kind, preventing
construction of a tagless generic substitute.

The historical schema envelopes are computed by subtracting the fields added
at each schema version. A v1–v8 document with a v9 cleanup field fails the
exact envelope check. The loader also rejects an explicit `kind` value of
`CLEANUP_ROUTE` before decoding under a historical schema, and post-decode
checks reject saved handled-context values or signatures, cleanup tables, and
route instances. V1 retains its preexisting migration rule: it injects empty
`completions` and `invoke_arguments` fields and rejects those fields if they
were present in the v1 input. Version-specific capability checks also prevent
an old version label from carrying later binding/resource/environment/control/
provider/native capabilities.

CLI `check-program` sets `cleanup_structure_validated=true` only after strict
decode and full graph validation. Its cleanup scope says “declared static
interfaces, CFG routes and state flow.” In the exercised v9 result,
`source_recovery`, `transformation_authorized`, `cleanup_unwinding_verified`,
`exception_context_verified`, and `pending_runtime_realization_verified` were
all `false`. The output reports declared counts; it does not claim source
recovery, actual unwinding, exception-state execution, or rewrite authority.

## Reproducible checks

Run from the worktree with the `lewm` environment and `PYTHONPATH=.`:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python - <<'PY'
from pathlib import Path
import json
from scar.ir.program.codec import dumps, loads
for version in range(2, 9):
    raw = Path(f"tests/fixtures/program_graph_v{version}_frozen.json").read_text()
    assert json.loads(dumps(loads(raw))) == json.loads(raw)
print("v2-v8 frozen fixtures: decoded and re-encoded JSON objects equal")
PY
```

Observed: all seven JSON-object comparisons were true, and each fixture's raw
bytes were exactly its canonical compact wire plus one trailing newline. The
raw file SHA therefore differs from the canonical `wire_sha256` recorded by
the v7/v8 proof files. For those two frozen fixtures, the canonical output
SHA-256 matched each proof's `wire_sha256`:

| Version | Canonical output SHA-256 | Proof match |
|---|---|---|
| v7 | `67e5c54e8971952d070975df9268bdb3453da1485c8e48853ff6455b5d6dc35e` | yes |
| v8 | `384f343bccc9afe69e0c992cb64e2f7c9ed8258c3e827b8e0fd8dfd7fb09faa9` | yes |

A typed C1 graph from `cleanup_return_resume_graph()` encoded as schema v9 and
decoded back to the same canonical JSON. Its route carried
`kind: CLEANUP_ROUTE`; a C0 dispatch in the same graph had exactly the two
historical keys `pending` and `successors`. Changing the route tag to
`PENDING_DISPATCH` failed with `ValueError: value does not match union type`.
Removing the tag caused the decoder to try the legacy C0 record shape, after
which full graph validation rejected the malformed C0 pending projection and
landing (`pending_projection_count` / `pending_exit_landing`). This exercises
the complete loader path; it does not rely on JSON shape alone.

The CLI probe used:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m scar.cli check-program /tmp/<temp>/graph.json
```

Observed exit code `0`, status `WELL_FORMED`, one cleanup interface, three
cleanup actions, and three cleanup routes. Authority fields listed above were
all `false`.

## Limits

The v2–v8 fixture check establishes current typed readability and re-encoding
for those checked files; it is not an independent historical implementation
oracle for every schema. No v1 frozen fixture was available in this review.
The v7/v8 files do include proof records whose canonical wire hashes matched.
No source-replay, runtime-unwinding, full-suite, or LeWM execution was run as
part of this wire review.
