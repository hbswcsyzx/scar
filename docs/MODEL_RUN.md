# 从已有采集自动组织建模

最新source-entry阶段默认自动选择已实现语法，无须逐个指定capability：

```bash
python -B -m scar.cli model-run --from-model-run DEPENDENCY_RUN/model-run.json \
  --stage source-entries --out fresh-entry-run
```

CLI默认`--source-entry-profile latest`，从公共registry选择当前V6。
原entry/catalog/readonly CodeWitness解析后，准确的own-function AST自动选择Try、
expanded-call、nested-function、import、flat With、独立generator创建及Set能力。
AugAssign自动启用已有FunctionTry/in-place协议，不新增重复实现。创建和
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
