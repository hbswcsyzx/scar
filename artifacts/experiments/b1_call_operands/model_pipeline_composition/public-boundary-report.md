# Public composition boundary: focused development evidence

Final development attempt: `public_boundary/attempt004`, **16 passed / 1.02s**.
These are activated `lewm` CPU model tests, not a full regression or LeWM/GPU
profiling result. Independently edited modules were allowed during development.

The cases verify strict requests before artifact access, one inventory replay
and one outer detachment for a real content fixture, unchanged index after
returned-ledger mutation, changed semantic catalog rejection, independent
source edges without any ContentRead, partial edge cursors and partially
visited work relations. Shared-budget tests keep complete original inventory.

Earlier failures remain in this archive:

- attempt001: 12 passed / 1 failed. A test tried to clear immutable canonical
  ProgramGraph.operations. Corrected to verify the frozen graph and mutate
  actual mutable result dictionaries.
- attempt002: 13 passed / 1 failed. Removing a fixture ContentRead left original
  contribution-support FK rows. Validator correctly rejected the invalid input;
  the new fixture variant also removes those dependent support declarations.
- attempt003: 15 passed / 1 failed. The lifecycle test used a context registry
  name on ExecutionModel; corrected to its original `outcomes` field.

Independent source review separately identified missing source-only evidence
edges in the first aggregator. This was a source-inferred denominator gap,
not a claimed pre-fix runtime failure. The aggregator now traverses original
supplied EEG edges under the same budget and retains counts/pending/cursor;
attempts003/004 exercise no-read and partial-source paths. The original OPEN
review and later closure are retained. No backend or optimizer rule was added.
