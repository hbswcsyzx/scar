# 源码图保留与实际调用的连接

日期：2026-10-20。本项属于第一阶段；完整程序建模验收仍 OPEN。
实施和真实运行结果在本文后续记录，设计不能充当已恢复证据。

## 实际缺口与设计决定

`prepare_source` 已从同一份文本生成 SemanticGraph、SourceSemanticsGraph 和
SourceControlFlowGraph。`ProgramInventory` 保留了 source snapshot 和三图的
SourceContextDigest，但 private context store 在分析结束后删除，只剩摘要。
typed body 不支持某个构造时，这些已有表达式/控制关系也无法从库存离线查询。

因此保留**原有三图**，不创建新的 producer、heap、CFG 或 call report：

| 图 | 原有事实 | 不能升级为 |
| --- | --- | --- |
| SemanticGraph | 源码实体、作用域、版本化 span、OperationDefinitionID | 动态函数对象、实际 target、纯函数合同 |
| SourceSemanticsGraph | ordered operand/result、StaticValue.producer、局部绑定和语法边界 | 跨迭代内容版本、精确可变对象 alias、实际 value occurrence |
| SourceControlFlowGraph | suite/node/edge、分支/循环/失败与 gap；节点引用同 operation ID | 已执行路径、完整 exception 语义或可行性证明 |

这三张来源图是现有模型的观察层，不替代 canonical ProgramGraph，也不为一次
实际执行制造静态 Region/RETURN。静态 ValueID 和动态 ObjectID/ValueVersion 继续
分开；“某表达式产生输入”不同于“每次调用的输入数据版本不变”。

## 机械恢复流程

入口设计为 `source-layers --inventory ORIGINAL.json.gz --out FRESH_DIR`：

1. 有界读取原库存，保留原字节和解压字节身份，核对 header 与全部 file 分母。
2. 严格解码每条 snapshot/context，拒绝重复 source path 和非法 namespace/digest。
   不调用完整 `ProgramInventory.from_dict()`，不重跑 calls/全部 typed body。
3. 对每个文件按原 namespace_root 执行一次既有 prepare_source，核对源码 snapshot
   和三份原 digest。匹配后才把原三图以安全 JSON.gz 存一次，不公开私有 pickle。
4. 每个失败/缺少 context/预算不足的文件保留显式行和理由，不从分母删除。
   archive 的 complete 仅表示所有声明的 source context 留存成功。
5. reader 有界验证 artifact/hash/严格结构和三图交叉引用，返回原图，直接使用
   原有 operand/producer 与 query_reachability/query_dominance 等 API。
   普通读回不重新执行目标，也不重建整个库存。

原 inventory 的 scope、body status、coverage 和 reader1–6不变。本项不验证原
库存全部 declarations；只证明重新生成的 source context 与其指向的版本相符。
哈希不是签名；若原库存和归档都被改写，单独匹配哈希不提供独立可信证明。

后续可在 `_Inventory.snapshot()` 已持有 PreparedSource 时截取同一文档，避免
重建源码；本次先对既有完整 LeWM 库存恢复，不为持久化重构所有调度入口。

## 如何接原有调用关系

没有函数名特判，查询链为：

```text
verified CallSiteLink.call
  → FileInventory.calls[operation].semantic_operation
  → SourceSemanticsGraph.operations[id]
  → operands(role,index).value → StaticValue.producer
  → SourceControlFlowGraph.nodes[*].operations / suite / edges
```

semantic_operation 为 None 的 fallback 不能提升成计算语义；同 operation 可能
关联多个控制节点，必须保留全部。block 字符串不是 CFG NodeID。动态 actual/
formal、visit、状态和 slot 仍需原 call/operand/canonical receipts，不能用同一个
weak token 或静态 producer 自动补齐。

## 验收条件与范围

- 原库存、目标源码字节未改；输入、输出相互隔离，已有目录不覆盖。
- 全部文件都有留存/明确失败行；三图与原 digest 一致；预算不会删分母。
- 实际读回能追踪 ordered input→producer，并找到 CFG context；不是只输出计数。
- 通用 testcase 含 import、loop 与模块级异常哨兵，验证分析未执行目标。
- 对原 LeWM 151 文件库存执行机械恢复，保留命令、原始结果和独立核对。

即使以上通过，loop-carried reaching binding、细状态、运行时 dispatch、OS/CUDA
资源/寿命和输出因果闭包仍单独验收，不能宣称全程序建模完成。本项无 detector、
化简、变换或性能 A/B。
