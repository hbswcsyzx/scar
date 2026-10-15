# N2.call-evidence：有限组件验收与未闭合依赖

2026-10-15。实现冻结 `bedcd2dfa8536a5251c49e5b8b883196207f9a03`。
**组件 mapped gate、全仓回归与真实 LeWM API离线重放通过。**
预算/索引修复`677e10f`的公共CLI完整重放也已通过：exit 0、773.944s，源码未变。
完整 `N2.call-edges` 的 E4（跨调用精确回溯 source actual）仍未通过。

## 1. 自动化范围

输入原始命令、project root、预算及可选自动 inventory。SCAR 自动采集每次
入口的 immediate caller、代码版本、指令偏移、完整 span、记录过的父调用及
有限中间路径。离线自动对应 source Call、core CALL/callee UseID 和进入的
target code；保留不完整路径、源码失配和未 lower 的 target body。
没有 workload 函数名单、手工图、业务名称规则或新 detector/backend。

```bash
python -m scar.cli trace --calls-only --project-root /path/to/project \
  --out artifacts/traces/example -- python /path/to/project/main.py
python -m scar.cli link-calls artifacts/traces/example \
  --project-root /path/to/project --inventory inventory.json.gz --out calls.json.gz
python -m scar.cli check-call-links calls.json.gz
```

无 inventory 时也可生成 source/call 对应；可用 core 受自动前端的有限支持
范围约束。默认预算适用于小例，真实输入超预算应声明缺口或显式配置，不能
假装完整。调用证据不记录 Tensor 数值，不把 weak 引用当作逻辑内容版本。

## 2. 冻结自验

- mapped gate：**659 tests PASS / 87.478s**，source 未变化；
  `artifacts/reports/gates/n2-call-evidence-verified.json`。
- fingerprint：`b6971561d685dbdc6b4a5b8bddda034dc6b324a1b57ad1d397538c1d4af328dd`。
  本次补充 startup hook `sitecustomize.py` 的冻结指纹及篡改反例。
- 新代码定向：代码快照/采集95项、离线连接40项、CLI6项均通过。
  这些包含在 mapped gate 中，不重复加总为额外测试。
- 独立只读复验：原三个阻断的15项断言通过（agent 运行报告，非新增pytest计数）。
- 全仓回归：**1,694 passed / 154.52s**，三项warning（测试finally-return语法
  反例、既有多线程fork弃用提示、既有Torch量化弃用提示），无失败或skip。
  `artifacts/reports/gates/n2-call-evidence-full.xml`及同名log。

## 3. 独立审计发现并修复的错误

| 原错误 | 修复与验收 |
| --- | --- |
| child可指向已返回的同代码parent，或跳过当前递归frame | 同pid/tid活动栈和闭合入口/出口区间核对；失配不保留确定caller/core对应 |
| metadata可自报虚假bytes/open/unknown/limits | 从原始记录重算可推导计数、字节、缺失区间与实际预算；篡改拒绝 |
| bound method与显式actual恰同一引用，误用raw signature证明来源 | 删除未证明actual→formal来源边；query抵达形参明确ARGUMENT_ROUTING_UNVERIFIED |

`left.method(right)`、Name中的bound method、partial及动态defaults均有通用
原始源码反例。不是只禁Attribute；普通Name也可保存改变调用约定的对象。
`sys.monitoring.CALL`本机小实验会把优化后的bound调用报告为function+arg0，
仍不足以独自证明显式actual对应。本门没有仓促新增这种采集协议。

## 4. 真实外部程序采集

使用已成功的同一条LeWM命令，配置 `pusht`、1个episode、25步budget/goal
offset；Torch2.13.0+cu132、CUDA13.2、RTX4090。输出隔离到SCAR目录。
LeWM前后HEAD `f70fed80288462ca4d006cb3607ec6da6eaa851f`，git状态均干净。

| 项目 | 首次默认预算 | 扩预算重试 |
| --- | ---: | ---: |
| workload退出码 / episode success_rate | 0 / 100.0 | 0 / 100.0 |
| Python入口记录（含挂起代码进入段） | 30,728 | 84,319 |
| 入口/出口事件 | 61,450 | 168,638 |
| 代码描述 | 620 | 850 |
| code/events原始字节 | 63,999,900 | 160,150,081 |
| 丢弃事件 / 丢弃code / 未闭合入口 | 53,601 / 29,783 / 6 | 0 / 0 / 0 |
| path gaps / errors | 8,640 / 16 | 0 / 0 |

首次插桩wall=125.567s、重试112.960s，均非clean benchmark；首次记录触及64MB，
保留截断原因并无损压缩；重试保持
目标/采集器源码不变，事件预算250,000、字节预算192,000,000。
重试65个UNKNOWN出口及4,021个SUSPENDED出口均保留其原状态；UNKNOWN不是
已经证明的异常，挂起代码也不提升为普通同步调用。

重试原始记录含1,386,048个引用观察，超出离线默认1,000,000；实际API复验
显式使用2,000,000引用、256MB原始数据、250,000事件预算。入口是通用
`ProgramInventory.from_dict → link_calls → CallEdgeReport.from_dict`；inventory
只需先严格核验一次，然后在同进程复用。初版CLI未暴露全部CallEdgeBudget
字段，因此首个外部压力样例使用等价Python API，未手工补图。`677e10f`已补齐
公共CLI独立预算字段及原子限额输出；旧默认上限不自动放宽。

API重放已通过：548份code描述核验，421个不同definition；22,548次源码调用
位置观察去重为483处，1,119次core CALL观察去重为9处（已有110处）。直接
core→target body闭合0处，沿核验runtime parent链有1处可经中间层到达body；
该链保留wrapper和未证效果，不代表参数数据流闭合。详见
[真实连接逐项审计](N2_CALL_CONNECTION_AUDIT.md)。
inventory核验455.430s、连接94.677s、序列化102.265s、API重放329.328s，峰RSS
4,980,692KiB，均为分析成本。完整E4和优化合法性仍未通过。

## 5. 状态与下一门

- **Observed**：原始命令运行成功，新运行证据实际产生，截断/范围清楚。
- **Implemented / Verified（有限范围）**：自动采集、source/core/call对应及
  frame内/正常返回引用查询，以上测试中的证据重放与反例。
- **Rejected**：从条件签名和同引用直接推导实际参数来源。
- **Proposed / 未验收**：实际callable、receiver、partial、default/cell状态，
  跨调用完成/state、循环携带状态、逻辑provenance与依赖闭包。

完整E4目标保留；新的有限组件gate不替代它。下一门先补具体操作规则和自动
证据，恢复可靠actual→formal→use关系，再完成call结果/异常/state的对应。
这些连接闭合后才能判断高层依赖、合法提升位置或常量替换/import删除指导。
**没有新LeWM变换、clean A/B或已验证加速比。**
