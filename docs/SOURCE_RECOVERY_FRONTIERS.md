# Source recovery：真实缺口与下一条必要连接

日期：2026-10-23。第一阶段 **OPEN**。本报告是已保存产物的只读审查，
没有执行目标程序、prepare、compile、测试或新的全量任务，也没有修改运行代码。

## 1. 证据范围

输入：`artifacts/experiments/first_stage_source_bindings_reused_20261023/result/`
中的 `report.json`、`bindings.json`、`invocations.jsonl.gz`；另只读核对其绑定的
旧 inventory、当前原始 call events、collector 实现及实际文件是否存在。

**Observed：** 当前原档完整扫描产生 100,438 条 entry/exit 记录、817 个实际 entered
code group；855 个 captured descriptor 中，进入绑定的 817 组有 812 组完整
descriptor 匹配、5 组没有旧 witness。报告的 115 个当前 source guard 均为
`FINGERPRINT_MATCH`。这只覆盖获得 VERIFIED 静态来源的那 115 个 snapshot，
不是所有外部文件的来源验证。旧动态调用、PID 和执行次数没有用于生成本轮事实。

静态 witness 来自 `first_stage_environment_inventory_20261022/inventory.json.gz`：
其预算是 256 bodies／10,000 construction operations。本轮是显式
`witness_mode=reused_code`，没有重新编译来源，也没有自动获得更新后的 body。
原 raw scan、完整 descriptor、当前 source fingerprint 和旧 canonical body
引用各自承担不同证明，不能相互替代。

| 当前绑定状态 | code group | entry 记录数 |
| --- | ---: | ---: |
| BODY_LINKED_REUSED_WITNESS | 34 | 4,948 |
| SOURCE_LINKED_REUSED_WITNESS | 391 | 3,838 |
| UNRESOLVED | 392 | 91,652 |
| 合计 | 817 | 100,438 |

计数按每个 binding 的 `entered_invocations` 加权。生成器的多次 resume 也产生
frame entry/exit；现有报告有 4,021 条 suspend/continuity frontier，因此这些数字
不能解释成 100,438 次已证明完整、互不相同的高层函数执行。

## 2. 91,652 条 UNRESOLVED 分别卡在哪里

以下三类在本产物中互斥，合计精确等于 91,652。

| frontier | code group | entry 记录数 | 实际含义 |
| --- | ---: | ---: | --- |
| CODE_SOURCE_INCOMPLETE | 259 | 71,368 | 当前 resolver 的项目根目录边界 |
| NO_MATCHING_CODE_WITNESS | 5 | 16,137 | 新代码没有旧完整 descriptor/source witness |
| VERIFIED_CODE_WITHOUT_DEFINITION_WITNESS | 128 | 4,147 | 代码匹配成功，但没有对应类型的定义绑定 |

### 2.1 外部边界：71,368

**Observed：** 全部 259 组都记录同一 `SOURCE_BOUNDARY` 原因：
`code filename is outside project root`。这批记录中没有 source 文件数、字节数、
compile 次数等预算拒绝。不能把这个具体根目录限制解释成普遍“语义未知”。

| 文件类别 | code group | entry 记录数 |
| --- | ---: | ---: |
| site-packages 的普通文件路径 | 188 | 70,157 |
| 普通标准库文件路径 | 50 | 408 |
| `<frozen ...>` 或 `<string>` | 21 | 803 |

70,565 次对应的普通文件目前实际存在；本次只读存在性检查没有重新验证这些文件的
源码 SHA 或编译对应关系。803 次没有直接可打开的 `co_filename`：469 次 frozen
module、334 次 `<string>`。frozen module 可能通过固定 CPython 发行版本恢复，
所以“没有直接文件名”也不等于已经证明源码永远不可得。

主要文件（前缀为当前 lewm conda 环境的 `lib/python3.14/site-packages/`）：

| 文件 | entry 记录数 | 主要 code group |
| --- | ---: | --- |
| `numpy/_core/fromnumeric.py` | 37,532 | `_max_dispatcher` 和 `max` 各 18,685 |
| `torch/nn/modules/module.py` | 20,559 | `_wrapped_call_impl` 10,499；`__getattr__` 9,911 |
| `einops/einops.py` | 4,024 | `rearrange` |
| `pymunk/vec2d.py` | 1,777 | 向量操作 |
| `pymunk/space_debug_draw_options.py` | 1,438 | 颜色表示等操作 |
| `pymunk/body.py` | 1,309 | 位置、速度等属性 |

**必要连接：** 从实际 CapturedCode 自动准入其已安装依赖源码，保存 provider、版本、
源码 SHA、编译上下文与精确来源；外部 Python 调用通向 native 的区域继续保留边界。
准入和成功匹配本身不证明函数纯度、输入不变或可化简。

### 2.2 五个新代码：16,137

**Observed：** 回查旧 inventory 的 `model.codes`／`code_links`，五个 key 均不存在，
同 filename＋qualname 的旧 descriptor 也不存在。本例是没有旧 witness，
不是找到旧 descriptor 后确认它不匹配。

| binding | 代码路径、行和 qualname | entry 记录数 |
| --- | --- | ---: |
| 664 | `torch/_library/simple_registry.py:142 find_torch_dispatch_rule` | 14,224 |
| 353 | `scar/trace/callable_environment.py:228 ..._anchored_reference.<locals>.forgotten` | 1,891 |
| 164 | `scar/trace/execution_evidence.py:113 ...__init__.<locals>.importing` | 14 |
| 165 | `torch/_ops.py:1213 OpOverloadPacket.__getattr__` | 4 |
| 301 | `torch/_ops.py:1377 _OpNamespace.__getattr__` | 4 |

**Observed：** `forgotten` 是 SCAR 注册的 weakref callback，`importing` 是 SCAR
替换 `builtins.__import__` 的 hook。它们共 1,905 条属于 observer 活动；其中 1,800
条 `forgotten` 记录落在 Attention.forward 的 recorded parent 区间。父区间没有把
SCAR callback 变成 LeWM 源码。这些记录应保留并建立 observer 来源，不能仅按路径
删除，然后把减少后的分母宣称为完整覆盖。

**Observed：** 14,224 条 `find_torch_dispatch_rule` 原始 entry 的参数
`torch_dispatch_class` 全部引用同一 token `weak:272038:40405`。本 capture 的
dispatch collector 安装了 `DispatchEvidence.start.<locals>.Observe(TorchDispatchMode)`。
该 helper 的 recorded parent 主要是 modulate 5,400、ConditionalBlock.forward
4,500、Attention.forward 1,800；记录仍声明 `direct_callsite_established=false`。

**Inferred：** 新 mode 与新 callback 的出现支持这些 Torch helper 调用由 observer
引入的判断。**尚未 Verified：** class token 与 SCAR Observe 的身份边，以及其完整
生效区间；不能把全部 14,224 条当成已经证明可以从目标执行中排除的活动。

**必要连接：** collector 注册／注入的 hook、callback、mode 实体和生效区间，
以及 provider callback 到原 Python 调用位置的关系。先补五个实际新 code 的来源
witness；不能按 Torch 路径全部排除，也不能从 parent 区间猜直接调用边。

### 2.3 有 code witness，但没有定义绑定：4,147

| code 类型 | code group | entry 记录数 |
| --- | ---: | ---: |
| generator expression | 6 | 3,959 |
| lambda | 2 | 68 |
| module initializer | 115 | 115 |
| Python 3.14 `__annotate__` | 5 | 5 |

主要实例：`wm/lewm/module.py:62 Attention.forward.<locals>.<genexpr>` 3,600；
`wrapper/default.py:42 ..._check.<locals>.<genexpr>` 312；
`spaces.py:350 Box.__init__.<locals>.<lambda>` 62。

**必要连接：** 按实际 code 类型映射模块初始化、表达式生成器、lambda、延迟
annotation 的定义及区域接口；复用现有 source identity，不能伪装成普通 FunctionDef。
生成器还需要 factory／resume／suspend／completion 的关系，不能只给每个区间新建
一个完整函数调用来掩盖连续性缺口。

## 3. SOURCE_ONLY 的 3,838 条是什么

它们有 code/source witness，但原引用的旧 inventory 没有 canonical body。
按旧 admission 最后一个具体阻塞原因加权：heap／destructuring 1,259；IfExp
1,111；BoolOp 372；class 等特殊 scope 260；Slice 182。剩余 654 分布在其它
语法、局部 slot、generator 等边界，未自动视为覆盖。

主要实例是 Attention.forward 900、ConditionalBlock.forward 900、
DrawOptions.draw_fat_segment 324、Transformer.forward 150、Predictor.forward 150。
其中一些语法已经有后续实现。**下一步应先使用当前完整任务的新 inventory 重做
绑定**，不能重复把旧 snapshot 的诊断当成当前实现的缺陷。

所有 100,438 条记录仍有 actual/formal、return、function environment、state
effects、canonical completion 接口 frontier。4,948 条 body-linked 不是完整执行
模型的验收结果，也没有授权任何优化。

## 4. Proposed：最小自动 external source 准入

以下是下一条实施设计，**尚未实现**。只增加被实际 code 触发的来源准入，
不重新设计核心 IR，不增加 detector/backend，也不把项目根目录扩大。

### 4.1 保留 program root，独立选择 source namespace

1. 对原 capture 只执行一次现有 `scan_call_trace`／`_EnteredCodeSink`。保持 collector
   的真实 `project_root`，取已核验的 entered CapturedCode、完整 descriptor 和 anchors。
2. 复用当前 code/source witness 与 source guard；只为尚未解决的实际 code 建立
   新需求。普通绝对 `.py` 文件按规范路径去重，不枚举整个 site-packages，不执行
   package import，不展开所有传递 import。
3. 从采集环境的 interpreter／prefix／sysconfig 路径收据，以及已安装 distribution
   的 METADATA、RECORD／文件清单确定源码所属。记录 Python 版本、implementation／
   cache tag、distribution 版本与 metadata artifact SHA。元数据说明归属，**不能
   替代文件 SHA 或 code/source 对比**。多个 distribution 共用 namespace 时保留
   多个归属候选，不根据顶层名字猜唯一 owner。
4. 形成独立 SourceRoot 记录：program／installed distribution／stdlib／已注册
   observer provider 的来源角色、规范 namespace root、provider/version 依据，
   以及本次准入的精确文件列表。root 是源码身份的命名空间，不是递归读取权限；
   即使两个 distribution 共享 site-packages 祖先，也只准入各自被观察且有归属
   依据的文件。没有归属依据的外部路径保留 frontier，不能扩成 `/home` 或 `/`。
5. 按 root 分派已有 `_Sources` 与 `_SourceWorkspace`：worker 的 root 采用该来源
   的 namespace，`entry=None`，只对需求文件调用 `source_projection`。复用一次
   prepare、有限 scratch store、完整 compiler flags 和 optimize 0／1／2 的匹配
   逻辑；多个函数共用同一文件的 projection／编译结果。不要调用该库全目录的
   `inventory_program`，也不要触发 `prime_sources` 的传递 discovery。
6. 统一记录全局文件、字节、root、编译与 scratch 预算；不能给每个 root 一份
   完整总预算来绕过上限。每个 code 都保留准入、缺文件、归属不唯一、预算、
   flags 不支持、descriptor mismatch 等具体结果，未知不算覆盖。
7. 分别记录原始文件字节 SHA 与按当前协议解码后的 UTF-8 source fingerprint。
   CodeID 比较使用原 `compile_filename` 与完整 descriptor，不能改变路径后重新
   宣称是同一个 code。源码身份同时限定 root、provider 与 artifact，跨 root 不
   按短 SourceAtomID 字符串连接；现有 atom ID 含相对路径，单独使用可能冲突。
8. frozen／generated code、native extension 作为不同 frontier 保留。没有原始
   generated source 时不猜源码；没有 Python 文件的 native 区域不制造 Python body。
   观察到一个 external 文件也不证明其未执行分支或未观察传递依赖已经全部恢复。

### 4.2 当前硬边界与兼容方案

| 当前位置 | 限制／下一步 |
| --- | --- |
| `call_trace_reader._read_meta` | collector root 必须等于 replay root；保留此检查。不能把同一 trace 换成 library root 再读一遍 |
| `call_edges._Sources.context` | 当前要求 filename 属于 `self.root`；独立 namespace worker 只处理上层 registry 已准入的精确文件 |
| `call_demand._SourceWorkspace.prepare` | 当前只有一个 root；每 root 复用一个有界 workspace，并由协调器统一计费与释放 |
| `call_seeds._read_call_source_seeds` | 当前一次扫描后只建一个 `_Sources`；新增准入协调步骤复用扫描结果，不伪造新的 collector root |
| `CallSourceSeedModel.__post_init__` | snapshot 必须在 project_root 内；外部 link 不能塞入现有 v1/v2 report |
| `source_discovery`／`SourceDiscovery` | source_roots、files、dependency candidates 均限制在 program root；保留旧 discovery，external 文件单独准入 |
| `frontend_v2.source_reference`／`build_semantic_files` | 每次构造仍使用准确 namespace root，保留相对路径身份；不改变原项目根目录或旧 IDs |

**最小 wire 选择：** 先新增独立、带版本的新 external-source-admissions sidecar，
记录原 program/capture 身份、SourceRoot registry、精确 file snapshot 与 provider
artifact、每个 CapturedCode 到 root-qualified CodeSourceLink 的结果。旧 source
seed v1/v2、inventory v8、discovery 及已有 program composition v1 原样保留。
新 sidecar 不是现有模型已经支持多根目录的证据。

后续若把 external 结果直接纳入旧结构，则必须显式升级：source seed report/model
需新的版本来表达 root registry 与每个 link 的 root；`scar.call-edge-links` v1
若消费多根目录来源，也需新版 model/replay 的 root 资格字段；inventory/discovery
若接纳外部 FileInventory，也需新版 scope 和 reader；composition 若跨多个来源 artifact
引用 file/body，需新版 root＋artifact 限定引用；source-invocation bindings 若
消费这些新来源，需新版字段及严格 replay。不能只移除 `is_relative_to` 检查，
也不能在旧 wire 中添加字段而保持原版本。初次来源准入不需要修改 canonical
Operation/Value/State/Resource 或 ExecutionModel wire。

### 4.3 下一条必需实施及验收范围

实施 **observed external-code → provider/root/file admission manifest**：从现有
captured descriptor 自动生成有依据的 root/file 列表、global budget 及逐 code
frontier，再由独立 worker 复用 `_Sources` 的实际匹配。优先复用当前 trace 和
已保存 witness，不重新运行 LeWM，不修改当前进行中的全量任务。

验收必须逐条覆盖本次 259 个外部边界组及五个新 code 的准入结果：普通文件应明确
归属、source SHA 和 code/source 匹配状态；frozen/generated、observer 身份未绑定、
预算及 source 不匹配必须留有具体 frontier。降低 UNRESOLVED 数量不是验收条件。
source admission 成功以后，才进入对应类型的 definition/body 与调用接口连接。
