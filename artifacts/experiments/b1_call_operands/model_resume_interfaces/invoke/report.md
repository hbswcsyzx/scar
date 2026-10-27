# C2B body/INVOKE 组合证据

2026-10-18。只新增 `tests/fixtures/program_resumption_invoke_graphs.py` 与
`tests/unit/test_resumption_invoke.py`，不改产品。使用现有 conda `lewm`，
`PYTHONPATH=.`、`PYTHONDONTWRITEBYTECODE=1`。

1. initial：5项失败。新fixture误把既有字段 `graph.locations` 写成
   `graph.state_locations`，全部在构造阶段失败。stdout/stderr/JUnit/exitcode保留，
   不把它算产品拒绝或通过。
2. attempt2：修正后5项通过 / 0.29s。实际body内INVOKE两条completion仅产生
   world+Reference/packet，逐边独立Uses转发current context/caller；终端先Detach。
   旧world、Attach前context及直接CALL/INVOKE ResumableBody的反例被拒绝。
3. attempt3：仅新增2项通过 / 0.35s，另5项未选，不计为重新通过。
   添加实际Initial→Attach→Detach→Suspend前缀；只保存frame+x，world/context
   经ResumeInput重新接入，唯一landing Attach后再执行上述partial-state INVOKE。
   正例通过，旧pre-cut world/context变异被拒绝。

最终fixture SHA256：`5851615b6c1580d585da2a4d6c129698db9b8e605dd62f958b79d3b874269c22`。
最终测试 SHA256：`24fe7f3aa8015648c3feb159d87cf120cc03e09cb0ed7d04a232e7605d7150ab`。
全部7项随后纳入root最终组件门；不以定向子选择替代整体验收。

没有运行full、LeWM、GPU采集或install；手工IR不证明source/runtime/driver对应。
