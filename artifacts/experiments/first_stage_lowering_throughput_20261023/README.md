# Source construction throughput diagnostic

This is one fixed six-body cohort from the real, unchanged LeWM
`stable_worldmodel/policy.py`, selected in source order. It runs no target code,
does not change the full inventory scope, and is not a target performance claim.
Both variants retain the 100,000-operation per-body ceiling and all construction
validation. No broad test suite was run.

## Implemented

- `link_value` indexes complete immutable `ValueSource` records in a set while
  retaining the original ordered output list. Membership remains exact.
- Value IDs index their positions; structured block argument shifts replace the
  existing record without scanning all prior values.
- Removing an entry world port synchronizes the value list, source list, both
  indexes and value lookup. Clearing and checkpoint restoration synchronize the
  indexes too.
- File-wide source atom, definition, computational operation, slot and function
  indexes are read-only and reused only inside one explicitly sealed session.
  Each selected body retains its own function alias map and emitted records.

## Observed

All six before/after canonical graph, metadata, interface, structured overlay and
operation-count hashes are identical. Three bodies lower successfully and three
retain their existing explicit unsupported result.

Instrumented lowering time was 5.9606 seconds before and 6.1337 seconds after.
This small-function cohort does **not** establish a throughput speedup. Its
remaining dominant cost is the full-file control validation performed again for
each successful body: 5.784 seconds of the 5.961-second baseline lowering.
`record_errors` and recursive typed-record validation dominate the CPU profile.

The changes remove identified quadratic scans; proving a practical improvement
on larger construction workloads remains separate. Do not use this diagnostic
to claim a completed whole-program model or LeWM acceleration.

## Explicit sealed construction session

The source graphs and some source records are publicly mutable. Therefore the
ordinary `PreparedSource.lower()` does not reuse either source validation or a
source index from an earlier call. `seal_for_lowering()` instead deep-copies the
three source layers and AST into one private session, verifies the AST against
fixed source text, and fully validates all source layer records, references and
both cross-layer digests before permitting construction. It exposes `lower()`
without exposing mutable source graphs. Its body results contain frozen core
records, IDs, source references, interfaces and metadata. They contain no mutable
source definition, registry, AST or original context reference.

This receipt covers source structure and cross-layer consistency; it does not
grant public source replay, runtime, effect-completeness or transformation
authority. Public validators and ordinary source lowering still validate current
caller-owned inputs. Every newly constructed body/core/interface/typed protocol
and source correspondence is checked, including inside sealed sessions.

The structured/environment inventory path now uses one session per loaded file
context. Switching files releases the session before restoring another context;
this does not keep all 151 files' heavy graphs in memory. Re-entering a file
creates and validates a fresh session. Legacy profiles retain their prior path.

The exact same six-body cohort produced identical canonical hashes again.
Observed instrumented times:

| Part | Ordinary baseline | Sealed session |
| --- | ---: | ---: |
| Prepare source | 10.2084 s | 10.3700 s |
| Seal private source snapshot | — | 8.3633 s |
| Construct six bodies | 5.9606 s | 0.3253 s |
| Seal plus construct, excluding prepare | 5.9606 s | 8.6886 s |

The body-only ratio is 18.32, but the cold six-body sample is **not profitable**
after accounting for sealing. A larger inventory must measure whether enough
successfully constructed bodies share each loaded file context to amortize that
one-time cost. The observed peak RSS was 67,684 KiB after preparation and 71,580
KiB after sealing (+3,896 KiB in this one-file sample); this is not an estimate
for every source file or steady-state heap size.

One small mutation check in `snapshot-boundary.json` confirms that changing the
original context's source-control digest is rejected by ordinary lowering,
public body validation and a new seal; the earlier explicit sealed snapshot
still produces its unchanged body. The initial check attempted to mutate a
definition label and expected an exception, but the existing compiler-layout
check instead returned an explicit unsupported body. That diagnostic mistake is
retained in `snapshot-boundary-attempt1.stderr.txt`; production behavior was not
relaxed to accommodate it. No broad test suite or target/GPU execution was run.

## Evidence and reproduction

`before/` and `after/` retain raw `cProfile` records, readable top calls and
per-body hashes. `comparison.json` records the exact comparison and limitations.
`sealed/`, `sealed-comparison.json` and `sealed.time.txt` retain the final sealed
variant, including its one-time costs. Add `--sealed` to the command below to
reproduce that variant.

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" python \
  artifacts/experiments/first_stage_lowering_throughput_20261023/profile_sources.py \
  --source /home/zyf/AAA/le-wm/stable-worldmodel/stable_worldmodel/policy.py \
  --root /home/zyf/AAA/le-wm --out /path/to/new-result-directory
```
