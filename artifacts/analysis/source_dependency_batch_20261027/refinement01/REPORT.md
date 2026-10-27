# Special-control and frontier ceilings

Implemented after `da9ac979`; syntax/compile/import checked only. The prior real retained-model acceptance remains tied to its original source SHAs and is not promoted to these new bytes. No model/capture/target reran.

All four current dedicated terminators (`PendingDispatchTerminator`, `CleanupRouteTerminator`, `SuspendTerminator`, `BodyDriveTerminator`) do expose `.condition`, returning None. That does not describe their pending/cleanup/resume/drive selection semantics. Only exact ordinary `Terminator` now supplies an ordinary guard. Special edges preserve their original operation/successor identity and terminator kind, explicitly marking selection semantics unexpanded; upstream and consumer navigation retain `SPECIAL_CONTROL_NOT_EXPANDED` frontiers instead of treating None as absence of control dependencies.

Each query's frontier count is bounded by `max_nodes + max_routes`, including frontiers appended inside a single CFG fan-in or helper expansion. Further diagnostics are dropped with explicit `FRONTIER_BUDGET` and `truncated=True`; no false complete result is returned. The calculated `max_frontiers` is exposed in the view. Node/route/depth and batch ceilings remain unchanged.
