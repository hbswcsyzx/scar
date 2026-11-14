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

正式前端按层构建局部图，不运行目标程序：

```bash
scar frontend /path/to/source-root --out /path/to/frontend --jobs 8
scar build --entry /path/to/entry.py --catalog /path/to/frontend/catalog --cache-root /path/to/frontend --out /path/to/build
```

`frontend` 顺序执行源码→词法→AST→作用域/绑定→共享区域模板→局部接口→调用参数/返回接口；三类独立模板可并行。
每层检查原报告再推进，失败保留具体阶段。`local_declarations_complete` 只表示所选源码的局部声明图完成。
已有采集可追加 `--trace TRACE --project-root ORIGINAL_ROOT` 离线接线；随后 `build` 使用同一目录的观察接口。
已有F0–F3模型可用 `frontend ROOT --source-model MODEL --source FILE --out FRESH` 从F4继续；原source ID和分片保持，当前源字节先核对，F4仍执行收集与独立验证。
同一分析索引同时发布共享的类型/原生调用边界和独立观察表；有native companion时保原ABI字段，无companion时明确未记录。
边界可展开到实际Python回调的共享代码/body；普通入口与可挂起body分开，恢复位置和参数来源没有证据时保留未决字段。
编译器插入的生成器创建、类构造CALL单独接回原协议操作及其参数/状态/结果，不套普通函数ABI；共享正文不代表已证明实际激活或generator恢复实例。
可选 `scar trace --resumptions --project-root ROOT --out TRACE -- python app.py` 记录真实首次进入、恢复、yield 和最终完成，以同一激活连接原 InvocationID，不保存帧或 payload。
`scar source-resumptions --interfaces OBSERVED_FUNCTION_INTERFACES --metadata TRACE/resumption-meta.PID.json --out FRESH` 将边界接回原正文端口；委托驱动的继续执行不等于已完成规范化恢复，接线表尚待纳入统一 build。
动态生成的代码可用 `scar trace --compile-events --project-root ROOT --out TRACE -- python app.py` 保留限额内编译文本与执行代码指纹。
带此采集的 `frontend --trace TRACE --project-root ROOT` 会自动匹配兼容编译配方、生成局部F0–F4图并接回调用；只编译，不执行保存的文本。
同文件名的不同代码用完整CodeID区分，编译选项多解保留；原始编译请求、创建环境与参数值不由代码相等推出。
有trace时还会自动寻找外部文件及官方frozen源码，以完整CodeID验证后并行降低局部图；不导入目标模块。
最终catalog路径在frontend报告中；用 `scar build --entry ENTRY --trace TRACE --cache-root FRONTEND --out BUILD` 自动选取该目录及接口。

统一入口优先组合与入口源码匹配的 F4 catalog、调用/状态接口和资源材料；没有材料时建立源码、函数/循环子图和跨函数连接：

```bash
scar build --entry /path/to/entry.py --trace /path/to/trace --out /path/to/fresh-build --jobs 4
scar build --entry /path/to/entry.py --trace /path/to/trace --body-scope observed --target /path/to/target --out /path/to/fresh-build --jobs 8
scar build-query /path/to/fresh-build --action expand
scar build-query /path/to/fresh-build --action select --file model.py
scar build-query /path/to/fresh-build --action inputs
scar build-query /path/to/fresh-build --action resources
scar build-query /path/to/fresh-build --action dependencies --file model.py --entry forward --node program_value:ORIGINAL_ID
```

无 trace 时可省略 `--trace`。`--catalog` 选择 F4 局部声明或 context catalog，`--cache-root` 指定接口材料目录；
`--model` 显式选择旧 source model，`--source-root` 增加依赖源码根。
新源码构建的 `--body-scope observed` 根据完整运行 CodeID 选择正文，并自动准入 trace 涉及的外部源码文件；保留其余源码声明，不扫描整个依赖安装目录、不证明未观察路径为死代码。
该模式默认直接连接运行中的实际调用，跳过全局静态目标求解；`--call-binding static` 可显式恢复静态求解。
已有 source model 可用 `--model MODEL --call-binding observed` 接新 trace。`--target` 引用独立的硬件库存；库存、条件候选和实际资源使用分别保存。
`manifest.json` 引用原正文和关系分片；资源按原操作/区域延迟接线，观察依据独立保存。
入口源码树及显式依赖根的 YAML 自动进入现有配置材料解析器；不执行 tag、插值或 Hydra 组合。
`gaps.json` 保留局部缺口、跨层前沿、未接运行资源及查询截断。
`workflow_complete` 只表示构建/存储/读回流程通过，`first_stage_complete` 当前始终为 false。
候选 GPU、文件和 SSD/NVMe 关系带条件；它们不是实际 dispatch、存储身份或物理复制证据。

Python 中用 `BuildSession(build_path)` 共享一次查询会话的 catalog/代码/关系缓存。
`session.view` 提供原 `get/expand/producers/consumers/explain`。
`source_region_ref` 可先连接原声明的函数正文；`get/expand` 再读取和核验正文，循环与函数仍共享原 ID。
F4 构建的观察选择保留原 trace 与调用接口的 run scope，`attach_trace()` 返回已接入材料摘要；
静态调用 frame 不是动态 invocation。旧 model 构建继续通过 `observed_scopes/observed_ports` 查询独立观察调用域。

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

已有局部声明或 context catalog 后，可独立分析整个源树的调用声明，无需等待入口求解队列收敛：

```bash
python -B -m scar.cli call-declarations --catalog CONTEXT_CATALOG --source-root /path/to/program --out FRESH_CALLS --jobs 4
python -B -m scar.cli native-bindings --calls FRESH_CALLS --bindings GENERATED_BINDING_DECLARATIONS --out FRESH_BINDINGS --jobs 4
python -B -m scar.cli native-interfaces --named FRESH_BINDINGS --out FRESH_NATIVE --jobs 4
python -B -m scar.cli resource-graph --native FRESH_NATIVE --target TARGET_HARDWARE --out FRESH_RESOURCES
python -B -m scar.cli name-flow --declared FRESH_CALLS --unit SOURCE_UNIT --out FRESH_NAME_FLOW --jobs 4
```

每个源码单元独立存储。原调用、scope、参数和循环不复制；完整符号匹配保留所有候选overload。
声明图不代表scope已执行；参数类型、当前namespace、parser接受及实际dispatch仍需各自依据。
`name-flow`在共享控制流上计算词法槽位的may到达定义；新正常路径视图与原声明分开，未知效果保留。
资源图共享已有硬件库存，连接原生值的类型与源码依赖，不把设备候选当成实际placement。

## 文档

- [模型](docs/MODEL.md)：实体、身份、边、可展开结构与正确性约束。
- [流程](docs/ARCHITECTURE.md)：形式前端、建图流水线及动静分工。
- [开发用法](docs/DEVELOPMENT.md)：命令、查询接口和工作区约定。
- [当前状态](docs/STATUS.md)：真实结果、缺口与下一步。

当前CPU形式前端及建图证据在 `artifacts/current/experiments/cpu-*-current/formal/`，
精简验收摘要见 `artifacts/baseline/formal-frontend-results.json`；已有源码/查询材料仍共享原分片。
大产物不提交 Git，只保留一份正在开发的源码。

当前 CPU 主测试程序位于项目外、与 `le-wm` 同级：`sunfish`（一般程序）、`gray-scott`（PDE）、`cirq`（量子电路模拟）。
外部入口及命令、10 秒至 10 分钟的实测负载见 `artifacts/baseline/cpu-workloads.json`；测试程序的运行成功与完整建图验收分别报告。
