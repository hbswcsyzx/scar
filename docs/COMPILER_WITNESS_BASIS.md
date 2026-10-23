# Immutable compiler evidence for observed and unobserved functions

2026-10-23. **Observed source/metadata audit; Proposed next implementation.**
No production file, archive or current publication gate was changed. This audit
did not load marshal/source payloads, decode105 dependency graphs, prepare source,
compile code or execute a target.

## Actual denominators and the two distinct gaps

The existing frontend worklist accounts for2217 static bodies. Its original
1377 missing-body rows include12 synchronous functions/10files/12 complete code
descriptors/104 current calls whose module variant is absent from the20-key
archive, and705 FUNCTION definitions/113files with no complete captured-code
source witness and zero current groups/calls. These are different evidence
requirements. The latter are not proved to be synchronous merely because their
DefinitionKind is FUNCTION; compiler flags and entry adapters remain to be
checked. Current dynamic coverage cannot increase merely by compiling them.

The two file cohorts overlap in6files, so their union is117files. Of the113
unobserved-function files,13 already have some source text in the old archive;
2 of the10 missing-observed-variant files do. A source-text row proves neither
the required module variant nor a nested descriptor match. Counts are from
the saved metadata snapshot before the current two-body publication, not from
a new raw scan or a claim that all these bodies can lower successfully.

Inputs read for these counts:

| Artifact | SHA256 | Bytes |
| --- | --- | ---: |
| `artifacts/analysis/source_frontend_worklist_20261023/missing-bodies.jsonl.gz` | `d61e183427e1645014fd7515c8eb534f86ab387ec8fbc0aa45b72a9ea36c4bb7` | 87425 |
| same directory `summary.json` | `70c8f116a6257c4c765e7e6f9f12da8f6c38879f958fbbf6717446060ef0fca1` | 47770 |
| `first_stage_partitioned_operand_routes_20261023/result/code-witnesses/manifest.json` | `56355f7ef10d16d8ab4fb02a84988cf2f0070b75e4cd5fccbf1c86c1ea34170d` | 42283 |

## What the existing code already does

`CodeWitnessStore.resolve` requires an original CapturedCode, fixed snapshot
and recorded matching optimization levels. A fresh explicitly owned writer may
compile the whole module once per complete CompilationCacheKey; it requires a
complete generated descriptor match before publishing the module payload.
The old store can remain read-only. Therefore acquiring the12 observed variants
requires no new compiler or matcher:

```text
fresh CodeWitnessStore(create=True, compile_missing=True, explicit budget)
  → resolve(original CapturedCode, original snapshot,
            original link.optimize_levels, allow_compile=True)
  → close writer / reopen this new archive read-only
```

Requests must come from the original complete CodeSourceLink and definition/
snapshot/context join. Compiler keys retain canonical read path, lexical compile
filename, source fingerprint, profile, future flags, optimization level,
implementation/version, mode and dont_inherit; archive runtime additionally
retains exact build, cache tag, magic and marshal version. Payload SHA and
complete descriptors are independently checked on read. Compilation with
`compile(..., 'exec')` creates code objects but does not import/execute them.

The705 static definitions cannot legitimately enter that API with fabricated
captures. `resolve` requires a target descriptor before compilation;
`SourceCodeEvidence` additionally requires an actual original CodeCapture and
CodeSourceLink in the composition. Its observed-origin proof is deliberately
stronger than merely having compiled the source.

## Minimal archive-basis input, preserving every old receipt

Add one small read-only archive resolver, not a merged writable store:

```text
CompilerWitnessArchives(explicit tuple of (directory, manifest SHA), budgets)
  .store_for(original full store receipt) → original CodeWitnessStore
```

Only explicitly supplied canonical, owned, read-only archives may be selected.
The complete saved receipt, runtime, manifest SHA and store/source/module bounds
must agree. Never open an arbitrary path supplied solely by a report and never
invent an aggregate store receipt or union/rewrite manifests. Acquisition
output is a separate archive. A completed archive is reopened read-only; further
requests create another fresh archive rather than appending to historical data.

Publisher and SBA select the store named by each saved code-evidence dictionary
before reconstructing independent evidence. Old SourceProgram5 continues to
produce the exact old `SourceCodeEvidence.to_dict()` including its original
store receipt, original compiler/inventory locators and complete descriptor.
New bodies may refer to the new archive. This requires no change to old graph
bytes, snapshots, compiler proofs or code constants. A missing or conflicting
receipt is a frontier, not permission to try another archive until one passes.

For an observed code-object request not yet saved in a body, the worklist must
choose an exact archive/compile-key basis explicitly. Overlapping archive keys
must agree in source/runtime/module descriptor and payload receipts or be
reported ambiguous; a saved body's original basis always takes precedence for
that body's replay. This is compiler evidence selection, not dynamic identity.

## Static compiler evidence without a fictional observation

Use the existing source inventory and compiler machinery, with a distinct proof
origin and no CodeCapture, PID, anchor, InvocationKey or Run:

1. Resolve the original qualified definition and source/context through the
   actual CompositionIndex source view. Load only a dispatched file. Reuse an
   existing archived module variant when its full compile context is explicitly
   selected; the unobserved nested function need not have executed for that
   module's static code to exist.
2. For a missing module, add a bounded `compile_source_module(snapshot,
   compile_context)` operation to the fresh owned writer. Refactor the current
   text/key/compile/marshal-publication path rather than duplicate it. Unlike
   observed `resolve`, its output is a module witness and nested descriptor
   index, not a claim to match a nonexistent captured target.
3. A source-only request must state its compile context. Add an explicit
   `SOURCE_MODULE_CONTEXT_V1` compilation profile for this branch; preserve both
   old profiles unchanged. Use supported explicit future flags, chosen optimize
   level, exact filename, dont_inherit=True and exec mode. Source future imports
   are processed by the compiler. A chosen static variant is not inferred runtime
   optimization/future context and is not a model of every possible exec variant.
4. Extract the existing unique compiler-descriptor→inventoried-definition join
   from `_Sources.code` into a pure shared helper. Preserve its exact snapshot,
   compiler-produced complete descriptor, lexical qualification/decorator span
   and unique DefinitionID/SourceReference checks. It consumes the source view's
   real definition records; no new name-based optimization rule or second
   compiler matcher is introduced. A nonunique/missing match remains a frontier.
5. Add a focused `StaticSourceCodeEvidence` alongside the existing observed
   `SourceCodeEvidence`. It loads the exact selected module/constant path,
   rechecks descriptor and snapshot/context/definition, and exposes `code`,
   `descriptor_key`, `require_definition` and immutable `to_dict`. Its receipt is
   explicitly tagged STATIC_COMPILER, with archive/runtime/compile-key/module
   artifact/constant path/full descriptor/original source locators; it has no
   `captured` or runtime-observation claim. SourceLanguageOptions accepts only
   these two concrete verified evidence classes, not an arbitrary duck-typed
   object or success boolean.
6. Replace the two compiler-key uses of `evidence.captured.key` in slice lowering
   and language validation with `evidence.descriptor_key`. The observed class's
   new property returns the unchanged captured key. Existing code_evidence
   dictionary equality remains exact; static evidence has its own explicit
   origin discriminator rather than rewriting the old observed dictionary.

The SourceLanguageOverlay already carries a receipt dictionary rather than a
CodeCapture and does not need a new Operation/Value/State IR. Its structural
reader does not grant proof authority; full validation must construct the
concrete independent evidence matching that exact origin. The publisher must
explicitly accept static evidence by qualified original definition/source and
capability, without demanding a fictional original CodeCapture. Static body
publication may have zero observed admission origins. Keep that zero; do not
manufacture a CallSourceScope origin or current activation. A later real capture
can apply such a body only through an independently verified complete code/source/
entry-profile match, never because a static body now exists.

## Smallest implementation sequence and acceptance

First implement immutable multi-archive selection and acquire a bounded window
of the12 observed missing variants in a fresh archive using the existing writer.
Check old manifest/payload hashes remain exact, each new accepted descriptor is
the original observed descriptor, all attempted requests and budgets are
accounted for, compilation count follows unique dispatched module keys, and
target execution/import stays zero. Then a normal frontend worker may consume
that read-only evidence; graph lowering can still fail for unrelated adapters.

Next add explicit static-module acquisition, the extracted pure source join and
the separate static evidence class/property. One bounded file window should
enumerate all its original static definitions, retaining matched, ambiguous,
unsupported-entry and budget frontiers. Verify source/context/profile/build/
flags, complete nested descriptor and original constant path independently;
replay one old observed SourceProgram5 through its original archive and one new
static body through its new exact basis. Preserve2217 source-body obligations
and the current Run's separately measured dynamic denominator; static code
acquisition alone adds zero invocations or runtime coverage.

Do not set a guessed113-key compile limit or recompile per function. The planner
first derives unique requested module contexts from metadata; compiler/source/
marshal costs are measured per dispatched file and recorded before a larger
window. Missing adapters, generated/non-file origin, source drift, unmodeled
compile context, unknown constants and unsupported interpreter flags remain
explicit demands. No all-file compile, actual acquisition, production edit or
new gate was performed in this design review.
