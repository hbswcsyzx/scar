# Attempt02：保序 issue 索引修正后的独立实档验收

状态：**Observed / Verified：实际exit0，原接线及分表归档PASS；完整阶段OPEN。**

attempt1按根授权SIGINT中止，旧目录/日志/20-key archive全部保留。该次真实停止
栈位于`issue()`列表线性成员检查。此次唯一产品改动：维持原issues list及首见顺序，
用immutable `OperandRouteIssue`的set只加速成员测试；原guards/limits/conditions不减。
kind/detail/InvocationKey/CallRecordAnchor均由冻结可hash字段组成，输出语义不变。

本目录独立producer/inputs/patch/progress/time和报告，不覆盖attempt1。不执行目标、
GPU、prepare或source compile；CodeWitnessStore只读复用attempt1的20模块/20source，
逐项保存原manifest/文件SHA/大小，仍核Python build/magic和完整CapturedCode。
新run断言compile_attempts必须为0，源读取来自已有归档；原frame/operand/environment
独立reader与817/100438/312812/16403分母守恒检查不变。

输出延续有界gzip分表及小manifest，不重复写巨型JSON。

## 实际结果及证明边界

Python473042，原工具session30035，已退出0。原817groups/100,438entry/exit、312,812
operand、16,403environment events全部保留；74原CP/namespace，20原模块只读加载，
compile0/current source read0，完整descriptor匹配224次。

- 13,872入口参数occurrences；27argument、27completion条件路由；5,173返回root。
- 3,347entries接10,087env ports；6,694defaults未定。
- 100,523route issues：96,481HANDSHAKE、3,294SOURCE_CORE、748DISPATCH。
- 内容、状态、effects、world等价与完整function environment均未证明，原条件不减。

路由阶段2.04s，整体time5:26.17、peakRSS1,833,420KiB。中止的旧routes已耗764.42s，
不能把这个未完成耗时当成精确A/B基线或LeWM加速。

报告canonical文档99,289,131bytes，SHA256
`0197eff9d76e8673efd1ef639eab5d1b61e70fcb2aab4eae02d0d02fbaea3abd`；
实际按`result/analysis/manifest.json`分表保存，原scalar/header留原收据与namespace。
`summary.json`、原stdout/stderr/time/progress和frozen producer保存实际范围；
没有新target、GPU、prepare或测试套件。

## 正连接与原端口的独立归档核查

`audit-endpoints.py`仅用stdlib，实际exit0、wall2.64s、peakRSS109,656KiB：

- 全141个report chunk的stored/decoded SHA、字节、行数及各表总数核过。
- 74个原CP的完整stored/decoded收据及实际namespace/definition/root核过。
- 全13,872入口参数回到唯一原formal Value及PARAMETER source；3,347environment
  bindings的10,087端口回原environment member/role/cell位置。
- 27argument和27completion回原caller/callee body、Use/Value、formal、return payload
  和world端口；原全部条件保留。样例是实际chunk+line+原CP locator。

本次不是canonical graph语义重验、全report codec replay或raw capture重扫。
首次端口audit在receipt字段选择处退出（混用了另一个收据格式的字段名），原脚本/
stderr/time保留；修正使用本manifest真实`bytes/sha256`与CP的physical字段后才通过。
原模型、归档与连接记录均未改。见`endpoint-audit.json`及两个attempt日志。
