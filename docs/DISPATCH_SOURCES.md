# Production marker 与 source invocation 的连接

日期：2026-10-23。状态：已实现并完成一次全范围真实连接；第一阶段仍 OPEN。

## 职责与接口

```python
from scar.analysis.dispatch_sources import bind_dispatch_sources, query_dispatch_source

report = bind_dispatch_sources(source_binding_directory, dispatch_bridge_path,
                               coordinates, new_output_directory)
row = query_dispatch_source(output_directory, original_marker_instance)
```

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

## 实际验收记录

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
