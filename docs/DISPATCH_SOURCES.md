# Production marker 与 source invocation 的连接

日期：2026-10-23。状态：schema1 与 schema2 分片适配均各完成一次全范围真实连接。
第一阶段仍 OPEN。

## 职责与接口

```python
from scar.analysis.dispatch_sources import bind_dispatch_sources, query_dispatch_source

report = bind_dispatch_sources(source_binding_directory, dispatch_bridge_path,
                               coordinates, new_output_directory)
row = query_dispatch_source(output_directory, original_marker_instance)
```

source report 为 schema2 时，必须显式传入其原 composition index：

```python
from scar.analysis.program_composition import CompositionIndex

composition = CompositionIndex(original_composition_index_path)
report = bind_dispatch_sources(source_binding_directory, dispatch_bridge_path,
                               coordinates, new_output_directory,
                               composition_index=composition)
```

schema1 原接口与检查保持不变，不需要 composition。schema2 不接受一个旧单文件
inventory，也不根据 source 路径或 locator URI 自动寻找其他 inventory。

这是原图间的引用连接：原 marker instance / ETO raw reference → 原 retained
InvocationKey → 原 source definition / body / RegionActivation。没有新增规范图、
producer、value、state，也没有重编译或重新 prepare 源码。

两侧 calls/codes/meta 原 SHA、字节数与 process membership 必须一致，source Run
必须等于当前共同坐标的 Run。source report 必须声明当前 raw scan 已完成；本
适配器另外流核 source binding 和全部 invocation 产物字节、行数、内部引用与坐标。
它不再次重放 call raw parser，不重新解析 ETO/Kineto 图。原 producer 条件继续保留。

`CaptureCoordinates` 可以保留 memory URI；调用方应把对应 payload 作为外部证据
保存。公共入口将 payload 写入独立文件时，必须保持 artifact 的 SHA/bytes 和
Run/Process 身份对应，不把保存 payload 写成重新验证 native 执行。

## 关系的边界

- 每条关联保持 `RETAINED_ANCESTOR_CONTEXT`，`direct_callsite_established=False`。
  最近保留 frame 可以来自库，并不等于发起该 ATen 操作的直接 Python callsite。
- marker 的 native TID 仅在已有 production bridge 的 RF 对应核验通过时，使用
  同一 capture 的 Kineto artifact 查询 `thread_for(..., "linux_native_tid")`。
  不全局等同 Python ident 和 native TID。
- source 未绑定、body 未恢复、ancestor 缺失都逐观察保留；不能向上随意找一个
  已绑定函数来代替真实 retained frame。
- Tensor slot 只引用原 bridge paths。缺失或未资格化 payload 不变为已知。
- actual/formal、返回、函数环境、状态、副作用与 ready/lifetime 没有因引用连接
  自动闭合，不能用于授权优化。

## schema2 分片身份核验

新适配器先核两侧 capture 的原 calls/codes/meta SHA、字节数、Run/Process 与
membership，再接受 source report 的分片身份。新 capture 369749 不能与固定
272038 的 source 产物混合；相同源码路径、RegionID 或 Python ident 都不能绕过
这些检查。

schema2 的 `CompositionIndex` 必须为正式分片 index，report 内 inventory receipt
与 composition canonical SHA 必须完全相同。所有 locator 只与公共 index 返回的
原 receipt/representation/pointer 比较，再通过绑定的公共 reader 读取，不能打开
任意外来的 locator URI。

| 原实体 | 核验边界 |
| --- | --- |
| CodeCapture / descriptor | 当前进程、完整 code key；原 call_sources descriptor 精确相等 |
| CodeSourceLink | 原 call_sources locator；code、verified snapshot、SourceReference、DefinitionID |
| Admission | 原 call_source_scope locator；same_capture 保留当前 PID/code，reused_code 仅作静态 witness |
| Source definition | 原 source shard `#/file/definitions/n`；原 snapshot/context、DefinitionID、SourceReference |
| Body | 原 checkpoint `#/graph` 与 `#/metadata`；原 source shard `#/file/bodies/n`；公共 ProgramGraph codec |
| Invocation | 完整原 JSONL SHA/bytes/rows；原 InvocationKey、raw entry、Process 与 Python thread coordinate |
| RegionActivation | 原 invocation 的 entry、typed region 和原 activation ID；额外保留 body namespace |

body namespace 使用原 checkpoint artifact URI、decoded SHA、
`scar.program-graph/<实际 graph schema version>`、`#/graph` 和原
definition/entry/source。它不使用 SQLite 行号、不使用 checkpoint 外层存储版本，
也不将裸 RegionID 当跨 body 身份。旧单 JSON 的 `#/files/.../bodies/...` pointer
不能替代这些磁盘上真实存在的 locator。旧 witness pointer 字段应为 null、旧 static
pointer list 应为空；必须显式提供 schema2 locator 字段。

验证按绑定 composition 内的原 file/body 做一次，缓存有限的校验收据。原 source
archive 只加载、不重新 parse/compile/prepare；每个实际引用的 body 只做一次公共
codec 核验，不为数万个 marker 重复解码，也不另存全图。source 原有 current-file
guard 和 raw-scan producer 条件继续保留，本适配器不把这些条件改写成新的采集事实。

invocation 即使处于 suspended/resumption 前沿，仍保留其原 body namespace，但
不能生成 RegionActivation。输出 association report 的 version 跟随 source 为2；
events ProviderArtifact 明示 `scar.source-invocations.events.v2`。marker-index
结构未改变，保持 version1。query reader 显式接受 association report1/2。

schema2 的 `partitioned_source_scope_audit` 只报告这些原 locator 与局部公开 codec
已核验。它不证明 direct call、actual/formal、Tensor 逻辑版本、effect 或 whole model。
所有原 authority=false 仍保持。CLI 已由集成入口增加可选 `--composition`
参数；source schema2 时要求提供。本适配模块没有改 CLI。

静态冻结记录：2026-10-23。先仅执行标准库 AST 解析与字节 SHA256；模块 SHA256
为 `d15b156047f5ef2d7ae7cf52e551ccc084f37453f2f203d994316c0825de69e5`。
其后经授权执行下述唯一一次 schema2 原272038实档验收，未覆盖 schema1 结果。

## schema2 实际验收记录

产物：`artifacts/experiments/first_stage_partitioned_dispatch_sources_20261023/`。
唯一运行 exit0，固定原272038 capture 与同一 `capture:91a2ed…0c66` Run，输入
`first_stage_partitioned_composition_bindings_20261023/{composition,bindings}` 与原
production dispatch bridge。没有执行 target、GPU、native graph 重导、源码 prepare
或测试套件。新369749 capture 未参与。

| 原 marker observation 对应情况 | 数目 |
| --- | ---: |
| 全部保留 | 79,592（39,796 span + 39,796 output） |
| 原 qualified slot path 引用 | 109,288 |
| 匹配原 invocation / code | 79,112 |
| 有原 definition 引用 | 28,448 |
| 有原 body / activation / namespace 引用 | 10,992 |
| 有 source、无已恢复 body | 17,456 |
| invocation 有记录、source 未恢复 | 50,664 |
| retained ancestor 缺失 | 480 |
| 接到原已核 native thread | 79,592 |

完整源 invocation 流 100,438 行 / 570,527,758 decoded bytes 的原 SHA 与计数通过，
包含 5,624 原 source RegionActivation。marker 引用中有 15,048 个不同原 InvocationKey、
1,833 个不同原 activation、4 个不同原 checkpoint namespace。重复 marker 引用
不能算成新的调用或 activation。

schema2 接线独立核验了 83 个原 source archive snapshot/context、425 个 definition、
74 个不同原 body（公共 codec）、2,059 个原 witness locator；392 个 binding 仍没有
definition。四种 association 状态均通过公共 query 读取并校验原输出行 SHA，source
definition locator 与 body 的 checkpoint/source-shard/metadata/namespace 进行了
少量实档定位核对，详细收据在 `query-results.json`。383 个上游未资格化 payload
slot 保持 gap，未据此制造缺失路由。

本次 `/usr/bin/time` wall **442.34 秒**，user 431.55 秒，system 10.02 秒，峰值 RSS
**1,332,212 KiB**；脚本内阶段总计 441.44 秒。此成本包含原 capture 字节核验、原
source/ProgramGraph 局部核验、全部 invocation/marker 连接和输出分母/query 复核，
不是目标程序性能或加速比。source/CP 校验成本真实保留，没有以只读 metadata 标签
代替公共 codec 验证。运行脚本、revision/module/input SHA、原 patch、time/progress、
完整 report 与 summary 均独立保存。

schema2 仍只建立 `RETAINED_ANCESTOR_CONTEXT`，全部 `direct_callsite_established=False`；
actual/formal、环境、返回、世界效果和完整程序建模均没有因此闭合。

## schema1 实际验收记录

产物：`artifacts/experiments/first_stage_dispatch_sources_20261023/`。
输入为已经成功完成的 source `reused_code` 绑定和 production dispatch bridge，
共同 Run 为 `capture:91a2ed5e3f92817799bd02fb2453dadd65ad28fbf4361165c31b881c371c0c66`。

| 原 marker observation 对应情况 | 数目 |
| --- | ---: |
| 全部保留 | 79,592 |
| 匹配原 invocation / code | 79,112 |
| 有原 definition 引用 | 28,448 |
| 有原 body / activation 引用 | 10,986 |
| 有 source、无已恢复 body | 17,462 |
| invocation 有记录、source 未恢复 | 50,664 |
| retained ancestor 缺失 | 480 |
| 接到原已核 native thread | 79,592 |

上表是 marker 观察数；多个 marker 可以引用同一个 invocation，不能读成独立
函数或 activation 的数量。上游 383 个未资格化 payload leaf 仍保留原 gap 引用；
紧凑 bridge 未保留逐叶描述，本适配器没有制造对应关系。

输入 100,438 条 invocation、562,360,669 字节的完整原始输出流 SHA/计数核验成功。
运行 exit 0，wall 55.55 秒，峰值 RSS 890,756 KiB。四种状态的原 marker 查询均
已执行，结果在 `query-results.json`；全部保留 direct=false。

这次没有执行 GPU workload、测试套件或完整 native 解析。坐标重新绑定仅核验
原 capture 的字节、manifest 和进程/线程成员关系，RF 对应使用既有 bridge 的
核验结果。后续更完整的 body inventory 应生成新的独立产物，不覆盖本次结果。
