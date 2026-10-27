# Native declaration → retained Python context

Adds only `scar.analysis.native_declaration_python`. Main, the resource module,
all native declarations and original capture artifacts were not modified.

```python
with NativeDeclarationPythonSession(batch_report, capture_model, coordinates,
                                    budget=NativePythonBudget()) as session:
    result = session.query_view(normal_native_view, source_instances=None)
    # query(fragment_artifact, ...) is the ordinary native-reader wrapper.
```

All arguments are original `ProviderArtifact`s. The constructor reads the
completed ca66/PID1578961 parent inventory and dispatch bridge once, checks its
original dispatch callbacks once, then uses the existing strict streaming
`scan_call_trace` once. Private maps are source fields/locators, not a restored
owner or graph. `query_view` rechecks selected original parent-inventory rows
against normal original EEG records, consecutive `parent/ctrl_deps`, ETO thread
namespace and nearest span. The original dispatch callback's `call_event_index`
was not retained in the bridge, so its source JSONL is verified once to check
that point against the original FrameEntry/FrameExit interval. It never treats
Python ident, ETO thread tokens and native TID as equal namespaces.

The query stops at the nearest span even when its context is absent; it returns
a gap rather than borrowing a more distant caller. Process-root sentinels,
missing ancestors and bounded paths do not become fake dispatch contexts.
Connections reuse `NativeDeclarationOccurrence`, `EvidenceInstanceRef`, original
`FragmentLocator`s, `InvocationRef`, `CodeCapture`, `FrameEntry` and `FrameExit`.
No CallActivation, CodeID, SourceSnapshot or alternate graph is minted.

One actual normal read succeeded (exit 0):

- Original native `…:eto:20819` (`aten::copy_`) → `…:eto:20815` → nearest span
  `…:eto:20814`. Original bridge pointer `#/observations/5708` then names
  InvocationKey `(1578961, 133490304255808, 2080)` and original call-events line
  4154. Entry/exit event indices are 4154/4155. The captured code is
  `pycode-v2:90e9e0625c599944da452422f65dde1924d2629fc926f0ce8307843d971d39e2`,
  original filename `torch/nn/modules/module.py`, qualname `Module.to`.
  These names describe the mechanically selected result, not selection rules.
- Shared source-session construction: 67.323s, 1,258,625,280B artifact
  stored+decoded. It visited all 310,412 parent records, 39,796 span contexts,
  100,438 normal call invocations and 855 captured code descriptors once.
- This query: 0.117s and 19,274,958B additional artifact reads. Session cumulative
  1,277,900,238B / 67.447s. External normal native-view read was independently
  12.518s / 111,004,742B; total worker 80.059s. Limits stayed 2GB session input,
  600s and bounded private maps. No native/EO/Kineto raw import, source lowering,
  target, capture or compile was run. Original dispatch/call JSONL was read
  offline as explicitly reported; this is not a zero-raw-I/O claim.

`connections` is a tuple of `NativePythonContext` with original control-path and
source refs; `gaps` retains unresolved selected rows. `measurements` is session
cumulative; `query_measurements` is the current join delta, excluding constructor
and the caller's external native-reader cost. Default `source_instances=None`
processes every declaration in the supplied fragment, without per-op rescanning
of bridge/call/parent inventories. This is batch-capable, not an all-native
context-coverage result. The full denominators above describe source scans,
not completed per-native joins.

The relationship is **enclosing dispatch retained source context**, never direct
caller, actual/formal Tensor routing, content, state effects or ready. Fixed
historical collector/provider assumptions remain; source filename/line are not
CodeVersion. No captured-source owner/text or compiler witness for this ca66
code was established here. Static code witnesses could be admitted separately
by exact code identity; no 1ddea/runtime858 invocation was reused.

`RESULT.json` binds source SHA, exact original roots and measurements.
`CONNECTION.json` is the 27,864B reference view, SHA
`95cbe8484c4a9d5354832b4240c39564da73092b267fe736fbd6845ea31abb21`.
Only this module and small runner/result/time/report files belong to the commit;
no original source data, private database, large graph or capture was copied.
