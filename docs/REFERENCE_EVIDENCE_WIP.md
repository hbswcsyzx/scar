# 引用证据工作存档：未通过验收

日期：2026-10-13。起点：已推送的规划提交 `2208b61`。

用户随后再次明确：首先定义完整程序图的节点与依赖语义，再用图和子图化简；
远期以声明的功能/语义组织执行。宏观代码审计发现，统一状态位置/状态版本、
程序目标边界以及供化简消费的计算—值连接尚未完成。引用采集切片不是这些
核心能力的前置，因此本草稿暂停扩展，单独存档，不作为 main 的已验收能力。

## 已实现但未整门验收

- source adapter：参数 READ occurrence、精确 code/source witness、原语结果到
  Return use；复用 correspondence 编译机制，仅覆盖实测 CPython 3.14 字节码。
- object reference adapter：固定对象引用 handle/materialization、多次 observation，
  无 Tensor 内容读取，无未来 live guard。修复元类 descriptor 分派、类名伪装和
  provenance producer/id 篡改漏检；采样热路径不反复扫描全部历史模型。
- 精确 result occurrence 查询：沿指定 consumer 和 observation 查 producer，
  不沿共享 True 的 ValueVersion 选择任意 producer。查询不认证原始证据真实性。
- 通用 fixture、外部测量驱动及集成测试已写出；**测量驱动尚未跑通**。

组件开发时分别记录：source/correspondence 41 tests、object/record codec
21 tests、occurrence query 18 tests 通过。这些是不同命令的局部结果，不能称为
mapped gate 或整仓回归。存档时的实际复查和未通过集成记录随分支归档。

在冻结提交 `0b90f38` 的存档复查中，上述组件合并执行为 **80 passed**。
唯一重跑的集成用例为 **1 failed**：暂停重写后的 collector 仍引用已从记录
enum 移除的 PROFILE_CALL，抛出 AttributeError。这是未完成迁移，不能包装成
有效采集器。没有重跑整仓测试。原始 XML 与实现版本见
`artifacts/reports/wip/reference-evidence-archive.json`。

## 实际失败与证据纠正

第一次集成测试 `test_real_calls_connect_exact_return_occurrences_to_existing_regions`
失败：目标两次实际返回 True，但 collector.calls 为空，无法建立两个有效样本。

后续 CPython 3.14.7 探针确认：安装 `sys.setprofile` 时，目标的 monitoring
PY_START/PY_RETURN 仍出现，INSTRUCTION 事件消失。只装 monitoring 才观察到
load/IS_OP/return 的完整指令序列。因此最初“profile + monitoring 已可共同提供
完整证据”的工作假设不成立；不能沿用为 Observed 正例。

命名 monitoring callback 内直接 `sys._getframe(1)` 的替代探针看到了实际目标
frame、入口绑定和返回 bool，但尚未集成为通过测试的 collector。完整命令和
输出在 [IDENTITY_EXECUTION.md](IDENTITY_EXECUTION.md)。原 collector 草稿仍不
可用于有效正样本；未新增其 unit suite。

另一个已修复的分析副作用：读取 Python 3.14 `function.__annotations__` 可以
触发用户设置的 lazy `__annotate__`。source adapter 现在不求值 annotation，
检测到 resolver 即拒绝；marker 反例已通过。

## 范围与恢复条件

无新 backend，无 OIR/REUSE outcome 改动，无目标源码改写。LeWM 仓库保持原状，
没有新 LeWM trace、变换或加速比。该分支也没有可报告的引用采集性能结果。

先完成核心程序图的节点、边、区域接口与简化验收。只有明确需要这类动态引用
证据时，才从本存档选择可复用组件；不把未完成代码自动并入核心设计。
