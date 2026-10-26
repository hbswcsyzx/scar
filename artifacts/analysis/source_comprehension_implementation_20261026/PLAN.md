# Eager comprehension scope

Baseline main 9d32b8d0; 44 historical unsupported + one resumable remain intact. Four first-frontier eager comprehensions represent 77 historical calls. Generator five/142 is an old capability frontier and is not counted as a missing current implementation.

Add one opt-in comprehension capability and automatic V9 profile. Lower an original synchronous one-clause ListComp/SetComp/DictComp into the current function's real CFG: eager iterable, GET_ITER, empty container allocation, NEXT/exhaustion split, scoped target binding, original filters and element/key/value evaluation, ordered container update, repeat and scope cleanup. SSA uses original comprehension slots under private environment keys, so outer bindings are retained and never overwritten or leaked. No synthetic AST, child CodeType, function/frame creation, or opaque body placeholder.

Start with a Name target, no async/multiple clauses/walrus/nested comprehension, no active Try cleanup. Other shapes retain exact frontiers. Container/iterator/element references and coarse-world normal/raise completions remain explicit; iteration count, identity, values, dispatch and full effects stay unproved. One original candidate is verified through normal worker and independent readonly CodeWitness, using exact retained text.
