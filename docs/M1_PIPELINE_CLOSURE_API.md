# R3.3：调用顺序、端点范围与缓冲流水线

[实施计划](M1_PIPELINE_CLOSURE_PLAN.md)。本文定义模型与接口，不是测试通过报告。
Operation、Value、StateLocation、Region、Resource 五类实体保持不变，没有新增
ExecutionModel 表、wire 版本、detector 或 backend。

## 1. 函数递归展开后，顺序仍引用原图

同一个 ProgramGraph 可以包含入口、workflow 和任意层 helper Region。每次执行有
独立 activation，原 CallActivation 选择本次 caller 与本次 callee；相同函数名、
输入值或代码对象不能替代这条关系。跨调用的值/对象/表示身份仍需各自原证据。

`host_order.prepare_host_order` 只从已校验的原调用与 CFG 建一次派生索引：

```text
caller BEFORE ──entry bridge──> child 初始 block 首规范 op BEFORE
child 实际 RETURN/RAISE AFTER ──completion bridge──> caller AFTER / actual EDGE
```

CALL 走 AFTER，INVOKE 只走实际 taken EDGE。没有 entry、首 op、completion、实际
transfer 或已知相同线程时，不补相应桥；另一侧独立已知的桥可保留。不是选择较晚
捕获的操作代替入口，不默认 NORMAL，不根据同静态 Region 绑定另一 activation。

原 `ctx.point_precedes` 保留同 activation 的 True/False/None；P/V 的
`point_order` 使用原局部 CFG 快路，仅跨调用时做预算内 host path 查询。返回路径
保留原 CallActivation；准备/FK 成本与派生遍历预算分开。没有 host→WorkEnd 新边，
因此正常返回或 RAISE 不成为 GPU 完成、quiescence 或释放证明。

## 2. Endpoint selector 是有独立定义的范围

一个 EndpointContent 有原 MaterializationRef、准确 target lifetime，以及原
selector。StorageContent 的 RegionRef 仍表示 allocation 几何；endpoint 不伪装成
allocation/RegionRef。选定 profile 通过已有 ProviderFactReference 引用精确 bytes：

```json
{
  "schema": "scar.endpoint-byte-profile",
  "schema_version": 1,
  "profile": "BYTE_PREFIX_READ_AFTER_COMPLETED_WRITE",
  "operation": "READ",
  "offset_bytes": 0,
  "length_bytes": 8
}
```

artifact.schema 必须为 `scar.endpoint-byte-profile`，locator 为 `#`，最多 4096 bytes。
只接受固定字段、准确类型、无重复键及非有限数值的 UTF-8 JSON；不会打开 URI 或
执行外部 decoder。不同 schema/locator、非零 offset、缺 payload 都有准确未支持/
未决范围；已知非法字段不能借未支持 offset 掩盖。解析使用本 query 的精确
ExternalSnapshots，刷新时不信任之前的 profile cache。

operation 是 READ、WRITE_REQUEST、WRITE_ACTUAL 三个准确角色。READ 和
WRITE_REQUEST 为非空范围；WRITE_ACTUAL 可为零，但不满足非空读取需求。
读取 8、请求写 8、实际写 4 是三个独立 selector 定义，不能把读需求改成 4。
非零 offset、文本编码/append/device 语义及其它协议不由这一个 profile 推导。

## 3. 从源字节到端点的条件

BytePrefixWrite 仍核对原 RawRecordRef 的 request/actual byte counts 与准确 result
locator/原结果。端点写额外要求 writer-owned 原 Data Use 对应唯一 ContentRead，
源 Mat/version 与 linear rank-one uint8 selector 对得上。源 storage offset 与
destination endpoint offset 是不同量；一个任意整数或字符串标签不能补这条边。

source storage Mat 可以不同于 destination endpoint Mat，但不能因为 version 相同
就推断任意 cast/encode 表示等价。选定声明的 byte copy 仍保留 native/source
applicability 条件。Endpoint READ 与 WRITE 则要求准确同 target 与同 MatRef，不能
只用版本和长度合并两个编码/物化。URI 不是身份，SHA/schema/size/MatID 才是。

CompletedVisibility 只有经过原 contribution、actual、当前 state support、同
READ profile、target/Mat 及 host/work 顺序链才解释选定的 read-after-write 关系。
覆盖与贡献仍分 known/conditional，独立来源和可能 invalidators 不因删 join 缩小。
MATCHED 仅为这组声明关系相容；source/native capture、runtime 对应与变换许可
继续为 False。缺源、模糊输入、错端点/Mat 或实际前缀不足不能靠相同 FactRef 通过。

## 4. buffer 与 file 不能压成一个节点结果

默认通用 fixture 维护独立 buffer allocation/Mat 与 file endpoint Mat：

```text
serialized bytes
  → save.write → CPU buffer Mat + buffer/world state
  → close helper 的 buffer-state read → DataValue
  → flush 的原 Data Use/ContentRead → file endpoint write / actual prefix
  → close 的 handle/state 完成
```

buffer 可以已接收 8，但 file 尚未有贡献。缺 flush 不通过最终文件需求，提前观察
不能借未来 flush 的可见性；partial flush 仍对独立的 8-byte 需求报告缺额。
异常路径同样沿原 C1 pending/cleanup/replace 与实际调用出口；submit 后 RAISE
的执行不能伪造 wait/consume occurrence，也不能给未观测工作补 terminal/release。
保存尚未发生时，buffer 的当前内容是独立的 empty LogicalVersion/Mat：shape 为
0，allocation capacity 可为 8。close 读取这个空版本；flush 操作和状态仍保留，
但不伪造 requested8/actual0 的 byte-write 源记录或生产贡献。最终 READ8 义务不缩小。

这是一份通用声明模型，可以用机器验证连接；不等于从任意 Python 程序自动恢复
了这些阶段或库内部状态。M3 适配器与 M4 证据对应仍是后续工作。

## 5. 真实见证与范围

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python scripts/witness_io_pipeline.py --case file
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python scripts/witness_io_pipeline.py --case file_raise
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python scripts/witness_io_pipeline.py --case pending_raise
```

每个固定小程序在自己的子进程/临时目录执行，外层十秒超时，等 worker 退出后才清理
owned 路径。输出事件顺序、count、hash、实际异常及清理 receipt；不保存 Tensor
逐次全值，不升级环境，不访问用户数据。

file 的 pread 是同 fd、绕过 Python 缓冲的另一次 OS 读取，不是跨 process/open 的
可见性证明。file_raise 是 save 返回后的外层异常和成功 close，不模拟 close 自身
失败。pending_raise 的 4/8 是一次部分 memoryview 写后失败，不冒充 syscall 短写。
旧 nonblocking pipe 见证继续单独验证真实短写。OS 结果与手工 IR 对应分别归属，
timeout-kill 的源审也不能写成被正常退出的成功用例实测过。

flush、fsync-return、close、可重新读取和耐久性保持不同状态。Python
[io](https://docs.python.org/3.14/library/io.html) 描述流缓冲接口；
[os.fsync](https://docs.python.org/3.14/library/os.html#os.fsync) 是另一系统同步请求。
本门不进行断电/崩溃测试，也不从函数返回授予持久化证明。

## 6. 组合规模与未完成边界

完整流水线的多个 reads 共用同一个派生预算，不是每 read 重置 4096。复杂组合可
显式请求更大的有限预算，但必须报告实际用量和计费；默认值不因测试改大。完整
inventory、准备/FK/replay/复制成本与未检查项仍按 R3.2 区分，TRUNCATED 不变成安全。

Q facet 目标/基数、native/coherence、逻辑/物理真实对应、其它 endpoint 协议以及
selector/literal/C2/D3/M2 全构造分母仍逐项记录。完整第一阶段未完成，不宣称
自动 LeWM 建图/化简或新的加速比。
