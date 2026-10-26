# 单 GPU activity 的终结／静止合同补核

**结论：现 IR 足够，不需新增 enum、端点表、profile 或 backend。** 前一份 PLAN 对“尚缺 primary 合同”的判断在本次补核后缩小：固定 provider 的有效 kernel/copy end 能证明**该原 activity 的物理执行已经结束**。它不是原算子结果成功、host 提交闭包、child kernels 全完成或 value ready。

## 类型与下游实际含义

`docs/M1_RESOURCE_EXECUTION_CONTRACT.md:218` 已规定 `COMPLETED` 只表该 ticket 的协议终结；结果另取 `protocol_result`，输出效果另取 `effect_frontier`。`ResourceOutcome` 原字段允许结果及 quiescence 为 `Unresolved`、效果 coverage 为 UNKNOWN，没有必须把“物理活动结束”改写为 `cudaSuccess` 的类型限制。`work_validation.py:310–347` 独立核 ticket/Run/frontier，仍保内容与visibility缺口；下游 endpoint 支持也同时要求准确产出、源内容、placement、quiescence等，见 `validity_validation.py:640–673`。因此不应仅因三分 enum 新增一个 unknown-completion 表。

**优先复用 `WorkQuiescence`：** `M1_RESOURCE_WORK_PLAN.md:45–46` 将它定义为本 ticket 停止访问的独立依据，`work.py:212–224` 只绑定 ticket、原观察点与source。若 ticket 被严格限定为一个 CUPTI GPU activity，真实 end 是这一活动自身停止执行／访问的依据，可生成其独立 quiescence；绝不扩大到其子工作、同 host 调用或全部GPU。retention/dependencies/effects/materializations coverage仍 UNKNOWN，不生成 BorrowRelease、free或全局quiescence。该证明来自 end 合同，**不从 COMPLETED 标签推导**。

`WorkEnd(ticket)` 只有 ticket ID；`order_validation.py:216–219` 明说 intrinsic work-boundary 不是完成／成功产出的观测。因此单独构造 WorkEnd 不关闭接口。已有 `ResourceOutcome(COMPLETED)` 也能表达“此单activity协议已终结”，`protocol_result` 可指原活动fact；不表示计算结果正确。首门可先只发 submission + binding + 独立 quiescence，outcomes为空，避免强迫不需要的成功解释。

## 精确 primary 与限制

* [固定 Kineto CuptiActivity.h](https://github.com/pytorch/kineto/blob/094d3c1d072362d0a919a77299459eee94f97931/libkineto/src/CuptiActivity.h#L45-L69)，1-based L45–69：活动时间来自原 start，duration来自 end−start（启用TSC时分别转换）；L271–307是GPU活动和kernel类型，L532–544是copy metadata。此文件SHA **ab02afc2fd9b63e4aa99f20d24ed66a829f6e0b8fc2a6eb8d28183ff0a06e5a2**。
* [NVIDIA CUPTI13.2.1 Kernel10：start/end/completed](https://docs.nvidia.com/cupti/13.2.1/api/structCUpti__ActivityKernel10.html)：start/end是该kernel执行区间，0/0表示时间不可得；**completed另包含全部child kernels**。对应渲染行314–331（0-based网页抽取行，非HTML行）。end不能冒充completed。
* [NVIDIA CUPTI13.2.1 Memcpy6：start/end](https://docs.nvidia.com/cupti/13.2.1/api/structCUpti__ActivityMemcpy6.html)：字段表示该copy的执行区间，0/0时间不可得；渲染行309–322。该结构没有给出所复制logical Version／正确内容。
* [NVIDIA cuptiActivityFlushAll](https://docs.nvidia.com/cupti/13.2.1/api/group__CUPTI__ACTIVITY__API.html)：渲染行6626–6634，flush不隐式同步设备，forced可交付不完整记录。固定Kineto `CuptiActivityApi.cpp:193,458` 确实使用forced flush。因此“收到／closed／flush结束”不能替代逐活动end检查。已缓存 `output_json.cpp:772–865` 导出duration且负值截0，`119–128` 会将负relative timestamp截0；strict规则须排除零／负／非有限区间、annotation伪时长、未知或不一致actor/类别，不把所有`ph=X`都授终结。

资格是固定 provider 合同下**逐记录**的有效正区间解释；不能证明buffer完整或所有工作已结束。sample的正kernel/copy区间见原PLAN，本次未重读。原Chrome JSON未保存完整CUPTI raw struct，不能宣称恢复原`completed`、错误结果或flush前原buffer状态。cu132构建声明与固定Torch/Kineto源码仍是已有provider适用性条件；当前安装头`CUPTI_API_VERSION=130201`仅用于对应官方13.2.1文档，**不充作历史动态库字节或实际loaded版本证明**。primary逐文件bytes/SHA和审阅定位见 `primary-receipts.json`。

## 两源最小实现提案（PROPOSED / NOT_IMPLEMENTED）

后续实施／全量门准备位于 `artifacts/experiments/native_activity_work_20261026/attempt01`；Root已将初拟手选1条门改为全部provider GPU分母机械遍历。以下小门段落保留设计演进，不作为新门入口。

实际typedef补核：固定Kineto [DeviceProperties.h:25–42](https://github.com/pytorch/kineto/blob/094d3c1d072362d0a919a77299459eee94f97931/libkineto/src/DeviceProperties.h#L25-L42)在 `CUDA_VERSION>=13010` 选 **Kernel11**；`>=12000` 选 **Memcpy5 / MemcpyPtoP4**。cu132声明符合该分支条件；实际历史编译flags仍未观测。准确end合同见官方 [Kernel11](https://docs.nvidia.com/cupti/13.2.1/api/structCUpti__ActivityKernel11.html)、[Memcpy5](https://docs.nvidia.com/cupti/13.2.1/api/structCUpti__ActivityMemcpy5.html)、[MemcpyPtoP4](https://docs.nvidia.com/cupti/13.2.1/api/structCUpti__ActivityMemcpyPtoP4.html)；都按本activity的start/end解释，Kernel11的completed另含children。前述Kernel10/Memcpy6仅是初步共同字段背景，**不是实际typedef资格**。准确新primary SHA已追加到原receipt。PtoP serializer用inDevice/inContext，adapter按字段合同辨别，不按操作名字猜。memset本轮仍frontier。

1. 新 `scar/trace/native_work_bridge.py`：`acquire_native_activity_work(capture_root, partition_root, *, original_locators, max_decoded_bytes)` 在同进程调用现 `bind_capture_coordinates`，核原capture/manifest/Run/PID与 exact `process_for`；单次流式校验原Kineto SHA/EOF，保原array ordinal，只选择显式locator。复用原EEG archive的准确instance（必要时用既有partition reader作小projection并保原namespace/ordinal/source receipts），不重import全native。复用原Run/process，构造 `ExternalWorkSource`、`WorkSubmission`、`WorkEvidenceBinding`、`WorkQuiescence`。未知executor/scheduling与所有coverage/retention保未定，GPU lane不mint HostThread。factory返回私有不可从JSON恢复的source evidence和**现有typed records fragment**，不是新ExecutionModel／图authority。
2. 新 `scar/ir/execution/native_work_protocol.py`：独立checker对每ticket复核 exact artifact/schema/SHA/bytes、原instance/ordinal、Run/process、类别/device/context/stream、原ts/dur和scope限定。绑定source原row；end按原row的ts+dur解释，**不造不存在的 `/end` JSON字段**。依原source inventory拒绝漏/重/串ticket；修改candidate仍走独立语义核验，不用seal失败代替wrong-producer拒绝。它仅验证单activity quiescence，不授权success/production/ready。

**起止端点不得合并：** `EvidencePoint`本身无phase，故不能把相同raw整行fact同时称start/end。复用已有EEG `OperationInstance.start_ns/end_ns`：严格抽取原partition record成标准EEG小projection，保原instanceID/namespace及archive ordinal receipt；它有真实的 `#/instances/0/start_ns` 和 `#/instances/0/end_ns` 字段。origin.point与quiescence.observed_at分别引用该projection artifact的这两个不同FactSource；WorkEvidenceBinding指同exact EEG artifact/instance。原Kineto row locator另保原source。checker核小projection原字段与保存record相同，并按现 `native_import._ns(ts)`、`_ns(ts)+_ns(dur)` 核raw→EEG interval，不额外宣称无损恢复原CUPTI ns。若返回现 `ProtocolInterval(start,end,protocol,source)`，其两个ExecutionPoint也沿这两个实际EEG字段；不造raw `/end`、不新增endpoint表，不从数字先后生成HB。此派生视图只投影已有EEG，不成为替代provider的权威；无可核projection就拒绝端点资格。

**snapshot归属明确OPEN：** `ExecutionModel`必须有ProgramSnapshot，`ExternalWorkSource`只允许不依赖OperationOccurrence的来源，并不证明这个活动属于任取的host/shard程序。当前仅证明exact EEG activity→Run/process，未核此kernel属于哪个已建canonical activation；因此首门不造空ProgramGraph、不任取host图、不造ProgramSnapshot。它只返回可被原模型扩展消费的原typed记录，状态 `UNATTACHED_TO_PROGRAM_SNAPSHOT`。后续调用方若能提供exact真实ExecutionModel fragment及必要边界来源，才能按原snapshot扩展；本门不称该归属或整模型validator/query已通过。EEG小projection只作原来源的有receipt视图，不重命名原instance或取代原provider权威。

**单个实际门准备范围：** 复用原LeWM capture和kernel `#/traceEvents/387826`（copy `387651`只作真实wrong-instance交换负例）；公共binder一次 + 原Kineto215,705,815 B流式扫描一次 + 所需archive chunk一次。输出1个single-activity ticket/binding/quiescence，核原typed构造合同、owned source checker及唯一wrong-instance负例。公开checker接收原typed三表tuple，必须独立核source/原instance/Run/selector，不用密封错误替代语义拒绝；不为缺少standalone codec伪造ExecutionModel。不跑目标、GPU或原native producer，不扩大为全部kernel建模。Root持handle；runner只在Root批准2源API后准备，此文尚未实现或执行。

**真实获取成本不能写8MB：** 原coords已存verified bytes **1,170,866,107**；binder又解析OS **90,464,342**，下界 **1,261,330,449 decoded B**；再扫Kineto后下界 **1,477,036,264 B**。Root初步允许本门decoded **2,000,000,000 B**顶，选中archive chunk解码也在这个顶内；reserved／actual读量须独立计，不能把预扣写成已读。原archive-index声明全部stored **54,862,125 B**，后续prepare须计binder解码读+compressed hash读、OS第二遍及Kineto第二遍，不只计唯一文件大小。源码hash、control manifests与输出hash另列边界并冻结，无法装入即先报，不能静默额外scan。首门不读static program，原因是上述snapshot未接入；墙时成本未实测，不能借同CPU capture的0.8s数值。source代理确认858增量尚处设计且无resource消费hook；选择独立public binder，不为省扫描耦合其长门。未来只有同一fresh进程直接持有原live coordinates才可顺序复用，saved JSON不恢复authority。
