# P1 joint protocol/occurrence contract evidence

Baseline: `f9a568182e1672541261020bb9f919609179bb05`.
Status: **P1_CONTRACT_FROZEN_IMPLEMENTATION_OPEN**, independent PASS_WITH_SCOPE.
The maintained contract is `docs/M1_PROTOCOL_CONTRACT.md`; the parent plan
retains F01–F24/X25–X28 and P2–P5 implementation gates. This archive records a
design gate, not a new native-protocol/product validation or optimization.

`design/f-static.initial.md` preserves the first F proposal byte for byte. Its
generic relation language, dynamic references in static records, unscoped
definition subject and source-ambiguous Drive result were withdrawn. The
revised report and independent report retain those findings and corrections.
The O report preserves its narrower per-binding identity and conditional host
order corrections. Initial observations and the failed startup-throw witness
belong to the preceding P0 archive and are not rerun here.

The maintained joint contract resolves remaining shorthand in the archived F
report: packet results copy as whole packets, exception Reference results may
feed an explicit pack, NoEntryInputPort excludes DriveResult, and ordinary
yield/closed/admission rejection host routes derive from original ports. The
final independent receipt binds the exact maintained contract bytes; it grants
design approval only, with P2–P5 implementation and the full M2 gate still open.

`port_blueprint.py` ran once using existing IR, creating two driver activations
and one persistent body activation with Start/Resume segments. The saved
program/execution wires and receipt retain 8/5 original inputs, three outputs
per drive, six unresolved Start capture recipes, no existing structural issues,
and unproved source/identity/transform conditions. These are candidate FK rows,
not an implementation or test of the proposed O records/validator. No Python
resumable workload or pytest is launched by this blueprint.

`archive.py check` only reads saved receipts, hashes, Git state and registered
source/fixture fingerprints. It does not rerun the blueprint, old witnesses,
tests, a compiler, profiler, GPU workload or LeWM. Historical P0 document hashes
are checked at their exact frozen Git revision; current maintained documents
have separate hashes. Use the existing environment:

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_protocol_contract/archive.py check
```

Registered603 source files and78 fixtures remain those of the prior frozen L
implementation. Its5,294-case full result is reused with its original commit
attribution. This design gate starts zero new pytest/full/native witness runs.
M0–M2, automatic LeWM recovery and simplification remain unfinished; no new
speedup is claimed. Protected checkouts and environment remain unchanged.
