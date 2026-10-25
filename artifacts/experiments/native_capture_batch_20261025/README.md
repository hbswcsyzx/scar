# Native capture batch implementation: prepared, not run

2026-10-25. This isolated producer and its real runner await root's explicit
confirmation before any original large raw/chunk input or full gate is run.
There is no new full-domain PASS here.

The worktree is `/home/zyf/AAA/scar-worktrees/native-scalar-model`; the requested
base is `0678db92`. No Git command or main-worktree producer write was performed.
The implementation adds `scar/trace/native_capture_batch.py`, extends
`scar/ir/execution/native_port_protocol.py`, and factors pure projection-byte
preparation from `native_protocol.py`'s existing publication wrapper. Its typed
builders and projected bytes retain the same representation. The
original NativeProtocolWindow prefix/16 hard bounds remain intact.

The new entry binds no coordinates internally: the runner first calls the normal
public binder once and supplies that live result. Native acquisition fully checks
each original source once, streams the complete ETO/JSONL inputs into a private
SQLite navigation spool, validates complete parent chains, then reads the four
needed original archive tables once through BundlePartitions chunk receipts.
Spool payloads and locators have process-private authentication seals. This is a
rebuildable navigation index; loading its files cannot restore an owner or IR.
SQLite's page count is capped before table creation at the byte limit divided
by the actual page size, with the returned limit checked. This follows SQLite's
[max_page_count documentation](https://www.sqlite.org/pragma.html#pragma_max_page_count)
and [database-size limit](https://www.sqlite.org/limits.html). An oversized insert
returns SQLITE_FULL rather than growing past that limit. Every index get/put
also checks wall/RSS; actual closed file size remains measured.

Discovery enumerates actual source groups and stores actual BEGIN/OUTPUT/END
locators, operator and outcome. It never creates occurrence rows from range(1,N).
The metadata declaration and actual BEGIN/group counts remain separate. A missing
or duplicated BEGIN or domain discrepancy leaves status OPEN. Original held-slot,
physical metadata and unique-birth absences retain explicit frontiers. Contradictory
qualified source/record/ordinal fields reject instead of changing identity rules.

One complete schema interface catalog and one typed ProgramGraph are frozen
before ordinary ExecutionModel shards are built. Every shard retains the identical
ProgramSnapshot artifact. Static order checks use the full owned signature catalog;
actual Value/Use/transfer/denotation checks use that shard's replayed occurrences.
The source lease is detached from the live checked reader; evidence construction
seals the candidate itself and independently replays its source rows. Generic
representation contracts are unchanged. New per-dispatch inventory and shard
reports declare their own schema/version, without modifying the old bridge report.

The proposed real runner will require actual enumerated accounting to equal the
metadata domain, with qualified+frontier equal to actual attempts. It then forms a
new generic-valid wrong boundary/denotation permutation and its own new snapshot,
and requires a fresh constructor using this run's genuine owned lease to raise
NativePortOrderError. Wrong Run and the legacy no-proof gap are also checked.
Nothing grants scalar contents, ValueVersions, complete world/state effects,
alias completeness, readiness, whole-program coverage or optimization authority.

Small checks already run in conda `lewm`, with isolated PYTHONPATH and bytecode
writes disabled:

* `api-check.json`: seven checks PASS, using small saved typed declarations and
  a newly created tiny synthetic source. One actual activation under four shared
  static definitions passes; a newly sealed generic-valid permutation yields
  two static and two actual ordinal errors. Prefix bounds, sparse actual inventory,
  later serialized parent/root and modified private-spool rejection also pass.
* `parser-check.json`: 56 pure in-memory checks PASS. They cover negative decimal
  and exponent token cuts around the 65,536-byte boundary, split 2/3/4-byte UTF-8,
  and rejection of duplicate keys, truncation, trailing garbage and non-JSON NBSP.
* `integrity-check.json`: six synthetic checks PASS. Only genuinely missing
  original dependencies use the frontier exception; wrong ETO ordinals, duplicate
  positive births, changed spool payloads and deleted indexed rows reject hard.
* `identity-budget-check.json`: nine checks PASS. Wrong nonce, known wrong
  parent/thread and gapped-but-wrong physical identity reject before availability
  classification; zero schema children remain an explicit absence, ambiguity
  rejects, and an actual tiny SQLite insert returns SQLITE_FULL without crossing
  its 16 KiB test cap. Pure projection preparation contains no publication call.

These checks read no original raw sources or archive chunks, and create no
runtime-authoritative owned native evidence. They are not a replayed source gate.

The real runner is `run.sh`/`gate.py`; it uses original capture/partition inputs
from the main worktree only as read-only absolute paths and writes all results
under this experiment's fresh `result/`. Its start marker and exclusive output
files prohibit overwriting an earlier run. `freeze.json` pins the isolated static
import dependency closure, runner files and original small metadata. No original
raw source is read while preparing that freeze.
Actually imported SCAR source files are checked against the frozen set after
imports and at the end. The four unrelated new modeling-scope modules are
explicitly excluded and an unexpected import of them rejects.

Budget settings for root review (planning caps, not measured full-run results):

| Scope | Bound |
|---|---:|
| Whole real gate, including coordinates | 1,800 s alarm |
| Process maximum RSS | 2 GiB |
| Native raw acquisition | 600,000,000 decoded bytes |
| Private SQLite/index | 4,000,000,000 bytes |
| Shared canonical program | 64,000,000 bytes |
| Shared interface / inventory / report | 16 / 256 / 16 MB |
| Per shard | 256 actual ready attempts; 4,096 tensor / 8,192 total flat leaves |
| Per-shard source / execution / values / evidence | 64 / 64 / 64 / 128 MB |
| Per-shard projection receipts | 256 MB |
| Per materialized shard wall | 60 s |
| Published output | 8,000,000,000 bytes |
| Required free working space | 16,000,000,000 bytes |

All shard projection, execution, validation and report payloads are prepared and
checked against individual caps and remaining aggregate output budget before
any of that shard's files is written. Shared program/interface and the two
inventory files also have checks before publication.

Shard construction cuts at sequence/frontier boundaries and leaf limits. A
materialized byte/wall overrun currently stops with an incomplete failure instead
of silently widening limits; this initial runner does not promise every possible
source distribution fits those caps. Input identity/representation contradictions
likewise retain failure evidence for review. Independent path-API stored/decoded
counters, verified BytesIO chunk decodes and private-spool returned bytes have
separate scopes. SQLite returned payload counts are not physical disk I/O.
