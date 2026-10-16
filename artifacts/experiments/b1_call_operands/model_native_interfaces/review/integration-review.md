# P1 integration 独立审查

2026-10-16。审查对象为 root 编写的 native_validation、ProgramIndex 新查询、
model/codec/CLI 集成及对应 fixtures/tests；**不把我编写的 records 当作独立审查结论**。
未改产品/测试、未跑套件/全仓/采集/Torch/LeWM。运行一次 bounded IR-only probe。

## 1. 实质发现：B1 / P2，合法 legacy ID 子类图被索引拒绝

**Observed，修复前未关闭。** 现 core 历史上用 isinstance 接受 ValueID/RegionID
子类；新严格 EntryPortRef/ExitPortRef 则要求 exact 类型。ProgramIndex 初始化
无条件对所有 Region 调用 region_ports，为没有 native 能力的旧图也创建严格引用。

独立反例把 shared-body 旧图的 `caller.input` ValueID 改为子类实例，同时一致更新
既有 block argument 与 Uses。实际结果：

- `validate(graph) == ()`；`dumps(graph)` 成功，schema version **2**。
- `native_boundaries` 数量 **0**。
- `ProgramIndex(graph)` 抛 `TypeError: entry port value must be ValueID`。
- 同一结构的 exact-ID 控制图索引成功。

这属于新集成强制旧图采用新严格引用类型造成的兼容性回归。静态审查还发现
native_errors 对所有 Region 预构造引用，存在同类风险；本次实际复现的是索引路径。

建议修复：内部索引/分区使用包含**原 ID 对象**的 raw 坐标 tuple，避免为无关旧图
构造严格新记录；不能按 `.value` 字符串归并子类，也不能放松新 records 的 exact
合同或假定所有旧 core 都已禁止子类。new boundary 的严格引用仍须准确匹配 core。

root 已收到真实结果，并回复将用 root-owned regression 修复；本报告写入时尚未
读取修复后结果，不能宣称 B1 已关闭。不要用此前组件通过覆盖此反例。

## 2. 其余有界检查

| 项目 | 本次依据与结论 |
| --- | --- |
| native/core 分区 | 代码按 EntryPortRef 与完整 `(region,exit_name,index)` 检查并集/重复。实际重叠反例同时触发 native_port_duplicate / native_port_partition，codec 拒绝。 |
| 重复 Value、多 Return、Raise | 实际查询正常两个槽各返回2个独立 UseSite，Raise槽返回1个；相同Value的两位置UseID不同。没有按Value去重或选唯一producer。它们是静态控制site，不宣称每条路径实际执行。 |
| core 既有 unbound_exit | 源码/专门测试保留该限制；审查没有构造不存在 terminal 的假出口来绕过。 |
| partial / 多对多关系 | pair只核对对应boundary的真实端口，未强制双射或用同type配对；跨completion/type声明仍八域未证，符合冻结规格。 |
| 辅助 artifact / raw role / tree | 实际把signature/input-tree换为独立 `unopened://` 辅助artifact，图校验及roundtrip通过；代码无打开/flatten/role解释。未因不等于primary误拒。 |
| 私有属性篡改 | 实际把嵌套ExitPortRef.index改为False，validate先报schema，dumps拒绝；新native校验在共同schema/core/provider校验之后运行。 |
| model注册与唯一ID | 代码检查新表exact记录及独立ID唯一性；不存在与旧state/actuals并行的可变数据流表。 |
| codec v8 / legacy | 静态确认v8由native能力选择，v1–v7字段集排除新表，旧版本升级仅补空新表，旧schema不能注入新字段。读取了v7 frozen proof与测试；本轮没有重复执行legacy套件。 |
| CLI权限 | 代码只报WELL_FORMED，transformation_authorized及native signature/tree/state/relation证明标志保持false；未找到以Coverage.COMPLETE或类型相等提升权限的路径。CLI既有测试已阅读，本轮未另起CLI进程。 |

## 3. 原始反例与运行边界

- [probe.py](probe.py)、[results.json](results.json)：一次实际 IR 运行，四项控制/拒绝
  检查通过，一项明确REGRESSION；`torch_imported=false`。
- 最初直接运行脚本未带 repo PYTHONPATH，在任何 IR 执行前 import scar 失败。
  [results.initial.json](results.initial.json) 保留启动失败；只修正命令，没有改产品。
- 实际命令：

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python artifacts/experiments/b1_call_operands/model_native_interfaces/review/probe.py
```

结论仅适用于上述集成审查：**B1需修复及限定复审；没有发现第二个实质错接或
权限提升。** 不宣称 artifact真实性、P1全门、全程序模型或优化能力已通过。
