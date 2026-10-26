# 前一项 schema2 四源有限只读审查

审查时段：2026-10-25 23:52–23:56 UTC。主树为 `/home/zyf/AAA/scar-worktrees/structured-program-model`；以下文件起止 SHA 一致。没有运行测试、lowering、CLI、目标或 trace，没有修改生产。结论仅 code review：在指定四项不变量内未发现新的确定阻断，不是实档 gate／完整 schema2 语义验收。

|源码|bytes|SHA256|
|---|---:|---|
|`scar/analysis/source_program_publication.py`|66524|`21a99ab721863995e2c2cd7358d4606c9b1796cbd86d5bf66107e2b34807e53b`|
|`scar/analysis/program_composition.py`|108876|`c0addde68217b558fde4c9ecdc1ed5036bc16cd7bcc70eb034db481b0aee3cb9`|
|`scar/analysis/source_invocations.py`|69653|`9f80874b0ec0346801bc5d12ff9d4842562ece8336e18adf4a408844648eeea1`|
|`scar/analysis/source_entry_run.py`|53460|`044c3f396054af2cbd4783b3853e61ba6f095fe1f1b05e05d460de457ea9374f`|

1. **compiler origin／entry.origin2**：schema2的 project entry 复用已有编译 source witness；`SourceCodeEvidence.from_entry` 对 CompositionIndex 仍按原构造路径查 compiler source，dependency 分支使用 entry 自己的 origin，没有拿 origin2 覆盖 project compiler origin1。
2. **ADD／REVISE、parent CAS和旧ABI**：plan从 exact parent、source input、body、project slot和namespace重算；按已有receipt决定ADD/REVISE，REVISE保previous_body CAS。新entry ABI检查不替换旧ABI；publisher在admission后复核plan，reader重建原plan/checkpoint/signature/admission/graph hash。
3. **父namespace／旧查询**：overlay在原composition上建立独立active qualified map，key保完整SourceDefinitionReference，parent_view递归guard；未重写父document或旧typed查询结果。
4. **SourceInv先验后选body**：先核captured descriptor、VERIFIED witness、exact definition/source及新body CORE_LINKED admission，再应用qualified body。已知source/descriptor冲突仍拒绝，不因overlay消失；旧不可用frontier在parent_body_frontiers中保留。

Root先前已发现 inherited body 的routing signature不能从latest document.bodies查，另授权第五源码改为普通reader验证的active item原record；本四源审查不把它当新发现，也不授第五修正或后续实门资格。该审查不证明caller-expression routing、内容、environment、state或ready闭合。
