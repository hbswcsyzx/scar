# Existing kwargs bodies: formal ADD publication

This gate admits the three original SourceProgram5 artifacts (92/85/217
operations) listed by candidate04/postflight01. It starts at the current 843
body snapshot and uses the ordinary exact-parent body-revision API for three
ADD_GRAPH entries. The original candidate04 window exited 1; its storage
postflight exited 0. New admission is an independent consumer result and does
not rewrite those producer results.

`prepare.py` reads the public parent/planner and checks one existing graph with
its archived source text. It writes exact inputs, a plan, all SCAR source-byte
receipts and source snapshots, participating runtime receipts, and `freeze.json`.
It performs no publication. `run.py` is reserved for root after review. Its
exclusive start marker permits one actual attempt in this directory.

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
python -B artifacts/experiments/source_call_kwargs_publication_20261025/run.py
```

The actual gate has a 300s wall ceiling, exactly three input graphs, at most
three changed files, 512 operations per body, 64MB decoded per archive record,
512MB composition-index input and 256MB composition decoded-output ceiling.
The previous two-body publication took 152s; 300s is a ceiling, not a prediction.
The APIs bound their records rather than aggregate repeated input I/O. No
global input-byte claim is made. Only saved static source artifacts and witness
files are read; no call/raw/native inventory or runtime binding gate is run.

Before and after the gate, source/runtime/input/entry hashes are checked.
Public admission rechecks source snapshot, namespace, definition, original
compiler-origin, explicit four-capability declaration, structure, original AST,
and complete CodeWitness against the original read-only 20-key archive. Current
LeWM source files are not text authorities. Default reader behavior remains
unchanged when `source_texts` is omitted. No lowering, compile, source prepare,
target execution, backend action or graph replacement occurs.

The resulting CP2 references retain the original artifact URI and bytes.
The new snapshot retains the exact 843 parent and original source-context
namespaces. The 2217 definitions/151 files and every untouched body are
preserved by the standard lineage validator. The fourth selected subject
(JoinedStr, no returned graph) remains unchanged. Unsupported/not-attempted
rows remain visible; successful additions carry unknown construction cost.
Graph operation counts never substitute for construction cost.

Failures save traceback/progress and retain partial immutable output without
retry or overwriting history. A publication/composition may be present even
if later checks fail; it has no passing gate qualification until `result.json`
is present. The new snapshot grants no current-run integration, cross-function
runtime proof, object/content identity, whole-program completeness or readiness.
Original collector implementation provenance assumptions and existing modeling
scope debts remain open.
