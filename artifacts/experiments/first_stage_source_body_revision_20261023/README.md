# ONE source-model snapshot revision gate

2026-10-23. **Observed / Verified finite publication gate: actual exit0,
PASS_WITH_OPEN.** This revises SCAR's model of fixed source, not target code or
target execution. No raw trace/current-Run binding ran. All-program modeling is
still OPEN and lifetime/effect frontiers remain authoritative.

`freeze.json` binds four source files: publisher, partition reader, composition
and the narrow SBA header-capability branch. AST/import/API checks passed.
`production-source/` and `implementation.patch` preserve exact frozen bytes.
The legacy `publish_source_programs` entry retains its root-None add-only guard;
new explicit plan/revision APIs independently rederive exact parent/checkpoint/
namespace/digest expectations. No call_demand source change was needed: its
existing typed-body admission helper is reused without a new header parser.

The plan mechanically locates the two already-verified input artifacts by full
source snapshot/context/definition. It selects one ADD_GRAPH218 and one
REVISE_GRAPH65; no new lowering, package/function-name rule or fake CapturedCode
is involved. A deliberately stale expected namespace, with a recomputed plan
digest, is rejected before any output directory or source admission is created.
This validates the independent CAS guard rather than only plan self-consistency.

The resulting partition manifest remains version2 with explicit capabilities
SOURCE_PROGRAM5_ADMISSION_V1 and SOURCE_BODY_REVISION_V1, paired with
publication2. CP2/file2/SourceProgram5/ProgramGraph/composition3 meanings remain
unchanged. Old exact-capability readers reject the new combination. New ordinary
CompositionIndex reading independently verifies lineage, active references and
accounting. The active old65 CP is replaced at its unique interface/structured
position; ADD218 appends. Old artifacts survive only as parent/history evidence,
with one active CP per qualified body.

| Actual snapshot metric | Before | After |
| --- | ---: | ---: |
| Source files / static bodies | 151 /2217 | 151 /2217 |
| Active graph bodies | 842 | 843 |
| Core operations | 66295 | 66513 |
| Core values | 106100 | 106442 |
| Known construction subtotal | 99954 | 99929 |
| Unknown construction-cost bodies | 2 | 3 |
| Active checkpoint positions | 1627 | 1627 |

The new total construction cost stays UNKNOWN/None. New SourceProgram5 wrappers
do not contain original construction-cost measurements, so graph size is not
substituted for cost. The old bad65 graph is read only through exact immutable
receipts and the core codec for ACCOUNTING_ONLY statistics. Its current language/
lifetime legality is not re-established or bypassed. Counter deltas are checked
as parent minus old plus new; old65 ordered Uses180 becomes182, while graph/value/
protocol counts are unchanged. The ADD contributes218 operations/342 values.

Both new active bodies pass normal public typed/source readers with explicit
independent SourceLanguageOptions, exact source AST and the original owned
CodeWitness. Their actual SourceProgram artifact namespaces remain distinct from
their CP2 admission records. Unknown intermediate consumer/lifetime/effects are
not promoted to pure or fully verified. `code_source_origin` remains exactly the
parent's complete dictionary, despite the new active snapshot inventory receipt.

New manifest `result/publication/manifest.json` SHA:
`97342c29aaab8460f45b67a038e3a3cee22d1781393e1f57a4d7b22e58d26505`.
New `result/composition/index.json.gz` SHA:
`3424d0715a86a5a7db28c7a4617440c4307558c8d3cc7e2f8b9f5ddf2d3dd36c`.
Summary SHA: `19569d4914cf5da2c02245bb9d6458b748bcad3ecd484050dc93caa29cc9ef23`.
The old bad graph and all41 historical store files have identical before/after
hashes. CodeWitness compile0/module-load2/complete-descriptor-match4; no target
import/execution, source prepare, source lowering or105-dependency graph scan.

Session93021, Python PID684479, confirmed exit0. `/usr/bin/time -v`: wall153.76s,
user149.37s, system4.10s, peakRSS994884KiB. The gate retained its180s ceiling.
Publication completed at34.3s, changed-file composition ended at94.3s, and final
public-reader checks ended at152.1s. Repeated strict CP2/source-program accounting
reads are a concrete throughput concern inferred from code and stage timings;
no separate profiler hotspot measurement was made. These are offline modeling
costs, not target speedup results. Only two changed files were composed; other
source shards/graph references were inherited, without rebuilding840 old graphs.

Runtime ancestor proof remains a separate next step. The current private proof
factory still requires the immediately preceding composition; no attempt was
made to weaken it or connect100k calls here. The next reviewed change should
verify an exact original source-membership ancestor while keeping compiler-origin
equality, current raw ownership and source-reference checks. Region activations,
body attachments and Use routes must then be freshly derived for this snapshot,
once for the completed batch.
