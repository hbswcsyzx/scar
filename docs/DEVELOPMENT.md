# 开发与用法

使用现有 `conda activate lewm`，只在 `~/AAA/scar` 的 `main` 开发。
不创建 worktree、日期版源码或历史实验副本；正常提交 Git，不 reset。
不修改外部 LeWM、数据/权重、CUDA/driver 或整套环境。删除实现前先查引用。

## 当前形式前端入口

```bash
python -B -m scar.cli source-bytes --file /path/to/program.py --out /path/to/fresh-material
python -B -m scar.cli source-bytes --model /path/to/model --out /path/to/fresh-f0 --jobs 4
python -B -m scar.cli source-bytes --model /path/to/model --out /path/to/fresh-check --verify
python -B -m scar.cli source-tokens --model /path/to/model --out /path/to/fresh-f1 --jobs 4
python -B -m scar.cli source-tokens --model /path/to/model --out /path/to/fresh-lexical-check --verify --jobs 4
python -B -m scar.cli source-syntax --model /path/to/model --out /path/to/fresh-f2 --jobs 8
python -B -m scar.cli source-syntax --model /path/to/model --out /path/to/fresh-syntax-check --verify --jobs 8
```

F0只保原始bytes与编码结果。解码失败仍存原bytes；文件不可用/预算停止准确报错，不给后层授权。
现有模型只追加每源raw/token分片；旧源码和IR保持。F1也可用`--file PATH`独立采集（先执行F0）。
`--max-tokens`是每源上限；verify按原工件预算重放，原预算超过本次上限则拒绝，不会静默忽略限制。
F1只转录词法，不证明语法有效；原生错误保prefix，预算停止不发布partial模型。
F2默认exec，也支持eval/single/func_type；--file先经过F0/F1，--max-nodes是每源AST上限。
源码始终只解析为AST；语法成功不证明作用域/控制合法。大literal超固定预算准确报frontier，不标UNKNOWN。
F0/F1/F2声明材料验收已通过，下一阶段是F3作用域与名字绑定，前层未验收不新增后层功能。
当前profile固定本机CPython及tokenizer源码/静态解释器二进制指纹；内置tokenizer的shared Python暂不接纳。

F3-A：

```bash
PYTHONHASHSEED=0 python -B -m scar.cli source-symbols --model /path/to/model --out /path/to/materials --collect-only --jobs 8
PYTHONHASHSEED=0 python -B -m scar.cli source-symbols --model /path/to/model --materials /path/to/materials --out /path/to/check --verify --jobs 8
```

固定seed只用于分析进程；实际hash上下文写入profile，worker不一致时拒绝。每源scope/symbol上限可配置，
F1/F2及原材料的replay预算也受本次上限约束。默认capture会向可写模型只追加source_symbols；
collect-only是独立材料store，fresh核验绑定必需源码收据。PUBLIC_COMPILER_VIEW/UNJOINED不授AST绑定或scope完整性。
当前/home只读时，命令前缀改为`python -B /var/tmp/scar-f2-recovery-7w7nd_0z/run_overlay.py`；
它只加载同一main的变更源码缓冲，不创建checkout。恢复写入后按RECOVERY.json同步，普通入口即可使用。

F3-B（只分类字段角色，不执行symtable或目标）：

```bash
python -B -m scar.cli source-roles --model /path/to/model --out /path/to/roles --collect-only --jobs 8
python -B -m scar.cli source-roles --model /path/to/model --materials /path/to/roles --out /path/to/check --verify --jobs 8
```

每store只保存一份`source_roles/catalog.json.gz`，每源为稀疏原槽ports和484条计数；
`--max-ports/--max-slots`限制本层，`--max-nodes/--max-tokens`同时约束上游重放。
默认capture向可写模型只追加source_roles；collect-only不改模型，verify重新计算角色与计数。
纯API以`read_source_syntax_material`取得验证后的不可变F2材料，用`SyntaxRoleView(material)`复用索引查询。

C1源码上下文（不求词法存储或建立真实frame）：

```bash
python -B -m scar.cli source-contexts --model /path/to/model --roles-materials /path/to/roles --out /path/to/contexts --collect-only --jobs 8
python -B -m scar.cli source-contexts --model /path/to/model --roles-materials /path/to/roles --materials /path/to/contexts --out /path/to/check --verify --jobs 8
```

外部B输入只允许只读采集/核验；B已注册model时可省`--roles-materials`并使用默认增量发布。
C1只存scope/region/private策略与稀疏原槽边界，catalog共享一份；同源F2/B各只fresh一次。
`SourceContextView(syntax, roles, contexts).resolve(slot)`或`.port_context(port)`复用父槽索引；不复制端口或逐槽context。
`--max-scopes/--max-regions/--max-boundaries`限制本层，`--max-slots`及其余输入预算同时约束重放。

C2a名字投影和整scope声明：

```bash
python -B -m scar.cli source-declarations --model /path/to/model --roles-materials /path/to/roles --contexts-materials /path/to/contexts --out /path/to/declarations --collect-only --jobs 8
python -B -m scar.cli source-declarations --model /path/to/model --roles-materials /path/to/roles --contexts-materials /path/to/contexts --materials /path/to/declarations --out /path/to/check --verify --jobs 8
```

外部B/C1输入只读、全收据固定；全部canonical时才允许默认append。每原B port一disposition，名字只intern一次。
`SourceDeclarationView(...).port/scope/contribution/name`查询原引用账本；`--max-names/--max-contributions/--max-conflicts`约束本层。
投影阶段固定`SYMBOL_VISIT_PROJECTION`；源码操作意图、visit flags、visibility和C1抑制分别保存，不授运行值或物理地址。

C2b条件化namespace接口与捕获（仍不授C3编译器投影）：

```bash
python -B -m scar.cli source-bindings --model /path/to/model --roles-materials /path/to/roles --contexts-materials /path/to/contexts --declarations-materials /path/to/declarations --out /path/to/bindings --collect-only --jobs 8
python -B -m scar.cli source-bindings --model /path/to/model --roles-materials /path/to/roles --contexts-materials /path/to/contexts --declarations-materials /path/to/declarations --materials /path/to/bindings --out /path/to/check --verify --jobs 8
```

三个上游store固定原收据；全部canonical时才允许默认append。每store一catalog、每源一类型化绑定分片。
`SourceBindingView(roles, contexts, declarations, material).port/scope/binding/interface/plan/capture/relay`查询原引用，`.verify()`核引用与逆边。
八项本层预算超限不发布部分表；源码冲突保端口与原因。namespace为源码模板，未观察运行字典、物理cell或地址。

C3-T编译器拓扑（需要固定分析进程hash上下文；不运行目标）：

```bash
PYTHONHASHSEED=0 python -B -m scar.cli compiler-topology --model /path/to/model --roles-materials /path/to/roles --contexts-materials /path/to/contexts --symbols-materials /path/to/symbols --out /path/to/topology --collect-only --jobs 8
PYTHONHASHSEED=0 python -B -m scar.cli compiler-topology --model /path/to/model --roles-materials /path/to/roles --contexts-materials /path/to/contexts --symbols-materials /path/to/symbols --materials /path/to/topology --out /path/to/check --verify --jobs 8
```

`CompilerTopologyView(roles, contexts, native, material)`查询`.scope/.region/.block`，传原SourceContextView后可查询`.port`。
模板保原construction parent/children；PUBLIC引用原F3-A行，INLINED/FUTURE_DETACHED保模板和规则，不伪造公开行。
`--max-blocks/--max-rewrites/--max-visit-steps`约束本层；只验拓扑与scope元数据，符号来源/参数仍未投影。

C3-S符号来源与参数投影：

```bash
PYTHONHASHSEED=0 python -B -m scar.cli compiler-symbols --model /path/to/model --roles-materials /path/to/roles --contexts-materials /path/to/contexts --declarations-materials /path/to/declarations --symbols-materials /path/to/symbols --topology-materials /path/to/topology --out /path/to/compiler-symbols --collect-only --jobs 16
PYTHONHASHSEED=0 python -B -m scar.cli compiler-symbols --model /path/to/model --roles-materials /path/to/roles --contexts-materials /path/to/contexts --declarations-materials /path/to/declarations --symbols-materials /path/to/symbols --topology-materials /path/to/topology --materials /path/to/compiler-symbols --out /path/to/check --verify --jobs 16
```

`CompilerSymbolView(declarations, topology, native, material)`查询slot/fact/source/port/symbol/parameter，`.why(scope,ordinal)`返回有界来源引用。
source slot、compiler slot与native行分域；scope code不是低位flag；varnames只是有序参数，不冒充runtime locals布局。
五项独立本层预算与原D.max_contributions分开；超限不发布部分来源表，外部五store均固定原收据。

## 已有建图入口（前端形式验收尚未完成）

```bash
python -B -m scar.cli static /path/to/program --out /path/to/model --phase bodies --jobs 4
python -B -m scar.cli static /path/to/program --out /path/to/model --expand --jobs 4
python -B -m scar.cli static /path/to/program --out /path/to/model --link-calls --max-call-bodies 80
```

`--phase sources/graph` 为材料目录/源码图，`--phase bodies` 继续构建规范主体；
`--expand` 增量补主体。显式预算仅限本次工作，不缩小完整性分母。
依赖材料可用 `--inventory-dependencies --dependency-root PATH` 定位，
再用 `--expand-dependencies` 送回同一前端；这些命令均不执行目标。

## 动态采集及离线连接

```bash
python -B -m scar.cli trace --calls-only \
  --capture-plan /path/to/plan.json --capture-plan-sha256 PLAN_SHA256 \
  --capture-transport snapshot --project-root /path/to/program-root \
  --out /path/to/fresh-trace -- python /path/to/program.py
python -B -m scar.cli observed-calls --model /path/to/model \
  --trace /path/to/fresh-trace --out /path/to/fresh-bindings --expand-missing
python -B -m scar.cli observed-graph --model /path/to/model --expand-missing \
  --trace /path/to/fresh-trace --out /path/to/fresh-observed-graph
```

采集计划由 `scar.trace.lean_capture.LeanCapturePlan` 对原源码/代码身份生成；具体接口以源码为准。
采集不额外执行用户 repr、descriptor 或 hook 来探测对象，不保存每次 Tensor 的完整数值。
优先复用已保存 trace；`observed-calls` 只离线连接，缺主体按完整代码身份请求原前端补建。
`--expand-missing` 先核完整Code/profile及已有plan文件指纹；无历史指纹时可补当前源码候选，
再按匹配Code作用域补body并fresh接线，不将父模块/环境认作历史事实；
不执行源码、不猜import名，旧分片保留但覆盖仍限旧basis。文件/字节预算用`--max-source-files/bytes`。
已有graph=None诊断按当前静态规则判是否可重试；成功补建保留旧收据，已有规范图不覆盖。
尚缺static adapter时明确报告形状/入口需求，不能把artifact文件当已建图。
采集仍含 frame profile hooks，不能宣称零干扰；性能测量与建图采集分开。
需要实际 callable 类型/owner/ABI 时加 `trace --native-callables`：仅在新 trace 内隔离编译小 C probe，
不安装环境依赖；当前限 CPython 3.14.7/GIL/Linux x86-64，不执行用户 getter 或读取 Tensor 数值。

## 共享图查询

```python
from scar.analysis.program_dependency_session import ProgramDependencySession

with ProgramDependencySession('/path/to/model') as session:
    ns, = session.select_bodies(file='program.py', entry='function_name', kind='FUNCTION')
    body = session.load(ns)                 # 原共享函数图及 index
    loops = session.loop_constructs(ns)     # 原成员 ID、嵌套、初始/回边端口
    if loops:
        operations = loops[0].expand(session.graph())
        boundary = session.loop_boundary(ns, loops[0])
```

不存在的 structured/主体信息保留准确缺口，不当成空子图。`ProgramDependencyBudget`
控制时间、输入、缓存和关系读取；边界查询完成仍须检查前沿和字段覆盖。
CLI 的 `static-query --program-graph` 使用原 typed ID，不按名称制造依赖。
动态接口用 `session.attach_observations(trace)` 接入，再由 `session.graph().observed_incoming/outgoing(port)`
查询；作用域与端口由返回的provider提供。原trace重验后才授边，DTO读回不是证明。
`graph.observed_layouts(scope)` 返回条件ABI布局；v2显式保存布局，v1读回为NOT_RECORDED而非空布局。
`graph.observed_native_callables(scope)` 查询附着原 CALL/Use 的实际类型、owner、self、flags 和地址事实；
未对应静态 CALL 的记录保留 frontier。导出为v3，v1/v2的这些字段读回为None=NOT_RECORDED。
类型名称只是描述标签，地址只适用该进程事件；它们不单独证明源码实现、kernel、copy 或效果。
有native采集时，`observed-graph` 自动生成共享协议分片并导出v4；`--native-protocols DIR` 重放已有分片。
API以 `provider.build_native_protocols(fresh_dir)` 生成、`attach_native_protocols(dir)` 核验接入；
`provider.native_protocols` 返回可展开的原canonical模板。协议输入/声明出口没有实际Invocation，witness仅为原CALL。
旧v1/v2/v3读回的协议字段为None；异常引用包未适配时仍保已知world，不把整个出口丢掉。

## 维护

当前任务及验收结果只更新 [STATUS](STATUS.md)，结构变化更新 [MODEL](MODEL.md) 或
[ARCHITECTURE](ARCHITECTURE.md)；不新增专题、版本或 gate 文档。
先定位缺失的识别事实、端口、连接或推理规则，再修改负责层；只运行相关检查。
生成图仅发布到 `artifacts/current/static/`，查询只引用原 ID/收据，不另建权威程序。
