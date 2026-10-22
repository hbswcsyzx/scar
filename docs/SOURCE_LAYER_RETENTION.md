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
| SourceControlFlowGraph | suite/node/edge、分支/循环/失败与 gap；节点引用语句 operation ID | 表达式operation的相同粒度、已执行路径、完整exception语义或可行性证明 |

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

### 真实预算失败后的复用

首轮真实回建在512,000,000字节 canonical JSON总预算下保存66/151文件，余85条
明确记为预算gap，exit2；没有把未尝试文件丢掉。归档以gzip存储，实际约52MiB，
没有写出约496MB的未压缩重复文本。

`--reuse-archive PREVIOUS_DIR` 允许在**新目录**继续回建同一份库存：核对原input
SHA/字节/schema、snapshot/context，使用既有reader严格读回已存图，再核对当前
源码路径/namespace、decoded fingerprint 和Python版本。只有匹配才复用；缺行/
未存条仍需prepare，漂移或损坏不能计为成功。缓存字节仍消耗新预算，不能绕限。
同文件系统用独占hardlink保留已验证的不可变artifact，跨设备才复制；旧归档不改。
沿用的是先前源码重建证据，不宣称当前又重跑了该文件的AST分析。

## 如何接原有调用关系

没有函数名特判，查询链为：

```text
verified CallSiteLink.call
  → FileInventory.calls[operation].semantic_operation
  → SourceSemanticsGraph.operations[id]
  → operands(role,index).value → StaticValue.producer

同一调用的source atom + 指纹匹配AST字段路径 + lexical scope
  → 包含求值的原语句 → 原SourceControlFlowGraph node / suite / edges
```

**撤回旧exact-ID连接建议：** CFG以语句为粒度，CALL是另一个表达式定义；共享
ID类型不保证表达式ID出现在nodes.operations。frontend的parent_id是lexical scope，
不是AST父节点。不能将CALL塞进原CFG来冒充必执行，也不能只按包含行号拼接。

`index_source_control_contexts`复用既有三图，按指纹匹配的原AST kind/full span/
source atom重建parent/field/index。`index.query(call.source, execution_owner)`返回
原语句anchor、相对字段路径、scope、原CFG节点及gap。记录恒为execution_proven=false。
默认参数的路径保留无行号arguments等结构wrapper；同一行多条语句不合并；函数
call-time body不继承class/with定义时边界；comprehension首iterable归外层，其余
scope没有唯一原身份就明确未定。短路、注解策略、循环、失败与挂起边界均保留。

无计算语义的调用仍可按SourceReference查询，不补造StaticValue；scope查询不符
保留原字段路径、清空控制对应并报gap。block字符串不是CFG NodeID。动态actual/
formal、visit、状态和slot仍需原call/operand/canonical receipts，不能用weak token
或静态producer自动补齐。

## 2026-10-22恢复与验收记录

临时worktree及未提交的10月20日源码归档/实验日志在环境重启后已不在磁盘；
代码`93176e1`、`93a4171`、`ccf6cac`仍在Git。历史叙述不能替代当前证据。现在在
持久目录`~/AAA/scar-worktrees/structured-program-model`恢复，原仓库不改。
本次真实重建使用原已入库151文件库存，在同一prepare结果上查询上下文，再交给
原公共归档writer核snapshot/三图digest并保存，避免第二遍prepare/重读typed图。
这是实验观察器，不改变生产writer。命令、日志和最终结果见
[本次验收](../artifacts/experiments/first_stage_source_context_20261022/README.md)。

## 验收条件与范围

- 原库存、目标源码字节未改；输入、输出相互隔离，已有目录不覆盖。
- 全部文件都有留存/明确失败行；三图与原 digest 一致；预算不会删分母。
- 实际读回能追踪 ordered input→producer，并找到 CFG context；不是只输出计数。
- 通用 testcase 含 import、loop 与模块级异常哨兵，验证分析未执行目标。
- 对原 LeWM 151 文件库存执行机械恢复，保留命令、原始结果和独立核对。

即使以上通过，loop-carried reaching binding、细状态、运行时 dispatch、OS/CUDA
资源/寿命和输出因果闭包仍单独验收，不能宣称全程序建模完成。本项无 detector、
化简、变换或性能 A/B。
