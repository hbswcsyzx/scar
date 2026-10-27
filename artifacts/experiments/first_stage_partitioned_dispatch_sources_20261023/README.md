# 原272038 source schema2 → production dispatch 接线

2026-10-23：一次实际运行，exit0 / PASS。没有第二次尝试或修复重跑。

## 输入与冻结

- 原 capture：`../first_stage_lewm_dispatch_20261023/`，target PID272038。
- 固定 Run：`capture:91a2ed5e3f92817799bd02fb2453dadd65ad28fbf4361165c31b881c371c0c66`。
- source：`../first_stage_partitioned_composition_bindings_20261023/composition/index.json.gz`
  与 `bindings/`，正式 schema2、same_capture raw scan 已完成。
- bridge：`../first_stage_joined_dispatch_20261023/result/native/dispatch-bridge.json.gz`。
- 本次冻结 revision：`6fe602f9f6db92aade0072cfb2fbeedd463a3a50`。
- adapter SHA256：`d15b156047f5ef2d7ae7cf52e551ccc084f37453f2f203d994316c0825de69e5`。
- `producer.json` 保存实际 script、六个依赖模块与输入字节 SHA；
  `implementation.patch` 保存运行时工作区 adapter/document diff。

原 capture 264 个成员、5 个进程、252 个线程通过坐标字节/manifest 绑定。新369749
未参与；没有目标执行、GPU、native graph 重导、源码 parse/compile/prepare 或测试。

## 分母与范围

| 原观察 | 数量 |
| --- | ---: |
| marker observations | 79,592 |
| span / output | 各39,796 |
| 原 qualified slot path 索引引用 | 109,288 |
| retained invocation 已接 | 79,112 |
| 有 definition | 28,448 |
| 有 body、activation 与 namespace | 10,992 |
| source-only | 17,456 |
| invocation-only | 50,664 |
| 无 retained ancestor | 480 |
| 原 RF 核验 native-thread 引用 | 79,592 |

源 invocation 流 100,438 行 / 570,527,758 decoded bytes 的完整原 SHA、状态计数
通过。源流有5,624个原 activation；marker 引用覆盖15,048个不同 InvocationKey、
1,833个不同 activation、4个不同 checkpoint namespace。它们不是 marker 行数。

schema2 身份验证分母：83个 source snapshot/context、425个 definition、74个不同
原 body 公共 codec、2,059个 witness locator；392个 binding 无 definition。
每个原 source/body 的验证结果局部缓存，不重建或复制规范图。

`result/report.json` 保留所有前沿；上游383个未资格化 payload slot 未消失。
四种状态通过公开 `query_dispatch_source` 实际读回、核选中行 SHA。具有 definition
与 body 的样例进一步定位原 source-shard definition 及 checkpoint graph/metadata/
namespace，见 `query-results.json`。全部 direct=false。

## 运行成本与复现

实际命令：

```bash
bash artifacts/experiments/first_stage_partitioned_dispatch_sources_20261023/run.sh
```

`run.py` 使用正式公共 `CompositionIndex`、`bind_capture_coordinates`、
`bind_dispatch_sources(..., composition_index=...)` 与 query；结果目录必须不存在。
复现前应改用新的独立实验目录，不能覆盖本次原报告。

`/usr/bin/time` wall 442.34秒、user431.55秒、system10.02秒、峰值RSS1,332,212KiB；
脚本阶段总计441.44秒。进度日志的20秒 heartbeat 只表示当前阶段存活，不代表语义
覆盖计数。此成本是离线原图/证据接线核验，不是 LeWM wall-clock 或加速比。

`result/associations.jsonl.gz` 保留79,592行，decoded SHA256
`6a87d1359c7a0ecf00bbc00c0d45598f78648319216a055d79b24049f91356fa`，
decoded287,980,988bytes。`result/report.json` SHA256
`da896ba8ccda219065a26c485a75b4e3b00de1f7334b8ce58323d6bfee3a97b7`。
其余真实存储字节收据见 `artifact-receipts.json`。

PASSES 仅对应上述原档身份与引用边界。没有建立 direct Python→ATen call、完整
actual/formal/return/environment/effect/ready 关系；第一阶段完整模型仍 OPEN。
