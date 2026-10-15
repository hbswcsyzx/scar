# D1：真实调用来源自动接入程序展开

日期：2026-10-15。状态：**Implemented；映射门 Verified；全仓与外部复验待完成**。
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
- 全仓报告预定：`artifacts/reports/gates/n2-call-demand-full.*`，正在运行。
- 原 LeWM 入口、原 calls 记录、256 文件/256 body/10,000 operation 预算的生成与
  独立重放正在运行，输出在 `artifacts/experiments/n2_call_demand/real/`。
  同时核对嵌入 seed report 与冻结 D0 完全一致，原始记录与 LeWM Git/源码不变。

真实复验尚无终态，不填写源码/region 数量或时间，不据小程序测试声称 LeWM 已接通。
回归与离线分析可能并行，耗时只表示该次分析成本，不是 clean A/B 加速数据。

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

本门结束后仍需 C1/C2：准确的 actual→formal→return/raise、receiver/defaults、
globals/closure/环境与状态依赖，然后补 loop-carried 值、alias/版本及 logical
provenance，才能反向求出需要保留的最小依赖并给出替换、提升、共享或删除指导。

没有新增 detector/backend，没有目标程序名称分支，没有新的 LeWM 变换或可信加速比。
