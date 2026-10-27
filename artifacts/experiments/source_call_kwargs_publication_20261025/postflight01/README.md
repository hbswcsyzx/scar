# Minimal postflight, root execution pending

Preserve original `run.py`, freeze `d245641c…`, failure, exit1 and all artifacts.
The original publisher and composer completed; all three public-reader checks
saved PASS before the participant audit found `_compat_pickle.py` missing from
the original runtime freeze. That is the first reported omission, not proof of
a complete participant inventory. Historical execution bytes remain OPEN.

Run `python -B artifacts/experiments/source_call_kwargs_publication_20261025/postflight01/run.py`
in the standard lewm environment after root review. Budget: 45s, 64MB total
stored reads, 4MB decoded metadata, 2MB per metadata record. Only stored SHA of
the 17MB composition is checked; neither the 77MB decoded index nor the three
graphs are decoded. No publisher/composer/binder/lower/target/gate is repeated.

This entry checks saved small headers/receipts, original three PASS records,
the immutable CP2→original graph references, current source bytes against the
original freeze, and root stored SHA. It writes `receipt.json` and `RESULT.md`.
Postflight metadata success does not retroactively qualify the failed original
environment freeze. Static846/runtime843 and first-stage OPEN remain separate.

Future source_texts plumbing can remain two narrow changes: optional
`source_texts=None` on `compose_source_publication`, forwarded only to changed
CP2 `typed_body` checks; and archived text supplied before `SourceBodyAccess`
CP2 structure reading using existing readonly `source_context`. CP1/default
behavior, exact capabilities and original CodeWitness authority stay intact.
This postflight does not modify either production file or produce new roots.
