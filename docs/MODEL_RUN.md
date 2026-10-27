# 从已有采集自动组织建模

已有原生图的跨层关系可统一批量连接：

```bash
python -B -m scar.cli build-native-links \
  --pipeline NATIVE/manifest.json --pipeline-sha256 EXPECTED_PIPELINE_SHA256 \
  --navigation INPUT/port-navigation/manifest.json --navigation-sha256 EXPECTED_NAVIGATION_SHA256 \
  --resource-index RESOURCE/manifest.json --resource-sha256 EXPECTED_RESOURCE_INDEX_SHA256 \
  --work-manifest WORK/manifest.json --work-sha256 EXPECTED_WORK_SHA256 \
  --out fresh-native-links
```

默认处理源pipeline全部已发布片段；resource四个参数可一同省略。
一次metadata原记录扫描、一次活的native reader、可选同Run resource session，
逐片重核原source/ABI/core，写独立JSONL.gz关系片，根只保存引用/计数。
source-shard子集不会缩小原分母。没有重建native图、重跑workload或另造值版本。
`INPUT_METADATA`关系保旧状态及没有metadata leaf的路径；这些状态只回答Tensor
metadata观测，不把每个非Tensor输入误判为必须有Tensor metadata。`RESOURCE_WORK`
关系保原provider边与work/resource refs，多条路径到同work仍是一个物理work。
此批处理入口刚实现，完整批次的实际终态另行记录；不是全程序完成承诺。

原生操作边界现可直接从已发布的完整端口分片构建，不依赖 Python dispatch 标记：

```bash
python -B -m scar.cli build-native-interfaces \
  --ports-index PORTS/index.json --ports-sha256 EXPECTED_INDEX_SHA256 \
  --bundle BUNDLE/manifest.json \
  --coordinates capture-coordinates.json --coordinates-sha256 EXPECTED_COORDINATES_SHA256 \
  --out fresh-native-interfaces
```

默认处理索引的全部分片；可用 `--shard N` 做有界子集处理，但始终保留原完整分母。
共享一次接口目录，执行和来源关系分片独立保存；根 manifest 只保存引用和进度，
不是另一套 IR。缺 FunctionSchema 的 CPU 操作用 observed boxed interface 表示，
effects 保持 UNKNOWN；原输出来源与静态输出端口保留，未知完成不造 normal transfer。
普通完整 `model-run` 在 native-ports 后自动调用同一生产路径。
该接入代码已实现；这次实际执行的是上述公共命令的首个完整源分片，尚未实测
完整 `model-run` 的新阶段组合或全部原生操作。

真实首片 2,545 次操作、11,738 输入、1,753 条件输出，公共 CLI 17.393 秒；
仍有228,273次原生操作未处理。记录见
[结果](../artifacts/analysis/native_declaration_pipeline_20261027/RESULT.json)。
这只增加规范边界；metadata/物理分配接线、内容和状态等关系仍分别完成，不代表全图。

最新source-entry阶段默认自动选择已实现语法，无须逐个指定capability：

```bash
python -B -m scar.cli model-run --from-model-run DEPENDENCY_RUN/model-run.json \
  --stage source-entries --out fresh-entry-run
```

CLI默认`--source-entry-profile latest`，从公共registry选择当前V11。
原entry/catalog/readonly CodeWitness解析后，准确的own-function AST自动选择Try、
expanded-call、nested-function、import、flat With、独立generator创建及Set能力。
AugAssign自动启用已有FunctionTry/in-place协议；V7将固定解包结果接回既有heap/cell
store，不重复实现赋值协议。
V8选择原Lambda表达式Region与CodeWitness常量槽；Lambda defaults只在创建时求值，
body和captured cell读取在独立Region内表达。V9继续按AST选择单同步子句的eager推导式，
复用当前函数的CFG/SSA、原作用域slot及迭代/容器状态，不创建伪函数frame。V10继续
识别Tuple/List的starred display，复用有序构造/扩展与生命周期，和call参数展开分开。
V11按AST接属性/非slice下标AugAssign：只定位一次receiver/key，先读取左值，再计算右值，
连接in-place及原storeback，保normal/raise world与有序引用使用；真实属性入口131ops已正常
读回。Subscript实现未另实测，slice/private mangling仍保前沿。创建和
惰性body可以建模，不要求先证明未知C消费者的驱动次数。策略写入plan digest，每次实际选择记录
active capabilities；缺依据保原frontier。`legacy`与API默认None保留旧能力选择。
本阶段也自动导出`products.capture_plan`，可交给`trace --capture-plan URI
--capture-plan-sha256 SHA`。它只选择该dispatch window中的body，不是全程序计划；
只读CodeWitness派生，不导入workload/重新lower。导出缺口单独记录，不中止源恢复。
这还没有迁移纯source-only inventory的默认能力，也没有完成所有语法或自动发布/绑定。
一次真实import入口自动选择并普通读回148ops，12.086s、compile0，原SP5双SHA不变；
记录见`artifacts/analysis/source_entry_auto_profile_20261026/`。

同一source-entry命令增加`--shared-source-context`可发布共享上下文和独立body片段。
默认关闭；正常SP5与独立CodeWitness检查完成后才拆分，只移除本次新attempt的重复
SP5副本，旧输入不变。fragment保原decoded receipt及`#/program/graph`准确端点，
普通region查询可以直接读；旧CP2/SP5 admission尚未迁移到该transport，后续绑定
不能把fragment冒充SP5。此模式尚未减少原SP5生成/检查的成本。

实际两个原85/217-op body以1context+2body保存，stored3,303,841→1,764,854B，
decoded30,744,053→16,639,065B；正常共享session仅读取/检查context一次，24.355s。
主树普通region读取同一85-op片段0.223s，不重放context，完整性声明限core。
记录见`artifacts/experiments/source_entry_shared_context_20261026/`。
完整worker路径另以一个机械选出的原8-op entry实际通过：worker0.566s、正常
shared session读回0.169s、1context1body共20061B；原worker terminal和fragment端点
对应，旧case输入不变。见`source_entry_shared_worker_main_20261026/`。

`source-entry-bindings` 通用 CLI 现同时支持 project 与 dependency 的原 SP5。
2026-10-26 同一次 generic CPU 采集的后段实际退出 0：schema2 publication 包含
两个 project REVISE_GRAPH 和一个 dependency ADD_GRAPH；普通 qualified reader
查询三个原 body，v4 binder 在原 5groups/12calls 中关联 10body（project6、dependency4）、
1source、1unresolved。原 namespace、SourceDefinitionReference、SP5 URI 与项目
真实 fi/bi 保留；原 compiler witness 与 entry navigation origin 分列。
CP2 成本 UNKNOWN，publication/binding 不重 lower 或恢复 owner。
actual-formal/环境/state/return/control 及完整模型仍 OPEN，详见
[同 Run 实测与留存](../artifacts/experiments/project_dependency_publication_gate_20261025/REPORT.md)。

2026-10-25。P0通用离线入口已实现，真实八阶段串联通过；完整程序建模仍OPEN。
LeWM正式source858/runtime843的覆盖不受本次小CPU样例影响。

```bash
python -B -m scar.cli model-run --from-capture CAP --out RUN --plan-only
python -B -m scar.cli model-run --from-capture CAP --out RUN --resume --max-calls 512
```

在lewm conda环境使用本开发树时，先把`PYTHONPATH`设为该树路径。入口接受当前
支持的成功采集目录，使用原始声明中的命令、进程、项目边界和artifact来源。
它不执行采集命令，不导入workload，不接收业务函数名单。缺失的exec cwd、
命令入口、依赖或代码来源不会用分析进程的cwd猜补。

## 自动链路与输出

`--plan-only`读取有总预算的小metadata，不扫描原始trace或编译源程序。
普通模式依次调用既有capture importer、真实source coordinates、verified source
seeds、inventory8、source-layers、composition、fresh source bindings及workload
CodeWitness writer/readonly reader。工作单元和analysis seed由原记录机械确定。

lossless ETO及partitioned native bundle路径还自动生成native ports，随后调用同一
native-reference-flow producer生成分片引用导航，再调用native-operator-values自动
扫描原接口并保存紧凑派生声明；products保存三个index引用，不复制每个op的符号图。
这段bootstrap接线已实现；完整producer和公共查询已实际运行，新增整段bootstrap
未为此重复执行。原plain route保持其明确未生成状态，索引不建立内容版本或因果边。

每阶段生成独立目录和started/terminal收据；规范图保持原schema、命名空间及
artifact身份。小`model-run.json`保存导航和资格状态，没有新的可写图权威。
resume保留此前attempt并生成新attempt；P0会fresh replay整链，尚不复用完成阶段。
最新导航根可更新，原attempt及规范产物保持原字节。

此P0使用合法monolithic inventory bootstrap；已有分区路线仍保留。
`SourceFrontend`需要的原lowerer返回checkpoint handoff、partitioned report2/3，
以及native V2/统一覆盖账本接线仍OPEN，不能伪造检查点或前一运行报告。

## 实际门与边界

唯一已有CPU capture的首次G0实际exit2：43954B metadata、raw0，271次调用超过
默认256上限。显式512上限后，同一目录resume的G1实际exit0，八stage完成，
内部124.585290s；约26MB存储，主要耗时为native/OS导入。没有新capture/target/GPU运行。
原G0attempt和首次源码保留，360份当前工具源码的运行前后hash一致。

样例只有module顶层，源码清单1文件、0函数定义/0body，271次调用全部UNRESOLVED。
模块入口缺定义见证1次，另270次是CODE_SOURCE_INCOMPLETE：其中269次/7个Python
code groups的绝对源码位于recorded root之外而未准入，另1次是`<frozen os>`。
外部组包括Torch registry/overload、SCAR工具导入、pathlib及json；不是270次native
或module调用。下一步需自动依赖准入及明确tool/runtime namespace，保原271分母。
这只验证了通用串联及预算/恢复行为，不是完整源码依赖或模型验收。
workload archive单独完成1个compile key和readonly复核，不借用collector代码档。

预算分别报告：小metadata读取硬界、各公共API的raw参数、各stage完成后的record/
stored-output检查，以及外部wall限制。当前没有累计stored+decoded输入硬帽；
post-stage解压校验约999MB是输出校验成本，不是全部输入I/O测量。
超限保留失败和partial，`COMPONENTS_LINKED_WITH_OPEN`不授变换资格。

真实执行、预算与源码版本见
[根复核](../artifacts/experiments/model_run_offline_g1_20261025/ROOT_REVIEW.json)及
[实际结果与归因](../artifacts/experiments/model_run_offline_g1_20261025/RESULT.md)、
[接口和后续接线规划](../artifacts/analysis/model_run_orchestration_design_20261025/PLAN.md)。

## 独立依赖源码阶段

```bash
python -B -m scar.cli model-run --from-model-run RUN/model-run.json \
  --out SOURCE_RUN --stage dependency-sources
```

该入口核对导航和不可变terminal、原source-seeds/binding收据，再仅调用既有依赖准入
及新CodeWitness archive，不重做capture/native/OS/bootstrap。独立预算用
`--dependency-max-*`配置并逐字段记录来源，原bootstrap默认值保留。

真实门实际exit0/36.862007s：原9组/271调用守恒，4份snapshot/source graphs为6组/
265调用建立SOURCE_VERIFIED；新archive4compile keys/6descriptor matches，readonly
4loads/6matches、compile0。工具跨worktree4次和frozen1次未解析；project module1次
保留原scope。源码与编译匹配不是函数环境、actual/formal、状态或执行对应的证明。

该门结束时原G1绑定报告不修改，body-linked仍0；后继entry消费见下节。
正式body publication与新普通binding尚待接线。完整模型及LeWM正式覆盖数不变。
源图bulk按精确local receipts保留，未把全部86MB解码数据复制进导航root。
见[实际根复核](../artifacts/experiments/model_run_dependency_gate_20261025/ROOT_REVIEW.json)。

## 原定义entry、真实return与普通读回

同一CPU样例后继实际exit0/6.771874s：公共SourceEntryCatalog保留6候选及原9组/271调用，
按原调用权重自动选1entry，消费原source/context与readonly CodeWitness，正常sealed
lower返回28ops。相同返回已保存为SourceProgram5，普通STRUCTURE/source与独立code
reader均通过；readonly1load/2matches、compile0，source_prepare0，无raw/native/OS重做。
原260调用仅是所选定义的权重，不能增加runtime覆盖。正式静态858/runtime843不变。

live owned return只在该进程中有效，JSON不能恢复owner。后继可对原SP5 artifact做普通
独立准入，发布CP2未知成本，无需重复lower；publisher/binder及完整第一阶段仍OPEN。
见[实际结果](../artifacts/experiments/source_entry_catalog_gate_20261025/RESULT.md)。

后继CLI已实现`model-run --from-model-run <dependency terminal> --stage source-entries`，
真实门session48967 exit0/7.515233s，1entry/28ops及普通source/code读回通过。它固定
原terminal/admission/archive/source scope，并自动带入
原bootstrap的project composition与独立readonly archive。共同catalog保留全部9/271及
六dependency候选；module无definition明确保留前沿。仅复用现有catalog/plan/worker，
独立`--entry-max-*`默认窗口1entry/1file/4000ops；不重dependency/raw/native/OS，
不混入publication/binding，也不创建第二份图权威。
依赖archive实际1load/2matches/compile0，project archive0load/0match；两类原来源和
module无definition前沿均保留。project+admissions是同原9/271的来源联合，不是新增调用；
它与此前独立entry门分别保留实际producer/profile收据，不倒改历史。见
[CLI实际结果](../artifacts/experiments/model_run_source_entries_gate_20261025/RESULT.md)。

## 已存entry body的自动出版与调用关联

```bash
python -B -m scar.cli model-run --from-model-run SOURCE_ENTRY_TERMINAL \
  --stage source-entry-bindings --out BINDINGS --plan-only
python -B -m scar.cli model-run --from-model-run SOURCE_ENTRY_TERMINAL \
  --stage source-entry-bindings --out BINDINGS --resume
```

该独立阶段固定原SOURCE_ENTRIES immutable terminal、worker成功产物、dependency/
bootstrap输入与两readonly archive，机械取所有成功SP5。默认一个program；数量超限
明确BLOCKED，使用`--binding-max-programs`显式配置，不能截掉其它成功项。独立binding
profile不混用bootstrap/dependency/entry flags。plan-only仅有界小metadata及artifact
stat，不读graph/raw或编译。新source-entries输出精确worker terminal receipt；旧输入
只在所有保存program与原SUCCEEDED总数一致的无歧义情形接受，否则保留成功归属前沿。

实际模式复用既有publisher→ordinary qualified reader/query→fresh genuine coordinates
→v4普通binder，输入从原products自动取得，没有实验目录import或业务函数名单。
SP5 URI不变、CP2成本UNKNOWN，不lower/恢复owner/执行目标/重建native或OS模型。
默认4000ops/128MB source-provider decode，actual raw2MB/2048lines/1024events，坐标
64MB reservations；原seed metadata64MB等profile另列为解码上限，不授当前raw许可。
record64MB/output128MB是既有参数及post-stage检查，外部180s，全输入累计I/O仍OPEN。

resume新建attempt并保旧失败。输出只链接原SP5、规范publication/v4绑定和原project
composition，没有新图权威。schema1 保持 external-entry 合同；显式 schema2 计划
按原父 root/body/artifact/namespace 做 ADD/REVISE CAS，project 使用真实槽位，
dependency 保 qualified 来源。旧 compiler origin 不改名，entry origin 仅导航。
actual-formal/env/state/return/control及完整模型仍OPEN，旧SBA不因新v4自动取得资格。
实现范围与门见[短计划](../artifacts/analysis/model_run_source_entry_bindings_20261025/PLAN.md)。

真实CLI门session71666 exit0：1原成功SP5，独立出版→普通qualified查询→genuine坐标→
v4普通binder四阶段完成，无实验模块import、lower/compile/target/native或OS重建。
readonly依赖1load/2matches、project0；原9/271守恒，260body+5source+6unresolved，
271exits/0orphan。五类未连接接口仍各271，旧SBA2/3不放宽，858/843/6699不变。
这次历史门的旧成功归属仅1/1兼容，当时 project adapter 尚未实现；它不获得后续
schema2 的新资格。新 mixed 门实际覆盖 project REVISE 与 dependency ADD，尚未覆盖
project ADD、父 overlay 继承查询或 v5 参数路由。
详见[CLI实测与留存](../artifacts/experiments/model_run_source_entry_bindings_gate_20261025/RESULT.md)。

## 从已有发布图直接关联实际调用

多个增量已经合成一份source-entry publication时，可直接使用普通绑定入口：

```bash
python -B -m scar.cli bind-source-invocations \
  --source-publication PUBLICATION/manifest.json \
  --source-publication-sha256 MANIFEST_SHA256 \
  --capture ORIGINAL_CAPTURE --out fresh-bindings
```

入口从固定SHA的root取出原compiler archive receipts，只读打开archives，再调用既有
完整qualified reader与binder；没有业务函数名单、重新lower或新图格式。
`--composition INDEX`旧入口保留，两者互斥。`same_capture`仍要求原source seed和原采集
严格相符，不能把不同Run的同名函数或PID拼成一次执行。

`--max-source-programs`、`--max-source-operations`、`--max-source-record-bytes`及
`--max-source-decoded-bytes`控制已发布源码读取；原`--max-call-*`和capture坐标预算
继续约束原始调用/采集读取。`--max-source-context-seconds`是单file的共享source IO/
body验证上限，不能当作整个模型或前置catalog的总wall期限。超限报告失败，不截断函数或调用后报告完整。
该CLI接线已实现；完整LeWM实际读取/绑定结果须以相应运行报告为准。


## 按原 Tensor 观察查询物理存储

```bash
python -B -m scar.cli index-tensor-storage \
  --selection artifacts-selection.json --sha256 SELECTION_SHA256 \
  --out fresh-storage-index

python -B -m scar.cli query-tensor-storage \
  --index fresh-storage-index/manifest.json --sha256 INDEX_SHA256 \
  --source-fact original-object-storage-reference.json --out fresh-query.json
```

selection 只有 `bundle`、`capture_model`、`eto_source` 三份原始 artifact 收据，
每份含 `uri`、`sha256`、`size_bytes`、`schema`。ETO 收据指定原始命名空间，
此索引不重新读取 EO 原件。SourceFact 请求含 `artifact` 收据和原 `locator`，
必须指向同 bundle 的 OBJECT→USES_STORAGE→StorageRegion 边。
可以改用 `--region` 原 region ID；两个 selector 都省略时，机械选首个 CUDA
观察提示，再校验原始记录。请求仅是查询条件，不产生对象或内容同一性的证明。

索引只存原 ID、行号与 chunk 位置；查询按需读取并核对原对象、marker、descriptor、
view 和 allocation，不复制图记录、不保存 Tensor 内容。实际 LeWM CLI 查询通过，
局部查询约 1.00s、包含 Python 启动的命令约 2.56s。原引用索引一次构建约 73.73s，
压缩分片 7,363,611B + manifest 499,687B；构建 API 已实跑，新增构建 CLI 接线未另做
重复整批构建。见 [CLI 实际结果](../artifacts/analysis/tensor_storage_cli_20261026/RESULT.json)
和 [原索引报告](../artifacts/experiments/tensor_gpu_reference_query_20261026/REPORT.md)。

这些是原观察点的物理关系，不证明不同操作点之间内容未变、logical version、
持久驻留、Materialization 或 ready；source context 也不提升为 direct-call 关系。


## 进程范围的轻量调用与源码采集

`trace --capture-profile program-ports` 保留项目入口及其实际 Python 后代；
`trace --capture-profile process-ports` 使用独立 V2 合同，采集已安装 hook 的目标进程
Python 线程入口/退出与 CALL，排除采集器子树。两者均不开 INSTRUCTION，不保存
Tensor 内容。V2 透明转发真实 import/Torch 调用；进入未知/native 转发边界的首个
Python 调用不伪造直接 caller。probe/cleanup 触发的调用仍属于采集器。

V2 对已有帧没有补造 entry，不保证后起裸 native/_thread Python 线程，fork/exec
子进程 Python 也未采；这些范围在 metadata 明确保留，不能把 V2 标签当完整覆盖。
CPU V1 实际采集与 IO 读回已通过；V2 仅语法/导入/入口检查，待真实 LeWM 运行验证。
见 [原 CPU 结果](../artifacts/experiments/program_ports_cpu_20261027/REPORT.md)和
[V2 实现边界](../artifacts/analysis/program_ports_v2_20261027/REPORT.md)。

`CapturedSourceOwner` 正常核闭合 code/source 原件，再提供不可变归档文本；
`CodeWitnessStore.admit_captured_source` 不读 live 源文件，仍需普通编译与完整 descriptor
匹配。原归档永远只声明 `NOT_CHECKED`/非 loader-time 字节；新匹配见证独立保存。
owner 按原 call-meta 明确区分 V1/V2 并核 source metadata 的同一 profile，不能混用。
V1 的离线编译/只读读回已实测；V2 owner 适配尚待该版本的真实输入验证。
正常 `model-run` 已自动接入归档源码 owner：seed、discovery、inventory、source layers
共用同次 frame scan 和源码版本；归档缺失不会悄悄回读现场源码来补同次证据。
未捕获的静态文件另标 `CURRENT_STATIC_UNEXECUTED_SOURCE_VERSION`。一次真实 CPU
source bootstrap 已完成（2.898s、44 core operations、10 个现场源码 open=0），
它未运行 native 导入或 invocation binding，不能当作全链完成。
见 [实际报告](../artifacts/analysis/automatic_captured_source_20261027/REPORT.md)。

## 按需接通跨层源码端口

```bash
python -B -m scar.cli build-source-ports \
  --source-report BINDINGS/report.json --source-report-sha256 REPORT_SHA256 \
  --bindings BINDINGS/bindings.json --bindings-sha256 BINDINGS_SHA256 \
  --trace-root ORIGINAL_TRACE --max-selected-calls 8 --out fresh-ports.json.gz

python -B -m scar.cli query-source-dependencies \
  --model fresh-ports.json.gz --sha256 MODEL_SHA256 \
  --binding-index 0 --actual-index 0 --out fresh-dependencies.json
```

构建入口针对保留的 v4 source binding，读取同一采集的 attempt/handshake，
按需核对参与的原函数图及限定源码引用，不再要求重新读取全部发布 body，
也不从 JSON 恢复活动 proof owner。`--max-selected-calls` 是成功 binding 的上限；
选定批次与完整 trace 分母分开，不能把有限批次称为整个程序已连通。

导航复用原 body index 和端口 overlay，沿局部绑定 payload/read、CFG 参数、
实参/形参以及条件正常返回继续追溯，并列出返回结果的直接 consumer。
`--receiver` 可代替 `--actual-index`，独立追溯方法接收者投影；它不占显式参数下标，
也不把 callable 与 receiver 当作同一个引用。
跨分支的边保留条件；异常 completion 不接到正常 return。
任意计算、未知写入、缺失的调用绑定、resumable 输入以及预算终止均显式留下边界。
节点数、路径深度和关系数有独立上限。输入模型本身的读取仍受原 transport 预算约束。
这些是来源路径和依赖接口，不证明内容相等、具体分支选择、purity 或可移动性，
不授权 cache/hoist。真实 LeWM 选中三层链已接通两处调用，正常返回与粗粒度状态端口
查询通过；共享会话读取三个函数片段约 0.60 秒，未重读整批源码或原 trace。
当前仅连接 2/100,550 个调用尝试，仍有未绑定入口和方法查找边界。
见 [构建结果](../artifacts/analysis/source_call_bridge_20261027/REPORT.md)与
[导航及 CLI 实测](../artifacts/analysis/source_dependency_navigation_20261027/REPORT.md)。

## 分片连接与独立进程的依赖构建

```bash
python -B -m scar.cli build-source-port-shards \
  --source-report BINDINGS/report.json --source-report-sha256 REPORT_SHA256 \
  --bindings BINDINGS/bindings.json --bindings-sha256 BINDINGS_SHA256 \
  --max-candidate-pairs 512 --shard-calls 32 --out fresh-ports

python -B -m scar.cli build-source-dependencies \
  --publication fresh-ports/manifest.json --sha256 MANIFEST_SHA256 \
  --workers 4 --out fresh-dependencies
```

Session 只读一次原 trace，按原候选顺序分批；静态 Use/Value ID、源码与图定义可以复用，
动态 attempt、entry、receiver/arg0 和环境观察不能当静态数据缓存。每个模型片只引用原
函数图，不内嵌复制 body。构图进程接收路径、SHA、ordinal 和预算，独立读取闭合分片；
父进程不加载全部图或传递活动 owner。进程数、在途任务和输出字节均有上限，失败保留。

实际窗口检查 512/2,683 个直接调用候选，输出 449 个条件连接，15 个模型片共 416,923B。
原始 100,550 个 CALL attempts 分母保留；没有检查的 2,171 个直接候选与其他 CALL
分别保留。四个进程完成 15 片、2,077 项依赖查询，约 32.08s；未做同任务串行 A/B，
不能据此声称加速。派生 view 18.6MB gzip / 584.9MB expanded JSON，包含重复引用，
不能把它们称为紧凑核心图。原函数图与数据内容没有重复保存。

依赖导航可使用 `query-source-dependency-batch`；单输入查询用 `--include-computations`
继续经过操作输入。计算依赖、控制 guard、状态和 protocol 角色均保留；它们不意味着
同值、alias、纯函数或选定动态循环。旧 trace 中 106 个 normalized receiver 缺少运行时
defaults/target 状态，只能作为条件端点，不能提升为已观察的 bound receiver。
见 [分片构建](../artifacts/analysis/source_call_port_session_20261027/REPORT.md)、
[四进程实测](../artifacts/analysis/source_dependency_workers_20261027/REPORT.md)。

## 显式 OS 范围与归档

`trace --os-capture-root ROOT --os-profile program-interfaces --archive-workers 4`
观察程序资源接口，排除未列出的 OS 内部调用；`--os-profile all` 保留原全 syscall 选项。
接口模式请求 seccomp-bpf，实际启用和事件完整性仍未证明。Scope/argv/Run/归档校验
没有降低，也不能据未观察到 syscall 推断无副作用。归档在采集关闭后并行压缩与回读
核验；这已经实现，运行中的异步图构建尚未实现。见
[实际 provider 与归档报告](../artifacts/analysis/os_program_interfaces_20261027/REPORT.md)。
