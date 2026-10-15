# D1：真实调用来源自动接入程序展开

日期：2026-10-15。状态：**Verified D1 only**，实现 `2cf4e40`。
这不是完整程序模型或 LeWM 优化闭环的验收。

## 自动化输入和输出

无需函数名单、业务常量、人工纯性声明或手工 workload 图：

```bash
scar trace --calls-only --project-root /path/to/project --out /path/to/calls -- python entry.py
scar inventory-program /path/to/project/entry.py --project-root /path/to/project --calls /path/to/calls --out inventory.json.gz
scar check-inventory inventory.json.gz
```

命令仅描述通用接口；大程序应明确设置采集和独立验证预算。`--calls` 启用 v6，
与旧 `--trace` 目前是两个独立输入模式，不暗中混合两类观察身份。

v6 保存一份完整紧凑 calls report、每个 eligible `(pid, code)` 的接入结果、
有类型来源的展开队列、入口模块初始化作用域，以及最终 definition→core region。
它保存源码、引用、来源与结构，不保存每次迭代 Tensor 数值。

## 模型对应

Operation 表达动作；Value 表达数据/引用或状态版本；StateLocation 表达可变位置；
Region 表达递归子图。调用是 Operation，不是以函数名字充当数据恒定证明。
模块初始化、类定义期和普通函数调用期的 source owner 仍要区分。

本门补的是 evidence→source→analysis demand→local region 的对应。
`EnteredCallCode` 不是 actual/formal 边；`SourceCallCandidate` 仍有条件；
EntryRoot 是真实模块初始化作用域，不伪造普通函数 body。

入口及非 deferred 模块导入闭包先获得有限上下文预算；源码直接调用需求从上向下
推进，随后才处理未接到入口的观察根与静态 remainder。同一定义多个 PID/来源保留
各自 origin，只构造一次。构造失败或预算耗尽不会留下成功 region 链接或退款。

## 验收证据

- 映射门：**303 PASS / 57.703s**，6 个判据均通过，测试期间源码未变化。
- 源指纹：`a64ba352478c1808f6a1a3ed855c37e561898297e2cc3e630f9940505b540747`。
- 机器报告：`artifacts/reports/gates/n2-call-demand-verified.json`。
- 门定义：`gates/n2_call_demand.json`。
- 全仓：**2,193 PASS**，零失败/错误/跳过；pytest 249.54s，进程 251.29s，
  峰 RSS 1,026,500KiB。3 项已有 warning，无新增 gzip 析构 warning。
- 原 LeWM 入口、原 calls 记录、256 文件/256 body/10,000 operation 预算的生成与
  公共独立重放均通过，输出在 `artifacts/experiments/n2_call_demand/real/`。
  嵌入 seed report 与冻结 D0 完全一致，原始记录与 LeWM Git/源码不变。
- 真实结果：150 文件、2,211 定义、10,160 源调用、50 个带缺口的局部 body 图。
  256 次尝试中 206 个 UNSUPPORTED；1,955 个定义未尝试，含不支持的作用域。
- 421 个 eligible group 全部接到准确源码定义；**32 CORE_LINKED / 389 INDEXED_WITHOUT_BODY**。
  后者分为 260 class 定义期作用域、28 closure/cell、2 generator 和 99 个其它函数
  lowering 边界。161 个普通函数种子全部实际尝试，不能把它们说成 421 个优化点。
- prepare 151 个不同路径，各 1 次；0 workspace/projection 失败。完整上下文 spool
  写入 52,232,056 压缩字节，还原 392 次，累计还原 209,975,282 压缩字节。
- 生成 **602.086s / 355,692KiB** 峰 RSS；重放 **607.542s / 881,800KiB**。
  压缩报告 7,685,899 字节。分析成本仍高，不能称为分析提速或 LeWM 加速。

回归与离线生成有并行，耗时只表示该次分析成本，不是 clean A/B 加速数据。
与旧 v4 报告共同的 150 个源码 fingerprint 完全一致；旧报告另含 eval.py，其在
当前 D0 是明确 code mismatch。两份报告用不同 runtime 证据，不做 body 数量提升比。
真实明细与逐组原因见 `generation-audit.json`，完整结果见
`artifacts/reports/gates/n2-call-demand-real.json`。

## 失败、修复与边界

1. 独立审查指出无关观察根可先耗尽 spool。现在先自动发现入口/import 闭包，
   共享同一有界 PreparedContextStore；保留轻量源码投影，spool 失败不改写 D0 见证。
   实测反例覆盖入口仍可展开、decoy 明确不可用、每 path 仅 prepare 一次。
2. 共享源码准备失败最初改变了旧错误文案。现在复制异常并保留原字段，重抛独立
   副本，不把重型 context 的 traceback 留在缓存。ValueError/KeyError 自动对照通过。
3. 新路径的重复源码读取最初无上限。现在沿既有有界读取器核对 decoded hash，
   超过 4MB 和读取中增长均拒绝，不在拒绝前无界读取。
4. **Baseline defect**：既有 context store 在压缩预算中途失败时，Python 3.14
   gzip 的 BufferedWriter 析构报 `RuntimeError('lost gzip_file')`。严格 warning 模式
   已复现为 1 FAIL。修复为预算越界后停止写入、完成有界 record 的 gzip 收尾，再
   抛出原预算异常并删除 partial。写入计数不退款、不超限；严格定向回归通过。
5. 非冻结开发期间曾因队列字段编辑交错出现 13 个测试失败；冻结一致版本重跑
   原组合 30 PASS。正式门只认可冻结后的源指纹和逐项结果。
6. 非 `.py` 实际源码仍是 frontend 边界；协议测试不冒充真实端到端成功。

## 下一门

先修复新诊断发现的通用编译上下文缺口：5 个 mismatch 的源码 fingerprint 未变，
按记录的 future flags 编译可逐字段重现全部 5 个 descriptor；旧零 flags 尝试为 0/5。
这项 Observed 探针不等于生产 matcher 已修复，需版本分派保留旧报告重放。

随后仍需 C1/C2：准确的 actual→formal→return/raise、receiver/defaults、
globals/closure/环境与状态依赖，然后补 loop-carried 值、alias/版本及 logical
provenance，才能反向求出需要保留的最小依赖并给出替换、提升、共享或删除指导。
详细下一门正反例见 [跨层连接实现计划](N2_CROSS_CALL_IMPLEMENTATION.md)。

没有新增 detector/backend，没有目标程序名称分支，没有新的 LeWM 变换或可信加速比。
