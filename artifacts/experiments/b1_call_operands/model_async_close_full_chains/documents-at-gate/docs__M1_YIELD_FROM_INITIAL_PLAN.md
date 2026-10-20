# 下一门 F20：同一父实例的首次委托链

状态：Proposed。先封存F19；下一门G0记录实际起点SHA和冻结范围后才授权源码写入。
依据：[原剩余分母](M1_AFTER_F19_ORIGINAL_SCOPE.md)，不进入F22/F24，不新增优化。

## 一个完整验收单位

同一父P内的表达式求值、GetIterator、首次advance、匹配/提取、父终点与外driver：

```
Create P → Start P → evaluate N/R → GetIterator N/R → atomic NEXT
  item → P的真实DELEGATION Suspend/export
  error → StopIteration matcher
    true → extract N/R → P Return(value) / Raise(new packet)
    false → P Raise(本次advance packet)
→ 外D真实BodyDrive结果、适配器、host、caller和当前全state
```

零cut仍执行真实父BodyDrive；不能将delegate-only helper的NORMAL返回同时冒充
item和最终YieldFrom值。保原未选N/R、提取失败和future resume入口，但实际不执行
的路径不造CallActivation、Suspend或ResumeIngress。

## 六条有区分力的选路

1. expression-error：evaluate ownR→父Raise，GetIterator未执行。
2. getiter-error：本次GetIterator ownR→父Raise，advance未执行。
3. invalid-iterator：GetIterator内部tentative iter ownN→准确检查拒绝ownR→父Raise。
4. exhaustion：首次advance R→matcher True→extract ownN→父Return，零Suspend。
5. advance-error：同次advance R→matcher False→原packet父Raise。
6. item：advance ownN→真实父Suspend/export；不是最终表达式值，不种F。

invalid-iterator不借AwaitIteratorQualification，不从Reference类型或操作label猜
可迭代性。具体native检查适用性独立保条件；core能表达与自动恢复实现分开。

## 复用，先不预设产品缺口

- `program_continuation_graphs.continuation_site_program(kind='delegate', request='next', initial=True)`
  及`with_continuation_connections`：原GetIterator、InitialAdvance、提取和来源声明。
- `_Body`、`driver_program(target='start', body_graph=P)`、`with_publications`：真实
  父frame/context/current-state、BodyDrive与F。既有creator helper的固定fixture
  RegionID不是产品缺字段；新图可复用适当ID或原caller构法，不修改旧fixture。
- `_activation`、`capture_program(body_paths, extra_calls)`：两实例与准确callee调用。
- 原consumer ledger已有`OwnedUse`的Suspend.export消费者；不造HostTerminal(Suspend)。

建议四NEW文件：program/execution `yield_from_initial` fixtures及对应两unit文件。
入口`yield_from_initial_program(case=...)`和
`yield_from_initial_execution(case=..., instances=2)`；metadata先保原records、
端口、paths和parent/driver/caller关系。所有者明确后才写，不能按label补来源。

## 精准反例与自主验收

- advance偷用旧同型iterator；父Return偷用iterator或旧Ref而非extract ownN。
- 失败腿偷用独立且支配合法的旧packet。
- 一实例缺GetIterator关联、extract Use或父终端Use，完整兄弟不能补缺。
- 删inputs/consumers、budget1保原N/R和父Drive输出分母；旧state若被core提前
  拒绝单列，不能当作查询已识别的反例。

不重造已通过的backedge、bound-method、THROW参数等矩阵。优先atomic NEXT；
opaque method lookup导致InitialAdvance来源未证时保正确边界，不增加来源工具箱。

G0先核现有公开查询/固定参考与最小真实缺口；冻结完整六路后，仅新增图和测试；
全作者FROZEN后root串行首红，先修作者图。只有合法新图出现真实公开查询失败才
授权最薄产品接线。通过新组合、必要受影响旧覆盖、独审、报告与普通commit/push
后，才合账F20及本组合对X27的贡献。其余原分母不因此关闭，用户无需逐门审批。
