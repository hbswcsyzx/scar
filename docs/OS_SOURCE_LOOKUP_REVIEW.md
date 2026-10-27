# 自动从已有端口定位OS source：只读审查

2026-10-23。本轮没有改任何生产模块或已发布35端口产物，没有重开FD资源gate。
仅做一次有界positive lookup，验证如何去掉手挑child actor/ordinal。完整模型仍OPEN。

## 1. 小检索的真实结果

实验：`artifacts/experiments/first_stage_os_source_lookup_review_20261023/`。
实际exit0，wall **4.25s**，RSS **123,916KiB**。

从原R2的35个端口自动分成3个source groups；从原coordinates自动得到2个birth需求。
没有向算法输入actor数字、期望ordinal或LeWM名字。两次候选均经public resolver核实
精确source、row SHA、结果child TID及完整flags：

| 自动需求 | 自动从已有端口取的anchor | 查询候选 | 实际结果 |
|---|---|---|---|
| 已有post-exec anchor的actor之birth | raw3309 / obs3308 | obs3309 | 原raw3310，成功vfork |
| 唯一pre-exec端口actor之birth | raw863713 / obs867049 | obs867219 | 原raw863883，成功clone，无CLONE_FILES/CLONE_THREAD |

表中数字是**结果**，不是脚本入参或条件。正命中只涉及2个原JSONL chunk，共
31,998,744decoded bytes，逐chunk双SHA/line/ordinal核验；初始化原R2仍走其公开验证。
没有扫描百万observations或读取target raw。

第三组是creator context，原coordinates没有它自己的birth，保留
`NO_OWN_BIRTH_COORDINATE`；不捏造一个birth。它已有成功exec及target birth因果，
故不妨碍当前另行证明的table context。

**没有证明或声称全局observation source排序、全局唯一性、未命中即不存在。** 此次只有
两个已经严格核实的positive records，不是一次完整source索引构建。

## 2. 自动需求链与准确字段

1. `OSResourceRefinement.read`资格化原35 selected handles和preimages。
2. 每个`HandleBinding.source.artifact`通过原archive的**精确actual URI+rawSHA+bytes+schema**
   找到logical URI；按logical artifact分组，保留首末selected source物理行。
3. 原R1公共artifacts表提供`artifact_index`，只表示该provider的source表索引，不是新ID。
4. 使用原capture profile声明的per-native-TID文件selector，并核同artifact membership的
   `thread`、`process`与`HostThreadInstance`；TID不自动等于TGID。
5. 原`HostThreadInstance.source`给出birth的ProviderFactReference。它必须通过精确归档
   映射匹配原R1 source artifact；从此生成`Need(expected_source, child_thread)`。
6. `ProviderHandle.selector.ordinal`与原handle source行构成稀疏anchors。anchors只影响
   查询位置；最终身份依据是命中后的原record，不是anchor或距离。
7. 原成功exec receipts相对于首个selected行只决定是否需要pre-exec birth。当前自动
   得到1个`PRE_EXEC_BIRTH_REQUIRED`、1个`POST_EXEC_ANCHOR_ALREADY_AVAILABLE`。

新需求不接受`tid=`或`ordinal=`参数。返回的命中使用既有`ProviderRecordSelector`、
原row SHA、真实JSONL locator、原SourceFact和原ThreadInstance，不增加规范IR节点。

## 3. 查询算法与不能做的推断

R1冻结producer `_scan`按文件、物理行追加call，`apply`按这些call追加observation：
`os_resources.py:237/246/251/340/413/446/710`，SHA
`c52f45a62693e3e78875b3a23b7c56e0a4cdb48862436981f8d98941a4900c1b`。
这可作为**版本限定的查询优化线索**，不能仅凭manifest.PUBLISHED授予排序或唯一性。

优先候选为`anchor_ordinal + expected_raw_line - anchor_raw_line`。signal等跳过行会使
候选偏离，所以必须经`base.selector`→`base.resolve`严格核：

- 原artifact index及physical line恰等于Need；不是邻近行、同PID、时间接近或同hash。
- syscall确为birth、result恰等于原child thread.native_tid；完整flags可恢复。
- 原coordinates/归档/R1/R2属于同Run及精确receipt；原source namespace保持不变。

若候选未命中，可在预算内用source-order启发式尝试二分或另一个anchor；每次成功条件
仍是精确正命中。启发式可以漏搜，故用它搜索失败只能输出
`LOOKUP_BUDGET_FRONTIER / HEURISTIC_MISS / SOURCE_ORDER_UNQUALIFIED`，**不能**输出
source不存在、birth不存在、唯一匹配或整个artifact已检查完。

建议helper默认最多8个查询、64MB累计声明chunk decoded bytes，优先复用已有bounded
chunk cache；达到预算即保frontier。全局唯一性若需要独立证明，应有provider生产协议
或一次真正的完整source-index审计，不能在这里由二分命中冒充。

## 4. 最小下一步代码与接口（Proposed，尚未实现）

只新增`scar/trace/os_source_lookup.py`，不改core、R1/R2、coordinates或旧35端口产物。
建议公开入口：

```python
find_os_birth_witnesses(
    base, r2_manifest, *, archive, coordinates, context_events,
    max_queries=8, max_lookup_decoded_bytes=64_000_000,
)
```

它自动生成groups/needs，返回`matches`及`frontiers`；每个match保留既有selector、row、
row SHA、locator、expected source、child ThreadInstance和flags。数据仍是既有provider
记录的限定查询证据，不是第二张资源/状态图。

一个薄的`prepare_fd_context_evidence(..., fresh_out)`可在同模块内消费该查询结果并再次
核所选实际row，机械生成当前FD consumer需要的witness envelope；包括原Run、输入
receipts、target exec/birth anchors、自动得到的childbirth row/coordinate。可兼容既有
envelope wire shape，显式声明`AUTOMATIC_SOURCE_LOOKUP` producer，使用新artifact SHA，
不伪称由旧手工实验生成，也不改写旧artifact。随后普通调用原FD builder即可，不再
要求调用方挑actor或ordinal。

## 5. 必须保留的consumer限制

当前FD consumer v1只有一个`child_birth_r1`槽，不能把多个pre-exec需求任取一个后称
全部完成。自动查询层应完整返回所有需求；超过一个时给明确consumer-capability
frontier，未来再按统一witness集合扩展consumer。

还有一个更窄的API事实：当前consumer无条件读取`child_birth_r1`。若自动发现零个
pre-exec需求，不能伪造一个无关birth满足格式。后续可在旧代码允许修改后添加显式
optional-witness分支，只有全部selected groups已有合法post-exec依据时才允许零个。
本次既有case恰好一个required witness，因此**只新增helper**即可消除人工挑选依赖，
不需要现在改动已冻结consumer或重跑35端口gate。

这一步完成后只代表资源witness查找自动化；源码/值/状态/副作用/生命周期的完整程序
建模仍需各自证据，不能宣布第一阶段或端到端完整自动建模已完成。
