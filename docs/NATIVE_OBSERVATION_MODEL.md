# 原生观察如何接入程序模型

日期：2026-10-20。属于第一阶段的自动建模适配；完整 LeWM 验收仍为 **OPEN**。
上位范围见 [第一阶段合同](FIRST_STAGE_MODEL_CONTRACT.md)。

## 为什么不把 ETO 节点直接变成 ProgramGraph

ProgramGraph 描述带控制流、作用域和 SSA 值的程序定义。ETO 描述一次观察窗口
中的实际调用，序列化顺序还可能是子调用先于父调用。将它们依次塞入一个
Block，会制造串行关系；每个节点造一个 Region 和 RETURN，则会制造没有恢复
出来的静态定义和退出。两者都不能作为自动程序模型的证据。

本次适配复用已有 SemanticGraph、EvidenceGraph、ValueGraph 和 IRBundle。
provider 的操作描述进入定义目录，实际 occurrence 进入 EvidenceGraph；前者
没有被宣称为原 Python 源码函数的完整定义。尚未恢复的源码、当前状态、逻辑值
和资源生命周期仍在缺口中。没有产生 Optimization IR、candidate 或变换。

## 实体及其程序对应

| 实体 | 对应什么 | 不能由此认定什么 |
| --- | --- | --- |
| Operation definition | 固定 provider 版本下的操作描述 | 原 Python 函数的完整实现、纯函数 |
| Operation instance | 一次 ETO 调用或 Kineto 活动 | 静态节点、聚合调用数 |
| ProviderReference | provider 在该次窗口记录的引用编号 | Python ObjectID、LogicalVersion、allocation 生命周期 |
| 输入/输出引用边 | 某次调用有序槽位记录了哪个引用 | 读取/写入了哪些字节、唯一 producer、内容未变化 |
| resource observation | 该条活动实际报告的设备、context、stream 等选择器 | handle 未复用、stream 创建/销毁、队列已完成 |
| SUBMITS_WORK | 同 scope 内唯一 runtime correlation 对应的实际 GPU 工作 | host 返回先于 kernel 开始、GPU 已同步、依赖集合完整 |
| 原始定位与哈希 | 事实来自哪份文件、哪个记录/槽位 | 优化合法性或 provider 从未漏报 |

ProviderReference 是证据层实体，不是新的一种程序语义，也不取代五个结构支柱
Operation / Value / StateLocation / Region / Resource。它允许保存已经观察到的
引用关系，同时等待内容身份和状态转移的独立恢复。

例如，view 的两个 Tensor 引用可不同，但 storage 地址映射编号相同；原地写前后
Tensor 引用也可能相同。这些事实都保留。不能把同编号直接提升为同值，也不能
因为同 storage 编号就断言 allocation 的 generation、完整 alias 或内容版本。

## 机械恢复与限制

1. 离线读取 ETO/Kineto，固定 schema 和 provider revision；读取 gzip 时按解压字节
   限额。拒绝重复 JSON key、非有限数和结构冲突。不 import 或执行目标程序。
2. 建立 ETO 节点和 parent 索引。父子只表示 provider 调用包含，不推导完成先后，
   不自动变成 Python CallActivation。线程编号保留各 provider 的命名空间。
3. 只有 RF ID 和名称在双方都唯一且 scope 一致时，合并两侧对同次 CPU 调用的
   观察。重复、缺失或冲突保留为缺口，不选择第一个记录。
4. 按类型和嵌套槽位路径识别 Tensor 引用。Tensor 六元组中的 TensorImpl/storage
   地址映射字段只保留原始含义。普通六元素列表不是 Tensor；不采逐轮 Tensor 数值。
5. 保存 runtime 和实际 kernel/memcpy/memset；以唯一 correlation 建立提交关联。
   GPU 的 Chrome pid/tid 是设备活动 lane，不能直接解释为 OS 进程/线程。
6. 设备/流的观察使用资源目录和 USES_RESOURCE 边。没有生命周期收据时，不制造
   ResourceAccessBinding、QueuePrefix、Ready 或 LogicalVersion。
7. 所有原始类别在库存中保留。未知类别没有默认为无副作用、无消费者或无成本。

此时不能构造假的 ProgramSnapshot 来填 ExecutionModel。下一步接入真实源码图
后，才把已对应的 occurrence、端口、state/effect 和资源访问填入规范执行关联。
external-work 接口可承载尚未对齐的活动，但不豁免其必须引用真实源码快照的要求。

## 验收边界

局部验收要求：真实原生 trace 可机械导入、记录守恒、引用槽位可追溯、异步关系
不被错当同步、版本化图可 roundtrip。它不等于“完整程序建模通过”。

第一阶段还必须补齐源码内部自动恢复、Python→Torch 端口、状态与逻辑版本、
文件/进程/mmap/allocation/queue 的生命周期和 loading→推理→视频关闭的因果闭包。
这些项目不能因本次原生图导入成功而从验收分母中删除。

### 当前入口

```bash
conda activate lewm
python -m scar.cli import-native \
  --execution-trace /path/to/execution-trace.json.gz \
  --kineto /path/to/kineto.json.gz \
  --provider-revision cf30153c4c131c8164ee7798e5022d810682e2cb \
  --out /path/to/fresh-import
```

输出为 evidence-bundle、provider-references、resource-observations、import-report
的压缩 JSON。引用目录归 EvidenceGraph 所有，sidecar 是其便于查看的导出，
不是第二套数据依赖图。当前只解释经本机源码核对的固定 provider schema/revision；
其它版本拒绝解释，其原始证据仍可保留。

新目录及关系使用 evidence schema 4；旧能力继续输出原 schema 3 并可读。旧
region/content 投影若没有对应语义，明确拒绝而不将引用边当作 CONTROL 或内容。

## 固定 provider 的 CPU scope 关联

Torch 上述 revision 的 Kineto gitlink 是
`094d3c1d072362d0a919a77299459eee94f97931`。已按原始源码核对并归档：普通 CPU
scope 使用 CUSTOM0，USER_SCOPE 使用 CUSTOM1；Kineto 根据前者找到 linked CPU
activity，Chrome 写出的 External id 来自该 activity 的 correlation ID。
参见固定版本的 [Chrome 写出合同](https://github.com/pytorch/kineto/blob/094d3c1d072362d0a919a77299459eee94f97931/libkineto/src/output_json.cpp#L786-L807)
与 [精确映射](https://github.com/pytorch/kineto/blob/094d3c1d072362d0a919a77299459eee94f97931/libkineto/src/CuptiActivityProfiler.cpp#L289-L320)。

据此新增 **PROVIDER_SCOPE_ASSOCIATION**，方向为唯一 cpu_op occurrence→实际
runtime/driver/GPU activity。匹配必须绑定 capture、声明的 provider revision、
实际 host process 和 External id。CPU 候选必须唯一；一个 CPU scope 对应多个
runtime 正常。不会使用 user_annotation、名字、时间包含、其它进程或父线程来补边。
RF ID、External id、CUDA correlation 分属不同协议，不能交换使用。

这不是 parent、containment、submission、control、HB 或 ready。缺少正 ID、缺失/
重复 CPU 候选保留缺口；安装二进制实现声明源码版本仍是显式条件。仅有该新关系
时才使用 evidence schema 5，原能力保持3/4。Program27/Execution8未改。

## 独立对象目录与参数引用对应（Implemented，有限研究 profile）

审查发现旧 `ObjectBinding(object_id, value_version)` 只有内容关联，不能登记一个
内容尚未知的 Python 对象。现在在**既有 ValueGraph** 内增加 `ObjectInstance`：

| 记录 | 表示什么 | 不表示什么 |
| --- | --- | --- |
| ObjectInstance | 一个有采集作用域和身份证据的 Python 对象 | 内容版本、allocation、对象创建/释放 |
| ObjectBinding | 对象在指定范围与已知内容版本的关联 | 对象身份的唯一注册途径 |
| ProviderReference | ETO collector 的映射 token | Python 对象、存储寿命或内容身份 |
| OBJECT_REFERENCE_ASSOCIATION | 某个准确 marker 参数槽中的对象引用对应 | 全时间 alias、内容相等、producer、effect 或 ready |

`object_ids()/has_object()` 统一查询显式目录与历史 bindings；旧内容链接仍只读
bindings，不因对象登记而获得版本。Bundle、content、resource handle/holder、
identity query、source target 已使用同一所有者规则。identity 查询给目录查询计费；
snapshot 继续按完整 artifact 字节重验。没有建立第二套对象图。

Values 仅在非空对象目录时输出 schema 2；空目录保持 schema 1 原字段/计数。
新引用对应边仅在使用时输出 evidence 6；scope 关联仍为5，provider 引用仍为4，
旧图仍为3。旧 header 不接受新能力。Program27/Execution8 没有改版。

`scar.trace.reference_import.import_reference_bridge` 机械重放已归档 CPU 研究
collector 的 profile `scar.marker-research-probe-v1`。这**不是生产采集器**：它
固定 supplied 文件字节/作用域，核对 marker nonce/PID/sequence/phase、唯一实际
ETO node、弱引用 token、原 payload path、平铺后准确 Tensor 槽，以及录得的祖先
invocation/code。重复实参保留逐槽边；snapshot token、缺槽、重复节点/路径、
缺失 phase 或不一致进程会拒绝，不能用 shape、地址、函数名和时间修补。

研究 marker 把 Tensor leaves 平铺为位置实参，因此原 path `[0,0]` 与 ETO 槽0
不同。**output phase 也读取 marker.inputs**。边保留双侧原始 locator；JSONL
定位使用原物理行号。marker 的 provider parent 与 Python 祖先上下文分别保留，
不提升成直接 Python→ATen 调用。相同 Python weak token 对应多个 provider token
只报告观察，不能擅自把对象的全部时间绑定成一个 TensorImpl。

该桥按 **Inferred** 保存：输入属于同次声明 collector capture、collector 在持有
同一个 Tensor 时取弱引用并传 marker 参数，仍是明确条件。研究 sidecar 缺少
生产级 session/thread manifest、预算/丢失库存及生命周期收据；导入后不能倒称
这些保证已经存在。它不保存 Tensor 内容、不读 `_version`，不产生 LogicalVersion。

公共入口可省略 Kineto 做明确的 ETO-only 导入，报告 `kineto_not_supplied`；不能
伪造空 Chrome trace，不能从活动数为零推出没有 GPU 工作。研究引用对应需同时
给出以下参数（或使用 Python API）：

```bash
python -m scar.cli import-native --execution-trace ETO.json \
  --reference-markers markers.json --call-events call-events.jsonl \
  --call-codes call-codes.jsonl --call-meta call-meta.json \
  --reference-profile scar.marker-research-probe-v1 \
  --provider-revision cf30153c4c131c8164ee7798e5022d810682e2cb --out FRESH_DIR
```

## 后续连接顺序（Proposed）

1. 本次 scope 合同先通过反例、旧版读取和真实原生数据独立审核，再接下一桥。
2. CPU marker 实验及有条件的离线引用对应已接入。生产采集还需 recorder 的有界
   公共引用/context 接口、同次 manifest、独立预算/丢失及异常关闭；验证外部 mode、
   subclass 和线程边界后才可接真实 LeWM。不能假定 marker 包住原 ATen 调用。
3. source inventory应保留已有源码语义/CFG子图，避免只剩digest而失去分支/循环
   查询。再补尚缺的内部 source value/state 恢复和 OS 资源闭包。

已否决“再包一层 source-call occurrence report”：现 FrameCallEdge/CallSiteLink
已持有该来源关系，重复封装没有新增依赖边。上述步骤均属于第一阶段，不启动化简。
