# Isolated tuple-key recovery and pending-reference proposal

2026-10-23. **Implemented in isolated proposal sources; not applied to the active
worktree.** The current source/runtime gate continued with its original source
bytes. This directory does not publish a graph, inventory or Run connection.

The three proposed production files are `source_slice_lowering.py`,
`source_language_validation.py`, and NEW `source_tuple_validation.py` beneath
`proposal_sources/scar/analysis/`. `proposal.patch` addresses their ordinary
repository paths. `original_sources/` and `original-producer.json` preserve the
two original files; the final freeze compares the active files to these bytes.

The source adapter retains existing computational overlays when present. An
absent overlay is recovered only from the exact original SG Tuple operator,
output slot and source atom. Its original children are evaluated through the
existing heap-source recovery API, and ordered element Uses retain absent
StaticValue provenance. No package, class, function or variable-name rule is
used. A child lacking a supported source rule remains a frontier.

AST Tuple does not establish allocation: an exact witnessed LOAD_CONST tuple
continues through the existing nonallocating code-constant reference path.
Only one exact BUILD_TUPLE with matching source position and arity permits the
dynamic construction invoke. The independent validator rejects an allocation
invoke whose exact code position instead loads a constant tuple. Source/code
witnesses still do not establish the live CodeType/constant-object instance.

The internal invoke helper now distinguishes normal and exceptional input
consumption. For BUILD_TUPLE, the normal completion transfers the element holds;
the exceptional completion leaves them on the pending stack for the original
FrameExit/unwind. The fixed primary contract is CPython v3.14.7
[BUILD_TUPLE](https://github.com/python/cpython/blob/v3.14.7/Python/bytecodes.c#L1986)
and [success-only tuple steal](https://github.com/python/cpython/blob/v3.14.7/Objects/tupleobject.c#L413).
The downloaded exact primary-source bytes and SHA receipts remain in
`../first_stage_source_frontend_automatic_20261023/primary-source/`.

The focused validator uses the original key consumer, producer, source links,
CFG, held-reference operations and FrameExit Uses. Hold instances include their
original hold operation identity; duplicate ValueIDs are not collapsed into a
set. It checks exact ordered ports and mandatory exceptional element retention.
It independently propagates known pending paths and distinguishes the tuple's
normal continuation from its own failure completion. Unknown intermediate
consumption, nonunique pending joins and bounded-query limits remain explicit
frontiers, rather than certifying normal/outer lifetime. This check neither
certifies actual finalizers/nontermination nor creates allocation/free events.

`ir-check-final.json` records four bounded checks over the original 65-operation
v5 archive. The new validator rejects its existing exceptional element omission.
A deliberately in-memory augmented retention fixture is accepted only for its
local ordered ports/element retention; the existing Slice/INDEX consumption
remains a frontier, and normal/outer pending lifetime remains unverified. Removing
one element and reversing the element order are both rejected. No fixture is
published or source-replayed. The original archive SHA stays unchanged.

The final check exited0 in wall8.24s with peakRSS93468KiB. The first helper
revision/check is preserved in `ir-check-attempt01/`; a subsequent narrow
reporting correction prevents the tuple's own failure cleanup from counting as
verification of its normal path. Final checks are in the distinct final files.
These are IR validation checks, not target execution or a test suite.

No frontend body was re-lowered, no CodeWitness was compiled, no target/GPU was
run, and no automatic window was repeated. Old graph artifacts are not rewritten.
The former two v5 examples had finite structural/source checks and never had a
verified complete lifetime. Enabling this stronger validator will expose the
known old omission when that old graph is read under the new producer. A corrected
body needs a new producer/new immutable artifact and separate formal publication.
The current generic modeling stage remains OPEN.

Before any application, root reviews the patch, original production SHAs and
current runtime-gate terminal state. The next actual frontend gate should select
the SG-only fixed tuple key by source/AST/code evidence, not a name, retain the
same bounded budget and report its next real frontier without promising that the
entire body will succeed. This proposal does not expand worklist capacity or
introduce an optimization backend.
