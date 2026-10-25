# Local callee-entry routing — actual exit0 with OPEN

Implementation is restricted to source_invocations.py and the two new
source_entry_routing modules. The isolated branch baseline is bc139e19, using
program core28. Current mainA383fd2bd/core29 is not this runtime dependency or
this gate's qualification. No rebase/main/old-native-tree/scope change is made.

The explicit CALLEE_ENTRY_PARAMETER_ROUTING_V1 opt-in produces source-invocations
v5 plus entry-parameters.jsonl.gz. Default None retains the original v4 path and
does not import/read the operand sidecar. All five old unconnected-interface
flags/counts remain; this capability does not prove caller expressions, original
FunctionObject/environment, object identity, logical content or ExecutionModel.

```python
bind_source_invocations(...,
    entry_routing_profile=ENTRY_ROUTING_PROFILE,
    entry_operand_budget=CallOperandBudget(...),
    on_entry_routing=lambda live_session: ...)
```

The new path uses one normal read_call_operands invocation, including its one
internal complete frame scan. Both reader budgets are explicit; this gate sets
frame536684B +operand1463316B =total2MB ceiling. They are independent of historical
seed-metadata verification and ordinary coordinate member SHA/parse phases.
Previously observed actual frame+operand549969B is a candidate, not a preclaimed
new result. Source/body readers keep their existing independent budgets.

Each original FrameEntry/NamedReference vector remains live until full raw,
metadata,source and coordinate checks finish. The ordinary qualified-body reader
supplies original signature/interface/body/namespace. Static layout is checked
once per body; names map through source parameter slots to original FormalPort
values, including the validated BlockArgument and SourceRole.PARAMETER link.
Implicit environment prefix/world are excluded from explicit parameter binding.
The CPython code order differs from signature order for keyword-only/variadic
arguments; the implementation does not blindly zip them.

Existing ReferenceOccurrence(PARAMETER,core_value) and exact original SourceFact /
EvidencePoint carry the local mapping. A parameter fact extends the original
one-based #/lines/N locator with /parameters/i for the original zero-based vector
element; no new provider artifact/schema is created. Weak/snapshot strings are
occurrence carriers under the original issuer protocol, not object counts or
contents. Source/capture assumptions, including absent historical collector
UUID/execution-source witnesses, remain. Saved rows cannot restore the live
session. check_rows independently checks complete original inventory, source,
invocation, namespace, reference and slot; it does not use a caller-valid flag
or reject changed candidates merely through a scope/hash seal.

Pure syntax/fields/code-layout checks passed without Torch, raw/body reads or
owned producer execution. The actual Root-only command is:

```sh
bash /home/zyf/AAA/scar-worktrees/frame-entry-routing/artifacts/experiments/callee_entry_routing_20261025/attempt01/run.sh
```

That fresh CPU/offline gate uses the genuine public coordinate binder and
ordinary existing publication/body/source reader over the original URIs. It
does not import old artifact runners, relower,publish,capture or run a target.
The actual qualification count is computed;520 is only the prior candidate.
One real same-entry port/source exchange must be independently rejected. Missing
a suitable entry is BLOCKED. Limits:2MB combined call/operand reader,64MB record,
128MB selected source/provider,32MB compiler archives,64MB coordinate accounting,
128MB output and180s outer. Runtime source SHA checks are separate. The gate
records actual imports from this isolated tree and all old271/9 denominators.

Root session93681 confirmed actual exit0/38.890410046s. Actual271 entries contain
566 parameter occurrences;260 entries/520 formal ports qualified locally and
11 entries remain body-unavailable frontiers. REPORT.md records the exact scope.
Three sources/runner/freeze remain fixed at their actual bytes.
