实际终态：root 持有 session16093 确认 exit0，outer wall 104.4344s；worker 104.2890s，SELF peak RSS 194,844 KiB。导航发布并完成五个样本查询，**整体程序模型仍为 OPEN**。这不是 direct source CALL、跨域 object identity、逻辑内容/状态/ready 或完整 ProgramModel 通过。

准确根：navigation manifest SHA `8cef855ccfe081830a4548aaee80b4226d10aab22d4aa5e102cd1ebe18be8fa6`，47,237 bytes；执行 freeze SHA `00140598568a5c5776ed77b8a2a46f91392de837dd6806fb67921f678390cd24`。原 scope revision `scope_revision:1ae1c9387ba076a51170c9a60e0a0e5c63ef611c8e5fcc3320d6b0f6a3c03e73` 仅指旧 ledger 范围，不把新 native/adapter 输入追记为旧 scope 已绑定，也不关闭旧义务。

原 association gzip 仅 open1 次，完整 EOF/decoded SHA 核 79,592 rows、606,200,788 bytes、`5e5de5fe11f1bc89d7929c49cae2921df9e9fa54ac8c64aaf074be53b3818001`；实际 compressed 15,515,861 bytes、SHA `f32c2a174121b098fe5c50f84d7615e86fe82c8ec6235ed97684ddd20c2411d0`。原 marker-index 的行号/SHA 与 association 对齐。

全部40个原 native inventory data chunk 各 open1 次，逐 chunk 核原 artifact bytes/SHA/行分母，枚举39,796个实际 sequence；沿 final native根保留37,895 complete-reference /1,901 partial-reference分类。它们是原 native 端口分类，不能当成本次跨片 object identity 通过。导航含80 source、40 native、40 lookup index压缩chunks；159,184 transport rows =79,592 source +39,796 native +39,796 lookup。上述是完整 retained metadata 枚举，没有重新扫描 raw/100k invocation/DB 或重跑 native/source producer。

五次公共查询仅是样本；每次1 index、2 data、1 selected original EEG chunk，均在64MB/10s预算内。stored/decoded计费包含重复读取原小metadata、共享native program、选中execution/evidence projection及EEG，不能当物理磁盘I/O或全行语义验证。

| sequence | 选择依据 | 状态 | relationship | index/data/EEG | stored / decoded bytes | 秒 |
| ---: | --- | --- | --- | ---: | ---: | ---: |
| 1 | invocation-only / zero-Tensor | RETAINED_CONTEXT | RETAINED_SOURCE_CONTEXT | 1/2/1 | 21,157,113 / 43,077,757 | 1.720 |
| 2331 | body-linked | RETAINED_CONTEXT | RETAINED_SOURCE_CONTEXT | 1/2/1 | 21,344,495 / 45,346,497 | 1.859 |
| 244 | source-only | RETAINED_CONTEXT | RETAINED_SOURCE_CONTEXT | 1/2/1 | 21,157,113 / 43,077,757 | 1.687 |
| 3182 | native-only既有诊断 | RETAINED_CONTEXT | RETAINED_SOURCE_CONTEXT | 1/2/1 | 22,631,418 / 46,907,339 | 1.788 |
| 4 | source unresolved | CONTEXT_UNRESOLVED | null | 1/2/1 | 21,157,113 / 43,077,757 | 1.706 |

返回字段的连接范围如下。definition/namespace/activation列计两个phase中具有该字段的数量，不表示两个不同的原定义：

| sequence | 原 invocation_id | definition / namespace字段 / activation事实 | 限定native invoke+normal Return |
| ---: | ---: | ---: | --- |
| 1 | 103 | 0/0/0 | yes |
| 2331 | 1726 | 2/2/2 | yes |
| 244 | 1366 | 2/0/0 | yes |
| 3182 | 40811 | 2/0/0 | yes |
| 4 | none | 0/0/0 | yes |

2331保留准确body namespace字段/activation事实引用，244与3182保留source-only定义，1仅有已知invocation；4仍无retained source invocation，relationship严格为null。native invoke/normal Return均回到选中原EEG producer、ordinal、parent/thread与原projection记录。source invocation/body值通过原qualified references和行SHA保留；本查询没有重读原invocation内容、source body graph或刷新live source guard。zero-Tensor/native-only标签来自执行前已有小metadata/本次native门negative，不是本门重新建立内容/对象资格。

所有样本保留 `HISTORICAL_SCAR_COLLECTOR_EXECUTION_SOURCE_UNRECORDED`；actual/formal、return routing、environment、state/control及缺body等具体frontier未消除。当前代码/依赖冻结不能证明原369749 capture执行时的SCAR collector字节。

计费范围：

- builder input stored **116,076,040**、decoded **717,974,537** bytes；120s/decoded1GB/input256MB/output256MB/200k rows上限独立。
- freeze校验 **108,114,808×3 =324,344,424** bytes，launcher precheck和worker前后各一次，另计于builder/query；该计数不含每次freeze.json本身读取或实际imported-source recheck，不能作为全门总I/O。
- 五次query合计stored **107,447,252**、decoded **221,487,107** bytes，包含重复读取。
- manifest报告的output **24,181,690** bytes =160个closed transport chunks **24,179,311** +navigation BUILDING **2,379**；报告计数在写final manifest前冻结，不含final manifest **47,237** bytes。最终navigation文件合计 **24,228,927** bytes。final manifest仍受builder发布前输出预算约束。门级日志、query收据、freeze/源码/runtime快照及本整理文档不在此output计数内。

版本化与clone查询：全部160 compressed chunks已仅按stored bytes/SHA复核，最大219,118 bytes，均≤1,000,000 bytes，可将整个约24MB navigation与小manifest/收据版本化。没有重解压这些chunks。精确核对见 `navigation-stored-check.json`。

该导航**不是自包含模型包**。clone后公共查询仍需准确source/dispatch metadata roots、source/native coordinates、旧scope root、native final report及inventory declaration、shared native ProgramGraph、选中execution/evidence projection、原native bundle manifest和选中的原EEG instance chunks。还须满足原qualified URI布局及当前adapter准确字节/路径；没有隐式URI relocation。原association/invocation/operand raw流不用于query。只有重跑历史gate才需local frozen snapshots，公共reader不运行该gate的freeze checker。

stage清单排除 `frozen-sources/**`（当前Git c955已有源码，保留freeze准确字节收据即可）与全部119个 `frozen-runtime/**`（大二进制local-only），本地原件均保留不删。当前production/runner/freeze仍冻，未重跑producer、queries或codec全图。`terminal-receipt.json`绑定小终态、五样本与成本；`stage-paths.txt/json`列可stage路径及准确SHA。root安排的有限独立review尚未作出，本报告不借用其未来结论。
