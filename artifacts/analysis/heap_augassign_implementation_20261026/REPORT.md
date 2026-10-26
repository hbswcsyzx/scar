Heap AugAssign：一个真实属性入口已构图并经正常读回，整程序仍 OPEN。

隔离分支 `codex/source-heap-augassign` 固定基线 `c6e31a9a`；未修改主树、LeWM、native 或 201-body 发布。仅改六个生产文件，精确前后 SHA 在 `SOURCE_RECEIPTS.json`，补丁在 `PRODUCTION.diff.gz`（标准 unified diff 的 gzip 归档）。

设计与实际接点：

- `source_heap_lowering.py` 沿原 LHS SG definition 的 `READS_SLOT → output slot.owner` 区分读取子树与写回子树。只计算一次 receiver/key，发出原 SG ATTRIBUTE/INDEX 读取；`store_prepared_heap_target` 只接已求值的原 ValueID，不再调用 AST receiver/key。普通赋值仍保持 RHS→receiver/key 的旧顺序。
- `source_function_try_lowering.py` 连接定位/读取→RHS→`FUNCTION_INPLACE_BINARY`→原 `STORE_ATTRIBUTE/STORE_SUBSCRIPT`；复用 Operation/Use/ReferenceValue/StateVersionValue、原 StateLocation、PARTIAL StateAddress、normal/raise completions 和 C0/C1 exception/traceback pair。in-place 可改变内容后失败，其 raise world 不回滚；storeback 也有独立失败 world。
- 原 function Try validator 保留 Name 合同，新增 heap capability 分支核原 AST 角色、同一 saved receiver/key、LHS 结果→in-place 左端口、in-place 结果→store 端口、CFG 支配/明确 state def-use、局部 hold/消费与失败 handoff、正常有序 release。环境 validator 核 READ 地址；原 store validator 继续核 WRITE 地址。没有新 producer/def-use/pending 权威。
- 新显式 `PYTHON_HEAP_AUGASSIGN_314_V1` 与自动 profile `PYTHON_SOURCE_ENTRY_314_CAPS_V11`。SP5/core wire 不变；旧 V2–V10 profile 不获得该 heap 语义，library 三能力与旧四能力默认 tuple 不变。V11 按原 AST 自动选择，生产无业务名、类名或行号规则。

实际选择与结果：

`prepare.py` 对保存的四条 AugAssign 前沿（原历史权重 25+25+2+1=53）读取其准确 CodeWitness source archive，并核 SHA/bytes/snapshot。原 AST 表明三条为 Name；Attribute/Subscript 谓词筛后最高项为 key `67455b76dece1d3a3157481796dc1ac16f27efc78094bfa2f2300ed374a97546`，`gymnasium/wrappers/common.py:125` 的 `self._elapsed_steps += 1`，历史权重25。原243 candidates、817 groups、100438 invocations 分母由正常 catalog 核验；未重跑其他主体。

- 首窗口 session17809：actual exit0，15.097229s；主体 UNSUPPORTED/54 construction ops/无图。旧 helper 按 SourceAtom 要求唯一，遇原 frontend 为 read/binding 各建的 owner Name 定义而正确拒绝。`candidate01/` 保留原结果与六源字节；未改为成功。
- 同一主体修正窗口 session37462：actual exit0，GNU-time 30.97s；runner30.604741s，body22.208730s，RSS231780KiB。131静态构造 ops；正常 SP5 结构读回、独立 source/readonly CodeWitness 验证均通过，1 module load/2 complete descriptor matches/0 compile attempts，末源码 SHA 核验通过。`candidate02/ACTUAL_TERMINAL.json` 保存原 load/in-place/store 操作定位，未新增图事实。
- 新 SP5 为 1,101,998 stored bytes / 10,286,294 decoded bytes，stored SHA `6d8f16e517cce68c5089383125c13188125a978ec85ccc545f1bbe23877bade6`，decoded SHA `f3de9d39c27834d9f54b2af7adca8e03f8d6ec72be04e7e2796a31d43b269e1d`。准确 local URI 与七字段见 `successful-programs-delta1.json`。原始字节保留本地，不复制大上下文进 Git。

边界：本轮实际验证 Attribute；nonslice Subscript 已接相同协议，未另跑真实主体/测试矩阵。slice 与私有属性 mangling 保明确拒绝。物理 refcount、primitive/外层 cleanup、descriptor/index/fallback 内部、最终内容/alias/finalizer、运行对象与实际变更仍未证；用 incomplete world/memory 接口和原 EFFECT_SUMMARY 债务保留。嵌套 cleanup 未支持处继续由原前沿拒绝。没有把 `+=` 作为纯 add，没有新增运行/目标/capture/全量扫描；25 只是原 retained source scope（沿用 delta 的 source_scope_run=272038）的历史调用权重。此图未 publication/ADD、未 currentRun binding，不改变原201正式模型计数，也不宣称四项/53历史调用均已恢复或整模型完成。

语义依据是仓库 `docs/model/PYTHON_DATA_DEFINITION_PROTOCOLS.md` §8.3 与原 SG frontend 的 AugAssign read/store 端口；复用旧 FUNCTION_INPLACE_BINARY、heap STORE、StateAddress 与 propagation 合同，而非逐 primitive 重写编译器/引用计数模型。普通 reader 已在本次实际 worker 内执行；未额外 replay 已成功主体。
