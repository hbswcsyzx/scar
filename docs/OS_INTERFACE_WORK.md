# OS 接口与实际 work：R1 / R2 接线边界

2026-10-23。R1 已实现、仅静态冻结，尚未执行新模式的真实 raw 验收。
R2 仅设计，未增加关联类型/codec。完整程序建模仍 OPEN。

静态冻结收据：标准库AST解析PASS，未import/执行新导入模式。模块
`scar/trace/os_resources.py` 58,928bytes，SHA256
`c52f45a62693e3e78875b3a23b7c56e0a4cdb48862436981f8d98941a4900c1b`。
共享store模块仍为原冻结SHA
`eadc3e7ae116e4e47dad09aa842b5e33be48b39e49426c7e257efa3ad6b817b5`，未修改。

## 1. 审查发现与实际旧分母

原369749成功capture的离线报告
`artifacts/experiments/first_stage_joined_physical_20261023/resource-frontiers.json`：

- 1,067,773 物理行，253个per-TID artifacts；1,067,768 COMPLETED行、5个SIGNAL行。
- 原FD profile有915,204 observations，152,564次/40类接口被`outside_fd_profile`跳过。
- 这些接口包含metadata查询、poll、VM操作、pipe2/eventfd2/epoll_create1等真实producer。
- 原资源有12,648个OFD、12,649个handle generation、570个观察到的handle end。
- 原1,064次IO接到私有表区间；不代表全部IO或共享表已恢复。

旧`resource_gaps.count`是按`(code,TID,syscall)`聚合的组数，不能读成发生次数。
例如fd_table_identity_open有4组，首组就有201次。R1另保留groups与occurrences两种分母。

一个SCAR importer defect：失败exec的argv/env被省略后，旧replay落入FD参数路径，
产生`fd_argument_open`。这不是LeWM bug，也不是性能优化。新模式显式处理失败exec，
原schema1默认路径和历史已发布产物保持原样，修正范围在新profile中声明。

## 2. 显式API与兼容性

```python
from scar.trace.os_resources import (
    import_os_resources, publish_os_interfaces, OSInterfacePartitions,
)

# 不传interface_work仍是原schema1，原to_dict输出不变。
fragment = import_os_resources(
    retained_os_directory, scope="capture-import", root_tid=declared_root,
    coordinates=verified_capture_coordinates,
    max_bytes=2_000_000_000, max_lines=2_000_000,
    interface_work=True,
)
receipt = publish_os_interfaces(fragment, fresh_output, budgets=None, progress=callback)
reader = OSInterfacePartitions(fresh_output / "manifest.json")
for envelope in reader.iter_records("submissions"):
    original_typed_wire_record = envelope["record"]
```

`interface_work`必须为exact bool。新模式的原fragment/profile是schema2；它拒绝
`to_dict()`，要求有界分表导出，避免将百万work重复嵌入一个巨型JSON。显式新存储
manifest自身version1，声明承载原`scar.os-resource-fragment` schema2；存储版本不是IR版本。
CLI/联合pipeline由集成入口后续统一挂接，本模块没有改它们。

本轮只改`scar/trace/os_resources.py`、新增本文档。没有修改store或任何IR类型、
collector、source/native importer、LeWM或运行环境。

## 3. 每条实际接口如何进入模型

原扫描顺序保持per-TID原物理行顺序，不进行跨线程timestamp排序。每个可解析的
完成形状保留：

- 原artifact表索引、一基物理entry/receipt locator；有普通return时另给return locator。
- syscall、result整数及原token、errno、参数原顺序、exact数值或provider rendering。
- read/write/iovec、getdents/readlink/getcwd输出payload、exec argv/env、ioctl payload
  参数被省略为null并列出原参数位置。未识别接口仅保arity、全部参数省略，effects OPEN。
- 部分/截断参数保留`argument_rendering_complete=False`，stat结构里的`...`不会变成完整metadata值。
- 原十进制`provider_line_timestamp`、`provider_entry_line_timestamp`与-T duration；
  最多纳秒精度可精确转整数，更多精度保留原文本并使整数为null。每个timestamp另有
  明确`point_kind`：完整行是printleader，不能当return时间；resumed行仍只是provider
  resumed printleader，未验证为真实host return时刻。普通return仅保原source line，
  不用timestamp或entry+duration推导return/end时间。
- 原legacy profile归属、协议类别、来源process可解程度及所有source/effect/资源关联前沿。

协议类别仅覆盖内核接口类型，不是应用语义、纯性或设备效果证明。metadata、wait、
VM、namespace等当前被保留为实际work，资源依赖仍标`OPEN_R2`；不能因有类别就声称
这些依赖闭合。原line classifications仍保留`outside_fd_profile`，明确它是旧FD子集
的分母，另列新interface覆盖，避免历史分母被改写。

### 3.1 复用已有typed work

`fragment.iter_work_records("submissions"|"outcomes")`逐条构造现有类型：

```text
WorkSubmission
  origin = ExternalWorkSource(真实entry EvidencePoint)
  scheduling = DirectExecution(准确native-thread coordinate 或 Unresolved)
  executor = Unresolved
  dependencies/effects/materializations = (), coverage UNKNOWN
  retention = Unresolved

ResourceOutcome（仅普通syscall return）
  protocol_result = 原return ProviderFactReference
  frontier_coverage = UNKNOWN
  quiescence = Unresolved
```

空集合与UNKNOWN一起表示尚未恢复，不能读为NONE。当前不生成`WorkQuiescence`、
队列完成、GPU ready、完整效果完成、任何Tensor Materialization或逻辑值身份。

`COMPLETED`只表示这个内核接口返回；短IO、brk请求是否实现、poll就绪、driver内部
work及落盘都有独立合同，不能从该枚举推出。`-1`保留FAILED和errno。exit/exit_group
及成功exec不产生普通return outcome，分别保留EXIT_REQUEST/EXEC_IMAGE_REPLACED协议。
`?`等未知返回也不能编造结果或普通return。unfinished/resume解析前沿保留；没有恢复
完成receipt的entry不会被伪装成已完成work。

### 3.2 实际FD producer

新模式识别成功`pipe/pipe2`原输出FD pair，为read_end/write_end分别创建不同OFD
ResourceInstance与HandleBinding；同一pipe receipt/两个有序port保留在observation中，
绝不合并为一个OFD。正式channel/endpoint类型关联属于R2。
[pipe(2)](https://man7.org/linux/man-pages/man2/pipe.2.html)

成功eventfd/eventfd2与epoll_create/epoll_create1分别按实际返回FD创建独立OFD/port
receipt。已证明私有表区间中的close/dup可复用原replay；共享/继承身份继续OPEN。
对象内部counter、interest list和完整释放没有因创建FD自动建模。
[eventfd(2)](https://man7.org/linux/man-pages/man2/eventfd.2.html)、
[epoll_create(2)](https://man7.org/linux/man-pages/man2/epoll_create.2.html)

所有资源/handle身份仍由原profile receipt、原artifact/line/producer port限定。
FD数值不是全局身份；close绑定不等于底层OFD最终释放。未知producer返回或缺失
pipe pair使表状态保持前沿，不补猜测的FD。

## 4. 有界存储及验证语义

复用既有`scar/store/bundle_partitions.py`的`_line`、`_Chunk`/compressed sink、
完整chunk字节验证逻辑，没有再写一套encoder/compressor，也未修改该冻结模块。
这是对已有11个表的只读transport：

```text
observations / line_classifications / resources / handles /
target_lifetime_events / processes / threads / artifacts / gaps /
submissions / outcomes
```

work在导出时即时构造，不持有百万typed work对象副本；其他表来自原fragment。
每条保原ID；archive ordinal仅是本表原迭代顺序，不是旧单JSON pointer。locator是
真实chunk+line+/record。原provider trace不变，不另建可修改图。

输入扫描的max_bytes/max_lines与输出budgets独立。输出直接复用BundleBudgets：
默认16MB decoded chunk、17MB stored chunk、4MB单record、16GB总decoded、4GB总stored、
10M records、100K chunks、4MB manifest、JSON depth128/items2M。可显式传入budgets
实例或字典；实际预算达限则失败并留下partial chunks，不发布manifest，不改输入。

只有关闭全部chunk、表/work分母守恒并原子发布`manifest.json`后，reader才接受。
reader在yield第一个record前核完整有界chunk的stored/decoded SHA/size/line数量，
再逐条核ordinal；没有provisional行冒充完整hash已验。manifest也保协议原SHA/bytes。

typed构造检查、byte receipt、full execution cross-reference validation是三件事：
writer构造现有typed work、保留原资源typed记录；reader只报告字节/ordinal检查。
两者都不声称执行了全ExecutionModel校验或Linux效果/跨图依赖证明。局部消费者可
显式使用公共record_codec解码选中的typed原record。

## 5. R2 根本类型缺口与下一设计

**R2未实现，不得把下面内容读成已完成。**

当前已知FD数值/producer port仍不能成为`NativeHandle`，因为其要求canonical
`ValueOccurrence`；实际外部work也不能填入`ResourceAccessBinding`，因为后者及其
requirement绑定要求canonical OperationOccurrence/RegionActivation。executor存在
类似关联限制。实际已知身份不应仅因缺源程序端口就长期记为Unresolved。

下一阶段应先审查以下窄关联设计，接既有execution实体，随后再明确对应source：

1. **provider handle selector**：HandleNamespace + 原selector ProviderFactReference +
   原handle lifetime，可独立于ValueOccurrence存在；之后由显式对应关系连接源值。
   数字FD的含义由FD-table incarnation限定，不能只用Process/TID。
2. **external work/resource access association**：既有WorkTicketID → 原ResourceTarget /
   provider selector，保executor/访问方式/原receipt；canonical requirement或Use可未恢复，
   但已知target不能因此丢失。保留普通canonical ResourceAccessBinding现有语义。
3. **resource context/extent associations**：FD-table share/copy/member、pipe channel与
   endpoint、VM-context及mapping/backing/interval；每条关联有原点与provenance。
   表的状态变化与OFD position、mapping protection不能混成同一种版本。

这些都应是原ExecutionModel的不可变限定关联，公共codec/validator显式处理，不能
另建mutable resource graph，也不通过metadata标签替代真实端点。具体类型/表/codec
变更需先单独审查，再实现；R1没有暗加这些类型。

CLONE_FILES共享表，无该flag复制表但共享OFD；exec使表私有。回放必须使用clone
因果边与当时可证明的快照，不能复制父文件末尾状态或按timestamp全排序。
[clone(2)](https://man7.org/linux/man-pages/man2/clone.2.html)

VM mapping与FD是不同生命周期；文件FD关闭后mapping仍可活，部分unmap也不能直接
退休整个mapping。匿名/文件映射、MAP_PRIVATE/SHARED必须分开，不能直接等于Tensor
allocation、page驻留、PCIe transfer或LogicalVersion。
[mmap(2)](https://man7.org/linux/man-pages/man2/mmap.2.html)

poll返回仅是指定条件的就绪观察；metadata结果也依赖外部状态。R2及source/native
接线需原provider证据，不将时间相近、地址相同或retained Python scope变成directcall。
[poll(2)](https://man7.org/linux/man-pages/man2/poll.2.html)

## 6. 唯一369749旧raw验收计划（尚未执行）

静态冻结后经授权执行一次现存raw离线导入/分表导出，不重跑target/GPU/采集：

1. 固定原capture与共同coordinates；保上述1,067,773行/253artifacts及152,564次40类旧子集。
2. 新interface/work与ordinary/nonreturn分母分别核对；保原915,204 FD observations分母。
3. 原FD producer/read/write、failedexec、metadata、poll、mmap各少量locator核对；
   pipe输出必须两个不同target；失败exec没有伪FD参数gap。
4. 新reader完整byte/ordinal/count核验与少量公共typed decode，和全跨引用/效果校验区分。
5. 报告全部gap groups/occurrences、legacy与新process未定分母；source/native、共享FD、
   VM关系、未定process仍OPEN。预算、time/RSS/disk与producer/module SHA一并保存。

PUBLISHED仅表示本次原record transport写完，不能据此宣布第一阶段完整或授权优化。
