# SCAR

State · Control · Action · Resource：面向Python程序的宏观编译器。

目标流程：**统一程序/资源图 → 结构与硬件感知化简 → C++20宿主执行代码**。
算子实现通过版本化接口接入官方高性能库或外部算子生成agent，支持单算子、通信及融合区域。
当前只开发第一阶段，静态优先；软件边界到算子接口，不展开kernel内部。
已具备共享控制/数据/状态图、跨函数与容器传播及生成式算子接口接线；仍需补完整资源映射和外部接口。
第一阶段尚未完成，不启用目标程序变换，也没有LeWM加速比结论。
LeWM 是外部 testcase；通用规则不按业务名称选择处理方式。
后端基线为C++20、算子ABI v1、执行计划schema v1，配置见`pyproject.toml`。

## 使用

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate lewm
cd ~/AAA/scar
python -B -m scar.cli static /path/to/program --out /path/to/model --phase bodies --jobs 4
```

静态入口不导入或运行目标。按需 CALL 采集和离线连接用法见开发说明。
已有函数/循环展开、跨分片依赖查询、有限属性推理；存在节点不代表依赖或效果已闭合。

已有 F4 图与 facts6 后，先按单元并行投影接口，再跨单元接线：

```bash
python -B -m scar.analysis.source_interface_build --facts /path/to/facts --out /path/to/interfaces --jobs 48
python -B -m scar.analysis.normal_targets --facts /path/to/facts --interfaces /path/to/interfaces --entry /path/to/entry.py --out /path/to/targets
```

摘要沿用原函数/循环/状态端口；不导入目标，也不按调用或迭代展开正文。

已有 context catalog 后，可独立分析整个源树的调用声明，无需等待入口求解队列收敛：

```bash
python -B -m scar.analysis.source_declared_calls --catalog CONTEXT_CATALOG --source-root /path/to/program --out FRESH_CALLS --jobs 4
python -B -m scar.analysis.source_named_bindings --calls FRESH_CALLS --bindings GENERATED_BINDING_DECLARATIONS --out FRESH_BINDINGS --jobs 4
```

每个源码单元独立存储。原调用、scope、参数和循环不复制；完整符号匹配保留所有候选overload。
声明图不代表scope已执行；参数类型、当前namespace、parser接受及实际dispatch仍需各自依据。

## 文档

- [模型](docs/MODEL.md)：实体、身份、边、可展开结构与正确性约束。
- [流程](docs/ARCHITECTURE.md)：形式前端、建图流水线及动静分工。
- [开发用法](docs/DEVELOPMENT.md)：命令、查询接口和工作区约定。
- [当前状态](docs/STATUS.md)：真实结果、缺口与下一步。

当前权威图在 `artifacts/current/static/`；原 trace 与派生查询证据在
`artifacts/current/queries/`。大产物不提交 Git，只保留一份正在开发的源码。
