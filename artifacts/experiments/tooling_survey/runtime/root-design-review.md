# Root 工具调研与集成设计：独立只读复审

2026-10-16。审查 `docs/TOOLING_SURVEY.md`、`docs/MODELING_INTEGRATION.md`，对照
本目录 CPU 实测、raw ET/Chrome、installed source 与对应 revision 官方源码。
未改共享文档、产品或测试，未重跑 runtime/LeWM/GPU 实验。

**结论：runtime 部分未发现阻断性问题，可接受为尚未实施的集成设计。**

核对结果：

- ETO schema、tuple 六槽、shape/stride/type 另列及原位写后 ID 不变，与实测一致；
  没有把 provider ID 当 LogicalVersion、永久 ObjectID 或 allocation epoch。
- 34 个正 rf_id 的 CPU 对应明确限定本次记录；0 ID、跨运行、重复/冲突、window
  对齐与 GPU 尚未验收的边界没有被抹掉。kernel/copy 连接仍要求实际关联字段与
  验证规则，没有用重叠时间、相同名称或 host 返回补造因果/ready。
- source/code 必须有 snapshot/compile witness；source span、FX metadata 和真实
  occurrence 的关系保留证据与缺口，没有宣称一次 EEG 能证明未走路径。
- 普通 Python/NumPy/文件状态、外部写和合同仍由规范状态/协议连接；ET 图没有
  被宣称整个程序语义，graph break 也没有当成合法删除边界。
- record_shapes 的引用/执行扰动、配置/窗口/预算及采样非证明均写明；不是声称
  metadata-only 无成本。额外捕获必须受控 replay，不偷跑 live forward。
- 外部图为不可变 provider evidence，canonical producer/ordered use/state 只保存
  一套规范事实；精化/冲突分开记录。适配器成功不向 planner 授权纯性或变换。
- ETO/FX/Export 未接入与 M1/M2 未完成、T2—T4 后续阶段的状态一致，没有把工具
  调研/小样例成功升级成全程序自动建模、自动化简或 LeWM 加速证据。

仅一项措辞收窄：TOOLING_SURVEY 表中的“本机无 nsys”应为“当前 PATH 未找到
nsys”；原检查只有 `command -v nsys`，未搜索全机。已通知 root，对设计无阻断。

本复审只覆盖 runtime 与跨层对应主张；不冒称本审查者已独立验证其他作者关于
LibCST/CodeQL/torchview/Export 的全部实验。本目录证据不证明 GPU 因果/复制、采集
开销比例或完整生命周期适配器；这些明确待后续验收。
