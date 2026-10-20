# 第一阶段：真实原生观察图导入

2026-10-20。局部导入验收 **PASS**；完整程序建模 **OPEN**。

## 范围与版本

真实全量导入代码 `fdae346`，输入来自原先正常结束的 LeWM capture
`first_stage_lewm_capture_20261020_bpf`，不重新执行 LeWM/GPU。
两个输入解压共 276,060,429 字节，均按原始字节 SHA256 固定。
conda lewm，Python 3.14.7；实际目标原生 provider Torch revision
`cf30153c4c131c8164ee7798e5022d810682e2cb`，不是分析进程猜出的版本。
产品代码没有 workload 名称分支，也没有传入手写函数、Tensor 名或 IR。

`import-lewm.sh` 是实际命令。CLI 产生 EvidenceGraph/IRBundle，没有产生假的
ProgramGraph、ExecutionModel、LogicalVersion、静态 RETURN、candidate 或变换。

## Observed / Implemented

| 项目 | 结果 |
| --- | --- |
| 原始 ETO 节点 / Kineto 记录 | 151,228 / 330,452 |
| 规范证据图动态记录 / 边 | 205,424 / 429,336 |
| provider Tensor 引用编号 | 5,593；不等于对象生命周期或内容版本 |
| 有序引用槽位 | 357,090：180,977 input / 176,113 output |
| ETO↔Kineto CPU 唯一 RF/名称对应 | 151,226 |
| runtime→GPU 提交关联 | 24,082，覆盖已采 kernel/memcpy/memset |
| USES_RESOURCE 边 | 48,164 |
| 资源选择器 | 3：设备 0，context 1 的 stream 7/13；生命周期 UNKNOWN |
| 非 duration 记录库存 | 125,030；保留 locator，不作为已恢复的 memory/ordering 模型 |
| 导入成本 | 198.45 秒 wall；2,359,328 KiB peak RSS；exit 0 |

这是离线分析成本，**不是 LeWM wall-clock 或加速比**。

## Inferred

RF 合并和 CUDA correlation 边以输入属于同 capture、固定 provider 语义和唯一
匹配为条件；没有按函数名/时间相近猜边。GPU lane pid=0 没有被当成 OS 进程0。
correlation 不变成 HAPPENS_BEFORE、同步、ready 或逻辑 Tensor 身份。

## Verified

- `schema-regression`：145 项旧 IR/codec/normalizer 测试通过，1.47 秒。
- `connections-final`：76 项通过，4.18 秒，含13项原生导入和直接受影响的旧
  region/production 测试；最终 CLI 报告改为 gzip 后13项重验通过，1.88 秒。
  没有把重复运行相加为新测试数，也没有跑完整仓库测试。
- 既有真实 CPU trace 成功：36 ETO 节点、34 RF 对应、68引用边、15引用编号。
- `audit-import.py` 仅标准库，不 import SCAR/Torch/目标。直接重读保留的原始
  gzip 和图：重放全部 ETO 父子、151,226 RF 对应、24,082 GPU 关联、357,090槽位，
  核对图记录守恒；确认未伪造内容、alias、producer 或 HB。exit0，34.20秒。
- `lewm-audit.json` 是独立审核结果。它检查已表示的观察，不证明未表示的关系完整。
- LeWM 与原 SCAR checkout 仍 clean；未改源码、依赖环境、checkpoint 或用户数据。

## 首次真实输入失败与修正

`cpu.initial.*` 保留首次失败：错误地把 ETO 根节点 self-parent 当成循环。
核对已归档 provider C++ 的 `finalizeExecutionTraceOutput`，根节点 ID1 的 parent
明确就是自身。现在仅识别固定 schema/revision 的该结构哨兵；普通自环和环仍拒绝。
不是目标程序 bug，也没有靠删除记录通过。修正后重验，完整 LeWM 一次导入正常结束。

## Rejected / 尚未建立

- 30,007 条 runtime 的 External id 还没有经源合同核对的 CPU↔runtime 映射，保留
  `cpu_runtime_external_id_unverified`，不因字段相同直接接成语义边。
- 未建立 Python→Torch occurrence、完整字面值/非 Tensor 端口、逻辑值版本、状态
  转移、allocation/stream生命周期、readiness、OS资源和视频输出的因果闭包。
- provider 引用不能接入旧 source-content bridge；旧 region 投影不会默认为CONTROL。
- 未将根/线程结构记录计为完整展开的源操作，没有删除原 source inventory 缺口。

## Proposed：下一实施项

先核验上述 External id 的 provider 生成/关联合同；同时以现有精确 call-site
和版本化源码 CFG 恢复 Python occurrence 的来源连接。源码 body 整体回滚、循环/
容器/写入和当前状态的缺口单独处理。所有新增关系必须有可重放来源；继续第一阶段，
不转入图化简或优化实验。

## 保留空间

所有生成的模型为 gzip；最终本目录约33.1 MB。初版 CLI 的26MB文本报告经逐字节
解压核对后压缩，`report-archive.json`保留原 SHA/路径映射，只删除本次自己的
无损重复文本。产品 CLI 此后直接写 gzip报告；没有为了格式变化重跑 LeWM。
